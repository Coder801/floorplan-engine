"""Где символ точки стоит на плане и откуда к нему подходит трасса: якорь (точка вставки,
направление в помещение, «макушка» символа), стопки точек в одном месте стены, размеры
символов на листе. Общая основа рисования электрики (drawing/) и расчёта проводки — поэтому
здесь, а не в рисовании: трасса начинается от макушки символа.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from floorplan_engine.model.geometry import RoomGeometry, Vec
from floorplan_engine.model.scale import sheet
from floorplan_engine.model.schema import Board, ElectricalPoint, PointType

# Размеры символов, мм листа (блоки рисует drawing/symbols.py)
WALL_GAP = 0.4  # зазор символа от грани стены
SOCKET_R = 2.0
SOCKET_DEPTH = WALL_GAP + SOCKET_R  # до касательной (линия заземления)
SWITCH_R = 1.0
SWITCH_ARM = 3.0
SWITCH_DEPTH = WALL_GAP + 2 * SWITCH_R + SWITCH_ARM * math.sin(math.radians(45))
LIGHT_R = 2.5
DOWNLIGHT_R = 1.0
PENDANT_R = 2.0
SCONCE_R = 2.0
DATA_LEN = 3.5
DATA_TRI = 1.2
LED_OUTPUT_R = 0.6
LED_OUTPUT_DEPTH = WALL_GAP + 2.5
OUTLET_R = 0.8
OUTLET_DEPTH = WALL_GAP + 2.5
BOARD_DEPTH = 3.0

# Ключ символа: тип точки, а для двухклавишного выключателя — "switch2"; щит — "board"
# мм листа: насколько символ выступает от стены (у потолочных — радиус)
SYMBOL_DEPTH: dict[str, float] = {
    PointType.SOCKET: SOCKET_DEPTH,
    PointType.SWITCH: SWITCH_DEPTH,
    "switch2": SWITCH_DEPTH,
    PointType.PASS_SWITCH: SWITCH_DEPTH,
    PointType.LIGHT: LIGHT_R,
    PointType.DOWNLIGHT: DOWNLIGHT_R * 1.8,
    PointType.PENDANT: PENDANT_R,
    PointType.SCONCE: WALL_GAP + SCONCE_R,
    PointType.DATA: WALL_GAP + DATA_LEN,
    PointType.TV: WALL_GAP + DATA_LEN,
    PointType.LED_OUTPUT: LED_OUTPUT_DEPTH,
    PointType.OUTLET: OUTLET_DEPTH,
    "board": BOARD_DEPTH,
}


def symbol_key(pt: ElectricalPoint) -> str:
    if pt.type is PointType.SWITCH and pt.keys == 2:
        return "switch2"
    return str(pt.type)


STACK_GAP_MM = 1.0  # между символами, стоящими в одной точке стены
STACK_TOLERANCE = 30.0  # мм: точки ближе этого по стене рисуются стопкой


@dataclass(frozen=True)
class Anchor:
    """Положение символа: точка вставки и направление в помещение (None — потолок)."""

    pos: Vec
    inward: Vec | None
    wall_dir: Vec | None
    depth: float

    @property
    def node(self) -> Vec:
        """Точка подключения трассы — «макушка» символа."""
        return self.pos if self.inward is None else self.pos + self.inward * self.depth

    @property
    def rotation(self) -> float:
        if self.inward is None:
            return 0.0
        return math.degrees(math.atan2(self.inward.y, self.inward.x)) - 90.0

    @property
    def wall_is_vertical(self) -> bool:
        return self.wall_dir is not None and abs(self.wall_dir.y) > abs(self.wall_dir.x)


def room_geometry(geoms: dict[str, RoomGeometry], room_id: str) -> RoomGeometry:
    return geoms[room_id]


def wall_anchor(
    geoms: dict[str, RoomGeometry], room_id: str, wall: str, offset: float, depth: float
) -> Anchor:
    seg = room_geometry(geoms, room_id).contour.segment(wall)
    return Anchor(seg.point_at(offset), seg.inward, seg.direction, depth)


def point_anchor(pt: ElectricalPoint, geoms: dict[str, RoomGeometry], shift: float = 0.0) -> Anchor:
    """Положение символа; shift — сдвиг от стены в помещение (для стопки в одной точке)."""
    depth = SYMBOL_DEPTH[symbol_key(pt)]
    if pt.ceiling is not None:
        origin = Vec(*room_geometry(geoms, pt.room).room.origin)
        return Anchor(origin + Vec(*pt.ceiling), None, None, sheet(depth))
    assert pt.wall is not None and pt.offset is not None
    a = wall_anchor(geoms, pt.room, pt.wall, pt.offset, sheet(depth))
    if shift == 0.0 or a.inward is None:
        return a
    return Anchor(a.pos + a.inward * shift, a.inward, a.wall_dir, a.depth)


def stacks(points: Sequence[ElectricalPoint]) -> list[list[int]]:
    """Точки на одной стене в одном месте (в пределах STACK_TOLERANCE от первой) — розетка
    под выключателем и т. п., по порядку из YAML; потолочные точки — каждая сама по себе."""
    out: list[list[int]] = []
    for k, pt in enumerate(points):
        if pt.wall is None or pt.offset is None:
            out.append([k])
            continue
        group = next(
            (
                g
                for g in out
                if (first := points[g[0]]).room == pt.room
                and first.wall == pt.wall
                and first.offset is not None
                and abs(first.offset - pt.offset) <= STACK_TOLERANCE
            ),
            None,
        )
        if group is None:
            out.append([k])
        else:
            group.append(k)
    return out


def stack_shifts(points: Sequence[ElectricalPoint]) -> list[float]:
    """Сдвиг каждой точки от стены: следующая в стопке ставится за предыдущей."""
    shifts = [0.0] * len(points)
    for group in stacks(points):
        acc = 0.0
        for k in group:
            shifts[k] = acc
            acc += sheet(SYMBOL_DEPTH[symbol_key(points[k])] + STACK_GAP_MM)
    return shifts


def board_anchor(board: Board, geoms: dict[str, RoomGeometry]) -> Anchor:
    return wall_anchor(geoms, board.room, board.wall, board.offset, sheet(BOARD_DEPTH))
