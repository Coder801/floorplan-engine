"""Product feedback (decision 2026-11-12, docs/database.md, "Отзывы"): a viewer user tells us
about the service itself — a bug, an idea, other — with up to three photos; the platform
superuser reads it in the admin, marks it seen or done and leaves a note. This is not feedback on
a work task (db/work.py).

The author is a signed-in user or an access-code session (no account: the code and its label);
the debug guest writes nothing. At most RATE_LIMIT items per author in RATE_WINDOW. Functions
take an open Session and do not commit, like access.py; views return plain data for the API
(api/feedback.py).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from floorplan_engine.service.db.access import Principal, audit, aware, now
from floorplan_engine.service.db.models import AccessCode, AppUser, Feedback, Project
from floorplan_engine.service.db.work_records import PHOTO_MAX as WORK_PHOTO_MAX
from floorplan_engine.service.objects import ObjectStore, feedback_photo_key

KINDS = ("bug", "idea", "other")
STATUSES = ("new", "seen", "done")
TEXT_MAX = 4000
NOTE_MAX = 2000
PHOTOS_MAX = 3
PHOTO_MAX = WORK_PHOTO_MAX  # bytes, as a task photo
PHOTO_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
RATE_LIMIT = 10
RATE_WINDOW = timedelta(hours=1)
# context: at most CONTEXT_KEYS keys of up to KEY_MAX characters, strings up to VALUE_MAX,
# one level of nesting (viewport: {width, height})
CONTEXT_KEYS = 20
KEY_MAX = 40
VALUE_MAX = 500
LIST_LIMIT = 50
LIST_MAX = 200


class FeedbackError(ValueError):
    """A broken rule; status is the HTTP answer (422 by default)."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Upload:
    """A photo from the form."""

    data: bytes
    file_name: str
    content_type: str


def _scalar(value: Any) -> str | int | float | bool | None:
    """A context value kept as is (a string trimmed); anything else — None, dropped."""
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value.strip()[:VALUE_MAX]
    return None


