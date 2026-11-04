"""Ø50 drain tees: fixture pairs merged by pipe savings (spec "tees" 2026-11-02)."""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString

from floorplan_engine.electrical.routing import (
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
)
from floorplan_engine.plumbing.network_model import Outlet, Pipe, RiserNode
from floorplan_engine.plumbing.pipe_search import (
    angle_norm,
    outlet_invert,
    plan_length,
    riser_fields,
    riser_invert,
    root_of,
    shape45,
    tree_points,
)
from floorplan_engine.plumbing.rules import (
    ALONG_COST,
    PIPE_WEIGHT,
    SCREED_COVER,
    SCREED_MM,
    SEWER_BEND_COST,
    SLOPE_MIN,
    TAG_NEAR,
    TAG_OPEN,
    TEE_CANDIDATES,
)


@dataclass
class _Merge:
    """Node of the Ø50 sewer tree: a fixture (leaf) or a tee J over two nodes. Each fixture of the
    node has the pipe length from its approach spot to the node cell (for heights)."""

    cell: int
    fld: SearchField
    cost: np.ndarray  # path cost from the node to every grid cell
    members: list[Outlet]
    length: dict[str, float]
    leaf: Outlet | None = None
    approach: Approach | None = None
    children: tuple[_Merge, _Merge] | None = None


def _cost_array(fld: SearchField) -> np.ndarray:
    out = np.full(fld.grid.nx * fld.grid.ny, math.inf)
    for state, d in fld.dist.items():
        cell = state // fld.ndirs
        if d < out[cell]:
            out[cell] = d
    return out + fld.offset


def _node(ctx: Ctx, cell: int, members: list[Outlet], length: dict[str, float]) -> _Merge:
    fld = ctx.field(cell)
    return _Merge(cell, fld, _cost_array(fld), members, length)


def _between(a: _Merge, cell: int) -> list[Vec]:
    """Grid path from cell to node a (backwards along the flow)."""
    if cell == a.cell:
        return [a.fld.grid.center(cell)]
    return list(reversed(a.fld.path(cell)))


