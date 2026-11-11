"""Installation by tasks (docs/work-tasks.md): the work plan of a project, its tasks and lines, with
the rules of who may do what and when; photos, comments and payments — db/work_records.py.

The plan is made from the .epd `work_plan` draft of the latest build (pipeline/work_plan.py); the
service does not recount it. Plan: draft → proposed → approved → closed, one plan that is not
closed per project. Task: proposed → todo → in_progress → review → accepted, or review →
returned → in_progress | review; a task added after approval is extra and starts in proposed
until the client agrees to it. Sums are not stored: totals() counts them from the lines.

Rights are the actions of access.py (work_do, work_accept, work_manage) by the caller's project
role. Functions take an open Session and do not commit, like repositories.py; a broken rule is a
WorkError with a message for the user in Russian and an HTTP status.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db.models import (
    AppUser,
    Build,
    Membership,
    Project,
    ProjectMember,
    WorkComment,
    WorkLine,
    WorkPayment,
    WorkPhoto,
    WorkPlan,
    WorkTask,
)

PLAN_STATES = ("draft", "proposed", "approved", "closed")
STATUSES = ("proposed", "todo", "in_progress", "review", "returned", "accepted")
PHOTO = ("required", "optional", "none")
DOMAINS = ("electrical", "plumbing", "other")
KINDS = ("work", "material")
# Task status names for messages
STATUS_TEXT = {
    "proposed": "предложена",
    "todo": "к работе",
    "in_progress": "в работе",
    "review": "на приёмке",
    "returned": "возвращена",
    "accepted": "принята",
}
# Status change → the right it needs (docs/work-tasks.md, "Статусы задачи")
TRANSITIONS: dict[tuple[str, str], acc.Action] = {
    ("proposed", "todo"): "work_accept",  # the client agreed to an extra task
    ("todo", "in_progress"): "work_do",
    ("in_progress", "review"): "work_do",
    ("review", "accepted"): "work_accept",
    ("review", "returned"): "work_accept",
    ("returned", "in_progress"): "work_do",
    ("returned", "review"): "work_do",
}
# Plan action → the state it needs, the state it gives and the right
PLAN_ACTIONS: dict[str, tuple[tuple[str, ...], str | None, acc.Action]] = {
    "propose": (("draft",), "proposed", "work_manage"),
    "approve": (("proposed",), "approved", "work_accept"),
    "close": (("approved",), "closed", "work_manage"),
    "discard": (("draft", "proposed"), None, "work_manage"),  # remove a plan not yet approved
}
TEXT_MAX = 4000  # a comment, a description
TITLE_MAX = 200
_Row = TypeVar("_Row", WorkTask, WorkLine, WorkPhoto, WorkPayment)


class WorkError(ValueError):
    """A broken rule: the message is for the user, status is the HTTP answer (409 — not in this
    state, 403 — not your right, 422 — a wrong value, 404 — no such thing)."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Actor:
    """Who acts: a user, or someone logged in by a code (user None, label — the code's label);
    role — the project role."""

    role: str | None
    user: AppUser | None = None
    label: str = ""

    @property
    def user_id(self) -> uuid.UUID | None:
        return self.user.id if self.user is not None else None

    def can(self, action: acc.Action) -> bool:
        return acc.can(self.role, action)

    def need(self, action: acc.Action) -> None:
        if not self.can(action):
            raise WorkError("нет права на это действие", 403)


def actor_of(who: acc.Principal | None, role: str | None) -> Actor:
    """The actor of a request: a user by name, a code by its label ("код: Иван")."""
    user = who.user if who is not None else None
    if user is not None:
        return Actor(role, user, user.name or user.email or user.phone or "")
    if who is not None and who.by_code:
        return Actor(role, None, f"код: {who.code_label}" if who.code_label else "код доступа")
    return Actor(role)


# --- Reading --------------------------------------------------------------------------


def current_plan(session: Session, project: Project) -> WorkPlan | None:
    """The plan that is not closed, otherwise the latest closed one."""
    return session.scalar(
        select(WorkPlan)
        .where(WorkPlan.project_id == project.id)
        .order_by((WorkPlan.state == "closed").asc(), WorkPlan.created_at.desc())
        .limit(1)
    )


