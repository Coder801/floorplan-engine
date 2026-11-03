"""Raster accuracy bench: vector PDF → image → raster parsing, compared with the vector.

The vector is the reference: its labels and coordinates are exact. The same sheet is
rendered and parsed as raster (raster.py), dimensions are matched by position on the sheet:

- found: at the place of a vector dimension the raster found one with the same label;
- misread: it found a dimension but the label differs (an OCR error, a dangerous one: it
  gives a wrong wall);
- missed: the raster found nothing at the place of a vector dimension;
- extra: a raster dimension where the vector has none.

Scale is compared separately: the raster must find the same mm/pt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from floorplan_engine.service.facts.analysis import Dimension, PageFacts, page_facts
from floorplan_engine.service.facts.raster import RENDER_DPI, read_raster_pdf
from floorplan_engine.service.facts.vector import read_pdf

POSITION_TOL = 4.0  # pt: dimensions at one place have line and ends no farther apart than this


@dataclass
class PageBench:
    page: int
    vector_dims: int
    found: int = 0
    misread: list[tuple[int, int]] = field(default_factory=list)  # (vector, raster)
    missed: int = 0
    extra: int = 0
    vector_scale: float | None = None
    raster_scale: float | None = None

    @property
    def recall(self) -> float:
        """Share of vector dimensions the raster read correctly."""
        return self.found / self.vector_dims if self.vector_dims else 1.0

    @property
    def scale_error(self) -> float | None:
        """Raster scale deviation from the vector, %; None if either has no scale."""
        if not self.vector_scale or not self.raster_scale:
            return None
        return abs(self.raster_scale / self.vector_scale - 1) * 100


def same_place(a: Dimension, b: Dimension, tol: float = POSITION_TOL) -> bool:
    return (
        a.direction == b.direction
        and abs(a.line - b.line) <= tol
        and abs(a.start - b.start) <= tol
        and abs(a.end - b.end) <= tol
    )


def compare(vector: PageFacts, raster: PageFacts) -> PageBench:
    """Dimension check for one page: for each vector dimension, a raster one at the same place."""
    bench = PageBench(vector.page, len(vector.dimensions))
    bench.vector_scale, bench.raster_scale = vector.scale, raster.scale
    used: set[int] = set()
    for v in vector.dimensions:
        k = next(
            (i for i, r in enumerate(raster.dimensions) if i not in used and same_place(v, r)),
            None,
        )
        if k is None:
            bench.missed += 1
            continue
        used.add(k)
        r = raster.dimensions[k]
        if r.value == v.value:
            bench.found += 1
        else:
            bench.misread.append((v.value, r.value))
    bench.extra = len(raster.dimensions) - len(used)
    return bench


def run(pdf: Path, dpi: int = RENDER_DPI) -> list[PageBench]:
    vector = [page_facts(s) for s in read_pdf(pdf)]
    raster = [page_facts(s) for s in read_raster_pdf(pdf, dpi=dpi)]
    return [compare(v, r) for v, r in zip(vector, raster, strict=True)]


def report(name: str, pages: list[PageBench]) -> str:
    out = [f"### {name}", "| Стр. | Вектор | Верно | Ошибка OCR | Пропуск | Лишние | Масштаб, % |"]
    out.append("| --- | --- | --- | --- | --- | --- | --- |")
    for p in pages:
        err = "—" if p.scale_error is None else f"{p.scale_error:.2f}"
        wrong = ", ".join(f"{v}→{r}" for v, r in p.misread) or "0"
        out.append(
            f"| {p.page} | {p.vector_dims} | {p.found} ({p.recall:.0%}) | {wrong} | "
            f"{p.missed} | {p.extra} | {err} |"
        )
    return "\n".join(out)
