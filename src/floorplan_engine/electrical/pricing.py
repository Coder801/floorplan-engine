"""Where the estimate gets prices: the studio price list (with the project's on top, key by key).

Prices are never invented (decision 2026-11-27): an estimate is priced only by what the studio
set in its price list; the mock price service with typical Kyiv prices is gone. An item the list
has no price for stays in the estimate with its quantity, "no price", out of the total; finish
materials are a bill of quantities without prices (estimate/items.LISTED_SECTIONS). An external
price service (supplier prices for a series the client picks) may come later: it goes behind the
same `PriceSource` protocol, lives in `service/` (network only there) and is passed to
`pipeline.build_project` / `estimate_project` as prices_from; its rows are marked
(`Line.service`).
"""

from __future__ import annotations

from dataclasses import dataclass

from floorplan_engine.electrical.estimate import Estimate
from floorplan_engine.electrical.estimate.texts import text as estimate_text
from floorplan_engine.electrical.price_list import PriceList, PriceSource, Quote
from floorplan_engine.electrical.splices import Splice
from floorplan_engine.model.texts import Language

CURRENCY = "грн"


@dataclass(frozen=True)
class Prices:
    """Estimate prices: the price list (own: the studio list with the project's on top, key by
    key — pipeline.prices.load_price_layers; may be missing) on top of an external price
    service (service; none so far, the build passes None). An own key, even without a rating
    (`diff`), beats an exact service price (`diff.C16 30 мА`)."""

    own: PriceList | None = None
    service: PriceSource | None = None

    @property
    def currency(self) -> str:
        if self.own is not None:
            return self.own.currency
        return self.service.currency if self.service is not None else CURRENCY

    @property
    def priced(self) -> bool:
        """There is a price source; otherwise the estimate is a bill of quantities."""
        return self.own is not None or self.service is not None

    @property
    def splice(self) -> Splice | None:
        """How the studio joins wires in flush boxes: from its price list (a project list may
        set its own, merge_prices); None — not set."""
        if self.own is not None and self.own.splice is not None:
            return self.own.splice
        return None if self.service is None else self.service.splice

    def lookup(self, key: str) -> Quote:
        if self.own is not None:
            quote = self.own.lookup(key)
            if quote.price is not None:
                return quote
        if self.service is not None:
            return self.service.lookup(key)
        return Quote(None, None, False)


def price_notes(est: Estimate, prices: Prices, language: Language, note: bool = False) -> list[str]:
    """Price sources: the first estimate notes on the sheet, in the viewer and in files: the price
    list (with date and, if note is set, the list's remark), the share of a price service, items
    without a price, the finish materials listed without prices."""
    out = []
    if prices.own is not None:
        date = f" ({prices.own.date})" if prices.own.date else ""
        if note:
            tail = f" — {prices.own.note}" if prices.own.note else ""
            out.append(estimate_text("note_prices", language, date=date, note=tail))
        else:
            out.append(estimate_text("sheet_prices", language, date=date))
    if est.from_service:
        key = "note_service" if prices.own is not None else "note_service_all"
        out.append(estimate_text(key, language, n=est.from_service))
    if est.unpriced:
        out.append(estimate_text("unpriced", language, n=est.unpriced))
    if est.listed:
        out.append(estimate_text("note_listed", language, n=est.listed))
    return out
