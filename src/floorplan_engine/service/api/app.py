"""HTTP API сервиса (FastAPI). Документация — /docs.

POST /projects                        создать проект: name + файлы-источники
GET  /projects                        список проектов
GET  /projects/{id}                   состояние, этапы, готовые файлы
DELETE /projects/{id}                 удалить проект целиком
PUT  /projects/{id}/model/{file}      загрузить YAML модели (ручной анализатор)
POST /projects/{id}/analyze           запустить анализ (в фоне)
GET  /projects/{id}/questions         открытые вопросы раунда
POST /projects/{id}/answers           ответы раунда (в фоне — пересборка)
GET  /projects/{id}/report            report.json
GET  /projects/{id}/files/{path}      project.dxf, project.epd, report.md, …
GET  /projects/{id}/model/{file}      YAML модели
GET  /projects/{id}/sources/{name}    загруженный источник
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import BackgroundTasks, Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from floorplan_engine.model.intake import TextAnswer
from floorplan_engine.pipeline import OUT_DIR
from floorplan_engine.service.analysis.analyzer import OPERATOR_FILES, Analyzer, ManualAnalyzer
from floorplan_engine.service.models import AnswersIn, ProjectInfo, QuestionsOut
from floorplan_engine.service.storage import SOURCE_DIR, NotFoundError, Storage
from floorplan_engine.service.workflow import ConflictError, Workflow
from floorplan_engine.validation.report import REPORT_JSON

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def create_app(data_dir: Path, analyzer: Analyzer | None = None) -> FastAPI:
    storage = Storage(data_dir)
    flow = Workflow(storage, analyzer or ManualAnalyzer())
    app = FastAPI(title="Штроба", version="0.1.0")

    def load(project_id: str) -> ProjectInfo:
        try:
            return storage.load(project_id)
        except NotFoundError as exc:
            raise HTTPException(404, f"проекта {project_id} нет") from exc

    def report_json(project_id: str) -> dict[str, Any]:
        info = load(project_id)
        if info.state.busy:  # отчёт сейчас перезаписывается
            raise HTTPException(409, f"проект занят: {info.state.value}, повторите позже")
        path = storage.path(project_id) / OUT_DIR / REPORT_JSON
        if not path.exists():
            raise HTTPException(409, "отчёта ещё нет — сначала анализ")
        data: dict[str, Any] = json.loads(path.read_text("utf-8"))
        return data

    @app.post("/projects", status_code=201)
    async def create_project(
        name: Annotated[str, Form(min_length=1)],
        files: Annotated[list[UploadFile], File(description="PDF, JPEG, эскизы")],
    ) -> ProjectInfo:
        sources = []
        for f in files:
            content = await f.read()
            if len(content) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, f"{f.filename}: больше {MAX_UPLOAD_BYTES // 2**20} МБ")
            sources.append((f.filename or "file", content))
        return storage.create(name, sources)

    @app.get("/projects")
    def list_projects() -> list[ProjectInfo]:
        return storage.list()

    @app.get("/projects/{project_id}")
    def get_project(project_id: str) -> ProjectInfo:
        return load(project_id)

    @app.delete("/projects/{project_id}", status_code=204)
    def delete_project(project_id: str) -> None:
        info = load(project_id)
        if info.state.busy:
            raise HTTPException(409, f"проект занят: {info.state.value}, повторите позже")
        storage.delete(project_id)

    @app.get("/projects/{project_id}/model/{filename}")
    def get_model(project_id: str, filename: str) -> PlainTextResponse:
        load(project_id)
        if filename not in OPERATOR_FILES:
            raise HTTPException(400, f"файл модели — один из: {', '.join(OPERATOR_FILES)}")
        path = storage.path(project_id) / filename
        if not path.exists():
            raise HTTPException(404, f"{filename} ещё нет")
        return PlainTextResponse(path.read_text("utf-8"), media_type="text/yaml")

    @app.put("/projects/{project_id}/model/{filename}", status_code=204)
    def put_model(
        project_id: str, filename: str, text: Annotated[str, Body(media_type="text/yaml")]
    ) -> None:
        info = load(project_id)
        if filename not in OPERATOR_FILES:
            raise HTTPException(400, f"файл модели — один из: {', '.join(OPERATOR_FILES)}")
        if info.state.busy:
            raise HTTPException(409, f"проект занят: {info.state.value}")
        storage.write_model(project_id, filename, text)

    @app.post("/projects/{project_id}/analyze", status_code=202)
    def analyze(project_id: str, tasks: BackgroundTasks) -> ProjectInfo:
        load(project_id)
        try:
            info = flow.start_analysis(project_id)
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        tasks.add_task(flow.run_analysis, project_id)
        return info

    @app.get("/projects/{project_id}/questions")
    def questions(project_id: str) -> QuestionsOut:
        info = load(project_id)
        report = report_json(project_id)
        open_q = [q for q in report["questions"] if q["state"] == "open"]
        return QuestionsOut(
            project=project_id, round=info.round, state=info.state, questions=open_q
        )

    @app.post("/projects/{project_id}/answers", status_code=202)
    def answers(project_id: str, body: AnswersIn, tasks: BackgroundTasks) -> ProjectInfo:
        load(project_id)
        try:
            info = flow.submit_answers(project_id, body)
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        has_text = any(isinstance(v, TextAnswer) for v in body.answers.values())
        tasks.add_task(flow.run_answers, project_id, has_text)
        return info

    @app.get("/projects/{project_id}/report")
    def report(project_id: str) -> dict[str, Any]:
        load(project_id)
        return report_json(project_id)

    @app.get("/projects/{project_id}/files/{path:path}")
    def file(project_id: str, path: str) -> FileResponse:
        info = load(project_id)
        if path not in info.files:  # только файлы, которые собрал сервис
            raise HTTPException(404, f"файла {path} нет; есть: {', '.join(info.files)}")
        return FileResponse(storage.path(project_id) / OUT_DIR / path, filename=Path(path).name)

    @app.get("/projects/{project_id}/sources/{name}")
    def source(project_id: str, name: str) -> FileResponse:
        info = load(project_id)
        if f"{SOURCE_DIR}/{name}" not in info.sources:
            raise HTTPException(404, f"источника {name} нет")
        return FileResponse(storage.path(project_id) / SOURCE_DIR / name)

    return app
