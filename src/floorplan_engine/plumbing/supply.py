"""Water supply routes: supply unit, manifolds, radial and tee layouts, shared lines."""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import replace

import shapely
from shapely.geometry import LineString

from floorplan_engine.electrical.routing import (
    CLEARANCE,
    fit_path,
    simplify,
)
from floorplan_engine.model.geometry import (
    Vec,
    WallSegment,
)
from floorplan_engine.model.plumbing import (
    Fixture,
)
from floorplan_engine.plumbing.context import Ctx, nearest_wall
from floorplan_engine.plumbing.network_model import Collector, Outlet, Pipe, weak_spot
from floorplan_engine.plumbing.pipe_search import (
    plan_length,
    route_one,
    route_tree,
    target_node,
    wall_node,
)
from floorplan_engine.plumbing.rules import (
    BOILER_NEAR,
    BRANCH_SAVING,
    CAPACITY,
    COLLECTOR_GAP,
    COLLECTOR_HALF,
    COLLECTOR_HEIGHT,
    FLOW,
    MAIN_D,
    PAIR_GAP,
    PARALLEL_GAP,
    PARALLEL_MIN,
    SHARE_GAP,
    SHARED_PAIRS,
    SHARED_TYPES,
    SUPPLY_D,
    Kind,
)


def supply_groups(fixtures: Sequence[Fixture]) -> dict[str, str]:
    """Fixture → the fixture it shares a manifold line with (the first in the group; a single one
    maps
    to itself): SHARED_PAIRS pairs of one room on one wall with neighbouring supplies no farther
    than SHARE_GAP (double vanity; dishwasher by the sink)."""
    out = {f.id: f.id for f in fixtures}
    shared = sorted(
        (f for f in fixtures if f.type in SHARED_TYPES), key=lambda f: (f.room, f.wall, f.offset)
    )
    for a, b in itertools.pairwise(shared):
        near = (a.room, a.wall) == (b.room, b.wall) and b.offset - a.offset <= SHARE_GAP
        if near and (a.type, b.type) in SHARED_PAIRS:
            out[b.id] = out[a.id]
    return out


def _input_place(ctx: Ctx) -> tuple[str, str, float] | None:
    """Supply unit: from plumbing.yaml, or at the water riser (else the first riser) as an
    assumption.
    """
    inp = ctx.plumbing.input
    if inp is not None:
        return inp.room, inp.wall, inp.offset
    risers = sorted(ctx.net.risers, key=lambda r: not r.water)
    if not risers:
        return None
    r = risers[0]
    seg, t = nearest_wall(ctx.geoms[r.room], r.center)
    ctx.net.input_assumed = True
    return r.room, seg.id, t


def _hot_source(ctx: Ctx) -> str | None:
    """Where hot water comes from: a riser (riser) or a boiler (fixture id); None if from
    nowhere.
    """
    inp = ctx.plumbing.input
    boiler = next((f.id for f in ctx.plumbing.fixtures if f.spec.hot_source), None)
    if inp is not None and inp.hot is not None:
        return "riser" if inp.hot else boiler
    return boiler if boiler is not None else ("riser" if ctx.net.risers else None)


