from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from floorplan_engine.service.analysis import llm_analyzer
from floorplan_engine.service.analysis.llm_analyzer import (
    FIX_ATTEMPTS,
    USAGE_FILE,
    ApiBackend,
    ClaudeCodeBackend,
    LlmAnalyzer,
    Reply,
    Usage,
)
from floorplan_engine.validation.validate import validate_project

ROOM: dict[str, Any] = {
    "name": "Тест",
    "default_wall_thickness": 120,
    "source": "photo",
    "rooms": [
        {
            "id": "r",
            "name": "Комната",
            "walls": [{"id": f"w{k}", "length": n} for k, n in enumerate([3000, 4000] * 2, 1)],
        }
    ],
}
BROKEN = {**ROOM, "rooms": [{**ROOM["rooms"][0], "walls": ROOM["rooms"][0]["walls"][:3]}]}
INTAKE = {"sources": [{"file": "source/plan.pdf"}], "questions": []}


def _envelope(
    room: dict[str, Any] | None,
    resolved: list[str] | None = None,
    intake: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = yaml.safe_dump(intake or INTAKE, allow_unicode=True)
    files = [{"name": "intake.yaml", "content": text}]
    if room is not None:
        files.append({"name": "room.yaml", "content": yaml.safe_dump(room, allow_unicode=True)})
    return {"files": files, "resolved": resolved or [], "summary": "готово"}


@dataclass
class FakeBackend:
    replies: list[dict[str, Any]]
    name: str = "fake"
    prompts: list[str] = field(default_factory=list)

    def _next(self, prompt: str) -> Reply:
        self.prompts.append(prompt)
        usage = Usage("claude-opus-5-5", input_tokens=1_000_000, output_tokens=100_000).priced()
        return Reply(self.replies.pop(0), usage)

    def start(self, project: Path, prompt: str) -> Reply:
        return self._next(prompt)

    def follow_up(self, project: Path, prompt: str) -> Reply:
        return self._next(prompt)


def _project(tmp_path: Path) -> Path:
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "plan.pdf").write_bytes(b"%PDF-1.4")
    return tmp_path


def test_valid_model_in_one_call(tmp_path: Path) -> None:
    project = _project(tmp_path)
    backend = FakeBackend([_envelope(ROOM)])
    result = LlmAnalyzer(lambda: backend).analyze(project, 1)
    assert result.done and result.calls == 1
    assert result.cost_usd == pytest.approx(4.0 + 2.0)  # 1M input × $4 + 0.1M output × $20
    assert (project / "room.yaml").exists() and (project / "intake.yaml").exists()
    assert "Модели ещё нет" in backend.prompts[0]
    (record,) = [json.loads(line) for line in (project / USAGE_FILE).read_text().splitlines()]
    assert record["round"] == 1 and record["model"] == "claude-opus-5-5"


def test_validation_errors_go_back_to_model(tmp_path: Path) -> None:
    project = _project(tmp_path)
    backend = FakeBackend([_envelope(BROKEN), _envelope(ROOM)])
    result = LlmAnalyzer(lambda: backend).analyze(project, 1)
    assert result.calls == 2
    assert "не замыкается" in backend.prompts[1] or "turn" in backend.prompts[1]


def test_fix_attempts_are_limited(tmp_path: Path) -> None:
    project = _project(tmp_path)
    backend = FakeBackend([_envelope(BROKEN)] * (FIX_ATTEMPTS + 1))
    result = LlmAnalyzer(lambda: backend).analyze(project, 1)
    assert result.calls == FIX_ATTEMPTS + 1 and not backend.replies


def test_electrical_is_a_separate_step(tmp_path: Path) -> None:
    project = _project(tmp_path)
    electrical = {
        "points": [
            {
                "id": "r_socket_1",
                "room": "r",
                "wall": "w2",
                "offset": 500,
                "type": "socket",
                "height": 300,
            }
        ]
    }
    plan_reply = _envelope(ROOM)
    plan_reply["files"].append({"name": "electrical.yaml", "content": "мусор: ["})
    elec_reply = _envelope(None)
    elec_reply["files"].append({"name": "room.yaml", "content": "мусор: ["})
    elec_reply["files"].append({"name": "electrical.yaml", "content": yaml.safe_dump(electrical)})
    plan, elec = FakeBackend([plan_reply]), FakeBackend([elec_reply])
    result = LlmAnalyzer(lambda: plan, lambda: elec).analyze(project, 1)
    assert result.calls == 2
    assert "только план" in plan.prompts[0] and "электрика и сантехника" in elec.prompts[0]
    assert "--- room.yaml" in elec.prompts[0]  # electrical sees the finished plan
    # Each step writes only its own files
    assert yaml.safe_load((project / "room.yaml").read_text("utf-8")) == ROOM
    assert "r_socket_1" in (project / "electrical.yaml").read_text("utf-8")


