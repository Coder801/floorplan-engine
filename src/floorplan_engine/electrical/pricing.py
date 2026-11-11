"""Where the estimate gets prices: the studio or project price list (prices.yaml) on top of the
price service.

The price service is external (decision 2026-11-01): a price analysis API, a microservice or a
database fed from supplier sites. It does not exist yet; its place is taken by the mock
`MockPriceService` with typical Kyiv prices, so the estimate always has prices and
`prices.yaml` holds studio overrides on top (an own price list key beats any service price).
Rows priced by the service are marked in the estimate (`Line.service`, hint "from the price
service (mock for now)") so nobody takes them for market prices.
The real service client will live in `service/` (network only there) and will be passed to
`pipeline.build_project` / `estimate_project` through the same `PriceSource` protocol.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from floorplan_engine.electrical.boxes import BOX_TITLES
from floorplan_engine.electrical.estimate import (
    DERIVED_PRICES,
    LINES,
    PRICES_FILE,
    Estimate,
    Price,
    PriceList,
    PriceSource,
    Quote,
    split_key,
)
from floorplan_engine.electrical.estimate import text as estimate_text
from floorplan_engine.model.texts import Language

CURRENCY = "грн"

# Mock: UAH per item unit (LINES keys), a rough Kyiv guide for autumn 2026, not market
# prices. Keys with a parameter are priced by mock_price: cable by cross-section, frames by
# posts, boxes by size, panel devices by rating.
MOCK_PRICES: dict[str, float] = {
    "socket_box": 20,
    "crimp": 8,
    "cable_pad": 5,  # pad with a nail for the gun and a tie
    "board_enclosure": 6000,
    "breaker": 140,
    "diff": 950,
    "rcd": 1100,
    "input": 850,
    "relay": 1900,
    "spd": 2500,
    "changeover": 900,
    "ats": 4500,
    "contactor": 1200,
    "feed": 500,
    "output": 500,
    "dc_battery": 2600,
    "dc_breaker": 650,
    "dc_spd": 1400,
    "dc_enclosure": 1500,
    "socket": 180,
    "switch1": 150,
    "switch2": 190,
    "pass_switch": 210,
    "data": 250,
    "tv": 220,
    "light": 900,
    "downlight": 350,
    "pendant": 1500,
    "sconce": 1200,
    "led_output": 150,
    "outlet": 150,
    "led_strip": 250,
    "led_psu": 450,
    "led_psu_din": 1300,
    "rough_holder": 60,
    "rough_lamp": 50,
    "rough_switch": 80,
    "work.cable": 34,  # with a tag at each cable end
    "work.conduit": 15,
    "work.chase": 120,  # wall material unknown: as brick
    "work.wall_hole": 100,
    "work.socket_box": 140,
    "work.junction_box": 250,
    "work.board_install": 1500,
    "work.board_module": 100,
    "work.mechanism": 100,
    "work.led_psu": 220,
    "work.led_psu_din": 250,
    "work.rough_light": 100,
    "work.rough_switch": 100,
    "work.insulation_test": 150,
}
# Narrow chase by wall material, UAH per metre (Kyiv 2026-11); a wide one is × 1.5 (DERIVED_PRICES)
CHASE_PRICES = {"concrete": 200.0, "claydite": 150.0, "brick": 120.0, "aerated": 90.0}
CABLE_PER_MM2 = 10.0  # UAH per metre per mm² of total conductor section: 3×1.5 → 45, 3×2.5 → 75
BOX_PRICES = {"80": 40.0, "100x100": 60.0, "150x110": 110.0, "190x140": 180.0}
CONDUIT_PRICES = {16: 10.0, 20: 14.0, 25: 20.0, 32: 30.0}  # PVC conduit, UAH per metre
CLIP_PRICES = {16: 4.0, 20: 5.0, 25: 6.0, 32: 8.0}  # conduit clip with a gun nail, UAH each
JOINT_PRICES = {16: 4.0, 20: 5.0, 25: 7.0, 32: 10.0}  # conduit joint coupling, UAH each
ENTRY_PRICES = {16: 6.0, 20: 7.0, 25: 9.0, 32: 12.0}  # conduit entry into a box, UAH each
IP_FACTOR = 2.0  # IP44 costs twice a normal one
FRAME_FIRST, FRAME_NEXT = 60.0, 40.0  # frame: first post and each next one
HEAVY_A = 40  # rating from which supply, relay and breaker cost more
HEAVY = {"input": (650.0, 850.0), "relay": (1500.0, 1900.0), "breaker": (140.0, 220.0)}


def _rating(param: str) -> int | None:
    m = re.search(r"\d+", param)
    return int(m.group()) if m else None


# A three-phase device ("C16 3P", "C40 4P") against the usual one of its kind: more poles
POLE_FACTOR = {"breaker": 3.0, "diff": 2.5, "input": 2.0, "spd": 2.0}
_POLES = re.compile(r"\b[34]P\b")


def mock_price(key: str) -> float | None:
    """Mock price by item key; None for an unknown key."""
    base, param = split_key(key)
    price = _mock_price(base, param)
    if price is not None and base in POLE_FACTOR and _POLES.search(param):
        return round(price * POLE_FACTOR[base], 1)
    return price


def _mock_price(base: str, param: str) -> float | None:
    if base == "cable":
        m = re.fullmatch(r"(\d+)x([\d.,]+)", param.replace("×", "x"))
        if m is None:
            return None
        return round(CABLE_PER_MM2 * int(m.group(1)) * float(m.group(2).replace(",", ".")), 1)
    if base == "work.chase" and param:
        return CHASE_PRICES.get(param)
    if base == "conduit":
        return CONDUIT_PRICES.get(_rating(param) or 20)
    if base == "conduit_clip":
        return CLIP_PRICES.get(_rating(param) or 20)
    if base == "conduit_joint":
        return JOINT_PRICES.get(_rating(param) or 20)
    if base == "conduit_entry":
        return ENTRY_PRICES.get(_rating(param) or 20)
    if base == "frame":
        posts = _rating(param) or 1
        return FRAME_FIRST + FRAME_NEXT * (posts - 1)
    if base in ("junction_box", "junction_box_ip"):
        size = next((k for k, title in BOX_TITLES.items() if param in (k, title)), None)
        price = BOX_PRICES.get(size or "", BOX_PRICES["100x100"])
        return price * IP_FACTOR if base == "junction_box_ip" else price
    if base in HEAVY and param:
        light, heavy = HEAVY[base]
        rating = _rating(param)
        return heavy if rating is not None and rating > HEAVY_A else light
    if base in DERIVED_PRICES:
        of, factor = DERIVED_PRICES[base]
        known = _mock_price(of, param)
        return None if known is None else round(known * factor, 2)
    return MOCK_PRICES.get(base)


@dataclass(frozen=True)
class MockPriceService:
    """Price service mock: knows every estimate item, prices are typical and fixed. extra holds
    prices of items from other estimates (plumbing, plumbing/estimate.MOCK_PRICES) by key."""

    currency: str = CURRENCY
    extra: Mapping[str, float] = field(default_factory=dict)

    def lookup(self, key: str) -> Quote:
        price = mock_price(key)
        if price is None:
            price = self.extra.get(key)
        return Quote(None if price is None else Price(price=price), None, service=True)


@dataclass(frozen=True)
class Prices:
    """Estimate prices: the studio or project price list (own, may be missing) on top of the price
    service (service). An own key, even without a rating (`diff`), beats an exact service price
    (`diff.C16 30 мА`)."""

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

    def lookup(self, key: str) -> Quote:
        if self.own is not None:
            quote = self.own.lookup(key)
            if quote.price is not None:
                return quote
        if self.service is not None:
            return self.service.lookup(key)
        return Quote(None, None, False)


def price_notes(
    est: Estimate, prices: Prices, language: Language, f: str = PRICES_FILE, note: bool = False
) -> list[str]:
    """Price sources: the first estimate notes on the sheet, in the viewer and in files: the price
    list (with date and, if note is set, the list's remark), the share of the price service
    (mock), items without a price."""
    out = []
    if prices.own is not None:
        date = f" ({prices.own.date})" if prices.own.date else ""
        if note:
            tail = f" — {prices.own.note}" if prices.own.note else ""
            out.append(estimate_text("note_prices", language, f=f, date=date, note=tail))
        else:
            out.append(estimate_text("sheet_prices", language, f=f, date=date))
    if est.from_service:
        key = "note_service" if prices.own is not None else "note_service_all"
        out.append(estimate_text(key, language, n=est.from_service, f=f))
    if est.unpriced:
        out.append(estimate_text("unpriced", language, n=est.unpriced, f=f))
    return out


def mock_covers_all_lines() -> list[str]:
    """Item keys the mock has no price for (test: must be empty)."""
    sample = {"cable": "cable.3x1.5", "frame": "frame.2", "conduit": "conduit.20"}
    return [k for k in LINES if mock_price(sample.get(k, k)) is None]
