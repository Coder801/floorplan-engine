"""Tasks of a work plan (docs/work-tasks.md): the studio adds, edits, orders, links (after),
merges and deletes them and moves lines between them. The plan, statuses, lines and the errors
are in db/work.py; like it, functions take an open Session and do not commit.

Order: positions are always 0…n-1 without gaps — every change renumbers the whole list. `after`
holds keys or ids of tasks of the same plan; a task never comes after itself and the links never
close a circle. Lines move and tasks merge only while the money is open (work.money_editable):
the totals are counted from the lines, so they follow by themselves.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, TypeVar

from sqlalchemy.orm import Session

from floorplan_engine.service.db.models import Project, WorkComment, WorkLine, WorkPlan, WorkTask
from floorplan_engine.service.db.work import (
    DOMAINS,
    PHOTO,
    TEXT_MAX,
    TITLE_MAX,
    Actor,
    WorkError,
    assignees,
    audit,
    check_open,
    need_money,
    parse_line,
    refers,
    text_field,
)

_Row = TypeVar("_Row", WorkLine, WorkComment)
EDITABLE = ("title", "description", "position", "assignee_id", "materials_included", "photo")


def ordered(plan: WorkPlan) -> list[WorkTask]:
    """The tasks in their order; equal positions (should not happen) keep the list order."""
    return sorted(plan.tasks, key=lambda t: t.position)


def renumber(tasks: Iterable[WorkTask]) -> None:
    for k, t in enumerate(tasks):
        t.position = k


def ref_of(task: WorkTask) -> str:
    """How other tasks refer to this one: the draft key, the id for the studio's own task."""
    return task.key or str(task.id)


def _target(tasks: Iterable[WorkTask], ref: str) -> WorkTask | None:
    return next((t for t in tasks if refers(t, ref)), None)


def find_cycle(
    tasks: Sequence[WorkTask], after: Mapping[uuid.UUID, Sequence[str]]
) -> list[WorkTask] | None:
    """A circle of `after` links among the tasks (after[id] overrides the task's own list): the
    tasks along it, the first one again at the end; None — no circle."""
    edges = {
        t.id: [
            dep
            for ref in after.get(t.id, t.after)
            if (dep := _target(tasks, str(ref))) is not None and dep.id != t.id
        ]
        for t in tasks
    }
    state: dict[uuid.UUID, int] = {}  # 1 — on the path, 2 — done
    path: list[WorkTask] = []

    def visit(t: WorkTask) -> list[WorkTask] | None:
        state[t.id] = 1
        path.append(t)
        for dep in edges[t.id]:
            if state.get(dep.id) == 1:
                return [*path[path.index(dep) :], dep]
            if dep.id not in state and (found := visit(dep)) is not None:
                return found
        path.pop()
        state[t.id] = 2
        return None

    for t in tasks:
        if t.id not in state and (found := visit(t)) is not None:
            return found
    return None


def _no_cycle(
    tasks: Sequence[WorkTask], after: Mapping[uuid.UUID, Sequence[str]], field: str
) -> None:
    cycle = find_cycle(tasks, after)
    if cycle is not None:
        names = " → ".join(f"«{t.title}»" for t in cycle)
        raise WorkError(f"{field}: зависимость по кругу: {names}", 422)


def after_refs(plan: WorkPlan, task: WorkTask, value: object) -> list[str]:
    """`after` of a task, checked: keys or ids of other tasks of the plan, each task once, no
    circle."""
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise WorkError("after: нужен список id или ключей задач", 422)
    refs: list[str] = []
    seen: set[uuid.UUID] = set()
    for k, ref in enumerate(value):
        dep = _target(plan.tasks, ref)
        if dep is None:
            raise WorkError(f"after[{k}]: нет задачи {ref} в плане", 422)
        if dep.id == task.id:
            raise WorkError(f"after[{k}]: задача не может идти после самой себя", 422)
        if dep.id not in seen:
            seen.add(dep.id)
            refs.append(ref)
    _no_cycle(plan.tasks, {task.id: refs}, "after")
    return refs


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
        checked=[],
        after=[],
        materials_included=bool(data.get("materials_included", True)),
    )
    for j, ln in enumerate(lines):
        if not isinstance(ln, dict):
            raise WorkError(f"lines[{j}]: нужен объект", 422)
        task.lines.append(parse_line(j, ln, f"lines[{j}]"))
    order = ordered(plan)
    plan.tasks.append(task)
    renumber([*order, task])
    session.flush()
    payload = {"task": str(task.id), "title": task.title, "extra": task.extra}
    audit(session, actor, project, "work_task_add", payload)
    return task


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
    unknown = set(data) - {*EDITABLE, "after"}
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
            need_money(plan, task)
        task.materials_included = data["materials_included"]
    if "after" in data:
        task.after = after_refs(plan, task, data["after"])
    if "assignee_id" in data:
        task.assignee_id = _assignee(session, project, data["assignee_id"])
    if "position" in data:
        at = data["position"]
        if isinstance(at, bool) or not isinstance(at, int) or not 0 <= at < len(plan.tasks):
            raise WorkError(f"position: от 0 до {len(plan.tasks) - 1}", 422)
        order = [t for t in ordered(plan) if t.id != task.id]
        order.insert(at, task)
        renumber(order)
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


def _drop(plan: WorkPlan, gone: WorkTask, into: WorkTask | None = None) -> None:
    """Remove a task from the plan: links to it go to `into` (a merge) or away (a delete), each
    task keeps every dependency once and never itself; the rest are renumbered."""
    rest = [t for t in ordered(plan) if t.id != gone.id]
    for t in rest:
        t.after = _relinked(rest, t, t.after, gone, into)
    plan.tasks.remove(gone)
    renumber(rest)


