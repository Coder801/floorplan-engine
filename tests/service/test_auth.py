"""Viewer login (service/api/auth.py): settings from the environment, debug guest, project access
checks, invites. Google login via the provider answer (Auth._finish_login): exchanging the
code with Google cannot be tested without keys."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from floorplan_engine.service.api.auth import COOKIE, Auth, AuthConfig, CodeLimiter, ConfigError
from floorplan_engine.service.api.mail import LogMailer, SmtpMailer, mailer_from_env
from floorplan_engine.service.api.viewer import create_viewer
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db import access_codes
from floorplan_engine.service.db.models import Project
from floorplan_engine.service.db.session import make_sessions

SECRET = "x" * 40
ENV = {"SHTROBA_AUTH": "on", "SHTROBA_SECRET": SECRET, "SHTROBA_PUBLIC_URL": "http://t"}


def test_config_from_env() -> None:
    assert AuthConfig.from_env({}) is None  # login off: the viewer is open, as before
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
def auth(pg: Engine) -> Auth:
    engine = pg
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
        "code": None,
        "google": False,
        "email": False,
        "telegram": False,
        "dev": False,
        "visitor_allowed": True,
        "feedback": False,  # product feedback: only with projects in the database
    }
    assert client.get("/api/auth/google/login").status_code == 503  # no Google keys


def test_visitor_sees_all_read_only(auth: Auth, root: Path) -> None:
    client = TestClient(create_viewer(root, auth))
    assert client.post("/api/auth/visitor").status_code == 200
    assert client.get("/api/auth/me").json()["visitor"] is True
    names = {p["name"] for p in client.get("/api/projects").json()}
    assert names == {"kv1", "kv2", "folder-only"}
    assert client.post("/api/projects/kv1/wiring", json={}).status_code == 403
    assert client.get("/api/prices").json()["editable"] is False  # reads, does not edit
    assert client.post("/api/prices", json={"items": {}}).status_code == 403
    client.post("/api/auth/logout")
    assert client.get("/api/projects").status_code == 401


def test_visitor_off_by_default(pg: Engine, root: Path) -> None:
    engine = pg
    auth = Auth(AuthConfig(SECRET, "http://t"), make_sessions(engine))
    client = TestClient(create_viewer(root, auth))
    assert client.post("/api/auth/visitor").status_code == 403


def test_roles_filter_projects_and_actions(auth: Auth, root: Path) -> None:
    studio_token, _ = _login(auth, "studio")
    with auth.db() as db:
        studio = acc.session_user(db, studio_token)
        assert studio is not None
        acc.claim_root(db, acc.set_account_type(db, studio, "pro"))  # folders lie in the root
        kv1 = acc.create_project_for(db, studio, "Кв 1", "kv1")
        acc.create_project_for(db, studio, "Кв 2", "kv2")
        invite = acc.create_invite(db, studio, "client", project=kv1)

    client = TestClient(create_viewer(root, auth))
    info = client.get(f"/api/invites/{invite}").json()
    assert info == {"role": "client", "project": "Кв 1"}

    # A client logs in by invite: sees only their project, does not edit routes
    client_token, error = _login(auth, "flat-owner", invite)
    assert error is None
    client.cookies.set(COOKIE, client_token)
    me = client.get("/api/auth/me").json()["user"]
    assert me["account_type"] == "client"
    assert [p["name"] for p in client.get("/api/projects").json()] == ["kv1"]
    assert client.get("/api/projects/kv1").status_code == 200
    assert client.get("/api/projects/kv2").status_code == 404  # someone else's: hidden
    assert client.get("/api/projects/folder-only").status_code == 404
    assert client.post("/api/projects/kv1/wiring", json={}).status_code == 403
    assert client.get("/api/prices").status_code == 403  # the studio price list is not theirs
    # A studio client chooses the variant (the wizard) but does not edit routes; the page knows it
    assert client.get("/api/projects/kv1").json()["can"] == {
        "edit_wiring": False,
        "choose_variant": True,
        "answer": True,
        "review": False,
    }

    # The studio sees its projects but not a folder outside the database; chooses the variant and
    # edits routes
    client.cookies.set(COOKIE, studio_token)
    assert client.get("/api/projects/kv1").json()["can"]["choose_variant"] is True
    assert {p["name"] for p in client.get("/api/projects").json()} == {"kv1", "kv2"}
    assert client.get("/api/prices").json()["editable"] is True
    assert client.post("/api/prices", json={"items": {"work.chase": 90}}).status_code == 200
    assert client.get(f"/api/invites/{invite}").status_code == 404  # already accepted


def test_account_type_and_bad_invite(auth: Auth, root: Path) -> None:
    client = TestClient(create_viewer(root, auth))
    token, _ = _login(auth, "newbie")
    client.cookies.set(COOKIE, token)
    assert client.get("/api/auth/me").json()["user"]["account_type"] is None
    # A firm only through registration with a name and a kind
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
    """Test mailer: e-mails go into a list."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, text: str) -> None:
        self.sent.append((to, subject, text))

    def code(self) -> str:
        return self.sent[-1][1].rsplit(" ", 1)[-1]