def route_supply(ctx: Ctx) -> None:
    net = ctx.net
    users = {k: [o for o in net.outlets if o.kind == k] for k in ("cold", "hot")}
    if not users["cold"] and not users["hot"]:
        return
    place = _input_place(ctx)
    if place is None:
        return
    room, wall, offset = place
    seg = ctx.geoms[room].contour.segment(wall)
    inp = ctx.plumbing.input
    hot = _hot_source(ctx)
    net.hot_source = hot
    boiler_out = [o for o in users["hot"] if o.fixture == hot] if hot not in (None, "riser") else []
    hot_users = [o for o in users["hot"] if o.fixture != hot]
    if hot is None and hot_users:
        net.weak.append(weak_spot("warning", "no_hot", ""))
        hot_users = []
    tee = ctx.plumbing.distribution == "tee"
    water: tuple[tuple[Kind, float, list[Outlet]], ...] = (
        ("cold", COLLECTOR_GAP / 2, users["cold"]),
        ("hot", -COLLECTOR_GAP / 2, hot_users),
    )
    for kind, shift, outlets in water:
        if not outlets or (kind == "hot" and tee and boiler_out):
            continue  # hot main in the tee layout starts at the boiler
        c_room, c_wall, c_seg, c_at = room, wall, seg, offset + shift
        c_h = inp.height if inp is not None and inp.height is not None else COLLECTOR_HEIGHT
        far = boiler_out and (boiler_out[0].node - seg.point_at(offset)).length() > BOILER_NEAR
        if kind == "hot" and far:
            # Hot water from a boiler far from the unit: its manifold is at the boiler (change
            # 2026-11-02);
            # otherwise hot water would run from the boiler to the unit and back to fixtures by the
            # boiler
            b = boiler_out[0]
            c_room, c_wall = b.room, b.wall
            c_seg = ctx.geoms[b.room].contour.segment(b.wall)
            c_at = _clear_offset(ctx, c_seg, b.offset)
            c_h = COLLECTOR_HEIGHT
        at = min(max(c_at, 0.0), c_seg.length)
        col = Collector(
            f"collector_{kind}",
            kind,
            c_room,
            c_wall,
            at,
            c_seg.point_at(at),
            c_seg.inward,
            len(outlets),
            c_h,
        )
        net.collectors.append(col)
    collectors = {c.kind: c for c in net.collectors}
    # The boiler feeds hot water into the hot manifold (radial) or starts the main
    if boiler_out and "hot" in collectors and ctx.plumbing.distribution == "collector":
        route_one(
            ctx,
            "hot",
            boiler_out[0].fixture,
            boiler_out[0],
            collectors["hot"].id,
            target_node(collectors["hot"]),
            MAIN_D,
            target_id=collectors["hot"].id,
        )
    groups = supply_groups(ctx.plumbing.fixtures)
    with_hot = {o.fixture for o in users["hot"]}
    for kind, _, outlets in water:
        found = collectors.get(kind)
        if not tee and found is not None:
            by_group: dict[str, list[Outlet]] = {}
            for o in outlets:
                by_group.setdefault(groups.get(o.fixture, o.fixture), []).append(o)
            for members in by_group.values():  # groups come before parallel lines (_merge_parallel)
                # The line goes to the group fixture with hot water (cold goes to it paired with
                # hot), and of
                # those to the one nearest the manifold; the others are teed off it
                lead, *rest = sorted(
                    members,
                    key=lambda o: (o.fixture not in with_hot, (o.node - found.node).length()),
                )
                pipe = _radial(ctx, kind, found, lead)
                if rest and pipe is not None:
                    route_tree(
                        ctx,
                        kind,
                        found.id,
                        wall_node(found),
                        rest,
                        attach_to=[pipe.id],
                        main_d=SUPPLY_D,
                    )
            _merge_parallel(ctx, kind, found)
            for k, c in enumerate(net.collectors):
                lines = [p for p in net.pipes if p.source == c.id and p.parent is None]
                net.collectors[k] = replace(c, outputs=len(lines))
        elif tee and kind == "hot" and boiler_out:
            route_tree(ctx, kind, boiler_out[0].fixture, boiler_out[0], outlets)
        elif tee and found is not None:
            route_tree(ctx, kind, found.id, wall_node(found), outlets)


def _subtree(pipes: Sequence[Pipe], root: Pipe) -> list[Pipe]:
    """A pipe and all branches off it (and off its branches)."""
    out, todo = [root], [root.id]
    while todo:
        pid = todo.pop()
        for p in pipes:
            if p.parent == pid:
                out.append(p)
                todo.append(p.id)
    return out


def _demand(ctx: Ctx, pipes: Sequence[Pipe]) -> float:
    """Design flow of the fixtures on these pipes, l/s (FLOW)."""
    types = {f.id: f.type for f in ctx.plumbing.fixtures}
    return sum(FLOW.get(types[p.target], 0.1) for p in pipes if p.target in types)


def pipe_d(flow: float) -> int | None:
    """Pipe Ø for the flow; None if even Ø20 cannot carry it."""
    return next((d for d in sorted(CAPACITY) if flow <= CAPACITY[d] + 1e-9), None)


def _alongside(a: Pipe, b: Pipe) -> float:
    """How many mm of path b on the floor run next to a (closer than PARALLEL_GAP)."""
    if len(a.path) < 2 or len(b.path) < 2:
        return 0.0
    near = LineString([v.as_tuple() for v in a.path]).buffer(PARALLEL_GAP)
    return float(LineString([v.as_tuple() for v in b.path]).intersection(near).length)


def _merge_parallel(ctx: Ctx, kind: Kind, col: Collector) -> None:
    """Parallel lines (change 2026-11-02): a branch from the manifold is moved onto another branch
    with a tee if it runs alongside it for more than PARALLEL_MIN and the network water gets
    shorter, or if the tee saves at least BRANCH_SAVING; the shared pipe must carry the flow
    (FLOW, CAPACITY: Ø16, else Ø20; no larger). The boiler line stays separate: it heats water
    for the whole flat. Pairs with the longest shared piece go first; repeat while something can
    be merged."""
    net = ctx.net
    rejected: set[tuple[str, str]] = set()
    boilers = {f.id for f in ctx.plumbing.fixtures if f.spec.hot_source}
    while True:
        water = [p for p in net.pipes if p.kind == kind]
        roots = [
            p for p in water if p.source == col.id and p.parent is None and p.target not in boilers
        ]
        pairs = sorted(
            (
                (_alongside(a, b), a, b)
                for a in roots
                for b in roots
                if a is not b and (a.target, b.target) not in rejected
            ),
            key=lambda x: -x[0],
        )
        if not pairs:
            return
        along, a, b = pairs[0]
        moved = _subtree(water, b)
        d = pipe_d(_demand(ctx, _subtree(water, a)) + _demand(ctx, moved))
        saving = 1.0 if along >= PARALLEL_MIN else BRANCH_SAVING
        if d is None or not _rehang(ctx, kind, col, a, moved, d, saving):
            rejected.add((a.target, b.target))


