"""Lines of one panel group: through junction boxes, in a daisy chain or straight from the panel.

Variant rules:
- one cable of a group comes into a room (decision 2026-11-13, wiring_context.one_feed): the
  group's box nearest to the panel is fed from the panel, its other boxes in the room from the
  nearest box already fed (_box_feeders); with light in a chain, the switch nearest to the panel
  is fed from the panel and the cable branches in its flush box to the group's other switches
  (light_chains.py). Where every panel line has its own breaker (premium panel, proper layout:
  lines.per_line) each box and each switch keeps a panel line of its own, as before;
- otherwise cable runs only from the panel to a box, from the panel to a load or from a box to a
  load; never from a load to a box. With the loop distribution wall sockets are
  the exception: in a room, two or more sockets of a group go in a daisy chain through their
  flush boxes, nearest to the panel first, with no junction box and at most BOX_BRANCHES on a
  chain, each chain on its own panel line (_Group.chain). Light, switches and direct lines stay
  as they are;
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
- an appliance output of a lighting line in a chain (a fan) is fed from the flush box of the
  line's nearest switch that has the feed, not by a cable of its own from the panel
  (_Group.light_in_chain);
- behind a box, lights of one set (decision 2026-11-18, _lamp_sets: one kind, the same
  switches) share one cable: the box feeds the nearest of them, the cable goes on from light to
  light with a LIGHT_LOOP at each ceiling light; a box joins different sets, switches and
  outputs, it does not split one set into branches (_lamp_runs);
- no cable crosses the room volume (decision 2026-11-01): cable to a ceiling point runs on
  the ceiling; with a floor route a lighting group (only ceiling lights and switches) goes
  entirely on the ceiling, and in a mixed group the branch to a light rises up the wall from
  the box or panel to the ceiling and runs along the ceiling (_Group.to_point).
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from floorplan_engine.electrical.anchors import Anchor
from floorplan_engine.electrical.box_spots import box_spot
from floorplan_engine.electrical.boxes import BOX_BRANCHES, anchor_end, box_size, split_points
from floorplan_engine.electrical.light_chains import light_chains
from floorplan_engine.electrical.loads import LOW_TYPES, POWER_TYPES, assumed_mark
from floorplan_engine.electrical.switch_links import switch_links
from floorplan_engine.electrical.wiring_context import (
    END_ALLOWANCE,
    LAMP_TYPES,
    LIGHT_LOOP,
    LIGHT_TYPES,
    SWITCH_TYPES,
    Context,
    Link,
    between_plane,
    one_feed,
    rise,
    same_frame,
)
from floorplan_engine.electrical.wiring_model import Circuit, JunctionBox, Route
from floorplan_engine.model.schema import Cable, Electrical, ElectricalPoint, PointType, Room

HEAVY_SECTION = 4.0  # mm²: from this cross-section a line goes from the panel without boxes
# A group made only of these goes from the panel to each point without boxes: appliance outputs
# and floor heating controllers
DIRECT_TYPES = frozenset({PointType.OUTLET, PointType.THERMOSTAT})
BOX_LINES_MAX = BOX_BRANCHES + 1  # lines in a 150×110 box: no more feeds from a full one

LampSet = tuple[object, ...]


def section(mark: str) -> float:
    """Conductor cross-section from a type: "3x6" → 6, "5х2,5" → 2.5; 0 if unreadable."""
    m = re.search(r"[xх×]\s*(\d+(?:[.,]\d+)?)", mark)
    return float(m.group(1).replace(",", ".")) if m else 0.0


def _cable(elec: Electrical, group: str) -> Cable | None:
    return next((c for c in elec.cables if c.group == group), None)


def _mark(
    elec: Electrical, group: str, cable: Cable | None, points: Sequence[ElectricalPoint]
) -> tuple[str, bool]:
    if cable is not None:
        return cable.cable, False
    return assumed_mark(elec, group, points), True


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


def _looped(points: Sequence[ElectricalPoint]) -> list[ElectricalPoint]:
    """Wall sockets of a room that go in a daisy chain; a single one stays where it was."""
    sockets = [p for p in points if p.type in POWER_TYPES and p.ceiling is None]
    return sockets if len(sockets) >= 2 else []


def _box_height(box: JunctionBox, ceiling: float) -> float:
    """Box height from the floor: on a wall for a floor route, rise_mm from the floor; under the
    ceiling, ceiling minus rise_mm; on the ceiling, the ceiling."""
    return box.rise_mm if box.route == "floor" else ceiling - box.rise_mm


def _nearest_box(ctx: Context, boxes: Sequence[JunctionBox], target: Anchor) -> JunctionBox | None:
    """Group box with the shorter path to the point through the flat (via openings) on the box's
    plane."""
    best: tuple[float, JunctionBox] | None = None
    for b in boxes:
        cost = ctx.flat_router(anchor_end(b.anchor), b.route).cost(target.node)
        if best is None or cost < best[0]:
            best = (cost, b)
    return None if best is None else best[1]


def _lamp_end(p: ElectricalPoint, out: bool = False) -> float:
    """Cable at a light of a set chain: a LIGHT_LOOP loop at a ceiling light (the cable comes in
    there; going out it adds nothing more), the usual END_ALLOWANCE at a wall light."""
    if p.ceiling is None:
        return END_ALLOWANCE
    return 0.0 if out else LIGHT_LOOP


def _lamp_sets(elec: Electrical, pts: Sequence[ElectricalPoint]) -> dict[str, LampSet]:
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
    ctx: Context,
    box: JunctionBox,
    part: Sequence[ElectricalPoint],
    sets: dict[str, LampSet],
) -> list[list[ElectricalPoint]]:
    """Branches of a box (decision 2026-11-18): one per point, except the lights of one set
    (_lamp_sets), which go in a chain: the box feeds the light of the set nearest to it, the
    cable goes on to the nearest light not yet taken. A box joins different sets, switches and
    outputs; it does not split one set into branches."""
    out: list[list[ElectricalPoint]] = []
    grouped: dict[LampSet, list[ElectricalPoint]] = {}
    for p in part:
        key = sets.get(p.id)
        if key is None:
            out.append([p])
        else:
            grouped.setdefault(key, []).append(p)
    for left in grouped.values():
        out.append(ctx.nearest_chain(box.anchor.node, left))
    order = {p.id: k for k, p in enumerate(part)}
    return sorted(out, key=lambda r: order[r[0].id])


def _box_feeders(
    ctx: Context, made: Sequence[tuple[JunctionBox, Sequence[ElectricalPoint]]]
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


def group_links(
    ctx: Context,
    elec: Electrical,
    group: str,
    pts: Sequence[ElectricalPoint],
    boxes: list[JunctionBox],
) -> list[Link]:
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
    g = _Group(ctx, elec, group, mark, assumed, route, circuit, no_boxes)
    if elec.light_wiring == "chain" and not no_boxes:
        pts = g.light_in_chain(pts)
    sets = _lamp_sets(elec, pts)
    # A switch is tapped into the box of its light: in a room where the group has only
    # switches (by the door outside) they get no box or panel line of their own
    lit = {p.room for p in pts if p.type not in SWITCH_TYPES}
    outside = [] if no_boxes else [p for p in pts if p.type in SWITCH_TYPES and p.room not in lit]
    for room in ctx.plan.rooms:
        here = [p for p in pts if p.room == room.id and p not in outside]
        g.room_links(room, here, boxes, sets)
    own = [b for b in boxes if b.group == group]
    for p in outside:
        near = _nearest_box(ctx, own, ctx.anchors[p.id])
        if near is None:  # group has no box: switch from the panel
            g.direct(p)
            continue
        g.to_point(near.id, _box_height(near, ctx.ceiling), near.rise_mm, p, cross=True)
    return g.links


@dataclass
class _Group:
    """The links of one group as they are built: what every link of the group shares and the
    ways to add one (from the panel, to a point, light to light, a daisy chain)."""

    ctx: Context
    elec: Electrical
    group: str
    mark: str
    assumed: bool
    route: Route
    circuit: Circuit
    no_boxes: bool
    links: list[Link] = field(default_factory=list)

    def link(
        self,
        src: str,
        dst: str,
        b: Anchor,
        up: float,
        down: float,
        cross: bool = False,
        way: Route | None = None,
        wall: bool = False,
    ) -> None:
        line = Link(self.group, self.mark, self.assumed, src, dst, b, up, down, way or self.route,
                    self.circuit, cross, wall=wall)  # fmt: skip
        self.links.append(line)

    def to_point(
        self, src: str, from_height: float, up: float, p: ElectricalPoint, cross: bool = False
    ) -> None:
        """Branch to a point; to a ceiling point with a floor route, up the wall and along the
        ceiling (from_height is the connection height at the source, from the floor)."""
        ctx = self.ctx
        if self.route == "floor" and p.ceiling is not None:
            up = max(ctx.ceiling - from_height, 0.0)
            self.link(src, p.id, ctx.anchors[p.id], up, 0.0, cross, way="ceiling")
            return
        self.link(src, p.id, ctx.anchors[p.id], up, rise(p, ctx.ceiling, self.route), cross)

    def direct(self, p: ElectricalPoint) -> None:
        """A line of its own from the panel."""
        self.to_point("board", self.ctx.board.height, self.ctx.source_rise(self.route), p)

    def lamp_link(self, a: ElectricalPoint, b: ElectricalPoint) -> None:
        """Light to light of one set behind a box: on the ceiling if either end is there."""
        ctx = self.ctx
        way = between_plane(self.route, a, b)
        line = Link(self.group, self.mark, self.assumed, a.id, b.id, ctx.anchors[b.id],
                    rise(a, ctx.ceiling, way), rise(b, ctx.ceiling, way), way, self.circuit,
                    ends=_lamp_end(a, out=True) + _lamp_end(b))  # fmt: skip
        self.links.append(line)

    def chain(self, part: Sequence[ElectricalPoint]) -> None:
        """Daisy chain: the point nearest to the panel from it, then from point to point."""
        ctx = self.ctx
        from_board = ctx.from_source("board", self.route)
        left = sorted(part, key=lambda p: (from_board.cost(ctx.anchors[p.id].node), p.id))
        prev = left.pop(0)
        self.direct(prev)
        for p in ctx.nearest_chain(ctx.anchors[prev.id].node, left):
            assert prev.height is not None  # only wall points go in a chain
            if same_frame(prev, p):  # a jumper inside the frame: the cable stays in the wall
                self.link(prev.id, p.id, ctx.anchors[p.id], 0.0, 0.0, wall=True)
            else:
                self.to_point(prev.id, prev.height, rise(prev, ctx.ceiling, self.route), p)
            prev = p

    def light_in_chain(self, pts: Sequence[ElectricalPoint]) -> list[ElectricalPoint]:
        """Light in a chain without boxes (light_chains.py); with one feed into the room, an
        appliance output of the lighting line (a fan) is fed from the flush box of the line's
        nearest switch that has the feed, not by a cable of its own from the panel. Returns the
        points still to wire."""
        ctx, elec = self.ctx, self.elec
        chained, done = light_chains(
            ctx, elec, pts, self.group, self.mark, self.assumed, self.route, one_feed(elec)
        )
        self.links += chained
        pts = [p for p in pts if p.id not in done]
        if not one_feed(elec):
            return pts
        by_id = {p.id: p for p in ctx.points.values()}
        heads = {ln.source for ln in chained} | {"board"}
        taps = [
            by_id[ln.target]
            for ln in chained
            if ln.mark == self.mark and ln.source in heads and by_id[ln.target].type in SWITCH_TYPES
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
            up, down = rise(tap, ctx.ceiling, self.route), rise(p, ctx.ceiling, self.route)
            self.link(tap.id, p.id, ctx.anchors[p.id], up, down, cross=tap.room != p.room)
            pts = [q for q in pts if q is not p]
        return pts

    def room_links(
        self,
        room: Room,
        here: list[ElectricalPoint],
        boxes: list[JunctionBox],
        sets: dict[str, LampSet],
    ) -> None:
        """The group's lines in one room: sockets in a daisy chain (loop distribution), each
        point from the panel, or boxes by zone with the feed and the branches of each."""
        ctx, elec = self.ctx, self.elec
        looped = _looped(here) if elec.distribution == "loop" and not self.no_boxes else []
        if looped:
            nodes = [ctx.anchors[p.id].node for p in looped]
            for zone in split_points(nodes, BOX_BRANCHES):
                self.chain([looped[i] for i in zone])
            here = [p for p in here if p not in looped]
        if not here:
            return
        has_light = any(p.type in LIGHT_TYPES for p in here)
        if self.no_boxes or not (len(here) >= 2 or has_light):
            for p in here:
                self.direct(p)
            return
        made = self.room_boxes(room, here, boxes)
        feeder = _box_feeders(ctx, made) if one_feed(elec) else {}
        for box, part in made:
            src = feeder.get(box.id)
            if src is None:
                self.link("board", box.id, box.anchor, ctx.source_rise(self.route), box.rise_mm)
            else:  # the group's cable is already in the room: from the box it came to
                self.link(src.id, box.id, box.anchor, src.rise_mm, box.rise_mm)
            for run in _lamp_runs(ctx, box, part, sets):
                head = run[0]
                self.to_point(box.id, _box_height(box, ctx.ceiling), box.rise_mm, head)
                if len(run) > 1:  # a light set: the cable goes on from light to light
                    self.links[-1] = replace(self.links[-1], ends=END_ALLOWANCE + _lamp_end(head))
                    for a, b in itertools.pairwise(run):
                        self.lamp_link(a, b)

    def room_boxes(
        self, room: Room, here: Sequence[ElectricalPoint], boxes: list[JunctionBox]
    ) -> list[tuple[JunctionBox, list[ElectricalPoint]]]:
        """Boxes of the group in the room by zone, appended to boxes, each with its points; a
        zone with no spot for a box gets its points from the panel."""
        ctx = self.ctx
        # At most BOX_BRANCHES branches per box: more points means boxes by zone
        # With one cable into the room a box keeps an entry for the feed to the next box
        cap = BOX_BRANCHES - 1 if one_feed(self.elec) and len(here) > BOX_BRANCHES else BOX_BRANCHES
        zones = split_points([ctx.anchors[p.id].node for p in here], cap)
        made: list[tuple[JunctionBox, list[ElectricalPoint]]] = []
        for zone in zones:
            part = [here[i] for i in zone]
            spot = box_spot(ctx, room.id, part, boxes, self.route)
            if spot is None:  # no wall space for a box: each point from the panel
                for p in part:
                    self.direct(p)
                continue
            n = len(boxes) + 1
            size = box_size(len(part) + 1)
            box = JunctionBox(
                f"box_{n}", f"К{n}", room.id, self.group, spot, self.route, room.wet, size
            )
            boxes.append(box)
            made.append((box, part))
        return made
