"""Price lists: the studio's with the project's on top, the market sample, the studio price page.

Layers by key (decision 2026-11-25): the studio list (prices.yaml next to the projects, edited on
the studio price page) is the base, the project list (prices.yaml in the project folder) changes
only the keys it names, the price service fills the rest (pricing.Prices). Before, a project list
replaced the studio one as a whole, so a studio edit never reached a project that had one. A
project list should hold only the project's exceptions."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from floorplan_engine.electrical.estimate import (
    HINTS,
    LINES,
    PRICES_FILE,
    WORK_PREFIX,
    PriceList,
    PriceSource,
    edit_price_items,
    split_key,
    unknown_keys,
)
from floorplan_engine.electrical.market import (
    MARKET_FILE,
    MarketSample,
    item_spread,
    period,
    used_sources,
)
from floorplan_engine.electrical.pricing import Prices, mock_price
from floorplan_engine.electrical.splices import DEFAULT_SPLICE, Splice
from floorplan_engine.electrical.terms import term_issues
from floorplan_engine.model.intake import (
    Stage,
)
from floorplan_engine.model.schema import Electrical
from floorplan_engine.pipeline.assessment import Assessment, plumbing_of
from floorplan_engine.plumbing.estimate import LINES as PLUMBING_LINES
from floorplan_engine.validation.issues import (
    Issue,
    load_yaml,
    parse_model,
)


def sheet_inputs(
    project: Path, assessment: Assessment, service: PriceSource | None
) -> tuple[Electrical | None, Prices | None, list[Issue]]:
    """What goes on the sheets besides the plan: electrical (if the stage builds) and estimate
    prices, the project or studio price list (if present and readable) on top of the price
    service; prices are needed even without electrical if plumbing builds."""
    report = assessment.report
    elec_status = assessment.status(Stage.ELECTRICAL)
    elec = report.electrical if elec_status is not None and elec_status.status.builds else None
    if elec is None and plumbing_of(assessment) is None:
        return None, None, []
    own, issues = load_price_layers(project)
    return elec, Prices(own, service), issues


def price_files(project: Path) -> list[Path]:
    """The price lists of the project that exist, bottom layer first: the studio list
    (prices.yaml in the folder above the projects, next to studio.yaml), then the project's own
    (prices.yaml in its folder)."""
    return [p for p in (project.parent / PRICES_FILE, project / PRICES_FILE) if p.is_file()]


def find_prices(project: Path) -> Path | None:
    """The price list named in the estimate notes: the project's own if it has one (it is the
    top layer), otherwise the studio list; None if neither exists."""
    files = price_files(project)
    return files[-1] if files else None


def load_price_layers(project: Path) -> tuple[PriceList | None, list[Issue]]:
    """The estimate price list of the project: the studio list with the project's on top, key
    by key (merge_prices). An error in either list stops it: None and the errors, as one list
    did before; no list — None without errors."""
    merged: PriceList | None = None
    for path in price_files(project):
        layer, issues = load_prices(path)
        if layer is None:
            return None, issues
        merged = layer if merged is None else merge_prices(merged, layer)
    return merged, []


def merge_prices(base: PriceList, top: PriceList) -> PriceList:
    """top over base: its items and terms win key by key, the rest of base stays; currency, date,
    note and splice (how flush box joints are made) — top's if it sets them."""
    head: dict[str, Any] = {
        f: getattr(top, f)
        for f in ("currency", "date", "note", "splice")
        if f in top.model_fields_set
    }
    return base.model_copy(
        update={
            **head,
            "items": {**base.items, **top.items},
            "terms": {**base.terms, **top.terms},
        }
    )


def load_prices(path: Path) -> tuple[PriceList | None, list[Issue]]:
    """One price list file (the studio's or a project's); errors come with a field path, an
    unknown item key and a decision on terms the catalogue does not allow (terms.term_issues) are
    also errors."""
    data, issues = load_yaml(path)
    if data is None:
        return None, issues
    prices, issues = parse_model(PriceList, data, path.name)
    if prices is None:
        return None, issues
    keys = [k for k in unknown_keys(prices) if k not in PLUMBING_LINES]
    bad = [Issue(path.name, f"items.{k}", "нет такой позиции сметы") for k in keys]
    for problem in term_issues(prices.terms):
        field, _, message = problem.partition(": ")
        bad.append(Issue(path.name, field, message))
    return (None, bad) if bad else (prices, [])


NEW_PRICES = (
    "# Общий прайс студии для сметы; prices.yaml проекта меняет только свои ключи.\n"
    "# Цены — за единицу позиции; ключи — LINES в electrical/estimate.py.\n"
    "currency: грн\n"
    "items:\n"
)


def load_market(path: Path) -> tuple[MarketSample | None, list[Issue]]:
    """Market sample (market.yaml); no file — None without errors."""
    if not path.is_file():
        return None, []
    data, issues = load_yaml(path)
    if data is None:
        return None, issues
    return parse_model(MarketSample, data, path.name)