def test_no_plan_no_electrical_step(tmp_path: Path) -> None:
    project = _project(tmp_path)
    plan, elec = FakeBackend([_envelope(None)]), FakeBackend([])
    result = LlmAnalyzer(lambda: plan, lambda: elec).analyze(project, 1)
    assert result.calls == 1 and not elec.prompts


def test_text_answers_are_offered_and_resolved(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "room.yaml").write_text(yaml.safe_dump(ROOM, allow_unicode=True), "utf-8")
    intake = {"questions": [{"id": "q1", "stage": "plan", "text": "?", "severity": "minor"}]}
    (project / "intake.yaml").write_text(yaml.safe_dump(intake, allow_unicode=True), "utf-8")
    (project / "answers.yaml").write_text("answers:\n  q1: { text: обмера нет }\n", "utf-8")
    backend = FakeBackend([_envelope(ROOM, resolved=["q1"], intake=intake)])
    LlmAnalyzer(lambda: backend).analyze(project, 2)
    assert "q1: обмера нет" in backend.prompts[0] and "Текущая модель" in backend.prompts[0]
    answers = yaml.safe_load((project / "answers.yaml").read_text("utf-8"))
    assert answers["answers"]["q1"] == {"text": "обмера нет", "resolved": True}


def test_api_source_blocks(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "source" / "photo.JPG").write_bytes(b"\xff\xd8jpeg")
    (project / "source" / "plan.dwg").write_bytes(b"AC1032")
    blocks = ApiBackend.source_blocks(project)
    kinds = [b["type"] for b in blocks]
    # By name: photo.JPG, plan.dwg (explained in text), plan.pdf and its digest
    assert kinds == ["text", "image", "text", "text", "document", "text"]
    assert blocks[1]["source"]["media_type"] == "image/jpeg"
    assert "plan.dwg не читается: чтение DWG и DXF в разработке" in blocks[2]["text"]
    assert "Выжимка из source/plan.pdf" in blocks[5]["text"]
    assert "PDF не разобран" in blocks[5]["text"]  # not a real PDF in the test


def test_api_rejects_oversized_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(tmp_path)
    monkeypatch.setattr(llm_analyzer, "MAX_REQUEST_BYTES", 4)
    with pytest.raises(llm_analyzer.AnalyzerError, match="источники больше"):
        ApiBackend.source_blocks(project)


