"""Ceiling views for the "Elevations" sheets (decision 2026-11-12): the wiring cut room by room.

Like the wall elevations, but the plane is a room's ceiling seen from above (floor routes: the
floor, the same way): the plan orientation is kept, so the view matches the plan sheet. In the
view: the room outline with wall codes (model/wall_names.py, as on the elevations), the lines of
this plane that pass through the room (cut by the room's outline with its walls, so a passage
through a wall shows up to the neighbour), the junction boxes, the line ends (a drop to a wall
point, a ceiling light, a rise from the panel) with point numbers as on the electrical sheet,
and the offsets of the bundle axes, boxes and ends from the left and the bottom wall.

No new calculations: routes, boxes and ends come from wiring.py; lanes, fixings and bend radii
are drawn by drawing/ceilings.py from the same wiring.
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from shapely.geometry import LineString, Point, Polygon

from floorplan_engine.electrical.anchors import Anchor
from floorplan_engine.electrical.boxes import box_wall
from floorplan_engine.electrical.point_numbers import number_points
from floorplan_engine.electrical.wiring_model import Route, Run, Wiring
from floorplan_engine.model.geometry import Contour, RoomGeometry, Vec, room_geometries
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.model.wall_names import wall_names

PLANES: tuple[Route, ...] = ("ceiling", "floor")
AXIS_TOL_MM = 1.0  # a piece is along an axis if it deviates less than this
MIN_PIECE_MM = 1.0  # a line touching the room for less than this is not in the view
BOX_DEFAULT_MM = 100.0
MERGE_MM = 30.0  # scale values closer than this are one mark (lanes of one bundle)
END_TOL_MM = 50.0  # a line end this close to the inner outline is in the room (a wall point)


@dataclass(frozen=True)
class CeilingWall:
    """A wall of the room on the view: its id, code (2.B) and the inner face, mm of the model."""

    id: str
    code: str
    start: Vec
    end: Vec
    thickness: float

    @property
    def outward(self) -> Vec:
        """Unit normal out of the room (the walk is clockwise, as WallSegment.outward)."""
        d = self.end - self.start
        return d.left() * (1 / d.length())


@dataclass(frozen=True)
class CeilingBox:
    id: str
    label: str  # "К3"
    at: Vec  # centre, mm of the model
    size: float  # side, mm


@dataclass(frozen=True)
class CeilingEnd:
    """A line end in the room: kind drop (down a wall to a point; on a floor route: up), light
    (a point on the ceiling itself), board (from the panel, the rise to the plane); numbers are
    the point numbers of the electrical sheet, empty for the panel; groups are the line groups,
    for the panel its name instead (all lines start there)."""

    kind: str  # drop | light | board
    at: Vec
    numbers: tuple[int, ...]
    groups: tuple[str, ...]
    runs: tuple[str, ...]


@dataclass(frozen=True)
class CeilingView:
    room: str
    room_name: str
    plane: Route
    outline: tuple[Vec, ...]  # inner outline, wall starts in walk order
    clip: Polygon  # the room with its walls: lines are cut by it
    walls: tuple[CeilingWall, ...]
    runs: tuple[str, ...]  # ids of the lines that pass through the room, in wiring order
    boxes: tuple[CeilingBox, ...]
    ends: tuple[CeilingEnd, ...]
    left: str | None  # code of the wall the offsets along x are counted from
    bottom: str | None  # the same along y

    @property
    def key(self) -> str:
        return f"{self.room}.{self.plane}"

    @property
    def origin(self) -> Vec:
        return Vec(min(v.x for v in self.outline), min(v.y for v in self.outline))

    @property
    def size(self) -> Vec:
        o = self.origin
        return Vec(max(v.x for v in self.outline) - o.x, max(v.y for v in self.outline) - o.y)


def ceiling_views(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical,
    wiring: Wiring,
) -> list[CeilingView]:
    """Views of the planes with lines, room by room in plan order: the ceiling first, then the
    floor if a floor route crosses the room. A room without lines and boxes has no view."""
    numbers = number_points(plan, elec)
    names = wall_names(plan, contours)
    out: list[CeilingView] = []
    for g in room_geometries(plan, contours):
        clip = Polygon([c.as_tuple() for c in g.corners]).buffer(0)
        inner = Polygon([v.as_tuple() for v in g.contour.vertices]).buffer(0)
        for plane in PLANES:
            runs = [r for r in wiring.runs if r.route == plane and _crosses(r, clip)]
            boxes = [b for b in wiring.boxes if b.room == g.room.id and b.route == plane]
            if not runs and not boxes:
                continue
            walls = tuple(
                CeilingWall(s.id, names[(g.room.id, s.id)].code, s.start, s.end, s.thickness)
                for s in g.contour.segments
            )
            out.append(
                CeilingView(
                    g.room.id,
                    g.room.name,
                    plane,
                    tuple(g.contour.vertices),
                    clip,
                    walls,
                    tuple(r.id for r in runs),
                    tuple(
                        CeilingBox(b.id, b.label, _box_centre(g, b.anchor), _box_side(b.size))
                        for b in boxes
                    ),
                    _ends(runs, inner, numbers, elec.board.name if elec.board else ""),
                    _side(walls, vertical=True),
                    _side(walls, vertical=False),
                )
            )
    return out


def view_offsets(view: CeilingView, wiring: Wiring) -> tuple[list[float], list[float]]:
    """Offsets for the scales, mm, rounded and ascending: along x from the left wall (bundle axes
    running along y, boxes, ceiling points), along y from the bottom wall (axes running along x,
    boxes, ceiling points). An axis counts if its piece lies in the room. Drops at wall points are
    left out: their place is on the elevations. Values closer than MERGE_MM keep the first; the
    scale ends are 0 and the room size."""
    o, size = view.origin, view.size
    inner = Polygon([v.as_tuple() for v in view.outline]).buffer(0)
    xs: set[float] = set()
    ys: set[float] = set()
    runs = {r.id: r for r in wiring.runs}
    for rid in view.runs:
        path = runs[rid].path
        for a, b in itertools.pairwise(path):
            piece = LineString([a.as_tuple(), b.as_tuple()])
            if piece.length < MIN_PIECE_MM or piece.intersection(inner).length < MIN_PIECE_MM:
                continue
            if abs(a.x - b.x) < AXIS_TOL_MM:
                xs.add(round(a.x - o.x))
            elif abs(a.y - b.y) < AXIS_TOL_MM:
                ys.add(round(a.y - o.y))
    ceiling = [e.at for e in view.ends if e.kind == "light"]
    for p in [*(b.at for b in view.boxes), *ceiling]:
        xs.add(round(p.x - o.x))
        ys.add(round(p.y - o.y))
    return _merged(xs, round(size.x)), _merged(ys, round(size.y))


def offset_anchors(view: CeilingView, wiring: Wiring) -> tuple[list[Vec], list[Vec]]:
    """Where the scale values come from, for the dashed leaders to the scales (mm of the model):
    to the bottom scale — the lower end of each bundle axis running along y inside the room, and
    the boxes and ceiling points; to the right scale — the right end of each axis running along
    x, and the same boxes and points. One spot per value, the one nearest its scale."""
    inner = Polygon([v.as_tuple() for v in view.outline]).buffer(0)
    lows: dict[int, Vec] = {}
    rights: dict[int, Vec] = {}
    runs = {r.id: r for r in wiring.runs}

    def keep(store: dict[int, Vec], key: int, p: Vec, better: bool) -> None:
        if key not in store or better:
            store[key] = p

    for rid in view.runs:
        for a, b in itertools.pairwise(runs[rid].path):
            piece = LineString([a.as_tuple(), b.as_tuple()]).intersection(inner)
            if piece.is_empty or piece.length < MIN_PIECE_MM:
                continue
            _, y0, x1, _ = piece.bounds
            if abs(a.x - b.x) < AXIS_TOL_MM:
                key = round(a.x)
                keep(lows, key, Vec(a.x, y0), key in lows and y0 < lows[key].y)
            elif abs(a.y - b.y) < AXIS_TOL_MM:
                key = round(a.y)
                keep(rights, key, Vec(x1, a.y), key in rights and x1 > rights[key].x)
    spots = [*(b.at for b in view.boxes), *(e.at for e in view.ends if e.kind == "light")]
    return [*lows.values(), *spots], [*rights.values(), *spots]


def dimension_spots(
    view: CeilingView, wiring: Wiring
) -> tuple[dict[float, list[Vec]], dict[float, list[Vec]]]:
    """The scale values with what each measures (decision 2026-11-12: hovering a value in the
    viewer lights its leaders and spots): bottom scale value → the spots it is measured to
    (offset_anchors, mm of the model), and the same for the right scale; a spot goes to the
    nearest value on its scale (close values are merged, view_offsets). The scale ends (the walls)
    measure nothing of their own."""
    xs, ys = view_offsets(view, wiring)
    lows, rights = offset_anchors(view, wiring)
    o = view.origin

    def assign(values: list[float], spots: list[Vec], coord: str) -> dict[float, list[Vec]]:
        out: dict[float, list[Vec]] = {v: [] for v in values}
        for p in spots:
            v = (p.x - o.x) if coord == "x" else (p.y - o.y)
            near = min(values, key=lambda k: abs(k - v))
            if abs(near - v) <= MERGE_MM:
                out[near].append(p)
        return out

    return assign(xs, lows, "x"), assign(ys, rights, "y")


def dimension_key(view: CeilingView, axis: str, value: float) -> str:
    """The object of a scale value: "dim:<room>.<plane>.x1450" ("y" for the right scale)."""
    return f"dim:{view.room}.{view.plane}.{axis}{value:.0f}"


def _merged(values: set[float], size: float) -> list[float]:
    """The scale: 0, the values inside the room, size; a value within MERGE_MM of the previous
    one (or of the room size) is dropped."""
    out = [0.0]
    for v in sorted(v for v in values if 0 < v < size):
        if v - out[-1] >= MERGE_MM and size - v >= MERGE_MM:
            out.append(v)
    return [*out, size]


def _crosses(run: Run, clip: Polygon) -> bool:
    if len(run.path) < 2:
        return False
    line = LineString([p.as_tuple() for p in run.path])
    return bool(line.intersection(clip).length >= MIN_PIECE_MM)


def _ends(
    runs: Sequence[Run], inner: Polygon, numbers: dict[str, int], board: str
) -> tuple[CeilingEnd, ...]:
    """Line ends inside the room, one marker per spot: points at one spot (a frame of sockets)
    share it. A box end is drawn by the box itself; a chain point is the end of the line coming in
    and the start of the next, so it is marked once. At the panel end the label is its name."""
    near = inner.buffer(END_TOL_MM)
    kinds: dict[tuple[int, int], tuple[str, Vec]] = {}
    nums: dict[tuple[int, int], set[int]] = defaultdict(set)
    groups: dict[tuple[int, int], set[str]] = defaultdict(set)
    ids: dict[tuple[int, int], list[str]] = defaultdict(list)
    for r in runs:
        found: list[tuple[str, Vec, str]] = []
        if not r.target.startswith("box_"):
            found.append(("drop" if r.rise_end_mm > 0 else "light", r.path[-1], r.target))
        if r.source == "board" and r.rise_start_mm > 0:
            found.append(("board", r.path[0], ""))
        for kind, p, target in found:
            if not near.contains(Point(p.x, p.y)):
                continue
            key = (round(p.x), round(p.y))
            kinds.setdefault(key, (kind, p))
            if target in numbers:
                nums[key].add(numbers[target])
            groups[key].add(board if kind == "board" else r.group)
            ids[key].append(r.id)
    return tuple(
        CeilingEnd(kind, p, tuple(sorted(nums[key])), tuple(sorted(groups[key])), tuple(ids[key]))
        for key, (kind, p) in sorted(kinds.items())
    )


def _side(walls: Sequence[CeilingWall], vertical: bool) -> str | None:
    """The leftmost wall along y (vertical) or the lowest along x: the offsets are counted from
    it; None if no wall lies on that side of the outline (a slanted corner)."""
    best: tuple[float, float, str] | None = None
    for w in walls:
        d = w.end - w.start
        along = abs(d.y) if vertical else abs(d.x)
        if along < AXIS_TOL_MM or abs(d.x if vertical else d.y) > AXIS_TOL_MM:
            continue
        pos = w.start.x if vertical else w.start.y
        if best is None or (pos, -along) < (best[0], best[1]):
            best = (pos, -along, w.code)
    if best is None:
        return None
    lo = min(v for w in walls for v in ((w.start.x,) if vertical else (w.start.y,)))
    return best[2] if abs(best[0] - lo) < AXIS_TOL_MM else None


def _box_centre(g: RoomGeometry, anchor: Anchor) -> Vec:
    """A box on the ceiling sits on its point; one on a wall stands off the wall by half its
    side, as on the wiring sheet."""
    if box_wall(g, anchor) is None or anchor.inward is None:
        return anchor.pos
    return anchor.pos + anchor.inward * (BOX_DEFAULT_MM / 2)


def _box_side(size: str) -> float:
    """Box side by size: "100x100" → 100, "80" (round) → 80."""
    try:
        return float(size.split("x")[0])
    except ValueError:
        return BOX_DEFAULT_MM
