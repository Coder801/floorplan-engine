"""Вход в просмотр (service/auth.py): настройки из окружения, гость отладки, проверка доступа
к проектам, приглашения. Вход Google — ответом провайдера (Auth._finish_login): обмен кода
с Google без ключей не проверить."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from floorplan_engine.service.auth import COOKIE, Auth, AuthConfig, ConfigError
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db.session import create_tables, make_engine, make_sessions
from floorplan_engine.service.viewer import create_viewer

SECRET = "x" * 40
ENV = {"SHTROBA_AUTH": "on", "SHTROBA_SECRET": SECRET, "SHTROBA_PUBLIC_URL": "http://t"}


def test_config_from_env() -> None:
    assert AuthConfig.from_env({}) is None  # вход выключен — просмотр открыт, как раньше
    config = AuthConfig.from_env({**ENV, "SHTROBA_SUPERUSERS": "A@b.c, d@e.f"})
    assert config is not None and not config.google and not config.visitor
    assert config.superusers == ("a@b.c", "d@e.f")
    with pytest.raises(ConfigError, match="SHTROBA_SECRET"):
        AuthConfig.from_env({**ENV, "SHTROBA_SECRET": "short"})
    with pytest.raises(ConfigError, match="production"):
        AuthConfig.from_env(
            {**ENV, "SHTROBA_VISITOR": "1", "RAILWAY_ENVIRONMENT_NAME": "production"}
        )


def _folder(root: Path, name: str) -> None:
    (root / name / "out").mkdir(parents=True)
    (root / name / "room.yaml").write_text("name: x\n", "utf-8")


@pytest.fixture
def auth(tmp_path: Path) -> Auth:
    engine = make_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    create_tables(engine)
    return Auth(AuthConfig(SECRET, "http://t", visitor=True), make_sessions(engine))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    projects = tmp_path / "projects"
    for name in ("kv1", "kv2", "folder-only"):
        _folder(projects, name)
    return projects


def _login(auth: Auth, sub: str, invite: str | None = None) -> tuple[str, str | None]:
    info = {"sub": sub, "email": f"{sub}@example.com", "email_verified": True, "name": sub}
    return auth._finish_login(info, invite, "pytest")


def test_closed_without_login_and_open_auth_routes(auth: Auth, root: Path) -> None:
    client = TestClient(create_viewer(root, auth))
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/projects/kv1").status_code == 401
    me = client.get("/api/auth/me").json()
    assert me == {
        "auth": True,
        "user": None,
        "visitor": False,
        "google": False,
        "visitor_allowed": True,
    }
    assert client.get("/api/auth/google/login").status_code == 503  # ключей Google нет


def test_visitor_sees_all_read_only(auth: Auth, root: Path) -> None:
    client = TestClient(create_viewer(root, auth))
    assert client.post("/api/auth/visitor").status_code == 200
    assert client.get("/api/auth/me").json()["visitor"] is True
    names = {p["name"] for p in client.get("/api/projects").json()}
    assert names == {"kv1", "kv2", "folder-only"}
    assert client.post("/api/projects/kv1/wiring", json={}).status_code == 403
    client.post("/api/auth/logout")
    assert client.get("/api/projects").status_code == 401


def test_visitor_off_by_default(tmp_path: Path, root: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'off.db'}")
    create_tables(engine)
    auth = Auth(AuthConfig(SECRET, "http://t"), make_sessions(engine))
    client = TestClient(create_viewer(root, auth))
    assert client.post("/api/auth/visitor").status_code == 403


def test_roles_filter_projects_and_actions(auth: Auth, root: Path) -> None:
    studio_token, _ = _login(auth, "studio")
    with auth.db() as db:
        studio = acc.session_user(db, studio_token)
        assert studio is not None
        acc.set_account_type(db, studio, "pro")
        kv1 = acc.create_project_for(db, studio, "Кв 1", "kv1")
        acc.create_project_for(db, studio, "Кв 2", "kv2")
        invite = acc.create_invite(db, studio, "client", project=kv1)

    client = TestClient(create_viewer(root, auth))
    info = client.get(f"/api/invites/{invite}").json()
    assert info == {"role": "client", "project": "Кв 1"}

    # Клиент входит по приглашению: видит только свой проект, трассы не правит
    client_token, error = _login(auth, "flat-owner", invite)
    assert error is None
    client.cookies.set(COOKIE, client_token)
    me = client.get("/api/auth/me").json()["user"]
    assert me["account_type"] == "client"
    assert [p["name"] for p in client.get("/api/projects").json()] == ["kv1"]
    assert client.get("/api/projects/kv1").status_code == 200
    assert client.get("/api/projects/kv2").status_code == 404  # чужой — как будто нет
    assert client.get("/api/projects/folder-only").status_code == 404
    assert client.post("/api/projects/kv1/wiring", json={}).status_code == 403

    # Студия видит свои проекты, но не папку вне базы
    client.cookies.set(COOKIE, studio_token)
    assert {p["name"] for p in client.get("/api/projects").json()} == {"kv1", "kv2"}
    assert client.get(f"/api/invites/{invite}").status_code == 404  # уже принято


def test_account_type_and_bad_invite(auth: Auth, root: Path) -> None:
    client = TestClient(create_viewer(root, auth))
    token, _ = _login(auth, "newbie")
    client.cookies.set(COOKIE, token)
    assert client.get("/api/auth/me").json()["user"]["account_type"] is None
    r = client.post("/api/auth/account-type", json={"type": "pro"})
    assert r.status_code == 200 and r.json()["account_type"] == "pro"
    assert client.post("/api/auth/account-type", json={"type": "client"}).status_code == 409
    _, error = _login(auth, "late", "нет-такого")
    assert error is not None and "не найдено" in error


def test_open_viewer_reports_auth_off(root: Path) -> None:
    client = TestClient(create_viewer(root))
    assert client.get("/api/auth/me").json() == {"auth": False}
    assert len(client.get("/api/projects").json()) == 3
