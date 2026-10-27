"""Оценка проекта: вес вопросов и статус каждого этапа — строить, строить с вопросами или нет.

Вес вопроса считает код по полю, на которое он указывает, а не анализатор: один и тот
же проект всегда даёт один и тот же статус.

    геометрия (length, turn, origin, start_angle)   critical, если значения нет, иначе major
    привязка (offset, width, wall, ceiling, …)      major
    остальное (height, thickness, sill, group, …)   minor
    вопрос без target                               вес указывает анализатор

Этап не строится, если есть открытый critical или сумма весов (major 3, minor 1) больше
WEIGHT_LIMIT — «мало данных». Электрика без готового плана заблокирована.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from floorplan_engine.intake import QSeverity, Question, Stage
from floorplan_engine.validate import ELECTRICAL_FILE, ROOM_FILE, Report

GEOMETRY_FIELDS = frozenset({"length", "turn", "origin", "start_angle"})
PLACEMENT_FIELDS = frozenset({"offset", "width", "wall", "ceiling", "start", "end", "room"})
WEIGHTS = {QSeverity.CRITICAL: 0, QSeverity.MAJOR: 3, QSeverity.MINOR: 1}
WEIGHT_LIMIT = 12

# Этапы, которые уже умеем строить, и их файлы
STAGE_FILES = {Stage.PLAN: ROOM_FILE, Stage.ELECTRICAL: ELECTRICAL_FILE}
DEPENDS_ON = {
    Stage.ELECTRICAL: Stage.PLAN,
    Stage.FURNITURE: Stage.PLAN,
    Stage.LIGHTING: Stage.PLAN,
    Stage.POWER: Stage.PLAN,
    Stage.WIRING: Stage.PLAN,
    Stage.PLUMBING: Stage.PLAN,
    Stage.PANEL: Stage.ELECTRICAL,
}


class Status(StrEnum):
    READY = "ready"  # строится, вопросов нет
    QUESTIONS = "questions"  # строится по допущениям, вопросы в отчёте
    INSUFFICIENT = "insufficient"  # мало данных — не строится
    INVALID = "invalid"  # ошибки в YAML — не строится
    BLOCKED = "blocked"  # не готов этап, от которого зависит
    ABSENT = "absent"  # данных нет, делать не буду
    UNSUPPORTED = "unsupported"  # данные есть, этап ещё не умеем строить

    @property
    def builds(self) -> bool:
        return self in (Status.READY, Status.QUESTIONS)


STATUS_TEXT = {
    Status.READY: "готово",
    Status.QUESTIONS: "строится, есть вопросы",
    Status.INSUFFICIENT: "мало данных — не строится",
    Status.INVALID: "ошибки в данных — не строится",
    Status.BLOCKED: "заблокирован",
    Status.ABSENT: "данных нет, делать не буду",
    Status.UNSUPPORTED: "данные есть, этап пока не поддерживается",
}


def severity(q: Question) -> QSeverity:
    if q.target is None:
        assert q.severity is not None  # гарантирует схема
        return q.severity
    name = q.target.rsplit(".", 1)[-1]
    if name in GEOMETRY_FIELDS:
        return QSeverity.CRITICAL if q.assumption is None else QSeverity.MAJOR
    if name in PLACEMENT_FIELDS:
        return QSeverity.MAJOR
    return QSeverity.MINOR


@dataclass
class StageResult:
    stage: Stage
    status: Status
    reason: str = ""
    open_questions: list[Question] = field(default_factory=list)

    @property
    def weight(self) -> int:
        return sum(WEIGHTS[severity(q)] for q in self.open_questions)

    def count(self, level: QSeverity) -> int:
        return sum(1 for q in self.open_questions if severity(q) is level)


def _stages_in_play(report: Report) -> list[Stage]:
    present = set(STAGE_FILES)
    if report.intake is not None:
        present |= set(report.intake.stages)
    present |= {q.stage for q in report.questions}
    return [s for s in Stage if s in present]


def assess(report: Report) -> list[StageResult]:
    """Статус каждого этапа, о котором что-то известно, в порядке Stage."""
    intake = report.intake
    results: dict[Stage, StageResult] = {}
    for stage in _stages_in_play(report):
        open_q = [
            q
            for q in report.questions
            if q.stage is stage and report.question_states.get(q.id, "open") in ("open", "text")
        ]
        result = StageResult(stage, Status.READY, open_questions=open_q)
        results[stage] = result
        note = intake.stages.get(stage) if intake else None
        file = STAGE_FILES.get(stage)
        has_model = (stage is Stage.PLAN and report.plan is not None) or (
            stage is Stage.ELECTRICAL and report.electrical is not None
        )
        errors = [i for i in report.errors if file is not None and i.file in (file,)]
        parent = DEPENDS_ON.get(stage)
        if stage is Stage.PANEL:
            # Щит строится вместе с электрикой; его вопросы её не останавливают
            built = parent in results and results[parent].status.builds
            result.status = (
                Status.BLOCKED if not built else Status.QUESTIONS if open_q else Status.READY
            )
            result.reason = "" if built else f"не готов этап {parent}"
        elif file is None:
            result.status = (
                Status.ABSENT
                if note is not None and note.status == "absent"
                else Status.UNSUPPORTED
            )
            result.reason = note.note if note else ""
        elif errors:
            result.status = Status.INVALID
            result.reason = f"ошибок: {len(errors)}"
        elif result.count(QSeverity.CRITICAL):
            result.status = Status.INSUFFICIENT
            result.reason = f"критичных вопросов: {result.count(QSeverity.CRITICAL)}"
        elif result.weight > WEIGHT_LIMIT:
            result.status = Status.INSUFFICIENT
            result.reason = f"вес вопросов {result.weight} больше {WEIGHT_LIMIT}"
        elif not has_model:
            result.status = Status.ABSENT
            result.reason = note.note if note else f"нет {file}"
        elif parent is not None and parent in results and not results[parent].status.builds:
            result.status = Status.BLOCKED
            result.reason = f"не готов этап {parent.value}"
        elif open_q:
            result.status = Status.QUESTIONS
    return list(results.values())