def task_of(session: Session, plan: WorkPlan | None, task_id: str) -> WorkTask:
    task = get_row(session, WorkTask, task_id)
    if task is None or plan is None or task.plan_id != plan.id:
        raise WorkError(f"задачи {task_id} нет", 404)
    return task


def get_row(session: Session, model: type[_Row], key: str) -> _Row | None:
    try:
        return session.get(model, uuid.UUID(key))
    except ValueError:
        return None


def line_of(session: Session, task: WorkTask, line_id: str) -> WorkLine:
    line = get_row(session, WorkLine, line_id)
    if line is None or line.task_id != task.id:
        raise WorkError(f"строки {line_id} нет", 404)
    return line


@dataclass(frozen=True)
class Totals:
    work: float
    material: float
    paid: float
    unpriced: int  # lines without a price: the sum is counted without them
    materials_included: bool

    @property
    def total(self) -> float:
        return round(self.work + (self.material if self.materials_included else 0.0), 2)

    @property
    def settled(self) -> bool:
        """Paid in full ("оплачено" on the card)."""
        return self.paid >= self.total


def line_sum(line: WorkLine) -> float | None:
    qty = line.fact_qty if line.fact_qty is not None else line.plan_qty
    return None if line.price is None else round(qty * line.price, 2)


def totals(task: WorkTask) -> Totals:
    """Σ (fact ?? plan) × price over the lines, work and materials apart; materials count in the
    total if the task includes them; paid — Σ payments."""

    def by(kind: str) -> float:
        return round(sum(line_sum(ln) or 0.0 for ln in task.lines if ln.kind == kind), 2)

    return Totals(
        by("work"),
        by("material"),
        round(sum(p.amount for p in task.payments), 2),
        sum(1 for ln in task.lines if ln.price is None),
        task.materials_included,
    )


def _refers(task: WorkTask, ref: str) -> bool:
    return ref in (task.key, str(task.id))


def waiting(task: WorkTask, tasks: Iterable[WorkTask]) -> list[WorkTask]:
    """Tasks this one comes after that are not accepted yet (a soft dependency)."""
    others = [t for t in tasks if t.id != task.id]
    return [
        t for ref in task.after for t in others if _refers(t, str(ref)) and t.status != "accepted"
    ]


def assignees(session: Session, project: Project) -> list[AppUser]:
    """Who can be assigned: the people of the project's studio and installers invited to it."""
    studio = select(Membership.user_id).where(
        Membership.studio_id == project.studio_id, Membership.role.in_(acc.STUDIO_ROLES)
    )
    invited = select(ProjectMember.user_id).where(
        ProjectMember.project_id == project.id, ProjectMember.role == "installer"
    )
    return list(
        session.scalars(
            select(AppUser)
            .where(AppUser.id.in_(studio.union(invited)), AppUser.is_active)
            .order_by(AppUser.name, AppUser.email)
        )
    )


# --- The plan ---------------------------------------------------------------------------


def audit(
    session: Session, actor: Actor, project: Project, action: str, payload: dict[str, Any]
) -> None:
    if actor.user is None and actor.label:
        payload = {**payload, "by": actor.label}
    acc.audit(session, action, user=actor.user, project=project, payload=payload)


def text_field(value: object, field: str, limit: int, required: bool = False) -> str:
    if not isinstance(value, str):
        raise WorkError(f"{field}: нужна строка", 422)
    value = value.strip()
    if required and not value:
        raise WorkError(f"{field}: не может быть пустым", 422)
    if len(value) > limit:
        raise WorkError(f"{field}: не длиннее {limit} знаков", 422)
    return value


def number_field(value: object, field: str, nullable: bool = True) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise WorkError(f"{field}: нужно число не меньше 0", 422)
    return float(value)


