"""Sewer heights from the slab: slope per fixture route, screed, hidden zones, weak spots."""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

import shapely
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from floorplan_engine.electrical.routing import (
    STEP,
    opening_strip,
)
from floorplan_engine.model.geometry import (
    Vec,
    point_in_polygon,
)
from floorplan_engine.model.plumbing import (
    FixtureType,
    ObstacleType,
)
from floorplan_engine.model.schema import OpeningType
from floorplan_engine.plumbing.context import Ctx, is_living
from floorplan_engine.plumbing.network_model import (
    Pipe,
    RouteSegment,
    SewerCheck,
    SewerError,
    SewerRoute,
    Weak,
    Zone,
    drop_bends,
    metres,
    weak_spot,
)
from floorplan_engine.plumbing.pipe_search import angle_norm, plan_length, riser_invert
from floorplan_engine.plumbing.rules import (
    SCREED_COVER,
    SCREED_MM,
    SEWER_BENDS,
    SLOPE,
    SLOPE_MAX,
    SLOPE_MIN,
    WALL_BAND_MM,
    WC_REACH,
)

HIDDEN_NAMES: dict[ObstacleType, dict[str, str]] = {
    ObstacleType.INSTALLATION: {"ru": "инсталляция", "uk": "інсталяція"},
    ObstacleType.BOX: {"ru": "короб", "uk": "короб"},
    ObstacleType.BATH: {"ru": "под ванной", "uk": "під ванною"},
    ObstacleType.SHOWER_TRAY: {"ru": "под поддоном", "uk": "під піддоном"},
}
SAMPLE = 25.0  # mm: step for splitting a route piece into zones


@dataclass(frozen=True)
class Zones:
    """Where a sewer route point lies: a hidden zone, the screed (floor) or a wall; on the floor
    also whether it is by a wall (the WALL_BAND_MM band along walls and obstacles, without
    openings): there a pipe that does not fit the screed runs along the wall above the floor."""

    hidden: tuple[tuple[str, BaseGeometry, float], ...]  # obstacle, place, top height
    floor: BaseGeometry
    edge: BaseGeometry
    walls: BaseGeometry  # wall and obstacle faces: the room middle is farther than WALL_BAND_MM

    @classmethod
    def of(cls, ctx: Ctx) -> Zones:
        net = ctx.net
        assert net.rooms is not None
        hidden = tuple((oid, poly.buffer(1.0), h) for oid, (poly, h) in net.hidden.items())
        for _, g, _ in hidden:
            shapely.prepare(g)
        floor = net.rooms.buffer(-1.0)
        walls = net.rooms
        if net.obstacles:
            walls = walls.difference(shapely.unary_union(list(net.obstacles.values())))
        # The route band by walls (grid) plus a step: a corner cut by 45° bends is also by the wall
        edge = walls.boundary.buffer(WALL_BAND_MM + STEP)
        # A pipe is not run through an opening (door, arch) above the floor: people walk there
        openings = [
            opening_strip(g, op)
            for g in ctx.geoms.values()
            for op in g.room.openings
            if op.type is not OpeningType.WINDOW
        ]
        if openings:
            edge = edge.difference(shapely.unary_union(openings).buffer(1.0))
        line = walls.boundary
        for geom in (floor, edge, line):
            shapely.prepare(geom)
        return cls(hidden, floor, edge, line)

    def open_room(self, v: Vec) -> bool:
        """In the middle of a room: farther than WALL_BAND_MM from walls (hidden zones do not
        count).
        """
        return self.walls.distance(shapely.Point(v.as_tuple())) > WALL_BAND_MM + 1.0

    def at(self, v: Vec, z: float, d: int) -> tuple[Zone, str, float]:
        """Zone of a route point; z is the pipe bottom from the slab, d its Ø."""
        p = shapely.Point(v.as_tuple())
        for oid, g, h in self.hidden:
            if g.contains(p):
                return "hidden", oid, h
        if not self.floor.contains(p):
            return "wall", "", 0.0
        fits = d < 100 and z <= SCREED_MM - d - SCREED_COVER + 0.5
        if not fits and self.edge.contains(p):
            return "surface", "", 0.0
        return "screed", "", 0.0


