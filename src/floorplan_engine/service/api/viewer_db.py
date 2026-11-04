"""Viewer API from the database (stage B, step B4; docs/database.md, "Переезд проектов из папок в
базу"): the same addresses as the folder viewer (viewer.py), but a project is a database row —
addressed by its id (an old link by name still opens) — its sheets and out/ files come from the
latest build in file storage, the model from the latest version.

Writes keep the core as it is: a route edit or a wiring variant is applied by the same core
function (save_wiring_edits, save_variant) in a temporary folder with the latest version, the
changed files become a new model version by the user, and the project is rebuilt. The studio
price list is the caller's studio row in price_list (text with comments).

Turned on by create_viewer(..., store=…): login (auth) is required.
"""

from __future__ import annotations

import json
import mimetypes
import tempfile
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from floorplan_engine.electrical.estimate import PRICES_FILE
from floorplan_engine.epd.artifact import FORMAT_VERSION, MANIFEST
from floorplan_engine.epd.thumbnail import PREVIEW_FILE
from floorplan_engine.model.intake import ANSWERS_FILE, INTAKE_FILE, AnswerNote
from floorplan_engine.pipeline import (
    ARTIFACT_FILE,
    PROJECT_FILE,
    AnswerSaved,
    price_page,
    save_answer,
    save_prices,
    save_variant,
    save_wiring_edits,
)
from floorplan_engine.service import project_store as ps
from floorplan_engine.service import sync
from floorplan_engine.service.api.auth import Auth
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db import repositories as repo
from floorplan_engine.service.db.models import (
    Build,
    ModelVersion,
    PriceList,
    Project,
    Source,
)
from floorplan_engine.service.objects import ObjectStore
from floorplan_engine.validation.answers_file import build_digest, with_pending_text
from floorplan_engine.validation.issues import WIRING_FILE, Issue

SOURCE_DIR = ps.SOURCE_DIR


def check_manifest(zf: zipfile.ZipFile) -> dict[str, Any]:
    """The .epd manifest, if this server understands its format version (409 otherwise)."""
    data: dict[str, Any] = json.loads(zf.read(MANIFEST))
    if data.get("version") != FORMAT_VERSION:
        raise HTTPException(
            409, f"версия .epd {data.get('version')}, поддерживается {FORMAT_VERSION}"
        )
    return data


def refused_answer(saved: AnswerSaved) -> HTTPException:
    """422 of a refused answer: errors by field and the answers in the way of them, for the
    question card."""
    return HTTPException(
        422,
        {
            "issues": [
                {"file": i.file, "path": i.path, "message": i.message} for i in saved.issues
            ],
            "blocked_by": [{"id": q.id, "text": q.text} for q in saved.blocked_by],
        },
    )


def answer_note(who: acc.Principal | None) -> AnswerNote:
    """Who answered and when, for the log of answers.yaml; a code or a guest has no name."""
    user = who.user if who is not None else None
    return AnswerNote(
        at=datetime.now(UTC).isoformat(timespec="seconds"),
        by=(user.name or user.email) if user is not None else None,
    )


def answer_body(data: dict[str, Any]) -> tuple[str, Any]:
    """{id, answer} of POST /answers; answer null removes it."""
    qid = data.get("id")
    if not isinstance(qid, str) or not qid:
        raise HTTPException(422, "id: нужен id вопроса")
    return qid, data.get("answer")


def _version_of(session: Session, build: Build | None) -> ModelVersion | None:
    return session.get(ModelVersion, build.model_version_id) if build is not None else None


def _answers_of(version: ModelVersion | None) -> dict[str, Any]:
    answers = version.data.get(ANSWERS_FILE) if version is not None else None
    found = answers.get("answers") if isinstance(answers, dict) else None
    return found if isinstance(found, dict) else {}