def _rehang(
    ctx: Ctx, kind: Kind, col: Collector, a: Pipe, moved: list[Pipe], d: int, saving: float
) -> bool:
    """Re-hang the moved pipes (a branch and its sub-branches) onto pipe a with a tee; a is Ø d.
    If the network water gets shorter by less than saving mm, or the branch finds no spot on a,
    put things back (False)."""
    net = ctx.net
    before = list(net.pipes)
    old = sum(p.total for p in net.pipes if p.kind == kind)
    gone = {p.id for p in moved}
    outlets = [o for p in moved for o in net.outlets if o.fixture == p.target and o.kind == kind]
    net.pipes = [p for p in net.pipes if p.id not in gone]
    k = net.pipes.index(a)
    net.pipes[k] = replace(a, d=d)
    route_tree(ctx, kind, col.id, wall_node(col), outlets, attach_to=[a.id], main_d=d)
    new = [p for p in net.pipes if p.kind == kind]
    hung = all(p.parent is not None for p in new if p.target in {o.fixture for o in outlets})
    if hung and sum(p.total for p in new) <= old - saving:
        return True
    net.pipes = before
    return False


def _radial(ctx: Ctx, kind: Kind, col: Collector, o: Outlet) -> Pipe | None:
    """Branch from the manifold to a water outlet; hot goes paired with cold if cold is already
    there.
    """
    net = ctx.net
    cold = next((p for p in net.pipes if p.kind == "cold" and p.target == o.fixture), None)
    if kind == "hot" and cold is not None and cold.parent is None and _pair(ctx, cold, col, o):
        return net.pipes[-1]
    return route_one(ctx, kind, col.id, wall_node(col), o.fixture, o, SUPPLY_D)


def _clear_offset(ctx: Ctx, seg: WallSegment, offset: float) -> float:
    """Wall spot closest to offset where the manifold (COLLECTOR_HALF each way) is not behind an
    obstacle: under a boiler above an installation frame the manifold cannot go, so next to it."""
    obstacles = list(ctx.net.obstacles.values())
    if not obstacles:
        return offset
    blocked = shapely.unary_union(obstacles).buffer(1.0)

    def clear(t: float) -> bool:
        a, b = seg.point_at(t - COLLECTOR_HALF), seg.point_at(t + COLLECTOR_HALF)
        return not blocked.intersects(LineString([a.as_tuple(), b.as_tuple()]))

    lo, hi = COLLECTOR_HALF, seg.length - COLLECTOR_HALF
    for k in range(int(seg.length // 50) + 1):
        for t in (offset - 50 * k, offset + 50 * k):
            if lo <= t <= hi and clear(t):
                return t
    return offset


def parallel(path: Sequence[Vec], gap: float) -> list[Vec]:
    """Orthogonal polyline shifted left along its direction by gap (right if gap < 0)."""
    pts = simplify(path)
    if len(pts) < 2:
        return list(pts)

    def normal(i: int) -> Vec:
        d = pts[i + 1] - pts[i]
        u = d * (1 / d.length())
        return Vec(-u.y, u.x)

    out = [pts[0] + normal(0) * gap]
    for i in range(1, len(pts) - 1):
        a, b = normal(i - 1), normal(i)
        same = abs(a.x - b.x) < 1e-9 and abs(a.y - b.y) < 1e-9
        out.append(pts[i] + a * gap if same else pts[i] + (a + b) * gap)
    out.append(pts[-1] + normal(len(pts) - 2) * gap)
    return out


def _pair(ctx: Ctx, cold: Pipe, col: Collector, o: Outlet) -> bool:
    """Hot water to a fixture goes paired with cold: the same route, shifted by PAIR_GAP to the side
    where it is free; the ends go to the hot manifold and the water outlet. No room on either
    side gives False (hot water is routed on its own)."""
    free = ctx.net.free
    if free is None or len(cold.path) < 3:
        return False
    inside = free.buffer(CLEARANCE - 1.0)
    best: list[Vec] | None = None
    for gap in (PAIR_GAP, -PAIR_GAP):
        shifted = parallel(cold.path, gap)
        if len(shifted) < 2:
            continue
        path = fit_path(shifted, col.node, o.node)
        floor = path[1:-1]
        if len(floor) >= 2 and not inside.covers(LineString([v.as_tuple() for v in floor])):
            continue
        if best is None or plan_length(path) < plan_length(best):
            best = path
    if best is None:
        return False
    along = cold.wall_run
    pipe = Pipe(
        ctx.new_id("hot"),
        "hot",
        col.id,
        o.fixture,
        tuple(best),
        SUPPLY_D,
        rise=o.height + col.height,
        wall_run=along,
        room=o.room,
    )
    ctx.net.pipes.append(pipe)
    return True
