"""The "failed" gate: whether anything can be built from the sources, before calling the model.

If no drawing of the project gives geometry, the model is not called: the project is rejected
right away with a reason for each file, and no tokens are spent. A drawing is usable if at
least one of its pages has:

- a scale found (from consistent dimensions, as in analysis._scale);
- at least MIN_DIMS dimensions;
- an average label confidence of at least MIN_CONFIDENCE (1 for vector, an estimate for OCR).

A text description (.md, .txt) is always usable: the model parses it. A hand drawing does not
pass on its own: it has no scale and no dimension lines (rule 6 in CLAUDE.md).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path

from floorplan_engine.service.facts.analysis import PageFacts, page_facts
from floorplan_engine.service.facts.source import CAD_PENDING, is_cad, is_image, read_source

MIN_DIMS = 4
MIN_CONFIDENCE = 0.8
TEXT_TYPES = frozenset({".md", ".txt"})
ADVICE = "Пришлите PDF-экспорт из программы проектирования или скан чертежа от 300 dpi."


@dataclass
class Gate:
    ok: bool
    reasons: list[str] = field(default_factory=list)  # why each file is unusable, by file

    @property
    def message(self) -> str:
        if self.ok:
            return ""
        return "По источникам ничего не построить: " + "; ".join(self.reasons) + ". " + ADVICE


def page_problem(f: PageFacts) -> str | None:
    """What is wrong with the page; None if it is usable."""
    if f.scale is None:
        return "масштаб не найден"
    if len(f.dimensions) < MIN_DIMS:
        return f"размеров {len(f.dimensions)}, нужно от {MIN_DIMS}"
    confidence = statistics.mean(d.confidence for d in f.dimensions)
    if confidence < MIN_CONFIDENCE:
        return f"подписи читаются неуверенно ({confidence:.0%})"
    return None


def file_problem(path: Path) -> str | None:
    """What is wrong with the drawing file; None if at least one page is usable."""
    try:
        pages = [page_facts(s) for s in read_source(path)]
    except Exception as exc:  # a broken file is also a reason to reject, not a service crash
        return f"не открывается ({exc})"
    problems = [page_problem(f) for f in pages]
    if any(p is None for p in problems):
        return None
    return problems[0] if problems else "пустой файл"


def check_sources(source_dir: Path) -> Gate:
    """Whether the project sources are usable for analysis."""
    files = sorted(p for p in source_dir.iterdir() if p.is_file() and not p.name.startswith("."))
    if any(p.suffix.lower() in TEXT_TYPES for p in files):
        return Gate(True)
    drawings = [p for p in files if p.suffix.lower() == ".pdf" or is_image(p)]
    cad = [f"{p.name} — {CAD_PENDING}" for p in files if is_cad(p)]
    if not drawings:
        return Gate(False, cad or ["нет ни чертежей (PDF, картинки), ни текстового описания"])
    reasons = cad
    for p in drawings:
        problem = file_problem(p)
        if problem is None:
            return Gate(True)
        reasons.append(f"{p.name} — {problem}")
    return Gate(False, reasons)
