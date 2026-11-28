"""Wiring through junction boxes: topology, routes and cable lengths, all from the model.

The build (box_wiring) goes in stages, each in its module:
- the context of the build, shared by every line: plan, connection points, panel and the
  routers from it (wiring_context.py, Context; a line before routing is a Link);
- the lines of each panel group: through boxes, in a daisy chain or straight from the panel
  (wiring_links.py), light in a chain without boxes (light_chains.py), where a box stands
  (box_spots.py);
- lines outside the groups' boxes: the master switch control cable (_control_link), internet and
  TV without a group, the 12 V lines of LED supplies in the panel (low_links.py);
- the routes: every line searched in a fixed order, with the ready holes, the box leads, the
  internet and TV lines apart from power, the manual routes from wiring.yaml (wiring_routes.py);
  then the boxes are kept off the lines that pass by and the lines routed again
  (box_spots.clear_boxes);
- chases, wall passes and the Wiring for the sheets, the estimate and the viewer (chases.py,
  frames.py, wiring_model.py).

Line length = plan path + vertical from the connection point to the ceiling (or floor) at
both ends + tails: at the panel the cable runs down to the floor (BOARD_TAIL is the panel
height), at other connections END_ALLOWANCE. The total per cable type includes RESERVE.
Points without a group are not counted, except low-voltage (low_links.py).

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
opening, so the wall above it is drilled; one pass place per entry into a room, power and
low-voltage apart. A floor route passes
under the opening with no drilling. A route goes straight through a drillable wall
(routing.drillable_walls: not load-bearing, not outer, no thicker than WALL_DRILL_MAX; decision
2026-11-11), at the ceiling or at the floor, when that is shorter; such holes are counted the
same way. The search prices the passes as the estimate counts them (decision 2026-11-23,
routing.py): on the ceiling an opening lower than the ceiling costs the same pass as a wall, on
the floor an opening is free, and a hole already made by a line of the build is free for the
next lines of its plane and circuit within WALL_HOLE_SHARE, so lines of one source into a room
go through one hole (wiring_routes.route_runs: lines are routed one after another, in a fixed
order). A pass place has cable passes side by side, one PVC sleeve each by its cables, sealed
with firestop foam (sleeves.py, decision 2026-11-28: no large core-drilled hole).

Socket loop with one chase for both cables (loop_conduit shared, after plaster; decision
2026-11-25): both come down into the first flush box of a block and the outgoing cable is pulled
through the block to the last one, so its line is longer by POST_PITCH_MM per post past the
first (through_block). Two chases or before plaster the cables come in and leave at the edges
of the block: nothing to add.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import replace

import shapely

from floorplan_engine.electrical import trace
from floorplan_engine.electrical.anchors import board_anchor, point_anchor
from floorplan_engine.electrical.box_spots import clear_boxes, moved_boxes, sized
from floorplan_engine.electrical.boxes import anchor_end
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
from floorplan_engine.electrical.floor_heating import heating_zones
from floorplan_engine.electrical.frames import POST_PITCH_MM, entries
from floorplan_engine.electrical.groups import group_key
from floorplan_engine.electrical.led_supply import led_loads, length_weight
from floorplan_engine.electrical.loads import LOW_TYPES
from floorplan_engine.electrical.low_links import led_link, led_sections, low_feeds, low_link
from floorplan_engine.electrical.master import CONTROL_ID, CONTROL_MARK, master_point
from floorplan_engine.electrical.routing import ceiling_passes, drillable_walls, free_area
from floorplan_engine.electrical.sleeves import with_sleeves
from floorplan_engine.electrical.wiring_context import Context, Link, rise
from floorplan_engine.electrical.wiring_links import group_links
from floorplan_engine.electrical.wiring_model import JunctionBox, Route, Run, Wiring
from floorplan_engine.electrical.wiring_routes import apart, manual_runs, route_runs
from floorplan_engine.model.geometry import Contour, room_geometries
from floorplan_engine.model.scale import DEFAULT_SCALE, drawing_scale
from floorplan_engine.model.schema import Electrical, ElectricalPoint, Plan, PointType, WiringEdits

RESERVE = 0.15  # margin on the total per cable type

Notes = list[tuple[str, str]]  # where (an edit path or a box id) and what, for the report


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
    ctx = _context(plan, contours, elec)
    boxes, links = _topology(ctx, elec, grouped, led, low, master)
    edited: set[str] = set()
    notes: Notes = []
    if edits is not None:
        boxes, links = moved_boxes(ctx, boxes, links, edits, edited, notes)
    boxes, runs, box_notes, wire_notes = _routed(ctx, boxes, links, edits, edited)
    notes += wire_notes
    if led:
        runs = led_sections(runs, elec)
    skipped = tuple(p.id for p in elec.points if not p.group and p is not master and p not in low)
    return _wiring(ctx, contours, elec, boxes, runs, skipped, edited, notes, box_notes)


def _context(plan: Plan, contours: dict[str, Contour], elec: Electrical) -> Context:
    """The context of the build: room geometry, where every point and the panel connect, the
    drillable walls and the openings lower than the ceiling."""
    assert elec.board is not None
    geoms = {g.room.id: g for g in room_geometries(plan, contours)}
    rooms = list(geoms.values())
    return Context(
        plan,
        geoms,
        # At the wall, not at the stacked symbol: the cable ends where the point really is
        {p.id: point_anchor(p, geoms) for p in elec.points},
        elec.board,
        anchor_end(board_anchor(elec.board, geoms)),
        free_area(rooms),
        # On ceiling and floor along the shortest path, economy by default (docs/wiring-variants.md)
        elec.shortest_path,
        {p.id: p.room for p in elec.points},
        elec.media,
        None if elec.media is None else anchor_end(board_anchor(elec.media, geoms)),
        drillable_walls(rooms),
        ceiling_passes(rooms, plan.ceiling_height),
        {p.id: p for p in elec.points},
    )


def _topology(
    ctx: Context,
    elec: Electrical,
    grouped: Sequence[ElectricalPoint],
    led: Sequence[ElectricalPoint],
    low: Sequence[ElectricalPoint],
    master: ElectricalPoint | None,
) -> tuple[list[JunctionBox], list[Link]]:
    """All lines before routing, with the boxes they go through: the groups in their order, the
    master switch control cable, low-voltage points without a group, 12 V LED lines (a metre of
    such a line weighs more in the search, by the strip current: led_supply.length_weight); the
    boxes sized by their final number of lines."""
    boxes: list[JunctionBox] = []
    links: list[Link] = []
    for group in sorted({p.group for p in grouped if p.group}, key=group_key):
        pts = [p for p in grouped if p.group == group]
        links += group_links(ctx, elec, group, pts, boxes)
    if master is not None:
        links.append(_control_link(ctx, elec, master))
    feeds = low_feeds(elec)
    links += [low_link(ctx, elec, p, feeds.get(p.id)) for p in low]
    weights = {ld.point: length_weight(ld.current) for ld in led_loads(elec)} if led else {}
    links += [led_link(ctx, elec, p, weights[p.id]) for p in led]
    return sized(boxes, links), links


def _control_link(ctx: Context, elec: Electrical, p: ElectricalPoint) -> Link:
    """Control cable of the master switch: straight from the panel along the electrical route."""
    route: Route = "floor" if elec.route == "floor" else "ceiling"
    up = ctx.source_rise(route)
    down = rise(p, ctx.ceiling, route)
    anchor = ctx.anchors[p.id]
    return Link(CONTROL_ID, CONTROL_MARK, False, "board", p.id, anchor, up, down, route, "power")


def _routed(
    ctx: Context,
    boxes: Sequence[JunctionBox],
    links: Sequence[Link],
    edits: WiringEdits | None,
    edited: set[str],
) -> tuple[list[JunctionBox], list[Run], Notes, Notes]:
    """The lines routed, in rounds: auto, the manual routes from wiring.yaml, then internet and
    TV apart from power; a box on lines that pass by moves and the round is repeated
    (box_spots.clear_boxes). Returns the boxes, the runs, the box notes and the manual-route
    notes of the last round."""
    passable = shapely.unary_union([ctx.free, *ctx.walls]) if ctx.walls else ctx.free
    wire_notes: Notes = []
    rounds = itertools.count()

    def route(boxes: Sequence[JunctionBox], links: Sequence[Link]) -> list[Run]:
        with trace.scope(round=next(rounds)):
            runs = route_runs(ctx, links, boxes)
            wire_notes.clear()
            if edits is not None:
                runs = manual_runs(runs, edits.wires, passable, edited, wire_notes, ctx.any_angle)
            return apart(ctx, links, boxes, runs, edited)

    runs = route(boxes, links)
    boxes, _, runs, box_notes = clear_boxes(ctx, boxes, links, runs, route, edited)
    return list(boxes), runs, box_notes, wire_notes


def _wiring(
    ctx: Context,
    contours: dict[str, Contour],
    elec: Electrical,
    boxes: Sequence[JunctionBox],
    runs: Sequence[Run],
    skipped: tuple[str, ...],
    edited: set[str],
    notes: Notes,
    box_notes: Notes,
) -> Wiring:
    """The result for the sheets, the estimate and the viewer: the chases with their conduit and
    wall material, the wall passes, the frame entries, the floor heating zones."""
    plan = ctx.plan
    height_assumed = "ceiling_height" not in plan.model_fields_set
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
    rooms = list(ctx.geoms.values())
    holes = with_sleeves(wall_holes(runs, passages(rooms, ctx.ceiling), ctx.walls, rooms), runs)
    shared = shared_rises(runs, elec.points, elec.conduit_level, elec.loop_conduit)
    return Wiring(
        ctx.ceiling,
        height_assumed,
        tuple(boxes),
        tuple(through_block(runs, elec, shared)),
        skipped,
        chases,
        holes,
        ctx.free,
        frozenset(edited),
        tuple(notes),
        elec.plaster == "before",
        drops,
        shared,
        heating_zones(plan, contours, elec),
        box_notes=tuple(box_notes),
        entries=tuple(sorted(entry.items())),
    )


def through_block(runs: Sequence[Run], elec: Electrical, shared: frozenset[str]) -> list[Run]:
    """A loop line out of a block of sockets that shares the chase with the cable in (shared,
    after plaster; decision 2026-11-25): pulled through the block from its first flush box to
    its last, POST_PITCH_MM per post past the first, added to its ends."""
    if elec.plaster != "after" or not shared:
        return list(runs)
    posts = {p.id: p.count for p in elec.points if p.type is PointType.SOCKET}
    return [
        replace(r, ends_mm=r.ends_mm + POST_PITCH_MM * (posts[r.source] - 1))
        if r.id in shared and posts.get(r.source, 1) > 1
        else r
        for r in runs
    ]
