"""Модели API сервиса и состояния проекта."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from floorplan_engine.model.intake import Accept, TextAnswer


class ProjectState(StrEnum):
    CREATED = "created"  # источники загружены, анализа не было
    ANALYZING = "analyzing"
    NEEDS_MODEL = "needs_model"  # модель нужно доработать: нет YAML, ошибки, текстовые ответы
    NEEDS_ANSWERS = "needs_answers"  # есть открытые вопросы; черновик чертежа может быть готов
    BUILDING = "building"
    READY = "ready"  # чертёж собран
    INSUFFICIENT = "insufficient"  # план построить нельзя, спрашивать больше нечего
    REJECTED = "rejected"  # по источникам ничего не построить — модель не вызывалась
    FAILED = "failed"  # внутренняя ошибка

    @property
    def busy(self) -> bool:
        return self in (ProjectState.ANALYZING, ProjectState.BUILDING)


class StageInfo(BaseModel):
    stage: str
    status: str
    builds: bool
    reason: str = ""
    open_questions: int = 0


class ProjectInfo(BaseModel):
    id: str
    name: str
    state: ProjectState
    round: int = 0  # номер раунда вопросов; 1 — после первого анализа
    message: str = ""  # что делать дальше, по-русски
    created: str
    updated: str
    sources: list[str] = Field(default_factory=list)
    stages: list[StageInfo] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)  # готовые файлы: /projects/{id}/files/{path}
    llm_calls: int = 0  # вызовов LLM-анализатора за всё время проекта
    llm_cost_usd: float = 0.0  # их стоимость (оценка; подробности — usage.jsonl проекта)


class AnswersIn(BaseModel):
    """Ответы раунда: q1: 1800, q2: {accept: true}, q3: {text: "…"}."""

    answers: dict[str, float | str | Accept | TextAnswer]


class QuestionsOut(BaseModel):
    project: str
    round: int
    state: ProjectState
    questions: list[dict[str, Any]]  # как в report.json: вопрос, вес, состояние