def _stale(built_on: ModelVersion, latest: ModelVersion, report: dict[str, Any]) -> bool:
    """The model was changed after the build; a pending text answer alone changes nothing in it."""
    if latest.version <= built_on.version:
        return False
    old, new = repo.model_files(built_on), repo.model_files(latest)
    others = (new | old).keys() - {ANSWERS_FILE}
    if any(old.get(f) != new.get(f) for f in others):
        return True
    return report.get("answers_digest") != build_digest(new.get(ANSWERS_FILE))


def summary(session: Session, project: Project) -> dict[str, Any]:
    """The project card: as the folder viewer's _summary, from the latest build and version."""
    build = ps.latest_build(session, project)
    latest = repo.latest_model(session, project.id)
    built_on = _version_of(session, build)
    report = build.report if build is not None else {}
    questions = (with_pending_text(report, _answers_of(latest)) or {}).get("questions", [])
    return {
        "id": str(project.id),
        "name": project.slug or str(project.id),
        "title": report.get("project") or project.name,
        "built": build.created_at.timestamp() if build is not None else None,
        # The model was changed after the build: the sheets show the old state
        "stale": built_on is not None and latest is not None and _stale(built_on, latest, report),
        "stages": report.get("stages", []),
        "open_questions": sum(1 for q in questions if q.get("state") == "open"),
        "preview": build is not None and ps.build_file(session, build, PREVIEW_FILE) is not None,
    }


def _stored(store: ObjectStore, key: str) -> bytes:
    """A file of a build; a row in the database with no file is a lost build, not a server error."""
    try:
        return store.get(key)
    except FileNotFoundError as exc:
        raise HTTPException(404, f"файл сборки потерян, нужна пересборка: {key}") from exc


def _file_response(store: ObjectStore, key: str, name: str) -> Response:
    local = store.local_path(key)
    if local is not None:
        return FileResponse(local)
    media = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return Response(_stored(store, key), media_type=media)


