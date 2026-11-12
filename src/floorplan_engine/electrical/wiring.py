"""Wiring through junction boxes: topology, routes and cable lengths, all from the model.

Variant rules:
- cable runs only from the panel to a box, from the panel to a load or from a box to a load;
  never from a load to a box or from box to box. With the loop distribution wall sockets are
  the exception: in a room, two or more sockets of a group go in a daisy chain through their
  flush boxes, nearest to the panel first, with no junction box and at most BOX_BRANCHES on a
  chain, each chain on its own panel line. Light, switches and direct lines stay as they are;
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
- light in a chain without boxes (Electrical.light_wiring "chain", decision 2026-11-11, see
  _light_chains): panel → switch → its lights one after another; pass switches panel → first →
  second (PASS_MARK) → lights; a LIGHT_LOOP loop at each ceiling light for its future output.
  Otherwise light goes through a box, as below;
- LED supplies in the panel (Electrical.led_supply "board", decision 2026-11-11): each LED
  output gets a 12 V line of its own from the panel (LED_MARK, low-voltage chases), in the
  group of the output; its switch stays in the group as before. With supplies at the strip
  ("room") the output is a light point of the group, through its box;
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
Points without a group are not counted, except low-voltage (decision 2026-11-11): internet and
TV without a group get a line of their own each (group "Связь" by language) from the
low-voltage cabinet `media`, without it from the panel (assumption); the cabinet tail is like
the panel's.

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

Master switch (master.py): its control cable (CONTROL_MARK) runs from the panel to the switch as
a line of its own, the "group" of the control breaker (SF1), whatever group the source gave the
switch: it drives the contactor coil, not a light.

Wall passes (wall_holes): a ceiling route passes into a neighbouring room above a door or
opening, so the wall above it is drilled; one hole per entry into a room (more than
HOLE_CABLES cables: a large one), power and low-voltage in separate holes. A floor route passes
under the opening with no drilling. If the way round through a door is long, a route goes
straight through a drillable wall (routing.drillable_walls: not load-bearing, not outer, no
thicker than WALL_DRILL_MAX; decision 2026-11-11), at the ceiling or at the floor; such holes
are counted the same way.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

import shapely
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from floorplan_engine.electrical.anchors import Anchor, board_anchor, point_anchor
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
    before_plaster,
    channel_chases,
    passages,
    shared_rises,
    wall_chases,
    wall_holes,
    with_conduit,
    with_material,
)
from floorplan_engine.electrical.groups import group_key
from floorplan_engine.electrical.groups import text as group_text
from floorplan_engine.electrical.loads import DEFAULT_MARK, LOW_TYPES, POWER_TYPES, assumed_mark
from floorplan_engine.electrical.master import CONTROL_ID, CONTROL_MARK, master_point
from floorplan_engine.electrical.routing import (
    Router,
    drillable_walls,
    fit_path,
    free_area,
    is_ortho,
    length,
    room_area,
)
from floorplan_engine.electrical.switch_links import switch_links
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
SWITCH_TYPES = frozenset({PointType.SWITCH, PointType.PASS_SWITCH})
# Lighting in a room goes through a box (decision 2026-10-21), unless in a chain (light_wiring)
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
LED_MARK = "2x1.5"  # 12 V line from a LED supply in the panel to its output (assumption)
# Light in a chain without boxes (Electrical.light_wiring "chain")
LAMP_TYPES = LIGHT_TYPES - SWITCH_TYPES  # lights and LED outputs, without switches
LIGHT_LOOP = 600.0  # mm: cable loop at each ceiling light of a chain, 30 cm each way
PASS_MARK = "5x1.5"  # between pass switches without a box (assumption)
TWO_KEY_MARK = "4x1.5"  # from a two-key switch to its lights: two switched lines (assumption)


def _cable(elec: Electrical, group: str) -> Cable | None:
    return next((c for c in elec.cables if c.group == group), None)


def _mark(
    elec: Electrical, group: str, cable: Cable | None, points: Sequence[ElectricalPoint]
) -> tuple[str, bool]:
    if cable is not None:
        return cable.cable, False
    return assumed_mark(elec, group, points), True


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
    ends: float | None = None  # cable at both ends, mm; None: END_ALLOWANCE and the source tail


@dataclass(frozen=True)
class _Context:
    """Shared by all groups: plan, connection points, panel and routes from it."""

    plan: Plan
    geoms: dict[str, RoomGeometry]
    anchors: dict[str, Anchor]
    board: Board
    from_board: Router
    free: BaseGeometry  # the whole flat with openings, for branches to switches behind a door
    any_angle: bool = False  # ceiling and floor routes at any angle (routing.py)
    rooms: dict[str, str] = field(default_factory=dict)  # room of each point
    media: Board | None = None  # low-voltage cabinet (source "media")
    from_media: Router | None = None
    walls: Sequence[Polygon] = ()  # drillable walls (routing.drillable_walls)

    def tail(self, source: str) -> float:
        """Tail inside the panel or the cabinet down to the floor; END_ALLOWANCE elsewhere."""
        if source == "media" and self.media is not None:
            return self.media.height
        return self.board.height if source == "board" else END_ALLOWANCE

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
    master = master_point(elec)
    grouped = [p for p in elec.points if p.group and p is not master]
    # LED supplies in the panel: each output a 12 V line of its own, outside the group's boxes
    led = [p for p in grouped if elec.led_supply == "board" and p.type is PointType.LED_OUTPUT]
    grouped = [p for p in grouped if p not in led]
    low = [p for p in elec.points if not p.group and p.type in LOW_TYPES]
    if not grouped and not low:
        return None
    geoms = {g.room.id: g for g in room_geometries(plan, contours)}
    free = free_area(list(geoms.values()))
    walls = drillable_walls(list(geoms.values()))
    # On ceiling and floor along the shortest path, economy by default (docs/wiring-variants.md)
    any_angle = elec.shortest_path
    ctx = _Context(
        plan,
        geoms,
        # At the wall, not at the stacked symbol: the cable ends where the point really is
        {p.id: point_anchor(p, geoms) for p in elec.points},
        elec.board,
        Router(free, anchor_end(board_anchor(elec.board, geoms)), any_angle, walls),
        free,
        any_angle,
        {p.id: p.room for p in elec.points},
        elec.media,
        None
        if elec.media is None
        else Router(free, anchor_end(board_anchor(elec.media, geoms)), any_angle, walls),
        walls,
    )
    boxes: list[JunctionBox] = []
    links: list[_Link] = []
    for group in sorted({p.group for p in grouped if p.group}, key=group_key):
        pts = [p for p in grouped if p.group == group]
        links += _group_links(ctx, elec, group, pts, boxes)
    if master is not None:
        links.append(_control_link(ctx, elec, master))
    links += [_low_link(ctx, elec, p) for p in low]
    links += [_led_link(ctx, elec, p) for p in led]
    boxes = _sized(boxes, links)
    edited: set[str] = set()
    notes: list[tuple[str, str]] = []
    if edits is not None:
        boxes, links = _moved_boxes(ctx, boxes, links, edits, edited, notes)
    runs = _route_runs(ctx, links, boxes)
    if edits is not None:
        passable = shapely.unary_union([free, *walls]) if walls else free
        runs = _manual_runs(runs, edits.wires, passable, edited, notes, any_angle)
    height_assumed = "ceiling_height" not in plan.model_fields_set
    skipped = tuple(p.id for p in elec.points if not p.group and p is not master and p not in low)
    drops = with_conduit(
        wall_chases(runs, elec.points, elec.board, boxes, elec.media),
        elec.conduit_level,
        elec.loop_conduit,
    )
    chases = drops + channel_chases(elec.cable_channels)
    if elec.plaster == "before":
        chases = before_plaster(chases)
    chases = with_material(chases, plan)
    holes = wall_holes(runs, passages(list(geoms.values())), walls)
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
        elec.plaster == "before",
        drops,
        shared_rises(runs, elec.points, elec.conduit_level, elec.loop_conduit),
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
    pieces only on the shortest path (any_angle); at right angles such an edit is not applied."""
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
            notes.append(
                (where, "участок не по оси: под углом — только при кратчайшем пути — автотрасса")
            )
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
    mark, assumed = _mark(elec, group, cable, pts)
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

    def chain(part: Sequence[ElectricalPoint]) -> None:
        """Daisy chain: the point nearest to the panel from it, then from point to point."""
        left = sorted(part, key=lambda p: (ctx.from_board.cost(ctx.anchors[p.id].node), p.id))
        prev = left.pop(0)
        direct(prev)
        while left:
            at = ctx.anchors[prev.id].node
            p = min(left, key=lambda q: ((ctx.anchors[q.id].node - at).length(), q.id))
            left.remove(p)
            assert prev.height is not None  # only wall points go in a chain
            to_point(prev.id, prev.height, _rise(prev, ctx.ceiling, route), p)
            prev = p

    if elec.light_wiring == "chain" and not no_boxes:
        chained, done = _light_chains(ctx, elec, pts, [], group, mark, assumed, route)
        links += chained
        pts = [p for p in pts if p.id not in done]
    # A switch is tapped into the box of its light: in a room where the group has only
    # switches (by the door outside) they get no box or panel line of their own
    lit = {p.room for p in pts if p.type not in SWITCH_TYPES}
    outside = [] if no_boxes else [p for p in pts if p.type in SWITCH_TYPES and p.room not in lit]
    for room in ctx.plan.rooms:
        here = [p for p in pts if p.room == room.id and p not in outside]
        looped = _looped(here) if elec.distribution == "loop" and not no_boxes else []
        if looped:
            nodes = [ctx.anchors[p.id].node for p in looped]
            for zone in split_points(nodes, BOX_BRANCHES):
                chain([looped[i] for i in zone])
            here = [p for p in here if p not in looped]
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


