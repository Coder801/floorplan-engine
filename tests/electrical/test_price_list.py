"""Price list of the electrical estimate: prices by key, foreign and retired keys, derived
prices, editing prices.yaml."""

from __future__ import annotations

from floorplan_engine.electrical.price_list import (
    Price,
    PriceList,
    derived_quote,
    edit_price_items,
    unknown_keys,
)
from floorplan_engine.electrical.pricing import Prices


def test_wide_chase_costs_half_as_much_again() -> None:
    """A wide chase is priced from a narrow one in the same material × 1.5, unless the price
    list names it itself."""
    own = PriceList.model_validate({"items": {"work.chase.brick": 120}})
    quote = derived_quote(Prices(own), "work.chase_wide.brick")
    assert quote.price is not None and quote.price.price == 180 and not quote.service
    named = PriceList.model_validate({"items": {"work.chase_wide.brick": 200}})
    quote = derived_quote(Prices(named), "work.chase_wide.brick")
    assert quote.price is not None and quote.price.price == 200
    assert derived_quote(Prices(PriceList()), "work.chase_wide.brick").price is None


def test_cable_pass_is_not_priced_from_the_old_hole() -> None:
    """Decision 2026-11-28: a cable pass (drilling, sleeve, foam) has its own price; work.wall_hole
    is a plumbing item now, and the old core-drilled hole is retired, not an unknown key."""
    old = PriceList.model_validate({"items": {"work.wall_hole": 100, "work.wall_hole_large": 250}})
    assert derived_quote(Prices(old), "work.cable_pass").price is None
    assert unknown_keys(old) == []


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


def test_unknown_keys_skips_retired_items() -> None:
    # an old price list with end marking, now part of work.cable, still loads
    prices = PriceList.model_validate({"items": {"work.marking": 10, "work.cable": 34}})
    assert unknown_keys(prices) == []


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


PRICES_TEXT = """# прайс студии
currency: грн
items:
  # Материалы
  socket_box: 20
  board_enclosure: { price: 6000, name: "Корпус" }
  work.cable: 30                 # по потолку
  # work.mechanism — впишите цену
board_kit: []
"""


def test_edit_price_items_keeps_comments() -> None:
    out = edit_price_items(
        PRICES_TEXT,
        {"work.cable": 25.5, "board_enclosure": 6500, "socket_box": None, "work.mechanism": 90},
    )
    cable = "  work.cable: 25.5                 # по потолку"
    assert cable in out
    assert 'board_enclosure: { price: 6500, name: "Корпус" }' in out
    assert "socket_box" not in out
    assert "# прайс студии" in out and "# work.mechanism — впишите цену" in out
    # A new key goes after the last value of items, before the next section
    lines = out.splitlines()
    assert lines.index("  work.mechanism: 90") < lines.index("board_kit: []")
    assert lines.index("  work.mechanism: 90") > lines.index(
        "  work.cable: 25.5                 # по потолку"
    )


def test_edit_price_items_without_items_section() -> None:
    assert edit_price_items("currency: грн\n", {"work.chase": 100}) == (
        "currency: грн\nitems:\n  work.chase: 100\n"
    )


def test_wide_chase_priced_from_narrow_in_the_same_material() -> None:
    own = PriceList.model_validate({"items": {"work.chase.brick": 100}})
    quote = derived_quote(Prices(own), "work.chase_wide.brick")
    assert quote.price is not None and quote.price.price == 150 and not quote.service
    named = PriceList.model_validate({"items": {"work.chase_wide.brick": 170}})
    quote = derived_quote(Prices(named), "work.chase_wide.brick")
    assert quote.price is not None and quote.price.price == 170


def test_old_wago_prices_are_ignored() -> None:
    """A price list saved before 2026-11-25 may name the clamps: not an error, the price is not
    used (RETIRED)."""
    prices = PriceList.model_validate(
        {"items": {"wago": 20, "wago.412": 18, "wago.413": 22, "wago.415": 28, "nope": 1}}
    )
    assert unknown_keys(prices) == ["nope"]


def test_price_list_and_its_users_import_on_their_own() -> None:
    """Each module imports alone in a fresh interpreter: price_list imports estimate.items, which
    runs the estimate package, and the package must not import price_list back at load time (a
    cycle the test run hides, since there the package is usually loaded first)."""
    import subprocess
    import sys

    for module in (
        "floorplan_engine.electrical.price_list",
        "floorplan_engine.electrical.pricing",
        "floorplan_engine.service.sync",
    ):
        done = subprocess.run(
            [sys.executable, "-c", f"import {module}"], capture_output=True, text=True, check=False
        )
        assert done.returncode == 0, f"{module}: {done.stderr.strip().splitlines()[-1:]}"
