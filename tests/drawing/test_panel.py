"""Panel device table: short device names with a legend, assumed cable with "*"."""

from __future__ import annotations

from floorplan_engine.drawing.panel import device_rows, panel_notes
from floorplan_engine.electrical.panel import build_panel
from floorplan_engine.electrical.panel_text import DEVICE_LEGEND
from floorplan_engine.model.schema import Electrical, Plan

PLAN = {
    "name": "T",
    "default_wall_thickness": 100,
    "source": "text",
    "rooms": [
        {
            "id": "k",
            "name": "Кухня",
            "walls": [{"id": f"w{n}", "length": 3000} for n in range(1, 5)],
        }
    ],
}


def _elec(cable: str | None) -> Electrical:
    point = {"id": "s1", "room": "k", "type": "socket", "wall": "w1", "offset": 500, "height": 300}
    cables = [{"id": "c1", "from": "board", "to": ["s1"], "group": "QF1", "cable": cable}]
    return Electrical.model_validate(
        {
            "points": [{**point, "group": "QF1"}],
            "board": {"room": "k", "wall": "w1", "offset": 2000, "height": 1700},
            "cables": cables if cable else [],
        }
    )


def test_device_row_short_name_and_assumed_cable() -> None:
    plan = Plan.model_validate(PLAN)
    panel = build_panel(plan, _elec(None))
    assert panel is not None
    rows = {d.id: r for d, r in device_rows(panel, "ru")}
    assert rows["QF1"][2].startswith("АВ 1P C16")
    assert rows["QF1"][3] == "3x2.5*"
    assert DEVICE_LEGEND["ru"] in panel_notes(panel, "ru")
    given = build_panel(plan, _elec("ВВГнг 3x2.5"))
    assert given is not None
    assert {d.id: r for d, r in device_rows(given, "ru")}["QF1"][3] == "ВВГнг 3x2.5"
