"""Market prices for works: a sample of public price lists (market.yaml next to the studio
price list) and the spread per estimate item — min, quartiles, median, max — plus the period
the prices were collected over.

The sample is collected by hand or by an agent (studio sites and master platforms, decision
2026-11-03): every price has a source with a link and a price-list date, and the price-list
line it was taken from. No network here: only reading the file and a deterministic
calculation. Median, not mean: price lists differ several-fold, and one expensive list or a
"from …" price does not shift the middle.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, model_validator

from floorplan_engine.electrical.estimate import LINES
from floorplan_engine.model.schema import StrictModel

MARKET_FILE = "market.yaml"  # market sample — next to the studio price list (projects/)
SourceKind = Literal["company", "master", "platform", "review"]
DATE = re.compile(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")


class MarketSource(StrictModel):
    """Where prices come from: a studio or master price list, or a platform summary."""

    name: str = Field(min_length=1)
    url: str = Field(min_length=1)
    date: str = Field(
        default="", description="Price-list date: YYYY-MM-DD, YYYY-MM, YYYY; none — empty"
    )
    kind: SourceKind = "company"
    note: str = ""

    @model_validator(mode="after")
    def _date(self) -> MarketSource:
        if self.date and DATE.fullmatch(self.date) is None:
            raise ValueError(f"date: {self.date!r} — нужно ГГГГ, ГГГГ-ММ или ГГГГ-ММ-ДД")
        return self


class MarketQuote(StrictModel):
    price: float = Field(ge=0)
    text: str = Field(min_length=1, description="Price-list line the price is taken from")


class MarketItem(StrictModel):
    basis: str = Field(default="", description="What is compared: wall material, unit")
    quotes: dict[str, MarketQuote] = Field(default_factory=dict)


class MarketSample(StrictModel):
    """market.yaml: prices of works by estimate item keys (LINES) from the sources."""

    region: str = Field(min_length=1)
    collected: str = Field(description="When the sample was collected, YYYY-MM-DD")
    currency: str = "грн"
    sources: dict[str, MarketSource]
    items: dict[str, MarketItem] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _refs(self) -> MarketSample:
        for key, item in self.items.items():
            if key not in LINES:
                raise ValueError(f"items.{key}: нет такой позиции сметы")
            for src in item.quotes:
                if src not in self.sources:
                    raise ValueError(f"items.{key}.quotes.{src}: нет такого источника в sources")
        return self


@dataclass(frozen=True)
class Spread:
    """Market spread for an item: how many price lists and min / quartiles / median / max."""

    n: int
    min: float
    q1: float
    median: float
    q3: float
    max: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "n": self.n,
            "min": self.min,
            "q1": self.q1,
            "median": self.median,
            "q3": self.q3,
            "max": self.max,
        }


def spread(prices: list[float]) -> Spread | None:
    """Spread of prices; quartiles by the inclusive method (two prices — between them).
    No prices — None."""
    if not prices:
        return None
    xs = sorted(prices)
    if len(xs) == 1:
        q1 = median = q3 = xs[0]
    else:
        q1, median, q3 = statistics.quantiles(xs, n=4, method="inclusive")
    return Spread(len(xs), xs[0], round(q1, 1), round(median, 1), round(q3, 1), xs[-1])


def item_spread(sample: MarketSample, key: str) -> Spread | None:
    item = sample.items.get(key)
    return None if item is None else spread([q.price for q in item.quotes.values()])


@dataclass(frozen=True)
class Period:
    """The period of the prices: the earliest and latest price-list dates (YYYY or YYYY-MM),
    how many sources are dated and undated. No dates at all — start and end are empty."""

    start: str
    end: str
    dated: int
    undated: int

    def as_dict(self) -> dict[str, str | int]:
        return {"start": self.start, "end": self.end, "dated": self.dated, "undated": self.undated}


def _month(date: str) -> str:
    """Price-list date down to the month: "2026-03-24" → "2026-03", "2026" → "2026"."""
    m = DATE.fullmatch(date)
    assert m is not None
    return m.group(1) if m.group(2) is None else f"{m.group(1)}-{m.group(2)}"


def period(sample: MarketSample, used: set[str] | None = None) -> Period:
    """Period of the sample's prices (used — only these sources): from the earliest year to
    the latest. The start is the year if it has a list without a month (when in the year is
    unknown), otherwise the earliest month; the end is the latest month of the last year if
    known: "2024", "2026" and "2026-11" → from 2024 to 2026-11."""
    sources = [s for k, s in sample.sources.items() if used is None or k in used]
    dates = [_month(s.date) for s in sources if s.date]
    if not dates:
        return Period("", "", 0, len(sources))
    first = [d for d in dates if d[:4] == min(dates)[:4]]
    last = [d for d in dates if d[:4] == max(dates)[:4]]
    start = first[0][:4] if any(len(d) == 4 for d in first) else min(first)
    end = max(last)  # "2026-11" > "2026": a known month beats a bare year
    return Period(start, end, len(dates), len(sources) - len(dates))


def used_sources(sample: MarketSample) -> set[str]:
    """Sources that have at least one price in the sample."""
    return {src for item in sample.items.values() for src in item.quotes}
