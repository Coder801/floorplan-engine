"""Примитивы страницы источника — общий вход разбора, какой бы ни был формат файла.

Адаптер формата (vector.py — векторный PDF; растр — позже) превращает страницу в надписи
и отрезки; дальше всё считает analysis.py, не зная, откуда они пришли. Координаты — в
единицах источника (pt у PDF, px у картинки) от левого нижнего угла листа, Y вверх.
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
        """Точка лежит на отрезке (с допуском)."""
        dx, dy = self.x1 - self.x0, self.y1 - self.y0
        n2 = dx * dx + dy * dy
        if n2 == 0:
            return abs(x - self.x0) <= tol and abs(y - self.y0) <= tol
        t = max(0.0, min(1.0, ((x - self.x0) * dx + (y - self.y0) * dy) / n2))
        px, py = self.x0 + t * dx, self.y0 + t * dy
        return bool((x - px) ** 2 + (y - py) ** 2 <= tol * tol)


@dataclass
class Label:
    """Надпись: одна строка символов одного направления. Координаты — pt, Y вверх."""

    text: str
    direction: Direction
    a0: float  # начало и конец вдоль направления текста
    a1: float
    base: float  # базовая линия: Y для горизонтальной, X для вертикальной
    perp: float  # середина поперёк направления
    height: float
    confidence: float = 1.0  # 1 — вектор (точно); у OCR — его оценка

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
    """Страница источника как примитивы."""

    file: str
    page: int
    width: float
    height: float
    labels: list[Label] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    unit: str = "pt"  # единица координат: pt у векторного PDF, px у картинки
    source: Literal["vector", "raster"] = "vector"
    tolerance: float = 1.0  # во сколько раз шире допуски разбора (растр — неточные концы)
