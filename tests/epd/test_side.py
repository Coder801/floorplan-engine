"""Viewer side panel: sheet tables with rows linked to objects, sheet topic, drawing area on the
.epd page."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from floorplan_engine.drawing.tables import Column, Table
from floorplan_engine.electrical.panel import build_panel
from floorplan_engine.epd.artifact import export_artifact
from floorplan_engine.epd.objects import describe_objects
from floorplan_engine.epd.side import (
    STAGE_OBJECTS,
    drop_column,
    from_table,
    group_side_table,
    legend_entries,
    side_legends,
    side_tables,
)
from floorplan_engine.sheets.document import build_project_document, sheet_slug
from tests.epd.test_objects import _model


def test_sheet_slug_any_language() -> None:
    assert sheet_slug("03 Проводка") == "wiring"
    assert sheet_slug("02 Електрика") == "electrical"
    assert sheet_slug("07 Что-то") is None


def test_from_table_marks_sections_and_keeps_keys() -> None:
    t = Table(
        "T",
        (Column("№", 8.0), Column("Имя", 30.0, "left")),
        (("", "Материалы"), ("1", "Кабель")),
        total=("", "Всего"),
    )
    side = from_table(t, [(), ("wire:w1",)], ["примечание"])
    assert side.rows[0].section and not side.rows[1].section
    assert side.rows[1].keys == ("wire:w1",)
    assert side.align == ("center", "left")
    d = side.as_dict()
    assert d["total"] == ["", "Всего"] and d["notes"] == ["примечание"]
    assert "keys" not in side.rows[0].as_dict()


def test_drop_column_keeps_keys_and_total_label() -> None:
    t = Table(
        "T",
        (Column("Поз.", 8.0), Column("Назначение", 30.0, "left"), Column("P", 10.0)),
        (("QF1", "Свет", "0,5"),),
        total=("", "Установлена", "0,5"),
    )
    side = drop_column(from_table(t, [("device:QF1",)]), 1)
    assert side.columns == ("Поз.", "P") and side.align == ("center", "center")
    assert side.rows[0].cells == ("QF1", "0,5") and side.rows[0].keys == ("device:QF1",)
    assert side.total == ("Установлена", "0,5")


def test_side_tables_link_rows_to_objects() -> None:
    plan, contours, elec, wiring = _model()
    tables = side_tables(plan, contours, elec, wiring)
    assert set(tables) == {
        "plan",
        "electrical",
        "lighting",
        "wiring",
        "panel",
        "points",
        "estimate",
    }
    # Wiring has only "Groups"; the estimate is separate ("Estimate" tab), there is no specification
    assert [t.title for t in tables["wiring"]] == ["Группы"]
    assert tables["estimate"][0].title.startswith("Ведомость объёмов")  # no price list
    assert not any("Спецификация" in t.title for t in tables["electrical"])
    assert [t.title for t in tables["panel"]][-1] != "Аппараты для закупки"
    rooms = tables["plan"][0]
    assert "room:r" in rooms.rows[0].keys and "wall:r.w1" in rooms.rows[0].keys
    assert rooms.rows[0].cells[2] == "12,00"  # 3 × 4 m, like the area field
    groups = {r.cells[0]: r.keys for r in tables["wiring"][0].rows}
    qf2 = {f"wire:{r.id}" for r in wiring.runs if r.group == "QF2"}
    assert qf2 <= set(groups["QF2"])
    assert not qf2 & set(groups["QF3"])
    # "Electrical": only "Points" (plan number → kind, height, count; a row leads to its points);
    # the legend is not a table but a badge on the drawing (side_legends)
    (points_t,) = tables["electrical"]
    assert any("point:s1" in r.keys for r in points_t.rows)
    # "Groups" are on the wiring sheet: a row leads to both the points and the lines of the group
    assert "point:s1" in groups["QF2"]
    assert not any(t.title.startswith("Групп") for t in tables["electrical"])


def test_panel_devices_in_sections_square_marker_off_line() -> None:
    plan, contours, elec, wiring = _model()
    devices = side_tables(plan, contours, elec, wiring)["panel"][0]
    sections = [r.cells[1] for r in devices.rows if r.section]
    assert sections == ["Ввод и резерв", "Линии групп", "Щит АКБ"]  # backup: inverter*
    by_id = {r.cells[0]: r for r in devices.rows if not r.section}
    assert by_id["QS1"].marker == "square" and by_id["QB1"].marker == "square"
    assert by_id["QF2"].marker is None and by_id["QF2"].color is not None  # group dot
    assert by_id["QF2"].as_dict().get("marker") is None
    assert by_id["QS3"].as_dict()["marker"] == "square"
    # The "Group lines" section has group devices only
    rows = list(devices.rows)
    start = next(k for k, r in enumerate(rows) if r.cells[1] == "Линии групп")
    end = next(k for k, r in enumerate(rows) if r.cells[1] == "Щит АКБ")
    assert all(r.color is not None for r in rows[start + 1 : end])


def test_legend_entries_only_symbol_and_meaning() -> None:
    plan, _, elec, _ = _model()
    entries = legend_entries(elec, plan.language)
    assert [e.key for e in entries] == ["socket", "board"]
    assert entries[0].text == "Розетка с заземлением"
    assert not any("QF" in e.text or e.text.isdigit() for e in entries)  # no groups and no counts
    legends = side_legends(elec, plan.language)
    assert set(legends) == {"electrical", "lighting"}
    assert legends["lighting"] == []  # no lights in the model


def test_epd_page_has_view_stage_tables_and_theme_objects(tmp_path: Path) -> None:
    plan, contours, elec, wiring = _model()
    doc = build_project_document(plan, contours, elec)
    path = export_artifact(
        doc,
        plan,
        tmp_path / "p.epd",
        describe_objects(plan, contours, elec, wiring),
        side_tables(plan, contours, elec, wiring),
        legends=side_legends(elec, plan.language),
    )
    with zipfile.ZipFile(path) as zf:
        pages = [json.loads(zf.read(f"pages/0{k}.json")) for k in (1, 2, 3, 4)]
    # Electrical page legend: caption and icon primitives from the sheet; on the sheet these
    # primitives are no longer objects
    legend = {e["key"]: e for e in pages[1]["legend"]}
    assert set(legend) == {"socket", "board"} and "legend" not in pages[0]
    assert legend["socket"]["text"] == "Розетка с заземлением"
    assert all(
        e["items"] and all("d" in it and "o" not in it for it in e["items"])
        for e in legend.values()
    )
    assert not any(it.get("o", "").startswith("legend:") for it in pages[1]["items"])
    assert [p["stage"] for p in pages] == ["plan", "electrical", "wiring", "panel"]
    for page in pages:
        x0, y0, x1, y1 = page["view"]
        assert 0 < x0 < x1 < page["size"][0] and 0 < y0 < y1 < page["size"][1]
        types = {k.partition(":")[0] for k in page["objects"]}
        assert types <= STAGE_OBJECTS[page["stage"]]
        assert page["tables"]
    assert not any(k.startswith("point:") for k in pages[2]["objects"])  # wiring: no points
    assert any(k.startswith("box:") for k in pages[2]["objects"])
    assert "device:QS1" in pages[3]["objects"] and "model" not in pages[3]
    assert "panel" not in pages[3]  # no panel data: sheet primitives only
    assert pages[2]["estimate"]["rows"]  # estimate on the wiring page
    assert "estimate" not in pages[1]


def test_group_table_moves_purpose_to_the_row_hint() -> None:
    plan, _, elec, wiring = _model()
    table = group_side_table(plan, elec, wiring, build_panel(plan, elec))
    assert table is not None
    assert "Назначение" not in table.columns and len(table.columns) == len(table.align)
    assert all(r.hint and r.group == r.cells[0] for r in table.rows)
    row = table.rows[0].as_dict()
    assert row["group"] == table.rows[0].cells[0] and row["hint"] == table.rows[0].hint
    assert table.total is not None and len(table.total) == len(table.columns)


def test_estimate_work_rows_carry_their_scope() -> None:
    plan, contours, elec, wiring = _model()
    table = side_tables(plan, contours, elec, wiring)["estimate"][0]
    cable = next(r for r in table.rows if len(r.cells) > 1 and r.cells[1] == "Прокладка кабеля")
    scope = cable.as_dict()["scope"]
    assert isinstance(scope, dict) and set(scope) == {"includes", "excludes", "result"}
    assert "раскладка кабеля по трассе" in scope["includes"]
    assert any(x.startswith("соединение жил в коробках — отдельная") for x in scope["excludes"])
    # materials, section rows and totals have no scope
    material = next(r for r in table.rows if len(r.cells) > 1 and r.cells[1] == "Подрозетник")
    assert material.scope is None and "scope" not in material.as_dict()
    assert all(r.scope is None for r in table.rows if r.section)


def test_room_table_has_a_row_per_zone() -> None:
    """Zones that take every wall are rows of the room schedule (2026-11-11), each with its own
    walls."""
    from floorplan_engine.epd.side import room_table
    from floorplan_engine.model.schema import Plan
    from floorplan_engine.validation.plan import validate_plan

    walls = [{"id": f"w{k + 1}", "length": n} for k, n in enumerate((3000, 4000, 3000, 4000))]
    zones = [{"name": "Кухня", "walls": ["w1", "w2"]}, {"name": "Прихожая", "walls": ["w3", "w4"]}]
    room = {"id": "r", "name": "Кухня + прихожая", "walls": walls, "zones": zones}
    plan = Plan.model_validate(
        {"name": "тест", "default_wall_thickness": 120, "source": "text", "rooms": [room]}
    )
    _, contours = validate_plan(plan)
    table = room_table(plan, contours)
    assert [r.cells[1] for r in table.rows] == ["Кухня", "Прихожая"]
    assert table.rows[0].keys[:3] == ("zone:r.1", "wall:r.w1", "dimension:r.w1")
    assert "wall:r.w3" not in table.rows[0].keys
