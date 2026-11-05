from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from floorplan_engine.service.api.app import create_app
from floorplan_engine.service.models import PendingTask, ProjectState
from floorplan_engine.service.storage import Storage

ROOM: dict[str, Any] = {
    "name": "Тест",
    "default_wall_thickness": 120,
    "source": "photo",
    "rooms": [
        {
            "id": "r",
            "name": "Комната",
            "walls": [
                {"id": "w1", "length": 3000},
                {"id": "w2", "length": 4000},
                {"id": "w3", "length": 3000},
                {"id": "w4", "length": 4000},
            ],
        }
    ],
}


def _q(qid: str, **fields: Any) -> dict[str, Any]:
    return {"id": qid, "stage": "plan", "text": f"Вопрос {qid}", **fields}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    # workers=0: the work is done inside the request, so the next GET sees the state
    return TestClient(create_app(tmp_path / "data", workers=0))


def _create(client: TestClient) -> str:
    response = client.post(
        "/projects",
        data={"name": "Кухня"},
        files=[("files", ("plan.pdf", b"%PDF-1.4 test", "application/pdf"))],
    )
    assert response.status_code == 201, response.text
    info = response.json()
    assert info["state"] == "created" and info["sources"] == ["source/plan.pdf"]
    project_id: str = info["id"]
    return project_id


def _put(client: TestClient, pid: str, name: str, data: Any) -> None:
    response = client.put(
        f"/projects/{pid}/model/{name}",
        content=yaml.safe_dump(data, allow_unicode=True),
        headers={"content-type": "text/yaml"},
    )
    assert response.status_code == 204, response.text


def _state(client: TestClient, pid: str) -> dict[str, Any]:
    data: dict[str, Any] = client.get(f"/projects/{pid}").json()
    return data


def test_full_cycle(client: TestClient, tmp_path: Path) -> None:
    pid = _create(client)
    # Manual analyzer without a model: waiting for the operator
    assert client.post(f"/projects/{pid}/analyze").status_code == 202
    assert _state(client, pid)["state"] == "needs_model"

    question = _q("q1", target="rooms.r.walls.w2.length", also=["rooms.r.walls.w4.length"])
    _put(client, pid, "room.yaml", ROOM)
    _put(
        client,
        pid,
        "intake.yaml",
        {"questions": [{**question, "answer": "value", "assumption": 4000}]},
    )
    client.post(f"/projects/{pid}/analyze")
    info = _state(client, pid)
    assert info["state"] == "needs_answers" and info["round"] == 1
    # A draft is already built: the plan builds on an assumption
    assert {"report.md", "report.json", "project.dxf", "project.epd"} <= set(info["files"])

    questions = client.get(f"/projects/{pid}/questions").json()
    assert [q["id"] for q in questions["questions"]] == ["q1"]
    assert questions["questions"][0]["severity"] == "major"

    assert (
        client.post(f"/projects/{pid}/answers", json={"answers": {"q1": 4200}}).status_code == 202
    )
    info = _state(client, pid)
    assert info["state"] == "ready" and info["round"] == 2, info
    assert info["stages"][0] == {
        "stage": "plan",
        "status": "ready",
        "builds": True,
        "reason": "",
        "open_questions": 0,
    }
    dxf = client.get(f"/projects/{pid}/files/project.dxf")
    assert dxf.status_code == 200 and dxf.content.startswith(b"  0\nSECTION")
    epd = client.get(f"/projects/{pid}/files/project.epd")  # sheets from .epd, no PNGs
    assert epd.status_code == 200 and epd.content.startswith(b"PK")
    assert client.get(f"/projects/{pid}/files/sheets/01-plan.png").status_code == 404

    # Round history and the answer applied to the model
    project = tmp_path / "data" / pid
    assert (project / "rounds" / "001" / "answers.json").exists()
    assert (project / "rounds" / "002" / "report.json").exists()
    assert "4200" in (project / "answers.yaml").read_text("utf-8")
    assert "4200" not in (project / "room.yaml").read_text("utf-8")


def test_errors(client: TestClient) -> None:
    assert client.get("/projects/nope").status_code == 404
    pid = _create(client)
    bad_name = client.put(
        f"/projects/{pid}/model/evil.py", content="x", headers={"content-type": "text/yaml"}
    )
    assert bad_name.status_code == 400
    # Answers before questions
    assert client.post(f"/projects/{pid}/answers", json={"answers": {"q1": 1}}).status_code == 409
    _put(client, pid, "room.yaml", ROOM)
    _put(client, pid, "intake.yaml", {"questions": [_q("q1", answer="text", severity="minor")]})
    client.post(f"/projects/{pid}/analyze")
    assert _state(client, pid)["state"] == "needs_answers"
    unknown = client.post(f"/projects/{pid}/answers", json={"answers": {"q9": 1}})
    assert unknown.status_code == 409 and "q9" in unknown.json()["detail"]
    assert client.get(f"/projects/{pid}/files/../service.json").status_code == 404


