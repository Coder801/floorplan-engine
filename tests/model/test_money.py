import pytest

from floorplan_engine.electrical.estimate.texts import parse_number
from floorplan_engine.model.money import cents, format_money, line_total, money_sum


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (76, "76,00"),
        (76.0, "76,00"),
        (1587.5, "1 587,50"),
        (1234567.891, "1 234 567,89"),
        (0, "0,00"),
        (0.005, "0,01"),  # half up, not to even
        (1.005, "1,01"),  # float 1.005 is 1.00499…: decimals by repr, not by the binary value
        (2.675, "2,68"),
        (-1587.5, "-1 587,50"),
        (-0.004, "0,00"),  # no "-0,00"
    ],
)
def test_format_money_always_two_decimals(value: float, text: str) -> None:
    assert format_money(value) == text


@pytest.mark.parametrize("value", [76, 1587.5, 0.01, 1234567.89, -42.1])
def test_format_money_parses_back(value: float) -> None:
    assert parse_number(format_money(value)) == pytest.approx(value)


def test_cents_rounds_half_up_away_from_zero() -> None:
    assert cents(0.005) == 0.01
    assert cents(-0.005) == -0.01
    assert cents(0.004) == 0.0
    assert cents(10.125) == 10.13


def test_line_total_is_decimal_product_to_the_cent() -> None:
    assert 3 * 0.1 != 0.3  # the float product drifts
    assert line_total(3, 0.1) == 0.3
    assert line_total(1.5, 0.15) == 0.23  # 0.225 → 0.23
    assert line_total(12.34, 76) == 937.84
    assert line_total(0, 99.99) == 0.0


def test_money_sum_adds_without_drift() -> None:
    assert 0.1 + 0.2 != 0.3
    assert money_sum([0.1, 0.2]) == 0.3
    assert money_sum([]) == 0.0
    assert money_sum(line_total(3, 0.1) for _ in range(3)) == 0.9