def _relinked(
    tasks: Sequence[WorkTask],
    task: WorkTask,
    refs: Iterable[Any],
    gone: WorkTask,
    into: WorkTask | None,
) -> list[str]:
    out: list[str] = []
    seen: set[uuid.UUID] = set()
    for raw in refs:
        ref = str(raw)
        if refers(gone, ref):
            if into is None:
                continue
            ref = ref_of(into)
        dep = _target(tasks, ref)
        if dep is None or dep.id == task.id or dep.id in seen:
            continue
        seen.add(dep.id)
        out.append(ref)
    return out


def delete_task(
    session: Session, project: Project, plan: WorkPlan, task: WorkTask, actor: Actor
) -> None:
    """Only a task not started, without photos and payments; links to it are removed."""
    actor.need("work_manage")
    check_open(plan)
    if task.status not in ("proposed", "todo") or task.photos or task.payments:
        raise WorkError("удалить можно задачу, которую ещё не начали, без фото и оплат")
    audit(session, actor, project, "work_task_delete", {"task": str(task.id), "title": task.title})
    _drop(plan, task)
    session.flush()


def _other_task(plan: WorkPlan, task: WorkTask, value: object, field: str) -> WorkTask:
    """The task a body field points to (an id of the same plan), not this one."""
    if not isinstance(value, str):
        raise WorkError(f"{field}: нужен id задачи", 422)
    other = next((t for t in plan.tasks if str(t.id) == value), None)
    if other is None:
        raise WorkError(f"{field}: нет задачи {value} в плане", 422)
    if other.id == task.id:
        raise WorkError(f"{field}: это та же задача", 422)
    return other


def _hand_over(session: Session, source: list[_Row], target: list[_Row], rows: list[_Row]) -> None:
    """Move rows from a task's collection to another's. Both are loaded before (they are the
    arguments), and nothing is flushed in between: at a flush delete-orphan deletes a row that
    has no task."""
    with session.no_autoflush:
        for row in rows:
            source.remove(row)
        target.extend(rows)


def _renumber_lines(task: WorkTask) -> None:
    for k, line in enumerate(task.lines):
        line.position = k


def move_lines(
    session: Session,
    project: Project,
    plan: WorkPlan,
    task: WorkTask,
    data: Mapping[str, Any],
    actor: Actor,
) -> WorkTask:
    """Move lines of a task to another one: {line_ids: [id, …], to_task: id}. The studio, while the
    money of both tasks is open; the lines go to the end of the target in the order of the source.
    The target task."""
    actor.need("work_manage")
    check_open(plan)
    ids = data.get("line_ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(v, str) for v in ids):
        raise WorkError("line_ids: нужен непустой список id строк", 422)
    target = _other_task(plan, task, data.get("to_task"), "to_task")
    need_money(plan, task)
    need_money(plan, target)
    by_id = {str(ln.id): ln for ln in task.lines}
    for k, line_id in enumerate(ids):
        if line_id not in by_id:
            raise WorkError(f"line_ids[{k}]: нет строки {line_id} в задаче «{task.title}»", 422)
    chosen = set(ids)
    moving = [ln for ln in task.lines if str(ln.id) in chosen]
    _hand_over(session, task.lines, target.lines, moving)
    _renumber_lines(task)
    _renumber_lines(target)
    session.flush()
    payload = {"task": str(task.id), "to": str(target.id), "lines": [str(ln.id) for ln in moving]}
    audit(session, actor, project, "work_lines_move", payload)
    return target


def merge_task(
    session: Session,
    project: Project,
    plan: WorkPlan,
    task: WorkTask,
    data: Mapping[str, Any],
    actor: Actor,
) -> WorkTask:
    """Merge a task into another: {into: id}. The studio, while the money of both is open, only a
    task without photos and payments. Its lines, comments and acceptance items (with their ticks)
    go to the target, its description is added to the target's, links to it lead to the target;
    the task is deleted. The target task."""
    actor.need("work_manage")
    check_open(plan)
    target = _other_task(plan, task, data.get("into"), "into")
    need_money(plan, task)
    need_money(plan, target)
    if task.photos or task.payments:
        raise WorkError("объединить можно задачу без фото и оплат")
    rest = [t for t in ordered(plan) if t.id != task.id]
    after = {
        t.id: _relinked(rest, t, [*t.after, *(task.after if t is target else [])], task, target)
        for t in rest
    }
    _no_cycle(rest, after, "into")
    lines = list(task.lines)
    _hand_over(session, task.lines, target.lines, lines)
    _hand_over(session, task.comments, target.comments, list(task.comments))
    _renumber_lines(target)
    results, checked = list(target.result), {int(k) for k in target.checked}
    ticked = {int(k) for k in task.checked}
    for k, item in enumerate(task.result):
        if item not in results:
            results.append(item)
        if k in ticked:
            checked.add(results.index(item))
    target.result, target.checked = results, sorted(checked)
    if task.description and task.description not in target.description:
        joined = "\n\n".join(d for d in (target.description, task.description) if d)
        target.description = joined[:TEXT_MAX]
    if target.assignee_id is None:
        target.assignee_id = task.assignee_id
    payload = {
        "task": str(task.id),
        "title": task.title,
        "into": str(target.id),
        "lines": len(lines),
    }
    for t in rest:
        t.after = after[t.id]
    plan.tasks.remove(task)
    renumber(rest)
    session.flush()
    audit(session, actor, project, "work_task_merge", payload)
    return target
