"""Wall elevations (decision 2026-10-28, P1): what the installer does on each wall.

A wall is seen from inside the room: the wall start (in walk order) is on the left, the end on
the right (the walk is clockwise along the inner outline, so from inside the offset always
grows left to right); the floor is at the bottom, the ceiling at the top. On the wall:
openings, points (numbered as on the electrical sheet), panel, junction boxes, chases (drops
from the ceiling or rises from the floor) and the cable fixings on the drops (mounting.py; on
the drops, so they show without chases too). Only walls with points, a panel, boxes or chases.

A partition shared by two rooms has two elevations, one from each side (each from inside its
own room). To tell them apart, an elevation states what is behind the wall (behind): the
neighbouring room and the code of its wall on the other side (model/wall_names.py), or
"outside the flat". The neighbour's outlets on the far side (back) are shown in place, as seen
from this side: drill through or mount back to back.

No new calculations: points and panel come from the model, boxes and chases from wiring.py,
opening heights without data use the same assumptions as in 3D (scene3d).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from shapely.geometry import Polygon

from floorplan_engine.electrical.boxes import box_wall
from floorplan_engine.electrical.mounting import PRACTICE, BendSize, bend_size, bundle_radii, spots
from floorplan_engine.electrical.point_numbers import number_points, point_name
from floorplan_engine.electrical.routing import opening_strip
from floorplan_engine.electrical.wiring_model import Chase, Route, Run, Wiring
from floorplan_engine.model.geometry import (
    DOOR_TOP_MM,
    WINDOW_HEIGHT_MM,
    WINDOW_SILL_MM,
    Contour,
    RoomGeometry,
    Vec,
    WallSegment,
    room_geometries,
)
from floorplan_engine.model.schema import (
    Electrical,
    ElectricalPoint,
    OpeningType,
    Plan,
    PointType,
    Room,
)
from floorplan_engine.model.texts import Language, tr
from floorplan_engine.model.wall_names import (
    FACE_TOLERANCE_MM,
    WallName,
    behind,
    facing_segments,
    wall_names,
)

BOARD_HEIGHT_MM = 400.0  # panel height on the elevation: not in the model, an assumption
POST_PITCH_MM = 71.0  # post step in a frame
LOW_VOLTAGE = (PointType.DATA, PointType.TV)
BOX_DEFAULT_MM = 100.0


@dataclass(frozen=True)
class OpeningView:
    kind: str  # door | window | opening
    x0: float
    x1: float
    y0: float  # bottom: 0 for a door, sill for a window
    y1: float  # top
    assumed: bool  # height not in room.yaml, typical value
    hinge: str | None = None  # door: start | end, the side of the hinges on the elevation


@dataclass(frozen=True)
class PointView:
    """Point on the wall: block centre (x from the wall start, y from the floor), mm. Points at
    one spot share a frame (sockets with INT, sockets with switches): block is its posts in
    all, slot is the shift of this point's centre from the block centre, in post pitches."""

    id: str
    number: int
    type: PointType
    x: float
    y: float
    posts: int
    slot: float = 0.0
    block: int = 0  # 0: the point alone, block = posts

    @property
    def frame(self) -> int:
        return self.block or self.posts


@dataclass(frozen=True)
class BoxView:
    id: str
    label: str  # "К3"
    x: float
    y: float
    size: float  # side, mm


@dataclass(frozen=True)
class ChaseView:
    """Chase: vertical at x, from y0 to y1 (y0 < y1), mm; wide means more than two cables. With
    x1 it is horizontal at height y0 (= y1) from x to x1: the turn past an opening."""

    x: float
    y0: float
    y1: float
    cables: int
    wide: bool
    low: bool  # low-voltage (internet, TV)
    x1: float | None = None


@dataclass(frozen=True)
class FixingView:
    """Fixing on a cable drop along the wall (mounting.py): spot x, height y, mm; count is how
    many clips or pads stand there in one line (one per cable of the drop, decision 2026-11-12)."""

    x: float
    y: float
    count: int = 1


