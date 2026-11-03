"""Where a junction box goes: on the ceiling, at the centre of its points, at least
routing.CLEARANCE from walls (place_ceiling_box); for floor routes, on a wall (step BOX_STEP,
at least BOX_CLEARANCE from corners, place_box). Branch reach along the route
(branch_reach), box size by number of lines (box_size), splitting points into zones
(split_points), moving a box after an edit in the viewer (moved_anchor)."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from shapely.geometry import Point
from shapely.ops import nearest_points

from floorplan_engine.electrical.anchors import Anchor
from floorplan_engine.electrical.routing import (
    CLEARANCE,
    End,
    Grid,
    Router,
    room_area,
)
from floorplan_engine.model.geometry import RoomGeometry, Vec, WallSegment
from floorplan_engine.model.scale import sheet

BOX_STEP = 100.0  # mm: step for trying box spots along the wall
BOX_CLEARANCE = 150.0  # mm: from a corner and from an opening to the box
BOX_SPACING = 200.0  # mm: boxes of different groups in a room are at least this far apart
BOX_SIZE_MM = 2.5  # box square side, sheet mm
# Box sizes and how many lines (entries) to bring into each, at the low end of common
# practice (decision 2026-10-25); 190×140 only as a last resort
# The key is for the price list (junction_box.100x100), the name for the estimate and hints
BOX_SIZES: tuple[tuple[str, int], ...] = (("80", 3), ("100x100", 6), ("150x110", 8))
BOX_LARGE = ("190x140", 10)
BOX_ORDER = (*(k for k, _ in BOX_SIZES), BOX_LARGE[0])
BOX_TITLES = {"80": "Ø80", "100x100": "100×100", "150x110": "150×110", "190x140": "190×140"}
BOX_BRANCHES = BOX_SIZES[-1][1] - 1  # branches per box: one line is the feed from the panel
# Ceiling spots whose branches are at most this fraction longer than the shortest count as
# equal; among them the box goes closest to the centre of its points
CENTER_SLACK = 0.1


def _manhattan(a: Vec, b: Vec) -> float:
    return abs(a.x - b.x) + abs(a.y - b.y)


def anchor_end(a: Anchor) -> End:
    return End(a.node, a.wall_is_vertical)


def _box_candidates(g: RoomGeometry, depth: float) -> list[Anchor]:
    out: list[Anchor] = []
    for seg in g.contour.segments:
        spans = [(o.offset, o.offset + o.width) for o in g.room.openings if o.wall == seg.id]
        offset = BOX_CLEARANCE
        while offset <= seg.length - BOX_CLEARANCE:
            if all(not (a - BOX_CLEARANCE < offset < b + BOX_CLEARANCE) for a, b in spans):
                out.append(Anchor(seg.point_at(offset), seg.inward, seg.direction, depth))
            offset += BOX_STEP
    return out


# Cost of branches from a box spot to its points: sum of route paths around walls
Reach = Callable[[Vec], float]


def branch_reach(g: RoomGeometry, targets: Sequence[Anchor], any_angle: bool = False) -> Reach:
    """Sum of paths from the spot to the points along the route inside the room (with turns), not in
    a straight line: a box will not end up behind a partition from its points."""
    area = room_area(g)
    routers = [Router(area, anchor_end(t), any_angle) for t in targets]
    return lambda p: sum(r.cost(p) for r in routers)


def place_box(g: RoomGeometry, board: Router, reach: Reach, taken: Sequence[Vec]) -> Anchor | None:
    """Wall spot where the path from the panel plus the branches to the points is smallest."""
    best: tuple[float, Anchor] | None = None
    for cand in _box_candidates(g, sheet(BOX_SIZE_MM)):
        if any(_manhattan(cand.node, t) < BOX_SPACING for t in taken):
            continue
        cost = board.cost(cand.node) + reach(cand.node)
        if best is None or cost < best[0] - 1e-6:
            best = (cost, cand)
    return None if best is None else best[1]


def box_size(lines: int) -> str:
    """Box for the number of lines (feed + branches), at the low end of entries; 190×140 only if
    there are more lines than a 150×110 takes (in practice never: the group gets split)."""
    return next((name for name, cap in BOX_SIZES if lines <= cap), BOX_LARGE[0])


def split_points(points: Sequence[Vec], cap: int) -> list[list[int]]:
    """Points split into zones of at most cap each: halving (with the number of zones in mind) along
    the longer axis, so neighbouring points end up in one box."""
    idx = list(range(len(points)))

    def split(part: list[int]) -> list[list[int]]:
        if len(part) <= cap:
            return [part]
        k = math.ceil(len(part) / cap)
        xs = [points[i].x for i in part]
        ys = [points[i].y for i in part]
        axis = 0 if max(xs) - min(xs) >= max(ys) - min(ys) else 1
        part = sorted(part, key=lambda i: (points[i].x, points[i].y)[axis])
        cut = round(len(part) * (k // 2) / k)
        return split(part[:cut]) + split(part[cut:])

    return split(idx)


def place_ceiling_box(
    g: RoomGeometry, reach: Reach, targets: Sequence[Anchor], taken: Sequence[Vec], depth: float
) -> Anchor | None:
    """Ceiling box: a spot inside the room at least CLEARANCE from walls at the centre of its
    points.
    Among spots whose route branches to the points are at most CENTER_SLACK longer than the
    shortest, take the one closest to the middle of the points: the path from the panel does not
    choose the spot (one feed line does not pull the box towards the panel's wall)."""
    spots = [
        (reach(p), p)
        for p in Grid.of(room_area(g)).free_points()
        if all(_manhattan(p, t) >= BOX_SPACING for t in taken)
    ]
    if not spots:
        return None
    limit = min(c for c, _ in spots) * (1 + CENTER_SLACK) + 1e-6
    mid = Vec(
        sum(t.node.x for t in targets) / len(targets),
        sum(t.node.y for t in targets) / len(targets),
    )
    _, best = min(
        ((c, p) for c, p in spots if c <= limit), key=lambda s: ((s[1] - mid).length(), s[0])
    )
    return Anchor(best, None, None, depth)


def box_wall(g: RoomGeometry, anchor: Anchor) -> WallSegment | None:
    """Wall the box stands on (symbol); None on the ceiling."""
    if anchor.wall_dir is None:
        return None
    for seg in g.contour.segments:
        v = anchor.pos - seg.start
        along = v.dot(seg.direction)
        if (
            seg.direction.dot(anchor.wall_dir) > 0.99
            and abs(seg.direction.cross(v)) < 1.0
            and -1.0 <= along <= seg.length + 1.0
        ):
            return seg
    return None


def moved_anchor(g: RoomGeometry, anchor: Anchor, at: Vec) -> Anchor | None:
    """New box spot: on a wall, the projection onto its wall, at least BOX_CLEARANCE from corners;
    on the ceiling, a point inside the room, and if it is closer than CLEARANCE to walls, the
    nearest spot at that distance. None if there is no room."""
    if anchor.inward is None:
        area = room_area(g)
        pt = Point(at.x, at.y)
        if not area.contains(pt):
            return None
        inner = area.buffer(-CLEARANCE, join_style="mitre")
        if not inner.is_empty and not inner.contains(pt):
            near = nearest_points(inner, pt)[0]
            at = Vec(near.x, near.y)
        return Anchor(at, None, None, anchor.depth)
    seg = box_wall(g, anchor)
    if seg is None or seg.length < 2 * BOX_CLEARANCE:
        return None
    offset = min(
        max((at - seg.start).dot(seg.direction), BOX_CLEARANCE), seg.length - BOX_CLEARANCE
    )
    return Anchor(seg.point_at(offset), seg.inward, seg.direction, anchor.depth)
