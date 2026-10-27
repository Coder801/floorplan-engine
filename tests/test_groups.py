"""Группы щита отдельной таблицей: назначение из модели или составленное по точкам."""

from __future__ import annotations

from typing import Any

from floorplan_engine.groups import ASSUMED, group_rows, groups_table
from floorplan_engine.schema import Electrical
from floorplan_engine.tables import Mark
from floorplan_engine.validate import validate_electrical, validate_plan
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
    assert list(rows) == ["QF1", "QF2", "QF10"]  # по номерам, не по строке
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
    assert isinstance(row[0], Mark) and row[0].color  # кружок цвета группы
    assert row[1] == "Розетки кухни" and row[4] == "C16, 30 мА"  # без «*»: из модели
    assert any(str(r[1]).endswith(ASSUMED) for r in table.rows) and notes  # остальные составлены


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
