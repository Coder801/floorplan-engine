"""Access to the service API: 401, 404, 403 by the same roles as the viewer; closed by default."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from floorplan_engine.service.api.app import create_app
from floorplan_engine.service.api.auth import COOKIE, Auth, AuthConfig
from floorplan_engine.service.api.project_guard import action_for
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db import access_codes
from floorplan_engine.service.db.models import AppUser, AuditEvent, Project, ProjectMember
from floorplan_engine.service.db.session import make_sessions
from floorplan_engine.service.models import PendingTask, ProjectState
from floorplan_engine.service.storage import Storage

SECRET = "s" * 32


@pytest.fixture
def auth(pg: Engine) -> Auth:
    return Auth(AuthConfig(SECRET, "http://t"), make_sessions(pg))


@pytest.fixture
def app_client(auth: Auth, tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "data", auth=auth, workers=0))


def _client(
    app_client: TestClient, auth: Auth, sub: str, kind: acc.AccountType = "pro"
) -> TestClient:
    """A client with its own cookie, logged in as `sub` with a workspace."""
    info = {"sub": sub, "email": f"{sub}@example.com", "email_verified": True, "name": sub}
    token, _ = auth._finish_login(info, None, "pytest")
    with auth.db() as db:
        user = db.scalar(select(AppUser).where(AppUser.email == f"{sub}@example.com"))
        assert user is not None
        acc.set_account_type(db, user, kind)
    client = TestClient(app_client.app)
    client.cookies.set(COOKIE, token)
    return client


def _create(client: TestClient) -> Any:
    return client.post(
        "/projects",
        data={"name": "Кухня"},
        files=[("files", ("plan.pdf", b"%PDF-1.4 test", "application/pdf"))],
    )


def _user(db: Session, sub: str) -> AppUser:
    user = db.scalar(select(AppUser).where(AppUser.email == f"{sub}@example.com"))
    assert user is not None
    return user


def test_action_for_is_closed_by_default() -> None:
    assert action_for("GET", ["", "projects", "x", "report"]) == "view"
    assert action_for("HEAD", ["", "projects", "x"]) == "view"
    assert action_for("POST", ["", "projects", "x", "answers"]) == "answer"
    assert action_for("POST", ["", "projects", "x", "analyze"]) == "manage"
    assert action_for("PUT", ["", "projects", "x", "model", "room.yaml"]) == "manage"
    assert action_for("DELETE", ["", "projects", "x"]) == "manage"
    assert action_for("PATCH", ["", "projects", "x", "answers"]) == "manage"


def test_every_route_needs_login(app_client: TestClient) -> None:
    for route in app_client.app.routes:  # type: ignore[attr-defined]
        if not isinstance(route, APIRoute) or not route.path.startswith("/projects"):
            continue
        path = route.path.replace("{project_id}", "x").replace("{path:path}", "y")
        path = path.replace("{filename}", "y").replace("{name}", "y")
        for method in route.methods or ():
            assert app_client.request(method, path).status_code == 401, (method, path)


def test_owner_works_and_a_stranger_sees_nothing(app_client: TestClient, auth: Auth) -> None:
    owner = _client(app_client, auth, "owner")
    stranger = _client(app_client, auth, "stranger")
    created = _create(owner)
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    assert owner.get(f"/projects/{pid}").status_code == 200
    assert [p["id"] for p in owner.get("/projects").json()] == [pid]
    assert stranger.get("/projects").json() == []
    assert stranger.get(f"/projects/{pid}").status_code == 404
    assert stranger.get(f"/projects/{pid}/sources/plan.pdf").status_code == 404
    assert stranger.post(f"/projects/{pid}/analyze").status_code == 404
    assert stranger.delete(f"/projects/{pid}").status_code == 404
    assert owner.get(f"/projects/{pid}").status_code == 200


def test_project_client_views_but_does_not_manage(app_client: TestClient, auth: Auth) -> None:
    owner = _client(app_client, auth, "owner")
    pid = _create(owner).json()["id"]
    client = _client(app_client, auth, "flat", "client")
    with auth.db() as db:
        project = acc.project_by_slug(db, pid)
        assert project is not None
        db.add(ProjectMember(project_id=project.id, user_id=_user(db, "flat").id, role="client"))
    assert client.get(f"/projects/{pid}").status_code == 200
    assert client.post(f"/projects/{pid}/analyze").status_code == 403
    assert client.delete(f"/projects/{pid}").status_code == 403
    response = client.put(
        f"/projects/{pid}/model/room.yaml",
        content="name: x",
        headers={"content-type": "text/yaml"},
    )
    assert response.status_code == 403
    # The answers route is open to a client: refused by the project state, not by access
    assert client.post(f"/projects/{pid}/answers", json={"answers": {}}).status_code == 409


def test_create_needs_an_account_and_keeps_the_client_limit(
    app_client: TestClient, auth: Auth, tmp_path: Path
) -> None:
    client = _client(app_client, auth, "flat", "client")
    assert _create(client).status_code == 201
    refused = _create(client)
    assert refused.status_code == 403 and "один проект" in refused.json()["detail"]
    assert len(list((tmp_path / "data").iterdir())) == 1  # the refused folder is gone


def test_delete_keeps_the_journal_with_the_project_id(app_client: TestClient, auth: Auth) -> None:
    owner = _client(app_client, auth, "owner")
    pid = _create(owner).json()["id"]
    with auth.db() as db:
        project = acc.project_by_slug(db, pid)
        assert project is not None
        row, studio = str(project.id), str(project.studio_id)
        acc.audit(db, "support_access", project=project)
    assert owner.delete(f"/projects/{pid}").status_code == 204
    with auth.db() as db:
        assert db.scalar(select(func.count(Project.id))) == 0
        events = {e.action: e for e in db.scalars(select(AuditEvent))}
        for action in ("support_access", "project_delete"):
            assert events[action].project_id is None
            assert events[action].payload["project_id"] == row
            assert events[action].payload["studio_id"] == studio
        assert events["project_delete"].user_id is not None


def test_superuser_sees_and_manages_every_project(app_client: TestClient, auth: Auth) -> None:
    pid = _create(_client(app_client, auth, "owner")).json()["id"]
    admin = _client(app_client, auth, "admin")
    with auth.db() as db:
        _user(db, "admin").is_superuser = True
    assert [p["id"] for p in admin.get("/projects").json()] == [pid]
    assert admin.delete(f"/projects/{pid}").status_code == 204


def test_support_reads_with_a_journal_entry_and_changes_nothing(
    app_client: TestClient, auth: Auth
) -> None:
    pid = _create(_client(app_client, auth, "owner")).json()["id"]
    support = _client(app_client, auth, "dev")
    with auth.db() as db:
        project = acc.project_by_slug(db, pid)
        assert project is not None
        acc.grant_support(db, project, _user(db, "dev"), _user(db, "owner"), "разбор", 1)
    assert support.get(f"/projects/{pid}").status_code == 200
    assert support.post(f"/projects/{pid}/analyze").status_code == 403
    with auth.db() as db:
        query = select(func.count()).where(AuditEvent.action == "support_access")
        assert db.scalar(query) == 1  # the read; a refused write is not an access


def test_access_code_reads_one_project_and_creates_nothing(
    app_client: TestClient, auth: Auth
) -> None:
    owner = _client(app_client, auth, "owner")
    pid, other = _create(owner).json()["id"], _create(owner).json()["id"]
    with auth.db() as db:
        project = acc.project_by_slug(db, pid)
        assert project is not None
        code = access_codes.issue_code(db, project, _user(db, "owner"), "Иван")
    guest = TestClient(app_client.app)
    assert guest.post("/api/auth/code", json={"code": code}).status_code == 200
    assert guest.get(f"/projects/{pid}").status_code == 200
    assert guest.get(f"/projects/{other}").status_code == 404
    assert guest.post(f"/projects/{pid}/analyze").status_code == 403
    assert [p["id"] for p in guest.get("/projects").json()] == [pid]
    assert _create(guest).status_code == 403


def test_head_and_a_trailing_slash_are_closed_too(app_client: TestClient, auth: Auth) -> None:
    pid = _create(_client(app_client, auth, "owner")).json()["id"]
    assert app_client.head(f"/projects/{pid}").status_code == 401
    assert app_client.get("/projects/", follow_redirects=False).status_code == 401
    assert app_client.get(f"/projects/{pid}/", follow_redirects=False).status_code == 401


def test_a_failed_registration_leaves_no_folder(
    app_client: TestClient, auth: Auth, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = _client(app_client, auth, "owner")

    def broken(*_: object) -> None:
        raise RuntimeError("база недоступна")

    monkeypatch.setattr(acc, "create_project_for", broken)
    with pytest.raises(RuntimeError):
        _create(owner)
    assert list((tmp_path / "data").iterdir()) == []


def test_startup_with_login_recovers_work(auth: Auth, tmp_path: Path) -> None:
    storage = Storage(tmp_path / "data")
    info = storage.create("Кухня", [("plan.pdf", b"%PDF-1.4 test")])
    info.state, info.task = ProjectState.ANALYZING, PendingTask(kind="analysis")
    storage.save(info)
    app = create_app(tmp_path / "data", auth=auth, workers=1)
    with TestClient(app) as client:
        app.state.tasks.join()
        assert client.get("/projects").status_code == 401
    assert storage.load(info.id).task is None


def test_docs_stay_open(app_client: TestClient) -> None:
    assert app_client.get("/openapi.json").status_code == 200


def test_without_auth_the_api_is_open(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "data", workers=0))
    assert client.get("/projects").json() == []
