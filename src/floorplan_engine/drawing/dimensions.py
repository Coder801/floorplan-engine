"""Plan dimensions: rows of every wall, their linework, label spots and drawing.

The plan places them in two passes (`plan.draw_plan`). First `layout_dimensions` gives every
wall its rows (the chain of openings, if any, and the total length), unless the partition was
already dimensioned from the neighbour's side: on the facade line if nothing is outside the wall
and it is close to that line, otherwise on the side with the shortest extension lines (inside the
room, in the neighbour's room, beyond the building) where they find a level whose default labels
and line do not touch walls, room names and rows already laid out (`_sides`, `free_level`).
Then, with all rows known, their linework (`dim_linework`: dimension and extension lines, ticks)
is an obstacle for every label on the plan, and each dimension label takes its default spot
above the line, a spot next to it or under it (`dim_spots`) or a spot on a 45° leader
(`callouts`); `draw_dimension` draws it there.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass

from ezdxf.layouts.layout import Modelspace
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from floorplan_engine.drawing.callouts import (
    Candidate,
    Kind,
    Label,
    Obstacle,
    Spot,
    readable_angle,
    reading,
)
from floorplan_engine.drawing.layers import (
    A_DIMS,
    DIM_DLE_MM,
    DIM_EXE_MM,
    DIM_EXO_MM,
    DIM_GAP_MM,
    DIM_STYLE,
    DIM_TICK_MM,
    TEXT_DIM_MM,
    text_width,
)
from floorplan_engine.model.geometry import RoomGeometry, Vec, WallSegment, point_in_polygon
from floorplan_engine.model.scale import sheet
from floorplan_engine.model.schema import Room

DIM_LEVEL_1_MM = 8.0  # first dimension row from the wall face, sheet mm
DIM_LEVEL_STEP_MM = 7.0  # step between rows
DIM_TEXT_GAP_MM = 0.8  # gap around a dimension label along the line (like dimgap)
DIM_LIFT_MM = TEXT_DIM_MM * 1.4  # a label with no room along the line goes one row up
DIM_LINE_BAND_MM = 0.4  # dimension line band for the row level check
DIM_STEPS_MM = (0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0)  # how much farther to move the label
DIM_MAX_SHIFTS = 4  # how many levels a row may move if its place is taken
SHARED_WALL_TOLERANCE = 1.0
FACADE_SLACK_MM = 30.0  # a recessed outer wall keeps its rows on the facade line up to this far
_ZERO = Vec(0.0, 0.0)


def wall_gaps(room: Room, wall: str) -> list[tuple[float, float]]:
    """Sorted opening intervals on a wall."""
    spans = [(o.offset, o.offset + o.width) for o in room.openings if o.wall == wall]
    return sorted(spans)


@dataclass(frozen=True)
class Dim:
    """One dimension: part a…b of the wall's inner face, its line at offset from the face
    (+ is outward), model mm; key is "room.wall"."""

    key: str
    seg: WallSegment
    a: float
    b: float
    offset: float

    @property
    def text(self) -> str:
        return f"{self.b - self.a:.0f}"

    @property
    def owner(self) -> str:
        return f"dimension:{self.key}"

    def at(self, x: float) -> Vec:
        """Point of the dimension line opposite offset x along the wall."""
        return self.seg.point_at(x) + self.seg.outward * self.offset

    def fits(self) -> bool:
        """The label fits between the dimension's extension lines."""
        return sheet(text_width(self.text, TEXT_DIM_MM) + 2 * DIM_TEXT_GAP_MM) <= self.b - self.a

    def label(self) -> Label:
        """The label; its leader starts at the middle of the dimension line."""
        d, up = reading(self.seg.direction)
        width = sheet(text_width(self.text, TEXT_DIM_MM))
        mid = self.at((self.a + self.b) / 2)
        return Label(width, sheet(TEXT_DIM_MM), d, up, mid, self.owner)

    def centre(self, move: Vec = _ZERO) -> Vec:
        """Centre of the label above the line (where ezdxf puts it, dimtad=1), shifted by move."""
        _, up = reading(self.seg.direction)
        mid = self.at((self.a + self.b) / 2)
        return mid + up * (sheet(DIM_GAP_MM) + sheet(TEXT_DIM_MM) / 2) + move

    def tick(self, x: float) -> str:
        """Owner of the tick at offset x: neighbouring parts of a chain share it."""
        return f"tick:{self.key}:{self.offset:.1f}:{x:.1f}"


