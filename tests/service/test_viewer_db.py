"""Viewer API from the database (service/api/viewer_db.py): projects by id (an old link by name
still opens), sheets and files from the latest build in file storage, writes as new model
versions with a rebuild, the price list of the caller's own studio."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from floorplan_engine.service import project_store as ps
from floorplan_engine.service import sync
from floorplan_engine.service.api.auth import COOKIE, Auth, AuthConfig
from floorplan_engine.service.api.viewer import create_viewer
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db import repositories as repo
from floorplan_engine.service.db.models import PriceList, Project
from floorplan_engine.service.db.session import make_sessions
from floorplan_engine.service.objects import LocalObjectStore
from tests.electrical.test_variants import _project

SECRET = "x" * 40


@pytest.fixture
def auth(pg: Engine) -> Auth:
    return Auth(AuthConfig(SECRET, "http://t"), make_sessions(pg))


def _login(auth: Auth, sub: str) -> str:
    info = {"sub": sub, "email": f"{sub}@example.com", "email_verified": True, "name": sub}
    return auth._finish_login(info, None, "pytest")[0]


@pytest.fixture
def setup(auth: Auth, tmp_path: Path) -> tuple[TestClient, LocalObjectStore, dict[str, str]]:
    """Firm A with project kv (pushed from a folder, with a source), its client, firm B."""
    store = LocalObjectStore(tmp_path / "store")
    tokens = {name: _login(auth, name) for name in ("a", "b", "client")}
    folder = _project(tmp_path)
    (folder / "source").mkdir()
    (folder / "source" / "plan.pdf").write_bytes(b"%PDF-1")
    with auth.db() as db:
        a, b = acc.session_user(db, tokens["a"]), acc.session_user(db, tokens["b"])
        assert a is not None and b is not None
        firm = acc.register_firm(db, a, "А", "electric")
        acc.register_firm(db, b, "Б", "design")
        pushed = sync.push(db, store, folder, firm)
        tokens["id"] = str(pushed.project.id)
        invite = acc.create_invite(db, a, "client", project=pushed.project)
    with auth.db() as db:
        client = acc.session_user(db, tokens["client"])
        assert client is not None
        acc.accept_invite(db, client, invite)
    (tmp_path / "market").mkdir()
    return TestClient(create_viewer(tmp_path / "market", auth, store)), store, tokens


def test_needs_login(auth: Auth, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="только со входом"):
        create_viewer(tmp_path, None, LocalObjectStore(tmp_path))
    client = TestClient(create_viewer(tmp_path, auth, LocalObjectStore(tmp_path)))
    assert client.get("/api/projects").status_code == 401


def test_project_sheets_and_files_from_storage(
    setup: tuple[TestClient, LocalObjectStore, dict[str, str]],
) -> None:
    client, _, tokens = setup
    pid = tokens["id"]
    client.cookies.set(COOKIE, tokens["a"])
    [card] = client.get("/api/projects").json()
    assert (card["id"], card["name"], card["stale"], card["preview"]) == (pid, "kv", False, True)
    p = client.get(f"/api/projects/{pid}").json()
    assert p["artifact"] and p["dxf"] == "project.dxf" and p["sources"] == ["plan.pdf"]
    assert p["model"] == ["room.yaml", "electrical.yaml"]
    assert p["can"] == {"edit_wiring": True, "choose_variant": True, "answer": True}
    assert client.get("/api/projects/kv").json()["id"] == pid  # an old link by name
    manifest = client.get(f"/api/projects/{pid}/sheets").json()
    first = manifest["pages"][0]["index"]
    assert client.get(f"/api/projects/{pid}/sheets/{first}").status_code == 200
    assert client.get(f"/api/projects/{pid}/out/preview.svg").text.startswith("<svg")
    assert client.get(f"/api/projects/{pid}/source/plan.pdf").content == b"%PDF-1"
    assert "rooms:" in client.get(f"/api/projects/{pid}/model/room.yaml").text
    assert client.get(f"/api/projects/{pid}/out/nope.csv").status_code == 404

    client.cookies.set(COOKIE, tokens["b"])  # another firm: the project does not exist for it
    assert client.get("/api/projects").json() == []
    assert client.get(f"/api/projects/{pid}").status_code == 404
    client.cookies.set(COOKIE, tokens["client"])  # the client sees it, edits nothing
    assert client.get(f"/api/projects/{pid}").json()["can"]["edit_wiring"] is False
    assert client.post(f"/api/projects/{pid}/variant", json={}).status_code == 403


def test_writes_are_new_versions(
    setup: tuple[TestClient, LocalObjectStore, dict[str, str]], auth: Auth
) -> None:
    client, _, tokens = setup
    pid = tokens["id"]
    client.cookies.set(COOKIE, tokens["a"])
    bad = client.post(f"/api/projects/{pid}/variant", json={"mode": "cheap"})
    assert bad.status_code == 422 and "mode" in bad.json()["detail"]
    ok = client.post(f"/api/projects/{pid}/variant", json={"mode": "economy", "route": "floor"})
    assert ok.status_code == 200 and ok.json()["built"] is True
    assert client.post(f"/api/projects/{pid}/wiring", json={"wires": "x"}).status_code == 422
    with auth.db() as db:
        project = acc.project_by_key(db, pid)
        assert project is not None
        latest = repo.latest_model(db, project.id)
        assert latest is not None and latest.version == 2 and latest.author == "user"
        assert "economy" in repo.model_files(latest)["variant.yaml"]
        a = acc.session_user(db, tokens["a"])
        assert a is not None and latest.user_id == a.id
    p = client.get(f"/api/projects/{pid}").json()
    assert "variant.yaml" in p["model"] and p["stale"] is False


def test_price_list_of_own_studio(
    setup: tuple[TestClient, LocalObjectStore, dict[str, str]], auth: Auth
) -> None:
    client, _, tokens = setup
    client.cookies.set(COOKIE, tokens["a"])
    page = client.get("/api/prices").json()
    assert page["editable"] is True and page["exists"] is False
    assert client.post("/api/prices", json={"items": {"work.chase": 111}}).status_code == 200
    assert client.post("/api/prices", json={"items": {"work.nope": 1}}).status_code == 422
    client.cookies.set(COOKIE, tokens["b"])
    assert client.get("/api/prices").json()["exists"] is False  # A's list is not B's
    client.cookies.set(COOKIE, tokens["client"])
    assert client.get("/api/prices").status_code == 403
    with auth.db() as db:
        rows = db.query(PriceList).all()
        assert len(rows) == 1 and rows[0].text is not None and "111" in rows[0].text


def _with_questions(auth: Auth, store: LocalObjectStore, pid: str) -> None:
    """A new model version with two questions, built."""
    intake = (
        "questions:\n"
        '  - { id: q1, stage: plan, text: "Есть обмер?", answer: text, severity: major }\n'
        '  - { id: q2, stage: plan, text: "Потолок?", answer: value,'
        " target: rooms.r.walls.w2.thickness }\n"
    )
    with auth.db() as db:
        project = db.get(Project, uuid.UUID(pid))
        assert project is not None
        latest = repo.latest_model(db, project.id)
        assert latest is not None
        files = {**repo.model_files(latest), "intake.yaml": intake}
        ps.build(db, store, project, repo.add_model_version(db, project.id, files, "user"))


def test_answers_are_new_versions(
    auth: Auth, setup: tuple[TestClient, LocalObjectStore, dict[str, str]]
) -> None:
    client, store, tokens = setup
    pid = tokens["id"]
    _with_questions(auth, store, pid)
    client.cookies.set(COOKIE, tokens["client"])
    first = client.get(f"/api/projects/{pid}").json()
    assert first["can"]["answer"] is True

    def versions() -> int:
        with auth.db() as db:
            latest = repo.latest_model(db, uuid.UUID(pid))
            assert latest is not None
            return latest.version

    start = versions()
    # A text answer: a new version, no rebuild, the sheets are not stale
    saved = client.post(
        f"/api/projects/{pid}/answers", json={"id": "q1", "answer": {"text": "нет"}}
    )
    assert saved.json() == {"built": False, "rebuilt": False}
    assert versions() == start + 1
    p = client.get(f"/api/projects/{pid}").json()
    assert p["stale"] is False
    assert next(q for q in p["report"]["questions"] if q["id"] == "q1")["state"] == "text"
    assert p["open_questions"] == first["open_questions"] - 1
    assert p["answers"]["q1"] == {"text": "нет"}
    # A refused value changes nothing
    bad = client.post(f"/api/projects/{pid}/answers", json={"id": "q2", "answer": "много"})
    assert bad.status_code == 422
    assert bad.json()["detail"]["issues"][0]["path"] == "answers.q2"
    assert versions() == start + 1
    # A value: a new version and a rebuild; the log names who answered
    saved = client.post(f"/api/projects/{pid}/answers", json={"id": "q2", "answer": 2700})
    assert saved.json() == {"built": True, "rebuilt": True}
    p = client.get(f"/api/projects/{pid}").json()
    assert p["stale"] is False and p["open_questions"] == first["open_questions"] - 2
    assert next(q for q in p["report"]["questions"] if q["id"] == "q2")["state"] == "answered"
    with auth.db() as db:
        latest = repo.latest_model(db, uuid.UUID(pid))
        assert latest is not None
        assert latest.version == start + 2 and latest.user_id is not None
        assert latest.data["answers.yaml"]["log"]["q2"]["by"] == "client"


def test_answers_need_the_right(
    setup: tuple[TestClient, LocalObjectStore, dict[str, str]],
) -> None:
    client, _, tokens = setup
    client.cookies.set(COOKIE, tokens["b"])
    url = f"/api/projects/{tokens['id']}/answers"
    assert client.post(url, json={"id": "q1", "answer": 1}).status_code == 404