def test_mailer_from_env() -> None:
    assert isinstance(mailer_from_env({}, local=True), LogMailer)
    assert mailer_from_env({}, local=False) is None  # in production without SMTP: no code login
    smtp = mailer_from_env({"SMTP_HOST": "smtp.x", "SMTP_USER": "u@x"}, local=False)
    assert isinstance(smtp, SmtpMailer) and smtp.port == 587 and smtp.sender == "u@x"


def test_email_code_login(auth: Auth, root: Path) -> None:
    """E-mail code → login: a session cookie, the same user as with Google for this e-mail; a wrong
    code gives 400, too frequent requests 429; no mailer gives 503."""
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

    # Google with the same confirmed address is the same user
    with auth.db() as db:
        google = acc.oauth_login(db, "google", "ann", "ann@example.com", True)
        assert str(google.id) == me["id"]

    auth.mailer = None
    off = TestClient(create_viewer(root, auth))
    assert off.get("/api/auth/me").json()["email"] is False
    assert off.post("/api/auth/email/start", json={"email": "a@b.cd"}).status_code == 503


def test_access_code_login(auth: Auth, root: Path) -> None:
    """Access code: login without an account to one project, read only; revocation gives 401 at
    once; many wrong codes from one address give 429."""
    studio_token, _ = _login(auth, "studio")
    with auth.db() as db:
        studio = acc.session_user(db, studio_token)
        assert studio is not None
        acc.claim_root(db, acc.set_account_type(db, studio, "pro"))  # folders lie in the root
        kv1 = acc.create_project_for(db, studio, "Кв 1", "kv1")
        acc.create_project_for(db, studio, "Кв 2", "kv2")
        code = access_codes.issue_code(db, kv1, studio, label="Иван")

    client = TestClient(create_viewer(root, auth))
    bad = client.post("/api/auth/code", json={"code": "ABCD-2345"})
    assert bad.status_code == 400 and "не подходит" in bad.json()["detail"]
    assert client.get("/api/projects").status_code == 401
    ok = client.post("/api/auth/code", json={"code": code.lower()})
    assert ok.json() == {"ok": True, "project": "kv1"}
    me = client.get("/api/auth/me").json()
    assert me["user"] is None and me["visitor"] is False
    assert me["code"] == {"project": "kv1", "name": "Кв 1"}
    assert [p["name"] for p in client.get("/api/projects").json()] == ["kv1"]
    assert client.get("/api/projects/kv1").status_code == 200
    assert client.get("/api/projects/kv2").status_code == 404
    assert client.post("/api/projects/kv1/wiring", json={}).status_code == 403
    assert client.post("/api/projects/kv1/wizard", json={"variant": {}}).status_code == 403
    assert client.get("/api/projects/kv1").json()["can"] == {
        "edit_wiring": False,
        "choose_variant": False,
        "review": False,
        "answer": False,
    }

    with auth.db() as db:
        rows = access_codes.list_codes(db, acc.project_by_slug(db, "kv1"))  # type: ignore[arg-type]
        assert rows[0].uses == 1
        access_codes.revoke_code(db, acc.project_by_slug(db, "kv1"), str(rows[0].id))  # type: ignore[arg-type]
    assert client.get("/api/projects/kv1").status_code == 401
    assert client.post("/api/auth/code", json={"code": code}).status_code == 400

    auth.limiter = CodeLimiter(tries=2)
    client.post("/api/auth/code", json={"code": "ABCD-2345"})
    client.post("/api/auth/code", json={"code": "ABCD-2346"})
    assert client.post("/api/auth/code", json={"code": code}).status_code == 429


