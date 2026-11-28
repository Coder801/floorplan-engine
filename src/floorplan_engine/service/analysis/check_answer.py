"""The answer check (docs/question-threads.md, «Проверка ответа ИИ»): the studio accepted a message
of a question thread as the answer; the model decides whether it answers the question and, if it
does, patches the stage YAML by it. The rules are in analyzer_prompt.md, «Проверка ответа».

No database here: the service (service/answer_check.py) gathers the input (CheckInput), this
module makes the prompt, parses the envelope (parse_verdict) and makes the backends — the same
ones as the analyzer (llm_analyzer: `claude -p` by subscription or the API by key), with their own
JSON schema and without the sources. The core checks what comes back, as after a round.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from floorplan_engine.model.furniture import FURNITURE_FILE
from floorplan_engine.model.plumbing import PLUMBING_FILE
from floorplan_engine.service.analysis.llm_analyzer import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    ApiBackend,
    Backend,
    ClaudeCodeBackend,
)
from floorplan_engine.validation.issues import ELECTRICAL_FILE, ROOM_FILE

TASK = "Проверка ответа"  # the first words of the prompt: the section of the rules
VERDICTS = ("satisfied", "unsatisfied")
AUDIENCES = ("studio", "client", "installer")
SEVERITIES = ("critical", "major", "minor")
STAGES = ("plan", "electrical", "furniture", "lighting", "power", "wiring", "plumbing")
CHECK_FILES = (ROOM_FILE, ELECTRICAL_FILE, PLUMBING_FILE, FURNITURE_FILE)
# The model files shown for a question of a stage and written by its answer; room.yaml is the
# ground every stage refers to
STAGE_FILES: dict[str, tuple[str, ...]] = {
    "plan": (ROOM_FILE,),
    "electrical": (ROOM_FILE, ELECTRICAL_FILE),
    "lighting": (ROOM_FILE, ELECTRICAL_FILE),
    "power": (ROOM_FILE, ELECTRICAL_FILE),
    "wiring": (ROOM_FILE, ELECTRICAL_FILE),
    "panel": (ROOM_FILE, ELECTRICAL_FILE),
    "furniture": (ROOM_FILE, FURNITURE_FILE),
    "plumbing": (ROOM_FILE, PLUMBING_FILE),
}

_FOLLOWUP: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "audience": {"type": "string", "enum": list(AUDIENCES)},
        "severity": {"type": "string", "enum": list(SEVERITIES)},
        "stage": {"type": "string", "enum": list(STAGES)},
    },
    "required": ["text"],
    "additionalProperties": False,
}
CHECK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "reason": {"type": "string"},
        "changes": {"type": "array", "items": {"type": "string"}},
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": list(CHECK_FILES)},
                    "content": {"type": "string"},
                },
                "required": ["name", "content"],
                "additionalProperties": False,
            },
        },
        "followup": {"anyOf": [{"type": "null"}, _FOLLOWUP]},
    },
    "required": ["verdict", "reason", "changes", "files", "followup"],
    "additionalProperties": False,
}


class CheckError(ValueError):
    """The model's answer cannot be used: the message is for the thread, in Russian."""


@dataclass(frozen=True)
class Said:
    """A message of the thread as the model sees it."""

    author: str  # user | analyzer | system
    role: str  # the author's project role, "" — not known
    label: str
    text: str
    accepted: bool = False


@dataclass(frozen=True)
class Earlier:
    """An unresolved thread before this one: its question and the answer accepted there."""

    question: str
    answer: str


@dataclass(frozen=True)
class CheckInput:
    qid: str
    stage: str | None
    audience: str
    text: str
    target: str | None
    assumption: Any
    messages: list[Said]
    accepted: str
    earlier: list[Earlier] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)  # the stage's model files (STAGE_FILES)
    errors: list[str] = field(default_factory=list)  # the check of the current model

    @property
    def writable(self) -> tuple[str, ...]:
        return stage_files(self.stage)


@dataclass(frozen=True)
class Followup:
    text: str
    audience: str | None = None
    severity: str | None = None
    stage: str | None = None


@dataclass(frozen=True)
class Verdict:
    satisfied: bool
    reason: str
    changes: list[str]
    files: dict[str, str]
    followup: Followup | None = None


def stage_files(stage: str | None) -> tuple[str, ...]:
    return STAGE_FILES.get(stage or "", CHECK_FILES)


def _who(m: Said) -> str:
    if m.author == "analyzer":
        return "ИИ"
    if m.author == "system":
        return "система"
    who = ", ".join(x for x in (m.label, m.role) if x)
    return who or "участник"


