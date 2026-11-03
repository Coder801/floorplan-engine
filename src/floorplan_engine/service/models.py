"""Service API models and project state."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from floorplan_engine.model.intake import Accept, TextAnswer


class ProjectState(StrEnum):
    CREATED = "created"  # sources uploaded, no analysis yet
    ANALYZING = "analyzing"
    NEEDS_MODEL = "needs_model"  # the model needs work: no YAML, errors, text answers
    NEEDS_ANSWERS = "needs_answers"  # there are open questions; a draft drawing may be ready
    BUILDING = "building"
    READY = "ready"  # drawing built
    INSUFFICIENT = "insufficient"  # the plan cannot be built and there is nothing left to ask
    REJECTED = "rejected"  # nothing can be built from the sources; the model was not called
    FAILED = "failed"  # internal error

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
    round: int = 0  # question round number; 1 after the first analysis
    message: str = ""  # what to do next, in Russian
    created: str
    updated: str
    sources: list[str] = Field(default_factory=list)
    stages: list[StageInfo] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)  # ready files: /projects/{id}/files/{path}
    llm_calls: int = 0  # LLM analyzer calls over the project's lifetime
    llm_cost_usd: float = 0.0  # their cost (estimate; details in the project's usage.jsonl)


class AnswersIn(BaseModel):
    """Round answers: q1: 1800, q2: {accept: true}, q3: {text: "…"}."""

    answers: dict[str, float | str | Accept | TextAnswer]


class QuestionsOut(BaseModel):
    project: str
    round: int
    state: ProjectState
    questions: list[dict[str, Any]]  # as in report.json: question, weight, state
