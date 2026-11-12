from typing import Any

import pytest

from floorplan_engine.electrical.anchors import SYMBOL_DEPTH, stack_shifts
from floorplan_engine.model.scale import sheet
from floorplan_engine.model.schema import ElectricalPoint, PointType


def _pt(pid: str, kind: str, offset: float, **extra: Any) -> ElectricalPoint:
    return ElectricalPoint(
        id=pid, room="r", wall="w1", offset=offset, type=PointType(kind), height=900, **extra
    )


def test_stack_puts_small_symbols_at_the_wall() -> None:
    """Three switches and a cable outlet at one spot: the outlet stands at the wall, not 0.8 m
    into the room behind the switches; the step is the symbol depth, no extra gap."""
    points = [
        _pt("s1", "switch", 121),
        _pt("s2", "switch", 121),
        _pt("s3", "switch", 121),
        _pt("o", "outlet", 121),
    ]
    shifts = stack_shifts(points)
    switch, outlet = sheet(SYMBOL_DEPTH["switch"]), sheet(SYMBOL_DEPTH["outlet"])
    assert shifts[3] == 0.0
    assert shifts[:3] == pytest.approx([outlet, outlet + switch, outlet + 2 * switch])


def test_equal_symbols_keep_yaml_order_and_lone_points_stay_at_the_wall() -> None:
    points = [_pt("a", "socket", 300), _pt("b", "socket", 310), _pt("c", "socket", 2000)]
    shifts = stack_shifts(points)
    assert shifts == pytest.approx([0.0, sheet(SYMBOL_DEPTH["socket"]), 0.0])
