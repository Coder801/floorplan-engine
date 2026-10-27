from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from shtroba.service import llm_analyzer
from shtroba.service.llm_analyzer import (
    FIX_ATTEMPTS,
    USAGE_FILE,
    ApiBackend,
    ClaudeCodeBackend,
    LlmAnalyzer,
    Reply,
    Usage,
)

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
    assert result.cost_usd == pytest.approx(4.0 + 2.0)  # 1M ввода × $4 + 0,1M вывода × $20
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
    assert "только план" in plan.prompts[0] and "только электрика" in elec.prompts[0]
    assert "--- room.yaml" in elec.prompts[0]  # электрика видит готовый план
    # Каждый шаг пишет только свои файлы
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
    # По имени: photo.JPG, plan.dwg (пояснение текстом), plan.pdf и выжимка из него
    assert kinds == ["text", "image", "text", "text", "document", "text"]
    assert blocks[1]["source"]["media_type"] == "image/jpeg"
    assert "plan.dwg не читается" in blocks[2]["text"]
    assert "Выжимка из source/plan.pdf" in blocks[5]["text"]
    assert "PDF не разобран" in blocks[5]["text"]  # в тесте не настоящий PDF


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
            # Claude Code отдаёт нарастающий итог сессии: 0.42, затем 0.60
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
    assert again.usage.cost_usd == pytest.approx(0.18)  # цена вызова, а не итог сессии
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
    assert "ANTHROPIC_API_KEY" not in first["env"]  # работает подписка, а не ключ
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

    from shtroba.service.app import create_app

    backend = FakeBackend([_envelope(ROOM)])
    client = TestClient(create_app(tmp_path / "data", LlmAnalyzer(lambda: backend)))
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
    """Порог «не удалось»: по источнику ничего не построить — модель не вызывается."""
    from fastapi.testclient import TestClient

    from shtroba.service.app import create_app

    backend = FakeBackend([_envelope(ROOM)])
    client = TestClient(create_app(tmp_path / "data", LlmAnalyzer(lambda: backend)))
    pid = client.post(
        "/projects",
        data={"name": "x"},
        files=[("files", ("plan.pdf", b"%PDF", "application/pdf"))],  # битый PDF
    ).json()["id"]
    client.post(f"/projects/{pid}/analyze")
    info = client.get(f"/projects/{pid}").json()
    assert info["state"] == "rejected" and info["llm_calls"] == 0
    assert "plan.pdf — не открывается" in info["message"] and "300 dpi" in info["message"]
