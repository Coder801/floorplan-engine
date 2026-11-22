"""Work scope: what the price of an estimate work item covers, so there are no "hidden services".

The catalogue (work_scope.yaml next to this module) has two parts for every `work.*` item of
the estimate (estimate.LINES):

- includes — operations inside the item's price;
- result — the state the work is handed over in, something the client can check.

There is no "not included" list (decision 2026-11-22): first it was printed under every item
and read as hostile, then it went once into a "Work outside the estimate" section, and that
section was removed too. What is not in the item's composition is extra work, agreed before it
is done (the "extra" line of the appendix).

The catalogue has no prices and changes no quantities: it only describes the items the estimate
already has. Code checks it: unknown keys are errors (ScopeCatalog), every work item must have
a scope (missing_scope, a test).

For a project the scope goes next to the estimate: out/work-scope.md (an appendix that can be
attached to a contract) and a second sheet in out/estimate.xlsx.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from pydantic import Field, model_validator

from floorplan_engine.electrical.estimate import (
    LINES,
    SECTIONS,
    WORK_PREFIX,
    Estimate,
    Section,
    format_number,
    split_key,
)
from floorplan_engine.electrical.estimate import text as estimate_text
from floorplan_engine.model.schema import StrictModel
from floorplan_engine.model.texts import Language

SCOPE_FILE = Path(__file__).with_name("work_scope.yaml")
WORK_SCOPE_MD = "work-scope.md"  # in the project's out/, next to the estimate

TEXT: dict[str, dict[str, str]] = {
    "title": {"ru": "Состав работ по электрике: {name}", "uk": "Склад робіт з електрики: {name}"},
    "sheet": {"ru": "Состав работ", "uk": "Склад робіт"},
    "intro": {
        "ru": "Приложение к смете электрики. По каждой позиции работ: что входит в её цену "
        "и в каком виде работа сдаётся.",
        "uk": "Додаток до кошторису електрики. Для кожної позиції робіт: що входить у її ціну "
        "і в якому вигляді робота здається.",
    },
    "extra": {
        "ru": "Работа, которой нет в составе позиций, — дополнительная: её объём и цена "
        "согласуются до выполнения.",
        "uk": "Робота, якої немає у складі позицій, — додаткова: її обсяг і ціна "
        "узгоджуються до виконання.",
    },
    "includes": {"ru": "Входит", "uk": "Входить"},
    "result": {"ru": "Результат", "uk": "Результат"},
    "col_work": {"ru": "Работа", "uk": "Робота"},
    "note_scope": {
        "ru": "Состав работ по позициям — {f} и лист «{s}» в Excel",
        "uk": "Склад робіт за позиціями — {f} і аркуш «{s}» в Excel",
    },
}


def text(key: str, language: Language, **values: object) -> str:
    return TEXT[key][language].format(**values)


class Phrase(StrictModel):
    """One operation or result, in both project languages."""

    ru: str = Field(min_length=1)
    uk: str = Field(min_length=1)

    def of(self, language: Language) -> str:
        return self.ru if language == "ru" else self.uk


class WorkScope(StrictModel):
    includes: tuple[Phrase, ...] = Field(min_length=1)
    result: Phrase


class ScopeCatalog(StrictModel):
    """work_scope.yaml: scope by estimate work key."""

    items: dict[str, WorkScope]

    @model_validator(mode="after")
    def _keys(self) -> ScopeCatalog:
        for key in self.items:
            if not key.startswith(WORK_PREFIX) or key not in LINES:
                raise ValueError(f"{key}: нет такой работы в смете")
        return self


def parse_scope(data: object) -> ScopeCatalog:
    return ScopeCatalog.model_validate({"items": data or {}})


@cache
def load_scope() -> ScopeCatalog:
    """The catalogue shipped with the code (work_scope.yaml)."""
    return parse_scope(yaml.safe_load(SCOPE_FILE.read_text("utf-8")))


def missing_scope(catalog: ScopeCatalog) -> list[str]:
    """Estimate work items without a scope: every one of them is a place for a hidden service."""
    return [k for k in LINES if k.startswith(WORK_PREFIX) and k not in catalog.items]


@dataclass(frozen=True)
class ScopeEntry:
    """Scope of one work item of an estimate, in the project language."""

    section: Section
    no: int  # item number inside its section, as in the estimate
    key: str
    name: str
    unit: str
    qty: float
    includes: tuple[str, ...]
    result: str


def scope_entries(
    est: Estimate, language: Language, catalog: ScopeCatalog | None = None
) -> tuple[ScopeEntry, ...]:
    """Scope for the work items of this estimate, in estimate order."""
    catalog = catalog or load_scope()
    out: list[ScopeEntry] = []
    for section in SECTIONS:
        rows = [ln for ln in est.lines if ln.section == section]
        for no, ln in enumerate(rows, 1):
            scope = catalog.items.get(split_key(ln.key)[0])
            if scope is None:
                continue
            out.append(
                ScopeEntry(
                    section,
                    no,
                    ln.key,
                    ln.name,
                    ln.unit,
                    ln.qty,
                    tuple(p.of(language) for p in scope.includes),
                    scope.result.of(language),
                )
            )
    return tuple(out)


def _qty(entry: ScopeEntry) -> str:
    return f"{format_number(entry.qty, 1).removesuffix(',0')} {entry.unit}"


def write_scope_markdown(
    entries: tuple[ScopeEntry, ...],
    path: Path,
    title: str,
    language: Language,
    terms: Sequence[str] = (),
) -> Path:
    """The appendix: the rule about extra work, then every work item with what it includes and
    its result; terms — the section of items agreed with the client apart from the work
    (terms.terms_scope_markdown)."""

    def t(key: str) -> str:
        return text(key, language)

    consumables = estimate_text("note_consumables", language)
    out = [f"# {title}", "", t("intro"), "", t("extra"), "", f"{consumables}.", ""]
    for section in SECTIONS:
        rows = [e for e in entries if e.section == section]
        if not rows:
            continue
        out += [f"## {estimate_text(section, language)}", ""]
        for e in rows:
            out += [f"### {e.no}. {e.name} — {_qty(e)}", "", f"**{t('includes')}:**", ""]
            out += [f"- {x}" for x in e.includes]
            out += ["", f"**{t('result')}:** {e.result}", ""]
    out += terms
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def scope_sheet(
    entries: tuple[ScopeEntry, ...],
    language: Language,
    terms: Sequence[Sequence[str]] = (),
) -> Callable[[Workbook], None]:
    """A sheet with the same scope for the estimate workbook (estimate.write_xlsx, extra);
    terms — rows of the items agreed apart from the work (terms.terms_scope_sheet)."""

    def t(key: str) -> str:
        return text(key, language)

    def add(wb: Workbook) -> None:
        ws = wb.create_sheet(t("sheet")[:31])
        ws.append([t("extra")])
        ws.append([f"{estimate_text('note_consumables', language)}."])
        ws.append([])
        ws.append(
            [
                estimate_text("col_no", language),
                t("col_work"),
                estimate_text("col_qty", language),
                t("includes"),
                t("result"),
            ]
        )
        head = ws.max_row
        for cell in ws[head]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        wrap = Alignment(vertical="top", wrap_text=True)
        for section in SECTIONS:
            rows = [e for e in entries if e.section == section]
            if not rows:
                continue
            ws.append(["", estimate_text(section, language)])
            ws.cell(ws.max_row, 2).font = Font(bold=True)
            for e in rows:
                ws.append(
                    [
                        e.no,
                        e.name,
                        _qty(e),
                        "\n".join(f"• {x}" for x in e.includes),
                        e.result,
                    ]
                )
                for cell in ws[ws.max_row]:
                    cell.alignment = wrap
        for k, row in enumerate(terms):
            ws.append(list(row))
            if k == 0:
                ws.cell(ws.max_row, 2).font = Font(bold=True)
            for cell in ws[ws.max_row]:
                cell.alignment = wrap
        for letter, width in zip("ABCDE", (5, 34, 12, 62, 52), strict=True):
            ws.column_dimensions[letter].width = width
        ws.freeze_panes = f"A{head + 1}"

    return add
