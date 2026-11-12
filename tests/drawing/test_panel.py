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


def _many_groups(n: int) -> Electrical:
    """n socket groups: enough devices for several 12-module rails."""
    points = [
        {
            "id": f"s{k}",
            "room": "k",
            "type": "socket",
            "wall": "w1",
            "offset": 100 + 10 * k,
            "height": 300,
            "group": f"QF{k}",
        }
        for k in range(1, n + 1)
    ]
    board = {"room": "k", "wall": "w1", "offset": 2000, "height": 1700}
    return Electrical.model_validate({"points": points, "board": board})


def test_sheet_draws_the_rails_of_the_chosen_enclosure() -> None:
    # A wide sheet would give a larger module on 24-module rails; the sheet still shows the
    # enclosure as it is (Hager Golf, 12 per rail), as the viewer and the estimate do
    from floorplan_engine.drawing.panel import fit_panel

    panel = build_panel(Plan.model_validate(PLAN), _many_groups(20))
    assert panel is not None and panel.enclosure is not None
    fit = fit_panel(panel, 600.0, 300.0)
    assert fit is not None
    assert fit.per_row == panel.enclosure.per_row == 12
    assert fit.rows == panel.rows
    assert all(sum(d.modules for d in row) <= 12 for row in fit.rows)