def _light_chains(
    ctx: _Context,
    elec: Electrical,
    pts: Sequence[ElectricalPoint],
    out: list[_Link],
    group: str,
    mark: str,
    assumed: bool,
    route: Route,
) -> tuple[list[_Link], set[str]]:
    """Light of a group in a chain without boxes (decision 2026-11-11): panel → switch, from it
    its lights one after another, nearest first (switch_links: what it turns on). Pass switches
    that share lights go panel → first → second (PASS_MARK) → lights; a two-key switch feeds
    its lights with TWO_KEY_MARK. Lights no switch takes go in a chain from the panel; a switch
    with no light of the group gets a line of its own. At each ceiling light the cable leaves a
    LIGHT_LOOP loop, the reserve for the light output; the cable is on the ceiling wherever a
    ceiling point is at either end. Returns the links and the ids of the points they took."""
    lamps = {p.id: p for p in pts if p.type in LAMP_TYPES}
    switches = [p for p in pts if p.type in SWITCH_TYPES]
    on: dict[str, list[str]] = {s.id: [] for s in switches}
    for lk in switch_links(elec):
        if lk.switch in on:
            on[lk.switch] = [t for t in lk.targets if t in lamps]
    taken: set[str] = set()
    ceiling = ctx.ceiling

    def loop(p: ElectricalPoint) -> bool:
        return p.ceiling is not None and p.type in LAMP_TYPES

    def board_link(p: ElectricalPoint, cable: str, cable_assumed: bool) -> None:
        way: Route = "ceiling" if route == "ceiling" or p.ceiling is not None else "floor"
        up = ctx.board.height if way == "floor" else max(ceiling - ctx.board.height, 0.0)
        ends = (LIGHT_LOOP if loop(p) else END_ALLOWANCE) + ctx.tail("board")
        down = _rise(p, ceiling, way)
        line = _Link(group, cable, cable_assumed, "board", p.id, ctx.anchors[p.id], up, down, way,
                     "power", False, ends)  # fmt: skip
        out.append(line)

    def point_link(a: ElectricalPoint, b: ElectricalPoint, cable: str, cable_assumed: bool) -> None:
        on_ceiling = route == "ceiling" or a.ceiling is not None or b.ceiling is not None
        way: Route = "ceiling" if on_ceiling else "floor"
        ends = (0.0 if loop(a) else END_ALLOWANCE) + (LIGHT_LOOP if loop(b) else END_ALLOWANCE)
        line = _Link(group, cable, cable_assumed, a.id, b.id, ctx.anchors[b.id],
                     _rise(a, ceiling, way), _rise(b, ceiling, way), way, "power",
                     a.room != b.room, ends)  # fmt: skip
        out.append(line)

    def chain(start: ElectricalPoint, ids: Sequence[str], cable: str, cable_assumed: bool) -> None:
        left = [lamps[i] for i in dict.fromkeys(ids) if i not in taken]  # pass switches share
        taken.update(p.id for p in left)
        prev = start
        while left:
            at = ctx.anchors[prev.id].node
            p = min(left, key=lambda q: ((ctx.anchors[q.id].node - at).length(), q.id))
            left.remove(p)
            point_link(prev, p, cable, cable_assumed)
            prev = p

    # Pass switches that share a light are one set
    sets: list[list[ElectricalPoint]] = []
    for s in (s for s in switches if s.type is PointType.PASS_SWITCH):
        mine = set(on[s.id])
        joined = [g for g in sets if mine & {t for x in g for t in on[x.id]}]
        merged = [x for g in joined for x in g] + [s]
        sets = [g for g in sets if g not in joined] + [merged]
    for g in sets:
        g.sort(key=lambda x: (ctx.from_board.cost(ctx.anchors[x.id].node), x.id))
        board_link(g[0], mark, assumed)
        for a, b in itertools.pairwise(g):
            point_link(a, b, PASS_MARK, True)
        chain(g[-1], [t for x in g for t in on[x.id]], mark, assumed)
    for s in (s for s in switches if s.type is not PointType.PASS_SWITCH):
        board_link(s, mark, assumed)
        two = s.keys == 2
        chain(s, on[s.id], TWO_KEY_MARK if two else mark, two or assumed)
    free = [p for p in lamps.values() if p.id not in taken]
    if free:
        first = min(free, key=lambda p: (ctx.from_board.cost(ctx.anchors[p.id].node), p.id))
        taken.add(first.id)
        board_link(first, mark, assumed)
        chain(first, [p.id for p in free], mark, assumed)
    return out, {*lamps, *(s.id for s in switches)}


