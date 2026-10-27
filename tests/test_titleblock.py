from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
from ezdxf.document import Drawing
from ezdxf.entities.insert import Insert
from ezdxf.entities.mtext import MText
from ezdxf.filemanagement import readfile

from shtroba.layers import text_width
from shtroba.preview import sheet_layouts
from shtroba.schema import Plan, SheetInfo
from shtroba.sheets import Panel, SheetSpec, build_project_document, grid, place
from shtroba.texts import TEXTS
from shtroba.titleblock import (
    FRAME_LEFT,
    FRAME_MARGIN,
    PADDING,
    STAMP_BLOCK,
    STAMP_FIELDS,
    STAMP_H,
    STAMP_W,
    TEXT_MIN_MM,
    Line,
    fit_cell,
    fit_line,
)
from shtroba.validate import validate_plan
from tests.conftest import make_plan


def _spec(
    tables: list[tuple[float, float]], legend: tuple[float, float] | None = None
) -> SheetSpec:
    def panel(w: float, h: float) -> Panel:
        return Panel(w, h, lambda psp, at: None)

    return SheetSpec(
        "tab_plan",
        "plan_image",
        (),
        tuple(panel(*t) for t in tables),
        (panel(*legend),) if legend else (),
    )


def test_grid_crosses_at_stamp_corner() -> None:
    g = grid(594, 420)
    x0, y0, x1, y1 = FRAME_LEFT, FRAME_MARGIN, 594 - FRAME_MARGIN, 420 - FRAME_MARGIN
    xs, ys = x1 - STAMP_W, y0 + STAMP_H
    assert g.plan == (x0, ys, xs, y1)
    assert g.tables == (xs, ys, x1, y1)
    assert g.legend == (x0, y0, xs, ys)


def test_place_plan_centered_tables_right_legend_left_of_stamp() -> None:
    paper = ("A2", 594.0, 420.0)
    view = (200.0, 150.0)
    p = place(view, _spec([(100, 60), (80, 40)], legend=(250, 30)), paper)
    g = grid(paper[1], paper[2])
    assert p.layout.fits and p.layout.paper_prefix == "ISO_full_bleed_A2"
    # План — по центру своей секции
    cx = p.view_at.x + view[0] / 2
    cy = p.view_at.y - view[1] / 2
    assert cx == pytest.approx((g.plan[0] + g.plan[2]) / 2)
    assert cy == pytest.approx((g.plan[1] + g.plan[3]) / 2)
    (t1, a1), (t2, a2), (_, legend) = p.panels
    # Таблицы — прижаты к правому краю секции, одна под другой
    for t, at in ((t1, a1), (t2, a2)):
        assert at.x + t.width == pytest.approx(g.tables[2] - PADDING)
    assert a1.y == pytest.approx(g.tables[3] - PADDING) and a2.y < a1.y - t1.height
    # Легенда — в секции слева от штампа
    assert g.legend[0] <= legend.x and legend.x + 250 <= g.legend[2]
    assert g.legend[1] <= legend.y - 30 and legend.y <= g.legend[3]


def test_legend_too_tall_for_stamp_band_does_not_fit() -> None:
    p = place((100, 100), _spec([], legend=(100, STAMP_H)), ("A3", 420.0, 297.0))
    assert not p.layout.fits


def test_too_big_drawing_is_flagged() -> None:
    p = place((2000, 2000), _spec([]), ("A0", 1189.0, 841.0))
    assert not p.layout.fits


def _fits(text: str, width: float, height: float, factor: float) -> bool:
    return text_width(text, height) * factor <= width + 1e-6


def test_fit_line_shrinks_then_compresses() -> None:
    assert fit_line("Кухня", 68, 3.5) == (3.5, 1.0)
    medium = "План електропостачання М 1:30"  # 75,7 мм при 3,5 — не влезает в 68
    height, factor = fit_line(medium, 68, 3.5)
    assert TEXT_MIN_MM <= height < 3.5 and factor == 1.0 and _fits(medium, 68, height, factor)
    long = "Будівництво сховища цивільного захисту на 1200 місць " * 2
    height, factor = fit_line(long, 68, 3.5)
    assert height == TEXT_MIN_MM and factor < 1.0 and _fits(long, 68, height, factor)


