"""Product feedback API (decision 2026-11-12, docs/service-api.md, "Отзывы"): the viewer's
"Оставить отзыв" and its admin side. Only with projects in the database (create_viewer with
store): the folder viewer has no such routes, and /api/auth/me answers `feedback: false` there.

POST /api/feedback                              multipart: kind, text, context, project?, photos
GET  /api/admin/feedback                        list with filters and counts by status
PATCH /api/admin/feedback/{id}                  {status?, admin_note?}
GET  /api/admin/feedback/{id}/photos/{photo_id} a photo, superuser only

Auth.check already answers 401 to a caller who is not logged in and lets only a superuser into
/api/admin/*; the rules live in db/feedback.py. A notice of a new item goes by e-mail to
FEEDBACK_NOTIFY_EMAIL after the answer, best effort.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any, TypeVar

from fastapi import BackgroundTasks, Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from floorplan_engine.service.api.auth import Auth
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db import feedback as fb
from floorplan_engine.service.db.models import AppUser, Project
from floorplan_engine.service.objects import ObjectStore

log = logging.getLogger(__name__)
T = TypeVar("T")
# Photo types by extension, when the browser sends none
EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
KIND_NAMES = {"bug": "ошибка", "idea": "идея", "other": "другое"}
NOTICE_TEXT = 300  # characters of the text in the notice


def _content_type(upload: UploadFile) -> str:
    sent = (upload.content_type or "").split(";")[0].strip().lower()
    if sent in fb.PHOTO_TYPES:
        return sent
    return EXTENSIONS.get(Path(upload.filename or "").suffix.lower(), sent)


def _context(raw: str, user_agent: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise fb.FeedbackError("context: нужен JSON-объект") from exc
    return fb.clean_context(parsed, user_agent)


def notice(kind: str, author: str, project: str | None, text: str, admin_url: str) -> str:
    """The body of the notice e-mail."""
    where = f" · проект «{project}»" if project else ""
    short = text if len(text) <= NOTICE_TEXT else text[:NOTICE_TEXT] + "…"
    return (
        f"Новый отзыв ({KIND_NAMES.get(kind, kind)}) от {author or 'без имени'}{where}:\n\n"
        f"{short}\n\nАдминка: {admin_url}"
    )


def install_feedback_routes(app: FastAPI, auth: Auth, store: ObjectStore) -> None:
    """The feedback routes; /api/auth/me reports them (Auth.feedback)."""
    auth.feedback = True

    def send_notice(body: str) -> None:
        """Best effort: a failed notice is only a line in the log."""
        to, mailer = auth.config.feedback_to, auth.mailer
        if not to or mailer is None:
            return
        try:
            mailer.send(to, "Shtroba: новый отзыв", body)
        except Exception as exc:  # the item is saved anyway
            log.warning("уведомление об отзыве не ушло: %s", exc)

    def project_of(db: Session, who: acc.Principal | None, key: str) -> Project | None:
        """The project of the item if the caller sees it; one they do not see is 404, as in the
        project guard (auth.project_access)."""
        if not key or who is None:
            return None
        project = acc.project_by_key(db, key, who)
        if project is None or not acc.can(acc.project_role(db, who, project), "view"):
            raise fb.FeedbackError(f"проекта {key} нет", 404)
        return project

    @app.post("/api/feedback")
    def create_feedback(
        request: Request,
        background: BackgroundTasks,
        kind: Annotated[str, Form()] = "",
        text: Annotated[str, Form()] = "",
        context: Annotated[str, Form()] = "",
        project: Annotated[str, Form()] = "",
        photos: Annotated[list[UploadFile] | None, File()] = None,
    ) -> dict[str, str]:
        uploads = [
            fb.Upload(p.file.read(fb.PHOTO_MAX + 1), p.filename or "", _content_type(p))
            for p in photos or []
        ]
        with auth.db() as db:
            try:
                who = auth.principal(db, request)
                target = project_of(db, who, project.strip())
                row = fb.create(
                    db,
                    store,
                    who,
                    target,
                    kind,
                    text,
                    _context(context, request.headers.get("user-agent", "")),
                    uploads,
                )
            except fb.FeedbackError as exc:
                raise HTTPException(exc.status, str(exc)) from exc
            admin_url = f"{auth.config.public_url}/admin/"
            name = target.name if target is not None else None
            body = notice(row.kind, row.author_label, name, row.text, admin_url)
            result = {"id": str(row.id)}
        background.add_task(send_notice, body)
        return result

    @contextmanager
    def admin_db(request: Request) -> Iterator[tuple[Session, AppUser]]:
        """A session and the admin (Auth.check let only a superuser in); a broken rule gives its
        status, an unknown id 404, and nothing is written then."""
        with auth.sessions() as db:
            admin = db.get(AppUser, getattr(request.state, "admin", None))
            if admin is None:
                raise HTTPException(403, "только для владельца платформы")
            try:
                yield db, admin
            except fb.FeedbackError as exc:
                db.rollback()
                raise HTTPException(exc.status, str(exc)) from exc
            except LookupError as exc:
                db.rollback()
                raise HTTPException(404, str(exc)) from exc
            db.commit()

    def call(request: Request, fn: Callable[[Session, AppUser], T]) -> T:
        with admin_db(request) as (db, admin):
            return fn(db, admin)

    @app.get("/api/admin/feedback")
    def list_feedback(
        request: Request,
        status: str = "",
        kind: str = "",
        q: str = "",
        offset: int = 0,
        limit: int = fb.LIST_LIMIT,
    ) -> dict[str, Any]:
        return call(request, lambda db, _: fb.listing(db, status, kind, q, offset, limit))

    @app.patch("/api/admin/feedback/{feedback_id}")
    def update_feedback(
        request: Request, feedback_id: str, data: Annotated[dict[str, Any], Body()]
    ) -> dict[str, Any]:
        """{status?, admin_note?}: admin_note null or "" clears the note."""
        status, note = data.get("status"), data.get("admin_note")
        if status is not None and not isinstance(status, str):
            raise HTTPException(422, "status: нужна строка")
        if note is not None and not isinstance(note, str):
            raise HTTPException(422, "admin_note: нужна строка")

        def run(db: Session, admin: AppUser) -> dict[str, Any]:
            row = fb.get(db, feedback_id)
            fb.update(db, admin, row, status, note, note_given="admin_note" in data)
            return fb.item(db, row)

        return call(request, run)

    @app.get("/api/admin/feedback/{feedback_id}/photos/{photo_id}")
    def feedback_photo(request: Request, feedback_id: str, photo_id: str) -> Response:
        photo = call(request, lambda db, _: fb.photo_of(fb.get(db, feedback_id), photo_id))
        local = store.local_path(photo["key"])
        if local is not None and local.is_file():
            return FileResponse(local, media_type=photo["content_type"])
        try:
            data = store.get(photo["key"])
        except FileNotFoundError as exc:
            raise HTTPException(404, "файл фото потерян") from exc
        return Response(data, media_type=photo["content_type"])
