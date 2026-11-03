"""Platform admin (service/db/admin.py, service/api/admin.py): only an active superuser gets in;
changes keep the access rules (one workspace, one client project, a studio keeps an owner) and
land in the audit log."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from floorplan_engine.service.api.auth import COOKIE, Auth, AuthConfig
from floorplan_engine.service.api.viewer import create_viewer
from floorplan_engine.service.db import access as acc
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
    assert boss.get("/api/admin/summary").json()["users"] == 2
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
    assert detail["codes"][0]["label"] == "Иван" and detail["codes"][0]["active"] is True
    revoked = boss.delete(f"{base}/codes/{detail['codes'][0]['id']}").json()
    assert revoked["codes"][0]["active"] is False

    boss.post(f"{base}/invites", json={"role": "installer", "email": "i@x.io"})
    invite = boss.get(base).json()["invites"][0]
    assert invite["state"] == "active"
    assert boss.delete(f"/api/admin/invites/{invite['id']}").status_code == 200
    assert boss.get(base).json()["invites"][0]["state"] == "revoked"

    granted = boss.post(f"{base}/support", json={"user": dev_id, "reason": "щит"}).json()
    assert granted["support"][0]["active"] is True
    with auth.db() as db:
        project = acc.project_by_slug(db, "kv1")
        d = acc.session_user(db, dev)
        assert acc.project_role(db, acc.Principal(d), project) == "support"
    assert boss.delete(f"{base}/support/{dev_id}").json()["support"][0]["active"] is False
    assert boss.delete(f"{base}/members/{flat_id}").json()["members"] == []

    actions = [e["action"] for e in boss.get(f"/api/admin/events?project={p1}").json()]
    assert {"admin_member_add", "code_issue", "admin_invite_revoke", "support_revoke"} <= set(
        actions
    )


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
