"""Анализатор: источники проекта → intake.yaml и YAML этапов.

Интерфейс один для всех реализаций; сервис не знает, кто пишет модель.
Сейчас — ручной анализатор: модель загружает оператор (PUT /projects/{id}/model/...).
В фазе 4 здесь появится LLM-анализатор (подписка Claude или API-ключ).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from floorplan_engine.model.intake import ANSWERS_FILE, INTAKE_FILE
from floorplan_engine.validation.issues import ROOM_FILE

MODEL_FILES = (INTAKE_FILE, ROOM_FILE, "electrical.yaml")
# Что оператор может загрузить готовым: модель и накопленные ответы (эталонные проекты)
OPERATOR_FILES = (*MODEL_FILES, ANSWERS_FILE)


@dataclass(frozen=True)
class AnalysisResult:
    done: bool  # модель на месте, можно оценивать
    message: str = ""  # если не done — что нужно; если done — итог анализа
    cost_usd: float = 0.0  # стоимость вызовов LLM в этом анализе (оценка)
    calls: int = 0  # вызовов LLM


class Analyzer(Protocol):
    # Анализатор сам читает source/ (LLM): перед ним проверяется порог «не удалось»
    reads_sources: bool

    def analyze(self, project: Path, round_no: int) -> AnalysisResult:
        """Прочитать source/ (и answers.yaml с текстовыми ответами), записать intake.yaml и
        YAML этапов в папку проекта."""
        ...


class ManualAnalyzer:
    """Модель пишет человек (или Claude Code в репозитории) и загружает через API."""

    reads_sources = False

    def analyze(self, project: Path, round_no: int) -> AnalysisResult:
        if not (project / INTAKE_FILE).exists() and not (project / ROOM_FILE).exists():
            return AnalysisResult(
                False,
                f"ручной анализ: загрузите {INTAKE_FILE} и YAML этапов "
                "(PUT /projects/{id}/model/{файл}) и запустите анализ снова",
            )
        return AnalysisResult(True)
