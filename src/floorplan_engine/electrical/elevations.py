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
from typing import Any, TypeVar

from shapely.geometry import Polygon

from floorplan_engine.electrical.boxes import box_wall
from floorplan_engine.electrical.frames import (
    BOX_HALF_MM,
    LOW_VOLTAGE,
    posts,
)
from floorplan_engine.electrical.mounting import PRACTICE, BendSize, bend_size, bundle_radii, spots
from floorplan_engine.electrical.point_numbers import number_points, point_name
from floorplan_engine.electrical.routing import opening_strip
from floorplan_engine.electrical.wiring_model import Chase, JunctionBox, Route, Run, Wiring
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
    Conduit,
    Electrical,
    ElectricalPoint,
    OpeningType,
    Plan,
    PointType,
    Room,
    Wall,
)
from floorplan_engine.model.texts import Language, tr
from floorplan_engine.model.wall_names import (
    FACE_TOLERANCE_MM,
    WallName,
    behind,
    facing_segments,
    surface_names,
    surfaces,
)

BOARD_HEIGHT_MM = 400.0  # panel height on the elevation: not in the model, an assumption
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
_View = TypeVar(
    "_View", OpeningView, PointView, BoxView, ChaseView, FixingView, CableView, BoardView, WaterView
)
_Spot = tuple[
    str, str, float, float
]  # on a wall: room, wall, x from the wall start, y from the floor
_Doors = Sequence[tuple[Polygon, Vec]]  # doors of the flat: place on the plan and the hinge point


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
    # Walls of the surface in walk order (decision 2026-11-17): neighbours with no corner between
    # them (turn 180) are one plane, one elevation; x runs from the start of the first one
    parts: tuple[str, ...] = ()

    @property
    def title(self) -> str:
        """ "Спальня — 1.C · Кабинет за стеной, дверь": room, then the wall for people."""
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

    @property
    def electrical(self) -> bool:
        """Something electrical on the wall: points, panel, boxes, chases, cables or fixings."""
        return bool(
            self.points
            or self.boxes
            or self.chases
            or self.cables
            or self.fixings
            or self.board is not None
        )

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
    """The electrical items of one wall (or of a surface, once its parts are joined), in the
    order they were placed: the elevation sorts them."""

    points: list[PointView] = field(default_factory=list)
    boxes: list[BoxView] = field(default_factory=list)
    chases: list[ChaseView] = field(default_factory=list)
    fixings: list[FixingView] = field(default_factory=list)
    cables: list[CableView] = field(default_factory=list)
    board: BoardView | None = None


_Walls = defaultdict[tuple[str, str], _Wall]  # (room, wall) → its items


@dataclass(frozen=True)
class _Flat:
    """What every elevation of the flat shares: the model, the room geometries, the surface
    names, the sheet numbers of the points, the doors (the opening on the far side of a door is
    that door) and the ceiling height with whether it is assumed."""

    elec: Electrical
    geoms: dict[str, RoomGeometry]
    names: dict[tuple[str, str], WallName]
    numbers: dict[str, int]
    doors: _Doors
    ceiling: float
    assumed: bool


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
    geoms = {g.room.id: g for g in room_geometries(plan, contours)}
    flat = _Flat(
        elec,
        geoms,
        surface_names(plan, contours),
        number_points(plan, elec),
        _doors(geoms),
        ceiling,
        assumed,
    )
    walls = _model_items(elec, flat.numbers)
    if wiring is not None:
        _wiring_items(walls, wiring, elec, geoms, ceiling)

    out: list[WallElevation] = []
    for room in plan.rooms:
        for chain in surfaces(room):
            e = _surface_elevation(room, chain, walls, water or {}, flat)
            if e is not None:
                out.append(e)
    return out


def _model_items(elec: Electrical, numbers: Mapping[str, int]) -> _Walls:
    """Points and the panel from the model, by (room, wall): a point off the walls (on the
    ceiling, in the floor) is not on any elevation."""
    walls: _Walls = defaultdict(_Wall)
    for p in elec.points:
        if p.wall is None or p.offset is None or p.height is None:
            continue
        walls[(p.room, p.wall)].points.append(
            PointView(p.id, numbers[p.id], p.type, p.offset, p.height, posts(p))
        )
    if elec.board is not None:
        b = elec.board
        walls[(b.room, b.wall)].board = BoardView(
            b.name, b.offset, b.height, b.width, BOARD_HEIGHT_MM
        )
    return walls