@dataclass(frozen=True)
class _Piece:
    """Route part in one zone, along the flow; s is mm along the route from the fixture to its
    start.
    """

    a: Vec
    za: float
    b: Vec
    zb: float
    zone: Zone
    obstacle: str
    height: float
    s: float


def _upto(path: Sequence[Vec], s: float) -> list[tuple[Vec, float]]:
    """Polyline points from the start up to s mm along it, and the distance of each from the
    start.
    """
    out = [(path[0], 0.0)]
    acc = 0.0
    for a, b in itertools.pairwise(path):
        n = (b - a).length()
        if acc + n >= s - 1e-6:
            if n > 1e-9:
                out.append((a + (b - a) * ((s - acc) / n), s))
            return out
        acc += n
        out.append((b, acc))
    return out


def _flow(pipes: dict[str, Pipe], p: Pipe) -> list[tuple[Vec, float]]:
    """Fixture route along the flow, from the drain on the floor to the riser: points and pipe
    bottom.
    """
    out: list[tuple[Vec, float]] = []
    cur, end = p, plan_length(p.path)
    while True:
        part = [(v, cur.z0 + s * cur.slope) for v, s in reversed(_upto(cur.path, end))]
        out += part[1:] if out else part
        if cur.parent is None:
            return out
        cur, end = pipes[cur.parent], cur.attach


def _pieces(zones: Zones, flow: Sequence[tuple[Vec, float]], d: int) -> list[_Piece]:
    out: list[_Piece] = []
    s = 0.0
    for (a, za), (b, zb) in itertools.pairwise(flow):
        n = (b - a).length()
        if n < 1e-6:
            continue
        k = max(1, math.ceil(n / SAMPLE))
        for i in range(k):
            t0, t1 = i / k, (i + 1) / k
            pa, pb = a + (b - a) * t0, a + (b - a) * t1
            z0, z1 = za + (zb - za) * t0, za + (zb - za) * t1
            zone, oid, h = zones.at(a + (b - a) * ((t0 + t1) / 2), max(z0, z1), d)
            last = out[-1] if out else None
            straight = last is not None and (last.b - pa).length() < 1e-6 and i > 0
            if last is not None and straight and (last.zone, last.obstacle) == (zone, oid):
                out[-1] = replace(last, b=pb, zb=z1)
            else:
                out.append(_Piece(pa, z0, pb, z1, zone, oid, h, s + n * t0))
        s += n
    return out


def _room_at(ctx: Ctx, v: Vec) -> str:
    for g in ctx.geoms.values():
        if point_in_polygon(v, g.contour.vertices):
            return g.room.name
    g = min(
        ctx.geoms.values(),
        key=lambda g: Polygon([u.as_tuple() for u in g.contour.vertices]).distance(
            shapely.Point(v.as_tuple())
        ),
    )
    return g.room.name


@dataclass(frozen=True)
class _Eval:
    pipe: Pipe
    route: SewerRoute
    check: SewerCheck
    errors: tuple[tuple[SewerError, Weak], ...]