def _moves(dim: Dim) -> list[Vec]:
    """Where a label may go when its default spot is narrow or taken: along the line past the
    segment (closer first); under the line, centred and along it; one row up, centred and
    along the line."""
    d, up = reading(dim.seg.direction)
    width = text_width(dim.text, TEXT_DIM_MM)
    reach = (dim.b - dim.a) / 2 + sheet(width / 2 + DIM_TEXT_GAP_MM)
    along = [reach + sheet(step) for step in DIM_STEPS_MM]
    out = [d * (sign * x) for x in along for sign in (1.0, -1.0)]
    under = up * -sheet(2 * DIM_GAP_MM + TEXT_DIM_MM)
    lift = up * sheet(DIM_LIFT_MM)
    return out + [under] + [under + v for v in out] + [lift] + [lift + v for v in out]


def dim_spots(dim: Dim) -> list[Candidate]:
    """Own spots of a dimension label: above the middle of the line if it fits (it may touch the
    ticks at its own ends), then the nearby moves."""
    spots = [Candidate(dim.centre(m)) for m in _moves(dim)]
    if dim.fits():
        ends = frozenset({dim.tick(dim.a), dim.tick(dim.b)})
        spots.insert(0, Candidate(dim.centre(), ends))
    return spots


def dim_linework(dim: Dim) -> list[Obstacle]:
    """Dimension line with its overshoot, extension lines from the wall face and ticks, as
    drawn by the PLAN dimension style."""
    seg, n = dim.seg, dim.seg.outward
    side = 1.0 if dim.offset >= 0 else -1.0
    dle = seg.direction * sheet(DIM_DLE_MM)
    d, up = reading(seg.direction)
    tick = (d + up) * sheet(DIM_TICK_MM)
    group = dim.owner
    out = [Obstacle(_line(dim.at(dim.a) - dle, dim.at(dim.b) + dle), Kind.LINE, group, group)]
    for x in (dim.a, dim.b):
        start = seg.point_at(x) + n * (side * sheet(DIM_EXO_MM))
        end = dim.at(x) + n * (side * sheet(DIM_EXE_MM))
        out.append(Obstacle(_line(start, end), Kind.LINE, group, group))
        c = dim.at(x)
        out.append(Obstacle(_line(c - tick, c + tick), Kind.LINE, dim.tick(x), group))
    return out


def _line(a: Vec, b: Vec) -> LineString:
    return LineString([a.as_tuple(), b.as_tuple()])


def _line_band(seg: WallSegment, offset: float) -> BaseGeometry:
    """Dimension line of a row for the level check. The ends are trimmed: at a room corner the
    lines of neighbouring walls always cross."""
    band = sheet(DIM_LINE_BAND_MM)
    trim = min(abs(offset) + sheet(DIM_GAP_MM), seg.length * 0.45)
    a, b, n = seg.point_at(trim), seg.point_at(seg.length - trim), seg.outward
    lo, hi = offset - band, offset + band
    return Polygon([(p + n * k).as_tuple() for p, k in ((a, lo), (b, lo), (b, hi), (a, hi))])


def _hits(geom: BaseGeometry, taken: Sequence[BaseGeometry]) -> bool:
    return any(geom.intersection(t).area > 0 for t in taken)


def _lay(
    key: str,
    seg: WallSegment,
    rows: Sequence[Sequence[tuple[float, float]]],
    sign: float,
    start: float,
) -> tuple[list[BaseGeometry], list[BaseGeometry]]:
    """Default labels and line bands of the rows with the first at level start."""
    step = sheet(DIM_LEVEL_STEP_MM)
    offsets = [sign * (start + r * step) for r in range(len(rows))]
    dims = [
        Dim(key, seg, a, b, off) for parts, off in zip(rows, offsets, strict=True) for a, b in parts
    ]
    boxes: list[BaseGeometry] = [dim.label().box(dim.centre()) for dim in dims if dim.fits()]
    return boxes, [_line_band(seg, off) for off in offsets]