def _in_conduit(route: Route, conduit: Conduit) -> bool:
    """Drops in conduit: from the floor always, from the ceiling with conduit in the walls."""
    return route == "floor" or conduit == "walls"


def _wiring_items(
    walls: _Walls,
    wiring: Wiring,
    elec: Electrical,
    geoms: Mapping[str, RoomGeometry],
    ceiling: float,
) -> None:
    """What wiring.py placed on the walls: the boxes with their fixings and chases, the fixings
    on the cable drops, the cables along the walls and the chases."""
    box_at = _box_items(walls, wiring, elec, geoms, ceiling)
    for c in wiring.drops:
        if c.wall and c.kind != "channel":
            walls[(c.room, c.wall)].fixings += _drop_fixings(
                c.offset,
                _vertical(c),
                c.route,
                ceiling,
                max(c.cables, 1),
                _in_conduit(c.route, elec.conduit_level),
            )
    _cable_items(walls, wiring, elec, box_at, ceiling)
    for c in wiring.chases:
        if c.wall:  # at a box: drawn with the box
            walls[(c.room, c.wall)].chases += _chase_views(c, ceiling)


def _box_items(
    walls: _Walls,
    wiring: Wiring,
    elec: Electrical,
    geoms: Mapping[str, RoomGeometry],
    ceiling: float,
) -> dict[str, _Spot]:
    """Junction boxes on the walls (box_wall; a box on the ceiling is not on an elevation) with
    the fixings of the lines into them and the chase to the route plane (none if the cable goes in
    before the plaster: no box chases). Returns where each box stands."""
    box_at: dict[str, _Spot] = {}
    box_chases = {(c.room, c.route) for c in wiring.chases if c.kind == "box"}
    for box in wiring.boxes:
        g = geoms.get(box.room)
        seg = box_wall(g, box.anchor) if g is not None else None
        if g is None or seg is None:
            continue  # on the ceiling, not on a wall
        x = (box.anchor.pos - seg.start).dot(seg.direction)
        y = box.rise_mm if box.route == "floor" else ceiling - box.rise_mm
        wall = walls[(box.room, seg.id)]
        wall.boxes.append(BoxView(box.id, box.label, x, y, _box_side(box.size)))
        lines = sum(1 for r in wiring.runs if box.id in (r.source, r.target))
        wall.fixings += _drop_fixings(
            x,
            box.rise_mm,
            box.route,
            ceiling,
            max(lines, 1),
            _in_conduit(box.route, elec.conduit_level),
        )
        box_at[box.id] = (box.room, seg.id, x, y)
        if (box.room, box.route) in box_chases:
            y0, y1 = (0.0, y) if box.route == "floor" else (y, ceiling)
            wall.chases.append(ChaseView(x, y0, y1, 1, False, False))
    return box_at


def _cable_items(
    walls: _Walls,
    wiring: Wiring,
    elec: Electrical,
    box_at: Mapping[str, _Spot],
    ceiling: float,
) -> None:
    """The cables along the walls, by line (_cables), then the bend radii of their turns past the
    openings, by wall (turn_radii: the cables turning at one corner bend as a bundle)."""
    points = {p.id: p for p in elec.points}
    entries = dict(wiring.entries)
    for r in wiring.runs:
        for wall_key, cable in _cables(r, elec, points, box_at, ceiling, entries):
            walls[wall_key].cables.append(cable)
    by_id = {run.id: run for run in wiring.runs}
    for wall in walls.values():
        wall.cables = turn_radii(
            wall.cables,
            {
                run.id: (
                    run.route != "floor",
                    bend_size(run.mark, _in_conduit(run.route, elec.conduit_level)),
                )
                for c in wall.cables
                if (run := by_id.get(c.run)) is not None
            },
        )


