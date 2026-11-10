"""Work scope: what the price of an estimate work item covers, so there are no "hidden services".

The catalogue (work_scope.yaml next to this module) has three parts for every `work.*` item of
the estimate (estimate.LINES):

- includes — operations inside the item's price;
- excludes — what a client may expect but the price does not cover; `ref` names the estimate
  items where it is paid, no `ref` means it is not in the estimate at all;
- result — the state the work is handed over in, something the client can check.

The catalogue has no prices and changes no quantities: it only describes the items the estimate
already has. Code checks it: unknown keys and references are errors (ScopeCatalog), every work
item must have a scope (missing_scope, a test).

For a project the scope goes next to the estimate: out/work-scope.md (an appendix that can be
attached to a contract) and a second sheet in out/estimate.xlsx. A reference is printed with the
name of the item in this estimate; a referenced item the estimate does not have (no conduit, no
chases) is marked as not planned in it.
"""

from __future__ import annotations

from collections.abc import Callable
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
        "ru": "Приложение к смете электрики. По каждой позиции работ: что входит в её цену, "
        "что не входит и где это учтено, в каком виде работа сдаётся.",
        "uk": "Додаток до кошторису електрики. Для кожної позиції робіт: що входить у її ціну, "
        "що не входить і де це враховано, у якому вигляді робота здається.",
    },
    "extra": {
        "ru": "Работа, которой нет в составе позиций, — дополнительная: её объём и цена "
        "согласуются до выполнения.",
        "uk": "Робота, якої немає у складі позицій, — додаткова: її обсяг і ціна "
        "узгоджуються до виконання.",
    },
    "includes": {"ru": "Входит", "uk": "Входить"},
    "excludes": {"ru": "Не входит", "uk": "Не входить"},
    "result": {"ru": "Результат", "uk": "Результат"},
    "col_work": {"ru": "Работа", "uk": "Робота"},
    "paid_one": {"ru": "отдельная позиция {names}", "uk": "окрема позиція {names}"},
    "paid_many": {"ru": "отдельные позиции {names}", "uk": "окремі позиції {names}"},
    "paid_absent": {
        "ru": "в этой смете не предусмотрено",
        "uk": "у цьому кошторисі не передбачено",
    },
    "not_in_estimate": {"ru": "в смету не входит", "uk": "до кошторису не входить"},
    "note_scope": {
        "ru": "Состав работ по позициям (что входит и что не входит) — {f} и лист «{s}» в Excel",
        "uk": "Склад робіт за позиціями (що входить і що не входить) — {f} і аркуш «{s}» в Excel",
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
    excludes: tuple[str, ...]  # each with the place where it is paid
    result: str


def _excluded(item: Excluded, names: dict[str, str], language: Language) -> str:
    """ "штроба — отдельные позиции «…», «…»": where the excluded operation is paid."""
    if not item.ref:
        where = text("not_in_estimate", language)
    else:
        found = [f"«{names[ref]}»" for ref in item.ref if ref in names]
        if not found:
            where = text("paid_absent", language)
        else:
            key = "paid_one" if len(found) == 1 else "paid_many"
            where = text(key, language, names=", ".join(found))
    return f"{item.of(language)} — {where}"


def scope_entries(
    est: Estimate, language: Language, catalog: ScopeCatalog | None = None
) -> tuple[ScopeEntry, ...]:
    """Scope for the work items of this estimate, in estimate order; references use the names
    the items have in this estimate (a price list may rename them)."""
    catalog = catalog or load_scope()
    names = {ln.key: ln.name for ln in est.lines}
    out: list[ScopeEntry] = []
    for section in SECTIONS:
        rows = [ln for ln in est.lines if ln.section == section]
        for no, ln in enumerate(rows, 1):
            scope = catalog.items.get(ln.key)
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
                    tuple(_excluded(x, names, language) for x in scope.excludes),
                    scope.result.of(language),
                )
            )
    return tuple(out)


def _qty(entry: ScopeEntry) -> str:
    return f"{format_number(entry.qty, 1).removesuffix(',0')} {entry.unit}"


def write_scope_markdown(
    entries: tuple[ScopeEntry, ...], path: Path, title: str, notes: list[str], language: Language
) -> Path:
    """The appendix: the rule about extra work, then every work item with what it includes,
    what it does not and its result; notes — what the whole estimate leaves out."""

    def t(key: str) -> str:
        return text(key, language)

    out = [f"# {title}", "", t("intro"), "", t("extra"), ""]
    for section in SECTIONS:
        rows = [e for e in entries if e.section == section]
        if not rows:
            continue
        out += [f"## {estimate_text(section, language)}", ""]
        for e in rows:
            out += [f"### {e.no}. {e.name} — {_qty(e)}", "", f"**{t('includes')}:**", ""]
            out += [f"- {x}" for x in e.includes]
            if e.excludes:
                out += ["", f"**{t('excludes')}:**", ""]
                out += [f"- {x}" for x in e.excludes]
            out += ["", f"**{t('result')}:** {e.result}", ""]
    out += [f"- {n}" for n in notes]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def scope_sheet(
    entries: tuple[ScopeEntry, ...], notes: list[str], language: Language
) -> Callable[[Workbook], None]:
    """A sheet with the same scope for the estimate workbook (estimate.write_xlsx, extra)."""

    def t(key: str) -> str:
        return text(key, language)

    def add(wb: Workbook) -> None:
        ws = wb.create_sheet(t("sheet")[:31])
        ws.append([t("extra")])
        ws.append([])
        ws.append(
            [
                estimate_text("col_no", language),
                t("col_work"),
                estimate_text("col_qty", language),
                t("includes"),
                t("excludes"),
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
                        "\n".join(f"• {x}" for x in e.excludes),
                        e.result,
                    ]
                )
                for cell in ws[ws.max_row]:
                    cell.alignment = wrap
        ws.append([])
        for note in notes:
            ws.append(["", note])
        for letter, width in zip("ABCDEF", (5, 34, 12, 52, 62, 46), strict=True):
            ws.column_dimensions[letter].width = width
        ws.freeze_panes = f"A{head + 1}"

    return add
