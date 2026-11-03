"""Label placement on the sheet without overlaps (feedback 2026-10-28: electrical labels sat on
walls, doors, symbols and each other).

A label is a block of lines. Candidates are spots around the symbol: for a wall point, on the
room side, shifted along the wall and away from it; for a ceiling point, eight sides; farther
out, a far search in 16 directions. Each spot has a penalty: touching an already placed label,
a symbol, a door or an LED strip, sitting on a wall (outside exterior walls is free: in a
cramped room the label goes outside the flat outline); the leader crossing a label or a
symbol; plus distance from the symbol. The spot with the lowest penalty wins; a label farther
than `Metrics.leader_min` from the symbol gets a leader.

Geometry is model mm; the caller converts "on sheet" sizes (`scale.sheet`).
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from shapely import STRtree
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from floorplan_engine.model.geometry import Vec

# Penalties: label on label is worst, then symbol and door, then running onto a wall
HIT_LABEL = 10_000.0
HIT_SYMBOL = 5_000.0
HIT_ZONE = 3_000.0  # door, LED strip
HIT_FRAME = 6_000.0  # label leaves the plan frame: inflates the view and changes the sheet scale
HIT_LEADER = 2_000.0  # leader crosses a label or someone else's symbol
HIT_ROOM = 1_500.0  # label enters another room: the installer looks for it in the wrong place
PAD = 0.3  # margin around a label, fraction of line height: neighbours do not touch
ON_WALL = 2_500.0  # label touches a wall
ON_WALL_AREA = 4_000.0  # plus × fraction of the block area on walls
# Distance is counted in search steps (sheet mm), so it does not depend on scale
ALONG_COST = 1.0  # per step along the wall
AWAY_COST = 1.5  # per step away from the wall (farther from the symbol, the link reads worse)
FAR_COST = 2.0  # per step in the far search (with a leader)
LEADER_COST = 20.0  # the leader itself


class Align(Enum):
    """Line alignment inside the block: left, right, centre."""

    LEFT = "left"
    RIGHT = "right"
    CENTER = "center"


@dataclass(frozen=True)
class Placed:
    """Placed label: lines (centre of each line by height), alignment, block extent and the
    leader (from symbol to block) or None."""

    lines: list[tuple[str, Vec]]
    align: Align
    rect: tuple[float, float, float, float]
    leader: tuple[Vec, Vec] | None


@dataclass(frozen=True)
class Metrics:
    """Text sizes in model mm: line height, line step, gap from the symbol, search step and how
    many steps may be taken near the symbol (reach) and in the far search with a leader (far);
    a leader is added when the label is farther than leader_min."""

    line_h: float
    step: float
    gap: float
    probe: float
    reach: int
    far: int
    leader_min: float


class LabelPlacer:
    """Places labels one by one; each placed label becomes an obstacle for the next.

    walls is the wall silhouette (labels do not sit on it);
    symbols are symbol extents (neither label nor leader touches them); zones are where a label
    may not go but a leader may cross: door swings, LED strips at walls; frame is the frame a
    label must stay inside (plan extent plus a band); rooms are rooms by id: a label does not
    enter another room (outside the flat outline is allowed)."""

    def __init__(
        self,
        walls: BaseGeometry,
        symbols: Sequence[BaseGeometry],
        zones: Sequence[BaseGeometry],
        metrics: Metrics,
        frame: BaseGeometry | None = None,
        rooms: Mapping[str, BaseGeometry] | None = None,
    ) -> None:
        self.walls = walls
        self.frame = frame
        self.room_ids = list(rooms or {})
        self.rooms = [(rooms or {})[r] for r in self.room_ids]
        self.room_tree = STRtree(self.rooms)
        self.symbols = list(symbols)
        self.symbol_tree = STRtree(self.symbols)
        self.zones = list(zones)
        self.zone_tree = STRtree(self.zones)
        self.taken: list[BaseGeometry] = []
        self.m = metrics

    def place(
        self,
        lines: Sequence[str],
        widths: Sequence[float],
        pos: Vec,
        inward: Vec | None,
        depth: float,
        own: BaseGeometry | None = None,
        room: str | None = None,
    ) -> Placed:
        """Label for the symbol at pos: inward points into the room (None for ceiling), depth is how
        far the symbol sticks out from the wall (radius for a ceiling one); own is the extent of its
        own symbols, which do not block the label; room is the symbol's room."""
        w = max(widths)
        h = self.m.step * (len(lines) - 1) + self.m.line_h
        best: tuple[float, tuple[float, float, float, float], Align] | None = None
        for rect, align, dist in self._candidates(w, h, pos, inward, depth):
            if best is not None and dist >= best[0]:
                continue  # penalty is never negative, so a farther spot is not better
            cost = dist + self._penalty(rect, own, room)
            leader = self._leader(rect, pos, inward, depth)
            if leader is not None:
                cost += self._leader_penalty(leader, own)
            if best is None or cost < best[0]:
                best = (cost, rect, align)
                if cost == 0.0:
                    break
        assert best is not None
        _, rect, align = best
        pad = self.m.line_h * PAD
        self.taken.append(box(*rect).buffer(pad, join_style="mitre"))
        leader = self._leader(rect, pos, inward, depth)
        if leader is not None:
            self.taken.append(
                LineString([leader[0].as_tuple(), leader[1].as_tuple()]).buffer(pad / 2)
            )
        return Placed(self._lines(lines, rect, align), align, rect, leader)

    # --- candidates ----------------------------------------------------------

    def _candidates(
        self, w: float, h: float, pos: Vec, inward: Vec | None, depth: float
    ) -> Iterator[tuple[tuple[float, float, float, float], Align, float]]:
        """Spots in order of increasing distance: near the symbol, then the far search."""
        m = self.m
        base = depth + m.gap
        if inward is None:
            for away in range(m.reach + 1):
                for i, v in enumerate(_DIRS[:8]):
                    rect, align = _beside(pos + v * (base + away * m.probe), v, w, h)
                    yield rect, align, away * AWAY_COST + i * 0.01
        else:
            n, u = inward, inward.left()  # into the room and along the wall
            shifts = [0] + [s for k in range(1, m.reach + 1) for s in (k, -k)]
            for away in range(m.reach + 1):
                for s in shifts:
                    c = pos + n * (base + away * m.probe) + u * (s * m.probe)
                    rect, align = _beside(c, n, w, h)
                    yield rect, align, abs(s) * ALONG_COST + away * AWAY_COST
        # No room nearby: go farther in 16 directions, with a leader
        for away in range(m.reach + 1, m.far + 1, 2):
            for v in _DIRS:  # also across the wall, outside the flat: _penalty charges for the wall
                rect, align = _beside(pos + v * (base + away * m.probe), v, w, h)
                yield rect, align, away * FAR_COST + LEADER_COST

    # --- penalty -------------------------------------------------------------

    def _penalty(
        self, rect: tuple[float, float, float, float], own: BaseGeometry | None, room: str | None
    ) -> float:
        b = box(*rect)
        cost = 0.0
        if room is not None and any(
            self.room_ids[j] != room and b.intersection(self.rooms[j]).area > 0
            for j in self.room_tree.query(b)
        ):
            cost += HIT_ROOM
        if any(b.intersection(t).area > 0 for t in self.taken):
            cost += HIT_LABEL
        for j in self.symbol_tree.query(b):
            g = self.symbols[j]
            if own is not None and g.within(own.buffer(1e-6)):
                continue
            if b.intersection(g).area > 0:
                cost += HIT_SYMBOL
                break
        if any(b.intersection(self.zones[j]).area > 0 for j in self.zone_tree.query(b)):
            cost += HIT_ZONE
        if self.frame is not None and not b.within(self.frame):
            cost += HIT_FRAME
        if not self.walls.is_empty:
            on = b.intersection(self.walls).area / b.area
            if on > 0:
                cost += ON_WALL + ON_WALL_AREA * on
        return cost

    def _leader_penalty(self, leader: tuple[Vec, Vec], own: BaseGeometry | None) -> float:
        line = LineString([leader[0].as_tuple(), leader[1].as_tuple()])
        if any(line.intersects(t) for t in self.taken):
            return HIT_LEADER
        for j in self.symbol_tree.query(line):
            g = self.symbols[j]
            if (own is None or not g.within(own.buffer(1e-6))) and line.intersects(g):
                return HIT_LEADER
        return 0.0

    # --- result --------------------------------------------------------------

    def _lines(
        self, lines: Sequence[str], rect: tuple[float, float, float, float], align: Align
    ) -> list[tuple[str, Vec]]:
        x0, _, x1, y1 = rect
        x = {Align.LEFT: x0, Align.RIGHT: x1, Align.CENTER: (x0 + x1) / 2}[align]
        top = y1 - self.m.line_h / 2
        return [(t, Vec(x, top - k * self.m.step)) for k, t in enumerate(lines)]

    def _leader(
        self, rect: tuple[float, float, float, float], pos: Vec, inward: Vec | None, depth: float
    ) -> tuple[Vec, Vec] | None:
        tip = pos if inward is None else pos + inward * depth
        b, p = box(*rect), Point(tip.x, tip.y)
        if b.distance(p) <= depth + self.m.leader_min:
            return None
        near, _ = nearest_points(b, p)
        return (tip, Vec(near.x, near.y))


