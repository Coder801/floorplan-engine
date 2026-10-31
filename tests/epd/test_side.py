"""Боковая панель просмотра: таблицы листа со ссылками строк на объекты, тема листа,
область чертежа на странице .epd."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from floorplan_engine.drawing.tables import Column, Table
from floorplan_engine.epd.artifact import export_artifact
from floorplan_engine.epd.objects import describe_objects
from floorplan_engine.epd.side import STAGE_OBJECTS, drop_column, from_table, side_tables
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
    points_t, symbols = tables["electrical"][:2]
    # «Точки»: номер на плане → вид и высота; строка ведёт к своим точкам
    assert any("point:s1" in r.keys for r in points_t.rows)
    # «Группы» — на проводке: строка ведёт и к точкам, и к линиям группы
    assert "point:s1" in groups["QF2"]
    assert not any(t.title.startswith("Групп") for t in tables["electrical"])
    socket = next(r for r in symbols.rows if "point:s1" in r.keys)
    assert socket.cells[1] == "4"  # s1 ×2, s2, s3


def test_epd_page_has_view_stage_tables_and_theme_objects(tmp_path: Path) -> None:
    plan, contours, elec, wiring = _model()
    doc = build_project_document(plan, contours, elec)
    path = export_artifact(
        doc,
        plan,
        tmp_path / "p.epd",
        describe_objects(plan, contours, elec, wiring),
        side_tables(plan, contours, elec, wiring),
    )
    with zipfile.ZipFile(path) as zf:
        pages = [json.loads(zf.read(f"pages/0{k}.json")) for k in (1, 2, 3, 4)]
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
