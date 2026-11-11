"""Terms agreed with the client apart from the estimate work: delivery, carrying, debris and so on.

The catalogue (terms.yaml next to this module) lists the items without prices. For each one the
studio records a decision in the price list (`terms` in prices.yaml, TermDecision): who does it
(the studio or the client) and how the studio's part is paid:

- included — inside the prices of the estimate work;
- fixed — a fixed sum, goes into the agreed total;
- by_fact — a rate per unit (per trip, floor, day), paid on the actual amount, no total;
- percent — of the estimate materials (`percent: materials` in the catalogue, the sum is
  computed) or a surcharge on the work done at that time (`percent: work`, paid on the fact).

An item without a decision is printed as "not agreed": it stays visible in the estimate and the
work scope, so it does not turn into a hidden service. The block goes after the estimate total
(estimate.md and the estimate sheet in Excel) and into the work scope appendix; the estimate
lines and their total do not change.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet
from pydantic import Field, model_validator

from floorplan_engine.model.schema import StrictModel
from floorplan_engine.model.texts import Language

TERMS_FILE = Path(__file__).with_name("terms.yaml")


class Who(StrEnum):
    STUDIO = "studio"
    CLIENT = "client"


class Pay(StrEnum):
    INCLUDED = "included"
    FIXED = "fixed"
    BY_FACT = "by_fact"
    PERCENT = "percent"


class TermDecision(StrictModel):
    """terms.<key> in prices.yaml: who does the item and how it is paid."""

    who: Who
    pay: Pay | None = Field(default=None, description="Как оплачивается часть студии")
    price: float | None = Field(default=None, ge=0, description="fixed — сумма, by_fact — тариф")
    unit: str | None = Field(default=None, description="Единица тарифа by_fact вместо стандартной")
    percent: float | None = Field(default=None, gt=0, le=100)
    note: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> TermDecision:
        if self.who == Who.CLIENT:
            if self.pay is not None or self.price is not None or self.percent is not None:
                raise ValueError("who: client — силами заказчика, pay, price и percent не нужны")
            return self
        if self.pay is None:
            raise ValueError("who: studio — укажите pay: included, fixed, by_fact или percent")
        need_price = self.pay in (Pay.FIXED, Pay.BY_FACT)
        if need_price and self.price is None:
            raise ValueError(f"pay: {self.pay.value} — нужна цена price")
        if not need_price and self.price is not None:
            raise ValueError(f"pay: {self.pay.value} — price не нужна")
        if (self.pay == Pay.PERCENT) != (self.percent is not None):
            raise ValueError("percent задаётся только вместе с pay: percent")
        if self.unit is not None and self.pay != Pay.BY_FACT:
            raise ValueError("unit задаётся только вместе с pay: by_fact")
        return self


class Phrase(StrictModel):
    ru: str = Field(min_length=1)
    uk: str = Field(min_length=1)

    def of(self, language: Language) -> str:
        return self.ru if language == "ru" else self.uk


class TermItem(StrictModel):
    name: Phrase
    about: Phrase
    unit: Phrase
    percent: Literal["materials", "work"] | None = None


class TermCatalog(StrictModel):
    """terms.yaml: items in the order they are printed."""

    items: dict[str, TermItem]


@cache
def load_terms() -> TermCatalog:
    """The catalogue shipped with the code (terms.yaml)."""
    return TermCatalog.model_validate({"items": yaml.safe_load(TERMS_FILE.read_text("utf-8"))})


def term_issues(terms: Mapping[str, TermDecision], catalog: TermCatalog | None = None) -> list[str]:
    """Decisions the catalogue does not allow, as "terms.<key>: why" (unknown item, a percent for
    an item that is not paid by percent)."""
    catalog = catalog or load_terms()
    out: list[str] = []
    for key, decision in terms.items():
        item = catalog.items.get(key)
        if item is None:
            out.append(f"terms.{key}: нет такого пункта, есть: {', '.join(catalog.items)}")
        elif decision.pay == Pay.PERCENT and item.percent is None:
            out.append(f"terms.{key}: этот пункт не оплачивается процентом")
    return out


TEXT: dict[str, dict[str, str]] = {
    "title": {"ru": "Обговаривается отдельно", "uk": "Обговорюється окремо"},
    "intro": {
        "ru": "Эти пункты не входят в работы сметы. По каждому до начала работ договариваются: "
        "кто делает и как это оплачивается.",
        "uk": "Ці пункти не входять до робіт кошторису. Щодо кожного до початку робіт "
        "домовляються: хто виконує і як це оплачується.",
    },
    "head": {
        "ru": "| № | Пункт | Кто | Условие | Сумма, {c} |",
        "uk": "| № | Пункт | Хто | Умова | Сума, {c} |",
    },
    "col_item": {"ru": "Пункт", "uk": "Пункт"},
    "col_who": {"ru": "Кто", "uk": "Хто"},
    "col_terms": {"ru": "Условие", "uk": "Умова"},
    "agreement": {"ru": "Договорённость", "uk": "Домовленість"},
    "studio": {"ru": "Студия", "uk": "Студія"},
    "client": {"ru": "Заказчик", "uk": "Замовник"},
    "open": {"ru": "не обговорено", "uk": "не обговорено"},
    "by_client": {"ru": "силами заказчика", "uk": "силами замовника"},
    "included": {"ru": "входит в цену работ", "uk": "входить у ціну робіт"},
    "fixed": {"ru": "фиксированная сумма", "uk": "фіксована сума"},
    "by_fact": {"ru": "по факту: {p} {c} за {u}", "uk": "за фактом: {p} {c} за {u}"},
    "materials": {"ru": "{p} % от материалов сметы", "uk": "{p} % від матеріалів кошторису"},
    "work": {
        "ru": "надбавка {p} % к работам в это время",
        "uk": "надбавка {p} % до робіт у цей час",
    },
    "subtotal": {"ru": "Итого обговорено", "uk": "Разом обговорено"},
    "grand": {"ru": "Всего со сопутствующими", "uk": "Усього із супутніми"},
    "note_open": {
        "ru": "Не обговорено с заказчиком: {names} — договоритесь до начала работ (terms в {f})",
        "uk": "Не обговорено із замовником: {names} — домовтеся до початку робіт (terms у {f})",
    },
}


def text(key: str, language: Language, **values: object) -> str:
    return TEXT[key][language].format(**values)


def _num(x: float) -> str:
    return f"{x:,.2f}".replace(",", " ").replace(".", ",").removesuffix(",00")


@dataclass(frozen=True)
class TermRow:
    """One item for this estimate, in the project language."""

    no: int
    key: str
    name: str
    about: str
    who: str  # "Студия", "Заказчик" or "—"
    terms: str  # the condition, with the studio's note
    amount: float | None  # into the agreed total: fixed or a percent of materials
    percent: float | None  # of materials: the Excel row is a formula from the material subtotal
    agreed: bool


def term_rows(
    decisions: Mapping[str, TermDecision],
    materials: float,
    currency: str,
    language: Language,
    catalog: TermCatalog | None = None,
) -> tuple[TermRow, ...]:
    """Every catalogue item with the studio's decision; materials — the estimate material
    subtotal, the base of `percent: materials`."""
    catalog = catalog or load_terms()

    def t(key: str, **values: object) -> str:
        return text(key, language, **values)

    rows: list[TermRow] = []
    for no, (key, item) in enumerate(catalog.items.items(), 1):
        d = decisions.get(key)
        amount: float | None = None
        share: float | None = None
        if d is None:
            who, terms = "—", t("open")
        elif d.who == Who.CLIENT:
            who, terms = t("client"), t("by_client")
        else:
            who = t("studio")
            if d.pay == Pay.FIXED:
                assert d.price is not None
                terms, amount = t("fixed"), d.price
            elif d.pay == Pay.BY_FACT:
                assert d.price is not None
                unit = d.unit or item.unit.of(language)
                terms = t("by_fact", p=_num(d.price), c=currency, u=unit)
            elif d.pay == Pay.PERCENT:
                assert d.percent is not None and item.percent is not None
                terms = t(item.percent, p=f"{d.percent:g}".replace(".", ","))
                if item.percent == "materials":
                    share = d.percent
                    amount = round(materials * d.percent / 100, 2)
            else:
                terms = t("included")
        if d is not None and d.note:
            terms = f"{terms}; {d.note}"
        rows.append(
            TermRow(
                no,
                key,
                item.name.of(language),
                item.about.of(language),
                who,
                terms,
                amount,
                share,
                d is not None,
            )
        )
    return tuple(rows)


def agreed_total(rows: tuple[TermRow, ...]) -> float:
    return sum(r.amount or 0.0 for r in rows)


def open_note(rows: tuple[TermRow, ...], prices_file: str, language: Language) -> str | None:
    """Estimate note about the items nobody agreed on yet; None when all are agreed."""
    names = [r.name.lower() for r in rows if not r.agreed]
    if not names:
        return None
    return text("note_open", language, names=", ".join(names), f=prices_file)


def terms_markdown(
    rows: tuple[TermRow, ...], total: float, currency: str, language: Language
) -> list[str]:
    """The block after the estimate total: a table of items and, when something is agreed for a
    sum, the total with them (total — the estimate total)."""

    def t(key: str, **values: object) -> str:
        return text(key, language, **values)

    out = [f"## {t('title')}", "", t("head", c=currency), "|---|---|---|---|---:|"]
    for r in rows:
        amount = _num(r.amount) if r.amount is not None else "—"
        out.append(f"| {r.no} | {r.name} | {r.who} | {r.terms} | {amount} |")
    agreed = agreed_total(rows)
    if agreed:
        out += [f"| | **{t('subtotal')}** | | | **{_num(agreed)}** |", ""]
        out += [f"**{t('grand')}: {_num(total + agreed)} {currency}**"]
    out.append("")
    return out


def terms_scope_markdown(rows: tuple[TermRow, ...], currency: str, language: Language) -> list[str]:
    """The section of the work scope appendix: what each item is about and what was agreed."""

    def t(key: str) -> str:
        return text(key, language)

    out = [f"## {t('title')}", "", t("intro"), ""]
    for r in rows:
        who = "" if r.who == "—" else f"{r.who.lower()}, "
        amount = "" if r.amount is None else f" — {_num(r.amount)} {currency}"
        out.append(f"- **{r.name}** — {r.about}. {t('agreement')}: {who}{r.terms}{amount}")
    out.append("")
    return out


def terms_sheet_tail(
    rows: tuple[TermRow, ...], language: Language
) -> Callable[[Worksheet, Mapping[str, str]], None]:
    """The same block on the estimate sheet, after "Total" (estimate.write_xlsx, tail): a
    percent of materials is a formula from the material subtotal, so editing a price updates it;
    cells — the estimate cells by name (a section, "total")."""

    def t(key: str) -> str:
        return text(key, language)

    def add(ws: Worksheet, cells: Mapping[str, str]) -> None:
        ws.append([])
        ws.append(["", t("title")])
        ws.cell(ws.max_row, 2).font = Font(bold=True)
        first = ws.max_row + 1
        for r in rows:
            amount: float | str | None = r.amount
            if r.percent is not None:
                base = cells.get("material")
                amount = f"=ROUND({base}*{r.percent:g}/100,2)" if base else 0
            ws.append([r.no, r.name, r.who, r.terms, "", amount])
        last = ws.max_row
        if agreed_total(rows):
            ws.append(["", t("subtotal"), "", "", "", f"=SUM(F{first}:F{last})"])
            sub = ws.max_row
            ws.append(["", t("grand"), "", "", "", f"={cells['total']}+F{sub}"])
            for row in (sub, ws.max_row):
                ws.cell(row, 2).font = Font(bold=True)
                ws.cell(row, 6).font = Font(bold=True)
        for row in range(first, ws.max_row + 1):
            ws.cell(row, 6).number_format = "#,##0.00"

    return add


def terms_scope_sheet(
    rows: tuple[TermRow, ...], currency: str, language: Language
) -> list[list[str]]:
    """Rows for the work scope sheet: item, what is agreed, the agreement."""
    out = [["", text("title", language)], ["", text("intro", language)]]
    for r in rows:
        amount = "" if r.amount is None else f" — {_num(r.amount)} {currency}"
        out.append([str(r.no), r.name, "", r.about, "", f"{r.who}: {r.terms}{amount}"])
    return out
