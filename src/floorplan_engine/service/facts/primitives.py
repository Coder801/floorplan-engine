"""Source page primitives: the shared parser input, whatever the file format.

A format adapter (vector.py for vector PDF; raster later) turns a page into labels and
segments; analysis.py computes everything else without knowing where they came from.
Coordinates are in source units (pt for PDF, px for an image) from the bottom-left corner of
the sheet, Y up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

Direction = Literal["h", "v"]
NUMBER = re.compile(r"\d{1,3}(?: \d{3})+|\d+")


@dataclass(frozen=True)
class Segment:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def length(self) -> float:
        return float(((self.x1 - self.x0) ** 2 + (self.y1 - self.y0) ** 2) ** 0.5)

    @property
    def direction(self) -> Direction | None:
        if abs(self.y1 - self.y0) < 0.2 and abs(self.x1 - self.x0) >= 0.2:
            return "h"
        if abs(self.x1 - self.x0) < 0.2 and abs(self.y1 - self.y0) >= 0.2:
            return "v"
        return None

    def passes_near(self, x: float, y: float, tol: float) -> bool:
        """The point lies on the segment (within tolerance)."""
        dx, dy = self.x1 - self.x0, self.y1 - self.y0
        n2 = dx * dx + dy * dy
        if n2 == 0:
            return abs(x - self.x0) <= tol and abs(y - self.y0) <= tol
        t = max(0.0, min(1.0, ((x - self.x0) * dx + (y - self.y0) * dy) / n2))
        px, py = self.x0 + t * dx, self.y0 + t * dy
        return bool((x - px) ** 2 + (y - py) ** 2 <= tol * tol)


@dataclass
class Label:
    """Label: one line of characters in one direction. Coordinates in pt, Y up."""

    text: str
    direction: Direction
    a0: float  # start and end along the text direction
    a1: float
    base: float  # baseline: Y for horizontal, X for vertical
    perp: float  # middle across the direction
    height: float
    confidence: float = 1.0  # 1 for vector (exact); the OCR estimate for OCR

    @property
    def mid(self) -> float:
        return (self.a0 + self.a1) / 2

    @property
    def number(self) -> int | None:
        return int(self.text.replace(" ", "")) if NUMBER.fullmatch(self.text) else None

    def point(self) -> tuple[float, float]:
        return (self.mid, self.perp) if self.direction == "h" else (self.perp, self.mid)


@dataclass
class Sheet:
    """A source page as primitives."""

    file: str
    page: int
    width: float
    height: float
    labels: list[Label] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    unit: str = "pt"  # coordinate unit: pt for a vector PDF, px for an image
    source: Literal["vector", "raster"] = "vector"
    tolerance: float = 1.0  # how much wider the parser tolerances are (raster has imprecise ends)
