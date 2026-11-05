"""Service HTTP API (FastAPI). Docs at /docs.

POST /projects                        create a project: name + source files
GET  /projects                        list projects
GET  /projects/{id}                   state, stages, ready files
DELETE /projects/{id}                 delete the whole project
PUT  /projects/{id}/model/{file}      upload a model YAML (manual analyzer)
POST /projects/{id}/analyze           start analysis (in the background)
GET  /projects/{id}/questions         open questions of the round
POST /projects/{id}/answers           round answers (rebuild in the background)
GET  /projects/{id}/report            report.json
GET  /projects/{id}/files/{path}      project.dxf, project.epd, report.md, …
GET  /projects/{id}/model/{file}      model YAML
GET  /projects/{id}/sources/{name}    an uploaded source

With `auth` every /projects request goes through project_guard.check; without it the API is open,
and `floorplan-engine serve` then listens only on the local address.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from floorplan_engine import BRAND, __version__
from floorplan_engine.pipeline import OUT_DIR
from floorplan_engine.service.analysis.analyzer import OPERATOR_FILES, Analyzer, ManualAnalyzer
from floorplan_engine.service.api import project_guard
from floorplan_engine.service.api.auth import Auth
from floorplan_engine.service.db.access import AccessError
from floorplan_engine.service.models import AnswersIn, ProjectInfo, QuestionsOut
from floorplan_engine.service.storage import SOURCE_DIR, NotFoundError, Storage
from floorplan_engine.service.tasks import WORKERS, TaskQueue
from floorplan_engine.service.workflow import ConflictError, Workflow
from floorplan_engine.validation.report import REPORT_JSON

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def create_app(
    data_dir: Path,
    analyzer: Analyzer | None = None,
    auth: Auth | None = None,
    workers: int = WORKERS,
) -> FastAPI:
    """Service API for folder data_dir; auth is login and access (None means everything is open,
    locally); workers=0 runs analysis and builds inside the request (tasks.TaskQueue)."""
    storage = Storage(data_dir)
    flow = Workflow(storage, analyzer or ManualAnalyzer())
    tasks = TaskQueue(flow.run_task, workers)
    app = FastAPI(title=BRAND, version=__version__)
    app.state.tasks = tasks

    def resume() -> None:
        tasks.start()
        for project_id in flow.recover():
            tasks.submit(project_id)

    app.router.on_startup.append(resume)
    app.router.on_shutdown.append(tasks.stop)
    if auth is not None:
        guard = auth

        @app.middleware("http")
        async def project_access(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            denied = await run_in_threadpool(project_guard.check, guard, request)
            return denied if denied is not None else await call_next(request)

        # After this middleware: added later, it runs first and gives it request.session
        auth.install(app)

    def load(project_id: str) -> ProjectInfo:
        try:
            return storage.load(project_id)
        except NotFoundError as exc:
            raise HTTPException(404, f"проекта {project_id} нет") from exc

    def refuse_busy(info: ProjectInfo) -> None:
        if info.state.busy:
            raise HTTPException(409, f"проект занят: {info.state.value}, повторите позже")

    def refuse_foreign_file(filename: str) -> None:
        if filename not in OPERATOR_FILES:
            raise HTTPException(400, f"файл модели — один из: {', '.join(OPERATOR_FILES)}")

    def start_task(project_id: str, begin: Callable[[], ProjectInfo]) -> ProjectInfo:
        """Mark the project busy with `begin` and queue its background part."""
        load(project_id)
        try:
            info = begin()
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        tasks.submit(project_id)
        return info

    def report_json(project_id: str) -> dict[str, Any]:
        refuse_busy(load(project_id))  # the report is being rewritten now
        path = storage.path(project_id) / OUT_DIR / REPORT_JSON
        if not path.exists():
            raise HTTPException(409, "отчёта ещё нет — сначала анализ")
        data: dict[str, Any] = json.loads(path.read_text("utf-8"))
        return data

    @app.post("/projects", status_code=201)
    async def create_project(
        request: Request,
        name: Annotated[str, Form(min_length=1, max_length=200)],
        files: Annotated[list[UploadFile], File(description="PDF, JPEG, эскизы")],
    ) -> ProjectInfo:
        sources = []
        for f in files:
            content = await f.read()
            if len(content) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, f"{f.filename}: больше {MAX_UPLOAD_BYTES // 2**20} МБ")
            sources.append((f.filename or "file", content))
        info = storage.create(name, sources)
        if auth is not None:
            try:
                await run_in_threadpool(project_guard.register, auth, request, info)
            except Exception as exc:  # a folder without a row would be nobody's
                storage.delete(info.id)
                if isinstance(exc, AccessError):
                    raise HTTPException(403, str(exc)) from exc
                raise
        return info

    @app.get("/projects")
    def list_projects(request: Request) -> list[ProjectInfo]:
        projects = storage.list()
        if auth is None:
            return projects
        shown = project_guard.visible(auth, request, [p.id for p in projects])
        return [p for p in projects if p.id in shown]

    @app.get("/projects/{project_id}")
    def get_project(project_id: str) -> ProjectInfo:
        return load(project_id)

    @app.delete("/projects/{project_id}", status_code=204)
    def delete_project(request: Request, project_id: str) -> None:
        refuse_busy(load(project_id))
        storage.delete(project_id)
        if auth is not None:
            project_guard.forget(auth, request, project_id)

    @app.get("/projects/{project_id}/model/{filename}")
    def get_model(project_id: str, filename: str) -> PlainTextResponse:
        load(project_id)
        refuse_foreign_file(filename)
        path = storage.path(project_id) / filename
        if not path.exists():
            raise HTTPException(404, f"{filename} ещё нет")
        return PlainTextResponse(path.read_text("utf-8"), media_type="text/yaml")

    @app.put("/projects/{project_id}/model/{filename}", status_code=204)
    def put_model(
        project_id: str, filename: str, text: Annotated[str, Body(media_type="text/yaml")]
    ) -> None:
        info = load(project_id)
        refuse_foreign_file(filename)
        if info.state.busy:
            raise HTTPException(409, f"проект занят: {info.state.value}")
        storage.write_model(project_id, filename, text)

    @app.post("/projects/{project_id}/analyze", status_code=202)
    def analyze(project_id: str) -> ProjectInfo:
        return start_task(project_id, lambda: flow.start_analysis(project_id))

    @app.get("/projects/{project_id}/questions")
    def questions(project_id: str) -> QuestionsOut:
        info = load(project_id)
        report = report_json(project_id)
        open_q = [q for q in report["questions"] if q["state"] == "open"]
        return QuestionsOut(
            project=project_id, round=info.round, state=info.state, questions=open_q
        )

    @app.post("/projects/{project_id}/answers", status_code=202)
    def answers(project_id: str, body: AnswersIn) -> ProjectInfo:
        return start_task(project_id, lambda: flow.submit_answers(project_id, body))

    @app.get("/projects/{project_id}/report")
    def report(project_id: str) -> dict[str, Any]:
        load(project_id)
        return report_json(project_id)

    @app.get("/projects/{project_id}/files/{path:path}")
    def file(project_id: str, path: str) -> FileResponse:
        info = load(project_id)
        if path not in info.files:  # only files built by the service
            raise HTTPException(404, f"файла {path} нет; есть: {', '.join(info.files)}")
        return FileResponse(storage.path(project_id) / OUT_DIR / path, filename=Path(path).name)

    @app.get("/projects/{project_id}/sources/{name}")
    def source(project_id: str, name: str) -> FileResponse:
        info = load(project_id)
        if f"{SOURCE_DIR}/{name}" not in info.sources:
            raise HTTPException(404, f"источника {name} нет")
        return FileResponse(storage.path(project_id) / SOURCE_DIR / name)

    return app
