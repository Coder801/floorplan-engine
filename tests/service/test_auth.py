"""Вход в просмотр (service/api/auth.py): настройки из окружения, гость отладки, проверка доступа
к проектам, приглашения. Вход Google — ответом провайдера (Auth._finish_login): обмен кода
с Google без ключей не проверить."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from floorplan_engine.service.api.auth import COOKIE, Auth, AuthConfig, ConfigError
from floorplan_engine.service.api.mail import LogMailer, SmtpMailer, mailer_from_env
from floorplan_engine.service.api.viewer import create_viewer
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db.session import create_tables, make_engine, make_sessions

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
        "email": False,
        "dev": False,
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
    # Фирма — только регистрацией с названием и видом
    assert client.post("/api/auth/account-type", json={"type": "pro"}).status_code == 422
    bad = client.post("/api/auth/firm", json={"name": " ", "business": "electric"})
    assert bad.status_code == 409 and "название" in bad.json()["detail"]
    r = client.post(
        "/api/auth/firm",
        json={"name": "Искра", "business": "electric", "city": "Киев", "phone": "+380 44 000"},
    )
    assert r.status_code == 200 and r.json()["account_type"] == "pro"
    assert r.json()["space"] == {
        "kind": "studio", "name": "Искра", "business": "electric", "city": "Киев"
    }  # fmt: skip
    assert client.post("/api/auth/account-type", json={"type": "client"}).status_code == 409
    _, error = _login(auth, "late", "нет-такого")
    assert error is not None and "не найдено" in error


def test_open_viewer_reports_auth_off(root: Path) -> None:
    client = TestClient(create_viewer(root))
    assert client.get("/api/auth/me").json() == {"auth": False}
    assert len(client.get("/api/projects").json()) == 3


class _Outbox:
    """Почтальон для тестов: письма — в список."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, text: str) -> None:
        self.sent.append((to, subject, text))

    def code(self) -> str:
        return self.sent[-1][1].rsplit(" ", 1)[-1]


def test_mailer_from_env() -> None:
    assert isinstance(mailer_from_env({}, local=True), LogMailer)
    assert mailer_from_env({}, local=False) is None  # в работе без SMTP — входа по коду нет
    smtp = mailer_from_env({"SMTP_HOST": "smtp.x", "SMTP_USER": "u@x"}, local=False)
    assert isinstance(smtp, SmtpMailer) and smtp.port == 587 and smtp.sender == "u@x"


def test_email_code_login(auth: Auth, root: Path) -> None:
    """Код на почту → вход: cookie сессии, тот же пользователь, что с Google по этому email;
    неверный код — 400, частый запрос — 429; без почтальона — 503."""
    outbox = _Outbox()
    auth.mailer = outbox
    client = TestClient(create_viewer(root, auth))
    assert client.get("/api/auth/me").json()["email"] is True
    assert client.post("/api/auth/email/start", json={"email": "nope"}).status_code == 400
    r = client.post("/api/auth/email/start", json={"email": "Ann@Example.com", "lang": "uk"})
    assert r.status_code == 200 and r.json()["resend_in"] > 0
    to, subject, _ = outbox.sent[-1]
    assert to == "ann@example.com" and subject.startswith("Код входу")
    again = client.post("/api/auth/email/start", json={"email": "ann@example.com"})
    assert again.status_code == 429 and int(again.headers["Retry-After"]) > 0

    wrong = "000000" if outbox.code() != "000000" else "111111"
    bad = client.post("/api/auth/email/verify", json={"email": "ann@example.com", "code": wrong})
    assert bad.status_code == 400 and "попыток" in bad.json()["detail"]
    ok = client.post(
        "/api/auth/email/verify", json={"email": "ann@example.com", "code": outbox.code()}
    )
    assert ok.status_code == 200 and COOKIE in ok.cookies
    me = client.get("/api/auth/me").json()["user"]
    assert me["email"] == "ann@example.com"

    # Google с тем же подтверждённым адресом — тот же пользователь
    with auth.db() as db:
        google = acc.oauth_login(db, "google", "ann", "ann@example.com", True)
        assert str(google.id) == me["id"]

    auth.mailer = None
    off = TestClient(create_viewer(root, auth))
    assert off.get("/api/auth/me").json()["email"] is False
    assert off.post("/api/auth/email/start", json={"email": "a@b.cd"}).status_code == 503


def test_dev_login_config() -> None:
    """Вход для разработки — только локально и только при суперпользователе."""
    env = {**ENV, "SHTROBA_DEV_LOGIN": "1", "SHTROBA_SUPERUSERS": "Dev@x.io"}
    config = AuthConfig.from_env(env)
    assert config is not None and config.dev_login
    with pytest.raises(ConfigError, match="локальной"):
        AuthConfig.from_env({**env, "SHTROBA_PUBLIC_URL": "https://shtroba.app"})
    with pytest.raises(ConfigError, match="локальной"):
        AuthConfig.from_env({**env, "RAILWAY_ENVIRONMENT_NAME": "production"})
    with pytest.raises(ConfigError, match="SHTROBA_SUPERUSERS"):
        AuthConfig.from_env({**ENV, "SHTROBA_DEV_LOGIN": "1"})


def test_dev_login(tmp_path: Path, root: Path) -> None:
    """«Зайти для разработки» — сессия первого суперпользователя; выключен — 403."""
    engine = make_engine(f"sqlite:///{tmp_path / 'dev.db'}")
    create_tables(engine)
    config = AuthConfig(SECRET, "http://t", superusers=("dev@x.io",), dev_login=True)
    client = TestClient(create_viewer(root, Auth(config, make_sessions(engine))))
    assert client.get("/api/auth/me").json()["dev"] is True
    r = client.post("/api/auth/dev")
    assert r.status_code == 200 and COOKIE in r.cookies
    user = client.get("/api/auth/me").json()["user"]
    assert user["email"] == "dev@x.io" and user["superuser"] is True
    assert client.get("/api/projects").status_code == 200
    off = TestClient(
        create_viewer(root, Auth(AuthConfig(SECRET, "http://t"), make_sessions(engine)))
    )
    assert off.post("/api/auth/dev").status_code == 403
