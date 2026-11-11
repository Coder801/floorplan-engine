"""API for viewing built projects from the projects/ folder (the `view` command).

Projects are built in Claude Code (`/plan`, `/electrical`, `build`); here they are shown:
stages, questions with answers, remarks, sheets, out/ files, sources and model YAML. There is
no analysis and no answering. Writes: wiring edits — lines and boxes dragged on the wiring
sheet are written to the project's wiring.yaml and the project is rebuilt (decision
2026-10-27), the wiring variant (variant.yaml), and the studio price list — prices of works
from the studio price page go to prices.yaml next to the projects (decision 2026-11-03).

GET /                                   what this service is and where the page is
GET /api/projects                       list of projects
GET /api/projects/{name}                project: report, answers, files
GET /api/projects/{name}/out/{path}     a file from out/
GET /api/projects/{name}/source/{path}  a source from source/
GET /api/projects/{name}/model/{file}   model YAML
GET /api/projects/{name}/sheets         sheet manifest from out/project.epd
GET /api/projects/{name}/sheets/{n}     sheet n (1, 2…): vector primitives for canvas
POST /api/projects/{name}/wiring        wiring edits → wiring.yaml and rebuild
POST /api/projects/{name}/answers       one answer → answers.yaml and rebuild (not for text)
POST /api/projects/{name}/answers/review the developer takes a client answer into account or
                                        sends it back with a comment
POST /api/projects/{name}/wizard        variant and answers together, one rebuild
GET /api/prices                         studio price page: works, own price, market spread
POST /api/prices                        studio price edits → prices.yaml next to the projects
GET /api/auth/me                        who is logged in ({"auth": false} means login is off)

Login (service/api/auth.py) is turned on by SHTROBA_AUTH=on: then the project list holds only
what the caller can see, and project requests are checked against their role (db/access.py).

The viewer page is a separate project, web/ (React + TypeScript, decision 2026-10-27): it calls
this API at /api through a proxy (Vite in development, a reverse proxy in deployment). This is
API only: no HTML and no static files. Sheets are drawn in the browser (canvas) straight from
the .epd artifact; no PNGs are needed for display.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response

from floorplan_engine import BRAND, __version__
from floorplan_engine.electrical.estimate import PRICES_FILE
from floorplan_engine.epd.thumbnail import PREVIEW_FILE
from floorplan_engine.model.intake import ANSWERS_FILE, INTAKE_FILE, AnswerNote
from floorplan_engine.pipeline import (
    ARTIFACT_FILE,
    OUT_DIR,
    PROJECT_FILE,
    AnswerSaved,
    AuditError,
    BuildResult,
    build_project,
    price_page,
    review_answer,
    save_answer,
    save_prices,
    save_wiring_edits,
    save_wizard,
)
from floorplan_engine.service.api.auth import Auth
from floorplan_engine.service.api.viewer_db import (
    answer_body,
    answer_note,
    check_manifest,
    client_side,
    install_db_routes,
    question_counts,
    refused_answer,
    review_body,
    shown,
    wizard_body,
)
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.objects import ObjectStore
from floorplan_engine.validation.answers_file import build_digest
from floorplan_engine.validation.issues import (
    ELECTRICAL_FILE,
    ROOM_FILE,
    VARIANT_FILE,
    WIRING_FILE,
)
from floorplan_engine.validation.report import REPORT_JSON

FRONT_HINT = "страница — проект web/: cd web && npm run dev → http://127.0.0.1:5173"
SOURCE_DIR = "source"
MODEL_FILES = (ROOM_FILE, ELECTRICAL_FILE, INTAKE_FILE, ANSWERS_FILE, WIRING_FILE, VARIANT_FILE)


def project_folders(root: Path) -> list[Path]:
    """Project folders in root: not hidden, with model YAML or a built out/ (the studio price list
    and other files next to them are not projects, nor are studio folders). Login links these same
    folders to an owner (auth.Auth._adopt); the other studios' projects live in their own folders
    (access.studio_folder)."""
    return sorted(p for p in root.iterdir() if _is_project(p))


def _is_project(p: Path) -> bool:
    return (
        p.is_dir()
        and not p.name.startswith(".")
        and (any((p / f).exists() for f in MODEL_FILES) or (p / OUT_DIR).is_dir())
    )


# Tabs also show the estimate price list; it does not affect "build is stale" (estimate is a
# separate command)
SHOWN_FILES = (*MODEL_FILES, PRICES_FILE)


def _files(folder: Path) -> list[str]:
    """Folder files (recursive), paths relative to it; hidden ones skipped."""
    if not folder.is_dir():
        return []
    return sorted(
        p.relative_to(folder).as_posix()
        for p in folder.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(folder).parts)
    )


def _mtime(path: Path) -> float | None:
    return path.stat().st_mtime if path.exists() else None


def _answers_of(project: Path) -> dict[str, Any]:
    path = project / ANSWERS_FILE
    data = (yaml.safe_load(path.read_text("utf-8")) or {}) if path.exists() else {}
    found = data.get("answers") if isinstance(data, dict) else None
    return found if isinstance(found, dict) else {}


def _stale(project: Path, built: float | None, report: dict[str, Any]) -> bool:
    """The model was edited after the build; a pending text answer alone changes nothing in it."""
    if built is None:
        return False
    if any(
        (t := _mtime(project / f)) is not None and t > built
        for f in MODEL_FILES
        if f != ANSWERS_FILE
    ):
        return True
    path = project / ANSWERS_FILE
    changed = (_mtime(path) or 0) > built
    text = path.read_text("utf-8") if path.exists() else None
    return changed and report.get("answers_digest") != build_digest(text)


def _summary(project: Path, client: bool = False) -> dict[str, Any]:
    report_path = project / OUT_DIR / REPORT_JSON
    report: dict[str, Any] = (
        json.loads(report_path.read_text("utf-8")) if report_path.exists() else {}
    )
    built = _mtime(report_path)
    questions = (shown(report, _answers_of(project), client)[0] or {}).get("questions", [])
    return {
        "id": project.name,  # the key in addresses; in the database viewer — the project id
        "name": project.name,
        "title": report.get("project") or project.name,
        "built": built,
        # The model was edited after the build: the sheets show the old state
        "stale": _stale(project, built, report),
        "stages": report.get("stages", []),
        **question_counts(questions),
        # Plan preview for the card: GET /api/projects/{name}/out/preview.svg
        "preview": (project / OUT_DIR / PREVIEW_FILE).exists(),
    }


def _allowed(auth: Auth | None, request: Request, action: acc.Action) -> bool:
    """Project permission: with login off everything is allowed; otherwise by role (auth.check)."""
    return auth is None or acc.can(getattr(request.state, "role", None), action)


def _read_routes(
    app: FastAPI, root: Path, auth: Auth | None, project_dir: Callable[[Request, str], Path]
) -> None:
    """What the viewer shows: the service, projects, sheets."""

    @app.get("/")
    def about() -> dict[str, str]:
        return {"service": f"{BRAND} · API просмотра", "front": FRONT_HINT, "docs": "/docs"}

    @app.get("/api/projects")
    def projects(request: Request) -> list[dict[str, Any]]:
        folders = project_folders(root)
        if auth is not None:
            shown = auth.project_folders(request, [p.name for p in folders])
            folders = sorted(
                (p for name, folder in shown.items() if _is_project(p := root / folder / name)),
                key=lambda p: p.name,
            )
        return [_summary(p, client_side(request)) for p in folders]

    def allowed(request: Request, action: acc.Action) -> bool:
        return _allowed(auth, request, action)

    @app.get("/api/projects/{name}")
    def project(name: str, request: Request) -> dict[str, Any]:
        path = project_dir(request, name)
        report_path = path / OUT_DIR / REPORT_JSON
        built = json.loads(report_path.read_text("utf-8")) if report_path.exists() else None
        report, answers = shown(built, _answers_of(path), client_side(request))
        out = _files(path / OUT_DIR)
        intake_path = path / INTAKE_FILE
        intake = (
            (yaml.safe_load(intake_path.read_text("utf-8")) or {}) if intake_path.exists() else {}
        )
        return {
            **_summary(path, client_side(request)),
            "report": report,
            "answers": answers,
            "artifact": ARTIFACT_FILE in out,
            "dxf": PROJECT_FILE if PROJECT_FILE in out else None,
            "files": [f for f in out if "/" not in f],
            "sources": _files(path / SOURCE_DIR),
            # What was parsed (intake.yaml, sources): file relative to source/ and the parse note
            "parsed": [
                {
                    "file": str(s.get("file", "")).removeprefix(f"{SOURCE_DIR}/"),
                    "note": str(s.get("note", "")),
                }
                for s in intake.get("sources") or []
                if isinstance(s, dict)
            ],
            "model": [f for f in SHOWN_FILES if (path / f).exists()],
            "work": False,  # installation by tasks lives in the database (viewer_db, api/work.py)
            # What the caller may do: edit routes and choose a variant (studio, "Мой ремонт")
            "can": {
                "edit_wiring": allowed(request, "edit_wiring"),
                "choose_variant": allowed(request, "choose_variant"),
                "answer": allowed(request, "answer"),
                "review": allowed(request, "review"),
            },
        }

    def artifact(request: Request, name: str) -> zipfile.ZipFile:
        path = project_dir(request, name) / OUT_DIR / ARTIFACT_FILE
        if not path.is_file():
            raise HTTPException(404, f"нет {OUT_DIR}/{ARTIFACT_FILE} — сначала build")
        return zipfile.ZipFile(path)

    @app.get("/api/projects/{name}/sheets")
    def sheets(request: Request, name: str) -> dict[str, Any]:
        with artifact(request, name) as zf:
            return check_manifest(zf)

    @app.get("/api/projects/{name}/sheets/{index}")
    def sheet(request: Request, name: str, index: int) -> Response:
        with artifact(request, name) as zf:
            pages = check_manifest(zf)["pages"]
            page = next((p for p in pages if p["index"] == index), None)
            if page is None:
                raise HTTPException(404, f"листа {index} нет")
            # The page is already JSON: return it as is, without parsing or rebuilding
            return Response(zf.read(page["file"]), media_type="application/json")


def _note(auth: Auth | None, request: Request) -> AnswerNote:
    """Who answers and when, for the log of answers.yaml; login off: nobody."""
    who = None
    if auth is not None:
        with auth.db() as db:
            who = auth.principal(db, request)
    return answer_note(who)


def _build(path: Path) -> BuildResult:
    """Rebuild the project after a change; a failed audit of the artifact is 500."""
    try:
        return build_project(path)
    except AuditError as exc:
        raise HTTPException(500, str(exc)) from exc


def _rebuilt(path: Path, saved: AnswerSaved) -> dict[str, Any]:
    """After an answers.yaml change: a refused one is 422, a rebuild only if it needs one."""
    if saved.issues:
        raise refused_answer(saved)
    if not saved.rebuild:
        return {"built": False, "rebuilt": False}
    return {"built": _build(path).built, "rebuilt": True}


def _edit_routes(
    app: FastAPI, auth: Auth | None, project_dir: Callable[[Request, str], Path]
) -> None:
    """What the viewer writes to a project: wiring edits, answers, the variant."""

    @app.post("/api/projects/{name}/wiring")
    def save_wiring(
        request: Request, name: str, changes: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        """Wiring edits: {"wires": {id: {from, to, path} | null}, "boxes": {id: {room, group, at} |
        null}}, model mm; null restores the auto route. Then a rebuild."""
        path = project_dir(request, name)
        issues = save_wiring_edits(path, changes)
        if issues:
            raise HTTPException(422, "; ".join(f"{i.path}: {i.message}" for i in issues))
        result = _build(path)
        notes = [i for i in result.assessment.report.issues if i.file == WIRING_FILE]
        return {"built": result.built, "notes": [f"{i.path}: {i.message}" for i in notes]}

    @app.post("/api/projects/{name}/answers")
    def answer(
        request: Request, name: str, data: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        """One answer: {id, answer} → answers.yaml, null removes it; then a rebuild, unless the
        answer is text waiting for the analyzer (it changes nothing in the sheets)."""
        path = project_dir(request, name)
        qid, raw = answer_body(data)
        saved = save_answer(path, qid, raw, _note(auth, request), client=client_side(request))
        return _rebuilt(path, saved)

    @app.post("/api/projects/{name}/answers/review")
    def review(
        request: Request, name: str, data: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        """The developer reviews a client answer: {id, outcome: resolve | return, comment?} →
        answers.yaml; a rebuild when it is taken into account."""
        path = project_dir(request, name)
        qid, outcome, comment = review_body(data)
        if not _allowed(auth, request, "review"):
            raise HTTPException(403, "нет права на это действие")
        saved = review_answer(path, qid, outcome, comment, _note(auth, request))
        return _rebuilt(path, saved)

    @app.post("/api/projects/{name}/wizard")
    def wizard(
        request: Request, name: str, data: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        """The setup wizard: {variant?, answers?} → variant.yaml and answers.yaml, one rebuild."""
        path = project_dir(request, name)
        variant, items = wizard_body(data, lambda action: _allowed(auth, request, action))
        saved = save_wizard(path, variant, items, _note(auth, request), client=client_side(request))
        return _rebuilt(path, saved)


def _price_routes(
    app: FastAPI, root: Path, auth: Auth | None, studio_dir: Callable[[Request], Path]
) -> None:
    """The studio price page."""

    def edit_prices(request: Request) -> bool:
        """The studio price list is edited by the studio: login off — anyone; else auth.check."""
        return auth is None or getattr(request.state, "edit_prices", False)

    @app.get("/api/prices")
    def prices(request: Request) -> dict[str, Any]:
        """Studio price page: electrical works with the price of the caller's studio (prices.yaml
        in the studio folder) and the market spread (market.yaml in the root, shared), the period
        and sources of market prices."""
        return {**price_page(studio_dir(request), root), "editable": edit_prices(request)}

    @app.post("/api/prices")
    def save_price_list(
        request: Request, changes: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        """Price edits: {"items": {key: price | null}, "date"?} → prices.yaml; projects are not
        rebuilt (the estimate is rebuilt by build or estimate)."""
        if not edit_prices(request):
            raise HTTPException(403, "прайс правит только студия")
        issues = save_prices(studio_dir(request), changes)
        if issues:
            raise HTTPException(422, "; ".join(f"{i.path}: {i.message}" for i in issues))
        return {**price_page(studio_dir(request), root), "editable": True}


def _file_routes(
    app: FastAPI, project_dir: Callable[[Request, str], Path], inside: Callable[[Path, str], Path]
) -> None:
    """Project files: out/, sources, model YAML."""

    @app.get("/api/projects/{name}/out/{rel:path}")
    def out_file(request: Request, name: str, rel: str) -> FileResponse:
        return FileResponse(inside(project_dir(request, name) / OUT_DIR, rel))

    @app.get("/api/projects/{name}/source/{rel:path}")
    def source_file(request: Request, name: str, rel: str) -> FileResponse:
        return FileResponse(inside(project_dir(request, name) / SOURCE_DIR, rel))

    @app.get("/api/projects/{name}/model/{filename}")
    def model(request: Request, name: str, filename: str) -> PlainTextResponse:
        if filename not in SHOWN_FILES:
            raise HTTPException(400, f"файл модели — один из: {', '.join(SHOWN_FILES)}")
        path = inside(project_dir(request, name), filename)
        return PlainTextResponse(path.read_text("utf-8"), media_type="text/yaml")


def create_viewer(
    root: Path, auth: Auth | None = None, store: ObjectStore | None = None
) -> FastAPI:
    """Viewer API for folder root; auth is login and access (None means everything is open,
    locally). With store, projects come from the database and file storage (viewer_db.py; login
    is required), root keeps only the shared market sample (market.yaml)."""
    app = FastAPI(title=f"{BRAND} · просмотр", version=__version__)
    if store is not None:
        if auth is None:
            raise ValueError("проекты из базы — только со входом (SHTROBA_AUTH=on)")
        auth.install(app)

        @app.get("/")
        def about_db() -> dict[str, str]:
            return {"service": f"{BRAND} · API просмотра", "front": FRONT_HINT, "docs": "/docs"}

        install_db_routes(app, auth, store, root)
        return app
    if auth is not None:
        auth.folders = lambda: [p.name for p in project_folders(root)]
        auth.install(app)
    else:

        @app.get("/api/auth/me")
        def me() -> dict[str, bool]:
            return {"auth": False}

    def studio_dir(request: Request) -> Path:
        """Folder of the caller's studio (auth.check: request.state.folder); login off — root."""
        return root / getattr(request.state, "folder", "")

    def project_dir(request: Request, name: str) -> Path:
        path = studio_dir(request) / name
        # Only direct subfolders of the studio folder: a name without separators or a leading dot
        if "/" in name or "\\" in name or name.startswith(".") or not path.is_dir():
            raise HTTPException(404, f"проекта {name} нет")
        return path

    def inside(base: Path, rel: str) -> Path:
        path = (base / rel).resolve()
        if not path.is_relative_to(base.resolve()) or not path.is_file():
            raise HTTPException(404, f"файла {rel} нет")
        return path

    _read_routes(app, root, auth, project_dir)
    _edit_routes(app, auth, project_dir)
    _price_routes(app, root, auth, studio_dir)
    _file_routes(app, project_dir, inside)
    return app
