"""Drops past openings: where the cable goes down the wall to a point under a window."""

from __future__ import annotations

from typing import Any

import pytest

from floorplan_engine.electrical.detours import OPENING_GAP, drop_offset, opening_heights
from floorplan_engine.model.geometry import DOOR_TOP_MM, RoomGeometry, room_geometries
from floorplan_engine.model.schema import ElectricalPoint, Opening
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan

RECT = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]
WINDOW = {
    "wall": "w2",
    "type": "window",
    "offset": 1000,
    "width": 1500,
    "sill": 800,
    "height": 1900,
}


def _room(*openings: dict[str, Any]) -> RoomGeometry:
    plan = make_plan(RECT, list(openings))
    issues, contours = validate_plan(plan)
    assert not issues
    return room_geometries(plan, contours)[0]


def _socket(offset: float, height: float = 300, wall: str = "w2") -> ElectricalPoint:
    return ElectricalPoint.model_validate(
        {"id": "s", "room": "r", "type": "socket", "wall": wall, "offset": offset, "height": height}
    )


def test_drop_goes_beside_window_on_the_nearer_side() -> None:
    g = _room(WINDOW)
    assert drop_offset(g, _socket(1300), 2700, "ceiling") == 1000 - OPENING_GAP
    assert drop_offset(g, _socket(2300), 2700, "ceiling") == 2500 + OPENING_GAP


def test_no_detour_when_the_drop_misses_the_window() -> None:
    g = _room(WINDOW)
    assert drop_offset(g, _socket(500), 2700, "ceiling") is None  # beside the window
    assert drop_offset(g, _socket(1300, wall="w4"), 2700, "ceiling") is None  # another wall
    assert drop_offset(g, _socket(1300), 2700, "floor") is None  # up from the floor
    low = {**WINDOW, "height": 1200}  # top at 2000: a point above it is reached from above
    assert drop_offset(_room(low), _socket(1300, 2300), 2700, "ceiling") is None


def test_detour_skips_a_door_beside_the_window() -> None:
    """Left of the window a door: the drop goes to the far side, the turn under the window."""
    door = {"wall": "w2", "type": "door", "offset": 100, "width": 850}
    g = _room(WINDOW, door)
    assert drop_offset(g, _socket(1100), 2700, "ceiling") == 2500 + OPENING_GAP


def test_window_to_the_corner_drops_in_the_corner() -> None:
    """The spot beside the window is off the wall: the drop is clamped into the corner."""
    g = _room({**WINDOW, "offset": 50, "width": 3900})
    assert drop_offset(g, _socket(500), 2700, "ceiling") == 0.0
    assert drop_offset(g, _socket(3800), 2700, "ceiling") == 4000.0


def test_no_clear_spot_keeps_the_drop_at_the_point() -> None:
    """Doors on both sides of the window: every way round crosses one, so no detour."""
    left = {"wall": "w2", "type": "door", "offset": 0, "width": 1000}
    right = {"wall": "w2", "type": "door", "offset": 2500, "width": 1500}
    g = _room(WINDOW, left, right)
    assert drop_offset(g, _socket(1200), 2700, "ceiling") is None


@pytest.mark.parametrize(
    ("opening", "expected"),
    [
        ({"type": "window", "sill": 700, "height": 2500}, (700, 2700)),  # cut at the ceiling
        ({"type": "window"}, (900, 2300)),  # assumed sill and height
        ({"type": "door"}, (0, DOOR_TOP_MM)),
        ({"type": "opening", "height": 2400}, (0, 2400)),
    ],
)
def test_opening_heights(opening: dict[str, Any], expected: tuple[float, float]) -> None:
    op = Opening.model_validate({"id": "o", "wall": "w1", "offset": 0, "width": 900, **opening})
    assert opening_heights(op, 2700) == expected