def _read_routes(
    app: FastAPI,
    auth: Auth,
    store: ObjectStore,
    project_of: Callable[[Session, Request, str], Project],
    allowed: Callable[[Request, acc.Action], bool],
) -> None:
    """What the viewer shows, from the database and file storage."""

    @app.get("/api/projects")
    def projects(request: Request) -> list[dict[str, Any]]:
        with auth.db() as db:
            who = auth.principal(db, request)
            if who is None:
                return []
            rows = db.scalars(acc.visible_projects(db, who).order_by(Project.slug)).all()
            return [summary(db, p) for p in rows]

    @app.get("/api/projects/{key}")
    def project(key: str, request: Request) -> dict[str, Any]:
        with auth.db() as db:
            p = project_of(db, request, key)
            build = ps.latest_build(db, p)
            version = repo.latest_model(db, p.id)
            data = version.data if version is not None else {}
            names = [f.name for f in build.files] if build is not None else []
            answers = _answers_of(version)
            intake = data.get(INTAKE_FILE)
            model = repo.model_files(version) if version is not None else {}
            own_prices = db.scalar(select(PriceList.id).where(PriceList.project_id == p.id))
            return {
                **summary(db, p),
                "report": with_pending_text(
                    build.report if build is not None and build.report else None, answers
                ),
                "answers": answers,
                "artifact": ARTIFACT_FILE in names,
                "dxf": PROJECT_FILE if PROJECT_FILE in names else None,
                "files": sorted(n for n in names if "/" not in n),
                "sources": sorted(
                    db.scalars(select(Source.file_name).where(Source.project_id == p.id))
                ),
                "parsed": [
                    {
                        "file": str(s.get("file", "")).removeprefix(f"{SOURCE_DIR}/"),
                        "note": str(s.get("note", "")),
                    }
                    for s in (intake.get("sources") or [] if isinstance(intake, dict) else [])
                    if isinstance(s, dict)
                ],
                "model": [f for f in repo.MODEL_COLUMNS if f in model]
                + ([PRICES_FILE] if own_prices else []),
                "can": {
                    "edit_wiring": allowed(request, "edit_wiring"),
                    "choose_variant": allowed(request, "choose_variant"),
                    "answer": allowed(request, "answer"),
                },
            }

    def artifact(request: Request, key: str) -> zipfile.ZipFile:
        with auth.db() as db:
            p = project_of(db, request, key)
            build = ps.latest_build(db, p)
            f = ps.build_file(db, build, ARTIFACT_FILE) if build is not None else None
            if f is None:
                raise HTTPException(404, f"у проекта нет {ARTIFACT_FILE} — сначала сборка")
            return zipfile.ZipFile(BytesIO(_stored(store, f.object_key)))

    @app.get("/api/projects/{key}/sheets")
    def sheets(request: Request, key: str) -> dict[str, Any]:
        with artifact(request, key) as zf:
            return check_manifest(zf)

    @app.get("/api/projects/{key}/sheets/{index}")
    def sheet(request: Request, key: str, index: int) -> Response:
        with artifact(request, key) as zf:
            pages = check_manifest(zf)["pages"]
            page = next((p for p in pages if p["index"] == index), None)
            if page is None:
                raise HTTPException(404, f"листа {index} нет")
            return Response(zf.read(page["file"]), media_type="application/json")

    @app.get("/api/projects/{key}/out/{rel:path}")
    def out_file(request: Request, key: str, rel: str) -> Response:
        with auth.db() as db:
            build = ps.latest_build(db, project_of(db, request, key))
            f = ps.build_file(db, build, rel) if build is not None else None
            if f is None:
                raise HTTPException(404, f"файла {rel} нет")
            return _file_response(store, f.object_key, rel)

    @app.get("/api/projects/{key}/source/{rel:path}")
    def source_file(request: Request, key: str, rel: str) -> Response:
        with auth.db() as db:
            p = project_of(db, request, key)
            s = db.scalar(select(Source).where(Source.project_id == p.id, Source.file_name == rel))
            if s is None:
                raise HTTPException(404, f"файла {rel} нет")
            return _file_response(store, s.object_key, rel)

    @app.get("/api/projects/{key}/model/{filename}")
    def model(request: Request, key: str, filename: str) -> PlainTextResponse:
        with auth.db() as db:
            p = project_of(db, request, key)
            try:
                files = ps.project_files(db, p)
            except ps.NoModelError:
                files = {}
            if filename not in files:
                raise HTTPException(404, f"файла {filename} нет")
            return PlainTextResponse(files[filename], media_type="text/yaml")