def _chase_views(c: Chase, ceiling: float) -> list[ChaseView]:
    """A wall chase on the elevation: its vertical part (a channel between its heights; else from
    the route plane: the ceiling down or the floor up) and, past an opening, the turn along the
    wall at the bend height."""
    low = c.circuit != "power"
    if c.span is not None:
        y0, y1 = c.span
    elif c.route == "floor":
        y0, y1 = 0.0, _vertical(c)
    else:
        y0, y1 = ceiling - _vertical(c), ceiling
    out = [ChaseView(c.offset, y0, y1, c.cables, c.wide, low)]
    if c.bend is not None:
        x, y = c.bend
        out.append(ChaseView(c.offset, y, y, c.cables, c.wide, low, x))
    return out


def _surface_elevation(
    room: Room,
    chain: Sequence[int],
    walls: Mapping[tuple[str, str], _Wall],
    water: WaterMap,
    flat: _Flat,
) -> WallElevation | None:
    """The elevation of one surface of the room (chain: walk indices of its walls, from 0): the
    items of its parts moved along to the start of each part, the openings, what is behind and
    the outlets of the far side. None for a surface with nothing electrical and no water."""
    g = flat.geoms[room.id]
    parts = [room.walls[k] for k in chain]
    shifts = _shifts([wall.length for wall in parts])
    here = [walls.get((room.id, wall.id)) for wall in parts]
    wet = [tuple(water.get((room.id, wall.id), ())) for wall in parts]
    if all(w is None for w in here) and not any(wet):
        return None
    w = _joined(here, shifts)
    segs = [g.contour.segments[k] for k in chain]
    back = [
        _moved(v, dx)
        for seg, dx in zip(segs, shifts, strict=True)
        for v in _back_points(seg, room.id, flat.geoms, flat.elec, flat.numbers)
    ]
    water_views = [
        _moved(v, dx) for part_wet, dx in zip(wet, shifts, strict=True) for v in part_wet
    ]
    return WallElevation(
        room.id,
        room.name,
        parts[0].id,
        chain[0] + 1,
        sum(wall.length for wall in parts),
        flat.ceiling,
        flat.assumed,
        tuple(_surface_openings(g, parts, flat.ceiling, flat.doors)),
        tuple(sorted(_blocks(w.points), key=lambda p: (p.x, p.y))),
        tuple(sorted(w.boxes, key=lambda b: b.x)),
        tuple(sorted(w.chases, key=lambda c: (c.x, c.y0))),
        w.board,
        tuple(_behind_rooms(g, segs, flat.geoms, flat.names)),
        tuple(sorted(_blocks(_unique(back)), key=lambda p: (p.x, p.y))),
        tuple(sorted(water_views, key=lambda v: v.x)),
        flat.names[(room.id, parts[0].id)],
        _merged_fixings(w.fixings),
        tuple(sorted(w.cables, key=lambda c: (c.x, c.run))),
        tuple(wall.id for wall in parts),
    )


def _joined(parts: Sequence[_Wall | None], shifts: Sequence[float]) -> _Wall:
    """The items of a surface's parts in one plane: each part's items moved along by the start of
    the part (the panel: from the last part that has one)."""
    w = _Wall()
    for part, dx in zip(parts, shifts, strict=True):
        if part is None:
            continue
        w.points += [_moved(v, dx) for v in part.points]
        w.boxes += [_moved(v, dx) for v in part.boxes]
        w.chases += [_moved(v, dx) for v in part.chases]
        w.fixings += [_moved(v, dx) for v in part.fixings]
        w.cables += [_moved(v, dx) for v in part.cables]
        if part.board is not None:
            w.board = _moved(part.board, dx)
    return w


def _surface_openings(
    g: RoomGeometry, parts: Sequence[Wall], ceiling: float, doors: _Doors
) -> list[OpeningView]:
    """Openings of a surface: those of each part (_openings) moved along to the part's start."""
    return [
        _moved(o, dx)
        for part, dx in zip(parts, _shifts([wall.length for wall in parts]), strict=True)
        for o in _openings(g, part.id, ceiling, doors)
    ]


def _behind_rooms(
    g: RoomGeometry,
    segs: Sequence[WallSegment],
    geoms: Mapping[str, RoomGeometry],
    names: Mapping[tuple[str, str], WallName],
) -> list[tuple[str, str | None]]:
    """What is behind a surface, without repeats: the neighbouring room's name and the code of
    its wall on the far side (None where no wall of it faces this one)."""
    out: list[tuple[str, str | None]] = []
    for seg in segs:
        for near in behind(g, seg, list(geoms.values())):
            code = names[(near.room, near.wall)].code if near.wall else None
            item = (near.name, code)
            if item not in out:
                out.append(item)
    return out