def free_level(
    key: str,
    seg: WallSegment,
    rows: Sequence[Sequence[tuple[float, float]]],
    sign: float,
    base: float,
    taken: Sequence[BaseGeometry],
    room: BaseGeometry | None = None,
) -> float | None:
    """Level of the wall's first row: the first one (moving away from the wall, up to
    DIM_MAX_SHIFTS steps) where the default labels and lines of its rows do not touch what is
    already laid out (taken) and, for rows inside a room, the lines stay inside it (a narrow room
    does not push them across to the opposite wall); None if there is none."""
    step = sheet(DIM_LEVEL_STEP_MM)
    for k in range(DIM_MAX_SHIFTS + 1):
        boxes, lines = _lay(key, seg, rows, sign, base + k * step)
        if room is not None and not all(room.contains(line) for line in lines):
            return None
        if not any(_hits(g, taken) for g in boxes + lines):
            return base + k * step
    return None


def outside_is_free(g: RoomGeometry, seg: WallSegment, others: Sequence[RoomGeometry]) -> bool:
    """There is no other room outside the wall (dimensions may go there)."""
    mid = seg.point_at(seg.length / 2) + seg.outward * (seg.thickness + sheet(DIM_LEVEL_1_MM))
    return not any(point_in_polygon(mid, o.contour.vertices) for o in others if o is not g)


def mirrored_wall(g: RoomGeometry, seg: WallSegment, other: RoomGeometry) -> WallSegment | None:
    """The wall of another room that is the other side of this same partition."""
    far_start = seg.start + seg.outward * seg.thickness
    far_end = seg.end + seg.outward * seg.thickness
    mine = [(seg.length - b, seg.length - a) for a, b in wall_gaps(g.room, seg.id)]
    for o in other.contour.segments:
        if (o.start - far_end).length() <= SHARED_WALL_TOLERANCE and (
            o.end - far_start
        ).length() <= SHARED_WALL_TOLERANCE:
            theirs = wall_gaps(other.room, o.id)
            same = len(mine) == len(theirs) and all(
                abs(a1 - a2) <= SHARED_WALL_TOLERANCE and abs(b1 - b2) <= SHARED_WALL_TOLERANCE
                for (a1, b1), (a2, b2) in zip(mine, theirs, strict=True)
            )
            return o if same else None
    return None


def facing_walls(g: RoomGeometry, seg: WallSegment, other: RoomGeometry) -> list[WallSegment]:
    """Walls of another room on the other side of this wall's body: facing it at the wall's
    thickness and overlapping it along the wall (a partition whose two sides differ in length
    or openings, so `mirrored_wall` does not match them)."""
    lo, hi = seg.start.dot(seg.direction), seg.end.dot(seg.direction)
    far = seg.start.dot(seg.outward) + seg.thickness
    out: list[WallSegment] = []
    for o in other.contour.segments:
        if o.direction.dot(seg.direction) > -1 + 1e-6:
            continue  # not antiparallel
        if abs(o.start.dot(seg.outward) - far) > SHARED_WALL_TOLERANCE:
            continue
        a, b = sorted((o.start.dot(seg.direction), o.end.dot(seg.direction)))
        if min(hi, b) - max(lo, a) > SHARED_WALL_TOLERANCE:
            out.append(o)
    return out


@dataclass(frozen=True)
class _Side:
    """Where a wall's rows may go: sign of the offset (+ is outward), level of the first row
    from the wall face (the length of the extension lines) and the room the rows must stay
    in (None beyond the building)."""

    sign: float
    base: float
    room: BaseGeometry | None


