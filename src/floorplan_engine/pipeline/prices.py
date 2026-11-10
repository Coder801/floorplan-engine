"""Price lists: the project's or the studio's, the market sample, the studio price page."""

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
    price_path = find_prices(project)
    own, issues = load_prices(price_path) if price_path is not None else (None, [])
    return elec, Prices(own, service), issues


def find_prices(project: Path) -> Path | None:
    """Estimate price list: the project's own (prices.yaml in its folder), otherwise the shared
    studio list (prices.yaml in the folder above the projects, next to studio.yaml); None if
    neither exists."""
    for path in (project / PRICES_FILE, project.parent / PRICES_FILE):
        if path.is_file():
            return path
    return None


def load_prices(path: Path) -> tuple[PriceList | None, list[Issue]]:
    """Project price list; errors come with a field path, an unknown item key is also an error."""
    data, issues = load_yaml(path)
    if data is None:
        return None, issues
    prices, issues = parse_model(PriceList, data, path.name)
    if prices is None:
        return None, issues
    keys = [k for k in unknown_keys(prices) if k not in PLUMBING_LINES]
    bad = [Issue(path.name, f"items.{k}", "нет такой позиции сметы") for k in keys]
    return (None, bad) if bad else (prices, [])


NEW_PRICES = (
    "# Общий прайс студии для сметы: берётся, если у проекта нет своего prices.yaml.\n"
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
    """Studio price page (viewer, GET /api/prices): electrical works in estimate order — the
    studio price from root/prices.yaml next to the market spread from market.yaml (in
    market_root, by default in root: the sample is shared by all studios), the period of the
    market prices and its sources. Errors of either file — in issues."""
    prices_path = root / PRICES_FILE
    own, issues = load_prices(prices_path) if prices_path.is_file() else (None, [])
    market, market_issues = load_market((market_root or root) / MARKET_FILE)
    issues = [*issues, *market_issues]
    rows = []
    for key, (section, unit, ru, uk) in LINES.items():
        if not key.startswith(WORK_PREFIX):
            continue
        price = own.price(key) if own is not None else None
        item = market.items.get(key) if market is not None else None
        spread = item_spread(market, key) if market is not None else None
        rows.append(
            {
                "key": key,
                "section": section,
                "unit": unit,
                "name": {"ru": ru, "uk": uk},
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


def save_prices(root: Path, changes: dict[str, Any]) -> list[Issue]:
    """Studio price page edits → root/prices.yaml: {"items": {key: price | None}, "date"?};
    only works (work.*), None removes the price. Comments and other keys of the file stay
    (estimate.edit_price_items). Errors come with a field path; the file then is unchanged."""
    path = root / PRICES_FILE
    items = changes.get("items", {})
    if not isinstance(items, dict):
        return [Issue(PRICES_FILE, "items", "ожидается словарь «ключ: цена»")]
    bad = []
    for key, value in items.items():
        if not key.startswith(WORK_PREFIX) or key not in LINES:
            bad.append(Issue(PRICES_FILE, f"items.{key}", "нет такой работы в смете"))
        elif value is not None and (
            isinstance(value, bool) or not isinstance(value, int | float) or value < 0
        ):
            bad.append(Issue(PRICES_FILE, f"items.{key}", "цена — число не меньше 0"))
    date = changes.get("date")
    if date is not None and not isinstance(date, str):
        bad.append(Issue(PRICES_FILE, "date", "ожидается строка"))
    if bad:
        return bad
    text = edit_price_items(path.read_text("utf-8") if path.is_file() else NEW_PRICES, items)
    if date is not None:
        line = f'date: "{date}"' if date else 'date: ""'
        text, n = re.subn(r"^date:.*$", line, text, count=1, flags=re.M)
        if not n:
            text = re.sub(r"^items:", f"{line}\nitems:", text, count=1, flags=re.M)
    data = yaml.safe_load(text)
    parsed, issues = parse_model(PriceList, data, PRICES_FILE)
    if parsed is None:
        return issues
    root.mkdir(parents=True, exist_ok=True)  # a new studio has no folder yet
    path.write_text(text, encoding="utf-8")
    return []
