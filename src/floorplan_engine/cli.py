"""CLI: check / build / estimate / preview / render-artifact / analyze / pdf-facts / serve / view /
symbols."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from floorplan_engine.drawing.symbols import export_symbols
from floorplan_engine.epd.artifact import read_artifact, render_page_png
from floorplan_engine.model.schema import SheetFormat
from floorplan_engine.pipeline import (
    ARTIFACT_FILE,
    OUT_DIR,
    PROJECT_FILE,
    AuditError,
    assess_project,
    build_project,
    estimate_project,
    print_project,
    render_sheets,
)
from floorplan_engine.sheets.document import sheet_png_name
from floorplan_engine.validation.assess import STATUS_TEXT, StageResult
from floorplan_engine.validation.issues import Severity
from floorplan_engine.validation.report import STAGE_TEXT
from floorplan_engine.validation.validate import Report

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.orm import Session

    from floorplan_engine.service.api.auth import Auth
    from floorplan_engine.service.db.models import Project, Studio

app = typer.Typer(
    help="Чертежи DXF (план, электрика) из room.yaml / electrical.yaml.",
    no_args_is_help=True,
    add_completion=False,
)

ProjectArg = Annotated[
    Path,
    typer.Argument(exists=True, file_okay=False, dir_okay=True, help="Папка проекта"),
]

ARTIFACT_PREVIEW_DIR = "artifact"
AnalyzerOpt = Annotated[
    str, typer.Option(help="manual — оператор; claude-code — подписка; api — ANTHROPIC_API_KEY")
]
ModelOpt = Annotated[str, typer.Option(help="Модель Claude")]
EffortOpt = Annotated[str, typer.Option(help="low | medium | high | xhigh | max")]
ElectricalModelOpt = Annotated[
    str | None, typer.Option(help="Модель электрики — отдельным шагом после плана")
]


# Service commands read .env (Google login, database, API key); build and check do not: they
# need no environment, and CLI tests must not pick up someone else's .env
ENV_COMMANDS = frozenset({"serve", "view", "dev", "analyze", "access", "project", "studio"})


@app.callback()
def main(ctx: typer.Context) -> None:
    """floorplan-engine."""
    if ctx.invoked_subcommand in ENV_COMMANDS:
        load_env(Path(".env"))


def load_env(path: Path) -> None:
    """Load variables from .env into the environment (login, database: see .env.example): KEY=VALUE,
    # starts a comment, quotes around a value are stripped. Existing environment values are kept."""
    if not path.is_file():
        return
    for raw in path.read_text("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.removeprefix("export ").split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()  # trailing comment
        if key and key not in os.environ:
            os.environ[key] = value


def print_report(report: Report) -> None:
    for issue in report.issues:
        color = typer.colors.RED if issue.severity is Severity.ERROR else typer.colors.YELLOW
        typer.secho(str(issue), fg=color)
    if report.plan is not None:
        for room in report.plan.rooms:
            contour = report.contours.get(room.id)
            if contour is None:
                continue
            if contour.is_closed():
                state = (
                    f"контур замкнут, площадь {contour.area_m2:.2f} м², "
                    f"периметр {contour.perimeter / 1000:.2f} м"
                )
            else:
                state = "контур НЕ замкнут, площадь не считается"
            typer.echo(f"  {room.id} «{room.name}»: {len(room.walls)} стен, {state}")
    if report.electrical is not None:
        e = report.electrical
        typer.echo(
            f"  электрика: {len(e.points)} точек, {len(e.cables)} трасс, "
            f"щит {'есть' if e.board else 'нет'}"
        )
    if report.plumbing is not None:
        w = report.plumbing
        typer.echo(
            f"  сантехника: {len(w.fixtures)} приборов, {len(w.risers)} стояков, "
            f"препятствий {len(w.obstacles)}, разводка {w.distribution}"
        )
    n_err, n_warn = len(report.errors), len(report.warnings)
    if report.ok:
        typer.secho(f"OK: ошибок нет, предупреждений {n_warn}", fg=typer.colors.GREEN)
    else:
        typer.secho(f"Ошибок: {n_err}, предупреждений: {n_warn}", fg=typer.colors.RED)


def print_stages(results: list[StageResult]) -> None:
    typer.echo("Этапы:")
    for r in results:
        color = typer.colors.GREEN if r.status.builds else typer.colors.YELLOW
        reason = f" — {r.reason}" if r.reason else ""
        questions = f", открытых вопросов {len(r.open_questions)}" if r.open_questions else ""
        typer.secho(
            f"  {STAGE_TEXT[r.stage.value]}: {STATUS_TEXT[r.status]}{reason}{questions}", fg=color
        )


@app.command()
def check(project: ProjectArg) -> None:
    """Проверить проект без отрисовки: ошибки данных и статус каждого этапа."""
    assessment = assess_project(project)
    print_report(assessment.report)
    print_stages(assessment.stages)
    if not assessment.report.ok:
        raise typer.Exit(code=1)


@app.command()
def build(
    project: ProjectArg,
    png: Annotated[bool, typer.Option("--png", help="Ещё PNG листов из DXF в out/sheets/")] = False,
) -> None:
    """Проверить проект, записать отчёт и собрать out/project.dxf из этапов, которые можно
    строить: модель и лист на каждый этап, плюс артефакт .epd для просмотра. PNG для проверки —
    render-artifact (из .epd, как в просмотрщике)."""
    try:
        result = build_project(project, previews=png)
    except AuditError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=2) from exc
    print_report(result.assessment.report)
    print_stages(result.assessment.stages)
    for path in result.report_files:
        typer.echo(f"  {path}")
    if not result.built:
        typer.secho("Сборка остановлена: план нельзя построить — см. отчёт.", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    assert result.dxf is not None and result.artifact is not None
    for issue in result.price_issues:
        typer.secho(
            f"  {issue.file}: {issue.path}: {issue.message} — смета на листе без цен",
            fg=typer.colors.YELLOW,
        )
    typer.echo(f"  {result.dxf} — аудит без ошибок")
    typer.echo(f"  {result.artifact} — {result.artifact.stat().st_size // 1024} КБ")
    if result.journal is not None:
        typer.echo(f"  {result.journal} — кабельный журнал (проводка через коробки)")
    if result.chases is not None:
        typer.echo(f"  {result.chases} — ведомость штроб")
    if result.loads is not None:
        typer.echo(f"  {result.loads} — роспись потребителей щита")
    if result.estimate:
        typer.echo(f"  {result.estimate[-1]} — смета (и .md, .csv рядом)")
    if result.plumbing_estimate:
        typer.echo(f"  {result.plumbing_estimate[-1]} — смета сантехники (и .md, .csv рядом)")
    if result.sewer_routes is not None:
        typer.echo(f"  {result.sewer_routes} — трассы канализации (участки, зоны, высоты, ошибки)")
    for sheet_png in result.sheets:
        typer.echo(f"  {sheet_png}")


@app.command("print")
def print_album(
    project: ProjectArg,
    paper: Annotated[
        str,
        typer.Option(
            "--paper",
            help="Формат комплекта: auto — как при build, или A4 / A3 / A2 / A1 / A0 "
            "(листы раскладываются заново, масштаб подбирается под формат)",
        ),
    ] = "auto",
) -> None:
    """PDF-альбом листов в натуральную величину: страница — формат листа, печать «в размер»
    даёт масштаб чертежа. Проверяет самый мелкий текст и выход за рамку."""
    formats: tuple[SheetFormat, ...] = ("auto", "A4", "A3", "A2", "A1", "A0")
    fmt = next((f for f in formats if f.lower() == paper.lower()), None)
    if fmt is None:
        typer.secho(f"Формат «{paper}»: нужен один из {', '.join(formats)}", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    try:
        result = print_project(project, fmt)
    except AuditError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=2) from exc
    for issue in result.issues:
        typer.secho(f"  {issue.file}: {issue.message}", fg=typer.colors.YELLOW)
    if result.pdf is None:
        raise typer.Exit(code=1)
    typer.echo(f"Формат {result.paper}, масштаб 1:{result.scale:g}, листов: {len(result.checks)}")
    for check in result.checks:
        text = f"{check.min_text:.1f} мм" if check.min_text is not None else "—"
        typer.echo(f"  {check.tab}: мелкий текст {text}")
    for warning in result.warnings:
        typer.secho(f"  [внимание] {warning}", fg=typer.colors.YELLOW)
    if result.dxf is not None:
        typer.echo(f"  {result.dxf} — DXF под формат {result.paper}")
    typer.echo(f"  {result.pdf}")


@app.command()
def preview(project: ProjectArg) -> None:
    """PNG листов уже собранного out/project.dxf без перегенерации."""
    out = project / OUT_DIR
    sheets = render_sheets(out)
    for png in sheets:
        typer.echo(f"  {png}")
    if not sheets:
        typer.secho(f"Нет {out / PROJECT_FILE} — сначала build.", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@app.command("render-artifact")
def render_artifact(project: ProjectArg) -> None:
    """PNG страниц из out/project.epd — так, как их построит кабинет (без DXF)."""
    out = project / OUT_DIR
    epd = out / ARTIFACT_FILE
    if not epd.exists():
        typer.secho(f"Нет {epd} — сначала build.", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    target = out / ARTIFACT_PREVIEW_DIR
    for old in target.glob("*.png"):
        old.unlink()
    _, pages = read_artifact(epd)
    for page in pages:
        png = render_page_png(page, target / sheet_png_name(page["name"]))
        typer.echo(f"  {png} — «{page['name']}», примитивов {len(page['items'])}")


@app.command()
def serve(
    data: Annotated[Path, typer.Option(help="Папка проектов сервиса")] = Path("data/projects"),
    host: Annotated[str, typer.Option(help="Адрес")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Порт")] = 8000,
    analyzer: AnalyzerOpt = "manual",
    model: ModelOpt = "claude-opus-5-5",
    effort: EffortOpt = "medium",
    electrical_model: ElectricalModelOpt = None,
) -> None:
    """Запустить API сервиса (документация — http://host:port/docs)."""
    # Service dependencies (group service) are needed only by this command
    import uvicorn

    from floorplan_engine.service.analysis.llm_analyzer import make_analyzer
    from floorplan_engine.service.api.app import create_app

    app_ = create_app(data, make_analyzer(analyzer, model, effort, electrical_model))
    uvicorn.run(app_, host=host, port=port)


@app.command()
def estimate(
    project: ProjectArg,
    prices: Annotated[
        Path | None,
        typer.Option(help="Прайс (по умолчанию — prices.yaml проекта, иначе общий прайс студии)"),
    ] = None,
) -> None:
    """Смета электрики таблицей (без чертежа): out/estimate.md, .csv и .xlsx (Excel с формулами)."""
    result = estimate_project(project, prices)
    if result.prices is not None:
        typer.echo(f"Цены: {result.prices}")
    if result.estimate is not None and result.estimate.from_service:
        typer.echo(f"Сервис цен (имитация): {result.estimate.from_service} поз.")
    for issue in result.issues:
        typer.secho(str(issue), fg=typer.colors.RED)
    if result.estimate is None:
        raise typer.Exit(code=1)
    est = result.estimate
    cur = est.currency
    typer.echo(f"Материалы:        {est.subtotal('material'):,.0f} {cur}".replace(",", " "))
    typer.echo(f"Черновые работы:  {est.subtotal('rough'):,.0f} {cur}".replace(",", " "))
    typer.echo(f"Чистовые работы:  {est.subtotal('finish'):,.0f} {cur}".replace(",", " "))
    typer.echo(f"Всего:            {est.total:,.0f} {cur}".replace(",", " "))
    if est.unpriced:
        typer.secho(f"Без цены: {est.unpriced} поз. — в итог не входят", fg=typer.colors.YELLOW)
    for path in result.files:
        typer.echo(f"  {path}")


@app.command()
def view(
    projects: Annotated[Path, typer.Option(help="Папка собранных проектов")] = Path("projects"),
    host: Annotated[str, typer.Option(help="Адрес")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Порт")] = 8000,
) -> None:
    """API просмотра собранных проектов (http://host:port/api); страница — проект web/
    (`cd web && npm run dev`), она ходит в этот API через прокси."""
    import uvicorn

    from floorplan_engine.service.api.viewer import FRONT_HINT, create_viewer

    if not projects.is_dir():
        typer.echo(f"Папки {projects} нет", err=True)
        raise typer.Exit(1)
    typer.echo(f"API просмотра: http://{host}:{port}/api; {FRONT_HINT}")
    uvicorn.run(create_viewer(projects, _viewer_auth()), host=host, port=port)


DEV_PROJECTS_ENV = "SHTROBA_DEV_PROJECTS"  # projects folder for the `dev` API (survives restarts)


def dev_viewer() -> FastAPI:
    """API app for `dev`: uvicorn calls the factory again after every code-change restart; the
    projects folder comes from the environment."""
    from floorplan_engine.service.api.viewer import create_viewer

    return create_viewer(Path(os.environ.get(DEV_PROJECTS_ENV, "projects")), _viewer_auth())


@app.command()
def dev(
    projects: Annotated[Path, typer.Option(help="Папка собранных проектов")] = Path("projects"),
    port: Annotated[int, typer.Option(help="Порт API")] = 8000,
    web: Annotated[Path, typer.Option(help="Папка фронта")] = Path("web"),
) -> None:
    """Просмотр одной командой для разработки: API (`view`) и страница web/ (`npm run dev`,
    http://127.0.0.1:5173). Оба перезагружаются при правках: страница — Vite, API — uvicorn
    следит за кодом пакета и перезапускается сам (иначе после правок Python пересборки шли бы
    старым кодом). Ctrl+C останавливает оба."""
    import os
    import shutil
    import subprocess

    import uvicorn

    if not projects.is_dir() or not (web / "package.json").is_file():
        typer.echo(
            f"Нет папки {projects} или {web}/package.json — запускайте из корня репозитория",
            err=True,
        )
        raise typer.Exit(1)
    npm = shutil.which("npm")
    if npm is None:
        typer.echo("Нет npm — поставьте Node.js 22", err=True)
        raise typer.Exit(1)
    if not (web / "node_modules").is_dir():
        subprocess.run([npm, "install"], cwd=web, check=True)
    env = {**os.environ, "API_URL": f"http://127.0.0.1:{port}"}
    front = subprocess.Popen([npm, "run", "dev"], cwd=web, env=env)
    typer.echo(f"Страница: http://127.0.0.1:5173 · API: http://127.0.0.1:{port}/api")
    os.environ[DEV_PROJECTS_ENV] = str(projects.resolve())  # read by the API factory
    try:
        uvicorn.run(
            "floorplan_engine.cli:dev_viewer",
            factory=True,
            host="127.0.0.1",
            port=port,
            reload=True,
            reload_dirs=[str(Path(__file__).resolve().parent)],
        )
    finally:
        front.terminate()
        try:
            front.wait(timeout=5)
        except subprocess.TimeoutExpired:
            front.kill()


@app.command()
def analyze(
    project: ProjectArg,
    analyzer: AnalyzerOpt = "claude-code",
    model: ModelOpt = "claude-opus-5-5",
    effort: EffortOpt = "medium",
    electrical_model: ElectricalModelOpt = None,
    round_no: Annotated[int, typer.Option("--round", help="Номер раунда")] = 1,
) -> None:
    """LLM-анализ папки проекта: source/ → intake.yaml и YAML этапов (затем — build)."""
    from floorplan_engine.service.analysis.llm_analyzer import AnalyzerError, make_analyzer

    try:
        result = make_analyzer(analyzer, model, effort, electrical_model).analyze(project, round_no)
    except AnalyzerError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    typer.echo(result.message)
    typer.echo(f"  вызовов LLM: {result.calls}, стоимость ≈ ${result.cost_usd:.2f}")
    assessment = assess_project(project)
    print_report(assessment.report)
    print_stages(assessment.stages)


@app.command("pdf-facts")
def pdf_facts(
    pdf: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, help="Векторный PDF источника")
    ],
    as_json: Annotated[bool, typer.Option("--json", help="JSON вместо Markdown")] = False,
) -> None:
    """Выжимка из PDF без LLM: масштаб листа, размеры, цепочки, надписи с координатами."""
    from floorplan_engine.service.analysis.pdf_facts import describe, describe_json

    typer.echo(describe_json(pdf) if as_json else describe(pdf))


@app.command()
def facts(
    source: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, help="PDF или картинка источника")
    ],
    as_json: Annotated[bool, typer.Option("--json", help="JSON вместо Markdown")] = False,
) -> None:
    """Выжимка из любого источника без LLM: вектор или растр — по каждой странице сам."""
    import json

    from floorplan_engine.service.facts.analysis import page_facts, render, to_dict
    from floorplan_engine.service.facts.source import read_source

    pages = [page_facts(s) for s in read_source(source)]
    if as_json:
        typer.echo(json.dumps([to_dict(f) for f in pages], ensure_ascii=False, indent=1))
    else:
        typer.echo(render(pages))


@app.command("facts-bench")
def facts_bench(
    pdfs: Annotated[list[Path], typer.Argument(exists=True, dir_okay=False, help="Векторные PDF")],
) -> None:
    """Точность растра: PDF → картинка → растровый разбор, сверка размеров с вектором."""
    from floorplan_engine.service.facts.bench import report, run

    for pdf in pdfs:
        typer.echo(report(pdf.name, run(pdf)))
        typer.echo("")


@app.command()
def symbols(
    folder: Annotated[Path, typer.Argument(help="Куда выгрузить блоки УГО")] = Path("symbols"),
) -> None:
    """Выгрузить блоки УГО (розетка, выключатель, светильник, щит) в отдельные DXF."""
    for path in export_symbols(folder):
        typer.echo(f"  {path}")


def _viewer_auth() -> Auth | None:
    """Viewer login from the environment (SHTROBA_AUTH=on, service/api/auth.py); None when off."""
    from floorplan_engine.service.api.auth import Auth, AuthConfig, ConfigError
    from floorplan_engine.service.api.mail import LogMailer, mailer_from_env
    from floorplan_engine.service.api.telegram import telegram_from_env
    from floorplan_engine.service.db.session import make_engine, make_sessions

    try:
        config = AuthConfig.from_env()
    except ConfigError as exc:
        typer.secho(f"Вход: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc
    if config is None:
        return None
    google = "Google" if config.google else "без Google (нет GOOGLE_CLIENT_ID)"
    guest = ", гостевой вход для отладки" if config.visitor else ""
    if config.dev_login:
        guest += f", «Зайти для разработки» — как {config.superusers[0]}"
    typer.echo(f"Вход включён: {google}{guest}")
    mailer = mailer_from_env(dict(os.environ), local=not config.secure)
    if mailer is None:
        typer.echo("Вход по коду на почту выключен: нет SMTP_HOST")
    elif isinstance(mailer, LogMailer):
        typer.echo("Вход по коду на почту: без SMTP — код в этом терминале")
    bot = telegram_from_env(dict(os.environ))
    if bot is None:
        typer.echo("Вход через Telegram выключен: нет TELEGRAM_BOT_TOKEN")
    else:
        how = "вебхук" if config.secure else "опрос Bot API из этого процесса"
        typer.echo(f"Вход через Telegram: бот настроен, {how}")
    return Auth(config, make_sessions(make_engine()), mailer=mailer, telegram=bot)


access_app = typer.Typer(
    help="Доступ к проектам просмотра: связь папки с базой, приглашения, коды доступа."
)
app.add_typer(access_app, name="access")


@access_app.command("link")
def access_link(
    project: ProjectArg,
    owner: Annotated[
        str | None,
        typer.Option(help="Email владельца (уже входил и выбрал тип); нет — без владельца"),
    ] = None,
) -> None:
    """Связать папку проекта с базой: проект в студии владельца, slug — имя папки. Без
    --owner — проект «без владельца»: код доступа выдать уже можно, владелец (SHTROBA_OWNER)
    заберёт проект при входе."""
    from floorplan_engine.service.db import access as acc
    from floorplan_engine.service.db.models import AppUser
    from floorplan_engine.service.db.session import make_engine, make_sessions

    with make_sessions(make_engine())() as db:
        if acc.project_by_slug(db, project.name) is not None:
            typer.secho(f"Проект {project.name} уже в базе", fg=typer.colors.YELLOW)
            raise typer.Exit(1)
        if owner is None:
            acc.create_project_unowned(db, project.name, project.name)
            db.commit()
            typer.echo(f"Проект {project.name} — в базе без владельца")
            return
        user = db.query(AppUser).filter(AppUser.email == owner.strip().lower()).one_or_none()
        if user is None:
            typer.secho(f"Нет пользователя {owner} — пусть сначала войдёт", fg=typer.colors.RED)
            raise typer.Exit(1)
        try:
            studio = acc.own_studio(db, user)
            if studio is not None:  # the folder lies in the root: the root becomes the studio's
                acc.claim_root(db, studio)
            acc.create_project_for(db, user, project.name, project.name)
        except acc.AccessError as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
            raise typer.Exit(1) from exc
        db.commit()
    typer.echo(f"Проект {project.name} — в студии {owner}")


@access_app.command("invite")
def access_invite(
    project: ProjectArg,
    role: Annotated[str, typer.Option(help="client — хозяин квартиры, installer — монтажник")],
    email: Annotated[str | None, typer.Option(help="Кому (для списка приглашений)")] = None,
    days: Annotated[int, typer.Option(help="Срок ссылки, дней")] = 7,
) -> None:
    """Ссылка-приглашение в проект (от имени владельца платформы)."""
    import os

    from floorplan_engine.service.db import access as acc
    from floorplan_engine.service.db.session import make_engine, make_sessions

    with make_sessions(make_engine())() as db:
        target = acc.project_by_slug(db, project.name)
        if target is None:
            typer.secho(f"Проекта {project.name} нет в базе — access link", fg=typer.colors.RED)
            raise typer.Exit(1)
        try:
            token = acc.create_invite(db, None, role, project=target, email=email, days=days)
        except acc.AccessError as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
            raise typer.Exit(1) from exc
        db.commit()
    public = os.environ.get("SHTROBA_PUBLIC_URL", "http://127.0.0.1:5173").rstrip("/")
    typer.echo(f"{public}/?invite={token}")


def _db_project(db: Session, project: Path, create: bool = False) -> Project:
    """Project row in the database for a folder; if missing, exit with a hint or, with create, make
    a
    row without an owner (the owner claims it on login)."""
    from floorplan_engine.service.db import access as acc

    target = acc.project_by_slug(db, project.name)
    if target is None and create:
        target = acc.create_project_unowned(db, project.name, project.name)
        typer.echo(f"Проект {project.name} записан в базу без владельца", err=True)
    if target is None:
        typer.secho(f"Проекта {project.name} нет в базе — access link", fg=typer.colors.RED)
        raise typer.Exit(1)
    return target


@access_app.command("code")
def access_code(
    project: ProjectArg,
    label: Annotated[str, typer.Option(help="Кому выдан (для списка кодов)")] = "",
    days: Annotated[int, typer.Option(help="Срок кода, дней")] = 30,
) -> None:
    """Код доступа к проекту: человек вводит его на экране входа и смотрит этот проект
    (только чтение, без учётки). Показывается один раз — в базе только хеш. Проекта нет в
    базе — записывается без владельца."""
    from floorplan_engine.service.db import access as acc
    from floorplan_engine.service.db import access_codes
    from floorplan_engine.service.db.session import make_engine, make_sessions

    with make_sessions(make_engine())() as db:
        target = _db_project(db, project, create=True)
        try:
            code = access_codes.issue_code(db, target, None, label=label, days=days)
        except acc.AccessError as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
            raise typer.Exit(1) from exc
        db.commit()
    typer.echo(code)


@access_app.command("codes")
def access_codes_list(project: ProjectArg) -> None:
    """Коды доступа проекта: id, кому, срок, входов, отозван ли."""
    from floorplan_engine.service.db import access_codes
    from floorplan_engine.service.db.session import make_engine, make_sessions

    with make_sessions(make_engine())() as db:
        target = _db_project(db, project)
        rows = access_codes.list_codes(db, target)
        if not rows:
            typer.echo("Кодов нет — access code")
            return
        for r in rows:
            state = "отозван" if r.revoked_at else f"до {r.expires_at:%Y-%m-%d}"
            who = f" {r.label}" if r.label else ""
            typer.echo(f"{str(r.id)[:8]}{who}: {state}, входов {r.uses}")


@access_app.command("revoke-code")
def access_revoke_code(
    project: ProjectArg, code_id: Annotated[str, typer.Argument(help="id кода или его начало")]
) -> None:
    """Отозвать код доступа: входы по нему кончаются сразу."""
    from floorplan_engine.service.db import access as acc
    from floorplan_engine.service.db import access_codes
    from floorplan_engine.service.db.session import make_engine, make_sessions

    with make_sessions(make_engine())() as db:
        target = _db_project(db, project)
        try:
            row = access_codes.revoke_code(db, target, code_id)
        except acc.AccessError as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
            raise typer.Exit(1) from exc
        db.commit()
    typer.echo(f"Код {str(row.id)[:8]} отозван")


project_app = typer.Typer(
    help="Проект в базе ↔ папка (правда — база): push — папку в базу, pull — из базы в папку."
)
app.add_typer(project_app, name="project")
studio_app = typer.Typer(help="Прайс и профиль студии (prices.yaml, studio.yaml) ↔ база.")
app.add_typer(studio_app, name="studio")

OwnerOpt = Annotated[
    str | None, typer.Option(help="Почта или телефон владельца студии (уже входил и выбрал тип)")
]


def _owner_studio(db: Session, owner: str | None) -> Studio | None:
    """The studio of its owner by e-mail or phone; None without --owner; exit with a hint if there
    is none."""
    from sqlalchemy import func, or_, select

    from floorplan_engine.service.db import access as acc
    from floorplan_engine.service.db.models import AppUser

    if owner is None:
        return None
    key = owner.strip().lower()
    user = db.scalar(
        select(AppUser).where(or_(func.lower(AppUser.email) == key, AppUser.phone == key))
    )
    studio = acc.own_studio(db, user) if user is not None else None
    if studio is None:
        typer.secho(f"Нет студии у {owner} — пусть войдёт и выберет тип", fg=typer.colors.RED)
        raise typer.Exit(1)
    return studio


def _push_one(db: Session, folder: Path, studio: Studio | None, build: bool) -> None:
    from floorplan_engine.service import sync
    from floorplan_engine.service.objects import store_from_env

    try:
        result = sync.push(db, store_from_env(), folder, studio, build=build)
    except sync.SyncError as exc:
        typer.secho(f"{folder.name}: {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from exc
    db.commit()
    what = (
        f"версия {result.version}"
        if result.new_version
        else f"без изменений (версия {result.version})"
    )
    extra = f", исходников +{len(result.sources)}" if result.sources else ""
    built = f", сборка: {result.build.status}" if result.build is not None else ""
    typer.echo(f"{folder.name}: {what}{extra}{built}")


@project_app.command("push")
def project_push(
    project: ProjectArg,
    owner: OwnerOpt = None,
    build: Annotated[bool, typer.Option(help="Собрать новую версию")] = True,
) -> None:
    """Папку — в базу: новая версия модели, если файлы изменились; прайс проекта, новые
    исходники, сборка. Новый проект — в студию --owner. Отказ, если в базе версия новее той,
    с которой папка выгружена (сначала pull)."""
    from floorplan_engine.service.db.session import make_engine, make_sessions

    with make_sessions(make_engine())() as db:
        _push_one(db, project, _owner_studio(db, owner), build)


@project_app.command("pull")
def project_pull(
    slug: Annotated[str, typer.Argument(help="Имя проекта (папки) в базе")],
    to: Annotated[Path, typer.Option(help="Куда: папка проектов")] = Path("projects"),
    force: Annotated[
        bool, typer.Option(help="Затереть правки в папке, которых нет в базе")
    ] = False,
) -> None:
    """Из базы — в папку <to>/<имя>: последняя версия модели, прайс проекта, недостающие
    исходники и out/ последней сборки. Правки в папке, которых нет в базе, не затираются без
    --force."""
    from floorplan_engine.service import sync
    from floorplan_engine.service.db import access as acc
    from floorplan_engine.service.db.session import make_engine, make_sessions
    from floorplan_engine.service.objects import store_from_env

    with make_sessions(make_engine())() as db:
        target = acc.project_by_slug(db, slug)
        if target is None:
            typer.secho(f"Проекта {slug} в базе нет", fg=typer.colors.RED)
            raise typer.Exit(1)
        try:
            version = sync.pull(db, store_from_env(), target, to / slug, force=force)
        except sync.SyncError as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
            raise typer.Exit(1) from exc
    typer.echo(f"{to / slug}: версия {version}")


@project_app.command("import")
def project_import(
    root: Annotated[Path, typer.Argument(help="Папка проектов, например projects")],
    owner: Annotated[str, typer.Option(help="Почта или телефон владельца студии")],
    build: Annotated[bool, typer.Option(help="Собрать проекты")] = True,
) -> None:
    """Перенести папку проектов в базу: прайс и профиль студии (prices.yaml, studio.yaml), затем
    каждый проект — как project push. Повторный запуск заливает только изменения."""
    from floorplan_engine.service import sync
    from floorplan_engine.service.api.viewer import project_folders
    from floorplan_engine.service.db.session import make_engine, make_sessions

    with make_sessions(make_engine())() as db:
        studio = _owner_studio(db, owner)
        assert studio is not None
        taken = sync.push_studio(db, studio, root)
        db.commit()
        typer.echo(f"Студия «{studio.name}»: {', '.join(taken) or 'файлов студии нет'}")
        for folder in project_folders(root):
            _push_one(db, folder, studio, build)


@studio_app.command("push")
def studio_push(
    root: Annotated[Path, typer.Argument(help="Папка с prices.yaml и studio.yaml")],
    owner: Annotated[str, typer.Option(help="Почта или телефон владельца студии")],
) -> None:
    """Прайс и профиль студии из папки — в базу."""
    from floorplan_engine.service import sync
    from floorplan_engine.service.db.session import make_engine, make_sessions

    with make_sessions(make_engine())() as db:
        studio = _owner_studio(db, owner)
        assert studio is not None
        taken = sync.push_studio(db, studio, root)
        db.commit()
    typer.echo(f"Студия «{studio.name}»: {', '.join(taken) or 'файлов нет'}")


@studio_app.command("pull")
def studio_pull(
    root: Annotated[Path, typer.Argument(help="Куда: папка проектов")],
    owner: Annotated[str, typer.Option(help="Почта или телефон владельца студии")],
) -> None:
    """Прайс и профиль студии из базы — в папку."""
    from floorplan_engine.service import sync
    from floorplan_engine.service.db.session import make_engine, make_sessions

    with make_sessions(make_engine())() as db:
        studio = _owner_studio(db, owner)
        assert studio is not None
        written = sync.pull_studio(db, studio, root)
    typer.echo(f"{root}: {', '.join(written) or 'у студии нет прайса и профиля'}")
