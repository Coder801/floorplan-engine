"""The "Groups": purpose from the model or built from points; breaker and power from the "Panel"
sheet, cable and length from wiring."""

from __future__ import annotations

from typing import Any

from floorplan_engine.drawing.schedules import groups_table
from floorplan_engine.drawing.tables import Mark
from floorplan_engine.electrical.groups import ASSUMED, group_rows
from floorplan_engine.electrical.panel import build_panel
from floorplan_engine.electrical.wiring import box_wiring
from floorplan_engine.model.schema import Electrical
from floorplan_engine.validation.electrical import validate_electrical
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan

RECT = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]


def _pt(pid: str, kind: str, group: str, **extra: Any) -> dict[str, Any]:
    return {"id": pid, "room": "r", "type": kind, "wall": "w3", "offset": 500,
            "height": 300, "group": group, **extra}  # fmt: skip


def _elec(**extra: Any) -> Electrical:
    return Electrical.model_validate(
        {
            "points": [
                _pt("l1", "sconce", "QF1"),
                _pt("k1", "switch", "QF1"),
                _pt("s1", "socket", "QF2", count=2),
                _pt("s2", "socket", "QF10", note="духовка"),
            ],
            "cables": [
                {"id": "cable_1", "from": "board", "to": ["s1"], "group": "QF2", "cable": "3x2.5"}
            ],
            **extra,
        }
    )


def test_composed_purpose_by_points_and_rooms() -> None:
    plan = make_plan(RECT, [])
    rows = {r.group: r for r in group_rows(plan, _elec())}
    assert list(rows) == ["QF1", "QF2", "QF10"]  # by number, not by string
    assert rows["QF1"].purpose.startswith("Освещение — ") and rows["QF1"].assumed
    assert rows["QF2"].purpose.startswith("Розетки — ") and rows["QF2"].points == 2
    assert rows["QF2"].cable == "3x2.5" and rows["QF2"].cable_ids == ("cable_1",)
    assert rows["QF10"].purpose.startswith("Розетка: духовка")


def test_purpose_and_device_from_model() -> None:
    plan = make_plan(RECT, [])
    elec = _elec(groups={"QF2": {"name": "Розетки кухни", "breaker": "C16", "rcd": "30 мА"}})
    built = groups_table(plan, elec)
    assert built is not None
    table, notes = built
    row = next(r for r in table.rows if isinstance(r[0], Mark) and r[0].text == "QF2")
    assert isinstance(row[0], Mark) and row[0].color  # group colour dot
    assert row[1] == "Розетки кухни" and row[2] == "C16, 30 мА"  # no "*": from the model
    assert any(str(r[1]).endswith(ASSUMED) for r in table.rows) and notes  # the others are built


def test_device_column_only_when_known() -> None:
    built = groups_table(make_plan(RECT, []), _elec())
    assert built is not None and len(built[0].columns) == 4


def test_unknown_group_in_groups_is_warning() -> None:
    plan = make_plan(RECT, [])
    _, contours = validate_plan(plan)
    issues = validate_electrical(_elec(groups={"QF99": {"name": "x"}}), plan, contours)
    assert any(i.path == "groups.QF99" for i in issues)


def test_standard_mode_warns_group_over_rooms() -> None:
    plan = make_plan(RECT, [])
    _, contours = validate_plan(plan)
    two = make_plan(RECT, [])
    two.rooms.append(two.rooms[0].model_copy(update={"id": "r2", "name": "Вторая"}))
    elec = _elec()
    elec.points.append(elec.points[0].model_copy(update={"id": "l2", "room": "r2"}))
    _, contours2 = validate_plan(two)
    issues = validate_electrical(elec, two, contours2)
    assert any(i.path == "groups.QF1" and "несколько помещений" in i.message for i in issues)
    economy = elec.model_copy(update={"mode": "economy"})
    assert not any(i.path == "groups.QF1" for i in validate_electrical(economy, two, contours2))
    assert not any(
        i.path.startswith("groups.") for i in validate_electrical(_elec(), plan, contours)
    )


def test_groups_with_wiring_and_panel() -> None:
    """With wiring and a panel: breaker and power from the panel (a chosen one gets "*" and a note),
    cable and length from wiring; totals are length, points, power."""
    plan = make_plan(RECT, [])
    _, contours = validate_plan(plan)
    elec = _elec(board={"room": "r", "wall": "w1", "offset": 500, "height": 1700})
    wiring = box_wiring(plan, contours, elec)
    panel = build_panel(plan, elec)
    assert wiring is not None and panel is not None
    built = groups_table(plan, elec, wiring, panel)
    assert built is not None
    table, notes = built
    heads = [c.title for c in table.columns]
    assert heads == ["Группа", "Назначение", "Автомат", "Кабель", "Длина, м", "Точек", "P, кВт"]
    row = next(r for r in table.rows if isinstance(r[0], Mark) and r[0].text == "QF2")
    device = next(d for d in panel.devices if d.group == "QF2")
    assert str(row[2]).rstrip(ASSUMED) == device.label
    qf2 = sum(r.length_mm for r in wiring.runs if r.group == "QF2") / 1000
    assert row[4] == f"{qf2:.1f}".replace(".", ",")
    points = sum(int(str(r[5])) for r in table.rows)
    assert table.total is not None and table.total[5] == str(points)
    assert any("лист «Щит»" in n for n in notes)  # breaker chosen by code