def _line(position: int, data: Mapping[str, Any], where: str) -> WorkLine:
    kind = data.get("kind", "work")
    if kind not in KINDS:
        raise WorkError(f"{where}.kind: work или material", 422)
    qty = number_field(data.get("qty"), f"{where}.qty", nullable=False)
    return WorkLine(
        position=position,
        key=text_field(data.get("key", ""), f"{where}.key", 80),
        kind=kind,
        title=text_field(data.get("title"), f"{where}.title", TITLE_MAX, required=True),
        unit=text_field(data.get("unit", ""), f"{where}.unit", 20),
        plan_qty=qty,
        price=number_field(data.get("price"), f"{where}.price"),
    )


def create_plan(
    session: Session, project: Project, build: Build | None, draft: object, actor: Actor
) -> WorkPlan:
    """A draft plan from the .epd work_plan of a build: its tasks in the draft's order, all
    proposed until the client approves the plan."""
    actor.need("work_manage")
    if session.scalar(
        select(WorkPlan.id).where(WorkPlan.project_id == project.id, WorkPlan.state != "closed")
    ):
        raise WorkError("у проекта уже есть план работ")
    tasks = draft.get("tasks") if isinstance(draft, dict) else None
    if build is None or not isinstance(draft, dict) or not tasks:
        raise WorkError("в последней сборке нет черновика задач — пересоберите проект")
    plan = WorkPlan(
        project_id=project.id,
        model_version_id=build.model_version_id,
        build_id=build.id,
        state="draft",
        currency=str(draft.get("currency", ""))[:8],
        created_by=actor.user_id,
    )
    session.add(plan)
    for k, item in enumerate(tasks):
        task = WorkTask(
            key=str(item["key"]),
            domain=str(item["domain"]),
            position=k,
            title=str(item["title"])[:TITLE_MAX],
            status="proposed",
            photo=str(item.get("photo", "optional")),
            result=list(item.get("result", [])),
            after=list(item.get("after", [])),
        )
        plan.tasks.append(task)
        for j, ln in enumerate(item.get("lines", [])):
            task.lines.append(_line(j, ln, f"tasks[{k}].lines[{j}]"))
    session.flush()
    audit(session, actor, project, "work_plan_create", {"plan": str(plan.id), "tasks": len(tasks)})
    return plan


def plan_action(
    session: Session, project: Project, plan: WorkPlan | None, action: str, actor: Actor
) -> WorkPlan | None:
    """propose (studio), approve (client: tasks go to todo, who and when is kept), close (studio:
    every task accepted and paid), discard (studio: a plan not approved yet is removed). The plan,
    None after discard."""
    if action not in PLAN_ACTIONS:
        raise WorkError(f"действие плана — одно из: {', '.join(PLAN_ACTIONS)}", 404)
    states, to, right = PLAN_ACTIONS[action]
    actor.need(right)
    if plan is None:
        raise WorkError("плана работ ещё нет", 404)
    if plan.state not in states:
        raise WorkError(f"план в состоянии {plan.state}: {action} недоступно")
    if action == "close":
        open_ = [t.title for t in plan.tasks if t.status != "accepted" or not totals(t).settled]
        if open_:
            raise WorkError(f"не приняты или не оплачены: {', '.join(open_)}")
    payload = {"plan": str(plan.id), "from": plan.state, "to": to}
    audit(session, actor, project, f"work_plan_{action}", payload)
    if to is None:
        session.delete(plan)
        session.flush()
        return None
    plan.state = to
    if action == "approve":
        plan.approved_by, plan.approved_label = actor.user_id, actor.label
        plan.approved_at = acc.now()
        for task in plan.tasks:
            if task.status == "proposed":
                task.status = "todo"
    if action == "close":
        plan.closed_at = acc.now()
    session.flush()
    return plan


# --- Tasks ------------------------------------------------------------------------------


def check_open(plan: WorkPlan) -> None:
    if plan.state == "closed":
        raise WorkError("план работ закрыт")


def money_editable(plan: WorkPlan, task: WorkTask) -> bool:
    """Prices and lines change until the client approves: in a plan not yet approved, or in an
    extra task the client has not agreed to yet."""
    return plan.state in ("draft", "proposed") or (task.extra and task.status == "proposed")


def _money(plan: WorkPlan, task: WorkTask) -> None:
    if not money_editable(plan, task):
        raise WorkError("сумма задачи согласована с заказчиком — добавьте доп. работу")


