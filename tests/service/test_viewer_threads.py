"""Question threads in the database viewer (service/api/viewer_threads.py): who sees and writes
which threads, the studio accepting a message (202, the check hook) and closing a thread, state
errors 409, a form answer resolving the thread, the installer answering their own questions."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from floorplan_engine.service import project_store as ps
from floorplan_engine.service import sync
from floorplan_engine.service.api.auth import COOKIE, Auth, AuthConfig
from floorplan_engine.service.api.viewer import create_viewer
from floorplan_engine.service.api.viewer_threads import waiting_for
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db import access_codes
from floorplan_engine.service.db import repositories as repo
from floorplan_engine.service.db import threads as th
from floorplan_engine.service.db.models import Question, QuestionThread, ThreadMessage
from floorplan_engine.service.db.session import make_sessions
from floorplan_engine.service.objects import LocalObjectStore
from tests.electrical.test_variants import _project

SECRET = "x" * 40
INTAKE = (
    "questions:\n"
    '  - { id: q1, stage: plan, audience: client, text: "Есть обмер?", answer: text,'
    " severity: major }\n"
    '  - { id: q2, stage: plan, text: "Толщина стены?", answer: value,'
    " target: rooms.r.walls.w2.thickness }\n"
    '  - { id: q3, stage: plan, audience: installer, text: "Где стояк?", answer: text,'
    " severity: minor }\n"
    '  - { id: q4, stage: plan, audience: client, text: "Плита?", answer: choice,'
    " options: [gas, electric], severity: minor }\n"
)


class Setup:
    """Firm A with project kv (questions q1, q4 (choice) — client, q2 — studio, q3 — installer),
    its client and installer by invite, a client code, firm B; checked — the calls of the check
    hook."""

    def __init__(self, auth: Auth, tmp_path: Path) -> None:
        self.auth = auth
        store = LocalObjectStore(tmp_path / "store")
        self.tokens = {n: _login(auth, n) for n in ("a", "b", "client", "installer")}
        with auth.db() as db:
            a, b = acc.session_user(db, self.tokens["a"]), acc.session_user(db, self.tokens["b"])
            assert a is not None and b is not None
            firm = acc.register_firm(db, a, "А", "electric")
            acc.register_firm(db, b, "Б", "design")
            project = sync.push(db, store, _project(tmp_path), firm).project
            self.pid = str(project.id)
            latest = repo.latest_model(db, project.id)
            assert latest is not None
            files = {**repo.model_files(latest), "intake.yaml": INTAKE}
            ps.build(db, store, project, repo.add_model_version(db, project.id, files, "user"))
            invites = {
                r: acc.create_invite(db, a, r, project=project) for r in ("client", "installer")
            }
            self.code = access_codes.issue_code(db, project, None, "Иван", role="client_code")
        for role, token in invites.items():
            with auth.db() as db:
                user = acc.session_user(db, self.tokens[role])
                assert user is not None
                acc.accept_invite(db, user, token)
        (tmp_path / "market").mkdir()
        self.checked: list[tuple[uuid.UUID, uuid.UUID]] = []
        app = create_viewer(
            tmp_path / "market", auth, store, lambda p, t: self.checked.append((p, t))
        )
        self.client = TestClient(app)

    def act(self, who: str) -> TestClient:
        self.client.cookies.clear()
        if who == "code":
            self.client.post("/api/auth/code", json={"code": self.code})
        else:
            self.client.cookies.set(COOKIE, self.tokens[who])
        return self.client

    def url(self, tail: str = "") -> str:
        return f"/api/projects/{self.pid}/threads{tail}"

    def threads(self, who: str) -> dict[str, dict[str, Any]]:
        """The threads `who` sees, by question id."""
        listed = self.act(who).get(self.url())
        assert listed.status_code == 200, listed.text
        return {t["question"]["id"]: t for t in listed.json()["threads"]}


def _login(auth: Auth, sub: str) -> str:
    info = {"sub": sub, "email": f"{sub}@example.com", "email_verified": True, "name": sub}
    return auth._finish_login(info, None, "pytest")[0]


@pytest.fixture
def world(pg: Engine, tmp_path: Path) -> Setup:
    return Setup(Auth(AuthConfig(SECRET, "http://t"), make_sessions(pg)), tmp_path)


def test_each_side_sees_its_threads(world: Setup) -> None:
    studio = world.threads("a")
    assert {"q1", "q2", "q3"} <= set(studio)
    assert {t["state"] for t in studio.values()} == {"open"}
    assert studio["q1"]["question"]["audience"] == "client"
    assert studio["q2"]["question"]["kind"] == "value" and studio["q2"]["chain"] == 1
    # The client and a client code: the client questions and the panel settings; the installer
    # only theirs
    for who in ("client", "code"):
        seen = world.threads(who)
        assert "q1" in seen and "q2" not in seen and "q3" not in seen
        assert all(q in ("q1", "q4") or q.startswith("panel_") for q in seen)
    assert set(world.threads("installer")) == {"q3"}
    # Waiting: an open client question waits for the client, a studio one for the studio
    assert studio["q1"]["waiting_for"] == "client" and not studio["q1"]["waiting_for_you"]
    assert studio["q2"]["waiting_for_you"] is True
    assert world.threads("client")["q1"]["waiting_for_you"] is True
    # Another thread is 404 to a side that does not see it; another firm does not see the project
    q2 = studio["q2"]["id"]
    assert world.act("client").get(world.url(f"/{q2}")).status_code == 404
    assert world.act("installer").get(world.url(f"/{q2}")).status_code == 404
    assert world.act("a").get(world.url("/nope")).status_code == 404
    assert world.act("b").get(world.url()).status_code == 404


def test_messages_and_who_waits(world: Setup) -> None:
    q1 = world.threads("a")["q1"]["id"]
    url = world.url(f"/{q1}/messages")
    assert world.act("client").post(url, json={"text": "  "}).status_code == 422
    assert world.act("client").post(url, json={"text": 5}).status_code == 422
    said = world.act("client").post(url, json={"text": " Обмер есть, пришлю "})
    assert said.status_code == 201
    body = said.json()
    [m] = body["messages"]
    assert (m["text"], m["author"], m["role"], m["mine"]) == (
        "Обмер есть, пришлю",
        "user",
        "client",
        True,
    )
    assert body["waiting_for"] == "studio"
    studio = world.threads("a")["q1"]
    assert studio["waiting_for_you"] is True and studio["messages"][0]["mine"] is False
    assert world.act("a").get(world.url()).json()["waiting_for_you"] >= 1
    # The studio asks back: now the client is waited for
    world.act("a").post(url, json={"text": "Когда?"})
    assert world.threads("client")["q1"]["waiting_for_you"] is True
    # A client code writes too, signed with its label
    coded = world.act("code").post(url, json={"text": "Завтра"}).json()
    assert coded["messages"][-1]["author_label"] == "код: Иван"
    assert coded["messages"][-1]["role"] == "client_code" and coded["messages"][-1]["mine"]
    # The client writes only in their threads; the installer in theirs
    q3 = world.threads("a")["q3"]["id"]
    assert (
        world.act("client").post(world.url(f"/{q3}/messages"), json={"text": "x"}).status_code
        == 404
    )
    done = world.act("installer").post(world.url(f"/{q3}/messages"), json={"text": "В нише"})
    assert done.status_code == 201 and done.json()["messages"][0]["role"] == "installer"
    full = world.act("a").get(world.url(f"/{q1}")).json()
    assert full["messages_count"] == 3 and len(full["messages"]) == 3 and full["previous"] == []


def test_accept_needs_the_studio_and_starts_the_check(world: Setup) -> None:
    q1 = world.threads("a")["q1"]["id"]
    said = world.act("client").post(world.url(f"/{q1}/messages"), json={"text": "Есть"}).json()
    mid = said["messages"][0]["id"]
    accept = world.url(f"/{q1}/accept")
    assert world.act("client").post(accept, json={"message_id": mid}).status_code == 403
    assert world.act("installer").post(accept, json={"message_id": mid}).status_code == 403
    assert world.act("a").post(accept, json={"message_id": "x"}).status_code == 422
    assert world.act("a").post(accept, json={"message_id": str(uuid.uuid4())}).status_code == 404
    taken = world.act("a").post(accept, json={"message_id": mid})
    assert taken.status_code == 202, taken.text
    body = taken.json()
    assert body["state"] == "checking" and body["accepted_message_id"] == mid
    assert body["messages"][0]["accepted"] is True and body["waiting_for"] is None
    assert world.checked == [(uuid.UUID(world.pid), uuid.UUID(q1))]
    # The default hook does nothing: the thread stays checking; accepting again is a state error
    again = world.act("a").post(accept, json={"message_id": mid})
    assert again.status_code == 409 and "checking" in again.json()["detail"]
    assert world.act("a").post(world.url(f"/{q1}/close"), json={}).status_code == 409
    busy = world.act("client").post(world.url(f"/{q1}/messages"), json={"text": "ещё"})
    assert busy.status_code == 409 and "на проверке" in busy.json()["detail"]
    # A message of another thread; a question answered by the form
    threads = world.threads("a")
    q3 = threads["q3"]["id"]
    other = world.act("a").post(world.url(f"/{q3}/accept"), json={"message_id": mid})
    assert other.status_code == 409 and "этого треда" in other.json()["detail"]
    q2 = threads["q2"]["id"]
    note = world.act("a").post(world.url(f"/{q2}/messages"), json={"text": "120?"}).json()
    form = world.act("a").post(
        world.url(f"/{q2}/accept"), json={"message_id": note["messages"][0]["id"]}
    )
    assert form.status_code == 409 and "формой" in form.json()["detail"]


def test_close_by_the_studio(world: Setup) -> None:
    q3 = world.threads("a")["q3"]["id"]
    close = world.url(f"/{q3}/close")
    assert world.act("installer").post(close, json={}).status_code == 403
    assert world.act("a").post(close, json={"comment": 1}).status_code == 422
    closed = world.act("a").post(close, json={"comment": "Решено правкой plumbing.yaml"})
    assert closed.status_code == 200
    body = closed.json()
    assert body["state"] == "closed" and body["closed_at"] is not None
    assert body["messages"][-1]["text"] == "Решено правкой plumbing.yaml"
    assert world.act("a").post(close).status_code == 409  # no body: no comment
    # A thread that is over is read-only
    late = world.act("installer").post(world.url(f"/{q3}/messages"), json={"text": "ок"})
    assert late.status_code == 409 and "закрыт" in late.json()["detail"]


def test_form_answer_resolves_the_thread(world: Setup) -> None:
    """POST /answers stays: a value saved by the form resolves the question's thread (ingest)."""
    saved = world.act("a").post(
        f"/api/projects/{world.pid}/answers", json={"id": "q2", "answer": 150}
    )
    assert saved.status_code == 200, saved.text
    assert world.threads("a")["q2"]["state"] == "resolved"


