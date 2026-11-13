"""Chases and holes: cable drops and rises along walls to points and boxes (shared ones in one
chase, a wider one above CHASE_NARROW cables), cable channels, cable passes through door
openings and through drillable walls."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace

from shapely.geometry import LineString, Point, Polygon

from floorplan_engine.electrical.routing import (
    opening_strip,
)
from floorplan_engine.electrical.wiring_model import (
    Chase,
    ChaseKey,
    Circuit,
    Hole,
    JunctionBox,
    Route,
    Run,
)
from floorplan_engine.model.geometry import RoomGeometry
from floorplan_engine.model.schema import (
    Board,
    CableChannel,
    Conduit,
    ElectricalPoint,
    LoopConduit,
    OpeningType,
    Plan,
)

CHASE_SHARE = 150.0  # mm along the wall: closer drops share a chase
CHASE_CABLES = 4  # cables per chase, at most
WALL_HOLE_SHARE = 300.0  # mm: lines crossing a wall closer than this share a hole

# A drop to a point: wall offset, rise, point id, turn past an opening (offset and height)
_Drop = tuple[float, float, str, tuple[float, float] | None]


def wall_chases(
    runs: Sequence[Run],
    points: Sequence[ElectricalPoint],
    board: Board | None,
    boxes: Sequence[JunctionBox],
    media: Board | None = None,
) -> tuple[Chase, ...]:
    """Wall chases: shared by drops close together (CHASE_SHARE), up to CHASE_CABLES cables. A
    drop beside an opening (Run.end_drop, start_drop) is at its own spot and turns along the
    wall to the point (Chase.bend)."""
    by_id = {p.id: p for p in points}
    drops: dict[ChaseKey, list[_Drop]] = defaultdict(list)
    for r in runs:
        # In a daisy chain the line also leaves a point: a second cable in its chase
        for end, rise, at in (
            (r.target, r.rise_end_mm, r.end_drop),
            (r.source, r.rise_start_mm, r.start_drop),
        ):
            p = by_id.get(end)
            if rise <= 0 or p is None or p.wall is None or p.offset is None:
                continue
            bend = None if at is None or p.height is None else (p.offset, p.height)
            drops[(p.room, p.wall, r.route, r.lay)].append(
                (p.offset if at is None else at, rise, p.id, bend)
            )
    out: list[Chase] = []
    for key, items in sorted(drops.items()):
        group: list[_Drop] = []
        for item in sorted(items):
            if group and (item[0] - group[0][0] > CHASE_SHARE or len(group) == CHASE_CABLES):
                # A chain point's cable in and cable out stay in one chase (they may share a
                # conduit, with_conduit): a full chase hands the first of the pair on
                carry = group.pop() if len(group) > 1 and group[-1][2] == item[2] else None
                out.append(_shared(key, group))
                group = [carry] if carry is not None else []
            group.append(item)
        out.append(_shared(key, group))

    def bundle(kind: str, room: str, wall: str, offset: float, source: str) -> None:
        for same in source_rises(runs, source):
            rise, route, circuit = same[0].rise_start_mm, same[0].route, same[0].circuit
            out.append(Chase(kind, room, wall, offset, rise, len(same), (), route, circuit))

    if board is not None:
        bundle("board", board.room, board.wall, board.offset, "board")
    if media is not None:
        bundle("media", media.room, media.wall, media.offset, "media")
    for b in boxes:
        if b.on_ceiling:  # on the ceiling: no chase in the wall
            continue
        n = sum(1 for r in runs if b.id in (r.source, r.target))
        for k in range(math.ceil(n / CHASE_CABLES)):
            cables = min(CHASE_CABLES, n - k * CHASE_CABLES)
            out.append(Chase("box", b.room, "", 0.0, b.rise_mm, cables, (), b.route))
    return tuple(out)


def source_rises(runs: Sequence[Run], source: str) -> list[list[Run]]:
    """Lines going up (down) the wall from the panel or the low-voltage cabinet (source "board",
    "media"), by chase: the same route and circuit together, CHASE_CABLES per chase."""
    by_kind: dict[tuple[Route, Circuit], list[Run]] = defaultdict(list)
    for r in runs:
        if r.source == source and r.rise_start_mm > 0:
            by_kind[(r.route, r.lay)].append(r)
    return [
        same[k : k + CHASE_CABLES]
        for _, same in sorted(by_kind.items())
        for k in range(0, len(same), CHASE_CABLES)
    ]


def channel_chases(channels: Sequence[CableChannel]) -> tuple[Chase, ...]:
    """Cable channels: a wide chase from entry to exit; cables go in later, so no run and no
    power circuit."""
    return tuple(
        Chase(
            "channel",
            c.room,
            c.wall,
            c.offset,
            abs(c.exit - c.entry),
            CHASE_CABLES,
            (c.id,),
            circuit="low",
            span=(min(c.entry, c.exit), max(c.entry, c.exit)),
        )
        for c in channels
    )


def before_plaster(chases: Sequence[Chase]) -> tuple[Chase, ...]:
    """Cable laid before the plaster needs no chases: it fits in the plaster layer. Conduit does
    not, so chases stay where it goes down the wall (marked by with_conduit: ceiling routes with
    conduit in the walls, floor routes always, as conduit only on the ceiling ends there). A
    cable channel stays too: it is cut for cables that come later."""
    return tuple(c for c in chases if c.kind == "channel" or c.conduit)


def with_conduit(
    chases: Sequence[Chase], conduit: Conduit, loop: LoopConduit = "separate"
) -> tuple[Chase, ...]:
    """Mark the chases the cables go down in conduit (estimate.conduit_mm): floor routes always,
    ceiling routes with conduit in the walls. Such a chase is narrow only for one conduit
    (CHASE_NARROW_CONDUIT). With loop "shared" a chain point's cable in and cable out go in one
    conduit (decision 2026-11-11): a point twice in the chase is a pair, one conduit
    (Chase.pairs). A cable channel is cut wide for cables that come later: unchanged."""
    out: list[Chase] = []
    for c in chases:
        if c.kind == "channel" or not (c.route == "floor" or conduit == "walls"):
            out.append(c)
            continue
        pairs = c.cables - len(c.targets) if loop == "shared" and c.kind == "point" else 0
        out.append(replace(c, conduit=True, pairs=pairs))
    return tuple(out)


def shared_rises(
    runs: Sequence[Run], points: Sequence[ElectricalPoint], conduit: Conduit, loop: LoopConduit
) -> frozenset[str]:
    """Lines whose rise from a chain point shares one conduit with the cable coming in (loop
    "shared", decision 2026-11-11): a wall point with a cable in and a cable out, both down the
    wall in conduit (floor routes always, ceiling routes with conduit in the walls). The same
    pairs make Chase.pairs (with_conduit)."""
    if loop != "shared":
        return frozenset()
    on_wall = {p.id for p in points if p.wall is not None}
    coming = {r.target: r for r in runs}
    return frozenset(
        r.id
        for r in runs
        if r.source in on_wall
        and r.rise_start_mm > 0
        and r.source in coming
        and coming[r.source].rise_end_mm > 0
        and (r.route == "floor" or conduit == "walls")
    )


def with_material(chases: Sequence[Chase], plan: Plan) -> tuple[Chase, ...]:
    """Wall material of every chase (the estimate prices chases by it): the wall's own material,
    otherwise the plan default; a chase at a box has no wall, so the default too."""
    walls = {(r.id, w.id): w.material for r in plan.rooms for w in r.walls}
    default = plan.default_wall_material
    return tuple(replace(c, material=walls.get((c.room, c.wall)) or default) for c in chases)


def _shared(key: ChaseKey, group: Sequence[_Drop]) -> Chase:
    """Shared chase for a group of drops: middle along the wall, length to the farthest point; a
    turn past an opening to the farthest point it reaches."""
    room, wall, route, circuit = key
    offsets = [g[0] for g in group]
    middle = (min(offsets) + max(offsets)) / 2
    bends = [g[3] for g in group if g[3] is not None]
    return Chase(
        "point",
        room,
        wall,
        middle,
        max(g[1] for g in group),
        len(group),
        tuple(dict.fromkeys(g[2] for g in group)),  # a chain passes a point twice
        route,
        circuit,
        bend=max(bends, key=lambda b: (abs(b[0] - middle), b)) if bends else None,
    )


def passages(geoms: Sequence[RoomGeometry]) -> list[tuple[str, Polygon]]:
    """Doors and openings between rooms: id and position on the plan. The pair "door in one
    room, opening in the neighbour at the same spot" is one pass with the door id."""
    out: list[tuple[str, Polygon]] = []
    for g in geoms:
        for op in g.room.openings:
            if op.type is OpeningType.WINDOW:
                continue
            strip = opening_strip(g, op)
            same = next(
                (
                    k
                    for k, (_, s) in enumerate(out)
                    if s.intersection(strip).area > 0.5 * min(s.area, strip.area)
                ),
                None,
            )
            if same is None:
                out.append((op.id, strip))
            elif op.type is OpeningType.DOOR:
                out[same] = (op.id, out[same][1])
    return out