def test_model_errors_need_model(client: TestClient) -> None:
    pid = _create(client)
    room = ROOM["rooms"][0]
    broken = {**ROOM, "rooms": [{**room, "walls": room["walls"][:3]}]}  # outline not closed
    _put(client, pid, "room.yaml", broken)
    client.post(f"/projects/{pid}/analyze")
    info = _state(client, pid)
    assert info["state"] == "needs_model" and "ошибки" in info["message"]
    assert "project.dxf" not in info["files"]


def test_critical_without_geometry_is_insufficient_after_rounds(client: TestClient) -> None:
    pid = _create(client)
    _put(client, pid, "intake.yaml", {"questions": [_q("q1", severity="critical", answer="text")]})
    client.post(f"/projects/{pid}/analyze")
    info = _state(client, pid)
    assert info["state"] == "needs_answers"
    assert info["stages"][0]["status"] == "insufficient"
    # A text answer goes to the analyzer; the manual analyzer waits for the operator
    client.post(f"/projects/{pid}/answers", json={"answers": {"q1": {"text": "размеров нет"}}})
    info = _state(client, pid)
    assert info["state"] == "needs_model" and "q1" in info["message"]


def test_rounds_are_limited(client: TestClient) -> None:
    pid = _create(client)
    _put(client, pid, "room.yaml", ROOM)
    questions = [_q(f"q{k}", answer="text", severity="minor") for k in range(1, 6)]
    _put(client, pid, "intake.yaml", {"questions": questions})
    client.post(f"/projects/{pid}/analyze")
    for k in (1, 2, 3):
        assert _state(client, pid)["state"] == "needs_answers"
        client.post(f"/projects/{pid}/answers", json={"answers": {f"q{k}": {"accept": True}}})
    info = _state(client, pid)
    # After 3 rounds: a build on assumptions, remaining questions in the report
    assert info["state"] == "ready" and "допущениям" in info["message"], info
    assert info["stages"][0]["open_questions"] == 2


def test_busy_project_rejects_reads_of_report(client: TestClient, tmp_path: Path) -> None:
    pid = _create(client)
    state = tmp_path / "data" / pid / "service.json"
    data = json.loads(state.read_text("utf-8"))
    state.write_text(json.dumps({**data, "state": "building"}), "utf-8")
    for url in (f"/projects/{pid}/questions", f"/projects/{pid}/report"):
        response = client.get(url)
        assert response.status_code == 409 and "занят" in response.json()["detail"]
    assert client.post(f"/projects/{pid}/analyze").status_code == 409
    assert client.delete(f"/projects/{pid}").status_code == 409


def test_model_and_sources(client: TestClient) -> None:
    pid = _create(client)
    source = client.get(f"/projects/{pid}/sources/plan.pdf")
    assert source.status_code == 200 and source.content == b"%PDF-1.4 test"
    assert client.get(f"/projects/{pid}/sources/../service.json").status_code == 404

    assert client.get(f"/projects/{pid}/model/room.yaml").status_code == 404
    assert client.get(f"/projects/{pid}/model/service.json").status_code == 400
    _put(client, pid, "room.yaml", ROOM)
    model = client.get(f"/projects/{pid}/model/room.yaml")
    assert model.status_code == 200 and yaml.safe_load(model.text) == ROOM


def test_model_uploaded_with_sources(client: TestClient) -> None:
    room = yaml.safe_dump(ROOM, allow_unicode=True).encode()
    intake = yaml.safe_dump({"questions": [_q("q1", answer="text", severity="minor")]}).encode()
    response = client.post(
        "/projects",
        data={"name": "Эталон"},
        files=[
            ("files", ("plan.pdf", b"%PDF-1.4 test", "application/pdf")),
            ("files", ("room.yaml", room, "text/yaml")),
            ("files", ("intake.yaml", intake, "text/yaml")),
            ("files", ("answers.yaml", b"answers:\n  q1: {accept: true}\n", "text/yaml")),
        ],
    )
    info = response.json()
    assert info["sources"] == ["source/plan.pdf"]
    pid = info["id"]
    assert "accept" in client.get(f"/projects/{pid}/model/answers.yaml").text
    client.post(f"/projects/{pid}/analyze")
    # The answer from answers.yaml is already applied: no open questions
    assert _state(client, pid)["state"] == "ready"


def test_delete_project(client: TestClient, tmp_path: Path) -> None:
    pid = _create(client)
    assert client.delete(f"/projects/{pid}").status_code == 204
    assert not (tmp_path / "data" / pid).exists()
    assert client.get(f"/projects/{pid}").status_code == 404
    assert client.delete(f"/projects/{pid}").status_code == 404
    assert client.get("/projects").json() == []


def test_restart_resumes_cut_off_work(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "data")
    info = storage.create("Кухня", [("plan.pdf", b"%PDF-1.4 test")])
    info.state, info.task = ProjectState.ANALYZING, PendingTask(kind="analysis")
    storage.save(info)
    app = create_app(tmp_path / "data", workers=1)
    with TestClient(app):
        app.state.tasks.join()
    resumed = storage.load(info.id)
    assert resumed.state is ProjectState.NEEDS_MODEL  # the manual analyzer has no model to give
    assert resumed.task is None
