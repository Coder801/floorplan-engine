"""Tasks of a work plan (service/db/work_tasks.py; docs/work-tasks.md): the studio's own and extra
tasks, editing, order without gaps, `after` links without self and circles, deleting, moving
lines and merging tasks while the money is open."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from floorplan_engine.service.db import work
from floorplan_engine.service.db import work_records as records
from floorplan_engine.service.db import work_tasks as tasks
from floorplan_engine.service.db.models import AuditEvent, WorkPlan, WorkTask
from tests.service.conftest import DRAFT, World, draft_line, fails


def _draft(world: World) -> tuple[WorkPlan, WorkTask, WorkTask, WorkTask]:
    """A draft plan: chases, cable (after chases) and the studio's own panel task at the end."""
    plan = work.create_plan(world.db, world.project, world.build, DRAFT, world.owner)
    data = {"title": "Щит", "lines": [draft_line("work.panel", "work", 1.0, 2000.0)]}
    panel = tasks.add_task(world.db, world.project, plan, data, world.owner)
    chases, cable, _ = plan.tasks
    return plan, chases, cable, panel


def _edit(world: World, task: WorkTask, data: dict[str, object]) -> None:
    tasks.edit_task(world.db, world.project, world.plan(), task, data, world.owner)


def test_extra_work_after_approval(world: World) -> None:
    plan, chases, _ = world.approved()
    data = {"title": "Перенос розетки", "lines": [draft_line("", "work", 1.0, 400.0)]}
    with fails(403):
        tasks.add_task(world.db, world.project, plan, data, world.installer)
    with fails(422, "title"):
        tasks.add_task(world.db, world.project, plan, {"title": " "}, world.owner)
    with fails(422, "lines[0].kind"):
        tasks.add_task(
            world.db, world.project, plan, {"title": "x", "lines": [{"kind": "x"}]}, world.owner
        )
    extra = tasks.add_task(world.db, world.project, plan, data, world.owner)
    assert (extra.extra, extra.status, extra.domain, extra.position) == (
        True,
        "proposed",
        "other",
        2,
    )
    assert work.money_editable(plan, extra) and not work.money_editable(plan, chases)
    line = work.add_line(plan, extra, draft_line("", "material", 1.0, 60.0), world.owner)
    work.edit_line(plan, extra, line, {"price": 80.0}, world.owner)
    assert work.totals(extra).total == 480.0
    with fails(409, "согласована"):
        work.add_line(plan, chases, draft_line("", "work", 1.0, 1.0), world.owner)
    with fails(403):
        world.status(extra, "todo", world.installer)
    world.status(extra, "todo", world.client)  # the client agrees to the price
    with fails(409, "согласована"):
        work.edit_line(plan, extra, line, {"price": 1.0}, world.owner)


def test_edit_order_after_assignee_and_delete(world: World) -> None:
    plan, chases, cable = world.approved()
    data = {"title": "Новое", "description": "у окна", "photo": "none"}
    tasks.edit_task(world.db, world.project, plan, chases, data, world.owner)
    assert (chases.title, chases.description, chases.photo) == ("Новое", "у окна", "none")
    with fails(422, "after[0]: нет задачи"):
        tasks.edit_task(world.db, world.project, plan, chases, {"after": ["x"]}, world.owner)
    with fails(422, "это поле"):
        tasks.edit_task(world.db, world.project, plan, chases, {"status": "todo"}, world.owner)
    with fails(422, "position"):
        tasks.edit_task(world.db, world.project, plan, chases, {"position": 5}, world.owner)
    tasks.edit_task(world.db, world.project, plan, cable, {"position": 0}, world.owner)
    assert [t.key for t in world.plan().tasks] == ["electrical.cable", "electrical.chases"]
    people = {u.email for u in work.assignees(world.db, world.project)}
    assert people == {"a@example.com", "i@example.com"}  # the studio and invited installers
    installer = str(world.users["i"].id)
    tasks.edit_task(world.db, world.project, plan, cable, {"assignee_id": installer}, world.owner)
    assert cable.assignee_id == world.users["i"].id
    client = str(world.users["c"].id)
    with fails(422, "assignee_id"):
        tasks.edit_task(world.db, world.project, plan, cable, {"assignee_id": client}, world.owner)
    tasks.edit_task(world.db, world.project, plan, cable, {"assignee_id": None}, world.owner)
    assert cable.assignee_id is None
    world.photo(cable, world.owner)
    with fails(409, "без фото и оплат"):
        tasks.delete_task(world.db, world.project, plan, cable, world.owner)
    with fails(403):
        tasks.delete_task(world.db, world.project, plan, chases, world.installer)
    tasks.delete_task(world.db, world.project, plan, chases, world.owner)
    assert [(t.key, t.position) for t in world.plan().tasks] == [("electrical.cable", 0)]
    assert cable.after == []  # the link to the deleted task goes away


