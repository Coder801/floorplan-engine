"""The answer check step (service/analysis/check_answer.py): the prompt holds the question, the
thread, the chain and the stage's model; the envelope is parsed strictly where a mistake would
write the model and leniently where a default exists; the backends are the analyzer's, with the
check's schema and without the sources. No tokens: the CLI is faked."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from floorplan_engine.service.analysis import check_answer as ca
from floorplan_engine.service.analysis.llm_analyzer import ApiBackend, Reply, Usage


def _input(**over: Any) -> ca.CheckInput:
    data: dict[str, Any] = {
        "qid": "q7",
        "stage": "plan",
        "audience": "client",
        "text": "Ширина проёма в кухню?",
        "target": None,
        "assumption": None,
        "messages": [
            ca.Said("user", "client_code", "код: Иван", "как на кухне", accepted=True),
            ca.Said("analyzer", "", "", "уточните"),
        ],
        "accepted": "как на кухне",
        "files": {"room.yaml": "name: Кв\n"},
    }
    return ca.CheckInput(**{**data, **over})


def test_prompt_holds_the_question_thread_and_model() -> None:
    earlier = [ca.Earlier("Где кухня?", "справа")]
    errors = ["[error] room.yaml: rooms: пусто"]
    prompt = ca.check_prompt(_input(earlier=earlier, errors=errors, target="a.b", assumption=900))
    assert prompt.startswith("Проверка ответа.")
    assert "адресат: client" in prompt and "target: a.b" in prompt and "assumption: 900" in prompt
    assert "- [код: Иван, client_code] (принято студией): как на кухне" in prompt
    assert "- [ИИ]: уточните" in prompt
    assert "принятый ответ: справа" in prompt
    assert "Файлы, которые можно менять: room.yaml." in prompt
    assert "--- room.yaml\nname: Кв\n" in prompt and "rooms: пусто" in prompt
    bare = ca.check_prompt(_input(files={}, messages=[], stage=None))
    assert "Файлов этапа в модели нет." in bare and "- нет" in bare
    assert "electrical.yaml" in bare  # no stage: every model file may change
    assert "новые ошибки" in ca.retry_prompt(["x"])


def test_stage_files() -> None:
    assert ca.stage_files("plan") == ("room.yaml",)
    assert ca.stage_files("wiring") == ("room.yaml", "electrical.yaml")
    assert ca.stage_files("plumbing") == ("room.yaml", "plumbing.yaml")
    assert ca.stage_files(None) == ca.CHECK_FILES
    assert _input(stage="furniture").writable == ("room.yaml", "furniture.yaml")


def test_satisfied_envelope() -> None:
    v = ca.parse_verdict(
        json.dumps(
            {
                "verdict": "satisfied",
                "reason": " даёт ширину ",
                "changes": ["room.yaml: w2 4000 → 4100", " "],
                "files": [{"name": "room.yaml", "content": "x: 1\n"}],
                "followup": {"text": "лишнее"},
            }
        )
    )
    assert v == ca.Verdict(
        True, "даёт ширину", ["room.yaml: w2 4000 → 4100"], {"room.yaml": "x: 1\n"}
    )


def test_unsatisfied_envelope() -> None:
    v = ca.parse_verdict(
        {
            "verdict": "unsatisfied",
            "reason": "нет размера",
            "changes": ["игнорируется"],
            "files": [{"name": "room.yaml", "content": "x"}],
            "followup": {"text": " Ширина, мм? ", "audience": "boss", "severity": "major"},
        }
    )
    # Nothing is written by an unsatisfied verdict; an unknown audience falls back to the old one
    assert (v.satisfied, v.changes, v.files) == (False, [], {})
    assert v.followup == ca.Followup("Ширина, мм?", None, "major", None)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("не json", "не JSON"),
        ([], "не объект"),
        ({"verdict": "maybe"}, "verdict"),
        ({"verdict": "satisfied", "files": [{"name": "room.yaml"}]}, "name и content"),
        (
            {"verdict": "satisfied", "files": [{"name": "intake.yaml", "content": ""}]},
            "не пишется",
        ),
        ({"verdict": "unsatisfied", "followup": None}, "followup"),
        ({"verdict": "unsatisfied", "followup": {"text": "  "}}, "followup"),
    ],
)
def test_unusable_envelopes(raw: Any, message: str) -> None:
    with pytest.raises(ca.CheckError, match=message):
        ca.parse_verdict(raw)


def test_claude_code_backend_for_the_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "plan.pdf").write_bytes(b"%PDF-1")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        out = {"structured_output": {"verdict": "satisfied"}, "session_id": "s", "usage": {}}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")

    monkeypatch.setattr("shutil.which", lambda _: "/bin/claude")
    monkeypatch.setattr("subprocess.run", fake_run)
    backend = ca.make_check_backend("claude-code")()
    backend.start(tmp_path, "Проверка ответа.")
    cmd = calls[0]
    assert cmd[2] == "Проверка ответа."  # no sources listed
    schema = json.loads(cmd[cmd.index("--json-schema") + 1])
    assert schema["required"] == ["verdict", "reason", "changes", "files", "followup"]
    with pytest.raises(ValueError, match="а не manual"):
        ca.make_check_backend("manual")


def test_api_backend_for_the_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "plan.pdf").write_bytes(b"%PDF-1")
    backend = ca.make_check_backend("api")()
    assert isinstance(backend, ApiBackend) and backend.schema is ca.CHECK_SCHEMA
    sent: list[Any] = []

    def call(self: ApiBackend) -> Reply:
        sent.append(list(self._messages))
        return Reply({}, Usage("m"))

    monkeypatch.setattr(ApiBackend, "_call", call)
    backend.start(tmp_path, "Проверка ответа.")
    assert sent[0][0]["content"] == [{"type": "text", "text": "Проверка ответа."}]