@dataclass(frozen=True)
class CableView:
    """A cable along the wall (decision 2026-11-12): line `run` of `group` at x, from height y0
    to y1, mm — from the route plane (ceiling or floor) down or up to its point, panel or box.
    With x1 it is horizontal at height y0 (= y1) from x to x1: the turn past an opening, and
    radius is its bend radius on the cable axis, mm (turn_radii; None for a cable without sizes:
    low voltage, LED)."""

    run: str
    group: str
    x: float
    y0: float
    y1: float
    x1: float | None = None
    radius: float | None = None


@dataclass(frozen=True)
class BoardView:
    name: str
    x: float  # centre
    y: float  # centre
    width: float
    height: float


@dataclass(frozen=True)
class WaterView:
    """Water outlet or drain on the wall, computed by plumbing (plumbing/rows.water_views):
    x from the wall start, y is the axis from the floor, mm; number is the fixture number on the
    "Plumbing" sheet."""

    fixture: str
    number: int
    kind: str  # cold | hot | sewer
    x: float
    y: float
    d: int  # Ø, mm
    assumed: bool  # typical height
    names: dict[str, str] = field(default_factory=dict)  # fixture in words: ru, uk


WaterMap = Mapping[tuple[str, str], Sequence[WaterView]]  # (room, wall) → supplies


@dataclass(frozen=True)
class WallElevation:
    room: str
    room_name: str
    wall: str
    index: int  # wall number in the walk, from 1
    length: float
    height: float  # ceiling height
    height_assumed: bool
    openings: tuple[OpeningView, ...] = ()
    points: tuple[PointView, ...] = ()
    boxes: tuple[BoxView, ...] = ()
    chases: tuple[ChaseView, ...] = ()
    board: BoardView | None = None
    behind: tuple[tuple[str, str | None], ...] = ()  # behind the wall: (room, its wall code)
    back: tuple[PointView, ...] = ()  # outlets on the far side of the wall (x from this side)
    water: tuple[WaterView, ...] = ()  # plumbing water outlets and drains
    name: WallName | None = None  # code and description (model/wall_names.py)
    fixings: tuple[FixingView, ...] = ()  # fixings on the cable drops (decision 2026-11-11)
    cables: tuple[CableView, ...] = ()  # the cables along the wall (decision 2026-11-12)

    @property
    def title(self) -> str:
        """ "Спальня — 1.В · Кабинет за стеной, дверь": room, then the wall for people."""
        return f"{self.room_name} — {self.name.full if self.name else self.wall}"

    @property
    def key(self) -> str:
        return f"{self.room}.{self.wall}"

    @property
    def top(self) -> float:
        """Top of the drawing: the ceiling or, if something is above the ceiling (bad data or a
        wrong
        ceiling), that spot with a margin."""
        tops = [p.y + 100.0 for p in self.points] + [b.y + b.size / 2 for b in self.boxes]
        tops += [w.y + 100.0 for w in self.water]
        if self.board is not None:
            tops.append(self.board.y + self.board.height / 2)
        return max([self.height, *tops])

    def above_ceiling(self) -> list[str]:
        """Ids of points above the ceiling."""
        return [p.id for p in self.points if p.y > self.height]

    def heights(self) -> list[float]:
        """Heights from the floor for dimensions: points, panel, boxes (unique, ascending)."""
        ys = {round(p.y) for p in self.points} | {round(b.y) for b in self.boxes}
        ys |= {round(w.y) for w in self.water}
        if self.board is not None:
            ys.add(round(self.board.y))
        return sorted(float(y) for y in ys)

    def offsets(self) -> list[float]:
        """Offsets from the wall start: points, panel, boxes (unique, ascending)."""
        xs = {round(p.x) for p in self.points} | {round(b.x) for b in self.boxes}
        xs |= {round(w.x) for w in self.water}
        if self.board is not None:
            xs.add(round(self.board.x))
        return sorted(float(x) for x in xs)


@dataclass
class _Wall:
    points: list[PointView] = field(default_factory=list)
    boxes: list[BoxView] = field(default_factory=list)
    chases: list[ChaseView] = field(default_factory=list)
    fixings: list[FixingView] = field(default_factory=list)
    cables: list[CableView] = field(default_factory=list)
    board: BoardView | None = None