def add_task(
    session: Session, project: Project, plan: WorkPlan | None, data: Mapping[str, Any], actor: Actor
) -> WorkTask:
    """The studio's own task, at the end; after approval it is extra work and starts proposed.
    data: title, description?, domain?, photo?, materials_included?, lines? (as add_line)."""
    actor.need("work_manage")
    if plan is None:
        raise WorkError("плана работ ещё нет", 404)
    check_open(plan)
    domain = data.get("domain", "other")
    if domain not in DOMAINS:
        raise WorkError(f"domain: одно из {', '.join(DOMAINS)}", 422)
    photo = data.get("photo", "optional")
    if photo not in PHOTO:
        raise WorkError(f"photo: одно из {', '.join(PHOTO)}", 422)
    lines = data.get("lines", [])
    if not isinstance(lines, list):
        raise WorkError("lines: нужен список строк", 422)
    task = WorkTask(
        domain=domain,
        position=len(plan.tasks),
        title=text_field(data.get("title"), "title", TITLE_MAX, required=True),
        description=text_field(data.get("description", ""), "description", TEXT_MAX),
        status="proposed",
        extra=plan.state == "approved",
        photo=photo,
        result=[],
        after=[],
        materials_included=bool(data.get("materials_included", True)),
    )
    for j, ln in enumerate(lines):
        if not isinstance(ln, dict):
            raise WorkError(f"lines[{j}]: нужен объект", 422)
        task.lines.append(_line(j, ln, f"lines[{j}]"))
    plan.tasks.append(task)
    session.flush()
    payload = {"task": str(task.id), "title": task.title, "extra": task.extra}
    audit(session, actor, project, "work_task_add", payload)
    return task


