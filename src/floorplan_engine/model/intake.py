"""intake.yaml — что известно об источниках проекта, и answers.yaml — ответы на вопросы.

intake.yaml пишет анализатор (сейчас — Claude по правилам CLAUDE.md):

    sources:                       # что разобрано
      - { file: source/plan.pdf, note: "лист 08, масштаб по привязкам" }
    stages:                        # этапы, о которых есть что сказать
      plumbing: { status: absent, note: "на листах нет сантехники" }
    questions:
      - id: q1
        stage: plan
        target: rooms.storage.walls.w2.length   # поле модели, путь по id
        also: [rooms.storage.walls.w4.length]   # те же значения в других полях
        text: "Ширина кладовки не подписана, 1783 — расчёт 7245 − 5462"
        answer: value                           # value | choice | text
        unit: mm
        assumption: 1783                        # что сейчас стоит в модели
      - id: q2
        stage: plan
        text: "Есть ли обмерный план?"
        answer: text
        severity: major                         # только у вопросов без target

answers.yaml — ответы, накладываются на YAML этапа при загрузке (исходники не переписываются):

    answers:
      q1: 1800                       # value / choice — подставляется в target
      q2: { text: "обмера нет" }      # текст — ждёт анализатора; разобрал — resolved: true
      q3: { accept: true }           # оставить допущение
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from floorplan_engine.model.schema import ID_PATTERN, StrictModel

INTAKE_FILE = "intake.yaml"
ANSWERS_FILE = "answers.yaml"


class Stage(StrEnum):
    """Этапы проекта; построение пока есть у plan и electrical."""

    PLAN = "plan"
    ELECTRICAL = "electrical"
    FURNITURE = "furniture"
    LIGHTING = "lighting"
    POWER = "power"
    WIRING = "wiring"
    PLUMBING = "plumbing"
    PANEL = "panel"  # щит: вопросы составляет код по расчёту (panel_questions.panel_questions)


class QSeverity(StrEnum):
    CRITICAL = "critical"  # без ответа этап не строится
    MAJOR = "major"  # строится по допущению, влияет на геометрию
    MINOR = "minor"  # уточнение


class Source(StrictModel):
    file: str
    note: str = ""


class StageNote(StrictModel):
    status: Literal["found", "absent"]
    note: str = ""


class Question(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    stage: Stage
    text: str = Field(min_length=1)
    target: str | None = Field(
        default=None, description="Путь к полю в YAML этапа по id: rooms.kitchen.walls.w3.length"
    )
    also: list[str] = Field(
        default_factory=list, description="Другие поля, куда подставляется тот же ответ"
    )
    answer: Literal["value", "choice", "text"] = "text"
    unit: str | None = None
    options: list[str] = Field(default_factory=list)
    assumption: float | str | None = Field(
        default=None, description="Значение, которое сейчас стоит в модели; null — его нет"
    )
    severity: QSeverity | None = Field(
        default=None, description="Только для вопросов без target; иначе вес считает код"
    )

    @model_validator(mode="after")
    def _consistent(self) -> Question:
        if self.answer == "choice" and not self.options:
            raise ValueError("для answer: choice нужен список options")
        if self.answer != "choice" and self.options:
            raise ValueError("options бывают только у answer: choice")
        if self.target is None and self.severity is None:
            raise ValueError("у вопроса без target нужен severity: critical | major | minor")
        if self.target is not None and self.severity is not None:
            raise ValueError("у вопроса с target вес считает код — уберите severity")
        if self.also and self.target is None:
            raise ValueError("also без target не имеет смысла")
        if self.answer in ("value", "choice") and self.target is None:
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
    # Анализатор перенёс смысл ответа в YAML этапа — вопрос закрыт
    resolved: bool = False


Answer = float | str | Accept | TextAnswer


class Answers(StrictModel):
    answers: dict[str, Answer] = Field(default_factory=dict)


# --- Пути к полям -------------------------------------------------------------


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
    """Значение поля по пути из id; отсутствующее последнее поле — None."""
    parts = target.split(".")
    node = data
    for k, key in enumerate(parts[:-1]):
        node = _step(node, key, ".".join(parts[:k]) or "<корень>")
    if not isinstance(node, dict):
        raise TargetError(f"«{'.'.join(parts[:-1])}» — не объект")
    return node.get(parts[-1])


def set_target(data: Any, target: str, value: Any) -> None:
    """Записать значение в поле по пути из id (поле создаётся, объекты — нет)."""
    parts = target.split(".")
    node = data
    for k, key in enumerate(parts[:-1]):
        node = _step(node, key, ".".join(parts[:k]) or "<корень>")
    if not isinstance(node, dict):
        raise TargetError(f"«{'.'.join(parts[:-1])}» — не объект")
    node[parts[-1]] = value


def index_path(data: Any, target: str) -> str:
    """Путь по id → путь по индексам, как в сообщениях валидации:
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
