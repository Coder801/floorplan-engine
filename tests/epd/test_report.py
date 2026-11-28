from __future__ import annotations

import re
from typing import Any

import pytest

from floorplan_engine.epd.report import (
    LOGO_MARK,
    LOGO_WORD,
    LOGO_WORD_WIDTH,
    MIN_STROKE_MM,
    PANEL_BOX_MM,
    PARTS,
    PLAN_BOX_MM,
    estimate_blocks,
    group_lengths,
    joined,
    mono,
    parts_of,
    plan_svg,
    report_filename,
    report_html,
    report_title,
)

MANIFEST: dict[str, Any] = {"project": {"name": "Кв <1>", "language": "ru"}, "pages": []}


def _row(*cells: str, **extra: Any) -> dict[str, Any]:
    return {"cells": list(cells), **extra}


ESTIMATE: dict[str, Any] = {
    "title": "Смета электрики",
    "columns": ["№", "Наименование", "Ед.", "Кол.", "Цена, грн", "Сумма, грн"],
    "align": ["center", "left", "center", "center", "center", "center"],
    "rows": [
        # A build before 2026-11-23: a note after the dash in the heading
        _row("", "Черновые материалы — цены пока имитация", "", "", "", "", section=True),
        _row("1", "Кабель ВВГнг 3×1,5", "м", "10", "45", "450"),
        _row("", "Итого", "", "", "", "450"),
        # Finish materials: a bill of quantities, no price, no total (decision 2026-11-27)
        _row("", "Чистовые материалы", "", "", "", "", section=True),
        _row("1", "Розетка", "шт", "2", "", ""),
        _row("", "Черновые работы", "", "", "", "", section=True),
        _row(
            "1",
            "Прокладка кабеля",
            "м",
            "10",
            "34",
            "340",
            scope={"includes": ["разметка трассы", "фиксация"], "result": "кабель закреплён"},
        ),
        _row("", "Итого", "", "", "", "340"),
        _row("", "Чистовые работы", "", "", "", "", section=True),
        _row("1", "Установка механизмов", "шт", "2", "100", "200"),
        _row("", "Итого", "", "", "", "1 200,50"),
    ],
    "total": ["", "Всего", "", "", "", "1 990,50"],
    "notes": ["Цены: prices.yaml"],
}


