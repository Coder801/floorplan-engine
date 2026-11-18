"""Frames of mechanisms on a wall and where the cable goes into them (decision 2026-11-17).

Points at one wall spot (room, wall, offset, height) stand side by side in one frame, in model
order, low-voltage last (to the right); the model offset is the middle of the frame. A socket
takes `count` posts (internet and TV too), anything else one; posts are POST_PITCH_MM apart.

The cable down the wall (up from the floor) does not come into the middle of a block but at its
side, by the top (bottom) outer corner of the first mechanism, as installers do:

- a frame with a switch next to a socket: the bundle goes in between them ("switch, socket,
  socket, socket": between the switch and the first socket);
- otherwise at the outer edge of the block: power at the left one when the low-voltage part
  stands to its right, low voltage at the right one; a block alone in its frame at the edge the
  cable comes from along the wall (the route on the ceiling or floor), the wall start when it
  comes square to the wall.

Power and low voltage of one frame each have their own entry: they lie in chases apart. Wall
lights, outputs and other points without a flush box keep the drop above the point.
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from collections.abc import Mapping, Sequence

from floorplan_engine.electrical.wiring_model import Run
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.schema import ElectricalPoint, PointType

POST_PITCH_MM = 71.0  # post step in a frame
BOX_HALF_MM = 34.0  # flush box Ø68: the cable goes in by its top (bottom) edge
LOW_VOLTAGE = (PointType.DATA, PointType.TV)
SWITCH_TYPES = (PointType.SWITCH, PointType.PASS_SWITCH)
# Mechanisms in a flush box: the cable goes in by the side of their frame
MECHANISMS = frozenset(
    {
        PointType.SOCKET,
        PointType.SWITCH,
        PointType.PASS_SWITCH,
        PointType.DATA,
        PointType.TV,
        PointType.THERMOSTAT,
    }
)
_SQUARE = 1.0  # mm along the wall: less is a route square to the wall


def posts(p: ElectricalPoint) -> int:
    """Posts in a frame: count for sockets and low-voltage, one for everything else."""
    return p.count if p.type in (PointType.SOCKET, *LOW_VOLTAGE) else 1


def frames(points: Sequence[ElectricalPoint]) -> list[list[ElectricalPoint]]:
    """Wall points by frame: those at one spot together, in model order, low-voltage last."""
    by_spot: dict[tuple[str, str, int, int], list[ElectricalPoint]] = defaultdict(list)
    for p in points:
        if p.wall is None or p.offset is None or p.height is None:
            continue
        by_spot[(p.room, p.wall, round(p.offset), round(p.height))].append(p)
    return [sorted(same, key=lambda p: p.type in LOW_VOLTAGE) for same in by_spot.values()]


def entries(
    points: Sequence[ElectricalPoint], runs: Sequence[Run], wall_dirs: Mapping[str, Vec]
) -> dict[str, float]:
    """Wall offset of the cable entry for every wall mechanism with a drop or rise (see the
    module doc): point id → mm from the wall start. A drop beside an opening (Run.end_drop,
    start_drop) keeps its own spot. wall_dirs: point id → wall direction on the plan (the
    offset grows along it), to tell which side a route comes from."""
    sides = _sides(runs, wall_dirs)
    out: dict[str, float] = {}
    for frame in frames([p for p in points if p.type in MECHANISMS]):
        total = sum(posts(p) for p in frame)
        left = (frame[0].offset or 0.0) - total * POST_PITCH_MM / 2
        spans: list[tuple[ElectricalPoint, int, int]] = []
        k = 0
        for p in frame:
            spans.append((p, k, k + posts(p)))
            k += posts(p)
        for low in (False, True):
            part = [s for s in spans if (s[0].type in LOW_VOLTAGE) == low]
            if not part:
                continue
            post = _entry_post(part, total, _side([p.id for p, _, _ in part], sides))
            for p, _, _ in part:
                out[p.id] = round(left + post * POST_PITCH_MM, 1)
    return out


def _entry_post(part: Sequence[tuple[ElectricalPoint, int, int]], total: int, side: int) -> int:
    """Entry of one circuit's part of a frame, in posts from the frame's left edge: the joint of
    a switch and a socket, else the part's outer edge (both outer: the side the cable comes
    from, the left one when it comes square)."""
    for (a, _, joint), (b, _, _) in itertools.pairwise(part):
        kinds = {a.type in SWITCH_TYPES, b.type in SWITCH_TYPES}
        if kinds == {True, False} and PointType.SOCKET in (a.type, b.type):
            return joint
    lo, hi = part[0][1], part[-1][2]
    outer_lo, outer_hi = lo == 0, hi == total
    if outer_lo and outer_hi:
        return hi if side > 0 else lo
    if outer_hi:
        return hi
    if outer_lo:
        return lo
    return hi if side > 0 else lo


def _side(ids: Sequence[str], sides: Mapping[str, int]) -> int:
    """The side the cable comes from to a part of a frame: of its first point with a route."""
    for pid in ids:
        if pid in sides:
            return sides[pid]
    return 0


def _sides(runs: Sequence[Run], wall_dirs: Mapping[str, Vec]) -> dict[str, int]:
    """Point id → the side its route comes from along the wall: -1 the wall start, +1 the end,
    0 square to the wall. The line coming in counts first, a chain line going out after."""
    out: dict[str, int] = {}
    for at_end in (True, False):
        for r in runs:
            pid = r.target if at_end else r.source
            rise = r.rise_end_mm if at_end else r.rise_start_mm
            drop = r.end_drop if at_end else r.start_drop
            d = wall_dirs.get(pid)
            if pid in out or d is None or rise <= 0 or drop is not None or len(r.path) < 2:
                continue
            path = list(reversed(r.path)) if at_end else list(r.path)
            out[pid] = _approach(path, d)
    return out


def _approach(path: Sequence[Vec], wall_dir: Vec) -> int:
    """Side along the wall the path comes from to its first vertex: the first vertex back that
    is off the square line."""
    end = path[0]
    for v in path[1:]:
        along = (v - end).dot(wall_dir)
        if abs(along) > _SQUARE:
            return 1 if along > 0 else -1
    return 0
