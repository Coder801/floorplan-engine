"""Смета: ключи прайса, цены, суммы позиций и формат чисел — без модели и файлов."""

from __future__ import annotations

import pytest

from shtroba.estimate import (
    Estimate,
    Line,
    Price,
    PriceList,
    _num,
    split_key,
    unknown_keys,
)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("cable.3x1.5", ("cable", "3x1.5")),
        ("frame.2", ("frame", "2")),
        ("cable", ("cable", "")),
        ("cable.", ("cable.", "")),
        ("work.cable", ("work.cable", "")),
        ("socket", ("socket", "")),
        ("", ("", "")),
    ],
)
def test_split_key(key: str, expected: tuple[str, str]) -> None:
    assert split_key(key) == expected


def test_unknown_keys_lists_only_foreign_keys_in_order() -> None:
    prices = PriceList.model_validate(
        {
            "items": {
                "socket": 1,
                "sokcet": 2,
                "cable.3x2.5": 3,
                "work.cable": 4,
                "work.unknown": 5,
                "frame.3": 6,
            }
        }
    )
    assert unknown_keys(prices) == ["sokcet", "work.unknown"]


def test_unknown_keys_empty_price_list() -> None:
    assert unknown_keys(PriceList()) == []


def test_price_number_becomes_price_without_name() -> None:
    prices = PriceList.model_validate({"items": {"socket": 120, "crimp": 2.5}})
    assert prices.price("socket") == Price(price=120)
    assert prices.price("crimp") == Price(price=2.5)


def test_price_object_keeps_own_name() -> None:
    prices = PriceList.model_validate({"items": {"socket": {"price": 99, "name": "Розетка X"}}})
    p = prices.price("socket")
    assert p is not None and p.price == 99 and p.name == "Розетка X"


def test_price_missing_key_is_none() -> None:
    assert PriceList().price("socket") is None


def test_price_list_defaults() -> None:
    prices = PriceList()
    assert prices.currency == "грн" and prices.items == {} and prices.board_kit == []


def _line(section: str, qty: float, price: float | None, key: str = "k") -> Line:
    assert section in ("material", "work")
    return Line("material" if section == "material" else "work", key, key, "шт", qty, price)


@pytest.mark.parametrize(
    ("qty", "price", "total"), [(3, 10.0, 30.0), (2.5, 4.0, 10.0), (0, 7.0, 0.0), (5, None, None)]
)
def test_line_total(qty: float, price: float | None, total: float | None) -> None:
    assert _line("material", qty, price).total == total


def test_estimate_subtotals_skip_unpriced_lines() -> None:
    est = Estimate(
        (
            _line("material", 2, 10.0),
            _line("material", 1, None),
            _line("work", 3, 5.0),
            _line("work", 4, None),
        ),
        "грн",
    )
    assert est.subtotal("material") == 20
    assert est.subtotal("work") == 15
    assert est.total == 35
    assert est.unpriced == 2


def test_empty_estimate_is_zero() -> None:
    est = Estimate((), "грн")
    assert est.subtotal("material") == 0 and est.total == 0 and est.unpriced == 0


@pytest.mark.parametrize(
    ("value", "digits", "text"),
    [
        (10, 2, "10"),
        (1234.5, 2, "1 234,50"),
        (1234567.891, 2, "1 234 567,89"),
        (0.25, 2, "0,25"),
        (0, 2, "0"),
        (1234567, 0, "1 234 567"),
        (5, 0, "5"),
        (2.75, 1, "2,8"),
        (3.0, 1, "3,0"),
    ],
)
def test_num_format(value: float, digits: int, text: str) -> None:
    assert _num(value, digits) == text