def electrical_walls(walls: Sequence[WallElevation]) -> list[WallElevation]:
    """Walls of the electrical elevations (decision 2026-11-18): only those with something
    electrical, without the plumbing (it has its own elevations)."""
    return [replace(e, water=()) for e in walls if e.electrical]


def plumbing_walls(walls: Sequence[WallElevation]) -> list[WallElevation]:
    """Walls of the plumbing elevations (decision 2026-11-18): only those with water outlets or
    drains, without the electrical items (points, panel, boxes, chases, cables, fixings and the
    outlets of the far side)."""
    return [
        replace(e, points=(), boxes=(), chases=(), board=None, back=(), fixings=(), cables=())
        for e in walls
        if e.water
    ]


def _shifts(lengths: Sequence[float]) -> list[float]:
    """Start of each part of a surface from the start of the first one, mm."""
    out, at = [], 0.0
    for length in lengths:
        out.append(at)
        at += length
    return out


def _moved(view: _View, dx: float) -> _View:
    """A view of a wall part moved along the surface by dx, mm."""
    if dx == 0:
        return view
    fields = ("x0", "x1") if isinstance(view, OpeningView) else ("x", "x1")
    moved: dict[str, Any] = {}
    for name in fields:
        x = getattr(view, name, None)
        if x is not None:
            moved[name] = x + dx
    return replace(view, **moved)


def _unique(points: Sequence[PointView]) -> list[PointView]:
    """Points without repeats by id: at the joint of two parts one point may face both."""
    seen: dict[str, PointView] = {}
    for p in points:
        seen.setdefault(p.id, p)
    return list(seen.values())


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


def _line_end(
    end: str,
    elec: Electrical,
    points: Mapping[str, ElectricalPoint],
    boxes: Mapping[str, _Spot],
) -> _Spot | None:
    """Where a line ends on a wall: the panel ("board"), a wall point or a box on a wall; None for
    a point off the walls (on the ceiling, in the floor) and for a box on the ceiling."""
    if end == "board":
        b = elec.board
        return (b.room, b.wall, b.offset, b.height) if b is not None else None
    p = points.get(end)
    if p is not None:
        if p.wall is None or p.offset is None or p.height is None:
            return None
        return (p.room, p.wall, p.offset, p.height)
    return boxes.get(end)


def _cables(
    r: Run,
    elec: Electrical,
    points: Mapping[str, ElectricalPoint],
    boxes: Mapping[str, _Spot],
    ceiling: float,
    entries: Mapping[str, float],
) -> list[tuple[tuple[str, str], CableView]]:
    """The parts of a line along walls: a drop at its end to a wall point or box, a rise at its
    start from the panel, a chain point or a box on a wall; from the route plane (ceiling, or the
    floor for a floor route). A drop to a mechanism goes to its frame entry (entries,
    frames.py: the side of the block) and stops at the box top (bottom), not at its middle."""
    plane = 0.0 if r.route == "floor" else ceiling
    out: list[tuple[tuple[str, str], CableView]] = []
    for end, rise, drop in (
        (r.target, r.rise_end_mm, r.end_drop),
        (r.source, r.rise_start_mm, r.start_drop),
    ):
        if rise <= 0:
            continue
        spot = _line_end(end, elec, points, boxes)
        if spot is None:
            continue
        room, wall, x, y = spot
        side = drop is None and end in entries
        if side:  # into the frame by the corner of its first box
            y += BOX_HALF_MM if plane > y else -BOX_HALF_MM
        lo, hi = sorted((y, plane))
        # beside an opening, then along the wall to the point
        down = drop if drop is not None else entries.get(end, x)
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


@dataclass(frozen=True)
class _Links:
    """What the viewer shows on an elevation beside the geometry: the names of the points in the
    project language, the group colours and where the wiring line to a point or box comes from
    (the panel, the media panel, a box or the previous point of a chain)."""

    lang: Language
    points: Mapping[str, ElectricalPoint]
    boxes: Mapping[str, JunctionBox]
    board: str  # the panel name
    media: str | None  # the media panel name, if any
    feeds: Mapping[str, str]  # line target → its source
    colors: Mapping[str, int]  # group → colour

    def fed(self, target: str) -> str | None:
        """Where the line to target comes from, in words; None without a line."""
        src = self.feeds.get(target)
        if src is None:
            return None
        if src == "board":
            return self.board
        if src == "media" and self.media is not None:
            return self.media
        if src in self.boxes:
            return self.boxes[src].label
        return point_name(self.points[src], self.lang)

    def color(self, group: str | None) -> str | None:
        c = self.colors.get(group or "")
        return f"#{c:06x}" if c is not None else None


