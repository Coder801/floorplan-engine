"""A project folder ↔ the database (stage B, step B3; docs/database.md, "Переезд проектов из папок в
базу"): the database is the truth, a folder is a working copy for Claude Code.

- push: the folder's model files become a new model version (only if they changed), plus the
  project's own price list and new sources (by hash), then a build. A new project needs a studio.
- pull: the latest version, the project price list, missing sources and the latest build's out/
  go into the folder.
- The folder remembers where it came from in a hidden `.shtroba.yaml` (project id and version):
  push refuses if the database got a newer version meanwhile (a route edit on the server — pull
  first), pull refuses to overwrite local edits that were never pushed (unless forced).
- Studio files next to the projects (prices.yaml, studio.yaml): push_studio / pull_studio.

Functions take an open Session and do not commit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from floorplan_engine.electrical.estimate import PRICES_FILE
from floorplan_engine.pipeline import OUT_DIR
from floorplan_engine.service import project_store as ps
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db import repositories as repo
from floorplan_engine.service.db import telegram_login as tg
from floorplan_engine.service.db.models import (
    AccessCode,
    AppUser,
    Build,
    Invite,
    ModelVersion,
    PriceList,
    Project,
    ProjectMember,
    Source,
    Studio,
    StudioProfile,
)
from floorplan_engine.service.objects import ObjectStore, source_key
from floorplan_engine.validation.issues import ROOM_FILE, STUDIO_FILE

MARKER = ".shtroba.yaml"
SOURCE_DIR = ps.SOURCE_DIR
IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff", ".bmp"}


class SyncError(RuntimeError):
    """Pushing or pulling would lose someone's edits: the message says what to do, in Russian."""


@dataclass
class PushResult:
    project: Project
    version: int  # model version the folder now matches
    new_version: bool
    sources: list[str] = field(default_factory=list)  # source files added to the database
    build: Build | None = None


@dataclass(frozen=True)
class Marker:
    project: uuid.UUID
    version: int


def read_marker(folder: Path) -> Marker | None:
    path = folder / MARKER
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text("utf-8")) or {}
    return Marker(uuid.UUID(str(data["project"])), int(data["version"]))


def write_marker(folder: Path, project: Project, version: int) -> None:
    text = (
        "# Рабочая копия проекта из базы Shtroba (floorplan-engine project pull/push): не править\n"
        f"project: {project.id}\nslug: {project.slug}\nversion: {version}\n"
    )
    (folder / MARKER).write_text(text, "utf-8")


def model_files(folder: Path) -> dict[str, str]:
    """The model files lying in the folder."""
    return {
        name: (folder / name).read_text("utf-8")
        for name in repo.MODEL_COLUMNS
        if (folder / name).is_file()
    }


def _source_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGES:
        return "image"
    return {".pdf": "pdf", ".txt": "text", ".md": "text"}.get(suffix, "file")


def _parsed_prices(text: str) -> dict[str, Any]:
    """The parsed columns of price_list from prices.yaml; the text stays the truth."""
    data = repo.parsed_copy(text)
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    for key, default in (("currency", "грн"), ("date", ""), ("note", ""), ("items", {})):
        value = data.get(key, default)
        out[key] = value if isinstance(value, type(default)) else default
    return out


def put_price_list(session: Session, owner: dict[str, uuid.UUID], text: str | None) -> None:
    """Write (or remove, text None) the price list of a studio or a project."""
    column = PriceList.studio_id if "studio_id" in owner else PriceList.project_id
    row = session.scalar(select(PriceList).where(column == next(iter(owner.values()))))
    if text is None:
        if row is not None:
            session.delete(row)
        return
    if row is None:
        row = PriceList(**owner)
        session.add(row)
    row.text = text
    for key, value in _parsed_prices(text).items():
        setattr(row, key, value)


def _project_name(files: dict[str, str], fallback: str) -> str:
    room = repo.parsed_copy(files.get(ROOM_FILE, ""))
    name = room.get("name") if isinstance(room, dict) else None
    return str(name) if name else fallback


def _blank(session: Session, project: Project) -> bool:
    """Only a name: the row was made before the model reached the database (`access link`, an
    access code, a folder adopted on login)."""
    return (
        repo.latest_model(session, project.id) is None
        and session.scalar(select(Source.id).where(Source.project_id == project.id).limit(1))
        is None
    )