def check_prompt(inp: CheckInput) -> str:
    """The first message of a check: the question, the thread, the accepted answer, the earlier
    threads of the chain, the stage's model and its errors."""
    question = [f"id: {inp.qid}", f"этап: {inp.stage or '—'}", f"адресат: {inp.audience}"]
    question.append(f"текст: {inp.text}")
    if inp.target:
        question.append(f"target: {inp.target}")
    if inp.assumption is not None:
        question.append(f"assumption: {inp.assumption}")
    parts = [f"{TASK}.", "Вопрос:\n" + "\n".join(question)]
    if inp.earlier:
        lines = [f"- вопрос: {e.question}\n  принятый ответ: {e.answer}" for e in inp.earlier]
        parts.append("Предыдущие треды цепочки (ответ не закрыл вопрос):\n" + "\n".join(lines))
    said = [
        f"- [{_who(m)}]{' (принято студией)' if m.accepted else ''}: {m.text}" for m in inp.messages
    ]
    parts.append("Сообщения треда, по порядку:\n" + ("\n".join(said) or "- нет"))
    parts.append(f"Принятый ответ:\n{inp.accepted}")
    parts.append(f"Файлы, которые можно менять: {', '.join(inp.writable)}.")
    if inp.files:
        parts.append("Текущая модель:")
        parts += [f"--- {name}\n{text}" for name, text in inp.files.items()]
    else:
        parts.append("Файлов этапа в модели нет.")
    if inp.errors:
        parts.append("Ошибки проверки текущей модели (до ответа):\n" + "\n".join(inp.errors))
    return "\n\n".join(parts)


def retry_prompt(problems: list[str]) -> str:
    return (
        "Проверка модели с твоими файлами нашла новые ошибки. Исправь их и верни ответ целиком "
        "(те же поля, файлы — полностью):\n" + "\n".join(f"- {p}" for p in problems)
    )


def _envelope(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CheckError("ответ ИИ — не JSON") from exc
    if not isinstance(raw, dict):
        raise CheckError("ответ ИИ — не объект JSON")
    return raw


def _choice(value: Any, allowed: tuple[str, ...]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _followup(raw: Any) -> Followup | None:
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or "").strip()
    if not text:
        return None
    return Followup(
        text,
        _choice(raw.get("audience"), AUDIENCES),
        _choice(raw.get("severity"), SEVERITIES),
        _choice(raw.get("stage"), STAGES),
    )


def parse_verdict(raw: Any) -> Verdict:
    """The check envelope: a verdict, why, what changed and the files; an unsatisfied verdict needs
    a follow-up question. An unknown audience, severity or stage of the follow-up is dropped (the
    old question's is taken); a file outside CHECK_FILES makes the answer unusable."""
    data = _envelope(raw)
    verdict = data.get("verdict")
    if verdict not in VERDICTS:
        raise CheckError(f"ответ ИИ: verdict — {' | '.join(VERDICTS)}, а не {verdict!r}")
    files: dict[str, str] = {}
    for f in data.get("files") or []:
        if not isinstance(f, dict) or not isinstance(f.get("content"), str):
            raise CheckError("ответ ИИ: в files нужны name и content")
        name = f.get("name")
        if name not in CHECK_FILES:
            raise CheckError(f"ответ ИИ: файл {name!r} в проверке ответа не пишется")
        files[str(name)] = f["content"]
    changes = [str(c) for c in data.get("changes") or [] if str(c).strip()]
    followup = _followup(data.get("followup"))
    satisfied = verdict == "satisfied"
    if not satisfied and followup is None:
        raise CheckError("ответ ИИ: не закрывает вопрос, но нового вопроса (followup) нет")
    return Verdict(
        satisfied,
        str(data.get("reason") or "").strip(),
        changes if satisfied else [],
        files if satisfied else {},
        None if satisfied else followup,
    )


def make_check_backend(
    kind: str, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT
) -> Callable[[], Backend]:
    """A new backend for every check (it holds the conversation): claude-code — subscription,
    api — key. No sources: the thread and the model are the whole input."""
    if kind == "claude-code":
        return lambda: ClaudeCodeBackend(
            model=model, effort=effort, max_budget_usd=2.0, schema=CHECK_SCHEMA, sources=False
        )
    if kind == "api":
        return lambda: ApiBackend(
            model=model, effort=effort, max_tokens=32000, schema=CHECK_SCHEMA, sources=False
        )
    raise ValueError(f"проверка ответа: claude-code | api, а не {kind}")
