"""Product feedback (service/db/feedback.py, service/api/feedback.py; decision 2026-11-12): a
user or an access-code session leaves a bug, an idea or other with up to three photos, at most
ten an hour; the platform superuser lists, filters and marks them in the admin, and every mark
lands in the audit log. Only with projects in the database."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from floorplan_engine.service.api.auth import COOKIE, Auth, AuthConfig
from floorplan_engine.service.api.feedback import notice
from floorplan_engine.service.api.viewer import create_viewer
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db import access_codes
from floorplan_engine.service.db import feedback as fb
from floorplan_engine.service.db.models import AuditEvent, Feedback
from floorplan_engine.service.db.session import make_sessions
from floorplan_engine.service.objects import LocalObjectStore
from tests.service.conftest import PNG

SECRET = "x" * 40
BOSS = "boss@example.com"
URL = "/api/feedback"


class Mailbox:
    """A mailer that keeps the letters; fail — it raises instead."""

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.fail = fail

    def send(self, to: str, subject: str, text: str) -> None:
        if self.fail:
            raise OSError("smtp down")
        self.sent.append((to, subject, text))


class Env:
    """Firm A with project kv and a client code to it, firm B with its own project, the
    superuser; the viewer on the database."""

    def __init__(self, pg: Engine, tmp_path: Path, mailer: Mailbox | None = None) -> None:
        config = AuthConfig(
            SECRET, "http://t", superusers=(BOSS,), visitor=True, feedback_to="owner@shtroba.app"
        )
        self.auth = Auth(config, make_sessions(pg), mailer=mailer)
        self.store = LocalObjectStore(tmp_path / "store")
        self.tmp = tmp_path
        self.tokens = {n: self._login(n) for n in ("a", "b", "boss")}
        with self.auth.db() as db:
            a = acc.session_user(db, self.tokens["a"])
            b = acc.session_user(db, self.tokens["b"])
            assert a is not None and b is not None
            acc.register_firm(db, a, "Искра", "electric")
            acc.register_firm(db, b, "Другая", "design")
            kv = acc.create_project_for(db, a, "Квартира на Вавилова", "kv")
            other = acc.create_project_for(db, b, "Чужая", "other")
            self.kv, self.other = str(kv.id), str(other.id)
            self.code = access_codes.issue_code(db, kv, a, "Иван", role="client_code")
        (tmp_path / "market").mkdir()

    def _login(self, sub: str) -> str:
        email = BOSS if sub == "boss" else f"{sub}@example.com"
        info = {"sub": sub, "email": email, "email_verified": True, "name": sub.title()}
        return self.auth._finish_login(info, None, "pytest")[0]

    def client(self, who: str | None) -> TestClient:
        client = TestClient(create_viewer(self.tmp / "market", self.auth, self.store))
        if who == "code":
            assert client.post("/api/auth/code", json={"code": self.code}).status_code == 200
        elif who == "visitor":
            assert client.post("/api/auth/visitor").status_code == 200
        elif who is not None:
            client.cookies.set(COOKIE, self.tokens[who])
        return client


@pytest.fixture
def env(pg: Engine, tmp_path: Path) -> Env:
    return Env(pg, tmp_path)


def _send(
    client: TestClient,
    text: str = "Лист проводки не открывается",
    kind: str = "bug",
    context: Any = None,
    project: str | None = None,
    photos: list[tuple[str, bytes, str]] | None = None,
) -> Any:
    data = {"kind": kind, "text": text}
    if context is not None:
        data["context"] = context if isinstance(context, str) else json.dumps(context)
    if project is not None:
        data["project"] = project
    files = [("photos", p) for p in photos or []]
    return client.post(URL, data=data, files=files or None)


def test_capability_only_with_the_database(env: Env, pg: Engine, tmp_path: Path) -> None:
    assert env.client("a").get("/api/auth/me").json()["feedback"] is True
    # The folder viewer, with or without login: no feedback, no route
    folder_auth = Auth(AuthConfig(SECRET, "http://t"), make_sessions(pg))
    folder = TestClient(create_viewer(tmp_path / "market", folder_auth))
    folder.cookies.set(COOKIE, env.tokens["a"])
    assert folder.get("/api/auth/me").json()["feedback"] is False
    assert _send(folder).status_code in (404, 405)
    open_viewer = TestClient(create_viewer(tmp_path / "market"))
    assert "feedback" not in open_viewer.get("/api/auth/me").json()
    assert _send(open_viewer).status_code in (404, 405)


def test_create_with_photos_and_context(env: Env) -> None:
    client = env.client("a")
    context = {
        "sheet": "04-wiring",
        "path": "/p/kv",
        "version": "0.5.1",
        "viewport": {"width": 1440, "height": 900, "junk": [1]},
        "long": "я" * 2000,
        "nested": [1, 2],
    }
    photos = [("a.png", PNG, "image/png"), ("b.jpg", b"\xff\xd8\xff" + b"0" * 10, "")]
    r = _send(client, "  Не тянется трасса  ", context=context, project=env.kv, photos=photos)
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    with env.auth.db() as db:
        row = fb.get(db, fid)
        assert (row.kind, row.text, row.status, row.author_label) == (
            "bug",
            "Не тянется трасса",
            "new",
            "A",
        )
        assert str(row.project_id) == env.kv and row.user_id is not None
        assert row.access_code_id is None
        assert row.context["viewport"] == {"width": 1440, "height": 900}
        assert len(row.context["long"]) == fb.VALUE_MAX and "nested" not in row.context
        assert row.context["user_agent"] == "testclient"  # from the request header
        assert [p["content_type"] for p in row.photos] == ["image/png", "image/jpeg"]
        assert all(p["key"].startswith(f"feedback/{fid}/") for p in row.photos)
        assert env.store.get(row.photos[0]["key"]) == PNG


def test_validation(env: Env) -> None:
    client = env.client("a")
    assert _send(client, kind="praise").status_code == 422
    assert "text:" in _send(client, "   ").json()["detail"]
    assert _send(client, "я" * (fb.TEXT_MAX + 1)).status_code == 422
    assert _send(client, "я" * fb.TEXT_MAX).status_code == 200
    assert "context:" in _send(client, context="{not json").json()["detail"]
    assert _send(client, context="[1, 2]").status_code == 422
    four = [("p.png", PNG, "image/png")] * 4
    assert "photos:" in _send(client, photos=four).json()["detail"]
    gif = _send(client, photos=[("x.gif", b"GIF89a", "image/gif")])
    assert gif.status_code == 415 and "photos[0]" in gif.json()["detail"]
    assert _send(client, photos=[("e.png", b"", "image/png")]).status_code == 422
    big = b"0" * (fb.PHOTO_MAX + 1)
    assert _send(client, photos=[("big.png", big, "image/png")]).status_code == 413
    with env.auth.db() as db:  # nothing of the refused ones is stored
        assert len(db.scalars(select(Feedback)).all()) == 1
    assert not (env.tmp / "store" / "feedback").exists()


def test_who_may_leave_feedback(env: Env) -> None:
    assert _send(env.client(None)).status_code == 401
    assert _send(env.client("visitor")).status_code == 403
    code = env.client("code")
    r = _send(code, "Код работает", kind="idea", project=env.kv)
    assert r.status_code == 200
    with env.auth.db() as db:
        row = fb.get(db, r.json()["id"])
        assert row.user_id is None and row.access_code_id is not None
        assert row.author_label == "код: Иван"
    # A project the caller does not see is not revealed
    assert _send(code, project=env.other).status_code == 404
    assert _send(env.client("a"), project=env.other).status_code == 404
    assert _send(env.client("a"), project="no-such").status_code == 404
    assert _send(env.client("b"), project=env.other).status_code == 200
    assert _send(env.client("boss"), project=env.other).status_code == 200  # sees everything


def test_rate_limit(env: Env) -> None:
    a = env.client("a")
    for i in range(fb.RATE_LIMIT):
        assert _send(a, f"отзыв {i}").status_code == 200
    r = _send(a, "ещё один")
    assert r.status_code == 429 and "в час" in r.json()["detail"]
    # Each author has their own limit
    assert _send(env.client("b")).status_code == 200
    code = env.client("code")
    for _ in range(fb.RATE_LIMIT):
        assert _send(code).status_code == 200
    assert _send(code).status_code == 429


def _seed(env: Env) -> dict[str, str]:
    a, code, b = env.client("a"), env.client("code"), env.client("b")
    photo = [("a.png", PNG, "image/png")]
    return {
        "bug": _send(a, "Падает печать", project=env.kv, photos=photo).json()["id"],
        "idea": _send(code, "Тёмная тема", kind="idea").json()["id"],
        "other": _send(b, "Спасибо за сервис", kind="other").json()["id"],
    }


def test_admin_list_and_filters(env: Env) -> None:
    ids = _seed(env)
    assert env.client("a").get("/api/admin/feedback").status_code == 403
    boss = env.client("boss")
    page = boss.get("/api/admin/feedback").json()
    assert page["total"] == 3 and page["counts"] == {"new": 3, "seen": 0, "done": 0}
    items = {i["id"]: i for i in page["items"]}
    assert [i["id"] for i in page["items"]] == [ids["other"], ids["idea"], ids["bug"]]
    bug = items[ids["bug"]]
    assert bug["author"]["email"] == "a@example.com" and bug["author"]["name"] == "A"
    assert bug["project"] == {"key": env.kv, "name": "Квартира на Вавилова"}
    assert bug["status"] == "new" and bug["admin_note"] is None
    assert bug["context"]["user_agent"] == "testclient" and bug["created_at"]
    assert len(bug["photos"]) == 1 and bug["photos"][0].startswith(
        f"{URL.replace('/api', '/api/admin')}/"
    )
    assert items[ids["idea"]]["author"] == {"code_label": "Иван"}
    assert items[ids["idea"]]["project"] is None

    def found(**params: Any) -> list[str]:
        return [i["id"] for i in boss.get("/api/admin/feedback", params=params).json()["items"]]

    assert found(kind="idea") == [ids["idea"]]
    assert found(q="печать") == [ids["bug"]]
    assert found(q="b@example") == [ids["other"]]  # by the author's e-mail
    assert found(q="Иван") == [ids["idea"]]  # by the code's label
    assert found(limit=1, offset=1) == [ids["idea"]]
    assert boss.get("/api/admin/feedback", params={"limit": 1}).json()["total"] == 3
    assert boss.get("/api/admin/feedback", params={"status": "lost"}).status_code == 422
    assert boss.get("/api/admin/feedback", params={"kind": "lost"}).status_code == 422
    assert boss.get("/api/admin/summary").json()["feedback_new"] == 3

    photo = boss.get(bug["photos"][0])
    assert photo.status_code == 200 and photo.content == PNG
    assert photo.headers["content-type"] == "image/png"
    assert env.client("a").get(bug["photos"][0]).status_code == 403
    assert boss.get(f"/api/admin/feedback/{ids['bug']}/photos/nope").status_code == 404


def test_admin_patch_and_audit(env: Env) -> None:
    ids = _seed(env)
    boss = env.client("boss")
    url = f"/api/admin/feedback/{ids['bug']}"
    r = boss.patch(url, json={"status": "seen", "admin_note": "  воспроизвёл  "})
    assert r.status_code == 200
    assert (r.json()["status"], r.json()["admin_note"]) == ("seen", "воспроизвёл")
    assert r.json()["project"]["key"] == env.kv
    # Only the note: the status stays; an empty note clears it
    r = boss.patch(url, json={"admin_note": ""})
    assert (r.json()["status"], r.json()["admin_note"]) == ("seen", None)
    assert boss.patch(url, json={"status": "done"}).json()["admin_note"] is None
    assert boss.patch(url, json={"status": "closed"}).status_code == 422
    assert boss.patch(url, json={"status": 1}).status_code == 422
    assert boss.patch(url, json={"admin_note": ["x"]}).status_code == 422
    long = boss.patch(url, json={"admin_note": "я" * (fb.NOTE_MAX + 1)})
    assert long.status_code == 422 and "admin_note" in long.json()["detail"]
    assert boss.patch("/api/admin/feedback/not-an-id", json={}).status_code == 404
    assert env.client("a").patch(url, json={"status": "new"}).status_code == 403
    counts = boss.get("/api/admin/feedback").json()["counts"]
    assert counts == {"new": 2, "seen": 0, "done": 1}
    with env.auth.db() as db:
        events = db.scalars(
            select(AuditEvent)
            .where(AuditEvent.action == "feedback_update")
            .order_by(AuditEvent.created_at)
        ).all()
        assert [e.payload.get("status") for e in events] == [
            ["new", "seen"],
            None,
            ["seen", "done"],
        ]
        assert all(e.payload["feedback"] == ids["bug"] and e.user_id for e in events)
    shown = boss.get("/api/admin/events").json()
    assert any(e["action"] == "feedback_update" for e in shown)


def test_notice_by_mail(pg: Engine, tmp_path: Path) -> None:
    box = Mailbox()
    env = Env(pg, tmp_path, box)
    assert _send(env.client("a"), "я" * 400, project=env.kv).status_code == 200
    ((to, subject, body),) = box.sent
    assert to == "owner@shtroba.app" and "отзыв" in subject
    assert "(ошибка) от A · проект «Квартира на Вавилова»" in body
    assert "я" * 300 + "…" in body and "http://t/admin/" in body


def test_failed_notice_keeps_the_item(pg: Engine, tmp_path: Path) -> None:
    env = Env(pg, tmp_path, Mailbox(fail=True))
    assert _send(env.client("a")).status_code == 200
    with env.auth.db() as db:
        assert len(db.scalars(select(Feedback)).all()) == 1


def test_no_notice_without_address(pg: Engine, tmp_path: Path) -> None:
    box = Mailbox()
    env = Env(pg, tmp_path, box)
    env.auth = Auth(
        AuthConfig(SECRET, "http://t"), env.auth.sessions, mailer=box
    )  # no FEEDBACK_NOTIFY_EMAIL
    assert _send(env.client("a")).status_code == 200
    assert box.sent == []


def test_clean_context_and_notice() -> None:
    assert fb.clean_context(None, "UA") == {"user_agent": "UA"}
    assert fb.clean_context({"user_agent": "page"}, "UA") == {"user_agent": "page"}
    many = {f"k{i}": i for i in range(50)}
    assert len(fb.clean_context(many)) == fb.CONTEXT_KEYS
    assert fb.clean_context({"": 1, "x" * 100: True})["x" * fb.KEY_MAX] is True
    with pytest.raises(fb.FeedbackError):
        fb.clean_context("text")
    assert "без имени" in notice("other", "", None, "t", "u")


def test_config_reads_the_notice_address() -> None:
    env = {"SHTROBA_AUTH": "on", "SHTROBA_SECRET": SECRET, "SHTROBA_PUBLIC_URL": "http://t"}
    config = AuthConfig.from_env({**env, "FEEDBACK_NOTIFY_EMAIL": " me@x.io "})
    assert config is not None and config.feedback_to == "me@x.io"
    plain = AuthConfig.from_env(env)
    assert plain is not None and plain.feedback_to is None