_DIRS = [
    Vec(math.cos(a), math.sin(a))
    for a in [0, math.pi, -math.pi / 2, math.pi / 2]
    + [-math.pi / 4, -3 * math.pi / 4, math.pi / 4, 3 * math.pi / 4]
    + [math.pi * (2 * k + 1) / 8 for k in range(8)]
]  # sides, diagonals, in-between


def _beside(c: Vec, n: Vec, w: float, h: float) -> tuple[tuple[float, float, float, float], Align]:
    """Block w × h pressed against point c from side n: on the right, left-aligned; on the left,
    right-aligned; above and below, centred."""
    if abs(n.x) > abs(n.y) + 1e-9:
        if n.x > 0:
            return (c.x, c.y - h / 2, c.x + w, c.y + h / 2), Align.LEFT
        return (c.x - w, c.y - h / 2, c.x, c.y + h / 2), Align.RIGHT
    if abs(n.y) > abs(n.x) + 1e-9:
        if n.y > 0:
            return (c.x - w / 2, c.y, c.x + w / 2, c.y + h), Align.CENTER
        return (c.x - w / 2, c.y - h, c.x + w / 2, c.y), Align.CENTER
    # Diagonal: the block corner sits at point c
    x0 = c.x if n.x > 0 else c.x - w
    y0 = c.y if n.y > 0 else c.y - h
    return (x0, y0, x0 + w, y0 + h), Align.LEFT if n.x > 0 else Align.RIGHT


def door_swing(hinge: Vec, closed: Vec, normal: Vec, width: float) -> BaseGeometry:
    """Door swing zone: a quarter circle of radius width at the hinge, on the normal side."""
    quad = Polygon(
        [
            (hinge.x, hinge.y),
            (closed.x, closed.y),
            (closed.x + normal.x * width, closed.y + normal.y * width),
            (hinge.x + normal.x * width, hinge.y + normal.y * width),
        ]
    )
    return Point(hinge.x, hinge.y).buffer(width, 32).intersection(quad)