def wall_holes(
    runs: Sequence[Run],
    passes: Sequence[tuple[str, Polygon]],
    walls: Sequence[Polygon] = (),
) -> tuple[Hole, ...]:
    """One hole per entry into a room whatever the number of cables (decision 2026-11-11; more
    than HOLE_CABLES is a large hole, Hole.large), power and low-voltage apart: above doors and
    openings for ceiling routes; through drillable walls (routing.drillable_walls) for ceiling
    and floor routes, lines crossing a wall closer than WALL_HOLE_SHARE share a hole."""
    lines = [(r, LineString([v.as_tuple() for v in r.path])) for r in runs if len(r.path) > 1]
    out: list[Hole] = []
    for pid, strip in passes:
        through: dict[Circuit, list[str]] = defaultdict(list)
        for r, line in lines:
            if r.route == "ceiling" and line.intersection(strip).length > 1.0:
                through[r.lay].append(r.id)
        for circuit, ids in sorted(through.items()):
            out.append(Hole(pid, len(ids), circuit, tuple(ids)))
    for k, strip in enumerate(walls):
        spots: dict[tuple[str, Circuit], list[tuple[Point, list[str]]]] = defaultdict(list)
        for r, line in lines:
            cut = line.intersection(strip)
            for piece in getattr(cut, "geoms", [cut]):
                if piece.is_empty or piece.length <= 1.0:
                    continue
                at = piece.centroid
                near = spots[(r.route, r.lay)]
                hit = next((ids for p, ids in near if p.distance(at) < WALL_HOLE_SHARE), None)
                if hit is None:
                    near.append((at, [r.id]))
                elif r.id not in hit:
                    hit.append(r.id)
        for (route, circuit), found in sorted(spots.items()):
            for at, ids in found:
                pid = f"wall:{k}:{route}:{at.x:.0f},{at.y:.0f}"
                out.append(Hole(pid, len(ids), circuit, tuple(ids)))
    return tuple(out)