def wall_elevations(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical,
    wiring: Wiring | None,
    ceiling_default: float = 2700.0,
    water: WaterMap | None = None,
) -> list[WallElevation]:
    """Elevations of walls with electrical and plumbing items (water is fixture supplies by wall),
    by room and wall walk order."""
    ceiling = wiring.ceiling_height if wiring is not None else ceiling_default
    assumed = wiring.height_assumed if wiring is not None else True
    numbers = number_points(plan, elec)
    geoms = {g.room.id: g for g in room_geometries(plan, contours)}
    names = wall_names(plan, contours)
    doors = _doors(geoms)
    walls: dict[tuple[str, str], _Wall] = defaultdict(_Wall)

    for p in elec.points:
        if p.wall is None or p.offset is None or p.height is None:
            continue
        walls[(p.room, p.wall)].points.append(
            PointView(p.id, numbers[p.id], p.type, p.offset, p.height, _posts(p))
        )
    if elec.board is not None:
        b = elec.board
        walls[(b.room, b.wall)].board = BoardView(
            b.name, b.offset, b.height, b.width, BOARD_HEIGHT_MM
        )

    box_at: dict[str, tuple[str, str, float, float]] = {}  # box on a wall: room, wall, x, y

    def walls_in(route: Route) -> bool:
        """Drops in conduit: from the floor always, from the ceiling with conduit in the walls."""
        return route == "floor" or elec.conduit_level == "walls"

    if wiring is not None:
        box_chases = {(c.room, c.route) for c in wiring.chases if c.kind == "box"}
        for box in wiring.boxes:
            g = geoms.get(box.room)
            seg = box_wall(g, box.anchor) if g is not None else None
            if g is None or seg is None:
                continue  # on the ceiling, not on a wall
            x = (box.anchor.pos - seg.start).dot(seg.direction)
            y = box.rise_mm if box.route == "floor" else ceiling - box.rise_mm
            side = _box_side(box.size)
            walls[(box.room, seg.id)].boxes.append(BoxView(box.id, box.label, x, y, side))
            lines = sum(1 for r in wiring.runs if box.id in (r.source, r.target))
            walls[(box.room, seg.id)].fixings += _drop_fixings(
                x, box.rise_mm, box.route, ceiling, max(lines, 1), walls_in(box.route)
            )
            box_at[box.id] = (box.room, seg.id, x, y)
            # Chase from the box to the route plane: none if cable goes in before the plaster
            if (box.room, box.route) in box_chases:
                y0, y1 = (0.0, y) if box.route == "floor" else (y, ceiling)
                walls[(box.room, seg.id)].chases.append(ChaseView(x, y0, y1, 1, False, False))
        for c in wiring.drops:
            if c.wall and c.kind != "channel":
                walls[(c.room, c.wall)].fixings += _drop_fixings(
                    c.offset, _vertical(c), c.route, ceiling, max(c.cables, 1), walls_in(c.route)
                )
        for r in wiring.runs:
            for wall_key, cable in _cables(r, elec, box_at, ceiling):
                walls[wall_key].cables.append(cable)
        by_id = {run.id: run for run in wiring.runs}
        for wall_view in walls.values():
            wall_view.cables = turn_radii(
                wall_view.cables,
                {
                    run.id: (run.route != "floor", bend_size(run.mark, walls_in(run.route)))
                    for c in wall_view.cables
                    if (run := by_id.get(c.run)) is not None
                },
            )
        for c in wiring.chases:
            if not c.wall:
                continue  # at a box: drawn higher up
            low = c.circuit != "power"
            if c.span is not None:
                y0, y1 = c.span
            elif c.route == "floor":
                y0, y1 = 0.0, _vertical(c)
            else:
                y0, y1 = ceiling - _vertical(c), ceiling
            walls[(c.room, c.wall)].chases.append(
                ChaseView(c.offset, y0, y1, c.cables, c.wide, low)
            )
            if c.bend is not None:
                x, y = c.bend
                walls[(c.room, c.wall)].chases.append(
                    ChaseView(c.offset, y, y, c.cables, c.wide, low, x)
                )

    out: list[WallElevation] = []
    for room in plan.rooms:
        for k, wall in enumerate(room.walls, 1):
            w = walls.get((room.id, wall.id))
            wet = tuple(sorted((water or {}).get((room.id, wall.id), ()), key=lambda v: v.x))
            if w is None and not wet:
                continue
            w = w or _Wall()
            seg = geoms[room.id].contour.segments[k - 1]
            openings = _openings(geoms[room.id], wall.id, ceiling, doors)
            out.append(
                WallElevation(
                    room.id,
                    room.name,
                    wall.id,
                    k,
                    wall.length,
                    ceiling,
                    assumed,
                    openings,
                    tuple(sorted(_blocks(w.points), key=lambda p: (p.x, p.y))),
                    tuple(sorted(w.boxes, key=lambda b: b.x)),
                    tuple(sorted(w.chases, key=lambda c: (c.x, c.y0))),
                    w.board,
                    tuple(
                        (b.name, names[(b.room, b.wall)].code if b.wall else None)
                        for b in behind(geoms[room.id], seg, list(geoms.values()))
                    ),
                    _back_points(seg, room.id, geoms, elec, numbers),
                    wet,
                    names[(room.id, wall.id)],
                    _merged_fixings(w.fixings),
                    tuple(sorted(w.cables, key=lambda c: (c.x, c.run))),
                )
            )
    return out


