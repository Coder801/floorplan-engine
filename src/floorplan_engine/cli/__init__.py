"""CLI `floorplan-engine`: the root app, the commands that start a server and read .env.

Commands live by what they work on: documents.py — a project folder (the core), sources.py —
sources, access.py and projects.py — the database. They print and set exit codes; the logic is
in pipeline/ and service/. Commands are registered at the end of this file: that order is the
order in --help.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from floorplan_engine.cli.access import access_app
from floorplan_engine.cli.common import AnalyzerOpt, EffortOpt, ElectricalModelOpt, ModelOpt
from floorplan_engine.cli.documents import (
    build,
    check,
    estimate,
    preview,
    print_album,
    render_artifact,
    symbols,
)
from floorplan_engine.cli.projects import project_app, studio_app
from floorplan_engine.cli.sources import analyze, facts, facts_bench, pdf_facts

if TYPE_CHECKING:
    from fastapi import FastAPI

    from floorplan_engine.service.api.auth import Auth
    from floorplan_engine.service.objects import ObjectStore

app = typer.Typer(
    help="Чертежи DXF (план, электрика) из room.yaml / electrical.yaml.",
    no_args_is_help=True,
    add_completion=False,
)

# Service commands read .env (Google login, database, API key); build and check do not: they
# need no environment, and CLI tests must not pick up someone else's .env
ENV_COMMANDS = frozenset({"serve", "view", "dev", "analyze", "access", "project", "studio"})
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DEV_PROJECTS_ENV = "SHTROBA_DEV_PROJECTS"  # projects folder for the `dev` API (survives restarts)
STORAGE_ENV = "SHTROBA_STORAGE"  # db — projects from the database (stage B); otherwise folders


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
    try:
        mailer = mailer_from_env(dict(os.environ), local=not config.secure)
    except ValueError as exc:
        typer.secho(f"Почта: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc
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


def _viewer_store() -> ObjectStore | None:
    """File storage when projects live in the database (SHTROBA_STORAGE=db, login is required);
    None — projects from the folder, as before."""
    if os.environ.get(STORAGE_ENV, "").lower() != "db":
        return None
    from floorplan_engine.service.objects import store_from_env

    typer.echo("Проекты — из базы (SHTROBA_STORAGE=db), файлы — SHTROBA_OBJECTS", err=True)
    return store_from_env()


def dev_viewer() -> FastAPI:
    """API app for `dev`: uvicorn calls the factory again after every code-change restart; the
    projects folder comes from the environment."""
    from floorplan_engine.service.api.viewer import create_viewer

    root = Path(os.environ.get(DEV_PROJECTS_ENV, "projects"))
    return create_viewer(root, _viewer_auth(), _viewer_store())


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

    auth = _viewer_auth()
    if auth is None and host not in LOOPBACK_HOSTS:
        typer.secho(
            f"Без входа API открыт всем: на {host} — только с SHTROBA_AUTH=on",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)
    app_ = create_app(data, make_analyzer(analyzer, model, effort, electrical_model), auth)
    uvicorn.run(app_, host=host, port=port)


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
    uvicorn.run(create_viewer(projects, _viewer_auth(), _viewer_store()), host=host, port=port)


def dev(
    projects: Annotated[Path, typer.Option(help="Папка собранных проектов")] = Path("projects"),
    port: Annotated[int, typer.Option(help="Порт API")] = 8000,
    web: Annotated[Path, typer.Option(help="Папка фронта")] = Path("web"),
    admin: Annotated[Path, typer.Option(help="Папка админки")] = Path("admin"),
) -> None:
    """Просмотр одной командой для разработки: API (`view`), страница web/ (`npm run dev`,
    http://127.0.0.1:5173) и админка admin/ (5174, открывается и как 5173/admin/ — один адрес и
    общий вход, как на сервере). Все перезагружаются при правках: страницы — Vite, API — uvicorn
    следит за кодом пакета и перезапускается сам (иначе после правок Python пересборки шли бы
    старым кодом). Ctrl+C останавливает всё."""
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
    fronts = [web] + ([admin] if (admin / "package.json").is_file() else [])
    for folder in fronts:
        if not (folder / "node_modules").is_dir():
            subprocess.run([npm, "install"], cwd=folder, check=True)
    env = {**os.environ, "API_URL": f"http://127.0.0.1:{port}"}
    procs = [subprocess.Popen([npm, "run", "dev"], cwd=folder, env=env) for folder in fronts]
    pages = "http://127.0.0.1:5173" + (" · админка: /admin/" if len(fronts) > 1 else "")
    typer.echo(f"Страница: {pages} · API: http://127.0.0.1:{port}/api")
    os.environ[DEV_PROJECTS_ENV] = str(projects.resolve())  # read by the API factory
    try:
        uvicorn.run(
            "floorplan_engine.cli:dev_viewer",
            factory=True,
            host="127.0.0.1",
            port=port,
            reload=True,
            # The whole floorplan_engine package: this file is in cli/
            reload_dirs=[str(Path(__file__).resolve().parent.parent)],
        )
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


app.command()(check)
app.command()(build)
app.command("print")(print_album)
app.command()(preview)
app.command("render-artifact")(render_artifact)
app.command()(serve)
app.command()(estimate)
app.command()(view)
app.command()(dev)
app.command()(analyze)
app.command("pdf-facts")(pdf_facts)
app.command()(facts)
app.command("facts-bench")(facts_bench)
app.command()(symbols)
app.add_typer(access_app, name="access")
app.add_typer(project_app, name="project")
app.add_typer(studio_app, name="studio")
