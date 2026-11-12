"""Where a point symbol sits on the plan and where the route reaches it: the anchor (insert
point, direction into the room, the symbol "tip"), stacks of points at one wall spot, symbol
sizes on the sheet. Shared by the electrical drawing (drawing/) and the wiring calculation,
which is why it lives here and not in drawing: a route starts at the symbol tip.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from floorplan_engine.model.geometry import RoomGeometry, Vec
from floorplan_engine.model.scale import sheet
from floorplan_engine.model.schema import Board, ElectricalPoint, PointType

# Symbol sizes, sheet mm (blocks are drawn by drawing/symbols.py)
WALL_GAP = 0.4  # symbol gap from the wall face
SOCKET_R = 2.0
SOCKET_DEPTH = WALL_GAP + SOCKET_R  # to the tangent line (earth line)
SWITCH_R = 1.0
SWITCH_ARM = 3.0
SWITCH_DEPTH = WALL_GAP + 2 * SWITCH_R + SWITCH_ARM * math.sin(math.radians(45))
LIGHT_R = 2.5
DOWNLIGHT_R = 1.0
PENDANT_R = 2.0
SCONCE_R = 2.0
DATA_LEN = 7.0  # internet and TV symbols: twice the original size
DATA_TRI = 2.4
LED_OUTPUT_R = 0.6
LED_OUTPUT_DEPTH = WALL_GAP + 2.5
OUTLET_R = 0.8
OUTLET_DEPTH = WALL_GAP + 2.5
BOARD_DEPTH = 3.0

# Symbol key: the point type, "switch2" for a two-key switch, "board" for the panel, "media" for
# the low-voltage cabinet
# sheet mm: how far the symbol sticks out from the wall (radius for ceiling ones)
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
    "media": BOARD_DEPTH,
}


def symbol_key(pt: ElectricalPoint) -> str:
    if pt.type is PointType.SWITCH and pt.keys == 2:
        return "switch2"
    return str(pt.type)


STACK_TOLERANCE = 30.0  # mm: wall points closer than this are drawn as a stack


@dataclass(frozen=True)
class Anchor:
    """Symbol position: insert point and direction into the room (None for ceiling)."""

    pos: Vec
    inward: Vec | None
    wall_dir: Vec | None
    depth: float

    @property
    def node(self) -> Vec:
        """Route connection point: the symbol "tip"."""
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
    """Symbol position; shift moves it from the wall into the room (for a stack at one spot)."""
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
    """Points on one wall at one spot (within STACK_TOLERANCE of the first): a socket under a
    switch and so on, in YAML order; each ceiling point stands alone."""
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
    """Offset of each point from the wall on the plan: the next in a stack goes behind the
    previous one, smaller symbols nearer the wall (a cable outlet before three switches, not 0.8 m
    into the room behind them). The step is the symbol depth, whose WALL_GAP is the gap between
    symbols. Drawing only: the route reaches the point at the wall (wiring takes no shift).
    """
    shifts = [0.0] * len(points)
    for group in stacks(points):
        acc = 0.0
        for k in sorted(group, key=lambda k: SYMBOL_DEPTH[symbol_key(points[k])]):
            shifts[k] = acc
            acc += sheet(SYMBOL_DEPTH[symbol_key(points[k])])
    return shifts


def board_anchor(board: Board, geoms: dict[str, RoomGeometry]) -> Anchor:
    return wall_anchor(geoms, board.room, board.wall, board.offset, sheet(BOARD_DEPTH))