def _merge_blank(session: Session, blank: Project, target: Project) -> None:
    """Who could reach the blank row now reaches `target`; the blank row goes away."""
    moved = {"project_id": target.id}
    session.execute(update(AccessCode).where(AccessCode.project_id == blank.id).values(moved))
    session.execute(update(Invite).where(Invite.project_id == blank.id).values(moved))
    members = select(ProjectMember.user_id).where(ProjectMember.project_id == target.id)
    session.execute(
        update(ProjectMember)
        .where(ProjectMember.project_id == blank.id, ProjectMember.user_id.not_in(members))
        .values(moved)
    )
    acc.audit(session, "project_merge", project=target, payload={"blank": str(blank.id)})
    session.delete(blank)
    session.flush()


def take_blank(session: Session, slug: str, studio: Studio) -> Project | None:
    """The blank row a folder `slug` fills in `studio`, None if there is none. A blank "no owner"
    row moves to the studio or, if the studio has this project already, merges into it."""
    own = acc.project_by_slug(session, slug, studio)
    unowned = session.scalar(
        select(Project)
        .join(Studio, Studio.id == Project.studio_id)
        .where(Studio.kind == acc.UNOWNED_KIND, Project.slug == slug)
    )
    if unowned is not None and _blank(session, unowned):
        if own is not None:
            _merge_blank(session, unowned, own)
        else:
            unowned.studio_id = studio.id
            session.flush()
            acc.audit(session, "project_adopt", project=unowned)
            return unowned
    return own if own is not None and _blank(session, own) else None


def push(
    session: Session,
    store: ObjectStore,
    folder: Path,
    studio: Studio | None = None,
    author: str = "operator",
    build: bool = True,
) -> PushResult:
    """Folder → database. A folder without the marker is a new project in `studio` (slug — the
    folder name; a blank row of that name is filled, take_blank); a folder with it continues its
    project, unless the database moved on."""
    files = model_files(folder)
    if not files:
        raise SyncError(f"в {folder} нет файлов модели (room.yaml, intake.yaml…)")
    marker = read_marker(folder)
    if marker is not None:
        project = session.get(Project, marker.project)
        if project is None:
            raise SyncError(f"проекта {marker.project} из {MARKER} в базе нет")
        latest = repo.latest_model(session, project.id)
        if latest is not None and latest.version > marker.version:
            raise SyncError(
                f"в базе версия {latest.version}, а папка выгружена с версии {marker.version} — "
                f"сначала project pull, потом push"
            )
    else:
        if studio is None:
            raise SyncError("новый проект: укажите студию (--owner)")
        blank = take_blank(session, folder.name, studio)
        if blank is not None:
            project = blank
            project.name = _project_name(files, folder.name)
        elif acc.project_by_slug(session, folder.name, studio) is not None:
            raise SyncError(
                f"проект {folder.name} уже в студии — выгрузите его: project pull {folder.name}"
            )
        else:
            project = Project(
                studio_id=studio.id, name=_project_name(files, folder.name), slug=folder.name
            )
            session.add(project)
            session.flush()
            acc.audit(session, "project_create", project=project, payload={"push": True})
        latest = None

    new = latest is None or repo.model_files(latest) != files
    version = repo.add_model_version(session, project.id, files, author) if new else latest
    assert version is not None
    prices = folder / PRICES_FILE
    put_price_list(
        session,
        {"project_id": project.id},
        prices.read_text("utf-8") if prices.is_file() else None,
    )
    result = PushResult(project, version.version, new)
    src = folder / SOURCE_DIR
    for path in sorted(p for p in src.rglob("*") if p.is_file()) if src.is_dir() else []:
        if any(part.startswith(".") for part in path.relative_to(src).parts):
            continue
        data = path.read_bytes()
        digest = repo.sha256(data)
        if session.scalar(
            select(Source.id).where(Source.project_id == project.id, Source.sha256 == digest)
        ):
            continue
        rel = path.relative_to(src).as_posix()
        key = source_key(project.id, digest, path.name)
        store.put(key, data)
        repo.add_source(session, project.id, rel, data, _source_kind(path), key)
        result.sources.append(rel)
    session.flush()
    if build and (new or ps.latest_build(session, project) is None):
        result.build = ps.build(session, store, project, version)
    write_marker(folder, project, version.version)
    return result