def _edit_routes(
    app: FastAPI,
    auth: Auth,
    store: ObjectStore,
    project_of: Callable[[Session, Request, str], Project],
) -> None:
    """What the viewer writes: a new model version and a rebuild."""

    def rewrite(
        request: Request,
        key: str,
        apply: Callable[[Path], list[Issue]],
        rebuild: Callable[[], bool] = lambda: True,
    ) -> dict[str, Any]:
        """A change by a core function in the latest version's folder → a new version by the user
        and a rebuild (unless rebuild() says the change does not need one, it is asked after
        apply); errors (with a field path) give 422 and change nothing."""
        with auth.db() as db:
            p = project_of(db, request, key)
            ps.lock(db, p)
            with ps.workdir(db, store, p) as folder:
                issues = apply(folder)
                if issues:
                    raise HTTPException(422, "; ".join(f"{i.path}: {i.message}" for i in issues))
                files = sync.model_files(folder)
            version = repo.add_model_version(db, p.id, files, "user")
            who = auth.principal(db, request)
            version.user_id = who.user.id if who is not None and who.user is not None else None
            if not rebuild():
                return {"built": False, "notes": []}
            build = ps.build(db, store, p, version)
            notes = [
                f"{i.get('path')}: {i.get('message')}"
                for i in build.report.get("issues", [])
                if i.get("file") == WIRING_FILE
            ]
            return {"built": build.status == "built", "notes": notes}

    @app.post("/api/projects/{key}/wiring")
    def save_wiring(
        request: Request, key: str, changes: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        """Wiring edits → wiring.yaml of a new model version, then a rebuild."""
        return rewrite(request, key, lambda folder: save_wiring_edits(folder, changes))

    @app.post("/api/projects/{key}/answers")
    def answer(
        request: Request, key: str, data: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        """One answer: {id, answer} → answers.yaml of a new model version; a rebuild unless the
        answer is text waiting for the analyzer."""
        qid, raw = answer_body(data)
        with auth.db() as db:
            note = answer_note(auth.principal(db, request))
        saved = AnswerSaved()

        def apply(folder: Path) -> list[Issue]:
            nonlocal saved
            saved = save_answer(folder, qid, raw, note)
            if saved.issues:
                raise refused_answer(saved)
            return []

        result = rewrite(request, key, apply, lambda: saved.rebuild)
        return {"built": result["built"], "rebuilt": saved.rebuild}

    @app.post("/api/projects/{key}/variant")
    def choose_variant(
        request: Request, key: str, data: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        """Wiring variant → variant.yaml of a new model version, then a rebuild (notes are only
        about route edits, as in the folder viewer: none here)."""
        result = rewrite(request, key, lambda folder: save_variant(folder, data))
        return {"built": result["built"], "notes": []}


def _price_routes(app: FastAPI, auth: Auth, market_root: Path) -> None:
    """The studio price page: the studio's price_list row."""

    def studio_prices(db: Session, request: Request) -> str | None:
        studio_id = getattr(request.state, "studio_id", None)
        if studio_id is None:
            return None
        row = db.scalar(select(PriceList).where(PriceList.studio_id == studio_id))
        return row.text if row is not None else None

    def page(text: str | None, editable: bool) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="shtroba-prices-") as tmp:
            if text:
                (Path(tmp) / PRICES_FILE).write_text(text, "utf-8")
            return {**price_page(Path(tmp), market_root), "editable": editable}

    @app.get("/api/prices")
    def prices(request: Request) -> dict[str, Any]:
        """The price list of the caller's studio next to the shared market spread."""
        with auth.db() as db:
            editable = bool(getattr(request.state, "edit_prices", False))
            has_studio = getattr(request.state, "studio_id", None) is not None
            return page(studio_prices(db, request), editable and has_studio)

    @app.post("/api/prices")
    def save_price_list(
        request: Request, changes: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        """Price edits of the caller's studio; projects are not rebuilt."""
        studio_id = getattr(request.state, "studio_id", None)
        if not getattr(request.state, "edit_prices", False) or studio_id is None:
            raise HTTPException(403, "прайс правит только студия")
        with auth.db() as db:
            with tempfile.TemporaryDirectory(prefix="shtroba-prices-") as tmp:
                text = studio_prices(db, request)
                if text:
                    (Path(tmp) / PRICES_FILE).write_text(text, "utf-8")
                issues = save_prices(Path(tmp), changes)
                if issues:
                    raise HTTPException(422, "; ".join(f"{i.path}: {i.message}" for i in issues))
                text = (Path(tmp) / PRICES_FILE).read_text("utf-8")
            sync.put_price_list(db, {"studio_id": studio_id}, text)
            return page(text, True)


def install_db_routes(app: FastAPI, auth: Auth, store: ObjectStore, market_root: Path) -> None:
    """The viewer's project and price routes on the database; market.yaml (the shared market
    sample) stays a file in market_root."""

    def project_of(db: Session, request: Request, key: str) -> Project:
        """The project of the address, found as auth.check found it: by id, or by name among the
        projects the caller sees."""
        project = acc.project_by_key(db, key, auth.principal(db, request))
        if project is None:
            raise HTTPException(404, f"проекта {key} нет")
        return project

    def allowed(request: Request, action: acc.Action) -> bool:
        return acc.can(getattr(request.state, "role", None), action)

    _read_routes(app, auth, store, project_of, allowed)
    _edit_routes(app, auth, store, project_of)
    _price_routes(app, auth, market_root)