def test_the_installer_answers_their_questions(world: Setup) -> None:
    """Decision 2026-11-28: the installer has `answer`, but only for the installer questions; the
    project card shows them only those."""
    card = world.act("installer").get(f"/api/projects/{world.pid}").json()
    assert card["can"]["answer"] is True and card["can"]["review"] is False
    assert [q["id"] for q in card["report"]["questions"]] == ["q3"]
    url = f"/api/projects/{world.pid}/answers"
    refused = world.act("installer").post(url, json={"id": "q2", "answer": 150})
    assert refused.status_code == 422
    assert refused.json()["detail"]["issues"][0]["message"] == "этот вопрос задан не монтажнику"
    ok = world.act("installer").post(url, json={"id": "q3", "answer": {"text": "В нише"}})
    assert ok.status_code == 200, ok.text
    [m] = world.threads("installer")["q3"]["messages"]
    assert (m["text"], m["role"]) == ("В нише", "installer")


def test_chain_of_a_follow_up(world: Setup) -> None:
    """An accepted answer that did not close the question: the new thread shows the old one."""
    q1 = world.threads("a")["q1"]["id"]
    mid = (
        world.act("client").post(world.url(f"/{q1}/messages"), json={"text": "как на кухне"}).json()
    )
    world.act("a").post(world.url(f"/{q1}/accept"), json={"message_id": mid["messages"][0]["id"]})
    with world.auth.db() as db:
        old = db.get(QuestionThread, uuid.UUID(q1))
        assert old is not None
        new = th.follow_up(db, old, th.FollowUp("Какая ширина кухни, мм?"))
        new_id = str(new.id)
    full = world.act("client").get(world.url(f"/{new_id}")).json()
    assert full["chain"] == 2 and full["previous_thread_id"] == q1
    assert full["question"]["text"] == "Какая ширина кухни, мм?"
    assert full["messages"][0]["meta"]["quote"] == mid["messages"][0]["id"]
    assert full["waiting_for"] == "client"  # the quote opens it: the client answers
    [previous] = full["previous"]
    assert previous["id"] == q1 and previous["state"] == "superseded"
    assert previous["question"]["in_intake"] is False


