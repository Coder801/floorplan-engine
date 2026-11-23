"""Routes of the wiring lines: the search for every link, in rounds, and the rules on top of it.

- routes run at right angles around walls (the same path as on the sheet): on the ceiling,
  or for a group with route: floor in the floor screed; at least routing.CLEARANCE (150 mm)
  from walls, except the approach to a wall point and the pass through an opening; in
  economy at any angle;
- lines are routed one after another, in a fixed order (decision 2026-11-23, route_runs),
  because a line that crosses a wall or an opening band leaves a hole the next lines of its
  plane and circuit go through for free (routing.Router holes, within WALL_HOLE_SHARE);
- a box on the ceiling (floor) with 2 to ONE_SIDE_MAX cables takes them all from one side
  (decision 2026-11-18, _one_side): they leave it together, straight, for BOX_LEAD_MM and part
  only there, so the cables lie evenly; boxes with more cables keep their routes;
- internet and TV apart from power (decision 2026-11-13, apart, routing.apart_cells): on the
  ceiling and on the floor such a cable runs no closer than routing.APART (150 mm) beside a
  power cable and crosses it at 90°. It is routed after the power lines (with their manual
  routes), so it goes round them; it comes closer only where there is no other way (a socket
  block, a narrow corridor). Within routing.PANEL_FREE (300 mm) of the panel neither the
  distance nor the 90° crossing applies (decision 2026-11-18). A 12 V LED line is not held
  apart; a manual route of the cable itself stays as drawn; at any angle (economy) the rule is
  not applied;
- manual edits (wiring.yaml, from the viewer, manual_runs): a line with a manual route follows
  it, its ends snapped to the source and target nodes at right angles. An edit whose id now
  means another line is not applied (edit_notes);
- a drop never crosses an opening (detours.py, Context.drop): to a point under a window the
  cable goes down beside the window and turns at 90° along the wall to the point; the route on
  the ceiling ends at the drop, the turn is part of the rise (_turn).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from floorplan_engine.electrical import trace
from floorplan_engine.electrical.anchors import Anchor
from floorplan_engine.electrical.boxes import anchor_end
from floorplan_engine.electrical.routing import (
    WALL_HOLE_SHARE,
    Crossing,
    End,
    Router,
    crossings,
    fit_path,
    is_ortho,
    length,
    room_area,
)
from floorplan_engine.electrical.wiring_context import END_ALLOWANCE, Context, Link
from floorplan_engine.electrical.wiring_model import Circuit, JunctionBox, Route, Run
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.schema import WireEdit

# A box on the ceiling (floor) with this many cables or fewer takes them all from one side
# (decision 2026-11-18, _one_side): they leave it together, straight, for BOX_LEAD_MM
ONE_SIDE_MAX = 3
BOX_LEAD_MM = 150.0
SIDES = (Vec(1.0, 0.0), Vec(0.0, 1.0), Vec(-1.0, 0.0), Vec(0.0, -1.0))

Drop = tuple[Anchor, float]  # the route end beside an opening and the wall offset of the drop


def _comms(circuit: Circuit, led: bool) -> bool:
    """Internet and TV: low voltage, but not a 12 V LED line."""
    return circuit == "low" and not led


def _lay(ln: Link) -> Circuit:
    """Circuit the line is laid with (Run.lay): power with the 12 V LED lines, low voltage apart."""
    return "power" if ln.led else ln.circuit


def apart(
    ctx: Context,
    links: Sequence[Link],
    boxes: Sequence[JunctionBox],
    runs: Sequence[Run],
    edited: set[str],
) -> list[Run]:
    """Internet and TV lines routed again, apart from the final power routes (decision
    2026-11-13, routing.apart_cells); a line with a manual route stays as it is."""
    power = [r for r in runs if r.circuit == "power"]
    if ctx.any_angle or not power or not any(_comms(r.circuit, r.led) for r in runs):
        return list(runs)
    again = {r.id: r for r in route_runs(ctx, links, boxes, power)}
    return [r if f"wire:{r.id}" in edited else again.get(r.id, r) for r in runs]


def manual_runs(
    runs: Sequence[Run],
    wires: dict[str, WireEdit],
    free: BaseGeometry,
    edited: set[str],
    notes: list[tuple[str, str]],
    any_angle: bool,
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


def route_runs(
    ctx: Context,
    links: Sequence[Link],
    boxes: Sequence[JunctionBox],
    beside: Sequence[Run] | None = None,
) -> list[Run]:
    """Line routes: from the panel through the whole flat, from a box or a socket of a daisy chain
    only inside its room. A wall point past an opening is reached where its drop goes down
    beside the opening (Context.drop); the turn to the point adds to the rise. With beside (the
    power lines already routed) only the internet and TV lines are routed, apart from the power
    routes of their plane (apart); the line ids are the same.

    Lines are routed one after another in a fixed order (decision 2026-11-23), because a line
    that crosses a wall or an opening band leaves a hole the next lines of its plane and circuit
    go through for free (routing.Router holes, within WALL_HOLE_SHARE): by source, the panel first,
    then the low-voltage cabinet, the boxes in their order, then the points of chains by id
    (_source_rank); within a source the farthest target first by the search cost with the holes
    made before the source began (not by its own lines: the order is fixed when the source
    starts), equal costs by line number. So the line that has to pay a new hole goes first and
    the nearer ones follow it into that hole; a line that already has a ready hole on its way is
    near, whatever it would have paid without it. At equal length a line prefers a hole made by
    its own source (Router own), so the cables of one box or flush box leave it together. The
    order changes only which line pays the pass, not the ids: wire_{k + 1} is the k-th link, as
    before. A router is searched again only when the holes of its plane and circuit have changed
    since its last line (_LineRouters.current); a hole within WALL_HOLE_SHARE of one already made
    is the same hole and changes nothing."""
    todo = [(k, ln) for k, ln in enumerate(links) if beside is None or _comms(ln.circuit, ln.led)]
    routers = _LineRouters(ctx, links, boxes, beside)
    rank = _source_rank(boxes, {ln.source for _, ln in todo})

    def order(item: tuple[int, Link]) -> tuple[float, int]:
        k, ln = item
        return 0.0 if ln.wall else -routers.current(ln).cost(routers.target_of(ln)[0].node), k

    by_source: dict[str, list[tuple[int, Link]]] = {}
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
        router = routers.current(ln)
        target, end = routers.target_of(ln)
        start = routers.drops.get((ln.source, ln.route)) if ln.source_rise > 0 else None
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
            routers.note_holes(ln, path, router.bands)
        found[k] = (_run_of(ctx, k, ln, path, start, end), None if ln.wall else (router, target))
    runs = [found[k][0] for k, _ in todo]
    ways = [found[k][1] for k, _ in todo]  # each run's router and target, for _one_side
    return _one_side(boxes, runs, ways) if beside is None else runs


def _source_rank(boxes: Sequence[JunctionBox], sources: set[str]) -> dict[str, int]:
    """Routing order of the sources: the panel, the cabinet, the boxes, the points of chains."""
    rank = {"board": 0, "media": 1, **{b.id: 2 + k for k, b in enumerate(boxes)}}
    rest = sorted(sources - set(rank))
    return rank | {src: len(rank) + k for k, src in enumerate(rest)}


def _run_of(
    ctx: Context, k: int, ln: Link, path: tuple[Vec, ...], start: Drop | None, end: Drop | None
) -> Run:
    """The routed line: its path, the rises with the turns from the drops beside openings, the
    tails at both ends."""
    return Run(
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


def _turn(ctx: Context, pid: str, spot: Drop | None) -> float:
    """Along the wall from a drop beside an opening to the point, mm; 0 without one."""
    p = ctx.points.get(pid)
    if spot is None or p is None or p.offset is None:
        return 0.0
    return abs(spot[1] - p.offset)


@dataclass
class _LineRouters:
    """Routers of the lines of one routing round, by source and plane: the panel and the cabinet
    through the whole flat, a box or a chain point inside its room (or through the flat via the
    openings for a branch behind a door), with the holes made so far on the plane and circuit."""

    ctx: Context
    links: Sequence[Link]
    boxes: Sequence[JunctionBox]
    beside: Sequence[Run] | None  # the power lines already routed: the apart stage
    drops: dict[tuple[str, Route], Drop] = field(init=False)
    routes: dict[str, Route] = field(init=False)  # plane of each source
    box_anchors: dict[str, Anchor] = field(init=False)
    box_rooms: dict[str, str] = field(init=False)
    beside_paths: dict[Route, list[tuple[Vec, ...]]] = field(init=False)
    plain: dict[tuple[str, Route, bool], Router] = field(default_factory=dict)  # no holes
    opened: dict[tuple[str, Route, bool, Circuit, int], Router] = field(default_factory=dict)
    holes: dict[tuple[Route, Circuit], list[tuple[Crossing, str]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ctx, links = self.ctx, self.links
        self.routes = {ln.source: ln.route for ln in links}
        self.drops = {
            (pid, route): spot
            for ln in links
            for pid, route, rise in (
                (ln.source, ln.route, ln.source_rise),
                (ln.target, ln.route, ln.target_rise),
            )
            if rise > 0 and (spot := ctx.drop(pid, route)) is not None
        }
        self.box_anchors = {b.id: b.anchor for b in self.boxes}
        self.box_rooms = {b.id: b.room for b in self.boxes}
        self.beside_paths = {"ceiling": [], "floor": []}
        for r in self.beside or ():
            self.beside_paths[r.route].append(r.path)

    def source_anchor(self, src: str) -> Anchor:
        spot = self.drops.get((src, self.routes[src]))
        return spot[0] if spot is not None else self.ctx.anchors[src]

    def router_of(self, src: str, plane: Route, wide: bool) -> Router:
        """Router of the source on the plane without ready holes: the panel and the cabinet
        through the whole flat; a box or a chain point inside its room, or through the whole flat
        via the openings for a branch to a switch behind a door and a light chain into the next
        room (wide); in the apart stage, kept off the power routes of the plane."""
        key = (src, plane, wide)
        if key in self.plain:
            return self.plain[key]
        ctx, box_anchors = self.ctx, self.box_anchors
        if src in ("board", "media"):
            router = ctx.from_source(src, plane)
        elif wide:
            end = anchor_end(box_anchors.get(src) or self.source_anchor(src))
            router = ctx.flat_router(end, plane)
        elif src in box_anchors:
            router = Router(room_area(ctx.geoms[self.box_rooms[src]]), anchor_end(box_anchors[src]),
                            ctx.any_angle)  # fmt: skip
        else:  # a daisy chain
            area = room_area(ctx.geoms[ctx.rooms[src]])
            router = Router(area, anchor_end(self.source_anchor(src)), ctx.any_angle)
        if self.beside is not None:
            # No APART within PANEL_FREE of the panel
            router = router.apart_from(self.beside_paths[plane], ctx.board_end.node)
        self.plain[key] = router
        return router

    def target_of(self, ln: Link) -> tuple[End, Drop | None]:
        end = self.drops.get((ln.target, ln.route)) if ln.target_rise > 0 else None
        return anchor_end(end[0] if end else ln.target_anchor), end

    def current(self, ln: Link) -> Router:
        """The line's router with the holes made so far on its plane and circuit; searched again
        only when they changed since the last line of this source."""
        wide = ln.source not in ("board", "media") and ln.cross
        made = self.holes.setdefault((ln.route, _lay(ln)), [])
        key = (ln.source, ln.route, wide, _lay(ln), len(made))
        router = self.opened.get(key)
        if router is None:
            own = [c for c, src in made if src == ln.source]
            router = self.router_of(ln.source, ln.route, wide).with_holes([c for c, _ in made], own)
            self.opened[key] = router
        return router

    def note_holes(self, ln: Link, path: tuple[Vec, ...], bands: Sequence[Polygon]) -> None:
        """The bands the routed line crosses are holes for the next lines of its plane and
        circuit; one within WALL_HOLE_SHARE of a hole already made is the same hole."""
        made = self.holes[(ln.route, _lay(ln))]
        for a, b in crossings(path, bands):
            mid = (a + b) * 0.5
            if all(((c + d) * 0.5 - mid).length() >= WALL_HOLE_SHARE for (c, d), _ in made):
                made.append(((a, b), ln.source))


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
