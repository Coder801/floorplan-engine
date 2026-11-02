"""Цены сметы (electrical/pricing.py): имитация сервиса цен знает все позиции, прайс студии
важнее сервиса, строки от сервиса помечены."""

from __future__ import annotations

import pytest

from floorplan_engine.electrical.estimate import LINES, PriceList, build_estimate
from floorplan_engine.electrical.pricing import (
    MockPriceService,
    Prices,
    mock_covers_all_lines,
    mock_price,
    price_notes,
)
from tests.electrical.test_estimate import _wiring


def test_mock_knows_every_line_and_is_deterministic() -> None:
    assert mock_covers_all_lines() == []
    assert len(LINES) > 30
    assert mock_price("socket") == mock_price("socket") == 180
    assert mock_price("нет такого") is None


@pytest.mark.parametrize(
    ("key", "price"),
    [
        ("cable.3x1.5", 45),  # 10 грн за мм² суммарного сечения
        ("cable.3x2.5", 75),
        ("cable.5x6", 300),
        ("cable.abc", None),
        ("frame.1", 60),
        ("frame.4", 180),
        ("junction_box.80", 40),
        ("junction_box.100×100", 60),
        ("junction_box_ip.150x110", 220),
        ("input.C63 2P", 850),  # больше 40 А — дороже
        ("input.C40 2P", 650),
        ("relay.63 А", 1900),
        ("breaker.C16", 140),
        ("breaker.C50", 220),
        ("diff.C16 30 мА", 950),
        ("ats.АВР", 4500),  # без номинала — цена вида
        ("work.chase", 200),
    ],
)
def test_mock_price_by_parameter(key: str, price: float | None) -> None:
    assert mock_price(key) == price


def test_own_prices_override_service_even_without_rating() -> None:
    own = PriceList.model_validate(
        {"items": {"diff": 700, "cable.3x2.5": {"price": 80, "name": "ВВГнг"}}}
    )
    prices = Prices(own, MockPriceService())
    diff = prices.lookup("diff.C16 30 мА")
    assert diff.price is not None and not diff.service
    assert diff.price.price == 700  # свой ключ вида важнее точной цены сервиса
    assert prices.lookup("socket").service and prices.lookup("socket").price is not None
    exact = prices.lookup("cable.3x2.5")
    assert exact.exact is not None and exact.exact.name == "ВВГнг"
    assert prices.currency == "грн" and prices.priced
    assert not Prices().priced and Prices().lookup("socket").price is None


def test_estimate_marks_service_lines_and_notes() -> None:
    wiring, elec = _wiring()
    own = PriceList.model_validate({"items": {"socket_box": 20}, "date": "2026-10"})
    est = build_estimate(wiring, elec, Prices(own, MockPriceService()), "uk")
    by_key = {ln.key: ln for ln in est.lines}
    assert not by_key["socket_box"].service and by_key["socket_box"].hint is None
    assert by_key["socket"].service and "імітація" in (by_key["socket"].hint or "")
    assert est.unpriced == 0 and est.from_service == len(est.lines) - 1
    notes = price_notes(est, Prices(own, MockPriceService()), "uk")
    assert notes[0] == "Ціни: prices.yaml (2026-10)" and "із сервісу цін" in notes[1]
    assert price_notes(est, Prices(None, MockPriceService()), "uk")[0].startswith("Усі ціни")
    # Установка механизмов: своё пояснение и пометка сервиса вместе
    assert "Встановлення розеток" in (by_key["work.mechanism"].hint or "")
    assert "імітація" in (by_key["work.mechanism"].hint or "")
