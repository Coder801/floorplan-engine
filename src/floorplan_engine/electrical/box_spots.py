"""Where a junction box stands and when it moves.

- a box for a ceiling route is always on the ceiling, at least routing.CLEARANCE from walls,
  at the centre of its points: among spots where the route branches to the points around
  walls (boxes.branch_reach) are nearly the shortest, the one closest to their middle (decision
  2026-11-01); for a floor group, on a wall at BOX_ABOVE_FLOOR from the floor where the path
  from the panel plus branches is smallest (box_spot);
- a box does not stand on lines that do not go into it (decision 2026-11-17, clear_boxes):
  after routing, a box whose square touches a passing line of its plane (with the bundle lanes
  as on the sheet) moves to the nearest spot by the rule above off those lines, and the lines
  are routed again; a box moved by hand, or with no such spot, stays, with a warning;
- manual edits (wiring.yaml, from the viewer, moved_boxes): a box is put at the given spot (on a
  wall, along its wall, at least BOX_CLEARANCE from corners; on the ceiling, inside the room),
  its lines without a manual route are routed again from the new spot. An edit whose id now
  means another box is not applied (edit_notes);
- box size is the smallest for the final number of lines (sized, boxes.box_size: the feed, the
  branches, the feeds to the next boxes and the switches behind the door), 190×140 only as a
  last resort.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

import shapely
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry

from floorplan_engine.electrical import trace
from floorplan_engine.electrical.anchors import Anchor
from floorplan_engine.electrical.boxes import (
    BOX_SIZE_MM,
    box_size,
    box_square,
    branch_reach,
    moved_anchor,
    place_box,
    place_ceiling_box,
)
from floorplan_engine.electrical.bundles import lane_paths
from floorplan_engine.electrical.routing import room_area
from floorplan_engine.electrical.wiring_context import Context, Link
from floorplan_engine.electrical.wiring_model import JunctionBox, Route, Run
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.scale import sheet
from floorplan_engine.model.schema import ElectricalPoint, WiringEdits

# A box keeps off lines that do not go into it (decision 2026-11-17, clear_boxes): at most this
# many rounds of moving boxes and routing again; a line closer than BOX_LINE_CLEAR_MM on the sheet
# counts as touching
BOX_CLEAR_ROUNDS = 3
BOX_LINE_CLEAR_MM = 0.3
# The white box square does not cover point symbols either (2026-11-18): a symbol is kept off as
# its outline (anchors.SYMBOL_DEPTH) widened by POINT_MARK_MM for its number beside it; a wall
# symbol is at least POINT_HALF_MM wide on each side of its axis
POINT_MARK_MM = 1.5
POINT_HALF_MM = 2.0

Reroute = Callable[[Sequence[JunctionBox], Sequence[Link]], list[Run]]


def box_spot(
    ctx: Context,
    room: str,
    part: Sequence[ElectricalPoint],
    boxes: Sequence[JunctionBox],
    route: Route,
    avoid: BaseGeometry | None = None,
    own: str = "",
) -> Anchor | None:
    """Box spot for the points of a zone: on the ceiling at the centre of the points for a ceiling
    route, on a wall for a floor route; off avoid (other lines, clear_boxes). own is the box
    being moved: its old spot does not count as taken."""
    g = ctx.geoms[room]
    taken = [b.anchor.node for b in boxes if b.room == room and b.id != own]
    targets = [ctx.anchors[p.id] for p in part]
    if not targets:
        return None
    reach = branch_reach(g, targets, ctx.any_angle)
    if route == "floor":
        return place_box(g, ctx.from_source("board", "floor"), reach, taken, avoid)
    return place_ceiling_box(g, reach, targets, taken, sheet(BOX_SIZE_MM), avoid)


def sized(boxes: Sequence[JunctionBox], links: Sequence[Link]) -> list[JunctionBox]:
    """Box size by the final number of lines, including switches behind the door."""
    lines = {b.id: 1 + sum(1 for ln in links if ln.source == b.id) for b in boxes}
    return [replace(b, size=box_size(lines[b.id])) for b in boxes]


def moved_boxes(
    ctx: Context,
    boxes: Sequence[JunctionBox],
    links: Sequence[Link],
    edits: WiringEdits,
    edited: set[str],
    notes: list[tuple[str, str]],
) -> tuple[list[JunctionBox], list[Link]]:
    """Boxes go to the spots from wiring.yaml; the panel → box line leads to the new spot."""
    by_id = {b.id: b for b in boxes}
    out = list(boxes)
    moved: dict[str, Anchor] = {}
    for bid, e in sorted(edits.boxes.items()):
        b = by_id.get(bid)
        where = f"boxes.{bid}"
        if b is None or (b.room, b.group) != (e.room, e.group):
            now = "её нет" if b is None else f"это коробка {b.group} в {b.room}"
            notes.append(
                (where, f"коробка {e.group} в {e.room} не найдена ({now}) — не перенесена")
            )
            continue
        spot = moved_anchor(ctx.geoms[b.room], b.anchor, Vec(*e.at))
        if spot is None:
            notes.append((where, f"место {e.at} вне помещения {b.room} — коробка не перенесена"))
            continue
        moved[bid] = spot
        out[out.index(b)] = replace(b, anchor=spot)
        edited.add(f"box:{bid}")
    return out, _led_to(links, moved)


def _led_to(links: Sequence[Link], moved: dict[str, Anchor]) -> list[Link]:
    """The links into moved boxes lead to their new spots."""
    return [
        replace(ln, target_anchor=moved[ln.target]) if ln.target in moved else ln for ln in links
    ]


@dataclass(frozen=True)
class BoxMove:
    """A box moved off lines that pass by (clear_boxes), for the debug trace (trace.py)."""

    box: str
    before: Vec
    after: Vec
    avoid: BaseGeometry  # the passing lines, widened: what the box keeps off


def clear_boxes(
    ctx: Context,
    boxes: Sequence[JunctionBox],
    links: Sequence[Link],
    runs: Sequence[Run],
    route: Reroute,
    edited: set[str],
) -> tuple[list[JunctionBox], list[Link], list[Run], list[tuple[str, str]]]:
    """A box does not stand on lines that do not go into it (decision 2026-11-17): its square
    (boxes.box_square, as on the wiring sheet) touches only its own lines, the feed in and its
    branches. Lines of its plane (ceiling or floor) that pass by, with their bundle lanes as
    drawn (bundles.lane_paths), are checked after routing; a box on them gets the nearest
    spot by the usual rule among those off them (box_spot with avoid), and all lines are
    routed again, at most BOX_CLEAR_ROUNDS times (a moved box changes the lanes). A box moved
    by hand in wiring.yaml stays. A box still on foreign lines stays where it is, with a
    warning (box id, what was done) for the report."""
    boxes, links, runs = list(boxes), list(links), list(runs)
    tried: set[str] = set()  # boxes with no free spot left
    for _ in range(BOX_CLEAR_ROUNDS):
        hits = _foreign_hits(ctx, boxes, runs)
        moved: dict[str, Anchor] = {}
        for b in boxes:
            if b.id not in hits or f"box:{b.id}" in edited or b.id in tried:
                continue
            spot = box_spot(
                ctx, b.room, _box_targets(ctx, b, links), boxes, b.route, hits[b.id], b.id
            )
            if spot is None:
                tried.add(b.id)
                continue
            moved[b.id] = spot
        if not moved:
            break
        if trace.on():
            for b in boxes:
                if b.id in moved:
                    trace.emit(BoxMove(b.id, b.anchor.node, moved[b.id].node, hits[b.id]))
        boxes = [replace(b, anchor=moved[b.id]) if b.id in moved else b for b in boxes]
        links = _led_to(links, moved)
        runs = route(boxes, links)
    left = _foreign_hits(ctx, boxes, runs)
    return boxes, links, runs, _stay_notes(boxes, left, edited, tried)


def _stay_notes(
    boxes: Sequence[JunctionBox], left: dict[str, BaseGeometry], edited: set[str], tried: set[str]
) -> list[tuple[str, str]]:
    """Why each box still on foreign lines (left) was not moved off them: for the report."""
    notes: list[tuple[str, str]] = []
    for b in boxes:
        if b.id not in left:
            continue
        if f"box:{b.id}" in edited:
            why = "перенесена вручную в wiring.yaml — не сдвигается"
        elif b.id in tried:
            why = "в помещении нет места вне чужих трасс — оставлена"
        else:
            why = "после переноса на неё снова легли трассы — оставлена"
        notes.append(
            (b.id, f"коробка {b.label} ({b.group}, {b.room}) стоит на чужих трассах: {why}")
        )
    return notes


def _foreign_hits(
    ctx: Context, boxes: Sequence[JunctionBox], runs: Sequence[Run]
) -> dict[str, BaseGeometry]:
    """Boxes whose square touches a line that does not go into them or a point symbol of its room
    (_point_marks) → those lines of its plane in its room as drawn (lanes), widened by
    BOX_LINE_CLEAR_MM, and the symbols: the area the box must keep off."""
    paths, _ = lane_paths(runs, ctx.free)
    size = sheet(BOX_SIZE_MM)
    clear = sheet(BOX_LINE_CLEAR_MM)
    keys = [k for k in range(len(runs)) if len(paths[k]) > 1]
    bands = [LineString([p.as_tuple() for p in paths[k]]).buffer(clear) for k in keys]
    tree = shapely.STRtree(bands)
    out: dict[str, BaseGeometry] = {}
    ids = {b.id for b in boxes}
    for b in boxes:
        mine = _box_reach(b.id, runs, ids)  # a set chain behind the box is its own line too

        def foreign(i: int, b: JunctionBox = b, mine: set[str] = mine) -> bool:
            r = runs[keys[i]]
            return r.route == b.route and b.id != r.target and r.source not in mine

        square = box_square(b.anchor, size)
        marks = _point_marks(ctx, b.room)
        if not square.intersects(marks) and not any(
            foreign(int(i)) for i in tree.query(square, predicate="intersects")
        ):
            continue
        room = room_area(ctx.geoms[b.room])
        near = [bands[int(i)] for i in tree.query(room, predicate="intersects") if foreign(int(i))]
        area = shapely.unary_union([*near, marks])
        shapely.prepare(area)
        out[b.id] = area
    return out


def _point_marks(ctx: Context, room: str) -> BaseGeometry:
    """Point symbols of a room as drawn, with room for their numbers: a box keeps off them
    (_foreign_hits), its white square would hide them."""
    pad = sheet(POINT_MARK_MM)
    marks: list[BaseGeometry] = []
    for pid, a in sorted(ctx.anchors.items()):
        if ctx.rooms.get(pid) != room:
            continue
        if a.inward is None:
            marks.append(Point(a.pos.as_tuple()).buffer(a.depth + pad))
        else:
            half = max(a.depth / 2, sheet(POINT_HALF_MM))
            marks.append(LineString([a.pos.as_tuple(), a.node.as_tuple()]).buffer(half + pad))
    return shapely.unary_union(marks)


def _box_reach(box: str, lines: Sequence[Link] | Sequence[Run], boxes: set[str]) -> set[str]:
    """The box and the points it feeds: its branches and the lights of a set chain behind
    them (a chain line always comes after the line to its source)."""
    reach = {box}
    for ln in lines:
        if ln.source in reach and ln.target not in boxes:
            reach.add(ln.target)
    return reach


def _box_targets(ctx: Context, b: JunctionBox, links: Sequence[Link]) -> list[ElectricalPoint]:
    """Points a box feeds: its branches and the lights of a set chain behind them."""
    reach = _box_reach(b.id, links, {ln.target for ln in links if ln.target not in ctx.points})
    return [ctx.points[ln.target] for ln in links if ln.target in reach and ln.target in ctx.points]
