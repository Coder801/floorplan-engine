"""Price list of the electrical estimate (prices.yaml) and the price source protocol.

PriceList is prices.yaml: prices by item key (estimate.items.LINES), the agreed terms and the
studio's splice method; PriceSource is what the estimate reads prices from (a price list, the
price service or both merged, pricing.Prices). Items of DERIVED_PRICES are priced from another
one unless the list names them. Prices are never invented: an item with no price stays in the
estimate marked "no price". edit_price_items edits the prices in the text of prices.yaml, line by
line, keeping its comments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from pydantic import Field

from floorplan_engine.electrical.estimate.items import LINES, RETIRED, split_key
from floorplan_engine.electrical.splices import Splice
from floorplan_engine.electrical.terms import TermDecision
from floorplan_engine.model.schema import StrictModel

PRICES_FILE = "prices.yaml"  # the project price list lives in the project folder, next to room.yaml


class Price(StrictModel):
    price: float = Field(ge=0)
    name: str | None = Field(default=None, description="Своё наименование вместо стандартного")


class BoardItem(StrictModel):
    """Deprecated: the panel set is computed by the "Panel" sheet, device prices use keys by kind
    (breaker, diff, rcd, input…). The field is still read so old price lists open."""

    name: str = Field(min_length=1)
    price: float = Field(ge=0)
    qty: int = Field(default=1, ge=1)
    modules: int = Field(default=0, ge=0, description="Ширина на DIN-рейке, модулей")


class PriceList(StrictModel):
    """prices.yaml: prices by item key (LINES), per unit, in the currency currency."""

    currency: str = "грн"
    date: str = Field(default="", description="Когда собраны цены")
    note: str = ""
    items: dict[str, float | Price] = Field(default_factory=dict)
    board_kit: list[BoardItem] = Field(
        default_factory=list, description="Устарело — не используется"
    )
    terms: dict[str, TermDecision] = Field(
        default_factory=dict,
        description="Что обговаривается с заказчиком отдельно: кто делает и как оплачивается "
        "(пункты — electrical/terms.yaml)",
    )
    splice: Splice | None = Field(
        default=None,
        description="Соединения в подрозетниках выключателей при свете цепочкой (в шлейфе "
        "розеток соединений нет): wago — клеммами Wago 221, crimp — опрессовкой гильзами с "
        "термоусадкой; нет — wago. В распаечных коробках — всегда опрессовка",
    )

    def price(self, key: str) -> Price | None:
        item = self.items.get(key)
        return Price(price=item) if isinstance(item, int | float) else item

    def lookup(self, key: str) -> Quote:
        """Price by key; with a parameter, also tries the key without it ("cable.3x4" → "cable")."""
        base, param = split_key(key)
        exact = self.price(key)
        return Quote(exact or (self.price(base) if param else None), exact, service=False)


@dataclass(frozen=True)
class Quote:
    """Price source answer: the price, the price for the exact key (its own name comes from it) and
    a flag that the price comes from the price service (pricing.py), not the price list."""

    price: Price | None
    exact: Price | None
    service: bool


class PriceSource(Protocol):
    """Where the estimate gets prices: a price list (PriceList), the price service or both merged
    (pricing.Prices).
    """

    @property
    def currency(self) -> str: ...

    @property
    def splice(self) -> Splice | None:
        """How wires are joined in flush boxes (Splice); None — not set, DEFAULT_SPLICE."""
        ...

    def lookup(self, key: str) -> Quote: ...


# Items priced from another one unless the price list names them itself: key → (base key, factor).
# A wide chase costs half as much again as a narrow one in the same material (work.chase_wide.brick
# from work.chase.brick)
DERIVED_PRICES: dict[str, tuple[str, float]] = {
    "work.chase_wide": ("work.chase", 1.5),
}


def derived_from(key: str) -> tuple[str, float] | None:
    """The item a DERIVED_PRICES item is priced from, with the factor; a parameter carries over
    (work.chase_wide.brick → work.chase.brick). None — the item has its own price."""
    if key in DERIVED_PRICES:
        return DERIVED_PRICES[key]
    base, param = split_key(key)
    if param and base in DERIVED_PRICES:
        of, factor = DERIVED_PRICES[base]
        return f"{of}.{param}", factor
    return None


def derived_quote(prices: PriceSource, key: str) -> Quote:
    """Price of an item: its own price list entry first; for a DERIVED_PRICES item without one,
    the base item's price (from the list or the service) times the factor."""
    quote = prices.lookup(key)
    derived = derived_from(key)
    if derived is None or (quote.exact is not None and not quote.service):
        return quote
    base_key, factor = derived
    base = prices.lookup(base_key)
    if base.price is None:
        return quote
    return Quote(Price(price=round(base.price.price * factor, 2)), None, base.service)


def unknown_keys(prices: PriceList) -> list[str]:
    """Price list keys that match no estimate item (a typo or a foreign key); retired items
    (RETIRED) are not errors."""
    return [k for k in prices.items if split_key(k)[0] not in LINES and k not in RETIRED]


ITEMS_LINE = re.compile(r"^items:\s*(#.*)?$")


def _money(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def edit_price_items(text: str, items: dict[str, float | None]) -> str:
    """Prices in the prices.yaml text, line by line, keeping comments: `key: 30  # …` → the new
    number, `key: { price: 30, name: … }` — only price; None removes the key's line; a missing
    key — a new line at the end of the items section. No items section — it is appended."""
    lines = text.splitlines()
    head = next((i for i, line in enumerate(lines) if ITEMS_LINE.match(line)), None)
    if head is None:
        lines += ["items:"]
        head = len(lines) - 1
    end = head + 1  # the section runs to the first unindented line that is not blank or a comment
    while end < len(lines) and (not lines[end].strip() or lines[end][:1] in (" ", "#")):
        end += 1
    last = head  # the section's last value line: new keys go after it
    for i in range(head + 1, end):
        if lines[i].strip() and not lines[i].lstrip().startswith("#"):
            last = i
    drop: set[int] = set()
    added: list[str] = []
    for key, value in items.items():
        pat = re.compile(rf"^(\s+){re.escape(key)}:\s*(.*)$")
        at = next((i for i in range(head + 1, end) if pat.match(lines[i])), None)
        if at is None:
            if value is not None:
                added.append(f"  {key}: {_money(value)}")
            continue
        if value is None:
            drop.add(at)
            continue
        m = pat.match(lines[at])
        assert m is not None
        indent, rest = m.groups()
        if rest.startswith("{"):
            rest = re.sub(r"price:\s*[\d.]+", f"price: {_money(value)}", rest, count=1)
        else:
            comment = re.search(r"\s+#.*$", rest)
            rest = _money(value) + (comment.group() if comment else "")
        lines[at] = f"{indent}{key}: {rest}"
    out = [line for i, line in enumerate(lines[: last + 1]) if i not in drop]
    out += added
    out += [line for i, line in enumerate(lines[last + 1 :], start=last + 1) if i not in drop]
    return "\n".join(out) + "\n"