def _sides(g: RoomGeometry, seg: WallSegment, geoms: Sequence[RoomGeometry]) -> list[_Side]:
    """Sides for a wall's rows, the preferred first. Beyond the building extent (one line per
    facade), if nothing is outside the wall and the wall is no more than FACADE_SLACK_MM from
    that line; then by the length of the extension lines: inside the room, in the neighbouring
    room behind a partition, beyond the building (a recessed wall: ventilation shaft, niche)."""
    level_1 = sheet(DIM_LEVEL_1_MM)
    inside = _Side(-1.0, level_1, _polygon(g))
    if outside_is_free(g, seg, geoms):
        reach = max(c.dot(seg.outward) for r in geoms for c in r.corners)
        facade = _Side(1.0, reach - seg.start.dot(seg.outward) + level_1, None)
        if facade.base <= seg.thickness + level_1 + sheet(FACADE_SLACK_MM):
            return [facade, inside]
        return [inside, facade]
    probe = seg.point_at(seg.length / 2) + seg.outward * (seg.thickness + level_1)
    behind = [o for o in geoms if o is not g and point_in_polygon(probe, o.contour.vertices)]
    return [inside] + [_Side(1.0, seg.thickness + level_1, _polygon(o)) for o in behind]


def _polygon(g: RoomGeometry) -> Polygon:
    return Polygon([v.as_tuple() for v in g.contour.vertices])


def layout_dimensions(geoms: Sequence[RoomGeometry], taken: list[BaseGeometry]) -> list[Dim]:
    """Rows of every wall, larger rooms first (a shared partition is dimensioned from the larger
    room, unless it was already dimensioned from the neighbour's side), in drawing order.

    A wall's rows go to the first of its sides (`_sides`: facade, then the shortest extension
    lines) where they find a free level (`free_level`); with none free, to the first side at its
    base level. taken holds walls and room names; the rows add their lines and default labels
    to it.
    """
    dims: list[Dim] = []
    done: list[RoomGeometry] = []
    step = sheet(DIM_LEVEL_STEP_MM)
    for g in sorted(geoms, key=lambda r: r.contour.area_mm2, reverse=True):
        for seg in g.contour.segments:
            key = f"{g.room.id}.{seg.id}"
            if any(mirrored_wall(g, seg, o) is not None for o in done):
                continue
            gaps = wall_gaps(g.room, seg.id)
            parts = [(0.0, seg.length)]
            if gaps:
                stops = sorted({0.0, seg.length, *(x for gap in gaps for x in gap)})
                parts = list(itertools.pairwise(stops))
            # Rows: chain of openings (if any), then the total length
            rows = [parts, [(0.0, seg.length)]] if gaps else [parts]
            sides = _sides(g, seg, geoms)
            chosen = next(
                (
                    (side, level)
                    for side in sides
                    for level in (
                        free_level(key, seg, rows, side.sign, side.base, taken, side.room),
                    )
                    if level is not None
                ),
                None,
            )
            side, level = chosen if chosen is not None else (sides[0], sides[0].base)
            boxes, lines = _lay(key, seg, rows, side.sign, level)
            taken.extend(boxes + lines)
            for r, row in enumerate(rows):
                offset = side.sign * (level + r * step)
                dims += [Dim(key, seg, a, b, offset) for a, b in row]
        done.append(g)
    return dims


def draw_dimension(msp: Modelspace, dim: Dim, spot: Spot) -> None:
    """The dimension with its label at spot (ezdxf puts a moved label's centre there) and the
    spot's leader on A-DIMS.

    For add_aligned_dim a positive distance is to the left of p1→p2, and "left" of a wall is
    outward. If the wall runs left or down, the points are swapped so the text is not upside
    down.
    """
    p1, p2, offset = dim.seg.point_at(dim.a), dim.seg.point_at(dim.b), dim.offset
    d = p2 - p1
    angle = math.degrees(math.atan2(d.y, d.x))
    if abs(readable_angle(angle) - angle) > 1e-6:
        p1, p2, offset = p2, p1, -offset
    entity = msp.add_aligned_dim(
        p1=p1.as_tuple(),
        p2=p2.as_tuple(),
        distance=offset,
        dimstyle=DIM_STYLE,
        dxfattribs={"layer": A_DIMS.name},
    )
    if (spot.centre - dim.centre()).length() > 1e-6:
        entity.set_location(spot.centre.as_tuple())
    entity.render()
    layer = {"layer": A_DIMS.name}
    for a, b in itertools.pairwise(spot.leader):
        msp.add_line(a.as_tuple(), b.as_tuple(), dxfattribs=layer)