def test_client_code_sets_the_project_up(auth: Auth, root: Path) -> None:
    """A client code: the page knows the client may answer and choose the variant, routes stay
    closed."""
    studio_token, _ = _login(auth, "studio")
    with auth.db() as db:
        studio = acc.session_user(db, studio_token)
        assert studio is not None
        acc.claim_root(db, acc.set_account_type(db, studio, "pro"))
        kv1 = acc.create_project_for(db, studio, "Кв 1", "kv1")
        code = access_codes.issue_code(db, kv1, studio, label="Иван", role="client_code")

    client = TestClient(create_viewer(root, auth))
    assert client.post("/api/auth/code", json={"code": code}).json()["project"] == "kv1"
    assert client.get("/api/projects/kv1").json()["can"] == {
        "edit_wiring": False,
        "review": False,
        "choose_variant": True,
        "answer": True,
    }
    assert client.post("/api/projects/kv1/wiring", json={}).status_code == 403


def test_code_limiter_window() -> None:
    limiter = CodeLimiter(tries=2, window=10)
    limiter.fail("a", 0)
    limiter.fail("a", 1)
    assert limiter.blocked("a", 2) and not limiter.blocked("b", 2)
    assert not limiter.blocked("a", 12)  # old misses are forgotten


def test_dev_login_config() -> None:
    """Development login only locally and only with a superuser."""
    env = {**ENV, "SHTROBA_DEV_LOGIN": "1", "SHTROBA_SUPERUSERS": "Dev@x.io"}
    config = AuthConfig.from_env(env)
    assert config is not None and config.dev_login
    with pytest.raises(ConfigError, match="локальной"):
        AuthConfig.from_env({**env, "SHTROBA_PUBLIC_URL": "https://shtroba.app"})
    with pytest.raises(ConfigError, match="локальной"):
        AuthConfig.from_env({**env, "RAILWAY_ENVIRONMENT_NAME": "production"})
    with pytest.raises(ConfigError, match="SHTROBA_SUPERUSERS"):
        AuthConfig.from_env({**ENV, "SHTROBA_DEV_LOGIN": "1"})


def test_dev_login(pg: Engine, root: Path) -> None:
    """The "Log in for development" button opens a session of the first superuser; off gives 403."""
    engine = pg
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


def test_owner_login_adopts_project_folders(pg: Engine, root: Path) -> None:
    """SHTROBA_OWNER: folders without a database row go to the owner's studio when they log in and
    choose "Firm"; other users do not get the folders."""
    engine = pg
    auth = Auth(AuthConfig(SECRET, "http://t", owner="boss@example.com"), make_sessions(engine))
    client = TestClient(create_viewer(root, auth))
    token, _ = _login(auth, "guest")
    with auth.db() as db:
        assert acc.project_by_slug(db, "kv1") is None  # someone else logs in: nothing
    token, _ = _login(auth, "boss")
    with auth.db() as db:
        assert acc.project_by_slug(db, "kv1") is None  # owner without an account type: too early
    client.cookies.set(COOKIE, token)
    r = client.post("/api/auth/firm", json={"name": "Штроба", "business": "electric"})
    assert r.status_code == 200
    assert {p["name"] for p in client.get("/api/projects").json()} == {"kv1", "kv2", "folder-only"}
    _folder(root, "kv3")  # a new folder after deploy: on the next login
    _login(auth, "boss")
    with auth.db() as db:
        assert acc.project_by_slug(db, "kv3") is not None
        assert len(db.query(Project).all()) == 4  # logging in again duplicates nothing


def test_fixed_codes_from_env() -> None:
    """SHTROBA_ACCESS_CODES: "folder=CODE" comma-separated, the code as in the database; a
    malformed entry is an error.
    """
    config = AuthConfig.from_env({**ENV, "SHTROBA_ACCESS_CODES": " kv1=abcd-2345, kv2=WXYZ 6789 ,"})
    assert config is not None and config.fixed_codes == (("kv1", "ABCD2345"), ("kv2", "WXYZ6789"))
    for bad in ("kv1", "=ABCD-2345", "kv1=ABCD-234O"):
        with pytest.raises(ConfigError, match="SHTROBA_ACCESS_CODES"):
            AuthConfig.from_env({**ENV, "SHTROBA_ACCESS_CODES": bad})