def test_claude_code_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(tmp_path)
    calls: list[dict[str, Any]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"cmd": cmd, **kwargs})
        out = {
            "structured_output": _envelope(ROOM),
            "session_id": "s-1",
            # Claude Code returns the running session total: 0.42, then 0.60
            "total_cost_usd": 0.42 if len(calls) == 1 else 0.60,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr("shutil.which", lambda _: "/bin/claude")
    monkeypatch.setattr("subprocess.run", fake_run)
    backend = ClaudeCodeBackend()
    reply = backend.start(project, "контекст")
    assert reply.usage.cost_usd == 0.42 and reply.envelope["summary"] == "готово"
    again = backend.follow_up(project, "исправь")
    assert again.usage.cost_usd == pytest.approx(0.18)  # the call price, not the session total
    first, second = calls
    cmd = first["cmd"]
    assert cmd[:2] == ["/bin/claude", "-p"] and "source/plan.pdf" in cmd[2]
    assert "Выжимка из source/plan.pdf" in cmd[2]
    assert json.loads(cmd[cmd.index("--json-schema") + 1])["required"] == [
        "files",
        "resolved",
        "summary",
    ]
    assert cmd[cmd.index("--allowedTools") + 1] == "Read"
    assert "ANTHROPIC_API_KEY" not in first["env"]  # the subscription is used, not the key
    assert first["cwd"] == project
    assert second["cmd"][-2:] == ["--resume", "s-1"]


def test_claude_code_error_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        out = {"is_error": True, "result": "Not logged in"}
        return subprocess.CompletedProcess(cmd, 1, json.dumps(out), "")

    monkeypatch.setattr("shutil.which", lambda _: "/bin/claude")
    monkeypatch.setattr("subprocess.run", fake_run)
    with pytest.raises(llm_analyzer.AnalyzerError, match="Not logged in"):
        ClaudeCodeBackend().start(_project(tmp_path), "x")


def test_service_accumulates_llm_cost(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from floorplan_engine.service.api.app import create_app

    backend = FakeBackend([_envelope(ROOM)])
    client = TestClient(create_app(tmp_path / "data", LlmAnalyzer(lambda: backend), workers=0))
    pid = client.post(
        "/projects",
        data={"name": "x"},
        files=[("files", ("notes.md", "Кімната 3000 × 4000".encode(), "text/markdown"))],
    ).json()["id"]
    client.post(f"/projects/{pid}/analyze")
    info = client.get(f"/projects/{pid}").json()
    assert info["state"] == "ready", info
    assert info["llm_calls"] == 1 and info["llm_cost_usd"] == pytest.approx(6.0)


def test_unusable_sources_rejected_before_llm(tmp_path: Path) -> None:
    """The "failed" gate: nothing can be built from the source, so the model is not called."""
    from fastapi.testclient import TestClient

    from floorplan_engine.service.api.app import create_app

    backend = FakeBackend([_envelope(ROOM)])
    client = TestClient(create_app(tmp_path / "data", LlmAnalyzer(lambda: backend), workers=0))
    pid = client.post(
        "/projects",
        data={"name": "x"},
        files=[("files", ("plan.pdf", b"%PDF", "application/pdf"))],  # broken PDF
    ).json()["id"]
    client.post(f"/projects/{pid}/analyze")
    info = client.get(f"/projects/{pid}").json()
    assert info["state"] == "rejected" and info["llm_calls"] == 0
    assert "plan.pdf — не открывается" in info["message"] and "300 dpi" in info["message"]


def test_targeted_analysis_writes_only_furniture_and_the_heating_section(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    (project / "room.yaml").write_text(yaml.safe_dump(ROOM, allow_unicode=True), "utf-8")
    elec_text = (
        "mode: standard  # режим\n"
        "points:\n"
        "  - { id: t1, room: r, type: thermostat, wall: w2, offset: 500, height: 900 }  # А-29\n"
        "floor_heating: []\n"
    )
    (project / "electrical.yaml").write_text(elec_text, "utf-8")
    intake = yaml.safe_dump(INTAKE, allow_unicode=True)
    (project / "intake.yaml").write_text(intake, "utf-8")
    furniture = {
        "items": [{"id": "k", "room": "r", "kind": "kitchen", "at": [0, 0], "size": [600, 3000]}]
    }
    bad_zone = "floor_heating:\n  - { id: fh, room: nope, thermostat: t1 }\n"
    good_zone = "floor_heating:  # S=9,5\n  - { id: fh, room: r, thermostat: t1, area: 9.5 }\n"

    def reply(zone: str) -> dict[str, Any]:
        files = [
            {"name": "furniture.yaml", "content": yaml.safe_dump(furniture)},
            {"name": "floor_heating.yaml", "content": zone},
            {"name": "room.yaml", "content": "мусор: ["},  # not this step's file
            {"name": "intake.yaml", "content": "мусор: ["},
        ]
        return {"files": files, "resolved": [], "summary": "мебель и тёплый пол"}

    backend = FakeBackend([reply(bad_zone), reply(good_zone)])
    analyzer = LlmAnalyzer(lambda: backend, stages=("furniture", "floor_heating"))
    result = analyzer.analyze(project, 2)
    assert result.calls == 2 and "Точечный разбор" in backend.prompts[0]
    assert "floor_heating[0].room" in backend.prompts[1]  # the error went back to the model
    assert yaml.safe_load((project / "room.yaml").read_text("utf-8")) == ROOM
    assert (project / "intake.yaml").read_text("utf-8") == intake
    assert yaml.safe_load((project / "furniture.yaml").read_text("utf-8")) == furniture
    text = (project / "electrical.yaml").read_text("utf-8")
    assert text.startswith(elec_text.split("floor_heating")[0])  # the rest and its comments
    assert "# S=9,5" in text and yaml.safe_load(text)["floor_heating"][0]["area"] == 9.5


def test_targeted_analysis_needs_a_model_and_known_stages(tmp_path: Path) -> None:
    project = _project(tmp_path)
    with pytest.raises(llm_analyzer.AnalyzerError, match=r"room\.yaml"):
        LlmAnalyzer(lambda: FakeBackend([]), stages=("furniture",)).analyze(project, 1)
    with pytest.raises(ValueError, match="furniture, floor_heating"):
        llm_analyzer.make_analyzer("api", stages=("plan",))
    with pytest.raises(ValueError, match="LLM"):
        llm_analyzer.make_analyzer("manual", stages=("furniture",))
    made = llm_analyzer.make_analyzer("api", stages=("floor_heating", "floor_heating"))
    assert isinstance(made, LlmAnalyzer) and made.stages == ("floor_heating",)
    (step,) = made.steps()
    assert step.files == ("floor_heating.yaml",) and not step.needs_intake


def _targeted_project(tmp_path: Path, elec_text: str) -> Path:
    project = _project(tmp_path)
    (project / "room.yaml").write_text(yaml.safe_dump(ROOM, allow_unicode=True), "utf-8")
    (project / "electrical.yaml").write_text(elec_text, "utf-8")
    (project / "intake.yaml").write_text(yaml.safe_dump(INTAKE, allow_unicode=True), "utf-8")
    return project


REG_LINE = "  - { id: t1, room: r, type: thermostat, wall: w2, offset: 500, height: 900 }\n"
GOOD_ZONE = "floor_heating:\n  - { id: fh, room: r, thermostat: t1 }\n"


def test_targeted_step_leaves_text_answers_alone(tmp_path: Path) -> None:
    project = _targeted_project(tmp_path, f"points:\n{REG_LINE}floor_heating: []\n")
    answers = "answers:\n  q1: { text: розетку у окна перенести }\n"
    (project / "answers.yaml").write_text(answers, "utf-8")
    reply = {
        "files": [{"name": "floor_heating.yaml", "content": GOOD_ZONE}],
        "resolved": ["q1"],  # the step must not take it: its electrical.yaml edits are dropped
        "summary": "тёплый пол",
    }
    backend = FakeBackend([reply])
    LlmAnalyzer(lambda: backend, stages=("floor_heating",)).analyze(project, 2)
    assert "розетку у окна" not in backend.prompts[0]
    assert (project / "answers.yaml").read_text("utf-8") == answers


def test_targeted_step_sees_and_counts_only_its_own_errors(tmp_path: Path) -> None:
    # heating_rooms is not the step's: the error stays, but it is not sent and spends no attempt
    elec = f"points:\n{REG_LINE}floor_heating: []\nheating_rooms: {{ x: r }}\n"
    project = _targeted_project(tmp_path, elec)
    reply = {
        "files": [{"name": "floor_heating.yaml", "content": GOOD_ZONE}],
        "resolved": [],
        "summary": "тёплый пол",
    }
    backend = FakeBackend([reply])
    result = LlmAnalyzer(lambda: backend, stages=("floor_heating",)).analyze(project, 2)
    assert result.calls == 1
    assert "heating_rooms" not in backend.prompts[0].split("Текущая модель:")[0]
    assert "Ошибки проверки" not in backend.prompts[0]
    errors = validate_project(project).errors
    assert [e.path for e in errors] == ["heating_rooms.x"]
    assert llm_analyzer.step_errors(errors, ("floor_heating.yaml",)) == []
    assert llm_analyzer.step_errors(errors, ("electrical.yaml",)) == errors


def test_targeted_floor_heating_needs_electrical(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "room.yaml").write_text(yaml.safe_dump(ROOM, allow_unicode=True), "utf-8")
    backend = FakeBackend([])
    analyzer = LlmAnalyzer(lambda: backend, stages=("floor_heating",))
    with pytest.raises(llm_analyzer.AnalyzerError, match=r"electrical\.yaml нет"):
        analyzer.analyze(project, 2)
    assert not backend.prompts and not (project / "electrical.yaml").exists()
