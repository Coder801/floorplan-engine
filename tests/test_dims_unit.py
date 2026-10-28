"""Раскладка размеров (draw_plan._place_rows): уровни рядов и вынос узких подписей."""

from __future__ import annotations

from shapely.geometry.base import BaseGeometry

from floorplan_engine.draw_plan import _fits, _place_rows, _text_box
from floorplan_engine.geometry import Vec, WallSegment
from floorplan_engine.layers import drawing_scale
from floorplan_engine.validate import validate_plan
from tests.conftest import make_plan


def _wall() -> WallSegment:
    plan = make_plan([{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}])
    _, contours = validate_plan(plan)
    return contours["r"].segment("w2")  # верхняя стена, 4000


def test_row_moves_to_next_level_when_taken() -> None:
    with drawing_scale(50):
        seg = _wall()
        taken: list[BaseGeometry] = []
        first, _ = _place_rows(seg, [[(0.0, seg.length)]], 1.0, 400.0, taken)
        second, _ = _place_rows(seg, [[(0.0, seg.length)]], 1.0, 400.0, taken)
        assert first == 400.0 and second > first  # то же место занято — следующий уровень


def test_narrow_part_text_is_moved_off_its_part() -> None:
    with drawing_scale(50):
        seg = _wall()
        parts = [(0.0, 1900.0), (1900.0, 2000.0), (2000.0, seg.length)]  # 100 мм — 2 мм листа
        assert not _fits(1900.0, 2000.0) and _fits(0.0, 1900.0)
        taken: list[BaseGeometry] = []
        level, moves = _place_rows(seg, [parts], 1.0, 400.0, taken)
        assert moves[0][0] is None and moves[0][2] is None
        move = moves[0][1]
        assert move is not None
        narrow = _text_box(seg, 1900.0, 2000.0, level, move)
        for a, b in (parts[0], parts[2]):
            assert narrow.intersection(_text_box(seg, a, b, level, Vec(0.0, 0.0))).area == 0