def test_fixed_codes_seeded_at_startup(pg: Engine, root: Path) -> None:
    """A permanent code goes to the database on server start: a project without a row is written as
    "no owner", the code opens only that project; a restart duplicates nothing."""
    engine = pg
    config = AuthConfig(SECRET, "http://t", fixed_codes=(("kv1", "ABCD2345"),))
    app = create_viewer(root, Auth(config, make_sessions(engine)))
    for _ in range(2):  # two starts, one code row
        with TestClient(app) as client:
            r = client.post("/api/auth/code", json={"code": "abcd-2345"})
            assert r.status_code == 200 and r.json()["project"] == "kv1"
            assert {p["name"] for p in client.get("/api/projects").json()} == {"kv1"}
    auth = Auth(config, make_sessions(engine))
    with auth.db() as db:
        kv1 = acc.project_by_slug(db, "kv1")
        assert kv1 is not None and len(access_codes.list_codes(db, kv1)) == 1


def test_fixed_codes_skip_unknown_folder_and_taken_code(pg: Engine, root: Path) -> None:
    """No folder (a typo in SHTROBA_ACCESS_CODES) or the code already belongs to another project: no
    project row is created, the other codes are written."""
    codes = (("kv-typo", "ABCD2345"), ("kv1", "WXYZ6789"), ("kv2", "WXYZ6789"))
    config = AuthConfig(SECRET, "http://t", fixed_codes=codes)
    app = create_viewer(root, Auth(config, make_sessions(pg)))
    with TestClient(app) as client:
        assert client.post("/api/auth/code", json={"code": "WXYZ-6789"}).json()["project"] == "kv1"
        assert client.post("/api/auth/code", json={"code": "ABCD-2345"}).status_code != 200
    with Auth(config, make_sessions(pg)).db() as db:
        assert {p.slug for p in db.query(Project).all()} == {"kv1"}


def test_studios_have_own_folders_and_price_lists(auth: Auth, root: Path) -> None:
    """The studio that took the root sees the root projects; another studio sees only the
    projects in its own folder (<root>/<studio id>/) and edits its own price list there — neither
    sees nor changes the other's prices."""
    a_token, _ = _login(auth, "studio-a")
    b_token, _ = _login(auth, "studio-b")
    with auth.db() as db:
        a = acc.session_user(db, a_token)
        b = acc.session_user(db, b_token)
        assert a is not None and b is not None
        acc.claim_root(db, acc.set_account_type(db, a, "pro"))
        acc.create_project_for(db, a, "Кв 1", "kv1")
        firm_b = acc.set_account_type(db, b, "pro")
        with pytest.raises(acc.AccessError, match="уже у"):
            acc.claim_root(db, firm_b)
        acc.create_project_for(db, b, "Б 1", "b1")
        folder_b = root / acc.studio_folder(firm_b)
    assert folder_b.parent == root and folder_b.name != ""
    _folder(folder_b, "b1")

    client = TestClient(create_viewer(root, auth))
    client.cookies.set(COOKIE, b_token)
    assert [p["name"] for p in client.get("/api/projects").json()] == ["b1"]
    assert client.get("/api/projects/b1").status_code == 200
    assert client.get("/api/projects/kv1").status_code == 404
    assert client.get("/api/prices").json()["exists"] is False  # no inherited list
    assert client.post("/api/prices", json={"items": {"work.chase": 111}}).status_code == 200
    assert "111" in (folder_b / "prices.yaml").read_text("utf-8")
    assert not (root / "prices.yaml").exists()

    client.cookies.set(COOKIE, a_token)
    assert [p["name"] for p in client.get("/api/projects").json()] == ["kv1"]
    assert client.get("/api/projects/b1").status_code == 404
    assert client.get("/api/prices").json()["exists"] is False  # B's list is not A's
    assert client.post("/api/prices", json={"items": {"work.chase": 222}}).status_code == 200
    assert "222" in (root / "prices.yaml").read_text("utf-8")
    assert "111" in (folder_b / "prices.yaml").read_text("utf-8")
