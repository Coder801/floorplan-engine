"""Records of a task (docs/work-tasks.md): photos and PDF reports in file storage, comments and
payments. The rules of the plan and the tasks, the errors and the actor are in db/work.py; like
it, functions take an open Session and do not commit.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from floorplan_engine.service.db.models import (
    Project,
    WorkComment,
    WorkPayment,
    WorkPhoto,
    WorkPlan,
    WorkTask,
)
from floorplan_engine.service.db.work import (
    TEXT_MAX,
    Actor,
    WorkError,
    audit,
    check_open,
    feed,
    get_row,
    number_field,
    text_field,
)
from floorplan_engine.service.objects import ObjectStore, work_photo_key

PHOTO_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heic",
    "application/pdf": "pdf",
}
PHOTO_MAX = 15 * 1024 * 1024  # bytes


def photo_of(session: Session, plan: WorkPlan | None, photo_id: str) -> WorkPhoto:
    photo = get_row(session, WorkPhoto, photo_id)
    task = session.get(WorkTask, photo.task_id) if photo is not None else None
    if photo is None or task is None or plan is None or task.plan_id != plan.id:
        raise WorkError(f"фото {photo_id} нет", 404)
    return photo


def payment_of(session: Session, plan: WorkPlan | None, payment_id: str) -> WorkPayment:
    payment = get_row(session, WorkPayment, payment_id)
    task = session.get(WorkTask, payment.task_id) if payment is not None else None
    if payment is None or task is None or plan is None or task.plan_id != plan.id:
        raise WorkError(f"оплаты {payment_id} нет", 404)
    return payment


def add_photo(
    session: Session,
    store: ObjectStore,
    project: Project,
    plan: WorkPlan,
    task: WorkTask,
    data: bytes,
    file_name: str,
    content_type: str,
    caption: str,
    actor: Actor,
) -> WorkPhoto:
    """A photo or a PDF report to an approved plan's task, up to PHOTO_MAX; the file goes to
    storage under projects/<project>/work/<task>/."""
    if not (actor.can("work_do") or actor.can("work_accept")):
        raise WorkError("нет права на это действие", 403)
    check_open(plan)
    if plan.state != "approved":
        raise WorkError("фото добавляются после утверждения плана")
    ext = PHOTO_TYPES.get(content_type.split(";")[0].strip().lower())
    if ext is None:
        raise WorkError("файл: JPEG, PNG, WebP, HEIC или PDF", 415)
    if len(data) > PHOTO_MAX:
        raise WorkError(f"файл больше {PHOTO_MAX // (1024 * 1024)} МБ", 413)
    if not data:
        raise WorkError("файл пустой", 422)
    photo_id = uuid.uuid4()
    key = work_photo_key(project.id, task.id, photo_id, ext)
    store.put(key, data)
    photo = WorkPhoto(
        id=photo_id,
        object_key=key,
        file_name=file_name[:200],
        content_type=content_type,
        size=len(data),
        caption=text_field(caption, "caption", TEXT_MAX),
        user_id=actor.user_id,
        author_label=actor.label,
    )
    task.photos.append(photo)
    session.flush()
    audit(session, actor, project, "work_photo", {"task": str(task.id), "photo": str(photo_id)})
    return photo


def delete_photo(
    session: Session,
    store: ObjectStore,
    project: Project,
    plan: WorkPlan,
    photo: WorkPhoto,
    actor: Actor,
) -> None:
    """The author deletes their photo until the task is accepted; the studio — any time."""
    check_open(plan)
    task = session.get(WorkTask, photo.task_id)
    assert task is not None
    own = photo.user_id is not None and photo.user_id == actor.user_id
    if not actor.can("work_manage") and not (own and task.status != "accepted"):
        raise WorkError("удалить фото может его автор (до приёмки) или студия", 403)
    payload = {"task": str(task.id), "photo": str(photo.id)}
    key = photo.object_key
    task.photos.remove(photo)
    session.flush()
    store.delete_prefix(key)
    audit(session, actor, project, "work_photo_delete", payload)


def add_comment(plan: WorkPlan, task: WorkTask, text: object, actor: Actor) -> WorkComment:
    if not (actor.can("work_do") or actor.can("work_accept")):
        raise WorkError("нет права на это действие", 403)
    check_open(plan)
    feed(task, actor, "comment", text_field(text, "text", TEXT_MAX, required=True))
    return task.comments[-1]


def add_payment(
    session: Session,
    project: Project,
    plan: WorkPlan,
    task: WorkTask,
    data: Mapping[str, Any],
    actor: Actor,
) -> WorkPayment:
    """A payment of an approved plan's task: {amount > 0, paid_on: YYYY-MM-DD, note?}."""
    actor.need("work_manage")
    check_open(plan)
    if plan.state != "approved":
        raise WorkError("оплаты отмечаются после утверждения плана")
    amount = number_field(data.get("amount"), "amount", nullable=False)
    if not amount:
        raise WorkError("amount: нужна сумма больше 0", 422)
    try:
        paid_on = date.fromisoformat(str(data.get("paid_on")))
    except ValueError as exc:
        raise WorkError("paid_on: дата ГГГГ-ММ-ДД", 422) from exc
    payment = WorkPayment(
        amount=round(amount, 2),
        paid_on=paid_on,
        note=text_field(data.get("note", ""), "note", TEXT_MAX),
        recorded_by=actor.user_id,
    )
    task.payments.append(payment)
    session.flush()
    payload = {"task": str(task.id), "payment": str(payment.id), "amount": payment.amount}
    audit(session, actor, project, "work_payment", payload)
    return payment


def delete_payment(
    session: Session, project: Project, plan: WorkPlan, payment: WorkPayment, actor: Actor
) -> None:
    actor.need("work_manage")
    check_open(plan)
    task = session.get(WorkTask, payment.task_id)
    assert task is not None
    payload = {"task": str(task.id), "payment": str(payment.id), "amount": payment.amount}
    task.payments.remove(payment)
    session.flush()
    audit(session, actor, project, "work_payment_delete", payload)
