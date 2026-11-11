"""Chases and holes: cable drops and rises along walls to points and boxes (shared ones in one
chase, a wider one above CHASE_NARROW cables), cable channels, cable passes through door
openings."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace

from shapely.geometry import LineString, Polygon

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
    OpeningType,
)

CHASE_SHARE = 150.0  # mm along the wall: closer drops share a chase
CHASE_CABLES = 4  # cables per chase, at most
HOLE_CABLES = 4  # cables per hole through a wall, at most


def wall_chases(
    runs: Sequence[Run],
    points: Sequence[ElectricalPoint],
    board: Board | None,
    boxes: Sequence[JunctionBox],
    media: Board | None = None,
) -> tuple[Chase, ...]:
    """Wall chases: shared by drops close together (CHASE_SHARE), up to CHASE_CABLES cables."""
    by_id = {p.id: p for p in points}
    drops: dict[ChaseKey, list[tuple[float, float, str]]] = defaultdict(list)
    for r in runs:
        # In a daisy chain the line also leaves a point: a second cable in its chase
        for end, rise in ((r.target, r.rise_end_mm), (r.source, r.rise_start_mm)):
            p = by_id.get(end)
            if rise <= 0 or p is None or p.wall is None or p.offset is None:
                continue
            drops[(p.room, p.wall, r.route, r.circuit)].append((p.offset, rise, p.id))
    out: list[Chase] = []
    for key, items in sorted(drops.items()):
        group: list[tuple[float, float, str]] = []
        for item in sorted(items):
            if group and (item[0] - group[0][0] > CHASE_SHARE or len(group) == CHASE_CABLES):
                out.append(_shared(key, group))
                group = []
            group.append(item)
        out.append(_shared(key, group))

    def bundle(kind: str, room: str, wall: str, offset: float, rs: Sequence[Run]) -> None:
        by_kind: dict[tuple[Route, Circuit], list[Run]] = defaultdict(list)
        for r in rs:
            by_kind[(r.route, r.circuit)].append(r)
        for (route, circuit), same in sorted(by_kind.items()):
            n = len(same)
            for k in range(math.ceil(n / CHASE_CABLES)):
                cables = min(CHASE_CABLES, n - k * CHASE_CABLES)
                rise = same[0].rise_start_mm
                out.append(Chase(kind, room, wall, offset, rise, cables, (), route, circuit))

    from_board = [r for r in runs if r.source == "board" and r.rise_start_mm > 0]
    if board is not None and from_board:
        bundle("board", board.room, board.wall, board.offset, from_board)
    from_media = [r for r in runs if r.source == "media" and r.rise_start_mm > 0]
    if media is not None and from_media:
        bundle("media", media.room, media.wall, media.offset, from_media)
    for b in boxes:
        if b.on_ceiling:  # on the ceiling: no chase in the wall
            continue
        n = sum(1 for r in runs if b.id in (r.source, r.target))
        for k in range(math.ceil(n / CHASE_CABLES)):
            cables = min(CHASE_CABLES, n - k * CHASE_CABLES)
            out.append(Chase("box", b.room, "", 0.0, b.rise_mm, cables, (), b.route))
    return tuple(out)


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


def before_plaster(chases: Sequence[Chase], conduit: Conduit) -> tuple[Chase, ...]:
    """Cable laid before the plaster needs no chases: it fits in the plaster layer. Conduit does
    not, so chases stay where it goes down the wall: ceiling routes with conduit in the walls,
    floor routes always (conduit only on the ceiling ends there). A cable channel stays too: it
    is cut for cables that come later."""
    if conduit == "walls":
        return tuple(chases)
    return tuple(c for c in chases if c.kind == "channel" or c.route == "floor")


def with_conduit(chases: Sequence[Chase], conduit: Conduit) -> tuple[Chase, ...]:
    """Mark the chases the cables go down in conduit (estimate.conduit_mm): floor routes always,
    ceiling routes with conduit in the walls. Such a chase is narrow only for one conduit
    (CHASE_NARROW_CONDUIT). A cable channel is cut wide for cables that come later: unchanged."""
    return tuple(
        replace(c, conduit=True)
        if c.kind != "channel" and (c.route == "floor" or conduit == "walls")
        else c
        for c in chases
    )


def _shared(key: ChaseKey, group: Sequence[tuple[float, float, str]]) -> Chase:
    """Shared chase for a group of drops: middle along the wall, length to the farthest point."""
    room, wall, route, circuit = key
    offsets = [g[0] for g in group]
    return Chase(
        "point",
        room,
        wall,
        (min(offsets) + max(offsets)) / 2,
        max(g[1] for g in group),
        len(group),
        tuple(dict.fromkeys(g[2] for g in group)),  # a chain passes a point twice
        route,
        circuit,
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


def wall_holes(runs: Sequence[Run], passes: Sequence[tuple[str, Polygon]]) -> tuple[Hole, ...]:
    """Holes above doors and openings for ceiling routes, up to HOLE_CABLES cables."""
    lines = [
        (r, LineString([v.as_tuple() for v in r.path]))
        for r in runs
        if r.route == "ceiling" and len(r.path) > 1
    ]
    out: list[Hole] = []
    for pid, strip in passes:
        through: dict[Circuit, list[str]] = defaultdict(list)
        for r, line in lines:
            if line.intersection(strip).length > 1.0:
                through[r.circuit].append(r.id)
        for circuit, ids in sorted(through.items()):
            for k in range(0, len(ids), HOLE_CABLES):
                chunk = tuple(ids[k : k + HOLE_CABLES])
                out.append(Hole(pid, len(chunk), circuit, chunk))
    return tuple(out)
