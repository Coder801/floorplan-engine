"""Штробы и отверстия: спуски и подъёмы кабелей по стенам к точкам и коробкам (общие —
одной штробой, шире — больше CHASE_NARROW кабелей), проходы кабелей через дверные проёмы."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence

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
    ElectricalPoint,
    OpeningType,
)

CHASE_SHARE = 150.0  # мм вдоль стены: спуски ближе — в общей штробе
CHASE_CABLES = 4  # кабелей в одной штробе, не больше
HOLE_CABLES = 4  # кабелей в одном отверстии через стену, не больше


def wall_chases(
    runs: Sequence[Run],
    points: Sequence[ElectricalPoint],
    board: Board | None,
    boxes: Sequence[JunctionBox],
) -> tuple[Chase, ...]:
    """Штробы по стенам: общие для спусков рядом (CHASE_SHARE), до CHASE_CABLES кабелей."""
    by_id = {p.id: p for p in points}
    drops: dict[ChaseKey, list[tuple[float, float, str]]] = defaultdict(list)
    for r in runs:
        p = by_id.get(r.target)
        if r.rise_end_mm <= 0 or p is None or p.wall is None or p.offset is None:
            continue
        drops[(p.room, p.wall, r.route, r.circuit)].append((p.offset, r.rise_end_mm, p.id))
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
    for b in boxes:
        if b.on_ceiling:  # на потолке — без штробы в стене
            continue
        n = sum(1 for r in runs if b.id in (r.source, r.target))
        for k in range(math.ceil(n / CHASE_CABLES)):
            cables = min(CHASE_CABLES, n - k * CHASE_CABLES)
            out.append(Chase("box", b.room, "", 0.0, b.rise_mm, cables, (), b.route))
    return tuple(out)


def _shared(key: ChaseKey, group: Sequence[tuple[float, float, str]]) -> Chase:
    """Общая штроба группы спусков: середина по стене, длина — до самой дальней точки."""
    room, wall, route, circuit = key
    offsets = [g[0] for g in group]
    return Chase(
        "point",
        room,
        wall,
        (min(offsets) + max(offsets)) / 2,
        max(g[1] for g in group),
        len(group),
        tuple(g[2] for g in group),
        route,
        circuit,
    )


def passages(geoms: Sequence[RoomGeometry]) -> list[tuple[str, Polygon]]:
    """Двери и проёмы между помещениями: id и место на плане. Пара «дверь в одной
    комнате — проём в соседней на том же месте» — один проход с id двери."""
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
    """Отверстия над дверями и проёмами для трасс по потолку, до HOLE_CABLES кабелей."""
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
