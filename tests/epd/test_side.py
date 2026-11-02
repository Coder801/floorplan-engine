"""Боковая панель просмотра: таблицы листа со ссылками строк на объекты, тема листа,
область чертежа на странице .epd."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from floorplan_engine.drawing.tables import Column, Table
from floorplan_engine.epd.artifact import export_artifact
from floorplan_engine.epd.objects import describe_objects
from floorplan_engine.epd.side import (
    STAGE_OBJECTS,
    drop_column,
    from_table,
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
    # Проводка — только «Группы»; смета — отдельно (вкладка «Смета»), спецификации нет
    assert [t.title for t in tables["wiring"]] == ["Группы"]
    assert tables["estimate"][0].title.startswith("Ведомость объёмов")  # прайса нет
    assert not any("Спецификация" in t.title for t in tables["electrical"])
    assert [t.title for t in tables["panel"]][-1] != "Аппараты для закупки"
    rooms = tables["plan"][0]
    assert "room:r" in rooms.rows[0].keys and "wall:r.w1" in rooms.rows[0].keys
    assert rooms.rows[0].cells[2] == "12,00"  # 3 × 4 м — как поле площади
    groups = {r.cells[0]: r.keys for r in tables["wiring"][0].rows}
    qf2 = {f"wire:{r.id}" for r in wiring.runs if r.group == "QF2"}
    assert qf2 <= set(groups["QF2"])
    assert not qf2 & set(groups["QF3"])
    # «Электрика»: только «Точки» (номер на плане → вид, высота, количество; строка ведёт
    # к своим точкам); легенда — не таблица, а плашка на чертеже (side_legends)
    (points_t,) = tables["electrical"]
    assert any("point:s1" in r.keys for r in points_t.rows)
    # «Группы» — на проводке: строка ведёт и к точкам, и к линиям группы
    assert "point:s1" in groups["QF2"]
    assert not any(t.title.startswith("Групп") for t in tables["electrical"])


def test_panel_devices_in_sections_square_marker_off_line() -> None:
    plan, contours, elec, wiring = _model()
    devices = side_tables(plan, contours, elec, wiring)["panel"][0]
    sections = [r.cells[1] for r in devices.rows if r.section]
    assert sections == ["Ввод и резерв", "Линии групп", "Щит АКБ"]  # резерв — инвертор*
    by_id = {r.cells[0]: r for r in devices.rows if not r.section}
    assert by_id["QS1"].marker == "square" and by_id["QB1"].marker == "square"
    assert by_id["QF2"].marker is None and by_id["QF2"].color is not None  # кружок группы
    assert by_id["QF2"].as_dict().get("marker") is None
    assert by_id["QS3"].as_dict()["marker"] == "square"
    # Раздел «Линии групп» — только аппараты групп
    rows = list(devices.rows)
    start = next(k for k, r in enumerate(rows) if r.cells[1] == "Линии групп")
    end = next(k for k, r in enumerate(rows) if r.cells[1] == "Щит АКБ")
    assert all(r.color is not None for r in rows[start + 1 : end])


def test_legend_entries_only_symbol_and_meaning() -> None:
    plan, _, elec, _ = _model()
    entries = legend_entries(elec, plan.language)
    assert [e.key for e in entries] == ["socket", "board"]
    assert entries[0].text == "Розетка с заземлением"
    assert not any("QF" in e.text or e.text.isdigit() for e in entries)  # без групп и количества
    legends = side_legends(elec, plan.language)
    assert set(legends) == {"electrical", "lighting"}
    assert legends["lighting"] == []  # света в модели нет


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
    # Легенда страницы электрики: подпись и примитивы значка с листа; на листе эти
    # примитивы больше не объекты
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
    assert not any(k.startswith("point:") for k in pages[2]["objects"])  # проводка: без точек
    assert any(k.startswith("box:") for k in pages[2]["objects"])
    assert "device:QS1" in pages[3]["objects"] and "model" not in pages[3]
    assert "panel" not in pages[3]  # без данных щита — только примитивы листа
    assert pages[2]["estimate"]["rows"]  # смета — на странице проводки, для вкладки «Смета»
    assert "estimate" not in pages[1]
