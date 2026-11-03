"""Project cycle in the service: analysis → questions → answers → … → build.

    created ─analyze─▶ analyzing ─▶ needs_model     (no model / errors / text answers)
                                 ─▶ needs_answers   (questions open and rounds not used up)
                                 ─▶ ready           (plan built, no questions or rounds used up)
                                 ─▶ insufficient    (plan cannot be built, nothing to ask)
    needs_answers ─answers─▶ building ─▶ the same

Every assessment rebuilds the report and, if the plan builds, the DXF, the artifact and the
PNGs: a draft is available even while questions are open.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from floorplan_engine.model.intake import ANSWERS_FILE, Accept, Answers, Stage, TextAnswer
from floorplan_engine.pipeline import OUT_DIR, BuildResult, build_project
from floorplan_engine.service.analysis.analyzer import MODEL_FILES, AnalysisResult, Analyzer
from floorplan_engine.service.facts.gate import Gate, check_sources
from floorplan_engine.service.models import AnswersIn, ProjectInfo, ProjectState, StageInfo
from floorplan_engine.service.storage import SOURCE_DIR, Storage
from floorplan_engine.validation.answers_file import dump_answers
from floorplan_engine.validation.assess import Status
from floorplan_engine.validation.report import REPORT_JSON

MAX_ROUNDS = 3  # question rounds; after that, a build on assumptions or "not enough data"
log = logging.getLogger(__name__)


class ConflictError(RuntimeError):
    """The action is not allowed in the current project state."""


def _files(result: BuildResult, out: Path) -> list[str]:
    """Ready files relative to out/: report.md, project.dxf, project.epd …"""
    paths = [*result.report_files, result.dxf, result.artifact, *result.sheets]
    return [p.relative_to(out).as_posix() for p in paths if p is not None]


def _apply(info: ProjectInfo, result: BuildResult, out: Path) -> None:
    """Assessment result → project state."""
    a = result.assessment
    info.stages = [
        StageInfo(
            stage=r.stage.value,
            status=r.status.value,
            builds=r.status.builds,
            reason=r.reason,
            open_questions=len(r.open_questions),
        )
        for r in a.stages
    ]
    info.files = _files(result, out)
    plan = a.status(Stage.PLAN)
    pending_text = [q for q, s in a.report.question_states.items() if s == "text"]
    if a.global_errors or (plan is not None and plan.status is Status.INVALID):
        info.state = ProjectState.NEEDS_MODEL
        info.message = "в модели ошибки — см. report.json, issues"
    elif pending_text:
        info.state = ProjectState.NEEDS_MODEL
        info.message = f"текстовые ответы ждут разбора анализатором: {', '.join(pending_text)}"
    elif a.open_questions and info.round <= MAX_ROUNDS:
        info.state = ProjectState.NEEDS_ANSWERS
        info.message = f"открытых вопросов: {a.open_questions} — GET /projects/{info.id}/questions"
    elif result.built:
        info.state = ProjectState.READY
        info.message = (
            "проект собран по допущениям: раунды вопросов кончились"
            if a.open_questions
            else "проект собран"
        )
    else:
        info.state = ProjectState.INSUFFICIENT
        info.message = "мало данных: план построить нельзя — см. report.md"


class Workflow:
    def __init__(self, storage: Storage, analyzer: Analyzer) -> None:
        self.storage = storage
        self.analyzer = analyzer

    def _set_busy(self, project_id: str, state: ProjectState) -> ProjectInfo:
        info = self.storage.load(project_id)
        if info.state.busy:
            raise ConflictError(f"проект занят: {info.state.value}")
        info.state = state
        info.message = ""
        self.storage.save(info)
        return info

    def start_analysis(self, project_id: str) -> ProjectInfo:
        return self._set_busy(project_id, ProjectState.ANALYZING)

    def run_analysis(self, project_id: str) -> None:
        """Background part: analysis and assessment."""
        with self.storage.lock(project_id):
            info = self.storage.load(project_id)
            try:
                gate = self._gate(project_id)
                if not gate.ok:  # do not call the model: no tokens spent on an unusable source
                    info.state, info.message = ProjectState.REJECTED, gate.message
                    self.storage.save(info)
                    return
                result = self.analyzer.analyze(self.storage.path(project_id), info.round + 1)
                _count(info, result)
                if not result.done:
                    info.state = ProjectState.NEEDS_MODEL
                    info.message = result.message
                else:
                    info.round += 1
                    self._evaluate(info)
            except Exception as exc:
                log.exception("анализ проекта %s", project_id)
                info.state, info.message = ProjectState.FAILED, f"ошибка анализа: {exc}"
            self.storage.save(info)

    def _gate(self, project_id: str) -> Gate:
        """The "failed" gate applies only to an analyzer that reads the sources, and only while
        there
        is no model (it does not check a model uploaded by an operator)."""
        path = self.storage.path(project_id)
        has_model = any((path / f).exists() for f in MODEL_FILES)
        if not self.analyzer.reads_sources or has_model:
            return Gate(True)
        return check_sources(path / SOURCE_DIR)

    def submit_answers(self, project_id: str, answers: AnswersIn) -> ProjectInfo:
        """Accept the round answers; then run_answers in the background."""
        info = self.storage.load(project_id)
        if info.state is not ProjectState.NEEDS_ANSWERS:
            raise ConflictError(
                f"ответы принимаются в состоянии needs_answers, сейчас {info.state.value}"
            )
        report = json.loads(
            (self.storage.path(project_id) / OUT_DIR / REPORT_JSON).read_text("utf-8")
        )
        open_ids = {q["id"] for q in report["questions"] if q["state"] == "open"}
        unknown = sorted(set(answers.answers) - open_ids)
        if unknown:
            raise ConflictError(f"нет открытых вопросов: {', '.join(unknown)}")
        path = self.storage.path(project_id) / ANSWERS_FILE
        current = (
            Answers.model_validate(yaml.safe_load(path.read_text("utf-8")) or {})
            if path.exists()
            else Answers()
        )
        merged = current.model_copy(update={"answers": {**current.answers, **answers.answers}})
        path.write_text(dump_answers(merged), encoding="utf-8")
        self.storage.save_round(
            project_id,
            info.round,
            "answers.json",
            {k: _plain(v) for k, v in answers.answers.items()},
        )
        return self._set_busy(project_id, ProjectState.BUILDING)

    def run_answers(self, project_id: str, has_text: bool) -> None:
        """Background part after answers: the analyzer handles text answers first, then the
        assessment.
        """
        with self.storage.lock(project_id):
            info = self.storage.load(project_id)
            try:
                info.round += 1
                if has_text:
                    _count(info, self.analyzer.analyze(self.storage.path(project_id), info.round))
                self._evaluate(info)
            except Exception as exc:
                log.exception("ответы проекта %s", project_id)
                info.state, info.message = ProjectState.FAILED, f"ошибка сборки: {exc}"
            self.storage.save(info)

    def _evaluate(self, info: ProjectInfo) -> None:
        path = self.storage.path(info.id)
        result = build_project(path)
        _apply(info, result, path / OUT_DIR)
        report = json.loads((path / OUT_DIR / REPORT_JSON).read_text("utf-8"))
        self.storage.save_round(info.id, info.round, "report.json", report)


def _count(info: ProjectInfo, result: AnalysisResult) -> None:
    info.llm_calls += result.calls
    info.llm_cost_usd = round(info.llm_cost_usd + result.cost_usd, 4)


def _plain(value: float | str | Accept | TextAnswer) -> object:
    if isinstance(value, Accept | TextAnswer):
        return value.model_dump()
    return value
