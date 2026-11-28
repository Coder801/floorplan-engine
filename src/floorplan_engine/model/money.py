"""Money: sums to the cent, rounded half up, and shown with two decimals ("76,00").

The estimate (electrical and plumbing), the agreed terms, the work plan stages and the service
work plan count money here, so md, csv, xlsx, the .epd and the API agree to the cent: a line
sum is qty × price rounded to the cent (decimal arithmetic, not float: 1.005 → 1.01), a total
is the sum of the rounded lines.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def _decimal(value: float) -> Decimal:
    # repr of a float is its shortest exact decimal: 0.1 → "0.1", not 0.1000000000000000055…
    return Decimal(repr(float(value)))


def _cents(value: Decimal) -> Decimal:
    out = value.quantize(CENT, rounding=ROUND_HALF_UP)
    return out if out else CENT * 0  # -0.00 → 0.00


def cents(value: float) -> float:
    """A sum rounded to the cent, half up (away from zero): 0.005 → 0.01, -0.005 → -0.01."""
    return float(_cents(_decimal(value)))


def line_total(qty: float, price: float) -> float:
    """The sum of an item: qty × price in decimals, rounded to the cent (3 × 0.1 → 0.3)."""
    return float(_cents(_decimal(qty) * _decimal(price)))


def money_sum(values: Iterable[float]) -> float:
    """A total of sums already rounded to the cent, without float drift (0.1 + 0.2 → 0.3)."""
    return float(_cents(sum((_decimal(v) for v in values), Decimal(0))))


def format_money(value: float) -> str:
    """A sum for the reader: always two decimals, space between thousands, decimal comma
    (76 → "76,00", 1587.5 → "1 587,50"); parse_number reads it back."""
    return f"{_cents(_decimal(value)):,.2f}".replace(",", " ").replace(".", ",")