def merge_drains(ctx: Ctx, r: RiserNode, outlets: Sequence[Outlet]) -> None:
    """Ø50 fixtures joined to riser r as a tree with the least pipe consumption ("tees" spec): for
    each pair of nodes (A, B), the tee spot J with the lowest cost d(A, J) + d(B, J) + k·d(J, R)
    (d is a grid path with 45° bends, a bend costs SEWER_BEND_COST, k is the main's PIPE_WEIGHT);
    the pair saving is d(A, R) + d(B, R) − cost. Pairs are merged in order of decreasing saving,
    J becomes a new node; a tee is not allowed if a fixture that fitted the screed or the drop on
    its own stops fitting with it (then the next spot by cost is tried), or if the branch to the
    tee runs through the middle of a room above the screed (length is the full path fixture →
    tee → riser). The search from the riser uses height pruning (height_prune), the search from
    fixtures a lower length bound. A node closer to the Ø110 (WC) pipe than to the riser tees into
    it with a 110×50 tee. Alignment and the 45° entry are handled when the pipe is assembled
    (shape45)."""
    if not outlets:
        return
    grid = ctx.grid
    pairs = riser_fields(ctx, r, 50)
    heads = [h for h, _ in pairs]
    hfields = [f for _, f in pairs]
    rcost = np.minimum.reduce([_cost_array(f) for f in hfields])
    z0 = riser_invert(r)
    slope = SLOPE_MIN[50]
    limit = SCREED_MM - 50 - SCREED_COVER
    tags = grid.tag
    # Branches from fixtures: the length to the riser is unknown, use a straight-line lower bound
    ctx.prune = height_prune(grid, z0, slope, 50, lower=r.center)

    def to_riser(cell: int) -> tuple[list[Vec], float]:
        """From the riser to the cell: the tail to the riser and the grid path."""
        k = min(range(len(heads)), key=lambda i: hfields[i].cost(cell))
        path = [*reversed(heads[k].tail), *hfields[k].path(cell)[1:]]
        return path, plan_length(path) - heads[k].along

    nodes: list[_Merge] = []
    direct: dict[str, float] = {}  # mm along the pipe from the fixture approach spot to the riser
    for o in outlets:
        options = ctx.wall_approaches(o.room, o.wall, o.offset)
        found = [x for f in hfields if (x := best_approach(f, options)) is not None]
        here = min(found, key=lambda x: float(rcost[x.cell]) + x.along * ALONG_COST, default=None)
        if here is None or math.isinf(rcost[here.cell]):
            ctx.unreachable(o.fixture, "sewer")
            continue
        node = _node(ctx, here.cell, [o], {o.fixture: 0.0})
        node.leaf, node.approach = o, here
        nodes.append(node)
        direct[o.fixture] = to_riser(here.cell)[1]
        path = simplify([*to_riser(here.cell)[0], *here.tail[1:]])
        shaped, _ = shape45(path)
        ctx.net.sewer_direct += equivalent_length(shaped, 50)

    def leg_ok(leg: Sequence[Vec], s0: float) -> bool:
        """Branch from the tee (leg[0]) to the node: in the room middle the pipe bottom plus Ø and
        the
        cover must not exceed the screed; s0 is mm along the pipe from the riser to the tee."""
        if tags is None:
            return True
        s = s0
        for a, b in itertools.pairwise(leg):
            s += (b - a).length()
            c = grid.nearest_free(b)
            if tags[c] in (TAG_NEAR, TAG_OPEN) and z0 + s * slope > limit + 0.5:
                return False
        return True

    def admissible(na: _Merge, nb: _Merge, cell: int) -> bool:
        tail = to_riser(cell)[1]
        legs = {id(n): _between(n, cell) for n in (na, nb)}
        for n in (na, nb):
            leg = legs[id(n)]  # from the tee to the node
            if not leg_ok(leg, tail):
                return False
            for o in n.members:
                zd = z0 + direct[o.fixture] * slope
                zv = z0 + (n.length[o.fixture] + plan_length(leg) + tail) * slope
                zout = outlet_invert(o)
                if (zd <= limit + 0.5 < zv) or (zd <= zout + 0.5 < zv):
                    return False
        return True

    k = PIPE_WEIGHT[50]
    while len(nodes) > 1:
        best: tuple[float, int, int, int] | None = None  # saving, A, B, J
        for i, j in itertools.combinations(range(len(nodes)), 2):
            na, nb = nodes[i], nodes[j]
            total = na.cost + nb.cost + k * rcost
            gain = float(rcost[na.cell] + rcost[nb.cell])
            order = np.argsort(total, kind="stable")[:TEE_CANDIDATES]
            for cell in (int(c) for c in order):
                saving = gain - float(total[cell])
                if not math.isfinite(saving) or saving <= 1e-6:
                    break
                if best is not None and saving <= best[0] + 1e-6:
                    break
                if admissible(na, nb, cell):
                    best = (saving, i, j, cell)
                    break
        if best is None:
            break
        _, i, j, cell = best
        a, b = nodes[i], nodes[j]
        length = {
            o.fixture: a.length[o.fixture] + plan_length(_between(a, cell)) for o in a.members
        }
        length |= {
            o.fixture: b.length[o.fixture] + plan_length(_between(b, cell)) for o in b.members
        }
        joint = _node(ctx, cell, [*a.members, *b.members], length)
        joint.children = (a, b)
        nodes = [n for n in nodes if n is not a and n is not b] + [joint]
    ctx.prune = None
    sewer = {p.id: p for p in ctx.net.pipes if p.kind == "sewer"}
    big = [p for p in sewer.values() if p.d >= 100 and root_of(sewer, p) == r.id]
    for n in nodes:
        into = _into_110(ctx, n, big, float(rcost[n.cell]), leg_ok)
        if into is not None:
            parent, at, along = into
            _emit(ctx, r, n, [at, *_between(n, ctx.grid.nearest_free(at))], parent, along)
            continue
        path = to_riser(n.cell)[0]
        k_head = min(range(len(heads)), key=lambda i: hfields[i].cost(n.cell))
        _emit(ctx, r, n, path, None, heads[k_head].along)