def test_fit_cell_wraps_long_value_to_two_lines() -> None:
    text = "Квартира на вулиці Вавилових, будинок 11, під'їзд 2"
    lines = fit_cell(text, 68, 3.5, lines=2)
    assert len(lines) == 2 and " ".join(line.text for line in lines) == text
    assert lines[0].dy > 0 > lines[1].dy
    for line in lines:
        assert _fits(line.text, 68, line.height, line.factor)
    # Короткое — одной строкой без уменьшения; одна строка, если графа не позволяет
    assert fit_cell("Кухня", 68, 3.5, lines=2) == [Line("Кухня", 3.5, 1.0)]
    assert len(fit_cell(text, 68, 3.5, lines=1)) == 1


def test_stamp_values_stay_inside_cells(tmp_path: Path) -> None:
    plan = make_plan([{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}])
    sheet = SheetInfo.model_validate(
        {
            "object": "Квартира на вулиці Вавилових, будинок 11, під'їзд 2, поверх 7",
            "building": "Житловий будинок з вбудованими приміщеннями громадського призначення",
            "organization": "ТОВ «Дизайн-студія інтер'єрів MV Group»",
            "code": "MV-2026-042-ЕМ.РД-01-ПРОЕКТ-КВАРТИРИ-ВАВИЛОВИХ-11-ЗМІНА-3",
            "signatures": [{"role": "Розробив", "name": "Костянтинопольський"}],
        }
    )
    doc = _build(plan.model_copy(update={"sheet": sheet}), tmp_path)
    (stamp,) = [i for i in sheet_layouts(doc)[0].query("INSERT") if i.dxf.name == STAMP_BLOCK]
    assert isinstance(stamp, Insert)
    fields = {tag: f for f in STAMP_FIELDS for tag in f.tags}
    x0 = stamp.dxf.insert.x
    for a in stamp.attribs:
        f = fields[a.dxf.tag]
        if not a.dxf.text:
            continue
        w = text_width(a.dxf.text, a.dxf.height) * a.dxf.width
        assert w <= f.width + 1e-6, a.dxf.tag
        assert a.dxf.height >= TEXT_MIN_MM or a.dxf.height == f.height
        # Центр строки — внутри графы по Y
        y = a.dxf.align_point.y - stamp.dxf.insert.y
        assert f.y - f.cell_h / 2 < y < f.y + f.cell_h / 2, a.dxf.tag
        assert x0 + f.x0 <= a.dxf.align_point.x <= x0 + f.x1
    assert stamp.get_attrib_text("OBJECT_2")  # длинный объект — на две строки


def _texts(doc: Drawing) -> set[str]:
    """Тексты листа плана, модели, блока штампа и значения атрибутов штампа."""
    sheet = sheet_layouts(doc)[0]
    out: set[str] = set()
    for layout in (sheet, doc.modelspace(), doc.blocks.get(STAMP_BLOCK)):
        out |= {m.text for m in layout.query("MTEXT") if isinstance(m, MText)}
        out |= {t.dxf.text for t in layout.query("TEXT")}
    (stamp,) = [i for i in sheet.query("INSERT") if i.dxf.name == STAMP_BLOCK]
    assert isinstance(stamp, Insert)
    return out | {a.dxf.text for a in stamp.attribs}


def test_stamp_is_block_with_attributes(tmp_path: Path) -> None:
    plan = make_plan([{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}])
    plan = plan.model_copy(update={"sheet": SheetInfo(code="KV-01-АР", stage="Р")})
    doc = _build(plan, tmp_path)
    tags = {a.dxf.tag for a in doc.blocks.get(STAMP_BLOCK).query("ATTDEF")}
    assert {"CODE", "OBJECT", "IMAGE", "STAGE", "SHEET", "SHEETS", "ROLE1", "NAME8"} <= tags
    (stamp,) = [i for i in sheet_layouts(doc)[0].query("INSERT") if i.dxf.name == STAMP_BLOCK]
    assert isinstance(stamp, Insert)
    assert stamp.get_attrib_text("CODE") == "KV-01-АР"
    assert stamp.get_attrib_text("SHEETS") == "1"


