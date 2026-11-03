"""Wiring through junction boxes: topology, routes and cable lengths, all from the model.

Variant rules:
- cable runs only from the panel to a box, from the panel to a load or from a box to a load;
  never from a load to a box or from box to box;
- a room is its own zone: a box sits in the room and feeds only its points, its cables do not
  leave the walls; cable reaches another room from the panel through door openings
  (routing.py). The exception is a switch: it is tapped into the box of its light, and if a
  group has only switches in a room (by a door outside), the branch to them comes from the
  group's nearest box through the opening; they get no box or panel line of their own
  (decision 2026-10-25);
- a box per group per room if the group has any light there, or two points or more; a single
  socket of a group in a room is fed directly from the panel; lines in a box (feed +
  branches) are at most the entries of a 150×110 (BOX_SIZES, low end); with more points the
  boxes are split by zone (split_points), each with its own panel line; box size is the
  smallest for the number of lines (box_size), 190×140 only as a last resort;
- direct lines run from the panel to each point without boxes: cross-section from
  HEAVY_SECTION mm² (hob, oven, boiler), a group made only of appliance outputs (air
  conditioner, towel rail) and low-voltage; in the model, Cable.direct;
- a box for a ceiling route is always on the ceiling, at least routing.CLEARANCE from walls,
  at the centre of its points: among spots where the route branches to the points around
  walls (branch_reach) are nearly the shortest, the one closest to their middle (decision
  2026-11-01); for a floor group, on a wall at BOX_ABOVE_FLOOR from the floor where the path
  from the panel plus branches is smallest;
- routes run at right angles around walls (the same path as on the sheet): on the ceiling,
  or for a group with route: floor in the floor screed; at least routing.CLEARANCE (150 mm)
  from walls, except the approach to a wall point and the pass through an opening; in
  economy at any angle;
- no cable crosses the room volume (decision 2026-11-01): cable to a ceiling point runs on
  the ceiling; with a floor route a lighting group (only ceiling lights and switches) goes
  entirely on the ceiling, and in a mixed group the branch to a light rises up the wall from
  the box or panel to the ceiling and runs along the ceiling (_to_ceiling).

Line length = plan path + vertical from the connection point to the ceiling (or floor) at
both ends + tails: at the panel the cable runs down to the floor (BOARD_TAIL is the panel
height), at other connections END_ALLOWANCE. The total per cable type includes RESERVE.
Points without a group (usually low-voltage) are not counted.

Chases (wall_chases) are vertical: from the ceiling down (or the floor up) to a wall point,
at the panel and at a box. Drops on one wall closer than CHASE_SHARE share one chase, at most
CHASE_CABLES cables per chase; a shared chase runs to the farthest point. At the panel and a
box there is one chase per CHASE_CABLES cables. Power and low-voltage (circuit) cables never
share a chase, nor do ceiling and floor routes. A chase with up to CHASE_NARROW cables is
narrow, more is wide (its own price in the estimate).

Manual edits (wiring.yaml, from the viewer): a box is put at the given spot (on a wall, along
its wall, at least BOX_CLEARANCE from corners; on the ceiling, inside the room), its lines
without a manual route are routed again from the new spot; a line with a manual route
follows it, its ends snapped to the source and target nodes at right angles. An edit whose
id now means another line or box is not applied (edit_notes).

Wall passes (wall_holes): a ceiling route passes into a neighbouring room above a door or
opening, so the wall above it is drilled; up to HOLE_CABLES cables per hole, power and
low-voltage in separate holes. A floor route passes under the opening with no drilling.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from floorplan_engine.electrical.anchors import Anchor, board_anchor, point_anchor, stack_shifts
from floorplan_engine.electrical.boxes import (
    BOX_BRANCHES,
    BOX_SIZE_MM,
    anchor_end,
    box_size,
    branch_reach,
    moved_anchor,
    place_box,
    place_ceiling_box,
    split_points,
)
from floorplan_engine.electrical.chases import (
    passages,
    wall_chases,
    wall_holes,
)
from floorplan_engine.electrical.groups import group_key
from floorplan_engine.electrical.routing import (
    Router,
    fit_path,
    free_area,
    is_ortho,
    length,
    room_area,
)
from floorplan_engine.electrical.wiring_model import (
    Circuit,
    JunctionBox,
    Route,
    Run,
    Wiring,
)
from floorplan_engine.model.geometry import Contour, RoomGeometry, Vec, room_geometries
from floorplan_engine.model.scale import DEFAULT_SCALE, drawing_scale, sheet
from floorplan_engine.model.schema import (
    Board,
    Cable,
    Electrical,
    ElectricalPoint,
    Plan,
    PointType,
    WireEdit,
    WiringEdits,
)

END_ALLOWANCE = 200.0  # mm: cable tail at every connection except the panel
RESERVE = 0.15  # margin on the total per cable type
HEAVY_SECTION = 4.0  # mm²: from this cross-section a line goes from the panel without boxes
POWER_TYPES = frozenset({PointType.SOCKET, PointType.OUTLET})
LOW_TYPES = frozenset({PointType.DATA, PointType.TV})  # low-voltage
SWITCH_TYPES = frozenset({PointType.SWITCH, PointType.PASS_SWITCH})
# Lighting in a room always goes through a box (decision 2026-10-21)
LIGHT_TYPES = frozenset(
    {
        PointType.LIGHT,
        PointType.DOWNLIGHT,
        PointType.PENDANT,
        PointType.SCONCE,
        PointType.SWITCH,
        PointType.PASS_SWITCH,
        PointType.LED_OUTPUT,
    }
)
DEFAULT_MARK = {"power": "3x2.5", "light": "3x1.5", "data": "UTP cat.6", "tv": "RG-6"}


def _cable(elec: Electrical, group: str) -> Cable | None:
    return next((c for c in elec.cables if c.group == group), None)


def _mark(cable: Cable | None, points: Sequence[ElectricalPoint]) -> tuple[str, bool]:
    if cable is not None:
        return cable.cable, False
    if all(p.type in LOW_TYPES for p in points):
        kind = "tv" if all(p.type is PointType.TV for p in points) else "data"
    else:
        kind = "power" if any(p.type in POWER_TYPES for p in points) else "light"
    return DEFAULT_MARK[kind], True


def section(mark: str) -> float:
    """Conductor cross-section from a type: "3x6" → 6, "5х2,5" → 2.5; 0 if unreadable."""
    m = re.search(r"[xх×]\s*(\d+(?:[.,]\d+)?)", mark)
    return float(m.group(1).replace(",", ".")) if m else 0.0


def _direct(
    cable: Cable | None, mark: str, points: Sequence[ElectricalPoint], circuit: Circuit
) -> bool:
    """Direct lines from the panel without boxes."""
    if cable is not None and cable.direct is not None:
        return cable.direct
    return (
        circuit == "low"
        or section(mark) >= HEAVY_SECTION
        or all(p.type is PointType.OUTLET for p in points)
    )


def _rise(pt: ElectricalPoint, ceiling: float, route: Route) -> float:
    """From the connection point to the route plane, mm: up to the ceiling (a ceiling point
    gives 0) or down to the floor (a ceiling point gives the whole wall height)."""
    if pt.ceiling is not None:
        return ceiling if route == "floor" else 0.0
    assert pt.height is not None  # a wall point always has a height (validated)
    return pt.height if route == "floor" else max(ceiling - pt.height, 0.0)


@dataclass(frozen=True)
class _Link:
    group: str
    mark: str
    mark_assumed: bool
    source: str
    target: str
    target_anchor: Anchor
    source_rise: float
    target_rise: float
    route: Route
    circuit: Circuit
    cross: bool = False  # box branch into a neighbouring room: a switch by the door outside


@dataclass(frozen=True)
class _Context:
    """Shared by all groups: plan, connection points, panel and routes from it."""

    plan: Plan
    geoms: dict[str, RoomGeometry]
    anchors: dict[str, Anchor]
    board: Board
    from_board: Router
    free: BaseGeometry  # the whole flat with openings, for branches to switches behind a door
    any_angle: bool = False  # economy: ceiling and floor routes at any angle (routing.py)

    @property
    def ceiling(self) -> float:
        return self.plan.ceiling_height


def estimate_wiring(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical,
    edits: WiringEdits | None = None,
) -> Wiring | None:
    """Wiring for estimate quantities, always at 1:50. Bundle lanes are set in sheet mm, so route
    lengths depend slightly on the sheet scale; the estimate does not depend on paper size: it is
    the same on A2, A3 and in out/estimate.*."""
    with drawing_scale(DEFAULT_SCALE):
        return box_wiring(plan, contours, elec, edits)


def box_wiring(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical,
    edits: WiringEdits | None = None,
) -> Wiring | None:
    """Wiring through boxes; None without a panel or grouped points. edits are manual edits from
    wiring.yaml: box spots and line routes."""
    if elec.board is None:
        return None
    grouped = [p for p in elec.points if p.group]
    if not grouped:
        return None
    geoms = {g.room.id: g for g in room_geometries(plan, contours)}
    shifts = stack_shifts(elec.points)
    free = free_area(list(geoms.values()))
    # Economy saves cable: on ceiling and floor along the shortest path (docs/wiring-variants.md)
    any_angle = elec.mode == "economy"
    ctx = _Context(
        plan,
        geoms,
        {p.id: point_anchor(p, geoms, shifts[k]) for k, p in enumerate(elec.points)},
        elec.board,
        Router(free, anchor_end(board_anchor(elec.board, geoms)), any_angle),
        free,
        any_angle,
    )
    boxes: list[JunctionBox] = []
    links: list[_Link] = []
    for group in sorted({p.group for p in grouped if p.group}, key=group_key):
        pts = [p for p in grouped if p.group == group]
        links += _group_links(ctx, elec, group, pts, boxes)
    boxes = _sized(boxes, links)
    edited: set[str] = set()
    notes: list[tuple[str, str]] = []
    if edits is not None:
        boxes, links = _moved_boxes(ctx, boxes, links, edits, edited, notes)
    runs = _route_runs(ctx, links, boxes)
    if edits is not None:
        runs = _manual_runs(runs, edits.wires, free, edited, notes, any_angle)
    height_assumed = "ceiling_height" not in plan.model_fields_set
    skipped = tuple(p.id for p in elec.points if not p.group)
    chases = wall_chases(runs, elec.points, elec.board, boxes)
    holes = wall_holes(runs, passages(list(geoms.values())))
    return Wiring(
        ctx.ceiling,
        height_assumed,
        tuple(boxes),
        tuple(runs),
        skipped,
        chases,
        holes,
        free,
        frozenset(edited),
        tuple(notes),
    )


def _moved_boxes(
    ctx: _Context,
    boxes: Sequence[JunctionBox],
    links: Sequence[_Link],
    edits: WiringEdits,
    edited: set[str],
    notes: list[tuple[str, str]],
) -> tuple[list[JunctionBox], list[_Link]]:
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
    new_links = [
        replace(ln, target_anchor=moved[ln.target]) if ln.target in moved else ln for ln in links
    ]
    return out, new_links


def _manual_runs(
    runs: Sequence[Run],
    wires: dict[str, WireEdit],
    free: BaseGeometry,
    edited: set[str],
    notes: list[tuple[str, str]],
    any_angle: bool = False,
) -> list[Run]:
    """Lines with a manual route from wiring.yaml; ends at the source and target nodes. Slanted
    pieces only in economy (any_angle); in standard and premium such an edit is not applied."""
    by_id = {r.id: r for r in runs}
    manual: dict[str, Run] = {}
    inside = free.buffer(1.0)
    for rid, e in sorted(wires.items()):
        r = by_id.get(rid)
        where = f"wires.{rid}"
        if r is None or (r.source, r.target) != (e.from_, e.to):
            now = "её нет" if r is None else f"это линия {r.source} → {r.target}"
            notes.append((where, f"линия {e.from_} → {e.to} не найдена ({now}) — автотрасса"))
            continue
        given = [Vec(*p) for p in e.path]
        if not any_angle and not is_ortho(given):
            notes.append((where, "участок не по оси: под углом — только в экономе — автотрасса"))
            continue
        path = tuple(fit_path(given, r.path[0], r.path[-1]))
        if not inside.covers(LineString([v.as_tuple() for v in path])):
            notes.append((where, "ручная трасса проходит сквозь стену"))
        manual[rid] = replace(r, path=path, plan_mm=length(path))
        edited.add(f"wire:{rid}")
    return [manual.get(r.id, r) for r in runs]


def _group_links(
    ctx: _Context,
    elec: Electrical,
    group: str,
    pts: Sequence[ElectricalPoint],
    boxes: list[JunctionBox],
) -> list[_Link]:
    """Lines of one group by room: through a box, or each point from the panel.
    New boxes are appended to boxes."""
    cable = _cable(elec, group)
    mark, assumed = _mark(cable, pts)
    # Route: the group's cable route if it has one; without a cable, the shared electrical route
    # (wiring variant)
    floor = cable.route == "floor" if cable is not None else elec.route == "floor"
    # Lighting (only ceiling lights and switches) runs on the ceiling even with a floor route:
    # otherwise cable from the floor to a light would cross the room volume
    lighting = any(p.ceiling is not None for p in pts) and all(
        p.ceiling is not None or p.type in SWITCH_TYPES for p in pts
    )
    route: Route = "floor" if floor and not lighting else "ceiling"
    circuit: Circuit = "low" if all(p.type in LOW_TYPES for p in pts) else "power"
    no_boxes = _direct(cable, mark, pts, circuit)
    height = ctx.board.height
    board_rise = height if route == "floor" else max(ctx.ceiling - height, 0.0)
    links: list[_Link] = []

    def link(
        src: str,
        dst: str,
        b: Anchor,
        up: float,
        down: float,
        cross: bool = False,
        way: Route | None = None,
    ) -> None:
        line = _Link(group, mark, assumed, src, dst, b, up, down, way or route, circuit, cross)
        links.append(line)

    def to_point(
        src: str, from_height: float, up: float, p: ElectricalPoint, cross: bool = False
    ) -> None:
        """Branch to a point; to a ceiling point with a floor route, up the wall and along the
        ceiling
        (from_height is the connection height at the source, from the floor)."""
        if route == "floor" and p.ceiling is not None:
            up = max(ctx.ceiling - from_height, 0.0)
            link(src, p.id, ctx.anchors[p.id], up, 0.0, cross, way="ceiling")
            return
        link(src, p.id, ctx.anchors[p.id], up, _rise(p, ctx.ceiling, route), cross)

    def direct(p: ElectricalPoint) -> None:
        to_point("board", height, board_rise, p)

    # A switch is tapped into the box of its light: in a room where the group has only
    # switches (by the door outside) they get no box or panel line of their own
    lit = {p.room for p in pts if p.type not in SWITCH_TYPES}
    outside = [] if no_boxes else [p for p in pts if p.type in SWITCH_TYPES and p.room not in lit]
    for room in ctx.plan.rooms:
        here = [p for p in pts if p.room == room.id and p not in outside]
        if not here:
            continue
        has_light = any(p.type in LIGHT_TYPES for p in here)
        if no_boxes or not (len(here) >= 2 or has_light):
            for p in here:
                direct(p)
            continue
        # At most BOX_BRANCHES branches per box: more points means boxes by zone
        zones = split_points([ctx.anchors[p.id].node for p in here], BOX_BRANCHES)
        for zone in zones:
            part = [here[i] for i in zone]
            spot = _box_spot(ctx, room.id, part, boxes, route)
            if spot is None:  # no wall space for a box: each point from the panel
                for p in part:
                    direct(p)
                continue
            n = len(boxes) + 1
            size = box_size(len(part) + 1)
            box = JunctionBox(f"box_{n}", f"К{n}", room.id, group, spot, route, room.wet, size)
            boxes.append(box)
            link("board", box.id, spot, board_rise, box.rise_mm)
            for p in part:
                to_point(box.id, _box_height(box, ctx.ceiling), box.rise_mm, p)
    own = [b for b in boxes if b.group == group]
    for p in outside:
        near = _nearest_box(ctx, own, ctx.anchors[p.id])
        if near is None:  # group has no box: switch from the panel
            direct(p)
            continue
        to_point(near.id, _box_height(near, ctx.ceiling), near.rise_mm, p, cross=True)
    return links


def _box_height(box: JunctionBox, ceiling: float) -> float:
    """Box height from the floor: on a wall for a floor route, rise_mm from the floor; under the
    ceiling, ceiling minus rise_mm; on the ceiling, the ceiling."""
    return box.rise_mm if box.route == "floor" else ceiling - box.rise_mm


def _nearest_box(ctx: _Context, boxes: Sequence[JunctionBox], target: Anchor) -> JunctionBox | None:
    """Group box with the shorter path to the point through the flat (via openings)."""
    best: tuple[float, JunctionBox] | None = None
    for b in boxes:
        cost = Router(ctx.free, anchor_end(b.anchor), ctx.any_angle).cost(target.node)
        if best is None or cost < best[0]:
            best = (cost, b)
    return None if best is None else best[1]


def _sized(boxes: Sequence[JunctionBox], links: Sequence[_Link]) -> list[JunctionBox]:
    """Box size by the final number of lines, including switches behind the door."""
    lines = {b.id: 1 + sum(1 for ln in links if ln.source == b.id) for b in boxes}
    return [replace(b, size=box_size(lines[b.id])) for b in boxes]


def _box_spot(
    ctx: _Context,
    room: str,
    part: Sequence[ElectricalPoint],
    boxes: Sequence[JunctionBox],
    route: Route,
) -> Anchor | None:
    """Box spot for the points of a zone: on the ceiling at the centre of the points for a ceiling
    route, on a wall for a floor route."""
    g = ctx.geoms[room]
    taken = [b.anchor.node for b in boxes if b.room == room]
    targets = [ctx.anchors[p.id] for p in part]
    reach = branch_reach(g, targets, ctx.any_angle)
    if route == "floor":
        return place_box(g, ctx.from_board, reach, taken)
    return place_ceiling_box(g, reach, targets, taken, sheet(BOX_SIZE_MM))


def _route_runs(ctx: _Context, links: Sequence[_Link], boxes: Sequence[JunctionBox]) -> list[Run]:
    """Line routes: from the panel through the whole flat, from a box only inside its room."""
    routers = {
        b.id: Router(room_area(ctx.geoms[b.room]), anchor_end(b.anchor), ctx.any_angle)
        for b in boxes
    }
    # Branch to a switch behind a door: through the whole flat via the opening
    wide = {
        b.id: Router(ctx.free, anchor_end(b.anchor), ctx.any_angle)
        for b in boxes
        if any(ln.cross and ln.source == b.id for ln in links)
    }
    board_tail = ctx.board.height  # tail inside the panel down to the floor
    runs: list[Run] = []
    for k, ln in enumerate(links):
        if ln.source == "board":
            router = ctx.from_board
        else:
            router = wide[ln.source] if ln.cross else routers[ln.source]
        path = tuple(router.route(anchor_end(ln.target_anchor)))
        runs.append(
            Run(
                id=f"wire_{k + 1}",
                group=ln.group,
                mark=ln.mark,
                mark_assumed=ln.mark_assumed,
                source=ln.source,
                target=ln.target,
                path=path,
                plan_mm=length(path),
                rise_start_mm=ln.source_rise,
                rise_end_mm=ln.target_rise,
                ends_mm=END_ALLOWANCE + (board_tail if ln.source == "board" else END_ALLOWANCE),
                route=ln.route,
                circuit=ln.circuit,
            )
        )
    return runs