def _local_edits(session: Session, project: Project, folder: Path) -> bool:
    """The folder's model files differ from the version it was pulled or pushed at."""
    marker = read_marker(folder)
    files = model_files(folder)
    if marker is None:
        return bool(files)
    if marker.project != project.id:
        raise SyncError(f"папка {folder} — рабочая копия другого проекта ({marker.project})")
    base = session.scalar(
        select(ModelVersion).where(
            ModelVersion.project_id == project.id, ModelVersion.version == marker.version
        )
    )
    return base is None or repo.model_files(base) != files


def pull(
    session: Session, store: ObjectStore, project: Project, folder: Path, force: bool = False
) -> int:
    """Database → folder: the latest model version (model files not in it are removed), the
    project price list, missing sources and the latest build's out/. Local edits that were never
    pushed stop it unless force. Returns the version number."""
    folder.mkdir(parents=True, exist_ok=True)
    if not force and _local_edits(session, project, folder):
        raise SyncError(
            f"в {folder} есть правки, которых нет в базе — сначала project push "
            f"(или --force, чтобы их затереть)"
        )
    version = repo.latest_model(session, project.id)
    if version is None:
        raise SyncError(f"у проекта {project.slug} нет модели")
    files = ps.project_files(session, project, version)
    for name in repo.MODEL_COLUMNS:
        if name not in files:
            (folder / name).unlink(missing_ok=True)
    if PRICES_FILE not in files:
        (folder / PRICES_FILE).unlink(missing_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text, "utf-8")
    for s in session.scalars(select(Source).where(Source.project_id == project.id)):
        target = folder / SOURCE_DIR / s.file_name
        if not target.is_file() and store.exists(s.object_key):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(store.get(s.object_key))
    build = ps.latest_build(session, project)
    if build is not None:
        for f in build.files:
            target = folder / OUT_DIR / f.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(store.get(f.object_key))
    write_marker(folder, project, version.version)
    return version.version


# --- Studio files next to the projects ---------------------------------------------------

PROFILE_FIELDS = ("organization", "stage", "signatures")


def push_studio(session: Session, studio: Studio, root: Path) -> list[str]:
    """root/prices.yaml and root/studio.yaml → the studio's price list and profile. Returns the
    files taken."""
    taken = []
    prices = root / PRICES_FILE
    if prices.is_file():
        put_price_list(session, {"studio_id": studio.id}, prices.read_text("utf-8"))
        taken.append(PRICES_FILE)
    profile_path = root / STUDIO_FILE
    if profile_path.is_file():
        data = yaml.safe_load(profile_path.read_text("utf-8")) or {}
        profile = session.get(StudioProfile, studio.id)
        if profile is None:
            profile = StudioProfile(studio_id=studio.id)
            session.add(profile)
        profile.organization = str(data.get("organization", ""))
        profile.stage = str(data.get("stage", ""))
        profile.signatures = list(data.get("signatures") or [])
        taken.append(STUDIO_FILE)
    session.flush()
    return taken


def pull_studio(session: Session, studio: Studio, root: Path) -> list[str]:
    """The studio's price list and profile → root/prices.yaml and root/studio.yaml."""
    root.mkdir(parents=True, exist_ok=True)
    files = ps.studio_files(session, studio.id)
    for name, text in files.items():
        (root / name).write_text(text, "utf-8")
    return sorted(files)


def has_studio_files(session: Session, studio: Studio) -> bool:
    """The studio already has a price list or a profile in the database."""
    prices = session.scalar(select(PriceList.id).where(PriceList.studio_id == studio.id))
    return prices is not None or session.get(StudioProfile, studio.id) is not None


def ensure_owner(session: Session, owner: str, firm: str = "Shtroba") -> Studio:
    """The studio of the projects' owner (SHTROBA_OWNER: an e-mail or a phone "+380…"), created if
    there is none: a user with that e-mail or phone and their firm. When the owner later logs in
    with Google (the same confirmed e-mail) or Telegram (the same phone), it is the same user
    (access.oauth_login)."""
    value = owner.strip()
    phone = tg.normalize_phone(value) if tg.is_phone(value) else None
    email = None if phone else value.lower()
    user = session.scalar(
        select(AppUser).where(
            AppUser.phone == phone if phone else func.lower(AppUser.email) == email
        )
    )
    if user is None:
        user = AppUser(email=email, phone=phone, name="")
        session.add(user)
        session.flush()
        acc.audit(session, "owner_create", user=user)
    studio = acc.own_studio(session, user)
    if studio is None:
        studio = acc.register_firm(session, user, firm, "electric")
    return studio