def _vertical(c: Chase) -> float:
    """The vertical part of a chase, mm: without its turn past an opening."""
    if c.bend is None:
        return c.length_mm
    return max(c.length_mm - abs(c.bend[0] - c.offset), 0.0)


def _drop_fixings(
    x: float, length: float, route: Route, ceiling: float, count: int, in_conduit: bool
) -> list[FixingView]:
    """Fixings on a drop of `length` mm at x holding `count` cables: counted from the route plane
    (ceiling down, floor up) with the wall step (conduit or bare) and offset of the norms
    (mounting.spots)."""
    step, offset = PRACTICE.step("wall", in_conduit), PRACTICE.offset
    return [
        FixingView(round(x, 1), round(d if route == "floor" else ceiling - d, 1), count)
        for d in spots(length, step, offset)
    ]


def _merged_fixings(fixings: Sequence[FixingView]) -> tuple[FixingView, ...]:
    """One fixing per spot: two drops meeting at a spot count the larger number of cables."""
    best: dict[tuple[float, float], int] = {}
    for f in fixings:
        best[(f.x, f.y)] = max(best.get((f.x, f.y), 0), f.count)
    return tuple(FixingView(x, y, n) for (x, y), n in sorted(best.items()))


def _cables(
    r: Run,
    elec: Electrical,
    boxes: Mapping[str, tuple[str, str, float, float]],
    ceiling: float,
) -> list[tuple[tuple[str, str], CableView]]:
    """The parts of a line along walls: a drop at its end to a wall point or box, a rise at its
    start from the panel, a chain point or a box on a wall; from the route plane (ceiling, or the
    floor for a floor route)."""
    plane = 0.0 if r.route == "floor" else ceiling
    points = {p.id: p for p in elec.points}
    out: list[tuple[tuple[str, str], CableView]] = []

    def at(end: str) -> tuple[str, str, float, float] | None:
        if end == "board":
            b = elec.board
            return (b.room, b.wall, b.offset, b.height) if b is not None else None
        p = points.get(end)
        if p is not None:
            if p.wall is None or p.offset is None or p.height is None:
                return None
            return (p.room, p.wall, p.offset, p.height)
        return boxes.get(end)

    for end, rise, drop in (
        (r.target, r.rise_end_mm, r.end_drop),
        (r.source, r.rise_start_mm, r.start_drop),
    ):
        if rise <= 0:
            continue
        spot = at(end)
        if spot is None:
            continue
        room, wall, x, y = spot
        lo, hi = sorted((y, plane))
        down = x if drop is None else drop  # beside an opening, then along the wall to the point
        out.append(
            ((room, wall), CableView(r.id, r.group, round(down, 1), round(lo, 1), round(hi, 1)))
        )
        if drop is not None:
            turn = CableView(r.id, r.group, round(drop, 1), round(y, 1), round(y, 1), round(x, 1))
            out.append(((room, wall), turn))
    return out