def test_waiting_for_without_a_role() -> None:
    """A message whose author's role is not known (an answer from a file) is the addressee's;
    a system note after a failed check waits for the studio."""
    q = Question(audience="client", stage="plan")
    t = QuestionThread(state="open")
    unknown = ThreadMessage(author="user", role="", meta={})
    assert waiting_for(t, q, [unknown]) == "studio"
    assert waiting_for(t, q, [ThreadMessage(author="system", role="", meta={})]) == "studio"
    assert waiting_for(t, q, [ThreadMessage(author="user", role="owner", meta={})]) == "client"
    assert waiting_for(QuestionThread(state="resolved"), q, []) is None
    assert waiting_for(t, Question(audience="studio"), []) == "studio"
    assert waiting_for(t, None, []) == "studio"


def test_a_client_choice_is_accepted_not_a_studio_form(world: Setup) -> None:
    """A client question only clarifies whatever its kind: its answer is a message the studio
    accepts and the AI checks; a studio value is answered by the form (409 on accept)."""
    q4 = world.threads("a")["q4"]["id"]
    said = world.act("client").post(world.url(f"/{q4}/messages"), json={"text": "Газовая"})
    assert said.status_code == 201, said.text
    mid = said.json()["messages"][-1]["id"]
    taken = world.act("a").post(world.url(f"/{q4}/accept"), json={"message_id": mid})
    assert taken.status_code == 202 and taken.json()["state"] == "checking"