def _build(plan: Plan, tmp_path: Path) -> Drawing:
    _, contours = validate_plan(plan)
    path = tmp_path / "project.dxf"
    doc = build_project_document(plan, contours, today=date(2026, 10, 15))
    doc.saveas(path, encoding="utf-8")
    doc = readfile(path)
    assert not doc.audit().has_errors
    return doc


def test_stamp_fields_from_sheet_block(tmp_path: Path) -> None:
    plan = make_plan([{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}])
    sheet = SheetInfo.model_validate(
        {"code": "KV-01-АР", "stage": "Р", "signatures": [{"role": "Разраб.", "name": "Иванов"}]}
    )
    plan = plan.model_copy(update={"sheet": sheet})
    texts = _texts(_build(plan, tmp_path))
    assert {"KV-01-АР", "Р", "Разраб.", "Иванов", "10.26"} <= texts
    assert any(t.startswith("Формат A") for t in texts)
    assert {"Изм.", "Кол.уч", "Стадия", "Листов"} <= texts
    assert "тест" in texts  # графа 2 по умолчанию — name
    assert any(re.fullmatch(r"План помещений М 1:\d+", t) for t in texts)


def test_ukrainian_labels(tmp_path: Path) -> None:
    plan = make_plan([{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}])
    plan = plan.model_copy(update={"language": "uk"})
    texts = _texts(_build(plan, tmp_path))
    assert {"Зм.", "Кільк.", "Арк.", "Підп.", "Стадія", "Аркуш", "Аркушів"} <= texts
    # Дополнительные графы ДСТУ Б А.2.4-4: 20–22 на поле для підшивки, 26–27 под рамкой
    assert {"Інв. № ор.", "Підпис і дата", "Зам. інв. №", "Копіював"} <= texts
    assert any(t.startswith("Формат A") for t in texts)
    assert {"Експлікація приміщень", "Площа, м²", "Загальна площа", "12,00"} <= texts
    assert any(re.fullmatch(r"План приміщень М 1:\d+", t) for t in texts)
    assert not {"Изм.", "Стадия", "Листов"} & texts


def test_every_text_has_both_languages() -> None:
    for key, variants in TEXTS.items():
        assert set(variants) == {"ru", "uk"}, key
        assert all(variants.values()), key


def test_tables_go_in_columns_and_take_plan_space() -> None:
    from shtroba.sheets import arrange, columns

    g = grid(594.0, 420.0)  # A2: секция таблиц над штампом 185 мм
    tall = Panel(140, 250, lambda psp, at: None)
    a = arrange([tall, tall], g)  # одной колонкой не влезут
    assert a is not None and len(a.tables) == 2
    (_, first), (_, second) = a.tables
    assert second.x < first.x  # вторая колонка — левее
    assert a.plan[2] < g.plan[2]  # плану осталось меньше места
    assert a.plan[2] <= second.x  # и он не заходит под таблицы
    too_tall = Panel(100, 1000, lambda psp, at: None)
    assert columns([too_tall], g.tables) is None and arrange([too_tall], g) is None
    one = arrange([Panel(100, 50, lambda psp, at: None)], g)
    assert one is not None and one.plan == g.plan  # влезло над штампом — план не трогаем


def test_wrap_by_font_metrics() -> None:
    from shtroba.sheets import wrap

    text = "Штроби по стінах: 86 шт, 95,4 м (до 4 кабелів, якщо спуски ближче 150 мм)"
    lines = wrap(text, 60.0, 2.0)
    assert len(lines) > 1 and " ".join(lines) == text
    assert all(text_width(line, 2.0) <= 60.0 for line in lines)
