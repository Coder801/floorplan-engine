"""Pipe search on the plumbing grids: one route, a tree of routes, riser heads and inverts."""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

import shapely
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from floorplan_engine.electrical.routing import (
    CLEARANCE,
    STEP,
    Grid,
    simplify,
)
from floorplan_engine.model.geometry import (
    Vec,
)
from floorplan_engine.plumbing import bends as b45
from floorplan_engine.plumbing.context import (
    Approach,
    Ctx,
    SearchField,
    best_approach,
    height_prune,
    point_approach,
)
from floorplan_engine.plumbing.network_model import Collector, Outlet, Pipe, RiserNode
from floorplan_engine.plumbing.rules import (
    ALONG_COST,
    FALLBACK_COST,
    HOLE_SHARE,
    MAIN_D,
    PARTITION_COST,
    RISER_REACH,
    RISER_TEE_D,
    RISER_WALL,
    SCREED_MM,
    SLOPE_MIN,
    SUPPLY_D,
    Kind,
)


def plan_length(path: Sequence[Vec]) -> float:
    return sum((b - a).length() for a, b in itertools.pairwise(path))


@dataclass(frozen=True)
class _Node:
    """Node on a wall: route source or target."""

    room: str
    wall: str
    offset: float
    node: Vec
    height: float


def wall_node(c: Collector) -> _Node:
    return _Node(c.room, c.wall, c.offset, c.node, c.height)


def target_node(c: Collector) -> Outlet:
    return Outlet(c.id, c.kind, c.room, c.wall, c.offset, c.height, c.node, c.inward, MAIN_D, False)


def _start(ctx: Ctx, src: _Node | Outlet) -> tuple[SearchField, Approach] | None:
    options = ctx.wall_approaches(src.room, src.wall, src.offset)
    if not options:
        return None
    a = options[0]
    return SearchField.from_cell(ctx.grid, a.cell), a


def route_one(
    ctx: Ctx,
    kind: Kind,
    source: str,
    src: _Node | Outlet,
    target: str,
    dst: Outlet,
    d: int,
    target_id: str | None = None,
) -> Pipe | None:
    """Pipe from node src to supply dst: on the floor from wall to wall, the tails in the wall."""
    started = _start(ctx, src)
    approach = None
    if started is not None:
        fld, head = started
        approach = best_approach(fld, ctx.wall_approaches(dst.room, dst.wall, dst.offset))
    if started is None or approach is None:
        ctx.unreachable(target, kind)
        return None
    fld, head = started
    middle = fld.path(approach.cell)
    path = simplify([*reversed(head.tail), *middle, *approach.tail[1:]])
    pipe = Pipe(
        ctx.new_id(kind),
        kind,
        source,
        target_id or target,
        tuple(path),
        d,
        rise=dst.height + src.height,
        wall_run=approach.along + head.along,
        room=dst.room,
    )
    ctx.net.pipes.append(pipe)
    _open_holes(ctx, pipe)
    return pipe


def _open_holes(ctx: Ctx, pipe: Pipe) -> None:
    """A hole in a partition already used by a water pipe is free (no PARTITION_COST) for the next
    water pipes: they go as a bundle through the same hole instead of making their own (change
    2026-11-02: the washing machine pipe went through the living room instead of through the
    bathroom with the rest)."""
    net, grid = ctx.net, ctx.grid
    if pipe.kind == "sewer" or not net.partitions or grid.penalty is None:
        return
    line = LineString([v.as_tuple() for v in pipe.path])
    for strip in net.partitions:
        cut = line.intersection(strip)
        if cut.is_empty or cut.length < 1.0:
            continue
        near = cut.buffer(max(HOLE_SHARE / 2, CLEARANCE))
        shapely.prepare(near)
        for k, cost in list(grid.penalty.items()):
            if cost == PARTITION_COST and near.contains(shapely.Point(grid.center(k).as_tuple())):
                grid.penalty[k] = 0.0


