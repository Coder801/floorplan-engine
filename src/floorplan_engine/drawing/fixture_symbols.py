"""Сантехприборы на плане контуром (лист «Сантехника»): ванна, душ, унитаз, умывальник,
мойка, машины, бойлер — чтобы прибор узнавался, а не был штриховкой, как стена.

Только геометрия, без ezdxf: контуры — ломаные в мм модели. Прибор стоит у своей стены:
локальные оси — u вдоль стены (0 — середина подводки), v от стены в помещение (0 — грань
стены или лицо короба, на котором прибор висит). Размеры — типовые (`SIZES`), это рисунок,
а не обмер: ванна и поддон, заданные препятствием, рисуются в его контуре.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.plumbing import FixtureType

ARC_STEP_DEG = 15.0  # шаг ломаной дуг и эллипсов
# Типовой размер прибора на плане, мм: вдоль стены × от стены
SIZES: dict[FixtureType, tuple[float, float]] = {
    FixtureType.BATH: (1700.0, 750.0),
    FixtureType.SHOWER: (900.0, 900.0),
    FixtureType.WC: (380.0, 680.0),
    FixtureType.WC_INSTALLATION: (360.0, 540.0),
    FixtureType.SINK: (550.0, 450.0),
    FixtureType.KITCHEN_SINK: (500.0, 500.0),
    FixtureType.WASHER: (600.0, 600.0),
    FixtureType.DISHWASHER: (600.0, 600.0),
    FixtureType.BOILER: (450.0, 450.0),
    FixtureType.HYGIENIC_SHOWER: (120.0, 160.0),
}


@dataclass(frozen=True)
class Shape:
    """Ломаная контура; closed — замкнута."""

    points: tuple[Vec, ...]
    closed: bool = True


@dataclass(frozen=True)
class Frame:
    """Место прибора: точка на стене (или на лице короба), вдоль стены и в помещение."""

    origin: Vec
    along: Vec
    inward: Vec

    def at(self, u: float, v: float) -> Vec:
        return self.origin + self.along * u + self.inward * v


def _rect(f: Frame, u0: float, v0: float, u1: float, v1: float) -> Shape:
    return Shape((f.at(u0, v0), f.at(u1, v0), f.at(u1, v1), f.at(u0, v1)))


def _rounded(f: Frame, u0: float, v0: float, u1: float, v1: float, r: float) -> Shape:
    """Прямоугольник со скруглёнными углами радиуса r."""
    r = min(r, (u1 - u0) / 2, (v1 - v0) / 2)
    pts: list[Vec] = []
    corners = ((u1 - r, v0 + r, -90.0), (u1 - r, v1 - r, 0.0), (u0 + r, v1 - r, 90.0))
    for cu, cv, start in (*corners, (u0 + r, v0 + r, 180.0)):
        for k in range(int(90 / ARC_STEP_DEG) + 1):
            a = math.radians(start + k * ARC_STEP_DEG)
            pts.append(f.at(cu + r * math.cos(a), cv + r * math.sin(a)))
    return Shape(tuple(pts))


def _ellipse(f: Frame, cu: float, cv: float, ru: float, rv: float) -> Shape:
    n = int(360 / ARC_STEP_DEG)
    return Shape(
        tuple(
            f.at(cu + ru * math.cos(2 * math.pi * k / n), cv + rv * math.sin(2 * math.pi * k / n))
            for k in range(n)
        )
    )


def _line(f: Frame, u0: float, v0: float, u1: float, v1: float) -> Shape:
    return Shape((f.at(u0, v0), f.at(u1, v1)), closed=False)


def symbol(kind: FixtureType, f: Frame, size: tuple[float, float] | None = None) -> list[Shape]:
    """Контур прибора; size — вдоль стены × от стены (ванна и поддон — по препятствию),
    иначе типовой SIZES. Первая фигура — внешний контур (место прибора на плане)."""
    w, d = size if size is not None else SIZES[kind]
    h = w / 2
    if kind is FixtureType.BATH:
        return [
            _rounded(f, -h, 0, h, d, 60),
            _rounded(f, -h + 70, 70, h - 70, d - 70, d / 2 - 70),
            _ellipse(f, -h + 70 + (d / 2 - 70), d / 2, 25, 25),  # слив у торца
        ]
    if kind is FixtureType.SHOWER:
        return [
            _rect(f, -h, 0, h, d),
            _line(f, -h, 0, h, d),
            _line(f, -h, d, h, 0),
            _ellipse(f, 0, d / 2, 45, 45),  # трап
        ]
    if kind is FixtureType.WC_INSTALLATION:
        return [_ellipse(f, 0, d / 2, h, d / 2), _ellipse(f, 0, d / 2 + 30, h - 60, d / 2 - 90)]
    if kind is FixtureType.WC:
        tank = 180.0
        bowl = d - tank
        return [
            _rect(f, -h, 0, h, tank),
            _ellipse(f, 0, tank + bowl / 2, h - 20, bowl / 2),
            _ellipse(f, 0, tank + bowl / 2 + 20, h - 80, bowl / 2 - 70),
        ]
    if kind is FixtureType.SINK:
        return [
            _rounded(f, -h, 0, h, d, 40),
            _ellipse(f, 0, d * 0.55, h - 70, d * 0.32),
            _ellipse(f, 0, 70, 20, 20),  # смеситель
        ]
    if kind is FixtureType.KITCHEN_SINK:
        return [
            _rect(f, -h, 0, h, d),
            _rounded(f, -h + 60, 110, h - 60, d - 50, 50),
            _ellipse(f, 0, 60, 20, 20),  # смеситель
        ]
    if kind is FixtureType.WASHER:
        return [_rect(f, -h, 0, h, d), _ellipse(f, 0, d / 2, h * 0.65, h * 0.65)]
    if kind is FixtureType.DISHWASHER:
        return [
            _rect(f, -h, 0, h, d),
            _rect(f, -h + 60, 60, h - 60, d - 60),
            _line(f, -h + 60, d / 2, h - 60, d / 2),
        ]
    if kind is FixtureType.BOILER:
        return [_ellipse(f, 0, d / 2, h, d / 2), _ellipse(f, 0, d / 2, h * 0.3, h * 0.3)]
    # Гигиенический душ: лейка на шланге
    return [_ellipse(f, 0, d - h, h, h), _line(f, 0, 0, 0, d - 2 * h)]