def turn_radii(
    cables: Sequence[CableView], sizes: Mapping[str, tuple[bool, BendSize | None]]
) -> list[CableView]:
    """Bend radii of the turns past an opening (decision 2026-11-13): the cables turning at one
    corner the same way bend as a bundle (bundle_radii, the inner one is the reference). sizes:
    run → (route on the ceiling, its bend size). The drop lanes go by run, left to right (as the
    elevations draw them); the inner lane is the one nearest the side the turn goes to."""
    corners: dict[tuple[float, float, bool, bool], list[CableView]] = defaultdict(list)
    for c in cables:
        if c.x1 is not None and c.run in sizes:
            corners[(c.x, c.y0, c.x1 > c.x, sizes[c.run][0])].append(c)
    radius: dict[tuple[str, float], float] = {}
    for (_, _, right, _), turning in corners.items():
        lanes = sorted(turning, key=lambda c: c.run, reverse=right)  # inner first
        sized = [(c, size) for c in lanes if (size := sizes[c.run][1]) is not None]
        for (c, _), r in zip(sized, bundle_radii([size for _, size in sized]), strict=True):
            radius[(c.run, c.x)] = r
    return [
        replace(c, radius=radius[(c.run, c.x)])
        if c.x1 is not None and (c.run, c.x) in radius
        else c
        for c in cables
    ]


