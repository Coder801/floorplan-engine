"""What the command modules share: argument types, failure exits, the report, the database."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, NoReturn

import typer

from floorplan_engine.validation.assess import STATUS_TEXT, StageResult
from floorplan_engine.validation.issues import Severity
from floorplan_engine.validation.report import STAGE_TEXT
from floorplan_engine.validation.validate import Report

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from floorplan_engine.service.db.models import Project, Studio

ProjectArg = Annotated[
    Path,
    typer.Argument(exists=True, file_okay=False, dir_okay=True, help="Папка проекта"),
]
AnalyzerOpt = Annotated[
    str, typer.Option(help="manual — оператор; claude-code — подписка; api — ANTHROPIC_API_KEY")
]
ModelOpt = Annotated[str, typer.Option(help="Модель Claude")]
EffortOpt = Annotated[str, typer.Option(help="low | medium | high | xhigh | max")]
ElectricalModelOpt = Annotated[
    str | None, typer.Option(help="Модель электрики — отдельным шагом после плана")
]


def fail(message: str, code: int = 1) -> NoReturn:
    typer.secho(message, fg=typer.colors.RED)
    raise typer.Exit(code=code)


@contextmanager
def exit_on(error: type[Exception], code: int = 1) -> Iterator[None]:
    """This error is a message for the user: print it and exit."""
    try:
        yield
    except error as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=code) from exc


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


def database() -> Session:
    """A session of the service database, for `with`. Service dependencies (group service) are
    needed only by the commands that open it."""
    from floorplan_engine.service.db.session import make_engine, make_sessions

    return make_sessions(make_engine())()


def find_project(db: Session, key: str, studio: Studio | None = None) -> Project | None:
    """A project by its id or name (in a studio, if given); the same name in several studios —
    exit with a hint to say which."""
    from floorplan_engine.service.db import access as acc

    with exit_on(acc.AccessError):
        project = acc.project_by_key(db, key) if studio is None else None
        if project is None:
            project = acc.project_by_slug(db, key, studio)
    return project
