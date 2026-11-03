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
POST /api/projects/{name}/variant       wiring variant → variant.yaml and rebuild
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
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response

from floorplan_engine import BRAND, __version__
from floorplan_engine.electrical.estimate import PRICES_FILE
from floorplan_engine.epd.artifact import FORMAT_VERSION, MANIFEST
from floorplan_engine.epd.thumbnail import PREVIEW_FILE
from floorplan_engine.model.intake import ANSWERS_FILE, INTAKE_FILE
from floorplan_engine.pipeline import (
    ARTIFACT_FILE,
    OUT_DIR,
    PROJECT_FILE,
    AuditError,
    build_project,
    price_page,
    save_prices,
    save_variant,
    save_wiring_edits,
)
from floorplan_engine.service.api.auth import Auth
from floorplan_engine.service.db import access as acc
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
    and
    other files next to them are not projects). Login links these same folders to an owner
    (auth.Auth._adopt)."""
    return sorted(
        p
        for p in root.iterdir()
        if p.is_dir()
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


def _summary(project: Path) -> dict[str, Any]:
    report_path = project / OUT_DIR / REPORT_JSON
    report: dict[str, Any] = (
        json.loads(report_path.read_text("utf-8")) if report_path.exists() else {}
    )
    built = _mtime(report_path)
    model_times = [t for f in MODEL_FILES if (t := _mtime(project / f)) is not None]
    questions = report.get("questions", [])
    return {
        "name": project.name,
        "title": report.get("project") or project.name,
        "built": built,
        # The model was edited after the build: the sheets show the old state
        "stale": built is not None and bool(model_times) and max(model_times) > built,
        "stages": report.get("stages", []),
        "open_questions": sum(1 for q in questions if q.get("state") == "open"),
        # Plan preview for the card: GET /api/projects/{name}/out/preview.svg
        "preview": (project / OUT_DIR / PREVIEW_FILE).exists(),
    }


def create_viewer(root: Path, auth: Auth | None = None) -> FastAPI:
    """Viewer API for folder root; auth is login and access (None means everything is open,
    locally).
    """
    app = FastAPI(title=f"{BRAND} · просмотр", version=__version__)
    if auth is not None:
        auth.folders = lambda: [p.name for p in project_folders(root)]
        auth.install(app)
    else:

        @app.get("/api/auth/me")
        def me() -> dict[str, bool]:
            return {"auth": False}

    def project_dir(name: str) -> Path:
        path = root / name
        # Only direct subfolders of root: a name without separators or a leading dot
        if "/" in name or "\\" in name or name.startswith(".") or not path.is_dir():
            raise HTTPException(404, f"проекта {name} нет")
        return path

    def inside(base: Path, rel: str) -> Path:
        path = (base / rel).resolve()
        if not path.is_relative_to(base.resolve()) or not path.is_file():
            raise HTTPException(404, f"файла {rel} нет")
        return path

    @app.get("/")
    def about() -> dict[str, str]:
        return {"service": f"{BRAND} · API просмотра", "front": FRONT_HINT, "docs": "/docs"}

    @app.get("/api/projects")
    def projects(request: Request) -> list[dict[str, Any]]:
        folders = project_folders(root)
        if auth is not None:
            shown = auth.visible(request, [p.name for p in folders])
            folders = [p for p in folders if p.name in shown]
        return [_summary(p) for p in folders]

    def allowed(request: Request, action: acc.Action) -> bool:
        """Project permission: with login off everything is allowed; otherwise by role
        (auth.check).
        """
        return auth is None or acc.can(getattr(request.state, "role", None), action)

    @app.get("/api/projects/{name}")
    def project(name: str, request: Request) -> dict[str, Any]:
        path = project_dir(name)
        report_path = path / OUT_DIR / REPORT_JSON
        report = json.loads(report_path.read_text("utf-8")) if report_path.exists() else None
        answers_path = path / ANSWERS_FILE
        answers = (
            (yaml.safe_load(answers_path.read_text("utf-8")) or {}).get("answers", {})
            if answers_path.exists()
            else {}
        )
        out = _files(path / OUT_DIR)
        intake_path = path / INTAKE_FILE
        intake = (
            (yaml.safe_load(intake_path.read_text("utf-8")) or {}) if intake_path.exists() else {}
        )
        return {
            **_summary(path),
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
            # What the caller may do: edit routes and choose a variant (studio, "Мой ремонт")
            "can": {
                "edit_wiring": allowed(request, "edit_wiring"),
                "choose_variant": allowed(request, "choose_variant"),
            },
        }

    def artifact(name: str) -> zipfile.ZipFile:
        path = project_dir(name) / OUT_DIR / ARTIFACT_FILE
        if not path.is_file():
            raise HTTPException(404, f"нет {OUT_DIR}/{ARTIFACT_FILE} — сначала build")
        return zipfile.ZipFile(path)

    def manifest(zf: zipfile.ZipFile) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(zf.read(MANIFEST))
        if data.get("version") != FORMAT_VERSION:
            raise HTTPException(
                409, f"версия .epd {data.get('version')}, поддерживается {FORMAT_VERSION}"
            )
        return data

    @app.get("/api/projects/{name}/sheets")
    def sheets(name: str) -> dict[str, Any]:
        with artifact(name) as zf:
            return manifest(zf)

    @app.get("/api/projects/{name}/sheets/{index}")
    def sheet(name: str, index: int) -> Response:
        with artifact(name) as zf:
            pages = manifest(zf)["pages"]
            page = next((p for p in pages if p["index"] == index), None)
            if page is None:
                raise HTTPException(404, f"листа {index} нет")
            # The page is already JSON: return it as is, without parsing or rebuilding
            return Response(zf.read(page["file"]), media_type="application/json")

    @app.post("/api/projects/{name}/wiring")
    def save_wiring(name: str, changes: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
        """Wiring edits: {"wires": {id: {from, to, path} | null}, "boxes": {id: {room, group, at} |
        null}}, model mm; null restores the auto route. Then a rebuild."""
        path = project_dir(name)
        issues = save_wiring_edits(path, changes)
        if issues:
            raise HTTPException(422, "; ".join(f"{i.path}: {i.message}" for i in issues))
        try:
            result = build_project(path)
        except AuditError as exc:
            raise HTTPException(500, str(exc)) from exc
        notes = [i for i in result.assessment.report.issues if i.file == WIRING_FILE]
        return {"built": result.built, "notes": [f"{i.path}: {i.message}" for i in notes]}

    @app.post("/api/projects/{name}/variant")
    def choose_variant(name: str, data: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
        """Wiring variant: {mode, route, distribution} → variant.yaml, then a rebuild.
        Each variant has its own route edits (wiring.yaml, variants)."""
        path = project_dir(name)
        issues = save_variant(path, data)
        if issues:
            raise HTTPException(422, "; ".join(f"{i.path}: {i.message}" for i in issues))
        try:
            result = build_project(path)
        except AuditError as exc:
            raise HTTPException(500, str(exc)) from exc
        return {"built": result.built, "notes": []}

    def edit_prices(request: Request) -> bool:
        """The studio price list is edited by the studio: login off — anyone; else auth.check."""
        return auth is None or getattr(request.state, "edit_prices", False)

    @app.get("/api/prices")
    def prices(request: Request) -> dict[str, Any]:
        """Studio price page: electrical works with the studio price (prices.yaml next to the
        projects) and the market spread (market.yaml), the period and sources of market prices."""
        return {**price_page(root), "editable": edit_prices(request)}

    @app.post("/api/prices")
    def save_price_list(
        request: Request, changes: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        """Price edits: {"items": {key: price | null}, "date"?} → prices.yaml; projects are not
        rebuilt (the estimate is rebuilt by build or estimate)."""
        if not edit_prices(request):
            raise HTTPException(403, "прайс правит только студия")
        issues = save_prices(root, changes)
        if issues:
            raise HTTPException(422, "; ".join(f"{i.path}: {i.message}" for i in issues))
        return {**price_page(root), "editable": True}

    @app.get("/api/projects/{name}/out/{rel:path}")
    def out_file(name: str, rel: str) -> FileResponse:
        return FileResponse(inside(project_dir(name) / OUT_DIR, rel))

    @app.get("/api/projects/{name}/source/{rel:path}")
    def source_file(name: str, rel: str) -> FileResponse:
        return FileResponse(inside(project_dir(name) / SOURCE_DIR, rel))

    @app.get("/api/projects/{name}/model/{filename}")
    def model(name: str, filename: str) -> PlainTextResponse:
        if filename not in SHOWN_FILES:
            raise HTTPException(400, f"файл модели — один из: {', '.join(SHOWN_FILES)}")
        path = inside(project_dir(name), filename)
        return PlainTextResponse(path.read_text("utf-8"), media_type="text/yaml")

    return app