def elevation_data(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical,
    wiring: Wiring | None,
    colors: dict[str, int],
    water: WaterMap | None = None,
) -> list[dict[str, Any]]:
    """Elevations as data for their own view in the viewer (page key elevations, like the panel):
    wall, openings, chases, panel, boxes and points, with the electrical sheet number, name,
    group and the box the wiring line to the point comes from (link to the wiring sheet).
    Object keys match the sheets (point:<id>, box:<id>, board:board). Also the inner face on the
    plan (face: where to stand to see the wall, for a mini map) and the neighbouring walls at the
    corners (left, right: inner turn angle and what is on the neighbouring wall, for isometry)."""
    lang = plan.language
    points = {p.id: p for p in elec.points}
    boxes = {b.id: b for b in wiring.boxes} if wiring is not None else {}
    board = elec.board.name if elec.board is not None else "board"
    feeds = {r.target: r.source for r in wiring.runs} if wiring is not None else {}

    def fed(target: str) -> str | None:
        src = feeds.get(target)
        if src is None:
            return None
        if src == "board":
            return board
        if src == "media" and elec.media is not None:
            return elec.media.name
        return boxes[src].label if src in boxes else point_name(points[src], lang)

    def color(group: str | None) -> str | None:
        c = colors.get(group or "")
        return f"#{c:06x}" if c is not None else None

    def r(v: float) -> float:
        return round(v, 1)

    def content(e: WallElevation) -> dict[str, Any]:
        pts = []
        for pv in e.points:
            p = points[pv.id]
            pts.append(
                {
                    "id": pv.id,
                    "key": f"point:{pv.id}",
                    "n": pv.number,
                    "type": pv.type.value,
                    "name": point_name(p, lang),
                    "x": r(pv.x),
                    "y": r(pv.y),
                    "posts": pv.posts,
                    **({"slot": pv.slot, "block": pv.block} if pv.block else {}),
                    "group": p.group,
                    "color": color(p.group),
                    "from": fed(pv.id),
                }
            )
        data: dict[str, Any] = {
            "key": f"elevation:{e.key}",
            "length": r(e.length),
            "openings": [
                {
                    "kind": o.kind,
                    **({"hinge": o.hinge} if o.hinge else {}),
                    "x0": r(o.x0),
                    "x1": r(o.x1),
                    "y0": r(o.y0),
                    "y1": r(o.y1),
                    "assumed": o.assumed,
                }
                for o in e.openings
            ],
            "chases": [
                {
                    "x": r(c.x),
                    "y0": r(c.y0),
                    "y1": r(c.y1),
                    "wide": c.wide,
                    "low": c.low,
                    **({"x1": r(c.x1)} if c.x1 is not None else {}),
                }
                for c in e.chases
            ],
            "fixings": [
                {"x": r(f.x), "y": r(f.y), **({"n": f.count} if f.count > 1 else {})}
                for f in e.fixings
            ],
            "cables": [
                {
                    "key": f"wire:{c.run}",
                    "x": r(c.x),
                    "y0": r(c.y0),
                    "y1": r(c.y1),
                    **({"x1": r(c.x1)} if c.x1 is not None else {}),
                    **({"r": r(c.radius)} if c.radius is not None else {}),
                    "color": color(c.group),
                }
                for c in e.cables
            ],
            "boxes": [
                {
                    "id": b.id,
                    "key": f"box:{b.id}",
                    "label": b.label,
                    "x": r(b.x),
                    "y": r(b.y),
                    "size": r(b.size),
                    "group": boxes[b.id].group if b.id in boxes else None,
                    "color": color(boxes[b.id].group if b.id in boxes else None),
                    "from": fed(b.id),
                }
                for b in e.boxes
            ],
            "points": pts,
            "water": [
                {
                    "fixture": v.fixture,
                    "key": f"fixture:{v.fixture}",
                    "name": v.names.get(lang, v.fixture),
                    "n": v.number,
                    "kind": v.kind,
                    "x": r(v.x),
                    "y": r(v.y),
                    "d": v.d,
                    "assumed": v.assumed,
                }
                for v in e.water
            ],
            "back": [
                {
                    "id": p.id,
                    "n": p.number,
                    "type": p.type.value,
                    "x": r(p.x),
                    "y": r(p.y),
                    "posts": p.posts,
                    **({"slot": p.slot, "block": p.block} if p.block else {}),
                }
                for p in e.back
            ],
        }
        if e.board is not None:
            b = e.board
            data["board"] = {
                "key": "board:board",
                "name": b.name,
                "x": r(b.x),
                "y": r(b.y),
                "width": r(b.width),
                "height": r(b.height),
            }
        return data

    elevations = wall_elevations(plan, contours, elec, wiring, water=water)
    ceiling = elevations[0].height if elevations else 2700.0
    done = {(e.room, e.wall): content(e) for e in elevations}
    geoms = {g.room.id: g for g in room_geometries(plan, contours)}
    doors = _doors(geoms)

    def neighbour(room: Room, k: int, turn: float) -> dict[str, Any]:
        """Neighbouring wall at a corner (k is its walk index, from 0): the angle and what is on it.
        A wall without electrical items has openings only."""
        wall = room.walls[k % len(room.walls)]
        side = done.get((room.id, wall.id))
        if side is None:
            side = content(
                WallElevation(
                    room.id,
                    room.name,
                    wall.id,
                    0,
                    wall.length,
                    ceiling,
                    True,
                    _openings(geoms[room.id], wall.id, ceiling, doors),
                )
            )
        side = {key: v for key, v in side.items() if key != "back"}
        return {"turn": turn, **side}

    out: list[dict[str, Any]] = []
    for e in elevations:
        room = next(x for x in plan.rooms if x.id == e.room)
        seg = geoms[e.room].contour.segments[e.index - 1]
        k = e.index - 1
        data = {
            **done[(e.room, e.wall)],
            "title": e.title,
            "behind": behind_text(e, lang),
            "height": r(e.height),
            "height_assumed": e.height_assumed,
            "top": r(e.top),
            # Inner face on the plan (model mm, like the 3D scene): the start is the left corner
            "face": [[r(seg.start.x), r(seg.start.y)], [r(seg.end.x), r(seg.end.y)]],
            # Corners to neighbouring walls: left to the previous in the walk, right to the next
            "left": neighbour(room, k - 1, room.walls[k - 1].turn),
            "right": neighbour(room, k + 1, room.walls[k].turn),
        }
        out.append(data)
    return out


def behind_text(e: WallElevation, language: Language) -> str:
    """What is behind the wall, in words: "Спальня (1.Б); Балкон" or "вне квартиры"."""
    names = [f"{room} ({code})" if code is not None else room for room, code in e.behind]
    return "; ".join(names) if names else tr("elev_outside", language)  # names may contain commas


