"""Analyzer: project sources → intake.yaml and stage YAML.

One interface for all implementations; the service does not know who writes the model.
Currently the manual analyzer: an operator uploads the model (PUT /projects/{id}/model/...).
Phase 4 adds an LLM analyzer here (Claude subscription or API key).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from floorplan_engine.model.intake import ANSWERS_FILE, INTAKE_FILE
from floorplan_engine.model.plumbing import PLUMBING_FILE
from floorplan_engine.validation.issues import ROOM_FILE

MODEL_FILES = (INTAKE_FILE, ROOM_FILE, "electrical.yaml", PLUMBING_FILE)
# What an operator may upload ready-made: the model and accumulated answers (reference projects)
OPERATOR_FILES = (*MODEL_FILES, ANSWERS_FILE)


@dataclass(frozen=True)
class AnalysisResult:
    done: bool  # the model is in place and can be assessed
    message: str = ""  # if not done: what is needed; if done: the analysis summary
    cost_usd: float = 0.0  # cost of LLM calls in this analysis (estimate)
    calls: int = 0  # LLM calls


class Analyzer(Protocol):
    # The analyzer reads source/ itself (LLM): the "failed" gate is checked before it
    reads_sources: bool

    def analyze(self, project: Path, round_no: int) -> AnalysisResult:
        """Read source/ (and answers.yaml with text answers), write intake.yaml and the stage YAML
        into
        the project folder."""
        ...


class ManualAnalyzer:
    """A human (or Claude Code in the repository) writes the model and uploads it through the
    API.
    """

    reads_sources = False

    def analyze(self, project: Path, round_no: int) -> AnalysisResult:
        if not (project / INTAKE_FILE).exists() and not (project / ROOM_FILE).exists():
            return AnalysisResult(
                False,
                f"ручной анализ: загрузите {INTAKE_FILE} и YAML этапов "
                "(PUT /projects/{id}/model/{файл}) и запустите анализ снова",
            )
        return AnalysisResult(True)
