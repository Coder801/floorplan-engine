"""Water supply and sewer network from plumbing.yaml: fixture supplies, routes, checks.

Rules (docs/plumbing.md):
- routes run on the floor (water in the screed, sewer on the floor in a box), at right
  angles, around walls and obstacles (installation frame, bath, tray, box), through door
  openings, at least routing.CLEARANCE from walls, on the same grid as wiring;
- a pipe reaches a fixture on the floor at the nearest free spot by its wall, then continues
  in the wall: along it (wall_run) and up to the water outlet or drain (rise). This way the
  route goes around an installation frame and a bath: the mixer above a bath is reached from
  the side, in the wall;
- water is radial (collector, the default): each water outlet has its own Ø16 pipe from the
  cold or hot manifold in the supply unit; tee layout (tee, economy): a main from the supply
  unit, a branch to each fixture from the nearest point of the main; a pipe with branches is
  Ø20, end ones are Ø16. The hot manifold for a boiler sits at the boiler. In the radial
  layout, neighbours on one wall (a double vanity, a dishwasher by the sink: supply_groups)
  share one Ø16 pipe from the manifold per water, the second one via a tee at the first; a
  branch that runs alongside another for long, or is much shorter as a branch from it, is
  teed off it if the shared pipe can carry the flow (_merge_parallel). Hot water comes from
  a riser or from a boiler (the boiler takes cold from the manifold and feeds hot into the
  hot manifold or the main);
- the outlets of a pair: hot on the left, cold on the right (view from inside), HOT_COLD_GAP / 2
  from the middle of the supply;
- sewer (routing spec 2026-11-02) is a tree to the riser: WCs first (Ø110, only into the
  riser or a Ø110 pipe, branch no longer than WC_REACH), then the rest into the riser or a
  Ø50 pipe (the WC is closest to the riser). Its own grid: never through door openings or
  thresholds of living rooms, hidden zones (box, installation frame, under bath and tray,
  HIDDEN_HEIGHT) are preferred; the search goes in eight directions, corners only with 45°
  bends (plumbing/bends.py), branches join with an angled tee. Heights are computed backwards
  from the riser inlet, from the slab: one slope over the whole fixture route (SLOPE, down to
  SLOPE_MIN for Ø110), a higher drain means a drop in the wall. In the screed (SCREED_MM) the
  pipe bottom + Ø + SCREED_COVER must not exceed the screed, Ø110 is not allowed in the
  screed. What does not fit in the screed runs along the wall above the floor (zone surface:
  by the wall, in a box; change 2026-11-02): not an error but a note with the box height; in
  the screed only pieces in the middle of a room and through openings remain errors. Passes:
  normal, through hidden zones and only along walls; the pass with fewer errors wins
  (SewerError, routes in SewerRoute, JSON in routes_json);
- weak spots (Weak) go to the sheet and the report: screed, height drop, WC branch, sewer
  through a living room, many bends, unreachable fixture, no hot water.

Supply heights without data come from FIXTURE_SPECS (an assumption, "*" in the fixture table);
the riser inlet axis without data is SEWER_INLET_MM.
"""

from __future__ import annotations

from typing import Any

import shapely
from shapely.geometry import LineString

from floorplan_engine.electrical.routing import (
    free_area,
    opening_strip,
)
from floorplan_engine.model.geometry import (
    Contour,
    RoomGeometry,
    room_geometries,
)
from floorplan_engine.model.plumbing import (
    SEWER_INLET_MM,
    Fixture,
    Plumbing,
)
from floorplan_engine.model.schema import OpeningType, Plan
from floorplan_engine.plumbing.context import (
    Ctx,
    base_grid,
    door_strips,
    obstacle_polygon,
    partition_strips,
    riser_center,
    sewer_grid,
)
from floorplan_engine.plumbing.drain_merge import equivalent_length
from floorplan_engine.plumbing.network_model import TEXT, Network, Outlet, RiserNode, weak_spot
from floorplan_engine.plumbing.rules import (
    HIDDEN_HEIGHT,
    HOLLOW,
    HOT_COLD_GAP,
    SCREED_MM,
    SEWER_VARIANTS,
    SUPPLY_D,
    Kind,
)
from floorplan_engine.plumbing.sewer import route_sewer
from floorplan_engine.plumbing.supply import route_supply

__all__ = ["Network", "build_network", "fixture_outlets", "routes_json"]


def fixture_outlets(fx: Fixture, geoms: dict[str, RoomGeometry]) -> list[Outlet]:
    """Fixture supplies on its wall: hot on the left, cold on the right, drain in the middle."""
    spec = fx.spec
    seg = geoms[fx.room].contour.segment(fx.wall)
    supply_h = fx.supply_height if fx.supply_height is not None else spec.supply_height
    supply_assumed = fx.supply_height is None
    pair = spec.cold and (spec.hot or spec.hot_source)
    out: list[Outlet] = []

    def add(kind: Kind, offset: float, height: float, d: int, assumed: bool) -> None:
        offset = min(max(offset, 0.0), seg.length)
        out.append(
            Outlet(
                fx.id,
                kind,
                fx.room,
                fx.wall,
                offset,
                height,
                seg.point_at(offset),
                seg.inward,
                d,
                assumed,
            )
        )

    half = HOT_COLD_GAP / 2 if pair else 0.0
    if spec.hot or spec.hot_source:
        add("hot", fx.offset - half, supply_h, SUPPLY_D, supply_assumed)
    if spec.cold:
        add("cold", fx.offset + half, supply_h, SUPPLY_D, supply_assumed)
    if spec.sewer is not None:
        assert spec.drain_height is not None
        drain = fx.drain_height if fx.drain_height is not None else spec.drain_height
        add("sewer", fx.offset, drain, spec.sewer, fx.drain_height is None)
    return out


