"""Platform admin (service/db/admin.py, service/api/admin.py): only an active superuser gets in;
changes keep the access rules (one workspace, one client project, a studio keeps an owner) and
land in the audit log."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from floorplan_engine.service import sync
from floorplan_engine.service.api.auth import COOKIE, Auth, AuthConfig
from floorplan_engine.service.api.viewer import create_viewer
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db.models import StudioProfile
from floorplan_engine.service.db.session import make_sessions

SECRET = "x" * 40
BOSS = "boss@example.com"


@pytest.fixture
def auth(pg: Engine) -> Auth:
    return Auth(AuthConfig(SECRET, "http://t", superusers=(BOSS,)), make_sessions(pg))


def _login(auth: Auth, sub: str) -> str:
    email = BOSS if sub == "boss" else f"{sub}@example.com"
    info = {"sub": sub, "email": email, "email_verified": True, "name": sub}
    return auth._finish_login(info, None, "pytest")[0]


def _client(auth: Auth, tmp_path: Path, token: str | None) -> TestClient:
    client = TestClient(create_viewer(tmp_path, auth))
    if token is not None:
        client.cookies.set(COOKIE, token)
    return client


def _ids(auth: Auth, *tokens: str) -> list[str]:
    with auth.db() as db:
        return [str(acc.session_user(db, t).id) for t in tokens]  # type: ignore[union-attr]


def test_only_superuser_gets_in(auth: Auth, tmp_path: Path) -> None:
    assert _client(auth, tmp_path, None).get("/api/admin/summary").status_code == 401
    user = _login(auth, "user")
    assert _client(auth, tmp_path, user).get("/api/admin/studios").status_code == 403
    boss = _client(auth, tmp_path, _login(auth, "boss"))
    summary = boss.get("/api/admin/summary").json()
    assert summary["users"] == 2 and summary["feedback_new"] == 0  # db/feedback.py
    assert boss.get("/api/admin/studios/not-an-id").status_code == 404


def test_studio_members_keep_rules(auth: Auth, tmp_path: Path) -> None:
    owner, staff, other = _login(auth, "owner"), _login(auth, "staff"), _login(auth, "other")
    with auth.db() as db:
        o, x = acc.session_user(db, owner), acc.session_user(db, other)
        assert o is not None and x is not None
        firm = str(acc.register_firm(db, o, "Искра", "electric").id)
        acc.register_firm(db, x, "Другая", "design")
    owner_id, staff_id, other_id = _ids(auth, owner, staff, other)
    boss = _client(auth, tmp_path, _login(auth, "boss"))

    url = f"/api/admin/studios/{firm}/members"
    r = boss.post(url, json={"user": staff_id, "role": "installer"})
    assert r.status_code == 200
    assert {m["user"]["id"]: m["role"] for m in r.json()["members"]} == {
        owner_id: "owner", staff_id: "installer"
    }  # fmt: skip
    taken = boss.post(url, json={"user": other_id, "role": "designer"})
    assert taken.status_code == 409 and "уже в «Другая»" in taken.json()["detail"]
    assert boss.patch(f"{url}/{staff_id}", json={"role": "designer"}).status_code == 200
    last = boss.patch(f"{url}/{owner_id}", json={"role": "designer"})
    assert last.status_code == 409 and "владелец" in last.json()["detail"]
    assert boss.delete(f"{url}/{owner_id}").status_code == 409
    assert boss.delete(f"{url}/{staff_id}").status_code == 200
    invite = boss.post(f"/api/admin/studios/{firm}/invites", json={"role": "installer"})
    assert invite.json()["url"].startswith("http://t/?invite=")
    assert boss.get("/api/admin/studios").json()[0]["members"] >= 1


def test_project_access_from_admin(auth: Auth, tmp_path: Path) -> None:
    owner, flat, dev = _login(auth, "owner"), _login(auth, "flat"), _login(auth, "dev")
    with auth.db() as db:
        o = acc.session_user(db, owner)
        assert o is not None
        acc.set_account_type(db, o, "pro")
        p1 = str(acc.create_project_for(db, o, "Кв 1", "kv1").id)
        p2 = str(acc.create_project_for(db, o, "Кв 2", "kv2").id)
    owner_id, flat_id, dev_id = _ids(auth, owner, flat, dev)
    boss = _client(auth, tmp_path, _login(auth, "boss"))
    base = f"/api/admin/projects/{p1}"

    r = boss.post(f"{base}/members", json={"user": flat_id, "role": "client"})
    assert r.status_code == 200 and r.json()["members"][0]["role"] == "client"
    second = boss.post(
        f"/api/admin/projects/{p2}/members", json={"user": flat_id, "role": "client"}
    )
    assert second.status_code == 409 and "уже есть проект" in second.json()["detail"]
    own = boss.post(f"{base}/members", json={"user": owner_id, "role": "installer"})
    assert own.status_code == 409  # already in the project's studio

    code = boss.post(f"{base}/codes", json={"label": "Иван"}).json()["code"]
    assert len(code) == 9 and code[4] == "-"
    detail = boss.get(base).json()
    assert detail["codes"][0]["label"] == "Иван" and detail["codes"][0]["state"] == "active"
    assert detail["codes"][0]["code"] == code  # kept, to copy from the list
    revoked = boss.delete(f"{base}/codes/{detail['codes'][0]['id']}").json()
    assert revoked["codes"][0]["state"] == "revoked"
    assert revoked["codes"][0]["code"] is None  # a dead code is not shown

    boss.post(f"{base}/invites", json={"role": "installer", "email": "i@x.io"})
    invite = boss.get(base).json()["invites"][0]
    assert invite["state"] == "active"
    assert boss.delete(f"/api/admin/invites/{invite['id']}").status_code == 200
    assert boss.get(base).json()["invites"][0]["state"] == "revoked"

    granted = boss.post(f"{base}/support", json={"user": dev_id, "reason": "щит"}).json()
    assert granted["support"][0]["state"] == "active"
    with auth.db() as db:
        project = acc.project_by_slug(db, "kv1")
        d = acc.session_user(db, dev)
        assert acc.project_role(db, acc.Principal(d), project) == "support"
    assert boss.delete(f"{base}/support/{dev_id}").json()["support"][0]["state"] == "revoked"
    assert boss.delete(f"{base}/members/{flat_id}").json()["members"] == []

    log = boss.get(f"/api/admin/events?project={p1}").json()
    actions = {e["action"] for e in log}
    assert {"admin_member_add", "code_issue", "admin_invite_revoke", "support_revoke"} <= actions
    added = next(e for e in log if e["action"] == "admin_member_add")
    assert added["subject"]["name"] == "flat" and added["user"]["email"] == "boss@example.com"


def test_block_ends_sessions(auth: Auth, tmp_path: Path) -> None:
    user = _login(auth, "user")
    boss_token = _login(auth, "boss")
    user_id, boss_id = _ids(auth, user, boss_token)
    boss = _client(auth, tmp_path, boss_token)
    assert (
        boss.post(f"/api/admin/users/{boss_id}/active", json={"active": False}).status_code == 409
    )
    r = boss.post(f"/api/admin/users/{user_id}/active", json={"active": False})
    assert r.status_code == 200 and r.json()["active"] is False and r.json()["sessions"] == []
    assert _client(auth, tmp_path, user).get("/api/auth/me").json()["user"] is None
    assert [u["email"] for u in boss.get("/api/admin/users?q=USER").json()] == ["user@example.com"]


def test_project_services_from_admin(auth: Auth, tmp_path: Path) -> None:
    """Services of a project (db/services.py): all by default, the admin ticks them, an unknown
    key is a rule broken (409), an empty list is allowed, the change is in the audit log."""
    owner = _login(auth, "owner")
    with auth.db() as db:
        o = acc.session_user(db, owner)
        assert o is not None
        acc.set_account_type(db, o, "pro")
        pid = str(acc.create_project_for(db, o, "Кв 1", "kv1").id)
    boss = _client(auth, tmp_path, _login(auth, "boss"))
    base = f"/api/admin/projects/{pid}"

    assert boss.get(base).json()["services"] == ["electrical", "plumbing", "demolition"]
    assert boss.get("/api/admin/projects").json()[0]["services"] == [
        "electrical", "plumbing", "demolition"
    ]  # fmt: skip
    r = boss.put(f"{base}/services", json={"services": ["plumbing", "electrical", "plumbing"]})
    assert r.status_code == 200 and r.json()["services"] == ["electrical", "plumbing"]
    assert boss.get("/api/admin/projects").json()[0]["services"] == ["electrical", "plumbing"]

    bad = boss.put(f"{base}/services", json={"services": ["electrical", "roof"]})
    assert bad.status_code == 409 and "неизвестный сервис roof" in bad.json()["detail"]
    assert boss.get(base).json()["services"] == ["electrical", "plumbing"]  # unchanged

    assert boss.put(f"{base}/services", json={"services": []}).json()["services"] == []
    missing = boss.put("/api/admin/projects/not-an-id/services", json={"services": []})
    assert missing.status_code == 404
    assert boss.put(f"{base}/services", json={}).status_code == 422

    log = boss.get(f"/api/admin/events?project={pid}").json()
    changes = [e["payload"]["services"] for e in log if e["action"] == "admin_project_services"]
    assert changes == [[], ["electrical", "plumbing"]]  # newest first


def test_clients_of_three_kinds(auth: Auth, tmp_path: Path) -> None:
    """GET /api/admin/clients: one row per client account, newest first — their own "Мой
    ремонт" project, a studio project by invite, or none yet; q searches like users."""
    owner, flat, guest, lonely = (_login(auth, n) for n in ("owner", "flat", "guest", "lonely"))
    _login(auth, "nobody")  # no account type yet — not a client
    with auth.db() as db:
        o, f, g, n = (acc.session_user(db, t) for t in (owner, flat, guest, lonely))
        assert o is not None and f is not None and g is not None and n is not None
        firm = acc.register_firm(db, o, "Искра", "electric")
        kv = acc.create_project_for(db, o, "Кв студии", "kv1")
        acc.accept_invite(db, g, acc.create_invite(db, o, "client", project=kv))
        acc.set_account_type(db, f, "client")
        acc.create_project_for(db, f, "Моя квартира", "flat")
        acc.set_account_type(db, n, "client")
        firm_id, kv_id = str(firm.id), str(kv.id)
    assert _client(auth, tmp_path, owner).get("/api/admin/clients").status_code == 403
    boss = _client(auth, tmp_path, _login(auth, "boss"))
    rows = boss.get("/api/admin/clients").json()
    assert [(r["user"]["name"], r["kind"]) for r in rows] == [
        ("lonely", "none"), ("guest", "studio"), ("flat", "personal")
    ]  # fmt: skip
    none, studio, personal = rows
    assert none["project"] is None and none["studio"] is None
    assert studio["project"]["id"] == kv_id
    assert studio["studio"] == {"id": firm_id, "name": "Искра"}
    assert personal["project"]["name"] == "Моя квартира" and personal["studio"] is None
    assert set(personal) == {"user", "kind", "project", "studio"}
    assert [r["user"]["email"] for r in boss.get("/api/admin/clients?q=GUE").json()] == [
        "guest@example.com"
    ]
    assert boss.get("/api/admin/summary").json()["clients"] == 3


