"""Installation by tasks in the viewer from the database (docs/work-tasks.md, "API"): the work plan
of a project, its tasks, photos, comments and payments. Only with the database: the folder viewer
has no tasks and answers `work: false` in the project card.

The rules live in db/work.py; here — the routes, reading the bodies and the answer. Every write
answers with the whole work state, as GET /work does, so the page just replaces it. The access
middleware (auth.Auth.check) lets anyone who sees the project through (view) and puts the project
role into request.state.role; each route checks its own right by that role.
"""

from __future__ import annotations

import json
import mimetypes
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from floorplan_engine.epd.artifact import MANIFEST
from floorplan_engine.pipeline import ARTIFACT_FILE
from floorplan_engine.service import project_store as ps
from floorplan_engine.service.api.auth import Auth
from floorplan_engine.service.db import repositories as repo
from floorplan_engine.service.db import work
from floorplan_engine.service.db import work_records as records
from floorplan_engine.service.db.models import (
    AppUser,
    Build,
    ModelVersion,
    Project,
    WorkLine,
    WorkPlan,
    WorkTask,
)
from floorplan_engine.service.objects import ObjectStore

# Photo types by extension, when the browser sends none (HEIC from a phone often comes so)
EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".pdf": "application/pdf",
}


def draft_of(session: Session, store: ObjectStore, build: Build | None) -> dict[str, Any] | None:
    """The work_plan draft of a build's .epd; None — no .epd or no draft in it (an older build or
    an estimate without lines)."""
    f = ps.build_file(session, build, ARTIFACT_FILE) if build is not None else None
    if f is None:
        return None
    local = store.local_path(f.object_key)
    try:
        source = local if local is not None else BytesIO(store.get(f.object_key))
        with zipfile.ZipFile(source) as zf:
            manifest = json.loads(zf.read(MANIFEST))
    except (FileNotFoundError, KeyError, zipfile.BadZipFile):
        return None
    draft = manifest.get("work_plan") if isinstance(manifest, dict) else None
    return draft if isinstance(draft, dict) and draft.get("tasks") else None


def _at(t: datetime | None) -> str | None:
    return t.isoformat(timespec="seconds") if t is not None else None


def _person(user: AppUser | None) -> dict[str, str] | None:
    if user is None:
        return None
    return {"id": str(user.id), "name": user.name or user.email or user.phone or ""}


def _line_json(line: WorkLine) -> dict[str, Any]:
    return {
        "id": str(line.id),
        "key": line.key,
        "kind": line.kind,
        "title": line.title,
        "unit": line.unit,
        "plan_qty": line.plan_qty,
        "fact_qty": line.fact_qty,
        "price": line.price,
        "sum": work.line_sum(line),
    }


def task_json(session: Session, project: Project, plan: WorkPlan, task: WorkTask) -> dict[str, Any]:
    t = work.totals(task)
    base = f"/api/projects/{project.id}/work/photos"
    return {
        "id": str(task.id),
        "key": task.key,
        "domain": task.domain,
        "position": task.position,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "extra": task.extra,
        "photo": task.photo,
        "result": task.result,
        "after": task.after,
        "waiting": [{"id": str(w.id), "title": w.title} for w in work.waiting(task, plan.tasks)],
        "assignee": _person(session.get(AppUser, task.assignee_id) if task.assignee_id else None),
        "materials_included": task.materials_included,
        "money_editable": work.money_editable(plan, task),
        "lines": [_line_json(ln) for ln in task.lines],
        "work_total": t.work,
        "material_total": t.material,
        "total": t.total,
        "paid": t.paid,
        "settled": t.settled,
        "unpriced": t.unpriced,
        "photos": [
            {
                "id": str(p.id),
                "url": f"{base}/{p.id}",
                "file_name": p.file_name,
                "content_type": p.content_type,
                "size": p.size,
                "caption": p.caption,
                "author": p.author_label,
                "user_id": str(p.user_id) if p.user_id else None,
                "created_at": _at(p.created_at),
            }
            for p in task.photos
        ],
        "comments": [
            {
                "id": str(c.id),
                "kind": c.kind,
                "status": c.status,
                "text": c.text,
                "author": c.author_label,
                "user_id": str(c.user_id) if c.user_id else None,
                "created_at": _at(c.created_at),
            }
            for c in task.comments
        ],
        "payments": [
            {
                "id": str(p.id),
                "amount": p.amount,
                "paid_on": p.paid_on.isoformat(),
                "note": p.note,
                "created_at": _at(p.created_at),
            }
            for p in task.payments
        ],
    }


def _version(session: Session, version_id: Any) -> int | None:
    row = session.get(ModelVersion, version_id) if version_id is not None else None
    return row.version if row is not None else None


