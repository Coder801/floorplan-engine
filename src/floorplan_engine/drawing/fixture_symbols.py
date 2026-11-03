"""Plumbing fixtures drawn as outlines on the plan ("Plumbing" sheet): bath, shower, WC, basin,
kitchen sink, machines, boiler, so a fixture is recognisable instead of hatched like a wall.

Geometry only, no ezdxf: outlines are polylines in model mm. A fixture stands at its wall:
local axes are u along the wall (0 is the middle of the supply) and v from the wall into the
room (0 is the wall face or the face of the box the fixture hangs on). Sizes are typical
(`SIZES`): this is a drawing, not a survey. A bath or shower tray given as an obstacle is drawn
inside that outline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.plumbing import FixtureType

ARC_STEP_DEG = 15.0  # polyline step for arcs and ellipses
# Typical fixture size on the plan, mm: along the wall × away from the wall
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
    """Outline polyline; closed means it is closed."""

    points: tuple[Vec, ...]
    closed: bool = True


@dataclass(frozen=True)
class Frame:
    """Fixture place: a point on the wall (or on the box face), along the wall and into the room."""

    origin: Vec
    along: Vec
    inward: Vec

    def at(self, u: float, v: float) -> Vec:
        return self.origin + self.along * u + self.inward * v


def _rect(f: Frame, u0: float, v0: float, u1: float, v1: float) -> Shape:
    return Shape((f.at(u0, v0), f.at(u1, v0), f.at(u1, v1), f.at(u0, v1)))


def _rounded(f: Frame, u0: float, v0: float, u1: float, v1: float, r: float) -> Shape:
    """Rectangle with rounded corners of radius r."""
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
    """Fixture outline; size is along the wall × away from the wall (bath and tray: from the
    obstacle), otherwise the typical SIZES. The first shape is the outer outline (fixture
    footprint)."""
    w, d = size if size is not None else SIZES[kind]
    h = w / 2
    if kind is FixtureType.BATH:
        return [
            _rounded(f, -h, 0, h, d, 60),
            _rounded(f, -h + 70, 70, h - 70, d - 70, d / 2 - 70),
            _ellipse(f, -h + 70 + (d / 2 - 70), d / 2, 25, 25),  # drain at the end
        ]
    if kind is FixtureType.SHOWER:
        return [
            _rect(f, -h, 0, h, d),
            _line(f, -h, 0, h, d),
            _line(f, -h, d, h, 0),
            _ellipse(f, 0, d / 2, 45, 45),  # floor drain
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
            _ellipse(f, 0, 70, 20, 20),  # mixer
        ]
    if kind is FixtureType.KITCHEN_SINK:
        return [
            _rect(f, -h, 0, h, d),
            _rounded(f, -h + 60, 110, h - 60, d - 50, 50),
            _ellipse(f, 0, 60, 20, 20),  # mixer
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
    # Hygienic shower: a hand shower on a hose
    return [_ellipse(f, 0, d - h, h, h), _line(f, 0, 0, 0, d - 2 * h)]
