from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from floorplan_engine.epd.thumbnail import plan_thumbnail, room_kind
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan

RECT = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]
SVG = "{http://www.w3.org/2000/svg}"


def _thumb(openings: list[dict[str, object]] | None = None) -> ET.Element:
    plan = make_plan(RECT, openings)
    issues, contours = validate_plan(plan)
    assert not issues
    return ET.fromstring(plan_thumbnail(plan, contours))


def test_view_box_covers_walls_with_padding() -> None:
    # Внутри 4000 × 3000, стены 120, поле 300: от −420 до 4420 по x
    assert _thumb().get("viewBox") == "-420 -3420 4840 3840"


def test_room_wall_and_window_classes() -> None:
    svg = _thumb([{"wall": "w2", "type": "window", "offset": 1000, "width": 1200, "sill": 800}])
    classes = [el.get("class") for el in svg]
    assert classes == ["room living", "wall", "window"]  # «Комната» — жилое
    line = svg.find(f"{SVG}line")
    assert line is not None
    # Окно по середине верхней стены: y = −(3000 + 60)
    assert (line.get("x1"), line.get("y1"), line.get("x2")) == ("1000", "-3060", "2200")


def test_no_negative_zero() -> None:
    assert not re.search(r"-0\b", ET.tostring(_thumb(), encoding="unicode"))


def test_room_kind_by_flag_and_first_word() -> None:
    """Мокрые — только по флагу; остальное — по слову, что стоит в названии раньше."""
    assert room_kind("Санвузол", True) == "wet"
    assert room_kind("Санвузол", False) == "living"  # без wet — не мокрое: пропуск виден
    assert room_kind("Кухня-вітальня, коридор, передпокій", False) == "kitchen"
    assert room_kind("Зал-вітальня + коридор", False) == "living"
    assert room_kind("Передпокій + гардеробна", False) == "service"
    assert room_kind("Лоджія", False) == "outdoor"
    assert room_kind("Комора", False) == "service"
    assert room_kind("Майстерня", False) == "living"  # не узнали — жилое