def tree_points(pipe: Pipe) -> list[tuple[Vec, float]]:
    """Spots along a floor pipe where a branch can tee in (without the wall tails): point and mm
    from the start.
    """
    out: list[tuple[Vec, float]] = []
    acc = 0.0
    floor = pipe.path[1:-1] if len(pipe.path) > 2 else pipe.path
    pts = list(pipe.path)
    for a, b in itertools.pairwise(pts):
        seg_len = (b - a).length()
        if a in floor and b in floor and seg_len > 1e-6:
            n = max(1, int(seg_len // STEP))
            for k in range(n + 1):
                out.append((a + (b - a) * (k / n), acc + seg_len * k / n))
        acc += seg_len
    return out


def _riser_heads(grid: Grid, center: Vec, rooms: BaseGeometry | None = None) -> list[Approach]:
    """Approaches to a riser from four sides: a riser in a wall projection or in a box is reached
    from the fixture's side (the nearest free cell on each axis). Inside a wall (outside rooms) at
    most RISER_WALL: a pipe does not run along the inside of a wall."""
    out: list[Approach] = []
    inside = rooms.buffer(1.0) if rooms is not None else None
    seen: set[int] = set()
    reach = int(RISER_REACH // STEP) + 1
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        for k in range(reach + 1):
            p = Vec(center.x + dx * k * STEP, center.y + dy * k * STEP)
            ix = round((p.x - grid.x0) / STEP)
            iy = round((p.y - grid.y0) / STEP)
            if not (0 <= ix < grid.nx and 0 <= iy < grid.ny):
                break
            cell = iy * grid.nx + ix
            if grid.free[cell]:
                head = point_approach(grid, center, cell)
                tail = LineString([v.as_tuple() for v in head.tail])
                in_wall = tail.difference(inside).length if inside is not None else 0.0
                if cell not in seen and in_wall <= RISER_WALL:
                    seen.add(cell)
                    out.append(head)
                break
    if not out:
        out.append(point_approach(grid, center))
    return out


def _heads(ctx: Ctx, src: _Node | Outlet | RiserNode) -> list[Approach]:
    if isinstance(src, RiserNode):
        return _riser_heads(ctx.grid, src.center, ctx.net.rooms)
    options = ctx.wall_approaches(src.room, src.wall, src.offset)
    return options[:1]


def root_of(pipes: dict[str, Pipe], p: Pipe) -> str:
    while p.parent is not None:
        p = pipes[p.parent]
    return p.source


def route_tree(
    ctx: Ctx,
    kind: Kind,
    source: str,
    src: _Node | Outlet | RiserNode,
    outlets: Sequence[Outlet],
    only_into: int | None = None,
    attach_to: Sequence[str] | None = None,
    main_d: int = MAIN_D,
) -> None:
    """Tree from a source: fixtures by cost from the source; each is a branch off the nearest spot
    of
    the pipes already laid (or off the source). only_into restricts branches to pipes of this
    diameter (a Ø110 WC only into Ø110 or the riser); attach_to restricts branches to these pipes
    (a group's shared line from the manifold); main_d is the Ø of a pipe with branches (water:
    the tee layout main is Ø20, the shared basin line Ø16)."""
    heads = _heads(ctx, src)
    if not heads:
        for o in outlets:
            ctx.unreachable(o.fixture, kind)
        return
    fields = [ctx.field(h.cell) for h in heads]
    if ctx.prune is not None:  # fallback: no pruning, else unreachable
        fields += [replace(ctx.field(h.cell, prune=False), offset=FALLBACK_COST) for h in heads]
    lift = src.height if not isinstance(src, RiserNode) else 0.0

    def reach(o: Outlet) -> float:
        options = ctx.wall_approaches(o.room, o.wall, o.offset)
        best = math.inf
        for fld in fields:
            a = best_approach(fld, options)
            if a is not None:
                best = min(best, fld.cost(a.cell) + a.along * ALONG_COST)
        return best

    order = sorted(outlets, key=reach)
    by_id = {p.id: p for p in ctx.net.pipes if p.kind == kind}
    if attach_to is not None:
        tree = [by_id[i] for i in attach_to if i in by_id]
    else:
        tree = [p for p in by_id.values() if root_of(by_id, p) == source]
    for o in order:
        if math.isinf(reach(o)):
            ctx.unreachable(o.fixture, kind)
            continue
        options = ctx.wall_approaches(o.room, o.wall, o.offset)
        here = min(
            (a for fld in fields if (a := best_approach(fld, options)) is not None),
            key=lambda a: min(f.cost(a.cell) for f in fields) + a.along * ALONG_COST,
        )
        # Search from the fixture: to the source and to each tee spot on pipes already laid
        back = ctx.field(here.cell)
        if all(math.isinf(back.cost(h.cell)) for h in heads):
            back = ctx.field(here.cell, prune=False)
        head = min(heads, key=lambda h: back.cost(h.cell))
        best_cost = back.cost(head.cell)
        best: tuple[Pipe, Vec, float] | None = None
        for p in tree:
            if only_into is not None and p.d != only_into:
                continue
            for at, along in tree_points(p):
                c = back.cost(ctx.grid.nearest_free(at))
                if c < best_cost - 1e-6:
                    best_cost, best = c, (p, at, along)
        d = o.d if kind == "sewer" else SUPPLY_D
        if best is None:
            middle = list(reversed(back.path(head.cell)))
            path = simplify([*reversed(head.tail), *middle, *here.tail[1:]])
            if kind == "sewer":
                path, _ = shape45(path)
            pipe = Pipe(
                ctx.new_id(kind),
                kind,
                source,
                o.fixture,
                tuple(path),
                d,
                o.height + lift,
                here.along + head.along,
                room=o.room,
            )
        else:
            parent, at, along = best
            cell = ctx.grid.nearest_free(at)
            middle = list(reversed(back.path(cell)))
            path = simplify([at, *middle, *here.tail[1:]])
            if kind == "sewer":
                path, along = shape45(path, parent, along)
            pipe = Pipe(
                ctx.new_id(kind),
                kind,
                parent.id,
                o.fixture,
                tuple(path),
                d,
                o.height,
                here.along,
                parent=parent.id,
                attach=along,
                room=o.room,
            )
            if kind != "sewer" and parent.d < main_d:  # with a branch: a Ø20 main
                k = ctx.net.pipes.index(parent)
                ctx.net.pipes[k] = replace(parent, d=main_d)
                tree[tree.index(parent)] = ctx.net.pipes[k]
        ctx.net.pipes.append(pipe)
        _open_holes(ctx, pipe)
        tree.append(pipe)


def shape45(
    path: Sequence[Vec], parent: Pipe | None = None, along: float = 0.0
) -> tuple[list[Vec], float]:
    """Sewer on the plan with 45° bends only: pieces in eight directions, the tee into pipe parent
    is an angled tee (the tee spot along moves towards the riser), corners use bends."""
    pts = b45.octilinear(path)
    if parent is not None:
        pts, along = b45.tee45(pts, parent.path, along)
    return b45.chamfer(pts), along


def riser_invert(r: RiserNode) -> float:
    """Pipe bottom at the riser inlet, mm from the slab: inlet axis from the finished floor plus the
    screed minus the radius of the Ø110 tee (a Ø50 pipe goes through a reducer, bottom flush with
    the tee). Sewer heights are always the pipe bottom; axis ↔ bottom conversion happens here and
    in outlet_invert."""
    return SCREED_MM + r.inlet - RISER_TEE_D / 2


def outlet_invert(o: Outlet) -> float:
    """Fixture drain bottom, mm from the slab: axis from the finished floor plus the screed minus
    the radius.
    """
    return SCREED_MM + o.height - o.d / 2


def riser_fields(ctx: Ctx, r: RiserNode, d: int) -> list[tuple[Approach, SearchField]]:
    """Search from the riser on each side: with height pruning for Ø d (the flattest slope allowed
    for it) and a fallback without pruning, FALLBACK_COST dearer, for a fixture that is otherwise
    unreachable (_evaluate will find the screed error)."""
    out: list[tuple[Approach, SearchField]] = []
    heads = _riser_heads(ctx.grid, r.center, ctx.net.rooms)
    prune = height_prune(ctx.grid, riser_invert(r), SLOPE_MIN[angle_norm(d)], d)
    for h in heads:
        tail = plan_length(h.tail)
        out.append((h, SearchField.from_cell(ctx.grid, h.cell, 8, prune, tail)))
    for h in heads:
        out.append((h, SearchField.from_cell(ctx.grid, h.cell, 8, offset=FALLBACK_COST)))
    return out


def angle_norm(d: int) -> int:
    return 110 if d >= 100 else 50