def build_network(plan: Plan, contours: dict[str, Contour], plumbing: Plumbing) -> Network:
    """Network from plumbing.yaml: supplies, manifolds, water and sewer routes, checks."""
    geoms = {g.room.id: g for g in room_geometries(plan, contours)}
    net = Network(distribution=plumbing.distribution)
    for ob in plumbing.obstacles:
        net.obstacles[ob.id] = obstacle_polygon(ob, geoms[ob.room])
    free = free_area(list(geoms.values()))
    rooms_only = free  # no partitions: their faces are walls too, sewer runs along them
    net.doors = door_strips(list(geoms.values()))
    net.partitions = partition_strips(list(geoms.values()), net.doors)
    net.under = partition_strips(list(geoms.values()), net.doors, inner=True)
    if net.partitions or net.under:
        free = shapely.make_valid(shapely.unary_union([free, *net.partitions, *net.under]))
    if net.obstacles:
        free = shapely.make_valid(
            free.difference(shapely.unary_union(list(net.obstacles.values())))
        )
    net.free = free
    boxes = {ob.id: ob.type in HOLLOW for ob in plumbing.obstacles}
    net.hollow = {k for k, v in boxes.items() if v}
    grid = base_grid(free, net)
    net.rooms = rooms_only
    for ob in plumbing.obstacles:
        if ob.type in HIDDEN_HEIGHT:
            h = ob.height if ob.height is not None else HIDDEN_HEIGHT[ob.type]
            net.hidden[ob.id] = (net.obstacles[ob.id], h)
    sewer_grids = tuple(sewer_grid(list(geoms.values()), net, v) for v in SEWER_VARIANTS)
    ctx = Ctx(plan, plumbing, geoms, grid, net, boxes, sewer_grids=sewer_grids)
    for r in plumbing.risers:
        inlet = r.sewer_inlet if r.sewer_inlet is not None else SEWER_INLET_MM
        net.risers.append(
            RiserNode(
                r.id, r.room, riser_center(r, geoms), r.sewer, r.water, inlet, r.sewer_inlet is None
            )
        )
    for fx in plumbing.fixtures:
        net.outlets += fixture_outlets(fx, geoms)
    route_supply(ctx)
    route_sewer(ctx)
    _check_doors(ctx)
    return net


def _check_doors(ctx: Ctx) -> None:
    """Water through a door opening is a weak spot (sewer through a door is impossible: its grid has
    no door openings)."""
    net = ctx.net
    names = {g.room.id: g.room.name for g in ctx.geoms.values()}
    seen: set[tuple[str, str, str]] = set()
    for p in net.pipes:
        if p.kind == "sewer" or not net.doors:
            continue
        line = LineString([v.as_tuple() for v in p.path])
        for g in ctx.geoms.values():
            for op in g.room.openings:
                if op.type is not OpeningType.DOOR:
                    continue
                if line.intersection(opening_strip(g, op)).length < 1.0:
                    continue
                key = (p.target, p.kind, op.id)
                if key in seen:
                    continue
                seen.add(key)
                net.weak.append(
                    weak_spot(
                        "warning",
                        "door_water",
                        p.target,
                        f=ctx.name(p.target),
                        k=TEXT[f"kind_{p.kind}"],
                        room=names[g.room.id],
                    )
                )


def routes_json(net: Network) -> dict[str, Any]:
    """Sewer routes in the routing spec format (out/sewer-routes.json): per fixture the diameter,
    slope, drop in the wall, parts along the flow with their zone (z is the pipe bottom, mm from
    the slab), fittings of its own pipe; errors with their place on the plan (model mm). Totals:
    totalLength is mm of all sewer pipes (on the floor, in walls, drops), totalFittings the number
    of fittings, savingVsDirect the mm of equivalent length (PIPE_WEIGHT, SEWER_BEND_COST) saved
    by tees compared with connecting each Ø50 fixture separately."""
    sewer = net.pipes_of("sewer")
    small = [p for p in sewer if p.d < 100]
    saving = net.sewer_direct - sum(equivalent_length(p.path, p.d) for p in small) if small else 0.0
    return {
        "screed": SCREED_MM,
        "totalLength": round(sum(p.total for p in sewer), 1),
        "totalFittings": sum(len(r.fittings) for r in net.routes),
        "savingVsDirect": round(saving, 1),
        "routes": [
            {
                "fixture": r.fixture,
                "diameter": r.d,
                "slope": r.slope,
                "verticalDrop": {"from": r.drop[0], "to": r.drop[1]} if r.drop else None,
                "segments": [
                    {"from": list(s.start), "to": list(s.end), "zone": s.zone, "length": s.length}
                    for s in r.segments
                ],
                "fittings": list(r.fittings),
                "into": r.into,
                "ok": r.ok,
            }
            for r in net.routes
        ],
        "errors": [
            {
                "fixture": e.fixture,
                "reason": e.reason,
                "at": [round(e.at.x, 1), round(e.at.y, 1)] if e.at is not None else None,
            }
            for e in net.sewer_errors
        ],
    }
