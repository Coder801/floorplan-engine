"""Loads: typical point power and the design peak of the backup bus (decision 2026-11-11)."""

from __future__ import annotations

import pytest

from floorplan_engine.electrical.loads import (
    POST_SHARE,
    SOCKET_POST_W,
    Load,
    backup_peak,
    backup_share,
    point_load,
)
from floorplan_engine.model.schema import ElectricalPoint


def _load(title: str, power: float, *, post: bool = False) -> Load:
    return Load("p", "Кухня", title, 1, power, True, post=post)


def _point(type_: str, note: str | None = None, count: int = 1) -> ElectricalPoint:
    return ElectricalPoint.model_validate(
        {
            "id": "p",
            "room": "r",
            "type": type_,
            "wall": "w1",
            "offset": 100,
            "height": 300,
            "note": note,
            "count": count,
        }
    )


def test_typical_socket_post_is_marked_and_an_appliance_is_not() -> None:
    post = point_load(_point("socket", count=2), "Спальня", "ru")
    fridge = point_load(_point("socket", "Холодильник"), "Кухня", "ru")
    tv = point_load(_point("socket", "ТВ"), "Кабинет", "ru")  # a note, but no known power
    assert post is not None and post.post and post.power == 2 * SOCKET_POST_W
    assert fridge is not None and not fridge.post and fridge.power == 300
    assert tv is not None and tv.post


def test_fan_output_is_a_fan_not_an_unknown_appliance() -> None:
    fan = point_load(_point("outlet", "Ел. вентилятор"), "Санвузол", "uk")
    assert fan is not None and fan.power == 50


def test_backup_peak_counts_posts_partly_and_one_occasional_appliance() -> None:
    loads = [
        _load("Светильник", 100),
        _load("Холодильник", 300),
        _load("Розетка", 1000, post=True),
        _load("Микроволновка", 1200),
        _load("Чайник", 2200),
    ]
    steady, peak = backup_share(loads)
    assert steady == pytest.approx(100 + 300 + 1000 * POST_SHARE)
    assert peak == 2200  # the kettle; the microwave does not run at the same time
    assert backup_peak(loads) == pytest.approx(steady + peak)


def test_backup_peak_of_nothing_is_zero() -> None:
    assert backup_share([]) == (0.0, 0.0)