def _page(
    view: list[float] | None = None, items: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    page: dict[str, Any] = {"size": [420, 297], "items": items or [], "estimate": ESTIMATE}
    if view is not None:
        page["view"] = view
    return page


def test_parts_in_report_order_unknown_refused() -> None:
    assert parts_of(["work_finish", "plan", "plan"]) == ("plan", "work_finish")
    with pytest.raises(ValueError, match="photos"):
        parts_of(["photos"])


@pytest.mark.parametrize(
    ("colour", "out"),
    [
        ("#000000", "#000000"),
        ("#f28e2b", "#000000"),  # a group colour
        ("#ff7fdf", "#000000"),  # LED
        ("#ffffff", "#ffffff"),  # label backing
        ("#eef0f2", "#ffffff"),  # light wall fill
        ("#ffffff80", "#ffffff"),
    ],
)
def test_mono(colour: str, out: str) -> None:
    assert mono(colour) == out


def test_plan_cut_to_view_and_black_and_white() -> None:
    items: list[dict[str, Any]] = [
        {"k": "s", "c": "#e15759", "w": 0.5, "d": "M10 10L20 10"},
        {"k": "f", "c": "#ffffff", "d": "M0 0L1 0L1 1Z"},
    ]
    svg = plan_svg(_page([100, 50, 300, 150], items))  # wider than tall: as it is
    assert 'viewBox="0 0 200 100"' in svg
    assert "translate(-100 -50)" in svg and "rotate" not in svg
    assert 'stroke="#000000"' in svg and 'fill="#ffffff"' in svg
    assert "#e15759" not in svg


def test_tall_plan_lies_down_and_thin_lines_thickened() -> None:
    items = [{"k": "s", "c": "#000000", "w": 0.01, "d": "M0 0L0 400"}]
    svg = plan_svg(_page([0, 0, 297, 420], items))  # taller than wide: turned
    assert 'viewBox="0 0 420 297"' in svg
    assert "translate(0 297) rotate(-90)" in svg
    box = PLAN_BOX_MM["portrait"]
    scale = min(box[0] / 420, box[1] / 297)
    assert f'stroke-width="{MIN_STROKE_MM / scale:.2f}"' in svg


def test_wide_plan_never_turned() -> None:
    for box in PLAN_BOX_MM.values():
        assert "rotate" not in plan_svg(_page(), box)  # 420 × 297 sheet
    tall = plan_svg(_page([0, 0, 100, 300]), PLAN_BOX_MM["landscape"])
    assert "rotate(-90)" in tall


def test_screen_column() -> None:
    assert "@media screen { body { max-width: 1024px;" in report_html(MANIFEST, None, [])


def test_brand_is_the_mark_and_wordmark() -> None:
    html = report_html(MANIFEST, None, [])
    assert 'role="img" aria-label="Shtroba"' in html
    assert html.count("<svg") == 2  # paths, no font


def test_page_orientation() -> None:
    assert "size: A4 portrait" in report_html(MANIFEST, None, [])
    assert "size: A4 landscape" in report_html(MANIFEST, None, [], "landscape")


def test_blocks_by_heading() -> None:
    blocks = estimate_blocks(ESTIMATE, "ru")
    assert [b.section for b in blocks] == ["material_rough", "material_finish", "rough", "finish"]
    assert blocks[0].title == "Черновые материалы"
    assert [r["cells"][1] for r in blocks[0].rows] == ["Кабель ВВГнг 3×1,5"]
    assert blocks[0].subtotal is not None and not blocks[0].listed
    assert blocks[1].listed and blocks[1].subtotal is None


def test_unknown_heading_skipped() -> None:
    est = {**ESTIMATE, "rows": [_row("", "Прочее", "", "", "", "", section=True), _row("1", "x")]}
    assert estimate_blocks(est, "ru") == []


def test_only_chosen_sections() -> None:
    html = report_html(MANIFEST, _page(), ["material_finish", "work_rough"])
    assert "Розетка" in html and "Прокладка кабеля" in html
    assert "Кабель ВВГнг" not in html and "Установка механизмов" not in html
    assert "r-plan" not in html  # no plan
    assert "<b>Входит:</b> разметка трассы; фиксация." in html
    assert "<b>Результат:</b> кабель закреплён" in html
    assert "Цены — после выбора серии" in html  # in place of the finish materials total
    assert '<div class="r-closing__grand">340,00</div>' in html  # finish materials have no price


def test_all_parts_summary_without_a_provisional_mark() -> None:
    html = report_html(MANIFEST, _page(), PARTS)
    assert '<section class="r-plan">' in html
    assert ">1 990,50<" in html  # 450 + 340 + 1 200,50: finish materials stay out
    assert "ориентировочные" not in html and "≈" not in html and " !" not in html
    assert '<span class="r-closing__sum">450</span>' in html
    assert "prices.yaml" not in html  # studio notes stay out of the report
    assert "Кв &lt;1&gt;" in html and "Кв <1>" not in html


def test_one_section_closing_block() -> None:
    html = report_html(MANIFEST, _page(), ["work_finish"])
    assert '<div class="r-closing__grand">1 200,50</div>' in html
    assert "ориентировочные" not in html  # work prices are not approximate


def test_no_closing_block_without_prices() -> None:
    rows = [
        _row("", "Черновые материалы", "", "", "", "", section=True),
        _row("1", "Кабель", "м", "10", "—", "—"),
    ]
    html = report_html(MANIFEST, _page() | {"estimate": {**ESTIMATE, "rows": rows}}, PARTS)
    assert "r-closing" not in html.split("</style>")[1]


def test_header_and_page_margin() -> None:
    html = report_html(MANIFEST, _page(), ["plan", "work_rough"])
    assert '<div class="r-head__project">Кв &lt;1&gt;</div>' in html
    assert '<div class="r-head__title">Смета электрики</div></section>' in html
    assert "r-head__part" not in html  # one line: no list of parts
    assert '"Страница " counter(page) " из " counter(pages)' in html
    assert 'content: "Shtroba · Кв \\3C 1>"' in html  # the name cannot close <style>


def test_work_scope_in_appendix_not_in_table() -> None:
    html = report_html(MANIFEST, _page(), ["work_rough", "work_finish"])
    table, _, appendix = html.partition('<section class="r-appendix">')
    assert "разметка трассы" not in table  # the table rows carry no scope
    assert table.count('<p class="r-lines__ref">') == 1  # only the work section with a scope
    assert "в приложении «Что входит в работы»" in table
    assert '<h2 class="r-appendix__title">Приложение. Что входит в работы</h2>' in appendix
    assert '<h3 class="r-appendix__group">Черновые работы</h3>' in appendix
    assert '<span class="r-appendix__no">1</span>Прокладка кабеля' in appendix
    assert "<b>Входит:</b> разметка трассы; фиксация." in appendix
    assert "<b>Результат:</b> кабель закреплён" in appendix
    assert "Установка механизмов" not in appendix  # no scope, not listed
    assert appendix.index("r-appendix") < len(appendix)
    assert html.index("r-closing__grand") < html.index('<section class="r-appendix">')


def test_no_appendix_without_work_scope() -> None:
    html = report_html(MANIFEST, _page(), ["material_rough", "work_finish"])
    assert (
        '<section class="r-appendix">' not in html
        and "r-lines__ref" not in html.split("</style>")[1]
    )


def test_not_split_materials_shown_once() -> None:
    rows = [
        _row("", "Материалы", "", "", "", "", section=True),
        _row("1", "Кабель", "м", "1", "1", "1"),
        _row("", "Итого", "", "", "", "1"),
    ]
    html = report_html(MANIFEST, _page() | {"estimate": {**ESTIMATE, "rows": rows}}, PARTS[1:3])
    assert html.count(">Материалы</h2>") == 1


def test_missing_wiring_and_section() -> None:
    html = report_html(MANIFEST, None, PARTS)
    assert "В сборке нет листа проводки" in html and "В сборке нет сметы электрики" in html
    rows = ESTIMATE["rows"][:3]
    page = _page() | {"estimate": {**ESTIMATE, "rows": rows}}
    html = report_html(MANIFEST, page, ["work_rough"])
    assert (
        '<h2 class="r-lines__title">Черновые работы</h2>' in html
        and "В смете нет этого раздела" in html
    )


def test_project_language_and_fallback() -> None:
    uk = report_html({"project": {"name": "Кв", "language": "uk"}}, None, ["plan"])
    assert '<html lang="uk">' in uk and "План електрики" in uk
    assert '<html lang="ru">' in report_html({}, None, [])


def test_deterministic() -> None:
    assert report_html(MANIFEST, _page(), PARTS) == report_html(MANIFEST, _page(), PARTS)


def test_sections_bring_only_their_styles() -> None:
    css = report_html(MANIFEST, _page(), ["work_rough"]).split("</style>")[0]
    assert ".r-lines__table" in css and ".r-closing" in css and ".r-plan" not in css
    css = report_html(MANIFEST, _page(), ["plan"]).split("</style>")[0]
    assert ".r-plan" in css and ".r-lines" not in css
    # Every rule but the page box is inside a section class
    rules = [r.strip() for r in css.split("<style>")[1].split("}") if "{" in r]
    loose = [
        r
        for r in rules
        if not r.startswith((".r-", "@page", "html, body", "@bottom", "@media", "@font-face"))
    ]
    assert loose == []


@pytest.mark.parametrize(
    ("path", "x_max", "y_min"),
    [(LOGO_MARK, 16.0, -12.0), (LOGO_WORD, LOGO_WORD_WIDTH, -14.0)],
)
def test_logo_paths_stay_in_their_box(path: str, x_max: float, y_min: float) -> None:
    # Numbers glued together when the path was wrapped into lines would land far outside
    # (x right of 0, y above the baseline; H and V take one number, so no pairs)
    numbers = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", path)]
    assert numbers and all(y_min <= n <= x_max for n in numbers)
    assert "Z" in path and not re.search(r"\.\d{3}", path)


def test_plan_full_width_capped_in_print() -> None:
    svg = plan_svg(_page(), PLAN_BOX_MM["landscape"])
    assert f'style="--plan-max-h: {PLAN_BOX_MM["landscape"][1]:g}mm"' in svg
    assert '<clipPath id="r-plan-clip"><rect width="420" height="297"/>' in svg
    assert '<g clip-path="url(#r-plan-clip)">' in svg
    css = report_html(MANIFEST, _page(), ["plan"]).split("</style>")[0]
    assert ".r-plan__drawing svg { display: block; width: 100%; height: auto;" in css
    assert "@media print { .r-plan__drawing svg { max-height: var(--plan-max-h); } }" in css


def test_font_embedded_once_per_weight() -> None:
    css = report_html(MANIFEST, None, []).split("</style>")[0]
    assert css.count("@font-face") == 2
    assert "font-weight: 400; src: url(data:font/woff2;base64," in css
    assert "font-weight: 600; src: url(data:font/woff2;base64," in css
    assert '"Shtroba Report Sans"' in css and "Liberation" not in css


def test_tables_flush_left() -> None:
    css = report_html(MANIFEST, _page(), ["work_rough"]).split("</style>")[0]
    assert ".r-lines__table td:first-child { padding-left: 0; }" in css


PANEL: dict[str, Any] = {
    "texts": {"grid": "Ввод от сети 230 В"},
    "devices": [
        {"id": "QS1", "kind": "input", "label": "C40 2P"},
        {"id": "QF1", "kind": "breaker", "label": "C10", "group": "QF1"},
    ],
    "groups": {"QF1": {"purpose": "Освещение — Кухня", "cable": "3x1.5", "power": 130}},
}


def test_panel_part_last_on_a_new_page_as_wide_as_the_column() -> None:
    page = report_html(MANIFEST, {"estimate": ESTIMATE}, ["panel", "work_rough"], panel=PANEL)
    assert PARTS[-1] == "panel"
    assert page.index('class="r-closing"') < page.index('class="r-panel"')
    assert "Однолинейная схема щита" in page and "Ввод от сети 230 В" in page
    tiers = re.findall(r'<div class="r-panel__tier"><svg[^>]* width="([\d.]+)mm"', page)
    assert tiers and all(float(w) <= PANEL_BOX_MM["portrait"][0] + 0.01 for w in tiers)
    assert "break-before: page" in page and "МОЩНОСТЬ, ВТ" in page


def test_panel_alone_titles_the_report_and_without_panel_says_so() -> None:
    alone = report_html(MANIFEST, None, ["panel"], panel=PANEL)
    assert re.search(r'r-head__title">Однолинейная схема щита<', alone) or (
        "<title>Кв &lt;1&gt; · Однолинейная схема щита</title>" in alone
    )
    assert "В сборке нет щита" in report_html(MANIFEST, None, ["panel"])


def test_joined_pieces_become_one_line() -> None:
    assert joined("M0 0L5 0M5 0L5 5M9 9L10 10") == "M0 0L5 0L5 5M9 9L10 10"
    assert joined("M0 0L1 0L1 1ZM0 0L2 2") == "M0 0L1 0L1 1ZL2 2"


def test_lighting_lines_dashed_labels_solid() -> None:
    items = [
        {"k": "s", "c": "#f28e2b", "w": 0.25, "l": "W-CABLE-LIGHT", "o": "wire:w1",
         "d": "M0 0L10 0M10 0L10 10"},
        {"k": "s", "c": "#f28e2b", "w": 0.25, "l": "W-CABLE-LIGHT", "o": "wire_len:w1",
         "d": "M1 1L2 1"},
        {"k": "s", "c": "#4e79a7", "w": 0.25, "l": "W-CABLE-SOCKET", "o": "wire:w2",
         "d": "M0 5L10 5"},
    ]  # fmt: skip
    svg = plan_svg(_page(None, items))
    paths = svg.split("<path")[1:]
    assert 'd="M0 0L10 0L10 10"' in paths[0] and "stroke-dasharray" in paths[0]
    assert "stroke-dasharray" not in paths[1] and "stroke-dasharray" not in paths[2]


def test_plan_legend_grid() -> None:
    box: list[dict[str, Any]] = [
        {"k": "f", "c": "#ffffff", "l": "W-BOX", "o": "box:b1", "d": "M0 0L5 0L5 5L0 5Z"},
        {"k": "s", "c": "#ff0000", "w": 0.25, "l": "W-BOX", "o": "box:b1", "d": "M0 0L5 0L5 5"},
    ]
    legend: list[dict[str, Any]] = [
        {"key": "socket", "text": "Розетка", "items": [{"k": "s", "c": "#ff0000", "w": 0.25,
                                                        "d": "M40 800L44 802"}]},
        {"key": "empty", "text": "Без значка", "items": []},
    ]  # fmt: skip
    html = report_html(MANIFEST, _page(None, box), ["plan"], legend=legend)
    grid = html.split('<div class="r-plan__legend">')[1]
    keys = grid.count('class="r-plan__key"')
    assert keys == 4  # two lines, the box, the socket; an entry without a symbol is skipped
    assert "Линии освещения" in grid and "Распаечная коробка" in grid and "Розетка" in grid
    assert grid.count("stroke-dasharray") == 1
    assert "#ff0000" not in grid
    assert "grid-template-columns: repeat(auto-fill" in html


def test_old_build_heading_note_is_dropped_and_priced_finish_materials_stay_out() -> None:
    """A build before 2026-11-27 priced finish materials and gave them a total: the report still
    leaves them out of the closing block; the old note after the dash is not part of the title."""
    assert estimate_blocks(ESTIMATE, "ru")[0].title == "Черновые материалы"
    rows = [
        _row("", "Чистовые материалы", "", "", "", "", section=True),
        _row("1", "Розетка", "шт", "2", "180", "360"),
        _row("", "Итого", "", "", "", "360"),
        _row("", "Черновые работы", "", "", "", "", section=True),
        _row("1", "Прокладка кабеля", "м", "10", "34", "340"),
        _row("", "Итого", "", "", "", "340"),
    ]
    page = {**_page(), "estimate": {**ESTIMATE, "rows": rows}}
    html = report_html(MANIFEST, page, ["material_finish", "work_rough"])
    assert '<div class="r-closing__grand">340,00</div>' in html


def test_panel_legend_explains_the_abbreviations() -> None:
    page = report_html(MANIFEST, None, ["panel"], panel=PANEL)
    assert "АВ — автоматический выключатель" in page


def test_panel_warnings_listed_major_first_and_lengths_from_wiring() -> None:
    panel = {
        **PANEL,
        "warnings": [
            {"severity": "minor", "text": "Вводной автомат — допущение"},
            {"severity": "major", "text": "QF1: перегрузка", "group": "QF1"},
        ],
    }
    wiring = {
        "tables": [
            {
                "columns": ["Группа", "Автомат", "Кабель", "Длина, м", "P, кВт"],
                "rows": [{"cells": ["QF1", "C10", "3x1.5", "51,6", "0,13"], "group": "QF1"}],
            }
        ]
    }
    page = report_html(MANIFEST, wiring, ["panel"], panel=panel)
    assert "Замечания расчёта" in page
    assert page.index("QF1: перегрузка") < page.index("Вводной автомат — допущение")
    assert 'r-panel__warning--major">QF1: перегрузка' in page
    assert "51,6 м" in page
    assert group_lengths(wiring) == {"QF1": "51,6"} and group_lengths(None) == {}
    assert "* — допущение" not in page  # nothing assumed in this panel


def test_report_title_and_pdf_filename() -> None:
    assert report_title([], "ru") == "Смета электрики"
    assert report_title(["plan", "work_rough"], "uk") == "Кошторис електрики"
    assert report_title(["plan"], "ru") == "План электрики"
    assert report_title(["panel"], "ru") == "Однолинейная схема щита"
    manifest = {"project": {"name": 'Кв 42 / Київ: "А"', "language": "uk"}}
    assert report_filename(manifest, ["panel"]) == "Кв 42 Київ А — Однолінійна схема щита.pdf"
    assert report_filename({"project": {}}, []) == "Смета электрики.pdf"
