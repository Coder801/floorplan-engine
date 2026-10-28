"""CLI: check / build / estimate / preview / render-artifact / analyze / pdf-facts / serve / view /
symbols."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from floorplan_engine.artifact import read_artifact, render_page_png
from floorplan_engine.assess import STATUS_TEXT, StageResult
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
from floorplan_engine.report import STAGE_TEXT
from floorplan_engine.schema import SheetFormat
from floorplan_engine.sheets import sheet_png_name
from floorplan_engine.symbols import export_symbols
from floorplan_engine.validate import Report, Severity

if TYPE_CHECKING:
    from floorplan_engine.service.auth import Auth

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


@app.callback()
def main() -> None:
    """floorplan-engine."""


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
    # Зависимости сервиса (группа service) нужны только этой команде
    import uvicorn

    from floorplan_engine.service.app import create_app
    from floorplan_engine.service.llm_analyzer import make_analyzer

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
    for issue in result.issues:
        typer.secho(str(issue), fg=typer.colors.RED)
    if result.estimate is None:
        raise typer.Exit(code=1)
    est = result.estimate
    cur = est.currency
    typer.echo(f"Материалы: {est.subtotal('material'):,.0f} {cur}".replace(",", " "))
    typer.echo(f"Работы:    {est.subtotal('work'):,.0f} {cur}".replace(",", " "))
    typer.echo(f"Всего:     {est.total:,.0f} {cur}".replace(",", " "))
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

    from floorplan_engine.service.viewer import FRONT_HINT, create_viewer

    if not projects.is_dir():
        typer.echo(f"Папки {projects} нет", err=True)
        raise typer.Exit(1)
    typer.echo(f"API просмотра: http://{host}:{port}/api; {FRONT_HINT}")
    uvicorn.run(create_viewer(projects, _viewer_auth()), host=host, port=port)


@app.command()
def dev(
    projects: Annotated[Path, typer.Option(help="Папка собранных проектов")] = Path("projects"),
    port: Annotated[int, typer.Option(help="Порт API")] = 8000,
    web: Annotated[Path, typer.Option(help="Папка фронта")] = Path("web"),
) -> None:
    """Просмотр одной командой для разработки: API (`view`) и страница web/ (`npm run dev`,
    http://127.0.0.1:5173) с перезагрузкой при правках; Ctrl+C останавливает оба."""
    import os
    import shutil
    import subprocess

    import uvicorn

    from floorplan_engine.service.viewer import create_viewer

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
    try:
        uvicorn.run(create_viewer(projects, _viewer_auth()), host="127.0.0.1", port=port)
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
    from floorplan_engine.service.llm_analyzer import AnalyzerError, make_analyzer

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
    from floorplan_engine.service.pdf_facts import describe, describe_json

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
    """Вход в просмотр по окружению (SHTROBA_AUTH=on, service/auth.py); выключен — None."""
    from floorplan_engine.service.auth import Auth, AuthConfig, ConfigError
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
    typer.echo(f"Вход включён: {google}{guest}")
    return Auth(config, make_sessions(make_engine()))


access_app = typer.Typer(help="Доступ к проектам просмотра: связь папки с базой, приглашения.")
app.add_typer(access_app, name="access")


@access_app.command("link")
def access_link(
    project: ProjectArg,
    owner: Annotated[str, typer.Option(help="Email владельца (уже входил и выбрал тип)")],
) -> None:
    """Связать папку проекта с базой: проект в студии владельца, slug — имя папки."""
    from floorplan_engine.service.db import access as acc
    from floorplan_engine.service.db.models import AppUser
    from floorplan_engine.service.db.session import make_engine, make_sessions

    with make_sessions(make_engine())() as db:
        user = db.query(AppUser).filter(AppUser.email == owner.strip().lower()).one_or_none()
        if user is None:
            typer.secho(f"Нет пользователя {owner} — пусть сначала войдёт", fg=typer.colors.RED)
            raise typer.Exit(1)
        if acc.project_by_slug(db, project.name) is not None:
            typer.secho(f"Проект {project.name} уже в базе", fg=typer.colors.YELLOW)
            raise typer.Exit(1)
        try:
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
