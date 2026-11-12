"""Drops past openings: a cable cannot go down the wall through a window. To a point under a
window (with a floor route, over an opening) the cable goes down the wall beside it, OPENING_GAP
from its edge, to the point height and turns at 90° along the wall to the point. The drop spot
is the nearest one on the wall that is clear of openings, with the turn clear of them too.
"""

from __future__ import annotations

from floorplan_engine.electrical.wiring_model import Route
from floorplan_engine.model.geometry import (
    DOOR_TOP_MM,
    WINDOW_HEIGHT_MM,
    WINDOW_SILL_MM,
    RoomGeometry,
)
from floorplan_engine.model.schema import ElectricalPoint, Opening, OpeningType

OPENING_GAP = 100.0  # mm from the opening edge to the drop beside it
_TOL = 1.0  # mm: touching an opening edge is not crossing it


def opening_heights(op: Opening, ceiling: float) -> tuple[float, float]:
    """Bottom and top of an opening from the floor, mm; missing heights are the assumptions of
    the elevations and the 3D scene."""
    if op.type is OpeningType.WINDOW:
        sill = op.sill if op.sill is not None else WINDOW_SILL_MM
        top = sill + (op.height if op.height is not None else WINDOW_HEIGHT_MM)
        return sill, min(top, ceiling)
    return 0.0, min(op.height if op.height is not None else DOOR_TOP_MM, ceiling)


def drop_offset(g: RoomGeometry, pt: ElectricalPoint, ceiling: float, route: Route) -> float | None:
    """Wall offset of the drop to a wall point when the drop straight above (route floor: below)
    it would cross an opening of its wall; None when it does not, or when no spot beside the
    opening is clear (then the drop stays at the point)."""
    if pt.wall is None or pt.offset is None or pt.height is None:
        return None
    spans = [
        (op.offset, op.offset + op.width, *opening_heights(op, ceiling))
        for op in g.room.openings
        if op.wall == pt.wall
    ]
    lo, hi = (0.0, pt.height) if route == "floor" else (pt.height, ceiling)

    def drop_clear(x: float) -> bool:
        return not any(
            a + _TOL < x < b - _TOL and min(hi, y1) - max(lo, y0) > _TOL for a, b, y0, y1 in spans
        )

    def turn_clear(x: float) -> bool:
        x0, x1 = sorted((x, pt.offset or 0.0))
        return not any(
            min(x1, b) - max(x0, a) > _TOL and y0 + _TOL < (pt.height or 0.0) < y1 - _TOL
            for a, b, y0, y1 in spans
        )

    if drop_clear(pt.offset):
        return None
    length = g.contour.segment(pt.wall).length
    spots = {
        min(max(x, 0.0), length) for a, b, _, _ in spans for x in (a - OPENING_GAP, b + OPENING_GAP)
    }
    ok = sorted((abs(x - pt.offset), x) for x in spots if drop_clear(x) and turn_clear(x))
    return ok[0][1] if ok else None
