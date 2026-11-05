"""Group `access`: tying a project folder to the database, invitations, access codes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from floorplan_engine.cli.common import ProjectArg, database, exit_on, fail, find_project

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from floorplan_engine.service.db.models import Project

access_app = typer.Typer(
    help="Доступ к проектам просмотра: связь папки с базой, приглашения, коды доступа."
)


def _db_project(db: Session, project: Path, create: bool = False) -> Project:
    """Project row in the database for a folder; if missing, exit with a hint or, with create, make
    a row without an owner (the owner claims it on login)."""
    from floorplan_engine.service.db import access as acc

    target = find_project(db, project.name)
    if target is None and create:
        target = acc.create_project_unowned(db, project.name, project.name)
        typer.echo(f"Проект {project.name} записан в базу без владельца", err=True)
    if target is None:
        fail(f"Проекта {project.name} нет в базе — access link")
    return target


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

    with database() as db:
        if find_project(db, project.name) is not None:
            typer.secho(f"Проект {project.name} уже в базе", fg=typer.colors.YELLOW)
            raise typer.Exit(1)
        if owner is None:
            acc.create_project_unowned(db, project.name, project.name)
            db.commit()
            typer.echo(f"Проект {project.name} — в базе без владельца")
            return
        user = db.query(AppUser).filter(AppUser.email == owner.strip().lower()).one_or_none()
        if user is None:
            fail(f"Нет пользователя {owner} — пусть сначала войдёт")
        with exit_on(acc.AccessError):
            studio = acc.own_studio(db, user)
            if studio is not None:  # the folder lies in the root: the root becomes the studio's
                acc.claim_root(db, studio)
            acc.create_project_for(db, user, project.name, project.name)
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
    from floorplan_engine.service.db import access as acc

    with database() as db:
        target = acc.project_by_slug(db, project.name)
        if target is None:
            fail(f"Проекта {project.name} нет в базе — access link")
        with exit_on(acc.AccessError):
            token = acc.create_invite(db, None, role, project=target, email=email, days=days)
        db.commit()
    public = os.environ.get("SHTROBA_PUBLIC_URL", "http://127.0.0.1:5173").rstrip("/")
    typer.echo(f"{public}/?invite={token}")


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

    with database() as db:
        target = _db_project(db, project, create=True)
        with exit_on(acc.AccessError):
            code = access_codes.issue_code(db, target, None, label=label, days=days)
        db.commit()
    typer.echo(code)


@access_app.command("codes")
def access_codes_list(project: ProjectArg) -> None:
    """Коды доступа проекта: id, кому, срок, входов, отозван ли."""
    from floorplan_engine.service.db import access_codes

    with database() as db:
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

    with database() as db:
        target = _db_project(db, project)
        with exit_on(acc.AccessError):
            row = access_codes.revoke_code(db, target, code_id)
        db.commit()
    typer.echo(f"Код {str(row.id)[:8]} отозван")
