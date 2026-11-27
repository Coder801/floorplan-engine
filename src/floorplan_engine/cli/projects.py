"""Groups `project` and `studio`: a project folder and studio files ↔ the database."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from floorplan_engine.cli.common import ProjectArg, database, exit_on, fail, find_project

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from floorplan_engine.service.db.models import Studio

project_app = typer.Typer(
    help="Проект в базе ↔ папка (правда — база): push — папку в базу, pull — из базы в папку."
)
studio_app = typer.Typer(help="Прайс и профиль студии из базы — в папку (рабочая копия).")

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
        fail(f"Нет студии у {owner} — пусть войдёт и выберет тип")
    return studio


def _push_one(db: Session, folder: Path, studio: Studio | None, build: bool) -> None:
    from floorplan_engine.service import sync
    from floorplan_engine.service.objects import store_from_env

    try:
        result = sync.push(db, store_from_env(), folder, studio, build=build)
    except sync.SyncError as exc:
        fail(f"{folder.name}: {exc}")
    db.commit()
    what = (
        f"версия {result.version}"
        if result.new_version
        else f"без изменений (версия {result.version})"
    )
    extra = f", исходников +{len(result.sources)}" if result.sources else ""
    if result.restored:
        extra += f", восстановлено файлов исходников: {len(result.restored)}"
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
    with database() as db:
        _push_one(db, project, _owner_studio(db, owner), build)


@project_app.command("pull")
def project_pull(
    slug: Annotated[str, typer.Argument(help="Имя проекта (папки) или его id")],
    to: Annotated[Path, typer.Option(help="Куда: папка проектов")] = Path("projects"),
    owner: OwnerOpt = None,
    force: Annotated[
        bool, typer.Option(help="Затереть правки в папке, которых нет в базе")
    ] = False,
) -> None:
    """Из базы — в папку <to>/<имя>: последняя версия модели, прайс проекта, недостающие
    исходники и out/ последней сборки. Правки в папке, которых нет в базе, не затираются без
    --force."""
    from floorplan_engine.service import sync
    from floorplan_engine.service.objects import store_from_env

    with database() as db:
        target = find_project(db, slug, _owner_studio(db, owner))
        if target is None:
            fail(f"Проекта {slug} в базе нет")
        slug = target.slug or str(target.id)
        with exit_on(sync.SyncError):
            version = sync.pull(db, store_from_env(), target, to / slug, force=force)
    typer.echo(f"{to / slug}: версия {version}")


@project_app.command("build")
def project_build(
    slugs: Annotated[
        list[str] | None, typer.Argument(help="Имена проектов; без них — все проекты студии")
    ] = None,
    owner: OwnerOpt = None,
    every: Annotated[
        bool, typer.Option("--all", help="Все проекты базы, всех студий (локальная копия)")
    ] = False,
) -> None:
    """Пересобрать проекты из базы текущим кодом: последняя версия модели, новая сборка в
    хранилище. Модель не меняется. Без имён нужен --owner или --all."""
    from sqlalchemy import select

    from floorplan_engine.service import project_store as ps
    from floorplan_engine.service.db.models import ModelVersion, Project
    from floorplan_engine.service.objects import store_from_env

    failed = False
    with database() as db:
        studio = _owner_studio(db, owner)
        if slugs and every:
            fail("Укажите имена проектов или --all, не вместе")
        if slugs:
            targets = [find_project(db, slug, studio) for slug in slugs]
            for slug, target in zip(slugs, targets, strict=True):
                if target is None:
                    fail(f"Проекта {slug} в базе нет")
        elif studio is not None:
            query = select(Project).where(Project.studio_id == studio.id).order_by(Project.slug)
            targets = list(db.scalars(query))
        elif every:
            targets = list(db.scalars(select(Project).order_by(Project.slug, Project.id)))
        else:
            fail("Укажите имена проектов, --owner или --all")
        store = store_from_env()
        for target in targets:
            assert target is not None
            name = target.slug or str(target.id)
            try:
                build = ps.build(db, store, target)
            except ps.NoModelError:
                db.rollback()
                typer.echo(f"{name}: модели нет — пропущен")
                continue
            version = db.get(ModelVersion, build.model_version_id)
            assert version is not None
            db.commit()
            failed = failed or build.status == "failed"
            typer.echo(f"{name}: версия {version.version}, сборка: {build.status}")
    if failed:
        raise typer.Exit(1)


@project_app.command("import")
def project_import(
    root: Annotated[Path, typer.Argument(help="Папка проектов, например projects")],
    owner: Annotated[str, typer.Option(help="Почта или телефон владельца студии")],
    build: Annotated[bool, typer.Option(help="Собрать проекты")] = True,
    create_owner: Annotated[
        bool, typer.Option(help="Нет владельца или его фирмы — создать (фирма «Shtroba»)")
    ] = False,
    only_new: Annotated[
        bool,
        typer.Option(
            help="Только то, чего в базе нет: проекты студии не трогать (старт сервера: правда — "
            "база)"
        ),
    ] = False,
) -> None:
    """Перенести папку проектов в базу: каждый проект — как project push. Прайс и профиль студии
    не переносятся: они живут только в базе (решение 2026-11-27). Повторный запуск заливает только
    изменения; с --only-new уже перенесённое не трогает вовсе (кроме строк без модели: они
    заполняются из папки)."""
    from floorplan_engine.service import sync
    from floorplan_engine.service.api.viewer import project_folders
    from floorplan_engine.service.db import access as acc
    from floorplan_engine.service.objects import store_from_env

    with database() as db:
        studio = sync.ensure_owner(db, owner) if create_owner else _owner_studio(db, owner)
        assert studio is not None
        db.commit()
        typer.echo(f"Студия «{studio.name}»")
        for folder in project_folders(root):
            if only_new and sync.take_blank(db, folder.name, studio) is None:
                db.commit()
                existing = acc.project_by_slug(db, folder.name, studio)
                if existing is not None:
                    restored = sync.restore_sources(db, store_from_env(), existing, folder)
                    db.commit()
                    note = f", восстановлено файлов исходников: {len(restored)}" if restored else ""
                    typer.echo(f"{folder.name}: уже в базе — пропущен{note}")
                    continue
            _push_one(db, folder, studio, build)


@studio_app.command("pull")
def studio_pull(
    root: Annotated[Path, typer.Argument(help="Куда: папка проектов")],
    owner: Annotated[str, typer.Option(help="Почта или телефон владельца студии")],
) -> None:
    """Прайс и профиль студии из базы — в папку: рабочая копия для сборки из папки. Обратно в базу
    они не идут: правда — база, прайс правится на странице прайса (решение 2026-11-27)."""
    from floorplan_engine.service import sync

    with database() as db:
        studio = _owner_studio(db, owner)
        assert studio is not None
        written = sync.pull_studio(db, studio, root)
    typer.echo(f"{root}: {', '.join(written) or 'у студии нет прайса и профиля'}")