def _into_110(
    ctx: Ctx,
    n: _Merge,
    big: Sequence[Pipe],
    to_riser: float,
    leg_ok: Callable[[Sequence[Vec], float], bool],
) -> tuple[Pipe, Vec, float] | None:
    """Tee spot of a Ø50 node into a Ø110 pipe with a 110×50 tee (routing spec, item 4), if that is
    cheaper than its own path to the riser and the branch does not run in the room middle above
    the screed."""
    best: tuple[float, Pipe, Vec, float] | None = None
    for p in big:
        for at, along in tree_points(p):
            c = n.fld.cost(ctx.grid.nearest_free(at))
            if c >= to_riser - 1e-6 or (best is not None and c >= best[0]):
                continue
            leg = _between(n, ctx.grid.nearest_free(at))  # from the tee to the node
            if leg_ok([at, *leg], along):
                best = (c, p, at, along)
    return (best[1], best[2], best[3]) if best is not None else None


def _emit(
    ctx: Ctx, r: RiserNode, node: _Merge, prefix: list[Vec], parent: Pipe | None, along: float
) -> None:
    """Pipes from the tree: from the start (riser or a spot on the parent pipe) along the "aligned"
    branch of each tee to a fixture is one pipe; the other branches are branches off it."""
    pts = list(prefix)
    branches: list[tuple[_Merge, int]] = []
    cur = node
    while cur.children is not None:
        incoming = ctx.grid.center(cur.cell) - pts[-2] if len(pts) >= 2 else None
        main, other = sorted(
            cur.children, key=lambda c: _straightness(c, cur.cell, incoming), reverse=True
        )
        branches.append((other, cur.cell))
        pts += _between(main, cur.cell)[1:]
        cur = main
    assert cur.leaf is not None and cur.approach is not None
    o, here_a = cur.leaf, cur.approach
    path = simplify([*pts, *here_a.tail[1:]])
    if parent is None:
        path, _ = shape45(path)
        pipe = Pipe(
            ctx.new_id("sewer"),
            "sewer",
            r.id,
            o.fixture,
            tuple(path),
            o.d,
            o.height,
            here_a.along + along,
            room=o.room,
        )
    else:
        path, attach = shape45(path, parent, along)
        pipe = Pipe(
            ctx.new_id("sewer"),
            "sewer",
            parent.id,
            o.fixture,
            tuple(path),
            o.d,
            o.height,
            here_a.along,
            parent=parent.id,
            attach=attach,
            room=o.room,
        )
    ctx.net.pipes.append(pipe)
    line = LineString([v.as_tuple() for v in pipe.path])
    for other, cell in branches:
        c = ctx.grid.center(cell)
        at = line.project(shapely.Point(c.as_tuple()))
        hit = line.interpolate(at)
        start = Vec(hit.x, hit.y)
        _emit(ctx, r, other, [start, *_between(other, cell)], pipe, at)


def _straightness(child: _Merge, cell: int, incoming: Vec | None) -> float:
    """How much the branch to child from the tee at cell continues the main: the cosine of the angle
    (1 means aligned); a zero-length branch (fixture at the tee) is a side branch."""
    path = _between(child, cell)
    if len(path) < 2 or incoming is None or incoming.length() < 1e-6:
        return -2.0
    d = path[1] - path[0]
    return d.dot(incoming) / (d.length() * incoming.length())


def equivalent_length(path: Sequence[Vec], d: int) -> float:
    """Pipe consumption in mm of equivalent length: weight per metre by diameter plus 45° bends."""
    return PIPE_WEIGHT[angle_norm(d)] * plan_length(path) + SEWER_BEND_COST * b45.bends(path)
