"""Loads: typical point power and the design peak of the backup bus (decision 2026-11-11)."""

from __future__ import annotations

import pytest

from floorplan_engine.electrical.loads import (
    FLOOR_HEATING_W,
    POST_SHARE,
    SOCKET_POST_W,
    Kind,
    Load,
    assumed_mark,
    backup_peak,
    backup_share,
    group_kind,
    point_load,
)
from floorplan_engine.model.schema import Electrical, ElectricalPoint


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


def test_lights_with_a_fan_stay_a_lighting_group() -> None:
    """Decision 2026-11-13: a fan or a hood output on a lighting line does not turn the group
    into a socket group (light cable and breaker); a socket or a big output does."""
    from floorplan_engine.electrical.loads import Kind, assumed_mark, group_kind

    def elec(extra: dict[str, object]) -> Electrical:
        lamp = {"id": "l1", "room": "r", "type": "downlight", "ceiling": [500, 500], "group": "QF1"}
        key = {"id": "k1", "room": "r", "wall": "w1", "offset": 500, "height": 900,
               "type": "switch", "group": "QF1", "note": "свет + вентилятор"}  # fmt: skip
        point = {"room": "r", "wall": "w1", "offset": 900, "height": 2400, "group": "QF1", **extra}
        return Electrical.model_validate({"points": [lamp, key, point]})

    fan = elec({"id": "f1", "type": "outlet", "note": "эл. вентилятор"})
    assert group_kind(fan, "QF1") is Kind.LIGHT
    assert assumed_mark(fan, "QF1", fan.points) == "3x1.5"
    socket = elec({"id": "s1", "type": "socket"})
    assert group_kind(socket, "QF1") is Kind.SOCKETS
    assert assumed_mark(socket, "QF1", socket.points) == "3x2.5"
    big = elec({"id": "o1", "type": "outlet", "power": 1500})
    assert group_kind(big, "QF1") is Kind.SOCKETS


def test_thermostat_is_a_floor_heating_load_and_a_power_cable() -> None:
    """The type names the load: no note needed, unlike a switch or an output with "ТП"."""
    bare = point_load(_point("thermostat"), "Коридор", "ru")
    noted = point_load(_point("thermostat", "санузел"), "Коридор", "ru")
    assert bare is not None and (bare.power, bare.assumed) == (FLOOR_HEATING_W, True)
    assert bare.title == "Регулятор тёплого пола"
    assert noted is not None and (noted.power, noted.title) == (FLOOR_HEATING_W, "Санузел")
    old = point_load(_point("switch", "регулятор ТП"), "Коридор", "ru")
    assert old is not None and old.power == FLOOR_HEATING_W  # the same load as before the type
    point = _point("thermostat").model_copy(update={"group": "QF1"})
    elec = Electrical.model_validate({"points": [point.model_dump()]})
    assert assumed_mark(elec, "QF1", elec.points) == "3x2.5"  # not a lighting cable
    assert group_kind(elec, "QF1") is Kind.SOCKETS
