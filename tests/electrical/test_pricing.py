"""Estimate prices (electrical/pricing.py): only the studio price list (decision 2026-11-27, no
mock price service), a price service on top is still possible and its rows are marked; finish
materials are a bill of quantities without prices."""

from __future__ import annotations

from dataclasses import dataclass

from floorplan_engine.electrical.estimate import build_estimate
from floorplan_engine.electrical.estimate.items import LINES, LISTED_SECTIONS
from floorplan_engine.electrical.price_list import Price, PriceList, Quote
from floorplan_engine.electrical.pricing import Prices, price_notes
from floorplan_engine.electrical.splices import Splice
from floorplan_engine.pipeline import price_service
from tests.electrical.test_estimate import _wiring


@dataclass(frozen=True)
class FlatService:
    """A stand-in external price service: one price for every key."""

    price: float = 99.0
    currency: str = "грн"

    @property
    def splice(self) -> Splice | None:
        return None

    def lookup(self, key: str) -> Quote:
        return Quote(Price(price=self.price), None, service=True)


def test_build_has_no_price_service_by_default() -> None:
    """No mock: without a given client the estimate is priced by the studio list alone."""
    assert price_service(None) is None
    service = FlatService()
    assert price_service(service) is service


def test_own_prices_override_service_even_without_rating() -> None:
    own = PriceList.model_validate(
        {"items": {"diff": 700, "cable.3x2.5": {"price": 80, "name": "ВВГнг"}}}
    )
    prices = Prices(own, FlatService())
    diff = prices.lookup("diff.C16 30 мА")
    assert diff.price is not None and not diff.service
    assert diff.price.price == 700  # own key for the kind beats the exact service price
    assert prices.lookup("socket_box").service and prices.lookup("socket_box").price is not None
    exact = prices.lookup("cable.3x2.5")
    assert exact.exact is not None and exact.exact.name == "ВВГнг"
    assert prices.currency == "грн" and prices.priced
    assert not Prices().priced and Prices().lookup("socket").price is None


def test_only_the_studio_list_prices_the_estimate() -> None:
    """A key the list has no price for stays "no price" (not invented), out of the total."""
    wiring, elec = _wiring()
    own = PriceList.model_validate({"items": {"socket_box": 20}, "date": "2026-10"})
    est = build_estimate(wiring, elec, Prices(own), "uk")
    by_key = {ln.key: ln for ln in est.lines}
    assert by_key["socket_box"].price == 20 and not by_key["socket_box"].service
    assert by_key["work.cable"].price is None  # no price in the list: not invented
    assert est.from_service == 0
    assert est.unpriced == sum(1 for ln in est.lines if not ln.listed) - 1
    notes = price_notes(est, Prices(own), "uk")
    assert notes[0] == "Ціни: прайс студії (2026-10)"  # the list, not a file (only in the DB)
    assert any(n.endswith("потрібна ціна в прайсі студії.") for n in notes)
    assert not any("імітація" in n for n in notes)


def test_finish_materials_are_listed_without_prices() -> None:
    """Wiring devices, lights and panel devices are the client's choice: no price even when the
    list names one, not counted as "no price", out of the totals; one note says why."""
    wiring, elec = _wiring()
    finish = [k for k, line in LINES.items() if line[0] in LISTED_SECTIONS]
    assert {"socket", "frame", "breaker", "rcd", "light", "led_psu"} <= set(finish)
    own = PriceList.model_validate({"items": {"socket": 180, "breaker": 140, "socket_box": 20}})
    est = build_estimate(wiring, elec, Prices(own), "ru")
    listed = [ln for ln in est.lines if ln.listed]
    assert listed and all(ln.section == "material_finish" for ln in listed)
    assert all(ln.price is None and ln.total is None for ln in listed)
    assert not any("уточняется" in (ln.hint or "") for ln in listed)
    assert est.subtotal("material_finish") == 0 and est.listed == len(listed)
    assert est.unpriced == sum(1 for ln in est.lines if ln.price is None and not ln.listed)
    notes = price_notes(est, Prices(own), "ru")
    assert any(
        n.startswith(f"Чистовые материалы ({len(listed)} поз.) — ведомость без цен") for n in notes
    )


def test_service_rows_are_marked_without_the_mock_wording() -> None:
    wiring, elec = _wiring()
    own = PriceList.model_validate({"items": {"socket_box": 20}})
    est = build_estimate(wiring, elec, Prices(own, FlatService()), "uk")
    by_key = {ln.key: ln for ln in est.lines}
    assert by_key["work.cable"].service and by_key["work.cable"].price == 99
    assert "із сервісу цін" in (by_key["work.cable"].hint or "")
    assert "імітація" not in (by_key["work.cable"].hint or "")
    assert not by_key["socket"].service  # a listed line is never looked up
    notes = price_notes(est, Prices(own, FlatService()), "uk")
    assert any("із сервісу цін" in n and "імітація" not in n for n in notes)
