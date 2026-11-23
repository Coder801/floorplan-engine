"""Light in a chain without boxes (Electrical.light_wiring "chain", decision 2026-11-11).

Panel → switch → its lights one after another; pass switches panel → first → second (PASS_MARK)
→ lights; a two-key switch feeds its lights with TWO_KEY_MARK; a LIGHT_LOOP loop at each
ceiling light for its future output. Lights no switch takes go in a chain from the panel; a
switch with no light of the group gets a line of its own. The cable is on the ceiling wherever
a ceiling point is at either end.

With one cable of a group into a room (wiring_context.one_feed, decision 2026-11-13) the
switch nearest to the panel is fed from the panel and the cable branches in its flush box to
the group's other switches, in the room and behind a door: every other line start of the group
is fed from the nearest switch already fed, at most BACK_BOX_FEEDS feeds from a flush box, and
between mechanisms of one frame the cable stays in the wall. A start in another room that is
closer to the panel than to any switch already fed gets a panel line of its own.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field

from floorplan_engine.electrical.boxes import anchor_end
from floorplan_engine.electrical.routing import Router
from floorplan_engine.electrical.switch_links import switch_links
from floorplan_engine.electrical.wiring_context import (
    END_ALLOWANCE,
    LAMP_TYPES,
    LIGHT_LOOP,
    SWITCH_TYPES,
    Context,
    Link,
    between_plane,
    rise,
    same_frame,
)
from floorplan_engine.electrical.wiring_model import Route
from floorplan_engine.model.schema import Electrical, ElectricalPoint, PointType

PASS_MARK = "4x1.5"  # between pass switches without a box: two travellers, N, PE (assumption)
TWO_KEY_MARK = "4x1.5"  # from a two-key switch to its lights: two switched lines (assumption)
# One cable of a group into a room (decision 2026-11-13): it branches in a switch flush box
BACK_BOX_FEEDS = 3  # feeds to the next switches from one flush box (assumption: a deep box)


def light_chains(
    ctx: Context,
    elec: Electrical,
    pts: Sequence[ElectricalPoint],
    group: str,
    mark: str,
    assumed: bool,
    route: Route,
    one_feed: bool,
) -> tuple[list[Link], set[str]]:
    """Light of a group in a chain without boxes: panel → switch, from it its lights one after
    another, nearest first (switch_links: what it turns on). Pass switches that share lights go
    panel → first → second (PASS_MARK) → lights; a two-key switch feeds its lights with
    TWO_KEY_MARK. Lights no switch takes go in a chain from the panel; a switch with no light of
    the group gets a line of its own. With one_feed only one cable of the group comes into a room
    from the panel, to the switch nearest to the panel; there it branches in the flush box
    (_Chain.feed). Returns the links and the ids of the points they took."""
    lamps = {p.id: p for p in pts if p.type in LAMP_TYPES}
    switches = [p for p in pts if p.type in SWITCH_TYPES]
    on: dict[str, list[str]] = {s.id: [] for s in switches}
    for lk in switch_links(elec):
        if lk.switch in on:
            on[lk.switch] = [t for t in lk.targets if t in lamps]
    chain = _Chain(ctx, group, mark, assumed, route, one_feed, lamps)
    for g in _pass_sets(switches, on):
        g.sort(key=lambda x: (chain.from_board(x), x.id))
        chain.start(g[0])
        for a, b in itertools.pairwise(g):
            chain.point_link(a, b, PASS_MARK, True)
        chain.lamps_after(g[-1], [t for x in g for t in on[x.id]], mark, assumed)
    for s in (s for s in switches if s.type is not PointType.PASS_SWITCH):
        chain.start(s)
        two = s.keys == 2
        chain.lamps_after(s, on[s.id], TWO_KEY_MARK if two else mark, two or assumed)
    free = [p for p in lamps.values() if p.id not in chain.taken]
    if free:
        first = min(free, key=lambda p: (chain.from_board(p), p.id))
        chain.taken.add(first.id)
        chain.start(first)
        chain.lamps_after(first, [p.id for p in free], mark, assumed)
    if chain.starts:
        chain.feed(chain.starts)
    return chain.out, {*lamps, *(s.id for s in switches)}


def _pass_sets(
    switches: Sequence[ElectricalPoint], on: dict[str, list[str]]
) -> list[list[ElectricalPoint]]:
    """Pass switches that share a light are one set: fed one after another, the lights after the
    last."""
    sets: list[list[ElectricalPoint]] = []
    for s in (s for s in switches if s.type is PointType.PASS_SWITCH):
        mine = set(on[s.id])
        joined = [g for g in sets if mine & {t for x in g for t in on[x.id]}]
        merged = [x for g in joined for x in g] + [s]
        sets = [g for g in sets if g not in joined] + [merged]
    return sets


@dataclass
class _Chain:
    """The links of one group's light chain as they are built: what every link shares and where
    the group's lines begin (starts, with one_feed)."""

    ctx: Context
    group: str
    mark: str
    assumed: bool
    route: Route
    one_feed: bool
    lamps: dict[str, ElectricalPoint]
    out: list[Link] = field(default_factory=list)
    taken: set[str] = field(default_factory=set)
    starts: list[ElectricalPoint] = field(default_factory=list)

    @staticmethod
    def loop(p: ElectricalPoint) -> bool:
        return p.ceiling is not None and p.type in LAMP_TYPES

    def plane(self, p: ElectricalPoint) -> Route:
        """Plane of a line from the panel to the point: the ceiling for a ceiling point."""
        return "ceiling" if self.route == "ceiling" or p.ceiling is not None else "floor"

    def from_board(self, p: ElectricalPoint) -> float:
        """Cost from the panel to the point on the plane its line would take."""
        return self.ctx.from_source("board", self.plane(p)).cost(self.ctx.anchors[p.id].node)

    def board_link(self, p: ElectricalPoint, cable: str, cable_assumed: bool) -> None:
        ctx, way = self.ctx, self.plane(p)
        up = ctx.source_rise(way)
        ends = (LIGHT_LOOP if self.loop(p) else END_ALLOWANCE) + ctx.tail("board")
        down = rise(p, ctx.ceiling, way)
        line = Link(self.group, cable, cable_assumed, "board", p.id, ctx.anchors[p.id], up, down,
                    way, "power", False, ends)  # fmt: skip
        self.out.append(line)

    def point_link(
        self, a: ElectricalPoint, b: ElectricalPoint, cable: str, cable_assumed: bool,
        wall: bool = False,
    ) -> None:  # fmt: skip
        ctx = self.ctx
        way = between_plane(self.route, a, b)
        ends = (0.0 if self.loop(a) else END_ALLOWANCE) + (
            LIGHT_LOOP if self.loop(b) else END_ALLOWANCE
        )
        # wall: a jumper inside one frame, it does not go up to the ceiling or down to the floor
        up, down = (0.0, 0.0) if wall else (rise(a, ctx.ceiling, way), rise(b, ctx.ceiling, way))
        line = Link(self.group, cable, cable_assumed, a.id, b.id, ctx.anchors[b.id], up, down, way,
                    "power", a.room != b.room, ends, wall=wall)  # fmt: skip
        self.out.append(line)

    def start(self, p: ElectricalPoint) -> None:
        """Where a line of the group begins: from the panel, or with one_feed noted for feed()."""
        if self.one_feed:
            self.starts.append(p)
        else:
            self.board_link(p, self.mark, self.assumed)

    def lamps_after(
        self, start: ElectricalPoint, ids: Sequence[str], cable: str, cable_assumed: bool
    ) -> None:
        """From the start on to its lights, the nearest not yet taken each time."""
        left = [self.lamps[i] for i in dict.fromkeys(ids) if i not in self.taken]  # pass share
        self.taken.update(p.id for p in left)
        prev = start
        for p in self.ctx.nearest_chain(self.ctx.anchors[prev.id].node, left):
            self.point_link(prev, p, cable, cable_assumed)
            prev = p

    def feed(self, part: Sequence[ElectricalPoint]) -> None:
        """One panel line for the line starts of the group, the rest from switch flush boxes.
        Into another room the feed goes through the opening; a start there that is closer to
        the panel than to any switch already fed gets a panel line of its own."""
        ctx, mark, assumed = self.ctx, self.mark, self.assumed
        reach: dict[str, Router] = {}

        def near(p: ElectricalPoint) -> tuple[float, str]:
            return self.from_board(p), p.id

        def gap(a: ElectricalPoint, b: ElectricalPoint) -> float:
            if a.room == b.room:
                return (ctx.anchors[a.id].node - ctx.anchors[b.id].node).length()
            if a.id not in reach:
                end = anchor_end(ctx.anchors[a.id])
                reach[a.id] = ctx.flat_router(end, self.route)
            return reach[a.id].cost(ctx.anchors[b.id].node)

        root = min([p for p in part if p.type in SWITCH_TYPES] or part, key=near)
        self.board_link(root, mark, assumed)
        fed, left = [root], [p for p in part if p is not root]
        feeds: dict[str, int] = {}
        while left:
            # Only flush boxes of this lighting line's switches: not sockets, not lights
            boxes = [a for a in fed if a.type in SWITCH_TYPES]
            free = [a for a in boxes if feeds.get(a.id, 0) < BACK_BOX_FEEDS] or boxes
            if not free:
                b = min(left, key=near)
                self.board_link(b, mark, assumed)
                left.remove(b)
                fed.append(b)
                continue
            a, b = min(
                ((a, b) for a in free for b in left),
                key=lambda ab: (gap(ab[0], ab[1]), ab[0].id, ab[1].id),
            )
            if a.room != b.room and near(b)[0] < gap(a, b):
                self.board_link(b, mark, assumed)
            else:
                self.point_link(a, b, mark, assumed, wall=same_frame(a, b))
                feeds[a.id] = feeds.get(a.id, 0) + 1
            left.remove(b)
            fed.append(b)