def _links(
    plan: Plan, elec: Electrical, wiring: Wiring | None, colors: Mapping[str, int]
) -> _Links:
    return _Links(
        plan.language,
        {p.id: p for p in elec.points},
        {b.id: b for b in wiring.boxes} if wiring is not None else {},
        elec.board.name if elec.board is not None else "board",
        elec.media.name if elec.media is not None else None,
        {r.target: r.source for r in wiring.runs} if wiring is not None else {},
        colors,
    )


def _r(v: float) -> float:
    return round(v, 1)


def _point_shape(p: PointView) -> dict[str, Any]:
    """Place and frame of a point: x, y, posts and, in a shared frame, its slot and the block."""
    return {
        "x": _r(p.x),
        "y": _r(p.y),
        "posts": p.posts,
        **({"slot": p.slot, "block": p.block} if p.block else {}),
    }


def _point_item(pv: PointView, links: _Links) -> dict[str, Any]:
    """A point of the wall with its sheet number, name, group and where its line comes from."""
    p = links.points[pv.id]
    return {
        "id": pv.id,
        "key": f"point:{pv.id}",
        "n": pv.number,
        "type": pv.type.value,
        "name": point_name(p, links.lang),
        **_point_shape(pv),
        "group": p.group,
        "color": links.color(p.group),
        "from": links.fed(pv.id),
    }


def _box_item(b: BoxView, links: _Links) -> dict[str, Any]:
    """A junction box with its group and where its line comes from."""
    group = links.boxes[b.id].group if b.id in links.boxes else None
    return {
        "id": b.id,
        "key": f"box:{b.id}",
        "label": b.label,
        "x": _r(b.x),
        "y": _r(b.y),
        "size": _r(b.size),
        "group": group,
        "color": links.color(group),
        "from": links.fed(b.id),
    }


def _cable_item(c: CableView, links: _Links) -> dict[str, Any]:
    """A cable along the wall, keyed as on the wiring sheet (wire:<run>), in its group colour."""
    return {
        "key": f"wire:{c.run}",
        "x": _r(c.x),
        "y0": _r(c.y0),
        "y1": _r(c.y1),
        **({"x1": _r(c.x1)} if c.x1 is not None else {}),
        **({"r": _r(c.radius)} if c.radius is not None else {}),
        "color": links.color(c.group),
    }


def _elevation_content(e: WallElevation, links: _Links) -> dict[str, Any]:
    """What is on the wall, as data: openings, chases, fixings, cables, boxes, points, water, the
    outlets of the far side and the panel. Object keys match the sheets (point:<id>, box:<id>,
    board:board)."""
    data: dict[str, Any] = {
        "key": f"elevation:{e.key}",
        "length": _r(e.length),
        "openings": [
            {
                "kind": o.kind,
                **({"hinge": o.hinge} if o.hinge else {}),
                "x0": _r(o.x0),
                "x1": _r(o.x1),
                "y0": _r(o.y0),
                "y1": _r(o.y1),
                "assumed": o.assumed,
            }
            for o in e.openings
        ],
        "chases": [
            {
                "x": _r(c.x),
                "y0": _r(c.y0),
                "y1": _r(c.y1),
                "wide": c.wide,
                "low": c.low,
                **({"x1": _r(c.x1)} if c.x1 is not None else {}),
            }
            for c in e.chases
        ],
        "fixings": [
            {"x": _r(f.x), "y": _r(f.y), **({"n": f.count} if f.count > 1 else {})}
            for f in e.fixings
        ],
        "cables": [_cable_item(c, links) for c in e.cables],
        "boxes": [_box_item(b, links) for b in e.boxes],
        "points": [_point_item(p, links) for p in e.points],
        "water": [
            {
                "fixture": v.fixture,
                "key": f"fixture:{v.fixture}",
                "name": v.names.get(links.lang, v.fixture),
                "n": v.number,
                "kind": v.kind,
                "x": _r(v.x),
                "y": _r(v.y),
                "d": v.d,
                "assumed": v.assumed,
            }
            for v in e.water
        ],
        "back": [
            {"id": p.id, "n": p.number, "type": p.type.value, **_point_shape(p)} for p in e.back
        ],
    }
    if e.board is not None:
        b = e.board
        data["board"] = {
            "key": "board:board",
            "name": b.name,
            "x": _r(b.x),
            "y": _r(b.y),
            "width": _r(b.width),
            "height": _r(b.height),
        }
    return data