def _after_refs(plan: WorkPlan, task: WorkTask, value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise WorkError("after: нужен список id или ключей задач", 422)
    for k, ref in enumerate(value):
        if not any(_refers(t, ref) for t in plan.tasks if t.id != task.id):
            raise WorkError(f"after[{k}]: нет задачи {ref} в плане", 422)
    return list(value)


def edit_task(
    session: Session,
    project: Project,
    plan: WorkPlan,
    task: WorkTask,
    data: Mapping[str, Any],
    actor: Actor,
) -> WorkTask:
    """The studio edits a task: title, description, position (place in the list, from 0),
    assignee_id (null — nobody), materials_included (money: until approved), photo, after."""
    actor.need("work_manage")
    check_open(plan)
    unknown = set(data) - {
        "title",
        "description",
        "position",
        "assignee_id",
        "materials_included",
        "photo",
        "after",
    }
    if unknown:
        raise WorkError(f"{sorted(unknown)[0]}: это поле задачи не меняется", 422)
    if "title" in data:
        task.title = text_field(data["title"], "title", TITLE_MAX, required=True)
    if "description" in data:
        task.description = text_field(data["description"], "description", TEXT_MAX)
    if "photo" in data:
        if data["photo"] not in PHOTO:
            raise WorkError(f"photo: одно из {', '.join(PHOTO)}", 422)
        task.photo = data["photo"]
    if "materials_included" in data:
        if not isinstance(data["materials_included"], bool):
            raise WorkError("materials_included: true или false", 422)
        if data["materials_included"] != task.materials_included:
            _money(plan, task)
        task.materials_included = data["materials_included"]
    if "after" in data:
        task.after = _after_refs(plan, task, data["after"])
    if "assignee_id" in data:
        task.assignee_id = _assignee(session, project, data["assignee_id"])
    if "position" in data:
        at = data["position"]
        if isinstance(at, bool) or not isinstance(at, int) or not 0 <= at < len(plan.tasks):
            raise WorkError(f"position: от 0 до {len(plan.tasks) - 1}", 422)
        order = [t for t in plan.tasks if t.id != task.id]
        order.insert(at, task)
        for k, t in enumerate(order):
            t.position = k
    session.flush()
    session.refresh(plan)
    return task


def _assignee(session: Session, project: Project, value: object) -> uuid.UUID | None:
    if value is None:
        return None
    people = {str(u.id): u.id for u in assignees(session, project)}
    if not isinstance(value, str) or value not in people:
        raise WorkError("assignee_id: этого человека нет в студии или среди монтажников", 422)
    return people[value]


def delete_task(
    session: Session, project: Project, plan: WorkPlan, task: WorkTask, actor: Actor
) -> None:
    """Only a task not started, without photos and payments."""
    actor.need("work_manage")
    check_open(plan)
    if task.status not in ("proposed", "todo") or task.photos or task.payments:
        raise WorkError("удалить можно задачу, которую ещё не начали, без фото и оплат")
    audit(session, actor, project, "work_task_delete", {"task": str(task.id), "title": task.title})
    plan.tasks.remove(task)
    for k, t in enumerate(plan.tasks):
        t.position = k
    session.flush()


def feed(task: WorkTask, actor: Actor, kind: str, text: str, status: str | None = None) -> None:
    task.comments.append(
        WorkComment(
            user_id=actor.user_id,
            author_label=actor.label,
            kind=kind,
            status=status,
            text=text,
        )
    )


def change_status(
    session: Session,
    project: Project,
    plan: WorkPlan,
    task: WorkTask,
    to: object,
    comment: object,
    actor: Actor,
) -> WorkTask:
    """A status change by the rules of docs/work-tasks.md: only in an approved plan; a task with
    photo: required is handed in only with a photo; returned only with a comment; a task waiting
    for others is started only by the studio. Goes to the task feed and the journal."""
    if to not in STATUSES:
        raise WorkError(f"to: одно из {', '.join(STATUSES)}", 422)
    if comment is not None and not isinstance(comment, str):
        raise WorkError("comment: нужна строка", 422)
    text = (comment or "").strip()[:TEXT_MAX]
    right = TRANSITIONS.get((task.status, to))
    if right is None:
        raise WorkError(
            f"задачу со статусом «{STATUS_TEXT[task.status]}» нельзя перевести "
            f"в «{STATUS_TEXT[to]}»"
        )
    actor.need(right)
    check_open(plan)
    if plan.state != "approved":
        raise WorkError("план работ ещё не утверждён заказчиком")
    if to == "in_progress" and task.status == "todo":
        before = waiting(task, plan.tasks)
        if before and not actor.can("work_manage"):
            names = ", ".join(t.title for t in before)
            raise WorkError(f"задача ждёт: {names} — начать раньше может только студия")
    if to == "review" and task.photo == "required" and not task.photos:
        raise WorkError(f"сдать задачу «{task.title}» можно только с фото")
    if to == "returned" and not text:
        raise WorkError("comment: вернуть задачу можно только с комментарием", 422)
    before_status, task.status = task.status, to
    feed(task, actor, "return" if to == "returned" else "status", text, to)
    session.flush()
    payload = {"task": str(task.id), "from": before_status, "to": to}
    audit(session, actor, project, "work_status", payload)
    return task


# --- Lines ------------------------------------------------------------------------------


def edit_line(
    plan: WorkPlan, task: WorkTask, line: WorkLine, data: Mapping[str, Any], actor: Actor
) -> WorkLine:
    """fact_qty — the installer, while the task is not accepted (null — as planned); price — the
    studio, until the client approves (null — no price)."""
    check_open(plan)
    unknown = set(data) - {"fact_qty", "price"}
    if unknown:
        raise WorkError(f"{sorted(unknown)[0]}: у строки меняются только fact_qty и price", 422)
    if "fact_qty" in data:
        actor.need("work_do")
        if plan.state != "approved" or task.status in ("proposed", "accepted"):
            raise WorkError("факт вписывается в задачу, которая в работе")
        line.fact_qty = number_field(data["fact_qty"], "fact_qty")
    if "price" in data:
        actor.need("work_manage")
        _money(plan, task)
        line.price = number_field(data["price"], "price")
    return line


def add_line(plan: WorkPlan, task: WorkTask, data: Mapping[str, Any], actor: Actor) -> WorkLine:
    """The studio's own line: {title, kind: work | material, unit?, qty, price?, key?}."""
    actor.need("work_manage")
    check_open(plan)
    _money(plan, task)
    line = _line(len(task.lines), data, "line")
    task.lines.append(line)
    return line