def price_page(root: Path, market_root: Path | None = None) -> dict[str, Any]:
    """Studio price page (viewer, GET /api/prices): the electrical estimate items in estimate
    order — works (kind "work") and materials (kind "material", decision 2026-11-25: the page shows
    every item the price list can hold) — the studio price from root/prices.yaml next to the
    market spread from market.yaml (in market_root, by default in root: the sample is shared by
    all studios), the period of the market prices and its sources. A key with a parameter the
    file names (cable.3x1.5, work.chase.brick) is a row of its own after its base item. Errors of
    either file — in issues."""
    prices_path = root / PRICES_FILE
    own, issues = load_prices(prices_path) if prices_path.is_file() else (None, [])
    market, market_issues = load_market((market_root or root) / MARKET_FILE)
    issues = [*issues, *market_issues]
    rows = []
    for key in _page_keys(own):
        base, param = split_key(key)
        section, unit, ru, uk = LINES[base]
        price = own.price(key) if own is not None else None
        item = market.items.get(key) if market is not None else None
        spread = item_spread(market, key) if market is not None else None
        name = {"ru": ru, "uk": uk}
        if param:
            name = (
                {"ru": price.name, "uk": price.name}
                if price is not None and price.name
                else {lang: f"{text} {param}" for lang, text in name.items()}
            )
        rows.append(
            {
                "key": key,
                "kind": "work" if base.startswith(WORK_PREFIX) else "material",
                "section": section,
                "unit": unit,
                "name": name,
                "hint": HINTS.get(key),
                "price": price.price if price is not None else None,
                # no studio price — the estimate takes the price service's (a mock for now)
                "service": mock_price(key) if price is None else None,
                "market": None
                if item is None or spread is None
                else {
                    **spread.as_dict(),
                    "basis": item.basis,
                    "quotes": [
                        {"source": src, "price": q.price, "text": q.text}
                        for src, q in sorted(item.quotes.items(), key=lambda kv: kv[1].price)
                    ],
                },
            }
        )
    used = used_sources(market) if market is not None else set()
    return {
        "file": PRICES_FILE,
        "exists": prices_path.is_file(),
        "currency": own.currency if own is not None else "грн",
        "date": own.date if own is not None else "",
        "note": own.note if own is not None else "",
        # joints in switch flush boxes, the studio's choice; not set — the default (wago)
        "splice": (own.splice if own is not None else None) or DEFAULT_SPLICE,
        "rows": rows,
        "market": None
        if market is None
        else {
            "region": market.region,
            "collected": market.collected,
            "currency": market.currency,
            "period": period(market, used).as_dict(),
            "sources": [
                {"id": k, **s.model_dump()} for k, s in market.sources.items() if k in used
            ],
        },
        "issues": [f"{i.file}: {i.path}: {i.message}" for i in issues],
    }


def _page_keys(own: PriceList | None) -> list[str]:
    """Rows of the price page: every electrical item (LINES) in estimate order, works first; after
    each, the keys with a parameter the price list names (cable.3x1.5 after cable). Retired keys
    are not shown."""
    named = [k for k in (own.items if own is not None else {}) if split_key(k)[1]]
    out: list[str] = []
    for work in (True, False):
        for key in LINES:
            if key.startswith(WORK_PREFIX) != work:
                continue
            out.append(key)
            out += [k for k in named if split_key(k)[0] == key]
    return out


SPLICES: tuple[Splice, ...] = ("wago", "crimp")
SPLICE_LINE = re.compile(r"^splice:[^#\n]*?(?P<comment>[ \t]+#.*)?$", re.M)


def _set_splice(text: str, splice: Splice) -> str:
    """The top-level splice line in the prices.yaml text, its comment kept; no line — it goes
    before items (as date does)."""
    if SPLICE_LINE.search(text):
        return SPLICE_LINE.sub(lambda m: f"splice: {splice}{m['comment'] or ''}", text, count=1)
    if re.search(r"^items:", text, flags=re.M):
        return re.sub(r"^items:", f"splice: {splice}\nitems:", text, count=1, flags=re.M)
    return f"{text}splice: {splice}\n"


def save_prices(root: Path, changes: dict[str, Any]) -> list[Issue]:
    """Studio price page edits → root/prices.yaml: {"items"?: {key: price | None}, "date"?,
    "splice"?: "wago" | "crimp"}; any electrical estimate item, works and materials, a key with a
    parameter too (its base in LINES); None removes the price; splice — joints in switch flush
    boxes (PriceList.splice). Comments and other keys of the file stay
    (estimate.edit_price_items). Errors come with a field path; the file then is unchanged."""
    path = root / PRICES_FILE
    items = changes.get("items", {})
    if not isinstance(items, dict):
        return [Issue(PRICES_FILE, "items", "ожидается словарь «ключ: цена»")]
    bad = []
    for key, value in items.items():
        if not isinstance(key, str) or split_key(key)[0] not in LINES:
            bad.append(Issue(PRICES_FILE, f"items.{key}", "нет такой позиции в смете"))
        elif value is not None and (
            isinstance(value, bool) or not isinstance(value, int | float) or value < 0
        ):
            bad.append(Issue(PRICES_FILE, f"items.{key}", "цена — число не меньше 0"))
    date = changes.get("date")
    if date is not None and not isinstance(date, str):
        bad.append(Issue(PRICES_FILE, "date", "ожидается строка"))
    splice = changes.get("splice")
    if splice is not None and splice not in SPLICES:
        bad.append(Issue(PRICES_FILE, "splice", f"ожидается одно из: {', '.join(SPLICES)}"))
    if bad:
        return bad
    text = edit_price_items(path.read_text("utf-8") if path.is_file() else NEW_PRICES, items)
    if date is not None:
        line = f'date: "{date}"' if date else 'date: ""'
        text, n = re.subn(r"^date:.*$", line, text, count=1, flags=re.M)
        if not n:
            text = re.sub(r"^items:", f"{line}\nitems:", text, count=1, flags=re.M)
    if splice is not None:
        text = _set_splice(text, splice)
    data = yaml.safe_load(text)
    parsed, issues = parse_model(PriceList, data, PRICES_FILE)
    if parsed is None:
        return issues
    root.mkdir(parents=True, exist_ok=True)  # a new studio has no folder yet
    path.write_text(text, encoding="utf-8")
    return []
