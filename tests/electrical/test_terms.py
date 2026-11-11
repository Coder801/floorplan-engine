"""Terms agreed apart from the estimate work: decisions are checked, every catalogue item is
printed, only a fixed sum and a percent of materials count in the agreed total.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from openpyxl import load_workbook
from pydantic import ValidationError

from floorplan_engine.electrical.estimate import LINES, Estimate, Line, PriceList, write_xlsx
from floorplan_engine.electrical.terms import (
    TermDecision,
    agreed_total,
    load_terms,
    open_note,
    term_issues,
    term_rows,
    terms_markdown,
    terms_scope_markdown,
    terms_sheet_tail,
)


def _decisions(data: dict[str, Any]) -> dict[str, TermDecision]:
    return {k: TermDecision.model_validate(v) for k, v in data.items()}


def test_catalogue_has_the_agreed_items_with_percent_bases() -> None:
    items = load_terms().items
    assert list(items) == [
        "delivery",
        "carry",
        "purchase",
        "debris",
        "dismantling",
        "power_off",
        "off_hours",
        "downtime",
        "parking",
        "no_power",
    ]
    assert {k: v.percent for k, v in items.items() if v.percent} == {
        "purchase": "materials",
        "off_hours": "work",
    }


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"who": "client", "pay": "fixed", "price": 100}, "силами заказчика"),
        ({"who": "studio"}, "укажите pay"),
        ({"who": "studio", "pay": "fixed"}, "нужна цена price"),
        ({"who": "studio", "pay": "by_fact"}, "нужна цена price"),
        ({"who": "studio", "pay": "included", "price": 100}, "price не нужна"),
        ({"who": "studio", "pay": "percent"}, "percent задаётся"),
        ({"who": "studio", "pay": "fixed", "price": 1, "percent": 5}, "percent задаётся"),
        ({"who": "studio", "pay": "fixed", "price": 1, "unit": "рейс"}, "unit задаётся"),
        ({"who": "studio", "pay": "percent", "percent": 0}, "greater than 0"),
        ({"who": "someone"}, "who"),
    ],
)
def test_decision_rejects_inconsistent_fields(data: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        TermDecision.model_validate(data)


def test_term_issues_unknown_item_and_percent_where_not_paid_so() -> None:
    issues = term_issues(
        _decisions(
            {
                "deliveri": {"who": "client"},
                "delivery": {"who": "studio", "pay": "percent", "percent": 5},
                "purchase": {"who": "studio", "pay": "percent", "percent": 5},
            }
        )
    )
    assert issues[0].startswith("terms.deliveri: нет такого пункта")
    assert issues[1] == "terms.delivery: этот пункт не оплачивается процентом"
    assert len(issues) == 2


def test_price_list_reads_terms() -> None:
    prices = PriceList.model_validate({"terms": {"debris": {"who": "client"}}})
    assert prices.terms["debris"].who == "client"
    assert PriceList().terms == {}


def test_rows_conditions_and_amounts() -> None:
    rows = term_rows(
        _decisions(
            {
                "delivery": {"who": "studio", "pay": "fixed", "price": 1500},
                "carry": {"who": "studio", "pay": "by_fact", "price": 150},
                "purchase": {"who": "studio", "pay": "percent", "percent": 7.5},
                "debris": {"who": "client", "note": "контейнер — заказчик"},
                "dismantling": {"who": "studio", "pay": "included"},
                "off_hours": {"who": "studio", "pay": "percent", "percent": 30},
                "parking": {"who": "studio", "pay": "by_fact", "price": 200, "unit": "сутки"},
            }
        ),
        materials=10000,
        currency="грн",
        language="ru",
    )
    by = {r.key: r for r in rows}
    assert len(rows) == len(load_terms().items)
    assert (by["delivery"].who, by["delivery"].terms, by["delivery"].amount) == (
        "Студия",
        "фиксированная сумма",
        1500,
    )
    assert by["carry"].terms == "по факту: 150 грн за этаж" and by["carry"].amount is None
    assert by["parking"].terms == "по факту: 200 грн за сутки"
    assert by["purchase"].terms == "7,5 % от материалов сметы"
    assert by["purchase"].amount == 750 and by["purchase"].percent == 7.5
    assert by["off_hours"].terms == "надбавка 30 % к работам в это время"
    assert by["off_hours"].amount is None  # paid on the fact
    assert by["debris"].terms == "силами заказчика; контейнер — заказчик"
    assert by["dismantling"].terms == "входит в цену работ"
    assert (by["no_power"].who, by["no_power"].terms, by["no_power"].agreed) == (
        "—",
        "не обговорено",
        False,
    )
    assert agreed_total(rows) == 2250


def test_ukrainian_rows() -> None:
    rows = term_rows(_decisions({"carry": {"who": "client"}}), 0, "грн", "uk")
    assert rows[1].name == "Підйом і занесення матеріалів"
    assert (rows[1].who, rows[1].terms) == ("Замовник", "силами замовника")
    assert rows[0].terms == "не обговорено"


def test_open_note_names_the_items_left_or_none() -> None:
    every = {k: {"who": "client"} for k in load_terms().items}
    assert open_note(term_rows(_decisions(every), 0, "грн", "ru"), "prices.yaml", "ru") is None
    del every["no_power"]
    note = open_note(term_rows(_decisions(every), 0, "грн", "ru"), "prices.yaml", "ru")
    assert note == (
        "Не обговорено с заказчиком: работа без электроэнергии — договоритесь до начала работ "
        "(terms в prices.yaml)"
    )


def test_markdown_total_only_when_something_is_agreed_for_a_sum() -> None:
    nothing = terms_markdown(term_rows({}, 1000, "грн", "ru"), 5000, "грн", "ru")
    assert nothing[0] == "## Обговаривается отдельно"
    assert not any("Итого" in line for line in nothing)
    fixed = _decisions({"delivery": {"who": "studio", "pay": "fixed", "price": 1500}})
    out = terms_markdown(term_rows(fixed, 1000, "грн", "ru"), 5000, "грн", "ru")
    assert "| 1 | Доставка материалов | Студия | фиксированная сумма | 1 500 |" in out
    assert "| | **Итого обговорено** | | | **1 500** |" in out
    assert "**Всего со сопутствующими: 6 500 грн**" in out


def test_scope_section_tells_what_each_item_is_about() -> None:
    fixed = _decisions({"delivery": {"who": "studio", "pay": "fixed", "price": 1500}})
    out = terms_scope_markdown(term_rows(fixed, 0, "грн", "ru"), "грн", "ru")
    assert out[0] == "## Обговаривается отдельно"
    assert out[4] == (
        "- **Доставка материалов** — кто привозит материалы на объект и сколько стоит рейс. "
        "Договорённость: студия, фиксированная сумма — 1 500 грн"
    )
    assert out[5].endswith("Договорённость: не обговорено")


def test_excel_percent_of_materials_is_a_formula_and_totals_follow(tmp_path: Path) -> None:
    lines = (
        Line("material", "socket_box", LINES["socket_box"][2], "шт", 10, 20.0),
        Line("rough", "work.cable", LINES["work.cable"][2], "м", 10, 30.0),
    )
    est = Estimate(lines, "грн")
    decisions = _decisions(
        {
            "delivery": {"who": "studio", "pay": "fixed", "price": 1500},
            "purchase": {"who": "studio", "pay": "percent", "percent": 10},
        }
    )
    rows = term_rows(decisions, est.subtotal("material"), "грн", "ru")
    path = write_xlsx(
        est, tmp_path / "e.xlsx", "Смета", [], "ru", tail=terms_sheet_tail(rows, "ru")
    )
    ws = load_workbook(path).worksheets[0]
    values = {row[1].value: row for row in ws.iter_rows() if row[1].value}
    assert values["Доставка материалов"][5].value == 1500
    purchase = values["Закупка материалов бригадой"][5].value
    material_total = values["Итого: Материалы"][5].coordinate
    assert purchase == f"=ROUND({material_total}*10/100,2)"
    assert str(values["Итого обговорено"][5].value).startswith("=SUM(F")
    grand = values["Всего со сопутствующими"][5].value
    total = values["Всего, грн"][5].coordinate
    assert grand == f"={total}+{values['Итого обговорено'][5].coordinate}"