def _back_points(
    seg: WallSegment,
    room: str,
    geoms: dict[str, RoomGeometry],
    elec: Electrical,
    numbers: dict[str, int],
) -> tuple[PointView, ...]:
    """Outlets of neighbouring rooms on the far side of wall seg: a point on the neighbour's wall
    along the same face, in this wall's coordinates (offset from its left corner, view from
    inside)."""
    out: list[PointView] = []
    for g in geoms.values():
        if g.room.id == room:
            continue
        for other in facing_segments(seg, g):
            for p in elec.points:
                if (
                    p.room != g.room.id
                    or p.wall != other.id
                    or p.offset is None
                    or p.height is None
                ):
                    continue
                x = (other.point_at(p.offset) - seg.start).dot(seg.direction)
                if -FACE_TOLERANCE_MM <= x <= seg.length + FACE_TOLERANCE_MM:
                    out.append(PointView(p.id, numbers[p.id], p.type, x, p.height, _posts(p)))
    return tuple(sorted(_blocks(out), key=lambda p: (p.x, p.y)))


def _blocks(points: Sequence[PointView]) -> list[PointView]:
    """Points at one spot side by side in one frame, in model order, low-voltage last (to the
    right): INT in a block of sockets no longer covers them. The block stays centred on the
    spot, the offset in the model is to the middle of the block."""
    by_spot: dict[tuple[float, float], list[PointView]] = defaultdict(list)
    for p in points:
        by_spot[(round(p.x), round(p.y))].append(p)
    out: list[PointView] = []
    for same in by_spot.values():
        if len(same) == 1:
            out.extend(same)
            continue
        same.sort(key=lambda p: p.type in LOW_VOLTAGE)
        total = sum(p.posts for p in same)
        k = 0
        for p in same:
            out.append(replace(p, slot=k + p.posts / 2 - total / 2, block=total))
            k += p.posts
    return out


def _posts(p: ElectricalPoint) -> int:
    """Posts in a frame: count for sockets and low-voltage, one for everything else."""
    return p.count if p.type in (PointType.SOCKET, PointType.DATA, PointType.TV) else 1


def _doors(geoms: Mapping[str, RoomGeometry]) -> list[tuple[Polygon, Vec]]:
    """Doors of the flat: place on the plan and the hinge point."""
    out: list[tuple[Polygon, Vec]] = []
    for g in geoms.values():
        for op in g.room.openings:
            if op.type is OpeningType.DOOR:
                seg = g.contour.segment(op.wall)
                at = op.offset if op.hinge == "start" else op.offset + op.width
                out.append((opening_strip(g, op), seg.point_at(at)))
    return out


def _openings(
    g: RoomGeometry, wall: str, ceiling: float, doors: Sequence[tuple[Polygon, Vec]]
) -> tuple[OpeningView, ...]:
    """Openings of a wall. The opening on the other side of a door is that door, seen from here."""
    seg = g.contour.segment(wall)
    out: list[OpeningView] = []
    for op in sorted((o for o in g.room.openings if o.wall == wall), key=lambda o: o.offset):
        view = _opening(op.type, op.offset, op.width, op.sill, op.height, ceiling)
        if op.type is OpeningType.DOOR:
            view = replace(view, hinge=op.hinge)
        elif op.type is OpeningType.OPENING:
            strip = opening_strip(g, op)
            for place, hinge in doors:
                if place.intersection(strip).area > 0.5 * min(place.area, strip.area):
                    near = (hinge - seg.start).dot(seg.direction) < op.offset + op.width / 2
                    view = replace(view, kind="door", hinge="start" if near else "end")
                    break
        out.append(view)
    return tuple(out)


def _box_side(size: str) -> float:
    """Box side on the elevation by size: "100x100" → 100, "80" (round) → 80."""
    try:
        return float(size.split("x")[0])
    except ValueError:
        return BOX_DEFAULT_MM


def _opening(
    kind: OpeningType,
    offset: float,
    width: float,
    sill: float | None,
    height: float | None,
    ceiling: float,
) -> OpeningView:
    if kind is OpeningType.WINDOW:
        s = sill if sill is not None else WINDOW_SILL_MM
        top = s + (height if height is not None else WINDOW_HEIGHT_MM)
        return OpeningView(
            "window", offset, offset + width, s, min(top, ceiling), sill is None or height is None
        )
    top = height if height is not None else DOOR_TOP_MM
    return OpeningView(kind.value, offset, offset + width, 0.0, min(top, ceiling), height is None)
