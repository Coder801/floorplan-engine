"""LLM analyzer: project sources → intake.yaml and stage YAML through Claude.

Two backends behind one interface:

- `ClaudeCodeBackend`: `claude -p` on a Claude subscription (development, tests). The model
  reads the sources itself with the Read tool from the project folder.
- `ApiBackend`: the Anthropic API with a key (`ANTHROPIC_API_KEY`), for the product. Sources
  are sent in the request as documents (PDF) and images.

Both backends attach the `pdf_facts` digest to every PDF: scale, dimensions, chains and labels
with coordinates. Code computes it, the model is left with the meaning.

Analysis runs in one step or two: the plan, then electrical with another (cheaper) model; the
second step gets the finished room.yaml and writes only electrical.yaml and its stage questions.

The model answers with an envelope (structured output): full texts of the model files, ids of
handled text answers and a short summary. The core validates the YAML; validation errors go
back to the model in the same conversation, at most FIX_ATTEMPTS times. Every call is logged
in the project's usage.jsonl: tokens, cost, duration.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

import yaml

if TYPE_CHECKING:
    from anthropic.types.beta import BetaOutputConfigParam

from floorplan_engine.model.intake import ANSWERS_FILE, INTAKE_FILE, Answers, TextAnswer
from floorplan_engine.model.plumbing import PLUMBING_FILE
from floorplan_engine.service.analysis.analyzer import (
    MODEL_FILES,
    AnalysisResult,
    Analyzer,
    ManualAnalyzer,
)
from floorplan_engine.service.analysis.pdf_facts import describe
from floorplan_engine.validation.issues import ELECTRICAL_FILE, ROOM_FILE, Issue
from floorplan_engine.validation.validate import validate_project

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"  # measured 2026-10-20: almost as good as high, faster and cheaper
FIX_ATTEMPTS = 2
USAGE_FILE = "usage.jsonl"
SOURCE_DIR = "source"
PROMPT = (Path(__file__).parent / "analyzer_prompt.md").read_text(encoding="utf-8")

# $ per 1M tokens: input, output, cache read, cache write (5 min, ×1.25 of input)
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
}

ENVELOPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": list(MODEL_FILES)},
                    "content": {"type": "string"},
                },
                "required": ["name", "content"],
                "additionalProperties": False,
            },
        },
        "resolved": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["files", "resolved", "summary"],
    "additionalProperties": False,
}

IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
IMAGE_TYPES |= {".webp": "image/webp", ".gif": "image/gif"}
MAX_REQUEST_BYTES = 30 * 1024 * 1024  # API request limit is 32 MB, base64 inflates by 4/3


class AnalyzerError(RuntimeError):
    pass


@dataclass
class Usage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float | None = None  # None means the model's price is not in PRICES
    seconds: float = 0.0

    def priced(self) -> Usage:
        if self.cost_usd is None and self.model in PRICES:
            p_in, p_out, p_read, p_write = PRICES[self.model]
            self.cost_usd = (
                self.input_tokens * p_in
                + self.output_tokens * p_out
                + self.cache_read_tokens * p_read
                + self.cache_write_tokens * p_write
            ) / 1_000_000
        return self


@dataclass
class Reply:
    envelope: dict[str, Any]
    usage: Usage


class Backend(Protocol):
    name: str

    def start(self, project: Path, prompt: str) -> Reply:
        """First message of a round: sources + context."""
        ...

    def follow_up(self, project: Path, prompt: str) -> Reply:
        """Continuation of the same conversation: validation errors."""
        ...


def _is_pdf(path: Path) -> bool:
    return path.suffix.lower() == ".pdf"


def facts_text(path: Path, name: str) -> str:
    return f"Выжимка из {name} (посчитана кодом по векторам PDF):\n\n{describe(path, name)}"


# --- Backend: claude -p (subscription) ---------------------------------------


@dataclass
class ClaudeCodeBackend:
    """`claude -p` in the project folder. The API key is removed from the environment so the
    subscription is used.
    """

    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    max_budget_usd: float = 10.0
    timeout_s: float = 30 * 60
    name: str = "claude-code"
    _session: str | None = field(default=None, repr=False)
    _spent: float = field(default=0.0, repr=False)  # session total_cost_usd at the previous call

    def _run(self, project: Path, prompt: str, resume: str | None) -> Reply:
        exe = shutil.which("claude")
        if exe is None:
            raise AnalyzerError("не найден claude (Claude Code CLI) — установите и войдите")
        with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as fh:
            fh.write(PROMPT)
        prompt_file = Path(fh.name)
        cmd = [
            exe,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(ENVELOPE_SCHEMA),
            "--model",
            self.model,
            "--effort",
            self.effort,
            "--append-system-prompt-file",
            str(prompt_file),
            # The model only reads the sources; writing files and running commands is not allowed
            "--allowedTools",
            "Read",
            "--permission-mode",
            "dontAsk",
            "--max-budget-usd",
            str(self.max_budget_usd),
        ]
        if resume:
            cmd += ["--resume", resume]
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        started = time.monotonic()
        try:
            done = subprocess.run(
                cmd,
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                check=False,
            )
        finally:
            prompt_file.unlink(missing_ok=True)
        seconds = time.monotonic() - started
        try:
            data: dict[str, Any] = json.loads(done.stdout)
        except json.JSONDecodeError as exc:
            raise AnalyzerError(
                f"claude -p вернул не JSON (код {done.returncode}): {done.stderr[-500:]}"
            ) from exc
        if data.get("is_error") or "structured_output" not in data:
            raise AnalyzerError(f"claude -p: {data.get('result') or data.get('subtype')}")
        self._session = data.get("session_id")
        # With --resume, total_cost_usd is the running session total, not the price of this call
        total = data.get("total_cost_usd")
        cost = None if total is None else total - self._spent
        self._spent = total if total is not None else self._spent
        u = data.get("usage") or {}
        usage = Usage(
            model=self.model,
            input_tokens=int(u.get("input_tokens", 0)),
            output_tokens=int(u.get("output_tokens", 0)),
            cache_read_tokens=int(u.get("cache_read_input_tokens", 0)),
            cache_write_tokens=int(u.get("cache_creation_input_tokens", 0)),
            cost_usd=cost,
            seconds=seconds,
        )
        return Reply(data["structured_output"], usage)

    def start(self, project: Path, prompt: str) -> Reply:
        sources = (
            sorted((project / SOURCE_DIR).glob("*")) if (project / SOURCE_DIR).exists() else []
        )
        names = [p.relative_to(project).as_posix() for p in sources]
        listing = "\n".join(f"- {n}" for n in names)
        facts = [facts_text(p, n) for p, n in zip(sources, names, strict=True) if _is_pdf(p)]
        full = (
            f"Источники проекта (прочитай каждый инструментом Read):\n{listing or '- нет'}\n\n"
            + "".join(f"{f}\n" for f in facts)
            + prompt
        )
        return self._run(project, full, None)

    def follow_up(self, project: Path, prompt: str) -> Reply:
        return self._run(project, prompt, self._session)


# --- Backend: Anthropic API (key) ---------------------------------------------


@dataclass
class ApiBackend:
    """Anthropic API: sources go in the request as documents and images."""

    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    max_tokens: int = 64000
    name: str = "api"
    _messages: list[dict[str, Any]] = field(default_factory=list, repr=False)

    @staticmethod
    def source_blocks(project: Path) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        total = 0
        folder = project / SOURCE_DIR
        for path in sorted(folder.glob("*")) if folder.exists() else []:
            suffix = path.suffix.lower()
            name = path.relative_to(project).as_posix()
            if suffix == ".pdf":
                kind, media = "document", "application/pdf"
            elif suffix in IMAGE_TYPES:
                kind, media = "image", IMAGE_TYPES[suffix]
            else:
                blocks.append(
                    {"type": "text", "text": f"Файл {name} не читается (формат {suffix})."}
                )
                continue
            data = path.read_bytes()
            total += len(data)
            if total > MAX_REQUEST_BYTES:
                raise AnalyzerError(
                    f"источники больше {MAX_REQUEST_BYTES // 2**20} МБ — разбейте или сожмите"
                )
            blocks.append({"type": "text", "text": f"Файл {name}:"})
            source = {
                "type": "base64",
                "media_type": media,
                "data": base64.b64encode(data).decode(),
            }
            blocks.append({"type": kind, "source": source})
            if kind == "document":
                blocks.append({"type": "text", "text": facts_text(path, name)})
        return blocks

    def _call(self) -> Reply:
        import anthropic  # a service group dependency, needed only by this backend

        client = anthropic.Anthropic()
        output_config = {
            "effort": self.effort,
            "format": {"type": "json_schema", "schema": ENVELOPE_SCHEMA},
        }
        started = time.monotonic()
        with client.beta.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            # A classifier refusal is retried on the recommended model, not treated as an empty
            # answer
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=[{"type": "text", "text": PROMPT, "cache_control": {"type": "ephemeral"}}],
            output_config=cast("BetaOutputConfigParam", output_config),
            messages=self._messages,  # type: ignore[arg-type]
        ) as stream:
            message = stream.get_final_message()
        if message.stop_reason == "refusal":
            raise AnalyzerError("модель отказалась обрабатывать источники")
        if message.stop_reason == "max_tokens":
            raise AnalyzerError(f"ответ не уместился в max_tokens={self.max_tokens}")
        text = next(b.text for b in message.content if b.type == "text")
        self._messages.append({"role": "assistant", "content": message.content})
        u = message.usage
        usage = Usage(
            model=message.model,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=u.cache_read_input_tokens or 0,
            cache_write_tokens=u.cache_creation_input_tokens or 0,
            seconds=time.monotonic() - started,
        ).priced()
        envelope: dict[str, Any] = json.loads(text)
        return Reply(envelope, usage)

    def start(self, project: Path, prompt: str) -> Reply:
        content = [*self.source_blocks(project), {"type": "text", "text": prompt}]
        self._messages = [{"role": "user", "content": content}]
        return self._call()

    def follow_up(self, project: Path, prompt: str) -> Reply:
        self._messages.append({"role": "user", "content": prompt})
        return self._call()


# --- Analyzer -------------------------------------------------------------------


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def round_prompt(project: Path, round_no: int, task: str = "") -> str:
    """Round context: step task, current model, text answers, validation errors."""
    parts = [f"Раунд {round_no}."]
    if task:
        parts.append(task)
    current = {name: _read(project / name) for name in MODEL_FILES}
    if any(current.values()):
        parts.append("Текущая модель:")
        parts += [f"--- {name}\n{text}" for name, text in current.items() if text is not None]
    else:
        parts.append("Модели ещё нет — прочитай источники и напиши её.")
    text_answers = _pending_text(project)
    if text_answers:
        parts.append("Текстовые ответы проектировщика — разбери и верни их id в resolved:")
        parts += [f"- {qid}: {text}" for qid, text in text_answers.items()]
    issues = [i for i in validate_project(project).errors] if any(current.values()) else []
    if issues:
        parts.append("Ошибки проверки текущей модели — исправь:")
        parts += [f"- {i}" for i in issues]
    return "\n\n".join(parts)


def _answers(project: Path) -> Answers:
    text = _read(project / ANSWERS_FILE)
    return Answers.model_validate(yaml.safe_load(text) or {}) if text else Answers()


def _pending_text(project: Path) -> dict[str, str]:
    return {
        qid: a.text
        for qid, a in _answers(project).answers.items()
        if isinstance(a, TextAnswer) and not a.resolved
    }


def _mark_resolved(project: Path, ids: list[str]) -> None:
    answers = _answers(project)
    changed = False
    for qid in ids:
        answer = answers.answers.get(qid)
        if isinstance(answer, TextAnswer) and not answer.resolved:
            answers.answers[qid] = TextAnswer(text=answer.text, resolved=True)
            changed = True
    if changed:
        plain = {
            k: v.model_dump() if hasattr(v, "model_dump") else v for k, v in answers.answers.items()
        }
        (project / ANSWERS_FILE).write_text(
            yaml.safe_dump({"answers": plain}, allow_unicode=True), encoding="utf-8"
        )


def _apply(project: Path, envelope: dict[str, Any], files: tuple[str, ...]) -> list[str]:
    written = []
    for f in envelope.get("files", []):
        if f["name"] in files:
            (project / f["name"]).write_text(f["content"], encoding="utf-8")
            written.append(f["name"])
    _mark_resolved(project, list(envelope.get("resolved", [])))
    return written


def _model_errors(project: Path, files: tuple[str, ...]) -> list[Issue]:
    """Errors in files the step can fix."""
    return [e for e in validate_project(project).errors if e.file in files]


def _log(project: Path, round_no: int, backend: str, attempt: int, usage: Usage) -> None:
    record = {
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
        "round": round_no,
        "attempt": attempt,
        "backend": backend,
        "model": usage.model,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "cost_usd": usage.cost_usd,
        "seconds": round(usage.seconds, 1),
    }
    with (project / USAGE_FILE).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class Step:
    files: tuple[str, ...]  # files the step writes; the rest of the answer is dropped
    task: str  # step task in the round prompt; empty means the whole model
    make_backend: Callable[[], Backend]


PLAN_FILES = (INTAKE_FILE, ROOM_FILE)
ELECTRICAL_FILES = (INTAKE_FILE, ELECTRICAL_FILE, PLUMBING_FILE)
PLAN_TASK = (
    "Этот шаг — только план: пиши intake.yaml и room.yaml. Электрику и сантехнику напишет "
    "следующий шаг, поэтому electrical.yaml и plumbing.yaml не пиши, вопросов и записей этапов "
    "electrical и plumbing в intake.yaml не добавляй, текстовые ответы про них не разбирай."
)
ELECTRICAL_TASK = (
    "Этот шаг — электрика и сантехника. План уже готов (room.yaml ниже) — не меняй его, "
    "ссылайся на его комнаты и стены. Пиши electrical.yaml, plumbing.yaml (если в источниках "
    "есть приборы или стояки) и intake.yaml: сохрани все источники, этапы и вопросы из текущего "
    "intake.yaml и добавь этапы electrical и plumbing и их вопросы; id вопросов продолжай после "
    "последнего."
)


@dataclass
class LlmAnalyzer:
    reads_sources = True
    # A new backend per analysis step: it holds the conversation state, and projects run in parallel
    make_backend: Callable[[], Backend]
    # A separate electrical model makes the analysis two steps: plan and electrical
    make_electrical: Callable[[], Backend] | None = None

    def steps(self) -> list[Step]:
        if self.make_electrical is None:
            return [Step(MODEL_FILES, "", self.make_backend)]
        return [
            Step(PLAN_FILES, PLAN_TASK, self.make_backend),
            Step(ELECTRICAL_FILES, ELECTRICAL_TASK, self.make_electrical),
        ]

    def analyze(self, project: Path, round_no: int) -> AnalysisResult:
        cost, calls, summaries = 0.0, 0, []
        for step in self.steps():
            if step.files == ELECTRICAL_FILES and not (project / ROOM_FILE).exists():
                break  # no plan: nothing to attach electrical to
            step_cost, step_calls, summary = self._step(project, round_no, step)
            cost, calls = cost + step_cost, calls + step_calls
            summaries.append(summary)
        return AnalysisResult(True, " ".join(summaries), cost_usd=cost, calls=calls)

    @staticmethod
    def _step(project: Path, round_no: int, step: Step) -> tuple[float, int, str]:
        backend = step.make_backend()
        reply = backend.start(project, round_prompt(project, round_no, step.task))
        cost, calls = 0.0, 0
        for attempt in range(FIX_ATTEMPTS + 1):
            _log(project, round_no, backend.name, attempt, reply.usage)
            cost += reply.usage.cost_usd or 0.0
            calls += 1
            _apply(project, reply.envelope, step.files)
            if not (project / INTAKE_FILE).exists():
                errors_text = f"нет {INTAKE_FILE} — верни его в files"
            else:
                errors = _model_errors(project, step.files)
                if not errors:
                    break
                errors_text = "\n".join(f"- {e}" for e in errors)
            if attempt == FIX_ATTEMPTS:
                break  # errors stay in the report, the project goes to needs_model
            reply = backend.follow_up(
                project,
                "Проверка нашла ошибки. Исправь их и верни исправленные файлы целиком:\n"
                + errors_text,
            )
        return cost, calls, str(reply.envelope.get("summary", ""))


def make_analyzer(
    kind: str,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    electrical_model: str | None = None,
) -> Analyzer:
    """manual: an operator uploads the model; claude-code: subscription; api: key.

    electrical_model: this model writes electrical in a separate step (for example, Sonnet)."""
    if kind == "manual":
        return ManualAnalyzer()
    backends: dict[str, Callable[[str], Backend]] = {
        "claude-code": lambda m: ClaudeCodeBackend(model=m, effort=effort),
        "api": lambda m: ApiBackend(model=m, effort=effort),
    }
    if kind not in backends:
        raise ValueError(f"анализатор: manual | claude-code | api, а не {kind}")
    make = backends[kind]
    split = electrical_model is not None and electrical_model != model
    return LlmAnalyzer(
        lambda: make(model),
        (lambda: make(electrical_model or model)) if split else None,
    )