def test_order_has_no_gaps_or_duplicates(world: World) -> None:
    plan, chases, cable, panel = _draft(world)
    assert [t.position for t in plan.tasks] == [0, 1, 2]
    chases.position, cable.position, panel.position = 5, 9, 5  # broken by hand
    _edit(world, panel, {"position": 0})
    assert [(t.title, t.position) for t in world.plan().tasks] == [
        ("Щит", 0),
        ("Штробы", 1),
        ("Прокладка кабеля", 2),
    ]
    _edit(world, panel, {"position": 2})
    assert [t.position for t in world.plan().tasks] == [0, 1, 2]
    assert world.plan().tasks[-1].id == panel.id
    for bad in (-1, 3, True, "1"):
        with fails(422, "position: от 0 до 2"):
            _edit(world, panel, {"position": bad})
    added = tasks.add_task(world.db, world.project, plan, {"title": "Ещё"}, world.owner)
    assert added.position == 3
    tasks.delete_task(world.db, world.project, plan, chases, world.owner)
    assert [t.position for t in world.plan().tasks] == [0, 1, 2]


def test_after_links_are_checked(world: World) -> None:
    _, chases, cable, panel = _draft(world)
    with fails(422, "after[0]: задача не может идти после самой себя"):
        _edit(world, panel, {"after": [str(panel.id)]})
    with fails(422, "after[1]: нет задачи x в плане"):
        _edit(world, panel, {"after": ["electrical.cable", "x"]})
    with fails(422, "after: нужен список"):
        _edit(world, panel, {"after": "electrical.cable"})
    _edit(world, panel, {"after": ["electrical.cable", str(cable.id), "electrical.chases"]})
    assert panel.after == ["electrical.cable", "electrical.chases"]  # each task once
    with fails(
        422, "after: зависимость по кругу: «Штробы» → «Щит» → «Прокладка кабеля» → «Штробы»"
    ):
        _edit(world, chases, {"after": [str(panel.id)]})
    with fails(422, "по кругу"):
        _edit(world, chases, {"after": ["electrical.cable"]})
    assert chases.after == []  # a refused change leaves the links as they were
    _edit(world, panel, {"after": []})
    _edit(world, chases, {"after": [str(panel.id)]})  # no circle now
    assert work.waiting(chases, world.plan().tasks) == [panel]


def test_find_cycle() -> None:
    a, b, c = (WorkTask(key=k, after=[]) for k in ("a", "b", "c"))
    for t in (a, b, c):
        t.id = uuid.uuid4()
    assert tasks.find_cycle([a, b, c], {a.id: ["b"], b.id: ["c"]}) is None
    assert tasks.find_cycle([a, b, c], {a.id: ["b"], b.id: ["c"], c.id: ["a"]}) == [a, b, c, a]
    assert tasks.find_cycle([a, b], {a.id: ["a", "zzz"]}) is None  # self and unknown: no edge


def test_move_lines(world: World) -> None:
    plan, chases, cable, panel = _draft(world)
    brick, box = chases.lines
    move = {"line_ids": [str(box.id)], "to_task": str(panel.id)}
    with fails(403):
        tasks.move_lines(world.db, world.project, plan, chases, move, world.installer)
    with fails(422, "line_ids: нужен непустой список"):
        tasks.move_lines(
            world.db, world.project, plan, chases, {**move, "line_ids": []}, world.owner
        )
    alien = {**move, "line_ids": [str(box.id), str(cable.lines[0].id)]}
    with fails(422, "line_ids[1]: нет строки"):
        tasks.move_lines(world.db, world.project, plan, chases, alien, world.owner)
    with fails(422, "to_task: это та же задача"):
        tasks.move_lines(
            world.db, world.project, plan, chases, {**move, "to_task": str(chases.id)}, world.owner
        )
    with fails(422, "to_task: нет задачи"):
        tasks.move_lines(
            world.db, world.project, plan, chases, {**move, "to_task": "x"}, world.owner
        )
    target = tasks.move_lines(world.db, world.project, plan, chases, move, world.owner)
    assert target is panel
    assert [(ln.key, ln.position) for ln in panel.lines] == [("work.panel", 0), ("socket_box", 1)]
    assert [(ln.key, ln.position) for ln in chases.lines] == [("work.chase.brick", 0)]
    assert (work.totals(chases).total, work.totals(panel).total) == (1200.0, 2060.0)
    world.db.expire_all()  # as the database has it: the line moved, it was not deleted
    assert [ln.key for ln in world.plan().tasks[2].lines] == ["work.panel", "socket_box"]
    every = {"line_ids": [str(ln.id) for ln in cable.lines], "to_task": str(chases.id)}
    tasks.move_lines(world.db, world.project, plan, cable, every, world.owner)
    assert cable.lines == [] and work.totals(cable).total == 0.0  # an empty task may stay
    assert [ln.position for ln in chases.lines] == [0, 1, 2]
    actions = world.db.scalars(select(AuditEvent.action)).all()
    assert actions.count("work_lines_move") == 2
    assert brick in chases.lines


