"""Work scope: what the price of an estimate work item covers, so there are no "hidden services".

The catalogue (work_scope.yaml next to this module) has three parts for every `work.*` item of
the estimate (estimate.LINES):

- includes — operations inside the item's price;
- excludes — what a client may expect but the price does not cover; `ref` names the estimate
  items where it is paid, no `ref` means it is not in the estimate at all. A document does not
  list them under every item (decision 2026-11-22: a "not included" list per item reads as
  hostile and mostly repeats the other items of the same estimate): what this estimate has
  elsewhere is not printed, the rest goes once into "Work outside the estimate"
  (outside_scope);
- result — the state the work is handed over in, something the client can check.

The catalogue has no prices and changes no quantities: it only describes the items the estimate
already has. Code checks it: unknown keys and references are errors (ScopeCatalog), every work
item must have a scope (missing_scope, a test).

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
    "outside": {"ru": "Работы вне сметы", "uk": "Роботи поза кошторисом"},
    "outside_intro": {
        "ru": "Этих работ в смете нет: их выполняет другой подрядчик или они согласуются "
        "до начала работ.",
        "uk": "Цих робіт у кошторисі немає: їх виконує інший підрядник або вони узгоджуються "
        "до початку робіт.",
    },
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


class Excluded(Phrase):
    ref: tuple[str, ...] = Field(
        default=(), description="Позиции сметы, где это оплачивается; пусто — в смету не входит"
    )


class WorkScope(StrictModel):
    includes: tuple[Phrase, ...] = Field(min_length=1)
    excludes: tuple[Excluded, ...] = ()
    result: Phrase


class ScopeCatalog(StrictModel):
    """work_scope.yaml: scope by estimate work key."""

    items: dict[str, WorkScope]

    @model_validator(mode="after")
    def _refs(self) -> ScopeCatalog:
        for key, scope in self.items.items():
            if not key.startswith(WORK_PREFIX) or key not in LINES:
                raise ValueError(f"{key}: нет такой работы в смете")
            for k, item in enumerate(scope.excludes):
                for ref in item.ref:
                    if not ref.startswith(WORK_PREFIX) or ref not in LINES:
                        raise ValueError(f"{key}.excludes[{k}].ref: нет работы {ref} в смете")
                    if ref == key:
                        raise ValueError(f"{key}.excludes[{k}].ref: ссылка на саму позицию")
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


def outside_scope(
    est: Estimate, language: Language, catalog: ScopeCatalog | None = None
) -> tuple[str, ...]:
    """Work a client may expect that this estimate does not have, once each, in estimate order:
    an excluded operation with no `ref`, or one whose referenced items are all absent from this
    estimate (no conduit, no insulation test). What another item of the estimate pays for is
    not listed: the item itself says it."""
    catalog = catalog or load_scope()
    present = {split_key(ln.key)[0] for ln in est.lines}
    out: dict[str, None] = {}
    for section in SECTIONS:
        for ln in est.lines:
            scope = catalog.items.get(split_key(ln.key)[0])
            if ln.section != section or scope is None:
                continue
            for item in scope.excludes:
                if not present.intersection(item.ref):
                    out.setdefault(item.of(language))
    return tuple(out)


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
    outside: Sequence[str],
    language: Language,
    terms: Sequence[str] = (),
) -> Path:
    """The appendix: the rule about extra work, then every work item with what it includes and
    its result; outside — work this estimate does not have (outside_scope), one section after
    the items; terms — the section of items agreed with the client apart from the work
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
    if outside:
        out += [f"## {t('outside')}", "", t("outside_intro"), ""]
        out += [f"- {x}" for x in outside] + [""]
    out += terms
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def scope_sheet(
    entries: tuple[ScopeEntry, ...],
    outside: Sequence[str],
    language: Language,
    terms: Sequence[Sequence[str]] = (),
) -> Callable[[Workbook], None]:
    """A sheet with the same scope for the estimate workbook (estimate.write_xlsx, extra);
    outside — work this estimate does not have (outside_scope), a block after the items;
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
        if outside:
            ws.append(["", t("outside")])
            ws.cell(ws.max_row, 2).font = Font(bold=True)
            ws.append(["", t("outside_intro")])
            for x in outside:
                ws.append(["", f"• {x}"])
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
