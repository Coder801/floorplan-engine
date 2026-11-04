"""Sewer tree to the riser: passes with different cell costs, the pass with fewer errors wins."""

from __future__ import annotations

import math

from floorplan_engine.plumbing.context import Ctx, best_approach, height_prune
from floorplan_engine.plumbing.drain_merge import merge_drains
from floorplan_engine.plumbing.network_model import Network, Outlet, RiserNode, weak_spot
from floorplan_engine.plumbing.pipe_search import riser_fields, riser_invert, route_tree
from floorplan_engine.plumbing.rules import SLOPE_MIN, TURN_COST_MM
from floorplan_engine.plumbing.sewer_heights import sewer_heights

DEPTH_ERRORS = frozenset({"screed_depth", "screed_110", "hidden_height"})


def route_sewer(ctx: Ctx) -> None:
    """Sewer in variants (SEWER_VARIANTS): normal, through hidden zones, only along walls; the
    variant with the lowest sewer_score wins (routing spec, item 6)."""
    net = ctx.net
    if not any(o.kind == "sewer" for o in net.outlets):
        return
    water = ctx.grid
    mark = (len(net.pipes), len(net.weak), dict(ctx.counter))
    ctx.ndirs, ctx.boxes_open = 8, True
    try:
        best: tuple[SewerScore, int] | None = None
        for k, grid in enumerate(ctx.sewer_grids):
            _rollback(ctx, mark)
            ctx.grid = grid
            _sewer_trees(ctx)
            score = sewer_score(net)
            if best is None or score < best[0]:
                best = (score, k)
            if score[:4] == (0, 0, 0.0, 0.0):
                break  # no errors, no podium, no box, no room middle
        if best is not None and best[1] != k:
            _rollback(ctx, mark)
            ctx.grid = ctx.sewer_grids[best[1]]
            _sewer_trees(ctx)
    finally:
        ctx.grid, ctx.ndirs, ctx.boxes_open, ctx.prune = water, 4, False, None


SewerScore = tuple[int, int, float, float, float]


def sewer_score(net: Network) -> SewerScore:
    """Sewer variant score, compared in order: screed and hidden zone errors, podiums (not enough
    drop), mm of box above the floor, mm in the middle of a room (farther than WALL_BAND_MM from
    walls outside hidden zones), mm of pipe plus bends at TURN_COST_MM."""
    sewer = net.pipes_of("sewer")
    fittings = sum(f == "bend45" for r in net.routes for f in r.fittings)
    return (
        sum(1 for e in net.sewer_errors if e.reason in DEPTH_ERRORS),
        sum(1 for e in net.sewer_errors if e.reason in ("drop", "unreachable")),
        round(sum(p.surface_length for p in sewer), 1),
        round(sum(p.open_length for p in sewer), 1),
        round(sum(p.total for p in sewer) + fittings * TURN_COST_MM, 1),
    )


def _rollback(ctx: Ctx, mark: tuple[int, int, dict[str, int]]) -> None:
    pipes, weak, counter = mark
    net = ctx.net
    del net.pipes[pipes:]
    del net.weak[weak:]
    net.sewer.clear()
    net.routes.clear()
    net.sewer_errors.clear()
    net.sewer_direct = 0.0
    ctx.counter = dict(counter)


def _sewer_trees(ctx: Ctx) -> None:
    net = ctx.net
    drains = [o for o in net.outlets if o.kind == "sewer"]
    risers = [r for r in net.risers if r.sewer]
    if not risers:
        net.weak.append(weak_spot("error", "no_riser", ""))
        return
    # A fixture goes to the riser with the shorter path; each riser has its own tree
    fields = {r.id: [f for _, f in riser_fields(ctx, r, 50)] for r in risers}

    def cost(r: RiserNode, o: Outlet) -> float:
        options = ctx.wall_approaches(o.room, o.wall, o.offset)
        out = math.inf
        for fld in fields[r.id]:
            a = best_approach(fld, options)
            if a is not None:
                out = min(out, fld.cost(a.cell))
        return out

    by_riser: dict[str, list[Outlet]] = {r.id: [] for r in risers}
    for o in drains:
        r = min(risers, key=lambda r: (cost(r, o), (r.center - o.node).length()))
        by_riser[r.id].append(o)
    for r in risers:
        mine = by_riser[r.id]
        if not mine:
            continue
        wc = [o for o in mine if o.d >= 110]
        rest = [o for o in mine if o.d < 110]
        # Ø110 never fits in the screed: the room middle is closed at any length
        ctx.prune = height_prune(ctx.grid, riser_invert(r), SLOPE_MIN[110], 110)
        route_tree(ctx, "sewer", r.id, r, wc, only_into=110)
        ctx.prune = None
        merge_drains(ctx, r, rest)
    sewer_heights(ctx)
