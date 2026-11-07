"""Wall elevations (decision 2026-10-28, P1): what the installer does on each wall.

A wall is seen from inside the room: the wall start (in walk order) is on the left, the end on
the right (the walk is clockwise along the inner outline, so from inside the offset always
grows left to right); the floor is at the bottom, the ceiling at the top. On the wall:
openings, points (numbered as on the electrical sheet), panel, junction boxes, chases (drops
from the ceiling or rises from the floor). Only walls with points, a panel, boxes or chases.

A partition shared by two rooms has two elevations, one from each side (each from inside its
own room). To tell them apart, an elevation states what is behind the wall (behind): the
neighbouring room and the number of its wall on the other side, or "outside the flat". The
neighbour's outlets on the far side (back) are shown in place, as seen from this side: drill
through or mount back to back.

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
from floorplan_engine.electrical.point_numbers import number_points, point_name
from floorplan_engine.electrical.routing import opening_strip
from floorplan_engine.electrical.wiring_model import Wiring
from floorplan_engine.model.geometry import (
    DOOR_TOP_MM,
    WINDOW_HEIGHT_MM,
    WINDOW_SILL_MM,
    Contour,
    RoomGeometry,
    Vec,
    WallSegment,
    point_in_polygon,
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

BOARD_HEIGHT_MM = 400.0  # panel height on the elevation: not in the model, an assumption
POST_PITCH_MM = 71.0  # post step in a frame
BOX_DEFAULT_MM = 100.0
BEHIND_PROBE_MM = 50.0  # how far past the outer wall face to look for a neighbouring room
FACE_TOLERANCE_MM = 30.0  # neighbour face no farther than this from this wall's outer face
BEHIND_STEP_MM = 500.0  # probe step along the wall (neighbour behind part of a wall)


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
    """Point on the wall: symbol centre (x from the wall start, y from the floor), mm."""

    id: str
    number: int
    type: PointType
    x: float
    y: float
    posts: int


@dataclass(frozen=True)
class BoxView:
    id: str
    label: str  # "К3"
    x: float
    y: float
    size: float  # side, mm


@dataclass(frozen=True)
class ChaseView:
    """Chase: vertical at x, from y0 to y1 (y0 < y1), mm; wide means more than two cables."""

    x: float
    y0: float
    y1: float
    cables: int
    wide: bool
    low: bool  # low-voltage (internet, TV)


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
    behind: tuple[tuple[str, int | None], ...] = ()  # behind the wall: (room, its wall number)
    back: tuple[PointView, ...] = ()  # outlets on the far side of the wall (x from this side)
    water: tuple[WaterView, ...] = ()  # plumbing water outlets and drains

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
            # Chase from the box to the route plane: none if cable goes in before the plaster
            if (box.room, box.route) in box_chases:
                y0, y1 = (0.0, y) if box.route == "floor" else (y, ceiling)
                walls[(box.room, seg.id)].chases.append(ChaseView(x, y0, y1, 1, False, False))
        for c in wiring.chases:
            if not c.wall:
                continue  # at a box: drawn higher up
            if c.span is not None:
                y0, y1 = c.span
            elif c.route == "floor":
                y0, y1 = 0.0, c.length_mm
            else:
                y0, y1 = ceiling - c.length_mm, ceiling
            walls[(c.room, c.wall)].chases.append(
                ChaseView(c.offset, y0, y1, c.cables, c.wide, c.circuit != "power")
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
                    tuple(sorted(w.points, key=lambda p: (p.x, p.y))),
                    tuple(sorted(w.boxes, key=lambda b: b.x)),
                    tuple(sorted(w.chases, key=lambda c: (c.x, c.y0))),
                    w.board,
                    behind(geoms[room.id], seg, list(geoms.values())),
                    _back_points(seg, room.id, geoms, elec, numbers),
                    wet,
                )
            )
    return out


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
                {"x": r(c.x), "y0": r(c.y0), "y1": r(c.y1), "wide": c.wide, "low": c.low}
                for c in e.chases
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
            "title": tr("elev_card", lang, room=e.room_name, n=e.index),
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
    """What is behind the wall, in words: "Спальня (стена 2); Балкон" or "вне квартиры"."""
    names = [
        tr("elev_behind_wall", language, room=room, n=n) if n is not None else room
        for room, n in e.behind
    ]
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
        for other in _facing_segments(seg, g):
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
    return tuple(sorted(out, key=lambda p: (p.x, p.y)))


def _posts(p: ElectricalPoint) -> int:
    """Posts in a frame: count for sockets and low-voltage, one for everything else."""
    return p.count if p.type in (PointType.SOCKET, PointType.DATA, PointType.TV) else 1


def behind(
    g: RoomGeometry, seg: WallSegment, geoms: Sequence[RoomGeometry]
) -> tuple[tuple[str, int | None], ...]:
    """What is behind wall seg of room g: neighbouring rooms (probed beyond the outer face along the
    whole wall: a partition may be shared only in part, a long wall may have several rooms behind
    it) and the neighbour's wall number on the same face; empty means no room of the flat behind."""
    out: list[tuple[str, int | None]] = []
    n = max(3, round(seg.length / BEHIND_STEP_MM))
    for k in range(n):
        at = seg.length * (k + 0.5) / n
        p = seg.point_at(at) + seg.outward * (seg.thickness + BEHIND_PROBE_MM)
        for o in geoms:
            if o is g or not point_in_polygon(p, o.contour.vertices):
                continue
            item = (o.room.name, _facing(seg, o))
            if item not in out:
                out.append(item)
    return tuple(out)


def _facing_segments(seg: WallSegment, other: RoomGeometry) -> list[WallSegment]:
    """Neighbour walls on the far side of seg: they run the opposite way along seg's outer face and
    overlap it along the wall."""
    far = seg.start + seg.outward * seg.thickness
    out: list[WallSegment] = []
    for o in other.contour.segments:
        if o.direction.dot(seg.direction) > -0.99:
            continue
        if abs((o.start - far).dot(seg.outward)) > FACE_TOLERANCE_MM:
            continue
        a = (o.end - seg.start).dot(seg.direction)
        b = (o.start - seg.start).dot(seg.direction)
        if min(b, seg.length) - max(a, 0.0) > FACE_TOLERANCE_MM:
            out.append(o)
    return out


def _facing(seg: WallSegment, other: RoomGeometry) -> int | None:
    """Number (from 1) of the neighbour's first wall on the far side of seg."""
    found = _facing_segments(seg, other)
    return found[0].index + 1 if found else None


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
