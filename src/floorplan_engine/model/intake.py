"""intake.yaml says what is known about the project sources, and answers.yaml holds the answers.

intake.yaml is written by the analyzer (currently Claude, following the CLAUDE.md rules):

    sources:                       # what was parsed
      - { file: source/plan.pdf, note: "лист 08, масштаб по привязкам" }
    stages:                        # stages with something to say
      plumbing: { status: absent, note: "на листах нет сантехники" }
    questions:
      - id: q1
        stage: plan
        target: rooms.storage.walls.w2.length   # model field, path by id
        also: [rooms.storage.walls.w4.length]   # the same value in other fields
        text: "Ширина кладовки не подписана, 1783 — расчёт 7245 − 5462"
        answer: value                           # value | choice | text
        unit: mm
        assumption: 1783                        # what the model holds now
      - id: q2
        stage: plan
        text: "Есть ли обмерный план?"
        answer: text
        severity: major                         # only for questions without target
      - id: q3
        stage: electrical
        audience: client                        # asked of the client; studio by default
        text: "Нужен ли тёплый пол в ванной?"
        answer: choice
        options: ["yes", "no"]
        severity: major

Who is asked (decision 2026-11-11): a studio question is about the drawing (a size, a wall, the
scale); its value or choice is put into the target, as the developer would edit the YAML. A client
question only clarifies: it has no target, its answer of any kind is kept as { text } and is never
put into the model (the drawing follows the design project alone). The developer takes it into
account (resolved: true, editing the sources if needed) or returns it with a comment (returned).
Code-built panel questions are the client's own settings (the setup wizard): they apply at once.

answers.yaml holds answers, applied to the stage YAML on load (the sources are not rewritten):

    answers:
      q1: 1800                       # value / choice: put into target
      q2: { text: "обмера нет" }      # text: waits for the developer; once handled, resolved: true
      q3: { text: "yes", returned: "В какой ванной — большой или гостевой?" }  # sent back
      q4: { accept: true }           # keep the assumption
    log:                             # written by the viewer: who answered and when
      q1: { at: "2026-11-04T10:00:00+00:00", by: "Иван" }
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from floorplan_engine.model.schema import ID_PATTERN, StrictModel

INTAKE_FILE = "intake.yaml"
ANSWERS_FILE = "answers.yaml"


class Stage(StrEnum):
    """Project stages; plan, electrical (with panel) and plumbing can be built."""

    PLAN = "plan"
    ELECTRICAL = "electrical"
    FURNITURE = "furniture"
    LIGHTING = "lighting"
    POWER = "power"
    WIRING = "wiring"
    PLUMBING = "plumbing"
    PANEL = "panel"  # questions built by code (panel_questions.panel_questions)


# Who is asked: the studio (the drawing) or the client (a clarification, never put into the model)
Audience = Literal["studio", "client"]


class QSeverity(StrEnum):
    CRITICAL = "critical"  # the stage is not built without an answer
    MAJOR = "major"  # built on an assumption, affects geometry
    MINOR = "minor"  # clarification


class Source(StrictModel):
    file: str
    note: str = ""


class StageNote(StrictModel):
    status: Literal["found", "absent"]
    note: str = ""


class Question(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    stage: Stage
    audience: Audience = "studio"
    text: str = Field(min_length=1)
    target: str | None = Field(
        default=None, description="Путь к полю в YAML этапа по id: rooms.kitchen.walls.w3.length"
    )
    also: list[str] = Field(
        default_factory=list, description="Другие поля, куда подставляется тот же ответ"
    )
    answer: Literal["value", "choice", "text", "groups"] = Field(
        default="text",
        description="groups — список групп щита из options; такой вопрос строит только код",
    )
    unit: str | None = None
    options: list[str] = Field(default_factory=list)
    option_labels: dict[str, str] = Field(
        default_factory=dict,
        description="Подпись варианта для человека, на языке проекта: {значение: подпись}",
    )
    assumption: float | str | None = Field(
        default=None, description="Значение, которое сейчас стоит в модели; null — его нет"
    )
    severity: QSeverity | None = Field(
        default=None, description="Только для вопросов без target; иначе вес считает код"
    )

    @model_validator(mode="after")
    def _consistent(self) -> Question:
        if self.answer in ("choice", "groups") and not self.options:
            raise ValueError(f"для answer: {self.answer} нужен список options")
        if self.answer not in ("choice", "groups") and self.options:
            raise ValueError("options бывают только у answer: choice и groups")
        if set(self.option_labels) - set(self.options):
            raise ValueError("option_labels — только для значений из options")
        if self.target is None and self.severity is None:
            raise ValueError("у вопроса без target нужен severity: critical | major | minor")
        if self.target is not None and self.severity is not None:
            raise ValueError("у вопроса с target вес считает код — уберите severity")
        if self.also and self.target is None:
            raise ValueError("also без target не имеет смысла")
        if self.audience == "client":
            if self.target is not None:
                raise ValueError(
                    "вопрос заказчику только уточняет: target у него не бывает, чертёж меняется "
                    "только по исходникам"
                )
            if self.answer == "groups":
                raise ValueError("answer: groups — только у вопросов щита")
        elif self.answer in ("value", "choice") and self.target is None:
            raise ValueError(f"ответ {self.answer} подставляется в поле — нужен target")
        return self


class Intake(StrictModel):
    sources: list[Source] = Field(default_factory=list)
    stages: dict[Stage, StageNote] = Field(default_factory=dict)
    questions: list[Question] = Field(default_factory=list)


class Accept(StrictModel):
    accept: Literal[True]


class TextAnswer(StrictModel):
    text: str = Field(min_length=1)
    # The developer (or the analyzer) took the answer into account: the question is closed
    resolved: bool = False
    # The developer sent the answer back with this comment: the question is open again
    returned: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _one_outcome(self) -> TextAnswer:
        if self.resolved and self.returned is not None:
            raise ValueError("ответ либо учтён (resolved), либо возвращён (returned)")
        return self


Answer = float | str | list[str] | Accept | TextAnswer


class AnswerNote(StrictModel):
    """Who answered in the viewer and when, and who reviewed a client answer; not used in a
    build."""

    at: str
    by: str | None = None
    reviewed_at: str | None = None
    reviewed_by: str | None = None


class Answers(StrictModel):
    answers: dict[str, Answer] = Field(default_factory=dict)
    log: dict[str, AnswerNote] = Field(default_factory=dict)


# --- Field paths --------------------------------------------------------------


class TargetError(ValueError):
    pass


def _step(node: Any, key: str, path: str) -> Any:
    if isinstance(node, dict):
        if key not in node:
            raise TargetError(f"в «{path}» нет поля «{key}»")
        return node[key]
    if isinstance(node, list):
        for item in node:
            if isinstance(item, dict) and item.get("id") == key:
                return item
        raise TargetError(f"в «{path}» нет объекта с id «{key}»")
    raise TargetError(f"«{path}» — не объект и не список")


def get_target(data: Any, target: str) -> Any:
    """Field value by an id path; a missing last field gives None."""
    parts = target.split(".")
    node = data
    for k, key in enumerate(parts[:-1]):
        node = _step(node, key, ".".join(parts[:k]) or "<корень>")
    if not isinstance(node, dict):
        raise TargetError(f"«{'.'.join(parts[:-1])}» — не объект")
    return node.get(parts[-1])


def set_target(data: Any, target: str, value: Any) -> None:
    """Write a value into the field at an id path (the field is created, objects are not)."""
    parts = target.split(".")
    node = data
    for k, key in enumerate(parts[:-1]):
        node = _step(node, key, ".".join(parts[:k]) or "<корень>")
    if not isinstance(node, dict):
        raise TargetError(f"«{'.'.join(parts[:-1])}» — не объект")
    node[parts[-1]] = value


def index_path(data: Any, target: str) -> str:
    """Id path → index path, as in validation messages:
    rooms.balcony.openings.balcony_window_1.sill → rooms[2].openings[2].sill."""
    out = ""
    node = data
    for key in target.split("."):
        if isinstance(node, list):
            index = next(
                k for k, item in enumerate(node) if isinstance(item, dict) and item.get("id") == key
            )
            out += f"[{index}]"
            node = node[index]
        else:
            out += f".{key}" if out else key
            node = node.get(key) if isinstance(node, dict) else None
    return out