def _bare_surface(
    room: Room, k: int, g: RoomGeometry, ceiling: float, doors: _Doors
) -> WallElevation:
    """The surface of wall k (walk index from 0) with nothing on it but its openings: a corner
    neighbour of an elevation that has no elevation of its own."""
    chain = next(c for c in surfaces(room) if k in c)
    parts = [room.walls[j] for j in chain]
    return WallElevation(
        room.id,
        room.name,
        parts[0].id,
        0,
        sum(w.length for w in parts),
        ceiling,
        True,
        tuple(_surface_openings(g, parts, ceiling, doors)),
    )


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
    links = _links(plan, elec, wiring, colors)
    elevations = wall_elevations(plan, contours, elec, wiring, water=water)
    ceiling = elevations[0].height if elevations else 2700.0
    # Every wall of a surface leads to its elevation: a corner neighbour may be any part of it
    done = {
        (e.room, wall): _elevation_content(e, links)
        for e in elevations
        for wall in e.parts or (e.wall,)
    }
    geoms = {g.room.id: g for g in room_geometries(plan, contours)}
    doors = _doors(geoms)

    def neighbour(room: Room, k: int, turn: float) -> dict[str, Any]:
        """Neighbouring surface at a corner (k is the walk index of its wall, from 0): the angle
        and what is on it, without the far side. A surface without electrical items has openings
        only."""
        k %= len(room.walls)
        side = done.get((room.id, room.walls[k].id))
        if side is None:
            side = _elevation_content(_bare_surface(room, k, geoms[room.id], ceiling, doors), links)
        return {"turn": turn, **{key: v for key, v in side.items() if key != "back"}}

    out: list[dict[str, Any]] = []
    for e in elevations:
        room = next(x for x in plan.rooms if x.id == e.room)
        k = e.index - 1
        last = (k + max(len(e.parts), 1) - 1) % len(room.walls)
        segs = geoms[e.room].contour.segments
        start, end = segs[k].start, segs[last].end
        out.append(
            {
                **done[(e.room, e.wall)],
                "title": e.title,
                "behind": behind_text(e, plan.language),
                "height": _r(e.height),
                "height_assumed": e.height_assumed,
                "top": _r(e.top),
                # Inner face on the plan (model mm, like the 3D scene): the start is the left corner
                "face": [[_r(start.x), _r(start.y)], [_r(end.x), _r(end.y)]],
                # Corners to neighbouring surfaces: left to the previous in the walk, right to the
                # next
                "left": neighbour(room, k - 1, room.walls[k - 1].turn),
                "right": neighbour(room, last + 1, room.walls[last].turn),
            }
        )
    return out


def behind_text(e: WallElevation, language: Language) -> str:
    """What is behind the wall, in words: "Спальня (1.B); Балкон" or "вне квартиры"."""
    names = [f"{room} ({code})" if code is not None else room for room, code in e.behind]
    return "; ".join(names) if names else tr("elev_outside", language)  # names may contain commas


def _back_points(
    seg: WallSegment,
    room: str,
    geoms: Mapping[str, RoomGeometry],
    elec: Electrical,
    numbers: Mapping[str, int],
) -> list[PointView]:
    """Outlets of neighbouring rooms on the far side of wall seg: a point on the neighbour's wall
    along the same face, in this wall's coordinates (offset from its left corner, view from
    inside); not yet in frames (_blocks)."""
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
                    out.append(PointView(p.id, numbers[p.id], p.type, x, p.height, posts(p)))
    return out


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


def _openings(g: RoomGeometry, wall: str, ceiling: float, doors: _Doors) -> tuple[OpeningView, ...]:
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