def work_state(
    session: Session, store: ObjectStore, project: Project, actor: work.Actor
) -> dict[str, Any]:
    """GET /work: the plan with its tasks and totals, whether the latest build has a draft, who
    can be assigned (to the studio) and what the caller may do."""
    session.flush()
    session.expire_all()  # what the write has just changed, as the database has it
    plan = work.current_plan(session, project)
    latest = repo.latest_model(session, project.id)
    out: dict[str, Any] = {
        "plan": None,
        "tasks": [],
        "draft_available": draft_of(session, store, ps.latest_build(session, project)) is not None,
        "model_version": latest.version if latest is not None else None,
        "assignees": [
            p
            for u in (work.assignees(session, project) if actor.can("work_manage") else [])
            if (p := _person(u)) is not None
        ],
        "can": {a: actor.can(a) for a in ("work_do", "work_accept", "work_manage")},
    }
    if plan is None:
        return out
    tasks = [task_json(session, project, plan, t) for t in plan.tasks]
    approver = session.get(AppUser, plan.approved_by) if plan.approved_by else None
    out["plan"] = {
        "id": str(plan.id),
        "state": plan.state,
        "currency": plan.currency,
        "model_version": _version(session, plan.model_version_id),
        "created_at": _at(plan.created_at),
        "approved_at": _at(plan.approved_at),
        "approved_by": (approver.name or approver.email) if approver else plan.approved_label,
        "closed_at": _at(plan.closed_at),
        "totals": {
            "work": round(sum(t["work_total"] for t in tasks), 2),
            "material": round(sum(t["material_total"] for t in tasks), 2),
            "total": round(sum(t["total"] for t in tasks), 2),
            "paid": round(sum(t["paid"] for t in tasks), 2),
            "tasks": len(tasks),
            "accepted": sum(1 for t in tasks if t["status"] == "accepted"),
            "settled": sum(1 for t in tasks if t["settled"]),
            "unpriced": sum(t["unpriced"] for t in tasks),
        },
    }
    out["tasks"] = tasks
    return out


def _content_type(upload: UploadFile) -> str:
    sent = (upload.content_type or "").split(";")[0].strip().lower()
    if sent in records.PHOTO_TYPES:
        return sent
    return EXTENSIONS.get(Path(upload.filename or "").suffix.lower(), sent)