def _evaluate(ctx: Ctx, zones: Zones, pipes: dict[str, Pipe], p: Pipe) -> _Eval:
    """Fixture route with a given slope and start: parts by zone, the drop in the wall, checks of
    screed, hidden zones, drop and WC branch."""
    net = ctx.net
    outlet = next(o for o in net.outlets if o.fixture == p.target and o.kind == "sewer")
    flow = _flow(pipes, p)
    total = sum((b - a).length() for (a, _), (b, _) in itertools.pairwise(flow))
    root = p
    while root.parent is not None:
        root = pipes[root.parent]
    riser = next(r for r in net.risers if r.id == root.source)
    name = ctx.name(p.target)
    errors: list[tuple[SewerError, Weak]] = []
    seen: set[str] = set()

    def error(reason: str, at: Vec | None, **values: object) -> None:
        if reason in seen:
            return
        seen.add(reason)
        weak = weak_spot("error", reason, p.target, f=name, **values)
        errors.append((SewerError(p.target, reason, at), weak))

    pieces = _pieces(zones, flow, p.d)
    for piece in pieces:
        if piece.zone == "screed" and p.d >= 100:
            at = (piece.a + piece.b) * 0.5
            error("screed_110", at, room=_room_at(ctx, at), L=metres(total - piece.s))
        elif piece.zone == "screed":
            limit = SCREED_MM - p.d - SCREED_COVER
            if piece.za > limit + 0.5:
                error(
                    "screed_depth",
                    piece.a,
                    d=p.d,
                    s=f"{SCREED_MM:g}",
                    z=round(piece.za),
                    lim=round(limit),
                    c=f"{SCREED_COVER:g}",
                    room=_room_at(ctx, piece.a),
                    L=metres(total - piece.s),
                )
        elif piece.zone == "hidden":
            top = piece.za + p.d - SCREED_MM
            if top > piece.height + 0.5:
                kind = next(ob.type for ob in ctx.plumbing.obstacles if ob.id == piece.obstacle)
                error(
                    "hidden_height",
                    piece.a,
                    zone=HIDDEN_NAMES[kind],
                    z=round(top),
                    max=f"{piece.height:g}",
                )
    z_end = flow[0][1]
    z_outlet = SCREED_MM + outlet.height - p.d / 2
    check = SewerCheck(
        p.target,
        riser.id,
        total,
        outlet.height,
        p.slope,
        p.d,
        riser.inlet,
        riser.inlet_assumed,
        root.z0,
        z_end,
        z_outlet,
    )
    if not check.ok:
        error(
            "drop",
            outlet.node,
            L=metres(total),
            i=f"{p.slope:g}".replace(".", ","),
            d=round(check.drop),
            h=f"{outlet.height:g}",
            r=f"{riser.inlet:g}",
            p=round(check.podium),
        )
    fx = next(f for f in ctx.plumbing.fixtures if f.id == p.target)
    if fx.type in (FixtureType.WC, FixtureType.WC_INSTALLATION) and total > WC_REACH + 0.5:
        error("wc_far", outlet.node, L=metres(total))
    rise = max(0.0, z_outlet - z_end)
    own = plan_length(p.path)
    surface, surface_top = _surface(pieces, own, p.d)
    open_length = sum(
        min(x.s + (x.b - x.a).length(), own) - x.s
        for x in pieces
        if x.zone == "screed" and x.s < own and zones.open_room((x.a + x.b) * 0.5)
    )
    fittings = ["bend45"] * (drop_bends(rise) + p.bends) + ["tee45"]
    segments = tuple(
        RouteSegment(
            (round(x.a.x, 1), round(x.a.y, 1), round(x.za, 1)),
            (round(x.b.x, 1), round(x.b.y, 1), round(x.zb, 1)),
            x.zone,
            round((x.b - x.a).length(), 1),
        )
        for x in pieces
    )
    route = SewerRoute(
        p.target,
        p.d,
        p.slope,
        (round(z_outlet, 1), round(z_end, 1)) if rise > 0.5 else None,
        segments,
        tuple(fittings),
        p.parent or p.source,
        not errors,
    )
    pipe = replace(p, rise=rise, surface=surface, surface_top=surface_top, open_length=open_length)
    return _Eval(pipe, route, check, tuple(errors))


def _surface(
    pieces: Sequence[_Piece], own: float, d: int
) -> tuple[tuple[tuple[float, float], ...], float]:
    """Parts of its own pipe along the wall above the floor, in mm from the start of its path (own
    is
    the path length; route parts are counted from the fixture), and the pipe top above the
    finished floor there."""
    spans: list[tuple[float, float]] = []
    top = 0.0
    for x in pieces:
        if x.zone != "surface" or x.s >= own:
            continue
        end = min(x.s + (x.b - x.a).length(), own)
        a, b = own - end, own - x.s
        if spans and abs(spans[-1][0] - b) < 1.0:
            spans[-1] = (a, spans[-1][1])
        else:
            spans.append((a, b))
        top = max(top, max(x.za, x.zb) + d - SCREED_MM)
    return tuple(sorted(spans)), top


