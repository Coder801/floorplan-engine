"""Wiring through junction boxes: topology, routes and cable lengths, all from the model.

Variant rules:
- one cable of a group comes into a room (decision 2026-11-13, _one_feed): the group's box
  nearest to the panel is fed from the panel, its other boxes in the room from the nearest box
  already fed; with light in a chain, the switch nearest to the panel is fed from the panel and
  the cable branches in its flush box to the group's other switches, in the room and behind a
  door (see _light_chains). Where every panel line has its own breaker (premium panel, proper
  layout: lines.per_line) each box and each switch keeps a panel line of its own, as before;
- otherwise cable runs only from the panel to a box, from the panel to a load or from a box to a
  load; never from a load to a box. With the loop distribution wall sockets are
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
  boxes are split by zone (split_points); box size is the smallest for the number of lines
  (box_size, the feeds to the next boxes count), 190×140 only as a last resort;
- direct lines run from the panel to each point without boxes: cross-section from
  HEAVY_SECTION mm² (hob, oven, boiler), a group made only of appliance outputs (air
  conditioner, towel rail) and floor heating controllers (`thermostat`), and low-voltage; in
  the model, Cable.direct;
- light in a chain without boxes (Electrical.light_wiring "chain", decision 2026-11-11, see
  _light_chains): panel → switch → its lights one after another; pass switches panel → first →
  second (PASS_MARK) → lights; a LIGHT_LOOP loop at each ceiling light for its future output.
  The group's other switches in the room are fed from a switch flush box, not from the panel;
  Otherwise light goes through a box, as below;
- behind a box, lights of one set (decision 2026-11-18, _lamp_sets: one kind, the same
  switches) share one cable: the box feeds the nearest of them, the cable goes on from light to
  light with a LIGHT_LOOP at each ceiling light; a box joins different sets, switches and
  outputs, it does not split one set into branches;
- LED supplies in the panel (Electrical.led_supply "board", decision 2026-11-11): each LED
  output gets a 12 V line of its own from the panel (Run.led, low-voltage chases), in the
  group of the output; its switch stays in the group as before. The supplies stand in a box
  under the panel (decision 2026-11-13), the line starts at the panel; its cross-section goes
  by the voltage drop over its final length (led_supply.section_for), LED_MARK at least.
  With supplies at the strip ("room") the output is a light point of the group, through its
  box;
- a box for a ceiling route is always on the ceiling, at least routing.CLEARANCE from walls,
  at the centre of its points: among spots where the route branches to the points around
  walls (branch_reach) are nearly the shortest, the one closest to their middle (decision
  2026-11-01); for a floor group, on a wall at BOX_ABOVE_FLOOR from the floor where the path
  from the panel plus branches is smallest;
- a box does not stand on lines that do not go into it (decision 2026-11-17, _clear_boxes):
  after routing, a box whose square touches a passing line of its plane (with the bundle lanes
  as on the sheet) moves to the nearest spot by the rule above off those lines, and the lines
  are routed again; a box moved by hand, or with no such spot, stays, with a warning;
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
the panel's. A cable without a group whose targets are all such points (decision 2026-11-17,
low_feeds) sets their source from the project: `board`, `media` or another low point (one UTP
to the TV zone, separate lines from there on); each target gets a line of its own from it, of
the cable's type. A line from a point goes through the whole flat via the openings.

A box on the ceiling (floor) with 2 to ONE_SIDE_MAX cables takes them all from one side
(decision 2026-11-18, _one_side): they leave it together, straight, for BOX_LEAD_MM and part only
there, so the cables lie evenly; boxes with more cables keep their routes.

Internet and TV apart from power (decision 2026-11-13, _apart, routing.apart_cells): on the
ceiling and on the floor such a cable runs no closer than routing.APART (150 mm) beside a power
cable and crosses it at 90°. It is routed after the power lines (with their manual routes), so it
goes round them; it comes closer only where there is no other way (a socket block, a narrow
corridor). Within routing.PANEL_FREE (300 mm) of the panel neither the distance nor the 90°
crossing applies (decision 2026-11-18). A 12 V LED line is not held apart; a manual route of
the cable itself stays as drawn; at any angle (economy) the rule is not applied.

Chases (wall_chases) are vertical: from the ceiling down (or the floor up) to a wall point,
at the panel and at a box. A drop never crosses an opening: to a point under a window it goes
down beside the window (detours.py) and turns at 90° along the wall to the point; the route
on the ceiling ends at the drop, the turn is part of the rise. Drops on one wall closer than
CHASE_SHARE share one chase, at most
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
under the opening with no drilling. A route goes straight through a drillable wall
(routing.drillable_walls: not load-bearing, not outer, no thicker than WALL_DRILL_MAX; decision
2026-11-11), at the ceiling or at the floor, when that is shorter; such holes are counted the
same way. The search prices the passes as the estimate counts them (decision 2026-11-23,
routing.py): on the ceiling an opening lower than the ceiling costs the same pass as a wall, on
the floor an opening is free, and a hole already made by a line of the build is free for the
next lines of its plane and circuit within WALL_HOLE_SHARE, so lines of one source into a room
go through one hole (_route_runs: lines are routed one after another, in a fixed order).
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from floorplan_engine.electrical import trace
from floorplan_engine.electrical.anchors import Anchor, board_anchor, point_anchor
from floorplan_engine.electrical.boxes import (
    BOX_BRANCHES,
    BOX_SIZE_MM,
    anchor_end,
    box_size,
    box_square,
    branch_reach,
    moved_anchor,
    place_box,
    place_ceiling_box,
    split_points,
)
from floorplan_engine.electrical.bundles import lane_paths
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
from floorplan_engine.electrical.detours import drop_offset
from floorplan_engine.electrical.floor_heating import heating_zones
from floorplan_engine.electrical.frames import entries
from floorplan_engine.electrical.groups import group_key
from floorplan_engine.electrical.groups import text as group_text
from floorplan_engine.electrical.led_supply import led_loads, led_mark, section_for
from floorplan_engine.electrical.loads import DEFAULT_MARK, LOW_TYPES, POWER_TYPES, assumed_mark
from floorplan_engine.electrical.master import CONTROL_ID, CONTROL_MARK, master_point
from floorplan_engine.electrical.panel import scheme_of
from floorplan_engine.electrical.routing import (
    WALL_HOLE_SHARE,
    Crossing,
    End,
    Router,
    ceiling_passes,
    crossings,
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
# A group made only of these goes from the panel to each point without boxes: appliance outputs
# and floor heating controllers
DIRECT_TYPES = frozenset({PointType.OUTLET, PointType.THERMOSTAT})
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
PASS_MARK = "4x1.5"  # between pass switches without a box: two travellers, N, PE (assumption)
TWO_KEY_MARK = "4x1.5"  # from a two-key switch to its lights: two switched lines (assumption)
# One cable of a group into a room (decision 2026-11-13): it branches in a switch flush box
BACK_BOX_FEEDS = 3  # feeds to the next switches from one flush box (assumption: a deep box)
FRAME_SPAN = 100.0  # mm along the wall: mechanisms this close at one height share a frame
BOX_LINES_MAX = BOX_BRANCHES + 1  # lines in a 150×110 box: no more feeds from a full one
# A box keeps off lines that do not go into it (decision 2026-11-17, _clear_boxes): at most this
# many rounds of moving boxes and routing again; a line closer than BOX_LINE_CLEAR_MM on the sheet
# counts as touching
BOX_CLEAR_ROUNDS = 3
BOX_LINE_CLEAR_MM = 0.3
# The white box square does not cover point symbols either (2026-11-18): a symbol is kept off as
# its outline (anchors.SYMBOL_DEPTH) widened by POINT_MARK_MM for its number beside it; a wall
# symbol is at least POINT_HALF_MM wide on each side of its axis
POINT_MARK_MM = 1.5
POINT_HALF_MM = 2.0
# A box on the ceiling (floor) with this many cables or fewer takes them all from one side
# (decision 2026-11-18, _one_side): they leave it together, straight, for BOX_LEAD_MM
ONE_SIDE_MAX = 3
BOX_LEAD_MM = 150.0
SIDES = (Vec(1.0, 0.0), Vec(0.0, 1.0), Vec(-1.0, 0.0), Vec(0.0, -1.0))


def _one_feed(elec: Electrical) -> bool:
    """One cable of a group into a room, branching there; False where every line from the panel
    has its own breaker (premium panel or proper layout, as lines.per_line)."""
    return not (elec.mode == "proper" or scheme_of(elec) == "premium")


def _same_frame(a: ElectricalPoint, b: ElectricalPoint) -> bool:
    """Two wall points side by side in one frame: the cable between them does not leave the wall."""
    if a.room != b.room or a.wall != b.wall or a.offset is None or b.offset is None:
        return False
    return a.height == b.height and abs(a.offset - b.offset) <= FRAME_SPAN


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
        or all(p.type in DIRECT_TYPES for p in points)
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
    led: bool = False  # 12 V line from an LED supply in the panel
    wall: bool = False  # a jumper between mechanisms of one frame: straight along the wall


@dataclass(frozen=True)
class _Context:
    """Shared by all groups: plan, connection points, panel and routes from it."""

    plan: Plan
    geoms: dict[str, RoomGeometry]
    anchors: dict[str, Anchor]
    board: Board
    board_end: End  # where the panel's cables start
    free: BaseGeometry  # the whole flat with openings, for branches to switches behind a door
    any_angle: bool = False  # ceiling and floor routes at any angle (routing.py)
    rooms: dict[str, str] = field(default_factory=dict)  # room of each point
    media: Board | None = None  # low-voltage cabinet (source "media")
    media_end: End | None = None
    walls: Sequence[Polygon] = ()  # drillable walls (routing.drillable_walls)
    passes: Sequence[Polygon] = ()  # openings lower than the ceiling (routing.ceiling_passes)
    points: dict[str, ElectricalPoint] = field(default_factory=dict)
    # Routers from the panel and the cabinet by plane, without ready holes (from_source)
    routers: dict[tuple[str, Route], Router] = field(default_factory=dict, repr=False)

    def bands(self, route: Route) -> tuple[Polygon, ...]:
        """What a route of the plane pays to cross: drillable walls on both planes, openings
        lower than the ceiling on the ceiling only (decision 2026-11-23)."""
        return (*self.walls, *self.passes) if route == "ceiling" else tuple(self.walls)

    def flat_router(self, end: End, route: Route, holes: Sequence[Crossing] = ()) -> Router:
        """Router through the whole flat from the end on the plane: via openings and drillable
        walls, with the ready holes of the plane."""
        passes = self.passes if route == "ceiling" else ()
        return Router(self.free, end, self.any_angle, self.walls, passes=passes, holes=holes)

    def from_source(self, source: str, route: Route) -> Router:
        """Router from the panel ("board") or the low-voltage cabinet ("media") on the plane,
        without ready holes: the costs the topology is chosen by (what is nearest to the panel)
        and the first search of the lines from it."""
        key = (source, route)
        if key not in self.routers:
            end = self.media_end if source == "media" else self.board_end
            assert end is not None  # "media" only with a cabinet (_low_link)
            self.routers[key] = self.flat_router(end, route)
        return self.routers[key]

    def drop(self, pid: str, route: Route) -> tuple[Anchor, float] | None:
        """Where the cable goes down to a wall point beside an opening (detours.py): the route
        end there and the wall offset of the drop; None when it goes straight above the point."""
        p = self.points.get(pid)
        if p is None or p.offset is None:
            return None
        at = drop_offset(self.geoms[p.room], p, self.ceiling, route)
        a = self.anchors[pid]
        if at is None or a.wall_dir is None:
            return None
        return Anchor(a.pos + a.wall_dir * (at - p.offset), a.inward, a.wall_dir, a.depth), at

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
    """Wiring for estimate quantities, always at the set scale (DEFAULT_SCALE). Bundle lanes are
    set in sheet mm, so route lengths depend slightly on the sheet scale; the estimate does not
    depend on paper size: it is the same on A2, A3 and in out/estimate.*."""
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
        anchor_end(board_anchor(elec.board, geoms)),
        free,
        any_angle,
        {p.id: p.room for p in elec.points},
        elec.media,
        None if elec.media is None else anchor_end(board_anchor(elec.media, geoms)),
        walls,
        ceiling_passes(list(geoms.values()), plan.ceiling_height),
        {p.id: p for p in elec.points},
    )
    boxes: list[JunctionBox] = []
    links: list[_Link] = []
    for group in sorted({p.group for p in grouped if p.group}, key=group_key):
        pts = [p for p in grouped if p.group == group]
        links += _group_links(ctx, elec, group, pts, boxes)
    if master is not None:
        links.append(_control_link(ctx, elec, master))
    feeds = low_feeds(elec)
    links += [_low_link(ctx, elec, p, feeds.get(p.id)) for p in low]
    links += [_led_link(ctx, elec, p) for p in led]
    boxes = _sized(boxes, links)
    edited: set[str] = set()
    notes: list[tuple[str, str]] = []
    if edits is not None:
        boxes, links = _moved_boxes(ctx, boxes, links, edits, edited, notes)
    passable = shapely.unary_union([free, *walls]) if walls else free
    wire_notes: list[tuple[str, str]] = []

    rounds = itertools.count()

    def route(boxes: Sequence[JunctionBox], links: Sequence[_Link]) -> list[Run]:
        """All line routes for these box spots: auto, manual from wiring.yaml, then internet
        and TV apart from power; the manual-route notes are those of the last call."""
        with trace.scope(round=next(rounds)):
            runs = _route_runs(ctx, links, boxes)
            wire_notes.clear()
            if edits is not None:
                runs = _manual_runs(runs, edits.wires, passable, edited, wire_notes, any_angle)
            return _apart(ctx, links, boxes, runs, edited)

    runs = route(boxes, links)
    boxes, links, runs, box_notes = _clear_boxes(ctx, boxes, links, runs, route, edited)
    notes += wire_notes
    if led:
        runs = _led_sections(runs, elec)
    height_assumed = "ceiling_height" not in plan.model_fields_set
    skipped = tuple(p.id for p in elec.points if not p.group and p is not master and p not in low)
    wall_dirs = {k: a.wall_dir for k, a in ctx.anchors.items() if a.wall_dir is not None}
    entry = entries(elec.points, runs, wall_dirs)
    drops = with_conduit(
        wall_chases(runs, elec.points, elec.board, boxes, elec.media, entry),
        elec.conduit_level,
        elec.loop_conduit,
    )
    chases = drops + channel_chases(elec.cable_channels)
    if elec.plaster == "before":
        chases = before_plaster(chases)
    chases = with_material(chases, plan)
    holes = wall_holes(runs, passages(list(geoms.values()), ctx.ceiling), walls)
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
        heating_zones(plan, contours, elec),
        box_notes=tuple(box_notes),
        entries=tuple(sorted(entry.items())),
    )


def _clear_boxes(
    ctx: _Context,
    boxes: Sequence[JunctionBox],
    links: Sequence[_Link],
    runs: Sequence[Run],
    route: Callable[[Sequence[JunctionBox], Sequence[_Link]], list[Run]],
    edited: set[str],
) -> tuple[list[JunctionBox], list[_Link], list[Run], list[tuple[str, str]]]:
    """A box does not stand on lines that do not go into it (decision 2026-11-17): its square
    (boxes.box_square, as on the wiring sheet) touches only its own lines, the feed in and its
    branches. Lines of its plane (ceiling or floor) that pass by, with their bundle lanes as
    drawn (bundles.lane_paths), are checked after routing; a box on them gets the nearest
    spot by the usual rule among those off them (_box_spot with avoid), and all lines are
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
            spot = _box_spot(
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
        links = [
            replace(ln, target_anchor=moved[ln.target]) if ln.target in moved else ln
            for ln in links
        ]
        runs = route(boxes, links)
    notes: list[tuple[str, str]] = []
    left = _foreign_hits(ctx, boxes, runs)
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
    return boxes, links, runs, notes


@dataclass(frozen=True)
class BoxMove:
    """A box moved off lines that pass by (_clear_boxes), for the debug trace (trace.py)."""

    box: str
    before: Vec
    after: Vec
    avoid: BaseGeometry  # the passing lines, widened: what the box keeps off


def _foreign_hits(
    ctx: _Context, boxes: Sequence[JunctionBox], runs: Sequence[Run]
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


def _point_marks(ctx: _Context, room: str) -> BaseGeometry:
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


def _box_reach(box: str, lines: Sequence[_Link] | Sequence[Run], boxes: set[str]) -> set[str]:
    """The box and the points it feeds: its branches and the lights of a set chain behind
    them (a chain line always comes after the line to its source)."""
    reach = {box}
    for ln in lines:
        if ln.source in reach and ln.target not in boxes:
            reach.add(ln.target)
    return reach


def _box_targets(ctx: _Context, b: JunctionBox, links: Sequence[_Link]) -> list[ElectricalPoint]:
    """Points a box feeds: its branches and the lights of a set chain behind them."""
    reach = _box_reach(b.id, links, {ln.target for ln in links if ln.target not in ctx.points})
    return [ctx.points[ln.target] for ln in links if ln.target in reach and ln.target in ctx.points]


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
        wall: bool = False,
    ) -> None:
        line = _Link(group, mark, assumed, src, dst, b, up, down, way or route, circuit, cross,
                     wall=wall)  # fmt: skip
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

    def lamp_link(a: ElectricalPoint, b: ElectricalPoint) -> None:
        """Light to light of one set behind a box: on the ceiling if either end is there."""
        on_ceiling = route == "ceiling" or a.ceiling is not None or b.ceiling is not None
        way: Route = "ceiling" if on_ceiling else "floor"
        line = _Link(group, mark, assumed, a.id, b.id, ctx.anchors[b.id],
                     _rise(a, ctx.ceiling, way), _rise(b, ctx.ceiling, way), way, circuit,
                     ends=_lamp_end(a, out=True) + _lamp_end(b))  # fmt: skip
        links.append(line)

    def chain(part: Sequence[ElectricalPoint]) -> None:
        """Daisy chain: the point nearest to the panel from it, then from point to point."""
        from_board = ctx.from_source("board", route)
        left = sorted(part, key=lambda p: (from_board.cost(ctx.anchors[p.id].node), p.id))
        prev = left.pop(0)
        direct(prev)
        while left:
            at = ctx.anchors[prev.id].node
            p = min(left, key=lambda q: ((ctx.anchors[q.id].node - at).length(), q.id))
            left.remove(p)
            assert prev.height is not None  # only wall points go in a chain
            if _same_frame(prev, p):  # a jumper inside the frame: the cable stays in the wall
                link(prev.id, p.id, ctx.anchors[p.id], 0.0, 0.0, wall=True)
            else:
                to_point(prev.id, prev.height, _rise(prev, ctx.ceiling, route), p)
            prev = p

    if elec.light_wiring == "chain" and not no_boxes:
        chained, done = _light_chains(
            ctx, elec, pts, [], group, mark, assumed, route, _one_feed(elec)
        )
        links += chained
        pts = [p for p in pts if p.id not in done]
        if _one_feed(elec):
            # An appliance output of a lighting line (a fan) is fed from the flush box of the
            # line's nearest switch that has the feed, not by a cable of its own from the panel
            by_id = {p.id: p for p in ctx.points.values()}
            heads = {ln.source for ln in chained} | {"board"}
            taps = [
                by_id[ln.target]
                for ln in chained
                if ln.mark == mark and ln.source in heads and by_id[ln.target].type in SWITCH_TYPES
            ]
            for p in [p for p in pts if p.type is PointType.OUTLET and taps]:
                node = ctx.anchors[p.id].node
                tap = min(
                    taps,
                    key=lambda t: (
                        t.room != p.room,
                        (ctx.anchors[t.id].node - node).length(),
                        t.id,
                    ),
                )
                up, down = _rise(tap, ctx.ceiling, route), _rise(p, ctx.ceiling, route)
                link(tap.id, p.id, ctx.anchors[p.id], up, down, cross=tap.room != p.room)
                pts = [q for q in pts if q is not p]
    sets = _lamp_sets(elec, pts)
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
        # With one cable into the room a box keeps an entry for the feed to the next box
        one_feed = _one_feed(elec)
        cap = BOX_BRANCHES - 1 if one_feed and len(here) > BOX_BRANCHES else BOX_BRANCHES
        zones = split_points([ctx.anchors[p.id].node for p in here], cap)
        made: list[tuple[JunctionBox, list[ElectricalPoint]]] = []
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
            made.append((box, part))
        feeder = _box_feeders(ctx, made) if one_feed else {}
        for box, part in made:
            src = feeder.get(box.id)
            if src is None:
                link("board", box.id, box.anchor, board_rise, box.rise_mm)
            else:  # the group's cable is already in the room: from the box it came to
                link(src.id, box.id, box.anchor, src.rise_mm, box.rise_mm)
            for run in _lamp_runs(ctx, box, part, sets):
                head = run[0]
                to_point(box.id, _box_height(box, ctx.ceiling), box.rise_mm, head)
                if len(run) > 1:  # a light set: the cable goes on from light to light
                    links[-1] = replace(links[-1], ends=END_ALLOWANCE + _lamp_end(head))
                    for a, b in itertools.pairwise(run):
                        lamp_link(a, b)
    own = [b for b in boxes if b.group == group]
    for p in outside:
        near = _nearest_box(ctx, own, ctx.anchors[p.id])
        if near is None:  # group has no box: switch from the panel
            direct(p)
            continue
        to_point(near.id, _box_height(near, ctx.ceiling), near.rise_mm, p, cross=True)
    return links


def _lamp_sets(elec: Electrical, pts: Sequence[ElectricalPoint]) -> dict[str, tuple[object, ...]]:
    """Light set of each light of a group (decision 2026-11-18): lights of one kind turned on by
    the same switches (switch_links) light up together, so behind a box they share one cable.
    LED outputs are not in a set: each has its own supply."""
    ids = {p.id for p in pts}
    by: dict[str, set[str]] = {}
    for lk in switch_links(elec):
        for t in lk.targets:
            if t in ids:
                by.setdefault(t, set()).add(lk.switch)
    return {
        p.id: (p.type.value, tuple(sorted(by.get(p.id, ()))))
        for p in pts
        if p.type in LAMP_TYPES and p.type is not PointType.LED_OUTPUT
    }


def _lamp_runs(
    ctx: _Context,
    box: JunctionBox,
    part: Sequence[ElectricalPoint],
    sets: dict[str, tuple[object, ...]],
) -> list[list[ElectricalPoint]]:
    """Branches of a box (decision 2026-11-18): one per point, except the lights of one set
    (_lamp_sets), which go in a chain: the box feeds the light of the set nearest to it, the
    cable goes on to the nearest light not yet taken. A box joins different sets, switches and
    outputs; it does not split one set into branches."""
    out: list[list[ElectricalPoint]] = []
    grouped: dict[tuple[object, ...], list[ElectricalPoint]] = {}
    for p in part:
        key = sets.get(p.id)
        if key is None:
            out.append([p])
        else:
            grouped.setdefault(key, []).append(p)
    at = box.anchor.node
    for left in grouped.values():
        prev = min(left, key=lambda q: ((ctx.anchors[q.id].node - at).length(), q.id))
        left.remove(prev)
        run = [prev]
        while left:
            node = ctx.anchors[prev.id].node
            prev = min(left, key=lambda q: ((ctx.anchors[q.id].node - node).length(), q.id))
            left.remove(prev)
            run.append(prev)
        out.append(run)
    order = {p.id: k for k, p in enumerate(part)}
    return sorted(out, key=lambda r: order[r[0].id])


def _lamp_end(p: ElectricalPoint, out: bool = False) -> float:
    """Cable at a light of a set chain: a LIGHT_LOOP loop at a ceiling light (the cable comes in
    there; going out it adds nothing more), the usual END_ALLOWANCE at a wall light."""
    if p.ceiling is None:
        return END_ALLOWANCE
    return 0.0 if out else LIGHT_LOOP


def _box_feeders(
    ctx: _Context, made: Sequence[tuple[JunctionBox, Sequence[ElectricalPoint]]]
) -> dict[str, JunctionBox]:
    """Which box feeds each box of a group in a room: the one nearest to the panel is fed from
    the panel (it is not in the result), every next one from the nearest box already fed that
    still has a free entry (BOX_LINES_MAX)."""
    if len(made) < 2:
        return {}
    lines = {b.id: len(part) + 1 for b, part in made}
    left = sorted(
        (b for b, _ in made),
        key=lambda b: (ctx.from_source("board", b.route).cost(b.anchor.node), b.id),
    )
    fed = [left.pop(0)]
    out: dict[str, JunctionBox] = {}
    while left:
        free = [a for a in fed if lines[a.id] < BOX_LINES_MAX] or fed
        a, b = min(
            ((a, b) for a in free for b in left),
            key=lambda ab: ((ab[0].anchor.node - ab[1].anchor.node).length(), ab[0].id, ab[1].id),
        )
        out[b.id] = a
        lines[a.id] += 1
        left.remove(b)
        fed.append(b)
    return out


def _light_chains(
    ctx: _Context,
    elec: Electrical,
    pts: Sequence[ElectricalPoint],
    out: list[_Link],
    group: str,
    mark: str,
    assumed: bool,
    route: Route,
    one_feed: bool = False,
) -> tuple[list[_Link], set[str]]:
    """Light of a group in a chain without boxes (decision 2026-11-11): panel → switch, from it
    its lights one after another, nearest first (switch_links: what it turns on). Pass switches
    that share lights go panel → first → second (PASS_MARK) → lights; a two-key switch feeds
    its lights with TWO_KEY_MARK. Lights no switch takes go in a chain from the panel; a switch
    with no light of the group gets a line of its own. At each ceiling light the cable leaves a
    LIGHT_LOOP loop, the reserve for the light output; the cable is on the ceiling wherever a
    ceiling point is at either end. With one_feed (decision 2026-11-13) only one cable of the
    group comes into a room from the panel, to the switch nearest to the panel; there it branches
    in the flush box: every other line start of the group, in this room or behind a door, is fed
    from the nearest switch already fed, at most BACK_BOX_FEEDS feeds from a flush box, and
    between mechanisms of one frame the cable stays in the wall. Returns the links and the ids
    of the points they took."""
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

    def plane(p: ElectricalPoint) -> Route:
        """Plane of a line from the panel to the point: the ceiling for a ceiling point."""
        return "ceiling" if route == "ceiling" or p.ceiling is not None else "floor"

    def from_board(p: ElectricalPoint) -> float:
        """Cost from the panel to the point on the plane its line would take."""
        return ctx.from_source("board", plane(p)).cost(ctx.anchors[p.id].node)

    def board_link(p: ElectricalPoint, cable: str, cable_assumed: bool) -> None:
        way = plane(p)
        up = ctx.board.height if way == "floor" else max(ceiling - ctx.board.height, 0.0)
        ends = (LIGHT_LOOP if loop(p) else END_ALLOWANCE) + ctx.tail("board")
        down = _rise(p, ceiling, way)
        line = _Link(group, cable, cable_assumed, "board", p.id, ctx.anchors[p.id], up, down, way,
                     "power", False, ends)  # fmt: skip
        out.append(line)

    def point_link(
        a: ElectricalPoint, b: ElectricalPoint, cable: str, cable_assumed: bool, wall: bool = False
    ) -> None:
        on_ceiling = route == "ceiling" or a.ceiling is not None or b.ceiling is not None
        way: Route = "ceiling" if on_ceiling else "floor"
        ends = (0.0 if loop(a) else END_ALLOWANCE) + (LIGHT_LOOP if loop(b) else END_ALLOWANCE)
        # wall: a jumper inside one frame, it does not go up to the ceiling or down to the floor
        up, down = (0.0, 0.0) if wall else (_rise(a, ceiling, way), _rise(b, ceiling, way))
        line = _Link(group, cable, cable_assumed, a.id, b.id, ctx.anchors[b.id],
                     up, down, way, "power", a.room != b.room, ends, wall=wall)  # fmt: skip
        out.append(line)

    starts: list[ElectricalPoint] = []  # with one_feed: where the group's lines begin

    def start(p: ElectricalPoint) -> None:
        if one_feed:
            starts.append(p)
        else:
            board_link(p, mark, assumed)

    def feed(part: Sequence[ElectricalPoint]) -> None:
        """One panel line for the line starts of the group, the rest from switch flush boxes.
        Into another room the feed goes through the opening; a start there that is closer to
        the panel than to any switch already fed gets a panel line of its own."""
        reach: dict[str, Router] = {}

        def near(p: ElectricalPoint) -> tuple[float, str]:
            return from_board(p), p.id

        def gap(a: ElectricalPoint, b: ElectricalPoint) -> float:
            if a.room == b.room:
                return (ctx.anchors[a.id].node - ctx.anchors[b.id].node).length()
            if a.id not in reach:
                end = anchor_end(ctx.anchors[a.id])
                reach[a.id] = ctx.flat_router(end, route)
            return reach[a.id].cost(ctx.anchors[b.id].node)

        root = min([p for p in part if p.type in SWITCH_TYPES] or part, key=near)
        board_link(root, mark, assumed)
        fed, left = [root], [p for p in part if p is not root]
        feeds: dict[str, int] = {}
        while left:
            # Only flush boxes of this lighting line's switches: not sockets, not lights
            boxes = [a for a in fed if a.type in SWITCH_TYPES]
            free = [a for a in boxes if feeds.get(a.id, 0) < BACK_BOX_FEEDS] or boxes
            if not free:
                b = min(left, key=near)
                board_link(b, mark, assumed)
                left.remove(b)
                fed.append(b)
                continue
            a, b = min(
                ((a, b) for a in free for b in left),
                key=lambda ab: (gap(ab[0], ab[1]), ab[0].id, ab[1].id),
            )
            if a.room != b.room and near(b)[0] < gap(a, b):
                board_link(b, mark, assumed)
            else:
                point_link(a, b, mark, assumed, wall=_same_frame(a, b))
                feeds[a.id] = feeds.get(a.id, 0) + 1
            left.remove(b)
            fed.append(b)

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
        g.sort(key=lambda x: (from_board(x), x.id))
        start(g[0])
        for a, b in itertools.pairwise(g):
            point_link(a, b, PASS_MARK, True)
        chain(g[-1], [t for x in g for t in on[x.id]], mark, assumed)
    for s in (s for s in switches if s.type is not PointType.PASS_SWITCH):
        start(s)
        two = s.keys == 2
        chain(s, on[s.id], TWO_KEY_MARK if two else mark, two or assumed)
    free = [p for p in lamps.values() if p.id not in taken]
    if free:
        first = min(free, key=lambda p: (from_board(p), p.id))
        taken.add(first.id)
        start(first)
        chain(first, [p.id for p in free], mark, assumed)
    if starts:
        feed(starts)
    return out, {*lamps, *(s.id for s in switches)}


def _control_link(ctx: _Context, elec: Electrical, p: ElectricalPoint) -> _Link:
    """Control cable of the master switch: straight from the panel along the electrical route."""
    route: Route = "floor" if elec.route == "floor" else "ceiling"
    height = ctx.board.height
    up = height if route == "floor" else max(ctx.ceiling - height, 0.0)
    down = _rise(p, ctx.ceiling, route)
    anchor = ctx.anchors[p.id]
    return _Link(CONTROL_ID, CONTROL_MARK, False, "board", p.id, anchor, up, down, route, "power")


def is_low(p: ElectricalPoint) -> bool:
    """Internet or TV point without a group: its line is low-voltage, not of a panel group."""
    return not p.group and p.type in LOW_TYPES


def low_feeds(elec: Electrical) -> dict[str, Cable]:
    """Low-voltage topology from the project (decision 2026-11-17): low point id → the cable
    without a group that feeds it. Such a cable has only low points in `to` and comes from
    `board`, `media` or a low point. A point fed twice or a ring is skipped here (the check
    reports it: validation.electrical); a point not in any cable is not in the result."""
    low = {p.id for p in elec.points if is_low(p)}
    feeds: dict[str, Cable] = {}
    for c in elec.cables:
        if c.group is not None or not all(t in low for t in c.to):
            continue
        if c.from_ not in ("board", "media") and c.from_ not in low:
            continue
        for t in c.to:
            if t not in feeds and t not in feeds_chain(feeds, c.from_):
                feeds[t] = c
    return feeds


def feeds_chain(feeds: dict[str, Cable], source: str) -> list[str]:
    """The source and what feeds it, up to the panel or the cabinet: a target among them is a
    ring."""
    chain = [source]
    while chain[-1] in feeds and len(chain) <= len(feeds):
        chain.append(feeds[chain[-1]].from_)
    return chain


def _low_link(
    ctx: _Context, elec: Electrical, p: ElectricalPoint, cable: Cable | None = None
) -> _Link:
    """Low-voltage point without a group: a line of its own from the cabinet, else the panel;
    with a cable of the project (low_feeds), from its source and of its type. The route is the
    cable's if set there, else the shared one. A line from a point goes through the flat via the
    openings (cross), as a branch behind a door."""
    if cable is None:
        source = "media" if ctx.media is not None else "board"
        mark, assumed = DEFAULT_MARK["tv" if p.type is PointType.TV else "data"], True
    else:
        source = "board" if cable.from_ == "media" and ctx.media is None else cable.from_
        mark, assumed = cable.cable, False
    own = cable is not None and "route" in cable.model_fields_set
    floor = cable.route == "floor" if cable is not None and own else elec.route == "floor"
    route: Route = "floor" if floor else "ceiling"
    group = group_text("low", ctx.plan.language)
    down = _rise(p, ctx.ceiling, route)
    head = ctx.points.get(source)
    if head is not None:
        up = _rise(head, ctx.ceiling, route)
        return _Link(group, mark, assumed, source, p.id, ctx.anchors[p.id], up, down, route,
                     "low", cross=True)  # fmt: skip
    height = ctx.tail(source)
    up = height if route == "floor" else max(ctx.ceiling - height, 0.0)
    return _Link(group, mark, assumed, source, p.id, ctx.anchors[p.id], up, down, route, "low")


def _led_link(ctx: _Context, elec: Electrical, p: ElectricalPoint) -> _Link:
    """LED output fed from a supply in the panel: a 12 V line of its own from the panel along the
    electrical route, in the group of the output (its breaker feeds the supply). Low voltage, so
    it does not share chases with 230 V cables."""
    assert p.group is not None
    route: Route = "floor" if elec.route == "floor" else "ceiling"
    height = ctx.board.height
    up = height if route == "floor" else max(ctx.ceiling - height, 0.0)
    down = _rise(p, ctx.ceiling, route)
    anchor = ctx.anchors[p.id]
    return _Link(p.group, LED_MARK, True, "board", p.id, anchor, up, down, route, "low", led=True)


def _looped(points: Sequence[ElectricalPoint]) -> list[ElectricalPoint]:
    """Wall sockets of a room that go in a daisy chain; a single one stays where it was."""
    sockets = [p for p in points if p.type in POWER_TYPES and p.ceiling is None]
    return sockets if len(sockets) >= 2 else []


def _box_height(box: JunctionBox, ceiling: float) -> float:
    """Box height from the floor: on a wall for a floor route, rise_mm from the floor; under the
    ceiling, ceiling minus rise_mm; on the ceiling, the ceiling."""
    return box.rise_mm if box.route == "floor" else ceiling - box.rise_mm


def _nearest_box(ctx: _Context, boxes: Sequence[JunctionBox], target: Anchor) -> JunctionBox | None:
    """Group box with the shorter path to the point through the flat (via openings) on the box's
    plane."""
    best: tuple[float, JunctionBox] | None = None
    for b in boxes:
        cost = ctx.flat_router(anchor_end(b.anchor), b.route).cost(target.node)
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
    avoid: BaseGeometry | None = None,
    own: str = "",
) -> Anchor | None:
    """Box spot for the points of a zone: on the ceiling at the centre of the points for a ceiling
    route, on a wall for a floor route; off avoid (other lines, _clear_boxes). own is the box
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


def _comms(circuit: Circuit, led: bool) -> bool:
    """Internet and TV: low voltage, but not a 12 V LED line."""
    return circuit == "low" and not led


def _apart(
    ctx: _Context,
    links: Sequence[_Link],
    boxes: Sequence[JunctionBox],
    runs: Sequence[Run],
    edited: set[str],
) -> list[Run]:
    """Internet and TV lines routed again, apart from the final power routes (decision
    2026-11-13, routing.apart_cells); a line with a manual route stays as it is."""
    power = [r for r in runs if r.circuit == "power"]
    if ctx.any_angle or not power or not any(_comms(r.circuit, r.led) for r in runs):
        return list(runs)
    again = {r.id: r for r in _route_runs(ctx, links, boxes, power)}
    return [r if f"wire:{r.id}" in edited else again.get(r.id, r) for r in runs]


def _lay(ln: _Link) -> Circuit:
    """Circuit the line is laid with (Run.lay): power with the 12 V LED lines, low voltage apart."""
    return "power" if ln.led else ln.circuit


def _route_runs(
    ctx: _Context,
    links: Sequence[_Link],
    boxes: Sequence[JunctionBox],
    beside: Sequence[Run] | None = None,
) -> list[Run]:
    """Line routes: from the panel through the whole flat, from a box or a socket of a daisy chain
    only inside its room. A wall point past an opening is reached where its drop goes down
    beside the opening (_Context.drop); the turn to the point adds to the rise. With beside (the
    power lines already routed) only the internet and TV lines are routed, apart from the power
    routes of their plane (_apart); the line ids are the same.

    Lines are routed one after another in a fixed order (decision 2026-11-23), because a line
    that crosses a wall or an opening band leaves a hole the next lines of its plane and circuit
    go through for free (routing.Router holes, within WALL_HOLE_SHARE): by source, the panel first,
    then the low-voltage cabinet, the boxes in their order, then the points of chains by id; within
    a source the farthest target first by the search cost with the holes made before the source
    began (not by its own lines: the order is fixed when the source starts), equal costs by line
    number. So the line that has to pay a new hole goes first and the nearer ones follow it into
    that hole; a line that already has a ready hole on its way is near, whatever it would have
    paid without it. At equal length a line prefers a hole made by its own source (Router own),
    so the cables of one box or flush box leave it together. The order changes only which line
    pays the pass, not the ids: wire_{k + 1}
    is the k-th link, as before. A router is searched again only when the holes of its plane and
    circuit have changed since its last line; a hole within WALL_HOLE_SHARE of one already made
    is the same hole and changes nothing."""
    todo = [(k, ln) for k, ln in enumerate(links) if beside is None or _comms(ln.circuit, ln.led)]
    beside_paths: dict[Route, list[tuple[Vec, ...]]] = {"ceiling": [], "floor": []}
    for r in beside or ():
        beside_paths[r.route].append(r.path)
    board = ctx.board_end.node  # no APART within PANEL_FREE of it
    routes = {ln.source: ln.route for ln in links}
    drops = {
        (pid, route): spot
        for ln in links
        for pid, route, rise in (
            (ln.source, ln.route, ln.source_rise),
            (ln.target, ln.route, ln.target_rise),
        )
        if rise > 0 and (spot := ctx.drop(pid, route)) is not None
    }

    def source_anchor(src: str) -> Anchor:
        spot = drops.get((src, routes[src]))
        return spot[0] if spot is not None else ctx.anchors[src]

    box_anchors = {b.id: b.anchor for b in boxes}
    box_rooms = {b.id: b.room for b in boxes}
    # Routing order of the sources: the panel, the cabinet, the boxes, the points of chains
    rank = {"board": 0, "media": 1, **{b.id: 2 + k for k, b in enumerate(boxes)}}
    rest = sorted({ln.source for _, ln in todo} - set(rank))
    rank |= {src: len(rank) + k for k, src in enumerate(rest)}
    plain: dict[tuple[str, Route, bool], Router] = {}

    def router_of(src: str, plane: Route, wide: bool) -> Router:
        """Router of the source on the plane without ready holes: the panel and the cabinet
        through the whole flat; a box or a chain point inside its room, or through the whole flat
        via the openings for a branch to a switch behind a door and a light chain into the next
        room (wide); in the apart stage, kept off the power routes of the plane."""
        key = (src, plane, wide)
        if key in plain:
            return plain[key]
        if src in ("board", "media"):
            router = ctx.from_source(src, plane)
        elif wide:
            router = ctx.flat_router(anchor_end(box_anchors.get(src) or source_anchor(src)), plane)
        elif src in box_anchors:
            router = Router(room_area(ctx.geoms[box_rooms[src]]), anchor_end(box_anchors[src]),
                            ctx.any_angle)  # fmt: skip
        else:  # a daisy chain
            area = room_area(ctx.geoms[ctx.rooms[src]])
            router = Router(area, anchor_end(source_anchor(src)), ctx.any_angle)
        if beside is not None:
            router = router.apart_from(beside_paths[plane], board)
        plain[key] = router
        return router

    def target_of(ln: _Link) -> tuple[End, tuple[Anchor, float] | None]:
        end = drops.get((ln.target, ln.route)) if ln.target_rise > 0 else None
        return anchor_end(end[0] if end else ln.target_anchor), end

    holes: dict[tuple[Route, Circuit], list[tuple[Crossing, str]]] = {}  # with the source
    opened: dict[tuple[str, Route, bool, Circuit, int], Router] = {}

    def current(ln: _Link) -> Router:
        """The line's router with the holes made so far on its plane and circuit; searched again
        only when they changed since the last line of this source."""
        wide = ln.source not in ("board", "media") and ln.cross
        made = holes.setdefault((ln.route, _lay(ln)), [])
        key = (ln.source, ln.route, wide, _lay(ln), len(made))
        router = opened.get(key)
        if router is None:
            own = [c for c, src in made if src == ln.source]
            router = router_of(ln.source, ln.route, wide).with_holes([c for c, _ in made], own)
            opened[key] = router
        return router

    def order(item: tuple[int, _Link]) -> tuple[float, int]:
        k, ln = item
        return 0.0 if ln.wall else -current(ln).cost(target_of(ln)[0].node), k

    by_source: dict[str, list[tuple[int, _Link]]] = {}
    for k, ln in todo:
        by_source.setdefault(ln.source, []).append((k, ln))
    found: dict[int, tuple[Run, tuple[Router, End] | None]] = {}
    # Sorted when the source's turn comes: by the holes the sources before it made
    queue = (
        (k, ln)
        for src in sorted(by_source, key=rank.__getitem__)
        for k, ln in sorted(by_source[src], key=order)
    )
    for k, ln in queue:
        router = current(ln)
        target, end = target_of(ln)
        start = drops.get((ln.source, ln.route)) if ln.source_rise > 0 else None
        path: tuple[Vec, ...]
        if ln.wall:  # one frame: the cable does not leave the wall, no lane on the route grid
            path = (ctx.anchors[ln.source].node, ln.target_anchor.node)
        else:
            with trace.scope(
                line=f"wire_{k + 1}",
                group=ln.group,
                source=ln.source,
                target=ln.target,
                plane=ln.route,
                stage="main" if beside is None else "apart",
            ):
                path = tuple(router.route(target))
            made = holes[(ln.route, _lay(ln))]
            for a, b in crossings(path, router.bands):
                mid = (a + b) * 0.5
                if all(((c + d) * 0.5 - mid).length() >= WALL_HOLE_SHARE for (c, d), _ in made):
                    made.append(((a, b), ln.source))
        run = Run(
            id=f"wire_{k + 1}",
            group=ln.group,
            mark=ln.mark,
            mark_assumed=ln.mark_assumed,
            source=ln.source,
            target=ln.target,
            path=path,
            plan_mm=length(path),
            rise_start_mm=ln.source_rise + _turn(ctx, ln.source, start),
            rise_end_mm=ln.target_rise + _turn(ctx, ln.target, end),
            ends_mm=END_ALLOWANCE + ctx.tail(ln.source) if ln.ends is None else ln.ends,
            route=ln.route,
            circuit=ln.circuit,
            end_drop=end[1] if end else None,
            start_drop=start[1] if start else None,
            led=ln.led,
        )
        found[k] = (run, None if ln.wall else (router, target))
    runs = [found[k][0] for k, _ in todo]
    ways = [found[k][1] for k, _ in todo]  # each run's router and target, for _one_side
    return _one_side(boxes, runs, ways) if beside is None else runs


def _one_side(
    boxes: Sequence[JunctionBox],
    runs: Sequence[Run],
    ways: Sequence[tuple[Router, End] | None],
) -> list[Run]:
    """A box on the ceiling (floor) with 2 to ONE_SIDE_MAX cables takes them all from one side
    (decision 2026-11-18): the cables run together, straight, BOX_LEAD_MM out of that side and
    part only there, so they lie evenly. The side is the one with the shortest cables in all,
    with its lead inside the room and no cable turning back over the box (_via_lead). A cable
    between two such boxes goes through both leads. A wall box needs none of it: its cables all
    come down from the top. Boxes with more cables keep their routes. ways are each run's
    router and target end."""
    out = list(runs)
    nodes = {b.id: b.anchor.node for b in boxes}
    leads: dict[str, Vec] = {}  # boxes given a side: the lead in front of it
    for b in boxes:
        mine = [k for k, r in enumerate(out) if b.id in (r.source, r.target)]
        if not b.on_ceiling or not 2 <= len(mine) <= ONE_SIDE_MAX:
            continue
        if any(ways[k] is None for k in mine):
            continue
        best: tuple[float, Vec, dict[int, _Via]] | None = None
        for side in SIDES:
            here = {**leads, b.id: b.anchor.node + side * BOX_LEAD_MM}
            vias: dict[int, _Via] = {}
            for k in mine:
                way = ways[k]
                assert way is not None
                r = out[k]
                start = (nodes[r.source], here[r.source]) if r.source in here else None
                end = (here[r.target], nodes[r.target]) if r.target in here else None
                via = _via_lead(start, end, *way)
                if via is None:
                    break
                vias[k] = via
            if len(vias) < len(mine):
                continue
            total = sum(length(v.path()) for v in vias.values())
            if best is None or total < best[0] - 1e-6:
                best = (total, here[b.id], vias)
        if best is not None:
            leads[b.id] = best[1]
            for k, via in best[2].items():
                with trace.scope(line=out[k].id, group=out[k].group, stage="one_side"):
                    path = via.path()
                out[k] = replace(out[k], path=path, plan_mm=length(path))
    return out


@dataclass(frozen=True)
class _Via:
    """A route through box leads (_via_lead): the router, where it goes and the straight
    pieces from and into the boxes."""

    router: Router
    to: End
    before: tuple[Vec, ...]
    after: tuple[Vec, ...]

    def path(self) -> tuple[Vec, ...]:
        return tuple(self.router.route(self.to, self.before, self.after))


def _via_lead(
    start: tuple[Vec, Vec] | None,
    end: tuple[Vec, Vec] | None,
    router: Router,
    target: End,
) -> _Via | None:
    """A cable through the leads of its boxes (_one_side): start is (box, lead) when it leaves a
    box from a side, end is (lead, box) when it comes into one; otherwise the run's own router
    and target. A route that turns back over a box is tried again kept off the stubs (as low
    voltage off power); None if it still does, or if a lead is outside the router's area."""
    stubs = [s for s in (start, end) if s is not None]
    if not all(router.area.contains(Point(v.as_tuple())) for s in stubs for v in s):
        return None
    to = End(end[0], False) if end is not None else target
    boxes = ([Point(start[0].as_tuple())] if start else []) + (
        [Point(end[1].as_tuple())] if end else []
    )
    for beside in ((), tuple(stubs)):
        begin = End(start[1], False) if start is not None else router.source
        used = router.rebased(begin, beside)
        rest = used.route(to)
        line = (
            LineString([v.as_tuple() for v in rest]) if len(rest) > 1 else Point(rest[0].as_tuple())
        )
        if all(line.distance(p) >= BOX_LEAD_MM / 2 for p in boxes):
            return _Via(used, to, start[:1] if start else (), end[1:] if end else ())
    return None


def _led_sections(runs: Sequence[Run], elec: Electrical) -> list[Run]:
    """12 V LED lines get their cross-section by length and strip current (led_supply), after
    the manual routes: the final length counts."""
    loads = {ld.point: ld for ld in led_loads(elec)}
    out = []
    for r in runs:
        ld = loads.get(r.target) if r.led else None
        if ld is not None:
            r = replace(r, mark=led_mark(section_for(r.length_mm, ld.current)))
        out.append(r)
    return out


def _turn(ctx: _Context, pid: str, spot: tuple[Anchor, float] | None) -> float:
    """Along the wall from a drop beside an opening to the point, mm; 0 without one."""
    p = ctx.points.get(pid)
    if spot is None or p is None or p.offset is None:
        return 0.0
    return abs(spot[1] - p.offset)