def test_studio_detail_shows_prices_and_profile(auth: Auth, tmp_path: Path) -> None:
    """The studio card shows its price list as written and its profile, read-only; a studio
    without them gets null text and null profile."""
    owner, other = _login(auth, "owner"), _login(auth, "other")
    with auth.db() as db:
        o, x = acc.session_user(db, owner), acc.session_user(db, other)
        assert o is not None and x is not None
        firm = acc.register_firm(db, o, "Искра", "electric")
        bare = str(acc.register_firm(db, x, "Пустая", "design").id)
        sync.put_price_list(db, {"studio_id": firm.id}, "currency: грн\nitems:\n  work.chase: 5\n")
        db.add(StudioProfile(studio_id=firm.id, organization="ООО Искра", stage="Р"))
        firm_id = str(firm.id)
    boss = _client(auth, tmp_path, _login(auth, "boss"))
    detail = boss.get(f"/api/admin/studios/{firm_id}").json()
    assert detail["prices"]["text"] == "currency: грн\nitems:\n  work.chase: 5\n"
    assert detail["prices"]["updated"] is not None
    assert detail["profile"] == {"organization": "ООО Искра", "stage": "Р", "signatures": []}
    empty = boss.get(f"/api/admin/studios/{bare}").json()
    assert empty["prices"] == {"text": None, "updated": None} and empty["profile"] is None
