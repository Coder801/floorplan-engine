"""Порог «не удалось»: можно ли по источникам что-то построить — до вызова модели.

Если ни один чертёж проекта не даёт геометрии, модель не вызывается: проект сразу получает
отказ с причиной по каждому файлу, токены не тратятся. Чертёж годится, если хотя бы на одной
его странице:

- найден масштаб (по согласным размерам, как в analysis._scale);
- размеров не меньше MIN_DIMS;
- средняя уверенность в подписях не ниже MIN_CONFIDENCE (у вектора — 1, у OCR — оценка).

Текстовое описание (.md, .txt) годится всегда: его разбирает модель. Рисунок от руки сюда
не проходит сам: на нём нет ни масштаба, ни размерных линий (правило 6 CLAUDE.md).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path

from shtroba.service.facts.analysis import PageFacts, page_facts
from shtroba.service.facts.source import is_image, read_source

MIN_DIMS = 4
MIN_CONFIDENCE = 0.8
TEXT_TYPES = frozenset({".md", ".txt"})
ADVICE = "Пришлите PDF-экспорт из программы проектирования или скан чертежа от 300 dpi."


@dataclass
class Gate:
    ok: bool
    reasons: list[str] = field(default_factory=list)  # почему файл не годится, по файлам

    @property
    def message(self) -> str:
        if self.ok:
            return ""
        return "По источникам ничего не построить: " + "; ".join(self.reasons) + ". " + ADVICE


def page_problem(f: PageFacts) -> str | None:
    """Что не так со страницей; None — годится."""
    if f.scale is None:
        return "масштаб не найден"
    if len(f.dimensions) < MIN_DIMS:
        return f"размеров {len(f.dimensions)}, нужно от {MIN_DIMS}"
    confidence = statistics.mean(d.confidence for d in f.dimensions)
    if confidence < MIN_CONFIDENCE:
        return f"подписи читаются неуверенно ({confidence:.0%})"
    return None


def file_problem(path: Path) -> str | None:
    """Что не так с файлом-чертежом; None — хотя бы одна страница годится."""
    try:
        pages = [page_facts(s) for s in read_source(path)]
    except Exception as exc:  # битый файл — тоже причина отказа, не падение сервиса
        return f"не открывается ({exc})"
    problems = [page_problem(f) for f in pages]
    if any(p is None for p in problems):
        return None
    return problems[0] if problems else "пустой файл"


def check_sources(source_dir: Path) -> Gate:
    """Годятся ли источники проекта для анализа."""
    files = sorted(p for p in source_dir.iterdir() if p.is_file() and not p.name.startswith("."))
    if any(p.suffix.lower() in TEXT_TYPES for p in files):
        return Gate(True)
    drawings = [p for p in files if p.suffix.lower() == ".pdf" or is_image(p)]
    if not drawings:
        return Gate(False, ["нет ни чертежей (PDF, картинки), ни текстового описания"])
    reasons = []
    for p in drawings:
        problem = file_problem(p)
        if problem is None:
            return Gate(True)
        reasons.append(f"{p.name} — {problem}")
    return Gate(False, reasons)
