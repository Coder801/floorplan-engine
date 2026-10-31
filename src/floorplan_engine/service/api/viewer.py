"""API просмотра собранных проектов из папки projects/ (команда `view`).

Проекты собираются в Claude Code (`/plan`, `/electrical`, `build`); здесь их показывают:
этапы, вопросы с ответами, замечания, листы, файлы out/, источники и YAML модели. Анализа
и ответов нет. Одна запись — правки проводки: линии и коробки, перетянутые на листе
проводки, пишутся в wiring.yaml проекта, и проект пересобирается (решение 2026-10-27).

GET /                                   что это за сервис и где страница
GET /api/projects                       список проектов
GET /api/projects/{name}                проект: отчёт, ответы, файлы
GET /api/projects/{name}/out/{path}     файл из out/
GET /api/projects/{name}/source/{path}  источник из source/
GET /api/projects/{name}/model/{file}   YAML модели
GET /api/projects/{name}/sheets         манифест листов из out/project.epd
GET /api/projects/{name}/sheets/{n}     лист n (1, 2…): векторные примитивы для canvas
POST /api/projects/{name}/wiring        правки проводки → wiring.yaml и пересборка
GET /api/auth/me                        кто вошёл ({"auth": false} — вход выключен)

Вход (service/api/auth.py) включается окружением SHTROBA_AUTH=on: тогда список проектов — только
видимые пришедшему, а запросы к проекту проверяются по его роли (db/access.py).

Страница просмотра — отдельный проект web/ (React + TypeScript, решение 2026-10-27): он
обращается к этому API по /api через прокси (Vite в разработке, обратный прокси при выкладке).
Здесь — только API: ни HTML, ни статики. Листы рисуются в браузере (canvas) прямо из
артефакта .epd — PNG для показа не нужны.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response

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
    save_wiring_edits,
)
from floorplan_engine.service.api.auth import Auth
from floorplan_engine.validation.issues import ELECTRICAL_FILE, ROOM_FILE, WIRING_FILE
from floorplan_engine.validation.report import REPORT_JSON

FRONT_HINT = "страница — проект web/: cd web && npm run dev → http://127.0.0.1:5173"
SOURCE_DIR = "source"
MODEL_FILES = (ROOM_FILE, ELECTRICAL_FILE, INTAKE_FILE, ANSWERS_FILE, WIRING_FILE)
# Во вкладках — ещё прайс сметы; на «сборка устарела» он не влияет (смета — отдельная команда)
SHOWN_FILES = (*MODEL_FILES, PRICES_FILE)


def _files(folder: Path) -> list[str]:
    """Файлы папки (рекурсивно), пути от неё; без скрытых."""
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
        # Модель правили после сборки: на листах старое состояние
        "stale": built is not None and bool(model_times) and max(model_times) > built,
        "stages": report.get("stages", []),
        "open_questions": sum(1 for q in questions if q.get("state") == "open"),
        # Превью плана для карточки: GET /api/projects/{name}/out/preview.svg
        "preview": (project / OUT_DIR / PREVIEW_FILE).exists(),
    }


def create_viewer(root: Path, auth: Auth | None = None) -> FastAPI:
    """API просмотра папки root; auth — вход и доступ (None — всё открыто, локально)."""
    app = FastAPI(title="Штроба · просмотр", version="0.1.0")
    if auth is not None:
        auth.install(app)
    else:

        @app.get("/api/auth/me")
        def me() -> dict[str, bool]:
            return {"auth": False}

    def project_dir(name: str) -> Path:
        path = root / name
        # Только прямые подпапки root: имя без разделителей и точек в начале
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
        return {"service": "Штроба · API просмотра", "front": FRONT_HINT, "docs": "/docs"}

    @app.get("/api/projects")
    def projects(request: Request) -> list[dict[str, Any]]:
        folders = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
        if auth is not None:
            shown = auth.visible(request, [p.name for p in folders])
            folders = [p for p in folders if p.name in shown]
        return [
            _summary(p)
            for p in folders
            if any((p / f).exists() for f in MODEL_FILES) or (p / OUT_DIR).is_dir()
        ]

    @app.get("/api/projects/{name}")
    def project(name: str) -> dict[str, Any]:
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
            # Что разобрано (intake.yaml, sources): файл от source/ и пометка разбора
            "parsed": [
                {
                    "file": str(s.get("file", "")).removeprefix(f"{SOURCE_DIR}/"),
                    "note": str(s.get("note", "")),
                }
                for s in intake.get("sources") or []
                if isinstance(s, dict)
            ],
            "model": [f for f in SHOWN_FILES if (path / f).exists()],
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
            # Страница уже JSON — отдаём как есть, без разбора и повторной сборки
            return Response(zf.read(page["file"]), media_type="application/json")

    @app.post("/api/projects/{name}/wiring")
    def save_wiring(name: str, changes: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
        """Правки проводки: {"wires": {id: {from, to, path} | null}, "boxes": {id: {room,
        group, at} | null}}, мм модели; null — вернуть автотрассу. Затем пересборка."""
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