def install_work_routes(
    app: FastAPI,
    auth: Auth,
    store: ObjectStore,
    project_of: Callable[[Session, Request, str], Project],
) -> None:
    """The /api/projects/{key}/work routes (docs/work-tasks.md, "API")."""

    @contextmanager
    def acting(
        request: Request, key: str
    ) -> Iterator[tuple[Session, Project, WorkPlan | None, work.Actor]]:
        """The project, its current plan and the caller; a broken rule — its HTTP status."""
        with auth.db() as db:
            project = project_of(db, request, key)
            role = getattr(request.state, "role", None)
            actor = work.actor_of(auth.principal(db, request), role)
            try:
                yield db, project, work.current_plan(db, project), actor
            except work.WorkError as exc:
                raise HTTPException(exc.status, str(exc)) from exc

    def plan_of(plan: WorkPlan | None) -> WorkPlan:
        if plan is None:
            raise work.WorkError("плана работ ещё нет", 404)
        return plan

    @app.get("/api/projects/{key}/work")
    def get_work(request: Request, key: str) -> dict[str, Any]:
        with acting(request, key) as (db, project, _, actor):
            return work_state(db, store, project, actor)

    @app.post("/api/projects/{key}/work/plan")
    def create_plan(request: Request, key: str) -> dict[str, Any]:
        """A draft plan from the latest build's work_plan."""
        with acting(request, key) as (db, project, _, actor):
            build = ps.latest_build(db, project)
            work.create_plan(db, project, build, draft_of(db, store, build), actor)
            return work_state(db, store, project, actor)

    @app.post("/api/projects/{key}/work/plan/{action}")
    def plan_action(request: Request, key: str, action: str) -> dict[str, Any]:
        """propose | approve | close | discard."""
        with acting(request, key) as (db, project, plan, actor):
            work.plan_action(db, project, plan, action, actor)
            return work_state(db, store, project, actor)

    @app.post("/api/projects/{key}/work/tasks")
    def add_task(
        request: Request, key: str, data: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        with acting(request, key) as (db, project, plan, actor):
            work.add_task(db, project, plan, data, actor)
            return work_state(db, store, project, actor)

    @app.patch("/api/projects/{key}/work/tasks/{task_id}")
    def edit_task(
        request: Request, key: str, task_id: str, data: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        with acting(request, key) as (db, project, plan, actor):
            task = work.task_of(db, plan, task_id)
            work.edit_task(db, project, plan_of(plan), task, data, actor)
            return work_state(db, store, project, actor)

    @app.delete("/api/projects/{key}/work/tasks/{task_id}")
    def delete_task(request: Request, key: str, task_id: str) -> dict[str, Any]:
        with acting(request, key) as (db, project, plan, actor):
            task = work.task_of(db, plan, task_id)
            work.delete_task(db, project, plan_of(plan), task, actor)
            return work_state(db, store, project, actor)

    @app.post("/api/projects/{key}/work/tasks/{task_id}/status")
    def change_status(
        request: Request, key: str, task_id: str, data: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        """{to, comment?}."""
        with acting(request, key) as (db, project, plan, actor):
            task = work.task_of(db, plan, task_id)
            to, comment = data.get("to"), data.get("comment")
            work.change_status(db, project, plan_of(plan), task, to, comment, actor)
            return work_state(db, store, project, actor)

    @app.patch("/api/projects/{key}/work/tasks/{task_id}/lines/{line_id}")
    def edit_line(
        request: Request,
        key: str,
        task_id: str,
        line_id: str,
        data: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        """{fact_qty?, price?}."""
        with acting(request, key) as (db, project, plan, actor):
            task = work.task_of(db, plan, task_id)
            line = work.line_of(db, task, line_id)
            work.edit_line(plan_of(plan), task, line, data, actor)
            db.flush()
            return work_state(db, store, project, actor)

    @app.post("/api/projects/{key}/work/tasks/{task_id}/lines")
    def add_line(
        request: Request, key: str, task_id: str, data: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        """{title, kind, unit?, qty, price?, key?}."""
        with acting(request, key) as (db, project, plan, actor):
            task = work.task_of(db, plan, task_id)
            work.add_line(plan_of(plan), task, data, actor)
            db.flush()
            return work_state(db, store, project, actor)

    @app.post("/api/projects/{key}/work/tasks/{task_id}/photos")
    def add_photo(
        request: Request,
        key: str,
        task_id: str,
        file: Annotated[UploadFile, File()],
        caption: Annotated[str, Form()] = "",
    ) -> dict[str, Any]:
        """multipart: file (JPEG, PNG, WebP, HEIC, PDF; up to 15 MB) and caption."""
        data = file.file.read(records.PHOTO_MAX + 1)
        with acting(request, key) as (db, project, plan, actor):
            task = work.task_of(db, plan, task_id)
            records.add_photo(
                db,
                store,
                project,
                plan_of(plan),
                task,
                data,
                file.filename or "",
                _content_type(file),
                caption,
                actor,
            )
            return work_state(db, store, project, actor)

    @app.get("/api/projects/{key}/work/photos/{photo_id}")
    def photo_file(request: Request, key: str, photo_id: str) -> Response:
        with acting(request, key) as (db, _, plan, _actor):
            photo = records.photo_of(db, plan, photo_id)
            local = store.local_path(photo.object_key)
            if local is not None:
                return FileResponse(local, media_type=photo.content_type)
            try:
                data = store.get(photo.object_key)
            except FileNotFoundError as exc:
                raise HTTPException(404, "файл фото потерян") from exc
            media = photo.content_type or mimetypes.guess_type(photo.file_name)[0]
            return Response(data, media_type=media or "application/octet-stream")

    @app.delete("/api/projects/{key}/work/photos/{photo_id}")
    def delete_photo(request: Request, key: str, photo_id: str) -> dict[str, Any]:
        with acting(request, key) as (db, project, plan, actor):
            photo = records.photo_of(db, plan, photo_id)
            records.delete_photo(db, store, project, plan_of(plan), photo, actor)
            return work_state(db, store, project, actor)

    @app.post("/api/projects/{key}/work/tasks/{task_id}/comments")
    def add_comment(
        request: Request, key: str, task_id: str, data: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        """{text}."""
        with acting(request, key) as (db, project, plan, actor):
            task = work.task_of(db, plan, task_id)
            records.add_comment(plan_of(plan), task, data.get("text"), actor)
            db.flush()
            return work_state(db, store, project, actor)

    @app.post("/api/projects/{key}/work/tasks/{task_id}/payments")
    def add_payment(
        request: Request, key: str, task_id: str, data: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        """{amount, paid_on, note?}."""
        with acting(request, key) as (db, project, plan, actor):
            task = work.task_of(db, plan, task_id)
            records.add_payment(db, project, plan_of(plan), task, data, actor)
            return work_state(db, store, project, actor)

    @app.delete("/api/projects/{key}/work/payments/{payment_id}")
    def delete_payment(request: Request, key: str, payment_id: str) -> dict[str, Any]:
        with acting(request, key) as (db, project, plan, actor):
            payment = records.payment_of(db, plan, payment_id)
            records.delete_payment(db, project, plan_of(plan), payment, actor)
            return work_state(db, store, project, actor)