def _control_link(ctx: _Context, elec: Electrical, p: ElectricalPoint) -> _Link:
    """Control cable of the master switch: straight from the panel along the electrical route."""
    route: Route = "floor" if elec.route == "floor" else "ceiling"
    height = ctx.board.height
    up = height if route == "floor" else max(ctx.ceiling - height, 0.0)
    down = _rise(p, ctx.ceiling, route)
    anchor = ctx.anchors[p.id]
    return _Link(CONTROL_ID, CONTROL_MARK, False, "board", p.id, anchor, up, down, route, "power")


def _low_link(ctx: _Context, elec: Electrical, p: ElectricalPoint) -> _Link:
    """Low-voltage point without a group: a line of its own from the cabinet, else the panel."""
    source = "media" if ctx.media is not None else "board"
    height = ctx.tail(source)
    route: Route = "floor" if elec.route == "floor" else "ceiling"
    up = height if route == "floor" else max(ctx.ceiling - height, 0.0)
    mark = DEFAULT_MARK["tv" if p.type is PointType.TV else "data"]
    group = group_text("low", ctx.plan.language)
    down = _rise(p, ctx.ceiling, route)
    return _Link(group, mark, True, source, p.id, ctx.anchors[p.id], up, down, route, "low")


def _led_link(ctx: _Context, elec: Electrical, p: ElectricalPoint) -> _Link:
    """LED output fed from a supply in the panel: a 12 V line of its own from the panel along the
    electrical route, in the group of the output (its breaker feeds the supply). Low voltage, so
    it does not share chases with 230 V cables."""
    assert p.group is not None
    route: Route = "floor" if elec.route == "floor" else "ceiling"
    height = ctx.board.height
    up = height if route == "floor" else max(ctx.ceiling - height, 0.0)
    down = _rise(p, ctx.ceiling, route)
    return _Link(p.group, LED_MARK, True, "board", p.id, ctx.anchors[p.id], up, down, route, "low")


