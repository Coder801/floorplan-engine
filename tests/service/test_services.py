"""Services of a project (service/db/services.py): the catalog order, None is all of them."""

from __future__ import annotations

from floorplan_engine.service.db.services import SERVICES, normalize, unknown


def test_none_is_all_services() -> None:
    assert normalize(None) == ["electrical", "plumbing", "demolition"] == list(SERVICES)


def test_normalize_keeps_catalog_order_and_drops_the_rest() -> None:
    assert normalize(["demolition", "electrical", "electrical", "roof"]) == [
        "electrical",
        "demolition",
    ]
    assert normalize([]) == []


def test_unknown_keys_in_given_order() -> None:
    assert unknown(["roof", "electrical", "walls", "roof"]) == ["roof", "walls"]
    assert unknown(SERVICES) == []