def sewer_heights(ctx: Ctx) -> None:
    """Sewer heights computed backwards from the riser inlet (from the slab), all as pipe bottom:
    each pipe has a slope and a bottom at its start; a branch starts on the parent pipe with its
    bottom flush with the parent's (a 110×50 tee: the branch bottom is not below the main's).
    One slope per pipe, from a list (routing spec, item 5): SLOPE; if the route fails with it,
    SLOPE_MIN (Ø110, no branches); if it passes, SLOPE_MAX when the route has no branches off it,
    the parent slope is not smaller and the box above the floor and the room middle do not grow
    (the main is not flatter than its branches)."""
    net = ctx.net
    pipes = {p.id: p for p in net.pipes if p.kind == "sewer"}
    if not pipes:
        return
    zones = Zones.of(ctx)
    risers = {r.id: r for r in net.risers}
    parents = {p.parent for p in pipes.values() if p.parent is not None}
    order = [p.id for p in net.pipes if p.kind == "sewer"]  # the parent is laid before the branch
    results: dict[str, _Eval] = {}
    for pid in order:
        p = pipes[pid]
        cap = SLOPE_MAX
        if p.parent is None:
            z0 = riser_invert(risers[p.source])
        else:
            parent = pipes[p.parent]
            z0 = parent.z0 + p.attach * parent.slope
            cap = parent.slope
        d = angle_norm(p.d)
        leaf = pid not in parents

        def run(slope: float, p: Pipe = p, z0: float = z0, pid: str = pid) -> _Eval:
            pipes[pid] = replace(p, slope=slope, z0=z0)
            return _evaluate(ctx, zones, pipes, pipes[pid])

        best = run(min(SLOPE[d], cap))
        if best.errors and leaf and SLOPE_MIN[d] < best.pipe.slope:
            low = run(SLOPE_MIN[d])
            if len(low.errors) < len(best.errors):
                best = low
        elif not best.errors and leaf and cap + 1e-9 >= SLOPE_MAX:
            steep = run(SLOPE_MAX)
            no_worse = (
                steep.pipe.surface_length <= best.pipe.surface_length + 0.5
                and steep.pipe.open_length <= best.pipe.open_length + 0.5
            )
            if not steep.errors and no_worse:
                best = steep
        pipes[pid] = best.pipe
        results[pid] = best
    for k, p in enumerate(net.pipes):
        if p.id in pipes:
            net.pipes[k] = pipes[p.id]
    for pid in order:
        res = results[pid]
        net.sewer.append(res.check)
        net.routes.append(res.route)
        for err, weak in res.errors:
            net.sewer_errors.append(err)
            net.weak.append(weak)
        _sewer_warnings(ctx, pipes[pid])


def _sewer_warnings(ctx: Ctx, p: Pipe) -> None:
    """Pipe warnings: many bends (cleanout), through a living room."""
    net = ctx.net
    name = ctx.name(p.target)
    fx = next(f for f in ctx.plumbing.fixtures if f.id == p.target)
    if p.surface_length > 1.0:
        net.weak.append(
            weak_spot(
                "warning",
                "surface",
                p.target,
                f=name,
                L=metres(p.surface_length),
                h=round(p.surface_top),
            )
        )
    if p.bends > SEWER_BENDS:
        net.weak.append(weak_spot("warning", "turns", p.target, f=name, n=p.bends))
    line = LineString([v.as_tuple() for v in p.path])
    for g in ctx.geoms.values():
        if not is_living(g.room) or g.room.id == fx.room:
            continue
        inside = line.intersection(Polygon([v.as_tuple() for v in g.contour.vertices]))
        if inside.length > 1.0:
            net.weak.append(weak_spot("warning", "living", p.target, f=name, room=g.room.name))