def _looped(points: Sequence[ElectricalPoint]) -> list[ElectricalPoint]:
    """Wall sockets of a room that go in a daisy chain; a single one stays where it was."""
    sockets = [p for p in points if p.type in POWER_TYPES and p.ceiling is None]
    return sockets if len(sockets) >= 2 else []


def _box_height(box: JunctionBox, ceiling: float) -> float:
    """Box height from the floor: on a wall for a floor route, rise_mm from the floor; under the
    ceiling, ceiling minus rise_mm; on the ceiling, the ceiling."""
    return box.rise_mm if box.route == "floor" else ceiling - box.rise_mm


def _nearest_box(ctx: _Context, boxes: Sequence[JunctionBox], target: Anchor) -> JunctionBox | None:
    """Group box with the shorter path to the point through the flat (via openings)."""
    best: tuple[float, JunctionBox] | None = None
    for b in boxes:
        cost = Router(ctx.free, anchor_end(b.anchor), ctx.any_angle, ctx.walls).cost(target.node)
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
    """Line routes: from the panel through the whole flat, from a box or a socket of a daisy chain
    only inside its room."""
    routers = {
        b.id: Router(room_area(ctx.geoms[b.room]), anchor_end(b.anchor), ctx.any_angle)
        for b in boxes
    }
    # Branch to a switch behind a door, and a light chain into the next room: through the whole
    # flat via the opening
    box_anchors = {b.id: b.anchor for b in boxes}
    wide = {
        src: Router(
            ctx.free, anchor_end(box_anchors.get(src) or ctx.anchors[src]), ctx.any_angle, ctx.walls
        )
        for src in {ln.source for ln in links if ln.cross}
    }
    for src in {ln.source for ln in links} - set(routers) - {"board", "media"}:  # a daisy chain
        area = room_area(ctx.geoms[ctx.rooms[src]])
        routers[src] = Router(area, anchor_end(ctx.anchors[src]), ctx.any_angle)
    runs: list[Run] = []
    for k, ln in enumerate(links):
        if ln.source == "board":
            router = ctx.from_board
        elif ln.source == "media" and ctx.from_media is not None:
            router = ctx.from_media
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
                ends_mm=END_ALLOWANCE + ctx.tail(ln.source) if ln.ends is None else ln.ends,
                route=ln.route,
                circuit=ln.circuit,
            )
        )
    return runs
