"""Installation by tasks (service/db/work.py, service/api/work.py; docs/work-tasks.md): the plan
from the .epd draft, its life, task statuses with their rules, sums counted from the lines, and
the API by role (photos, comments, payments of a task — test_work_records.py)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from floorplan_engine.service import sync
from floorplan_engine.service.api.auth import COOKIE, Auth, AuthConfig
from floorplan_engine.service.api.viewer import create_viewer
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db import access_codes, work, work_tasks
from floorplan_engine.service.db import work_records as records
from floorplan_engine.service.db.models import (
    AuditEvent,
    Project,
)
from floorplan_engine.service.db.session import make_sessions
from floorplan_engine.service.objects import LocalObjectStore
from tests.electrical.test_variants import _project
from tests.service.conftest import DRAFT, PNG, World, fails


def test_plan_from_the_draft(world: World) -> None:
    with fails(403):
        work.create_plan(world.db, world.project, world.build, DRAFT, world.client)
    with fails(409, "нет черновика"):
        work.create_plan(world.db, world.project, world.build, {"tasks": []}, world.owner)
    with fails(409, "нет черновика"):
        work.create_plan(world.db, world.project, None, DRAFT, world.owner)
    plan = work.create_plan(world.db, world.project, world.build, DRAFT, world.owner)
    assert (plan.state, plan.currency, plan.build_id) == ("draft", "грн", world.build.id)
    assert plan.model_version_id == world.build.model_version_id
    chases, cable = plan.tasks
    assert [t.status for t in plan.tasks] == ["proposed", "proposed"]
    assert (chases.key, chases.position, cable.position, cable.photo) == (
        "electrical.chases",
        0,
        1,
        "required",
    )
    assert [ln.key for ln in chases.lines] == ["work.chase.brick", "socket_box"]
    t = work.totals(chases)
    assert (t.work, t.material, t.total, t.paid, t.unpriced) == (1200.0, 60.0, 1260.0, 0.0, 0)
    assert work.totals(cable).unpriced == 1 and work.totals(cable).material == 0.0
    with fails(409, "уже есть план"):
        work.create_plan(world.db, world.project, world.build, DRAFT, world.owner)


def test_plan_life_and_close(world: World) -> None:
    work.create_plan(world.db, world.project, world.build, DRAFT, world.owner)
    plan = world.plan()
    with fails(409, "draft"):
        work.plan_action(world.db, world.project, plan, "approve", world.client)
    with fails(403):
        work.plan_action(world.db, world.project, plan, "propose", world.installer)
    with fails(404):
        work.plan_action(world.db, world.project, plan, "sign", world.owner)
    work.plan_action(world.db, world.project, plan, "propose", world.owner)
    with fails(403):
        work.plan_action(world.db, world.project, plan, "approve", world.installer)
    work.plan_action(world.db, world.project, plan, "approve", world.code)
    assert plan.state == "approved" and plan.approved_label == "код: Иван"
    assert plan.approved_at is not None and plan.approved_by is None
    assert [t.status for t in plan.tasks] == ["todo", "todo"]
    chases, cable = plan.tasks
    with fails(409, "не приняты или не оплачены: Штробы, Прокладка кабеля"):
        work.plan_action(world.db, world.project, plan, "close", world.owner)
    for task in (chases, cable):
        world.status(task, "in_progress", world.owner)
        world.photo(task, world.installer)
        world.status(task, "review", world.installer)
        world.status(task, "accepted", world.client)
    with fails(409, "не оплачены"):
        work.plan_action(world.db, world.project, plan, "close", world.owner)
    for task in (chases, cable):
        total = work.totals(task).total
        records.add_payment(
            world.db,
            world.project,
            plan,
            task,
            {"amount": total, "paid_on": "2026-11-11"},
            world.owner,
        )
        assert work.totals(task).settled
    work.plan_action(world.db, world.project, plan, "close", world.owner)
    assert plan.state == "closed" and plan.closed_at is not None
    with fails(409, "закрыт"):
        records.add_comment(plan, chases, "ещё", world.client)
    # A closed plan does not block a new one
    assert work.create_plan(world.db, world.project, world.build, DRAFT, world.owner).state == (
        "draft"
    )
    assert world.plan().state == "draft"  # the open plan comes first


def test_discard_a_plan_not_approved(world: World) -> None:
    work.create_plan(world.db, world.project, world.build, DRAFT, world.owner)
    assert work.plan_action(world.db, world.project, world.plan(), "discard", world.owner) is None
    assert work.current_plan(world.db, world.project) is None
    plan, _, _ = world.approved()
    with fails(409):
        work.plan_action(world.db, world.project, plan, "discard", world.owner)


def test_status_rules(world: World) -> None:
    plan, chases, cable = world.approved()
    assert work.waiting(cable, plan.tasks) == [chases]
    with fails(409, "задача ждёт: Штробы"):
        world.status(cable, "in_progress", world.installer)
    with fails(403):
        world.status(chases, "in_progress", world.client)
    with fails(409, "«к работе» нельзя перевести в «принята»"):
        world.status(chases, "accepted", world.client)
    with fails(422, "to:"):
        world.status(chases, "done", world.installer)
    world.status(cable, "in_progress", world.owner)  # the studio may start a waiting task
    with fails(409, "только с фото"):
        world.status(cable, "review", world.installer)
    world.photo(cable, world.installer)
    world.status(cable, "review", world.installer)
    with fails(422, "только с комментарием"):
        world.status(cable, "returned", world.client)
    world.status(cable, "returned", world.client, "кабель не закреплён у окна")
    world.status(cable, "review", world.installer)
    world.status(cable, "accepted", world.code)
    world.status(chases, "in_progress", world.installer)  # optional photo: hand in without
    world.status(chases, "review", world.installer)
    assert [(c.kind, c.status, c.author_label) for c in cable.comments] == [
        ("status", "in_progress", "A"),
        ("status", "review", "I"),
        ("return", "returned", "C"),
        ("status", "review", "I"),
        ("status", "accepted", "код: Иван"),
    ]
    assert cable.comments[2].text == "кабель не закреплён у окна"
    actions = world.db.scalars(select(AuditEvent.action)).all()
    assert actions.count("work_status") == 7 and "work_photo" in actions
    coded = world.db.scalars(
        select(AuditEvent).where(AuditEvent.action == "work_plan_approve")
    ).one()
    assert coded.user_id == world.users["c"].id


def test_draft_plan_has_no_work(world: World) -> None:
    work.create_plan(world.db, world.project, world.build, DRAFT, world.owner)
    plan = world.plan()
    plan.tasks[0].status = "todo"  # even so: the plan is not approved
    with fails(409, "не утверждён"):
        world.status(plan.tasks[0], "in_progress", world.owner)
    with fails(409, "после утверждения"):
        world.photo(plan.tasks[0], world.owner)
    with fails(409, "после утверждения"):
        records.add_payment(
            world.db,
            world.project,
            plan,
            plan.tasks[0],
            {"amount": 1, "paid_on": "2026-11-11"},
            world.owner,
        )


def test_sums_follow_fact_and_materials(world: World) -> None:
    plan, chases, _ = world.approved()
    chase, box = chases.lines
    with fails(409, "в работе"):  # not in the plan yet: todo is fine, proposed is not
        chases.status = "proposed"
        work.edit_line(plan, chases, chase, {"fact_qty": 12}, world.installer)
    chases.status = "todo"
    work.edit_line(plan, chases, chase, {"fact_qty": 12}, world.installer)
    assert work.totals(chases).work == 1440.0 and work.line_sum(chase) == 1440.0
    with fails(403):
        work.edit_line(plan, chases, chase, {"fact_qty": 1}, world.client)
    with fails(403):
        work.edit_line(plan, chases, chase, {"price": 1}, world.installer)
    with fails(409, "согласована"):
        work.edit_line(plan, chases, chase, {"price": 1}, world.owner)
    with fails(422, "fact_qty"):
        work.edit_line(plan, chases, chase, {"fact_qty": -1}, world.installer)
    with fails(422, "qty:"):
        work.edit_line(plan, chases, box, {"qty": 1}, world.owner)
    work.edit_line(plan, chases, chase, {"fact_qty": None}, world.installer)  # back to the plan
    assert work.totals(chases).total == 1260.0
    with fails(409, "согласована"):
        work_tasks.edit_task(
            world.db, world.project, plan, chases, {"materials_included": False}, world.owner
        )
    t = work.Totals(100.0, 50.0, 100.0, 0, False)
    assert t.total == 100.0 and t.settled


def test_studio_acts_for_the_client_only_with_a_channel(world: World) -> None:
    """Decision 2026-11-12: a work_accept action by the studio needs on_behalf (how the client
    confirmed); the client never sends it; other actions do not take it."""
    work.create_plan(world.db, world.project, world.build, DRAFT, world.owner)
    plan = world.plan()
    work.plan_action(world.db, world.project, plan, "propose", world.owner)
    with fails(422, "on_behalf: за заказчика — только с его подтверждением"):
        work.plan_action(world.db, world.project, plan, "approve", world.owner)
    with fails(422, "on_behalf: одно из phone, telegram, other"):
        work.plan_action(world.db, world.project, plan, "approve", world.owner, {"on_behalf": "x"})
    with fails(422, "note: нужна строка"):
        body = {"on_behalf": "phone", "note": 5}
        work.plan_action(world.db, world.project, plan, "approve", world.owner, body)
    with fails(422, "on_behalf: заказчик действует сам"):
        work.plan_action(
            world.db, world.project, plan, "approve", world.client, {"on_behalf": "phone"}
        )
    with fails(422, "on_behalf: заказчик действует сам"):
        work.plan_action(world.db, world.project, plan, "approve", world.code, {"note": "я"})
    assert plan.state == "proposed"
    body = {"on_behalf": "phone", "note": " звонок 12.11 "}
    work.plan_action(world.db, world.project, plan, "approve", world.owner, body)
    assert (plan.state, plan.approved_by, plan.approved_label) == (
        "approved",
        world.users["a"].id,
        "A",
    )
    assert (plan.approved_on_behalf, plan.approved_note) == ("phone", "звонок 12.11")
    event = world.db.scalars(
        select(AuditEvent).where(AuditEvent.action == "work_plan_approve")
    ).one()
    assert event.payload["on_behalf"] == "phone" and event.payload["note"] == "звонок 12.11"

    chases, cable = plan.tasks
    world.status(chases, "in_progress", world.owner)  # work_do: nothing to confirm
    with fails(422, "это не действие заказчика"):
        world.status(chases, "review", world.installer, body={"on_behalf": "phone"})
    world.status(chases, "review", world.installer)
    with fails(422, "on_behalf"):
        world.status(chases, "accepted", world.owner)
    with fails(422, "on_behalf"):  # the reason is checked first
        world.status(chases, "returned", world.owner, "криво", {})
    world.status(chases, "returned", world.owner, "криво", {"on_behalf": "telegram"})
    world.status(chases, "review", world.installer)
    superuser = work.Actor("superuser", world.users["a"], "A")
    with fails(422, "on_behalf"):
        world.status(chases, "accepted", superuser)
    world.status(chases, "accepted", world.owner, None, {"on_behalf": "other", "note": "в чате"})
    assert [(c.kind, c.on_behalf, c.on_behalf_note) for c in chases.comments] == [
        ("status", None, ""),
        ("status", None, ""),
        ("return", "telegram", ""),
        ("status", None, ""),
        ("status", "other", "в чате"),
    ]
    extra = work_tasks.add_task(world.db, world.project, plan, {"title": "Доп"}, world.owner)
    with fails(422, "on_behalf"):
        world.status(extra, "todo", world.owner)
    world.status(extra, "todo", world.client)  # the client agrees by themselves
    assert extra.comments[-1].on_behalf is None
    statuses = world.db.scalars(select(AuditEvent).where(AuditEvent.action == "work_status"))
    assert [e.payload.get("on_behalf") for e in statuses][-4:] == ["telegram", None, "other", None]
    assert cable.status == "todo"


def test_acceptance_ticks_are_kept(world: World) -> None:
    work.create_plan(world.db, world.project, world.build, DRAFT, world.owner)
    plan = world.plan()
    chases = plan.tasks[0]
    chases.result = ["штроба выбрана", "мусор убран", "глубина 25 мм"]
    tick = {"index": 1, "checked": True}
    with fails(409, "после утверждения"):
        work.set_check(world.db, world.project, plan, chases, tick, world.owner)
    work.plan_action(world.db, world.project, plan, "propose", world.owner)
    work.plan_action(world.db, world.project, plan, "approve", world.client)
    with fails(403):
        work.set_check(world.db, world.project, plan, chases, tick, world.viewer)
    for bad, message in (
        ({"index": 3, "checked": True}, "index: от 0 до 2"),
        ({"index": True, "checked": True}, "index:"),
        ({"index": "1", "checked": True}, "index:"),
        ({"index": 1, "checked": 1}, "checked: true или false"),
    ):
        with fails(422, message):
            work.set_check(world.db, world.project, plan, chases, bad, world.installer)
    work.set_check(world.db, world.project, plan, chases, tick, world.installer)
    work.set_check(world.db, world.project, plan, chases, {"index": 0, "checked": True}, world.code)
    work.set_check(world.db, world.project, plan, chases, tick, world.client)  # twice — once
    assert chases.checked == [0, 1]
    work.set_check(
        world.db, world.project, plan, chases, {"index": 0, "checked": False}, world.owner
    )
    world.db.expire_all()
    assert world.plan().tasks[0].checked == [1]  # kept in the database
    events = world.db.scalars(select(AuditEvent).where(AuditEvent.action == "work_check")).all()
    assert len(events) == 4 and events[-1].payload["checked"] is False
    empty = world.plan().tasks[1]
    empty.result = []
    with fails(422, "у задачи нет критерия"):
        work.set_check(world.db, world.project, world.plan(), empty, tick, world.installer)
    world.plan().state = "closed"
    with fails(409, "закрыт"):
        work.set_check(world.db, world.project, world.plan(), chases, tick, world.installer)


def test_actor_of_principal(world: World) -> None:
    user = world.users["a"]
    assert work.actor_of(acc.Principal(user), "owner").label == "A"
    coded = acc.Principal(None, code_project=uuid.uuid4(), code_label="Иван")
    assert work.actor_of(coded, "viewer").label == "код: Иван"
    assert work.actor_of(acc.Principal(None, code_project=uuid.uuid4()), None).label == (
        "код доступа"
    )
    assert work.actor_of(acc.VISITOR, "visitor") == work.Actor("visitor")


def test_rights_by_role() -> None:
    """docs/work-tasks.md, "Права": a view code and the support only view."""
    assert {r for r in acc.CAN["view"] if acc.can(r, "work_do")} == {
        "owner",
        "designer",
        "installer",
        "superuser",
    }
    assert acc.CAN["work_accept"] == {"owner", "designer", "client", "client_code", "superuser"}
    assert acc.CAN["work_manage"] == {"owner", "designer", "superuser"}
    for role in ("viewer", "support", "visitor"):
        assert not any(acc.can(role, a) for a in ("work_do", "work_accept", "work_manage"))


# --- API ---------------------------------------------------------------------------------

SECRET = "x" * 40


@pytest.fixture
def api(pg: Engine, tmp_path: Path) -> tuple[Auth, LocalObjectStore, dict[str, Any]]:
    """Firm A with a built project kv, its client and installer, a client code and a view code;
    firm B."""
    auth = Auth(AuthConfig(SECRET, "http://t"), make_sessions(pg))
    store = LocalObjectStore(tmp_path / "store")

    def login(sub: str) -> str:
        info = {"sub": sub, "email": f"{sub}@example.com", "email_verified": True, "name": sub}
        return auth._finish_login(info, None, "pytest")[0]

    tokens: dict[str, Any] = {n: login(n) for n in ("a", "b", "client", "inst")}
    with auth.db() as db:
        a, b = acc.session_user(db, tokens["a"]), acc.session_user(db, tokens["b"])
        assert a is not None and b is not None
        firm = acc.register_firm(db, a, "А", "electric")
        acc.register_firm(db, b, "Б", "design")
        pushed = sync.push(db, store, _project(tmp_path), firm)
        project = pushed.project
        tokens["id"] = str(project.id)
        invites = {r: acc.create_invite(db, a, r, project=project) for r in ("client", "installer")}
        tokens["code"] = access_codes.issue_code(db, project, a, "Иван", role="client_code")
        tokens["view"] = access_codes.issue_code(db, project, a, "Пётр")
    with auth.db() as db:
        for name, role in (("client", "client"), ("inst", "installer")):
            user = acc.session_user(db, tokens[name])
            assert user is not None
            acc.accept_invite(db, user, invites[role])
    (tmp_path / "market").mkdir()
    return auth, store, tokens


def _client(
    api: tuple[Auth, LocalObjectStore, dict[str, Any]], tmp_path: Path, who: str
) -> TestClient:
    auth, store, tokens = api
    client = TestClient(create_viewer(tmp_path / "market", auth, store))
    if who in ("code", "view"):
        assert client.post("/api/auth/code", json={"code": tokens[who]}).status_code == 200
    else:
        client.cookies.set(COOKIE, tokens[who])
    return client


def test_api_by_role(api: tuple[Auth, LocalObjectStore, dict[str, Any]], tmp_path: Path) -> None:
    auth, _, tokens = api
    pid = tokens["id"]
    url = f"/api/projects/{pid}/work"
    owner, inst, client, code, view, other = (
        _client(api, tmp_path, w) for w in ("a", "inst", "client", "code", "view", "b")
    )
    assert owner.get(f"/api/projects/{pid}").json()["work"] is True
    empty = owner.get(url).json()
    assert empty["plan"] is None and empty["tasks"] == [] and empty["draft_available"] is True
    assert empty["can"] == {"work_do": True, "work_accept": True, "work_manage": True}
    assert {p["name"] for p in empty["assignees"]} == {"a", "inst"}
    assert inst.get(url).json()["can"] == {
        "work_do": True,
        "work_accept": False,
        "work_manage": False,
    }
    assert client.get(url).json()["assignees"] == []  # only the studio picks people
    assert view.get(url).json()["can"] == {
        "work_do": False,
        "work_accept": False,
        "work_manage": False,
    }
    assert other.get(url).status_code == 404

    for who in (inst, client, code, view):
        assert who.post(f"{url}/plan").status_code == 403
    state = owner.post(f"{url}/plan").json()
    assert owner.post(f"{url}/plan").status_code == 409
    plan, tasks = state["plan"], state["tasks"]
    assert plan["state"] == "draft" and plan["currency"] and plan["model_version"] == 1
    assert plan["totals"]["tasks"] == len(tasks) > 0
    assert all(t["status"] == "proposed" and t["money_editable"] for t in tasks)
    keys = [t["key"] for t in tasks]
    assert keys[0] == "electrical.chases" and "electrical.cable" in keys
    assert client.post(f"{url}/plan/approve").status_code == 409  # still a draft
    assert owner.post(f"{url}/plan/propose").json()["plan"]["state"] == "proposed"
    assert inst.post(f"{url}/plan/approve").status_code == 403
    assert view.post(f"{url}/plan/approve").status_code == 403
    approved = code.post(f"{url}/plan/approve").json()
    assert approved["plan"]["state"] == "approved"
    assert approved["plan"]["approved_by"] == "код: Иван"
    assert {t["status"] for t in approved["tasks"]} == {"todo"}

    cable = next(t for t in approved["tasks"] if t["key"] == "electrical.cable")
    task_url = f"{url}/tasks/{cable['id']}"
    assert cable["waiting"] and cable["photo"] == "required"
    taken = inst.post(f"{task_url}/status", json={"to": "in_progress"})
    assert taken.status_code == 409 and "ждёт" in taken.json()["detail"]
    assert owner.post(f"{task_url}/status", json={"to": "in_progress"}).status_code == 200
    refused = inst.post(f"{task_url}/status", json={"to": "review"})
    assert refused.status_code == 409 and "фото" in refused.json()["detail"]
    bad = inst.post(f"{task_url}/photos", files={"file": ("a.txt", b"x", "text/plain")})
    assert bad.status_code == 415
    assert view.post(f"{task_url}/photos", files={"file": ("a.png", PNG)}).status_code == 403
    heic = inst.post(
        f"{task_url}/photos",
        files={"file": ("IMG_1.HEIC", b"heic", "application/octet-stream")},
        data={"caption": "трасса у окна"},
    )
    assert heic.status_code == 200
    [photo] = next(t for t in heic.json()["tasks"] if t["id"] == cable["id"])["photos"]
    assert (photo["content_type"], photo["caption"], photo["author"]) == (
        "image/heic",
        "трасса у окна",
        "inst",
    )
    assert view.get(photo["url"]).content == b"heic"  # view codes see photos
    assert other.get(photo["url"]).status_code == 404
    assert inst.post(f"{task_url}/status", json={"to": "review"}).status_code == 200
    back = client.post(f"{task_url}/status", json={"to": "returned"})
    assert back.status_code == 422 and "комментарием" in back.json()["detail"]
    assert inst.post(f"{task_url}/status", json={"to": "accepted"}).status_code == 403
    returned = client.post(f"{task_url}/status", json={"to": "returned", "comment": "переделать"})
    task = next(t for t in returned.json()["tasks"] if t["id"] == cable["id"])
    assert task["status"] == "returned" and task["comments"][-1]["kind"] == "return"
    assert inst.post(f"{task_url}/status", json={"to": "review"}).status_code == 200
    assert client.post(f"{task_url}/status", json={"to": "accepted"}).status_code == 200

    line = cable["lines"][0]
    line_url = f"{task_url}/lines/{line['id']}"
    assert inst.patch(line_url, json={"price": 1}).status_code == 403
    assert owner.patch(line_url, json={"price": 1}).status_code == 409  # agreed with the client
    assert inst.patch(line_url, json={"fact_qty": 1}).status_code == 409  # accepted: frozen
    chases = approved["tasks"][0]
    fact = inst.patch(
        f"{url}/tasks/{chases['id']}/lines/{chases['lines'][0]['id']}", json={"fact_qty": 2}
    )
    assert fact.json()["tasks"][0]["lines"][0]["fact_qty"] == 2

    assert view.post(f"{task_url}/comments", json={"text": "?"}).status_code == 403
    said = code.post(f"{task_url}/comments", json={"text": "спасибо"}).json()
    task = next(t for t in said["tasks"] if t["id"] == cable["id"])
    assert task["comments"][-1]["author"] == "код: Иван"

    pay = {"amount": 1000, "paid_on": "2026-11-11", "note": "аванс"}
    assert client.post(f"{task_url}/payments", json=pay).status_code == 403
    paid = owner.post(f"{task_url}/payments", json=pay).json()
    assert paid["plan"]["totals"]["paid"] == 1000.0
    payment = next(t for t in paid["tasks"] if t["id"] == cable["id"])["payments"][0]
    assert payment["paid_on"] == "2026-11-11" and payment["amount"] == 1000.0
    assert inst.delete(f"{url}/payments/{payment['id']}").status_code == 403
    assert owner.delete(f"{url}/payments/{payment['id']}").json()["plan"]["totals"]["paid"] == 0

    added = owner.post(f"{url}/tasks", json={"title": "Доп. розетка", "domain": "electrical"})
    extra = added.json()["tasks"][-1]
    assert (extra["extra"], extra["status"], extra["money_editable"]) == (True, "proposed", True)
    extra_url = f"{url}/tasks/{extra['id']}"
    with_line = owner.post(
        f"{extra_url}/lines", json={"title": "Розетка", "kind": "work", "unit": "шт", "qty": 1}
    )
    assert with_line.json()["tasks"][-1]["unpriced"] == 1
    assert owner.patch(extra_url, json={"title": "Две розетки"}).status_code == 200
    assert inst.patch(extra_url, json={"title": "x"}).status_code == 403
    assert client.post(f"{extra_url}/status", json={"to": "todo"}).status_code == 200
    assert owner.delete(extra_url).json()["plan"]["totals"]["tasks"] == len(tasks)
    assert owner.delete(task_url).status_code == 409  # accepted, with photos
    assert owner.get(f"{url}/tasks/{uuid.uuid4()}").status_code == 405
    assert owner.patch(f"{url}/tasks/nope", json={}).status_code == 404

    assert client.delete(f"/api/projects/{pid}/work/photos/{photo['id']}").status_code == 403
    assert owner.delete(f"/api/projects/{pid}/work/photos/{photo['id']}").status_code == 200
    assert owner.get(photo["url"]).status_code == 404
    assert owner.post(f"{url}/plan/close").status_code == 409

    with auth.db() as db:
        project = db.get(Project, uuid.UUID(pid))
        assert project is not None
        actions = set(
            db.scalars(select(AuditEvent.action).where(AuditEvent.project_id == project.id))
        )
    assert {"work_plan_create", "work_plan_approve", "work_status", "work_photo"} <= actions


def test_api_without_a_draft(
    api: tuple[Auth, LocalObjectStore, dict[str, Any]], tmp_path: Path
) -> None:
    """No build file: nothing to make a plan from; no plan: plan actions say so."""
    _, store, tokens = api
    pid = tokens["id"]
    owner = _client(api, tmp_path, "a")
    assert owner.post(f"/api/projects/{pid}/work/plan/propose").status_code == 404
    store.delete_prefix(f"projects/{pid}/builds")
    state = owner.get(f"/api/projects/{pid}/work").json()
    assert state["draft_available"] is False
    refused = owner.post(f"/api/projects/{pid}/work/plan")
    assert refused.status_code == 409 and "пересоберите" in refused.json()["detail"]


def test_api_ticks_merge_and_acting_for_the_client(
    api: tuple[Auth, LocalObjectStore, dict[str, Any]], tmp_path: Path
) -> None:
    """The routes of 2026-11-12: merge and move lines (studio, before approval), approval for the
    client with on_behalf, acceptance ticks (installer and client)."""
    pid = api[2]["id"]
    url = f"/api/projects/{pid}/work"
    owner, inst, client, view = (_client(api, tmp_path, w) for w in ("a", "inst", "client", "view"))
    tasks = owner.post(f"{url}/plan").json()["tasks"]
    first, second, third = tasks[0], tasks[1], tasks[2]
    move = {"line_ids": [first["lines"][0]["id"]], "to_task": second["id"]}
    assert inst.post(f"{url}/tasks/{first['id']}/lines/move", json=move).status_code == 403
    moved = owner.post(f"{url}/tasks/{first['id']}/lines/move", json=move).json()["tasks"]
    assert moved[1]["lines"][-1]["id"] == first["lines"][0]["id"]
    assert len(moved[0]["lines"]) == len(first["lines"]) - 1
    total = moved[1]["total"] + moved[2]["total"]
    bad = owner.post(f"{url}/tasks/{third['id']}/merge", json={"into": third["id"]})
    assert bad.status_code == 422 and bad.json()["detail"].startswith("into:")
    assert (
        client.post(f"{url}/tasks/{third['id']}/merge", json={"into": second["id"]}).status_code
        == 403
    )
    merged = owner.post(f"{url}/tasks/{third['id']}/merge", json={"into": second["id"]}).json()
    assert len(merged["tasks"]) == len(tasks) - 1
    assert merged["tasks"][1]["total"] == total
    assert [t["position"] for t in merged["tasks"]] == list(range(len(tasks) - 1))
    gone = {third["id"], third["key"]}
    assert all(not gone & set(t["after"]) for t in merged["tasks"])  # links lead to the target

    assert owner.post(f"{url}/plan/propose").status_code == 200
    refused = owner.post(f"{url}/plan/approve")
    assert refused.status_code == 422 and refused.json()["detail"].startswith("on_behalf:")
    sent = client.post(f"{url}/plan/approve", json={"on_behalf": "phone"})
    assert sent.status_code == 422 and "заказчик действует сам" in sent.json()["detail"]
    approved = owner.post(f"{url}/plan/approve", json={"on_behalf": "phone", "note": "звонок"})
    plan = approved.json()["plan"]
    assert plan["approved_on_behalf"] == {"channel": "phone", "note": "звонок"}
    assert plan["approved_by"] == "a"
    assert (
        owner.post(f"{url}/tasks/{first['id']}/merge", json={"into": second["id"]}).status_code
        == 409
    )

    task = approved.json()["tasks"][0]
    checks = f"{url}/tasks/{task['id']}/checks"
    assert task["checked"] == [] and task["result"]
    assert view.patch(checks, json={"index": 0, "checked": True}).status_code == 403
    assert inst.patch(checks, json={"index": 99, "checked": True}).status_code == 422
    ticked = inst.patch(checks, json={"index": 0, "checked": True}).json()["tasks"][0]
    assert ticked["checked"] == [0]
    assert client.get(url).json()["tasks"][0]["checked"] == [0]  # kept

    status = f"{url}/tasks/{task['id']}/status"
    assert owner.post(status, json={"to": "in_progress"}).status_code == 200
    assert inst.post(status, json={"to": "review"}).status_code == 200
    assert owner.post(status, json={"to": "accepted"}).status_code == 422
    done = owner.post(status, json={"to": "accepted", "on_behalf": "telegram"}).json()
    feed = done["tasks"][0]["comments"]
    assert feed[-1]["on_behalf"] == {"channel": "telegram", "note": ""}
    assert feed[0]["on_behalf"] is None
    assert approved.json()["plan"] and client.get(url).json()["plan"]["approved_by"] == "a"