def test_move_lines_only_while_money_is_open(world: World) -> None:
    plan, chases, cable = world.approved()
    move = {"line_ids": [str(chases.lines[0].id)], "to_task": str(cable.id)}
    with fails(409, "согласована"):
        tasks.move_lines(world.db, world.project, plan, chases, move, world.owner)
    extra = tasks.add_task(world.db, world.project, plan, {"title": "Доп"}, world.owner)
    with fails(409, "согласована"):  # the source is agreed already
        tasks.move_lines(
            world.db, world.project, plan, chases, {**move, "to_task": str(extra.id)}, world.owner
        )
    line = work.add_line(plan, extra, draft_line("", "work", 1.0, 100.0), world.owner)
    other = tasks.add_task(world.db, world.project, plan, {"title": "Доп 2"}, world.owner)
    world.db.flush()
    back = {"line_ids": [str(line.id)], "to_task": str(other.id)}
    tasks.move_lines(world.db, world.project, plan, extra, back, world.owner)  # both open
    assert work.totals(other).total == 100.0
    world.status(other, "todo", world.client)  # agreed: closed for money
    with fails(409, "согласована"):
        back = {"line_ids": [str(line.id)], "to_task": str(extra.id)}
        tasks.move_lines(world.db, world.project, plan, other, back, world.owner)
    plan.state = "closed"
    with fails(409, "закрыт"):
        tasks.move_lines(world.db, world.project, plan, extra, back, world.owner)


def test_merge_tasks(world: World) -> None:
    plan, chases, cable, panel = _draft(world)
    _edit(world, panel, {"after": ["electrical.cable"]})
    _edit(world, cable, {"description": "по потолку"})
    chases.checked, cable.checked = [], [0]  # ticks follow their items (synthetic)
    into = {"into": str(chases.id)}
    with fails(403):
        tasks.merge_task(world.db, world.project, plan, cable, into, world.installer)
    with fails(422, "into: это та же задача"):
        tasks.merge_task(world.db, world.project, plan, chases, into, world.owner)
    with fails(422, "into: нужен id задачи"):
        tasks.merge_task(world.db, world.project, plan, cable, {}, world.owner)
    with fails(422, "into: нет задачи"):
        tasks.merge_task(
            world.db, world.project, plan, cable, {"into": "electrical.chases"}, world.owner
        )
    total = work.totals(chases).total + work.totals(cable).total
    target = tasks.merge_task(world.db, world.project, plan, cable, into, world.owner)
    assert target is chases
    plan = world.plan()
    assert [(t.title, t.position) for t in plan.tasks] == [("Штробы", 0), ("Щит", 1)]
    assert [ln.position for ln in chases.lines] == [0, 1, 2, 3]
    assert work.totals(chases).total == total and work.totals(chases).unpriced == 1
    assert chases.result == ["штроба выбрана", "кабель закреплён"] and chases.checked == [1]
    assert chases.description == "по потолку"
    assert chases.after == []  # cable came after chases: not after itself
    assert panel.after == ["electrical.chases"]  # led to the merged task, now to the target
    event = world.db.scalars(select(AuditEvent).where(AuditEvent.action == "work_task_merge")).one()
    assert event.payload["into"] == str(chases.id) and event.payload["lines"] == 2
    world.db.expire_all()
    assert len(world.plan().tasks[0].lines) == 4  # as the database has it


def test_merge_refuses_a_circle(world: World) -> None:
    plan, chases, _, panel = _draft(world)
    _edit(world, panel, {"after": ["electrical.cable"]})
    # panel into chases: chases would come after cable, and cable comes after chases
    with fails(422, "into: зависимость по кругу"):
        tasks.merge_task(
            world.db, world.project, plan, panel, {"into": str(chases.id)}, world.owner
        )
    assert len(world.plan().tasks) == 3 and chases.after == [] and len(panel.lines) == 1


def test_merge_only_while_money_is_open_without_photos(world: World) -> None:
    plan, chases, cable = world.approved()
    with fails(409, "согласована"):
        tasks.merge_task(
            world.db, world.project, plan, cable, {"into": str(chases.id)}, world.owner
        )
    one = tasks.add_task(world.db, world.project, plan, {"title": "Доп 1"}, world.owner)
    two = tasks.add_task(world.db, world.project, plan, {"title": "Доп 2"}, world.owner)
    with fails(409, "согласована"):  # an agreed target
        tasks.merge_task(world.db, world.project, plan, one, {"into": str(chases.id)}, world.owner)
    world.photo(one, world.installer)
    with fails(409, "без фото и оплат"):
        tasks.merge_task(world.db, world.project, plan, one, {"into": str(two.id)}, world.owner)
    records.add_payment(
        world.db, world.project, plan, two, {"amount": 10, "paid_on": "2026-11-12"}, world.owner
    )
    with fails(409, "без фото и оплат"):
        tasks.merge_task(world.db, world.project, plan, two, {"into": str(one.id)}, world.owner)
    three = tasks.add_task(world.db, world.project, plan, {"title": "Доп 3"}, world.owner)
    records.add_comment(plan, three, "а розетку выше?", world.client)
    tasks.merge_task(world.db, world.project, plan, three, {"into": str(one.id)}, world.owner)
    assert [c.text for c in one.comments] == ["а розетку выше?"]  # the feed is kept
    assert [t.title for t in world.plan().tasks] == ["Штробы", "Прокладка кабеля", "Доп 1", "Доп 2"]