def clean_context(raw: Any, user_agent: str = "") -> dict[str, Any]:
    """The page context as stored: string keys, scalar values or one level of nested scalars,
    everything trimmed; the browser's user agent from the request when the page sent none."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise FeedbackError("context: нужен JSON-объект")
    out: dict[str, Any] = {}
    for key, value in list(raw.items())[:CONTEXT_KEYS]:
        if not isinstance(key, str) or not key.strip():
            continue
        if isinstance(value, dict):
            inner = {
                str(k)[:KEY_MAX]: kept
                for k, raw_value in list(value.items())[:CONTEXT_KEYS]
                if (kept := _scalar(raw_value)) is not None
            }
            out[key.strip()[:KEY_MAX]] = inner
        elif (v := _scalar(value)) is not None:
            out[key.strip()[:KEY_MAX]] = v
    if "user_agent" not in out and user_agent:
        out["user_agent"] = user_agent.strip()[:VALUE_MAX]
    return out


def _author_filter(who: Principal) -> ColumnElement[bool]:
    if who.user is not None:
        return Feedback.user_id == who.user.id
    return Feedback.access_code_id == who.code_id


def author_label(who: Principal) -> str:
    """Who wrote it, kept with the row: a user's name or e-mail, a code's label."""
    if who.user is not None:
        return (who.user.name or who.user.email or who.user.phone or "")[:200]
    return f"код: {who.code_label}"[:200] if who.code_label else "код доступа"


def check_author(who: Principal | None) -> Principal:
    """Only a user or an access-code session leaves feedback: not logged in — 401, the debug
    guest — 403."""
    if who is None:
        raise FeedbackError("нужен вход", 401)
    if who.user is None and who.code_id is None:
        raise FeedbackError("гостевой вход не оставляет отзывы", 403)
    return who


def check_rate(session: Session, who: Principal) -> None:
    """At most RATE_LIMIT items per author in RATE_WINDOW, then 429."""
    since = now() - RATE_WINDOW
    count = session.scalar(
        select(func.count())
        .select_from(Feedback)
        .where(_author_filter(who), Feedback.created_at > since)
    )
    if (count or 0) >= RATE_LIMIT:
        raise FeedbackError(
            f"Слишком много отзывов: не больше {RATE_LIMIT} в час — попробуйте позже", 429
        )


def _photo_ext(photo: Upload, index: int) -> str:
    ext = PHOTO_TYPES.get(photo.content_type.split(";")[0].strip().lower())
    field = f"photos[{index}]"
    if ext is None:
        raise FeedbackError(f"{field}: фото — JPEG, PNG или WebP", 415)
    if len(photo.data) > PHOTO_MAX:
        raise FeedbackError(f"{field}: фото больше {PHOTO_MAX // (1024 * 1024)} МБ", 413)
    if not photo.data:
        raise FeedbackError(f"{field}: файл пустой")
    return ext


def create(
    session: Session,
    store: ObjectStore,
    who: Principal | None,
    project: Project | None,
    kind: str,
    text: str,
    context: dict[str, Any],
    photos: list[Upload],
) -> Feedback:
    """A new item by the caller; the project is already checked for view access by the API.
    Everything is checked before the photos go to storage."""
    author = check_author(who)
    if kind not in KINDS:
        raise FeedbackError(f"kind: одно из {', '.join(KINDS)}")
    text = text.strip()
    if not text:
        raise FeedbackError("text: напишите, что случилось или что предлагаете")
    if len(text) > TEXT_MAX:
        raise FeedbackError(f"text: не длиннее {TEXT_MAX} символов")
    if len(photos) > PHOTOS_MAX:
        raise FeedbackError(f"photos: не больше {PHOTOS_MAX} фото")
    exts = [_photo_ext(p, i) for i, p in enumerate(photos)]
    check_rate(session, author)
    row = Feedback(
        id=uuid.uuid4(),
        user_id=author.user.id if author.user is not None else None,
        access_code_id=author.code_id if author.user is None else None,
        author_label=author_label(author),
        project_id=project.id if project is not None else None,
        kind=kind,
        text=text,
        context=context,
        status="new",
        photos=[],
    )
    stored: list[dict[str, Any]] = []
    for photo, ext in zip(photos, exts, strict=True):
        photo_id = uuid.uuid4()
        key = feedback_photo_key(row.id, photo_id, ext)
        store.put(key, photo.data)
        stored.append(
            {
                "id": str(photo_id),
                "key": key,
                "content_type": photo.content_type.split(";")[0].strip().lower(),
                "size": len(photo.data),
                "file_name": photo.file_name[:200],
            }
        )
    row.photos = stored
    session.add(row)
    session.flush()
    return row


# --- Admin -----------------------------------------------------------------------------


def get(session: Session, id_: str) -> Feedback:
    """The item by id; LookupError (→ 404) for a malformed or unknown id."""
    try:
        row = session.get(Feedback, uuid.UUID(id_))
    except ValueError:
        row = None
    if row is None:
        raise LookupError(f"отзыва {id_} нет")
    return row


def photo_of(row: Feedback, photo_id: str) -> dict[str, Any]:
    found = next((p for p in row.photos if p.get("id") == photo_id), None)
    if found is None:
        raise LookupError(f"фото {photo_id} нет")
    return dict(found)


def photo_url(row: Feedback, photo: dict[str, Any]) -> str:
    return f"/api/admin/feedback/{row.id}/photos/{photo.get('id')}"


def _item(
    row: Feedback,
    user: AppUser | None,
    code: AccessCode | None,
    project: Project | None,
) -> dict[str, Any]:
    if user is not None:
        author: dict[str, Any] = {
            "id": str(user.id),
            "email": user.email,
            "name": user.name or None,
            "phone": user.phone,
        }
    elif code is not None:
        author = {"code_label": code.label or "код доступа"}
    else:  # the user or the code is gone: what was kept with the row
        author = {"name": row.author_label or None}
    return {
        "id": str(row.id),
        "created_at": aware(row.created_at).isoformat(timespec="seconds"),
        "kind": row.kind,
        "text": row.text,
        "status": row.status,
        "admin_note": row.admin_note,
        "context": row.context,
        "author": author,
        "project": {"key": str(project.id), "name": project.name} if project is not None else None,
        "photos": [photo_url(row, p) for p in row.photos],
    }


def item(session: Session, row: Feedback) -> dict[str, Any]:
    """One item for the admin, as in the list."""
    return _items(session, [row])[0]


def _items(session: Session, rows: list[Feedback]) -> list[dict[str, Any]]:
    def by_id(model: type[Any], ids: set[Any]) -> dict[Any, Any]:
        ids.discard(None)
        if not ids:
            return {}
        return {r.id: r for r in session.scalars(select(model).where(model.id.in_(ids)))}

    users = by_id(AppUser, {r.user_id for r in rows})
    codes = by_id(AccessCode, {r.access_code_id for r in rows})
    projects = by_id(Project, {r.project_id for r in rows})
    return [
        _item(r, users.get(r.user_id), codes.get(r.access_code_id), projects.get(r.project_id))
        for r in rows
    ]


def listing(
    session: Session,
    status: str = "",
    kind: str = "",
    q: str = "",
    offset: int = 0,
    limit: int = LIST_LIMIT,
) -> dict[str, Any]:
    """Items newest first by status, kind and a search in the text, the author and the note;
    total — how many match, counts — how many there are by status (all, for the summary)."""
    where: list[ColumnElement[bool]] = []
    if status:
        if status not in STATUSES:
            raise FeedbackError(f"status: одно из {', '.join(STATUSES)}")
        where.append(Feedback.status == status)
    if kind:
        if kind not in KINDS:
            raise FeedbackError(f"kind: одно из {', '.join(KINDS)}")
        where.append(Feedback.kind == kind)
    if q.strip():
        like = f"%{q.strip()}%"
        authors = select(AppUser.id).where(or_(AppUser.email.ilike(like), AppUser.name.ilike(like)))
        where.append(
            or_(
                Feedback.text.ilike(like),
                Feedback.author_label.ilike(like),
                Feedback.admin_note.ilike(like),
                Feedback.user_id.in_(authors),
            )
        )
    total = session.scalar(select(func.count()).select_from(Feedback).where(*where)) or 0
    rows = list(
        session.scalars(
            select(Feedback)
            .where(*where)
            .order_by(Feedback.created_at.desc(), Feedback.id)
            .offset(max(offset, 0))
            .limit(min(max(limit, 1), LIST_MAX))
        )
    )
    counts = dict.fromkeys(STATUSES, 0)
    for s, n in session.execute(select(Feedback.status, func.count()).group_by(Feedback.status)):
        counts[s] = int(n)
    return {"items": _items(session, rows), "total": int(total), "counts": counts}


def new_count(session: Session) -> int:
    """Items nobody has looked at yet: for the admin summary."""
    return int(
        session.scalar(select(func.count()).select_from(Feedback).where(Feedback.status == "new"))
        or 0
    )


def update(
    session: Session,
    admin: AppUser,
    row: Feedback,
    status: str | None = None,
    note: str | None = None,
    note_given: bool = False,
) -> Feedback:
    """The superuser marks the item (status) and/or writes a note (an empty one clears it); in the
    audit log with the admin as its author."""
    changes: dict[str, Any] = {"feedback": str(row.id)}
    if status is not None:
        if status not in STATUSES:
            raise FeedbackError(f"status: одно из {', '.join(STATUSES)}")
        changes["status"] = [row.status, status]
        row.status = status
    if note_given:
        clean = (note or "").strip()
        if len(clean) > NOTE_MAX:
            raise FeedbackError(f"admin_note: не длиннее {NOTE_MAX} символов")
        row.admin_note = clean or None
        changes["note"] = True
    session.flush()
    audit(session, "feedback_update", user=admin, payload=changes)
    return row
