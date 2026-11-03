"""Each line from the panel gets its own breaker (lines.py): premium and proper split a group by
lines.
"""

from __future__ import annotations

from typing import Any

from floorplan_engine.electrical.groups import group_key
from floorplan_engine.electrical.lines import line_names, split_by_lines
from floorplan_engine.electrical.panel import build_panel
from floorplan_engine.electrical.wiring import box_wiring
from floorplan_engine.model.schema import Electrical
from floorplan_engine.validation.plan import validate_plan
from tests.electrical.test_wiring import _two_rooms_with_door


def _socket(pid: str, room: str, offset: float, group: str = "QF1") -> dict[str, Any]:
    return {
        "id": pid,
        "room": room,
        "type": "socket",
        "wall": "w4",
        "offset": offset,
        "height": 300,
        "group": group,
    }


def _elec(**extra: Any) -> Electrical:
    """Two QF1 sockets in rooms a and b each: a box in each, two lines from the panel."""
    return Electrical.model_validate(
        {
            "points": [
                _socket("a1", "a", 500),
                _socket("a2", "a", 2000),
                _socket("b1", "b", 500),
                _socket("b2", "b", 2000),
                {
                    "id": "d1",
                    "room": "a",
                    "type": "data",
                    "wall": "w2",
                    "offset": 500,
                    "height": 300,
                    "group": "QF9",
                },
                {
                    "id": "d2",
                    "room": "b",
                    "type": "data",
                    "wall": "w2",
                    "offset": 500,
                    "height": 300,
                    "group": "QF9",
                },
            ],
            "board": {"room": "a", "wall": "w1", "offset": 500, "height": 1700},
            "cables": [
                {"id": "cable_1", "from": "board", "to": ["a1"], "group": "QF1", "cable": "3x2.5"}
            ],
            "groups": {"QF1": {"name": "Розетки", "breaker": "C16"}},
            **extra,
        }
    )


def _split(elec: Electrical) -> Electrical:
    plan = _two_rooms_with_door()
    issues, contours = validate_plan(plan)
    assert not issues
    return split_by_lines(plan, contours, elec)


def test_standard_keeps_lines_on_one_breaker() -> None:
    elec = _elec()
    assert _split(elec) is elec


def test_proper_gives_each_board_line_own_group() -> None:
    out = _split(_elec(mode="proper", panel={"backup": "inverter", "reserve": ["QF1"]}))
    groups = {p.id: p.group for p in out.points}
    assert groups["a1"] == groups["a2"] == "QF1"
    assert groups["b1"] == groups["b2"] == "QF1.2"
    assert groups["d1"] == groups["d2"] == "QF9"  # low-voltage is not in the panel and is not split
    # Cable, breaker and group backup go to every line; the second one's purpose is built from
    # points
    assert [(c.group, c.cable) for c in out.cables] == [("QF1", "3x2.5"), ("QF1.2", "3x2.5")]
    assert out.cables[1].to == ["b1", "b2"]
    assert out.groups["QF1"].name == "Розетки"
    assert out.groups["QF1.2"].breaker == "C16" and out.groups["QF1.2"].name is None
    assert out.panel.reserve == ["QF1", "QF1.2"]


def test_premium_panel_and_wiring_agree_line_per_breaker() -> None:
    plan = _two_rooms_with_door()
    _, contours = validate_plan(plan)
    out = split_by_lines(plan, contours, _elec(panel={"scheme": "premium", "backup": "none"}))
    wiring = box_wiring(plan, contours, out)
    panel = build_panel(plan, out)
    assert wiring is not None and panel is not None
    lines = sorted(r.group for r in wiring.runs if r.source == "board" and r.group != "QF9")
    breakers = sorted(d.group for d in panel.devices if d.group)
    assert lines == breakers == ["QF1", "QF1.2"]


def test_line_names_skip_taken() -> None:
    assert line_names("QF1", 3, {"QF1", "QF1.2"}) == ["QF1", "QF1.3", "QF1.4"]


def test_group_key_line_right_after_group() -> None:
    names = ["QF10", "QF1.2", "QF2", "QF1"]
    assert sorted(names, key=group_key) == ["QF1", "QF1.2", "QF2", "QF10"]
