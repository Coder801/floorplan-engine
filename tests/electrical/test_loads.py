"""Loads: typical point power and the design peak of the backup bus (decision 2026-11-11)."""

from __future__ import annotations

from typing import Any

import pytest

from floorplan_engine.electrical.loads import (
    FLOOR_HEATING_W,
    POST_SHARE,
    SOCKET_POST_W,
    WATER,
    Kind,
    Load,
    assumed_mark,
    backup_peak,
    backup_share,
    group_kind,
    group_zone,
    panel_groups,
    point_load,
    rcd_of,
    shared_rcd_key,
)
from floorplan_engine.model.schema import Electrical, ElectricalPoint, Plan


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


def test_rcd_by_scheme_floor_heating_always_protected() -> None:
    """Decision 2026-11-16: the model wins; premium protects every group, standard every group
    but lighting; economy only wet ones; floor heating (a controller or a note) in any scheme
    and any room."""
    socket, light = _point("socket"), _point("light")
    heating = [_point("thermostat")]
    by_note = [_point("socket", "тепла підлога")]
    for scheme in ("standard", "premium"):
        assert rcd_of(scheme, Kind.SOCKETS, [socket], False, None) == "30 мА"
    assert rcd_of("premium", Kind.LIGHT, [light], False, None) == "30 мА"
    assert rcd_of("standard", Kind.LIGHT, [light], False, None) is None  # plain breaker
    assert rcd_of("standard", Kind.LIGHT, [light], True, None) is None  # a bathroom fan too
    assert rcd_of("standard", Kind.LIGHT, [light], False, "30 мА") == "30 мА"  # the model
    assert rcd_of("economy", Kind.SOCKETS, [socket], False, None) is None
    assert rcd_of("economy", Kind.SOCKETS, [socket], True, None) == "30 мА"  # a wet zone
    assert rcd_of("economy", Kind.SOCKETS, heating, False, None) == "30 мА"
    assert rcd_of("economy", Kind.SOCKETS, by_note, False, None) == "30 мА"
    assert rcd_of("economy", Kind.SOCKETS, [socket], False, "10 мА") == "10 мА"  # the model


ROOMS = [
    ("kitchen", "Кухня"),
    ("bed", "Спальня"),
    ("kid", "Дитяча"),
    ("hall", "Коридор"),
    ("loggia", "Лоджія"),
    ("bath", "Санвузол"),
]


def _flat() -> Plan:
    """Six rooms in a row, 3000 × 3000 each; the bathroom is wet by its name."""
    return Plan.model_validate(
        {
            "name": "T",
            "default_wall_thickness": 100,
            "source": "text",
            "rooms": [
                {
                    "id": rid,
                    "name": name,
                    "origin": [k * 3200, 0],
                    "walls": [{"id": f"w{n}", "length": 3000} for n in range(1, 5)],
                }
                for k, (rid, name) in enumerate(ROOMS)
            ],
        }
    )


def _pt(pid: str, kind: str, group: str, room: str, **kw: Any) -> dict[str, Any]:
    return {
        "id": pid,
        "room": room,
        "type": kind,
        "wall": "w1",
        "offset": 500,
        "height": 300,
        "group": group,
        **kw,
    }


def _groups(points: list[dict[str, Any]], scheme: str = "standard", **extra: Any) -> dict[str, Any]:
    elec = Electrical.model_validate(
        {
            "points": points,
            "board": {"room": "hall", "wall": "w1", "offset": 2000, "height": 1700},
            "panel": {"scheme": scheme, "backup": "none"},
            **extra,
        }
    )
    groups = panel_groups(_flat(), elec, elec.panel.scheme or "standard", False)
    return {g.group: g for g in groups}


def test_water_appliances_share_one_pattern() -> None:
    for note in ("пральна машина", "стиральная", "сушильна", "посудомойка", "бойлер", "водонагрев"):
        assert WATER.search(note), note
    assert not WATER.search("холодильник") and not WATER.search("духовка")


def test_group_zone_by_the_first_room_a_hall_is_public() -> None:
    places = {"a": "Спальня", "b": "Коридор", "c": "Вітальня", "d": "Гардеробна"}
    pt = _point("socket")
    pts = {k: pt.model_copy(update={"id": k}) for k in places}
    assert group_zone([pts["a"], pts["b"]], places) == "private"  # bedroom first
    assert group_zone([pts["b"], pts["a"]], places) == "public"  # hall first: public
    assert group_zone([pts["c"], pts["d"]], places) == "public"
    assert group_zone([pts["d"]], places) == "private"  # walk-in closet
    assert group_zone([], places) is None


def test_standard_shared_rcd_keys_by_zone_water_and_wet() -> None:
    """Decision 2026-11-16: in standard a wet group, a washer in the kitchen and a dryer in the
    hall get their own RCBOs; floor heating, bedroom and kitchen sockets go under the shared
    RCD of their kind; the hall and the loggia are the public zone; lighting has no RCD."""
    points = [
        _pt("k1", "socket", "QF1", "kitchen"),
        _pt("k2", "socket", "QF2", "kitchen", note="пральна машина"),
        _pt("h1", "socket", "QF3", "hall", note="сушильна машина"),
        _pt("b1", "socket", "QF4", "bed"),
        _pt("b2", "socket", "QF4", "hall"),  # a bedroom group that reaches the hall stays private
        _pt("h2", "socket", "QF5", "hall"),
        _pt("h3", "socket", "QF5", "bed"),  # the hall first: public
        _pt("w1", "socket", "QF6", "bath"),
        _pt("t1", "thermostat", "QF7", "bed"),
        _pt("t2", "thermostat", "QF7", "bath"),
        _pt("lg", "socket", "QF8", "loggia"),
        _pt("l1", "light", "QF9", "bath", wall=None, offset=None, height=None, ceiling=[1, 1]),
        _pt("l2", "light", "QF10", "bed", wall=None, offset=None, height=None, ceiling=[1, 1]),
        _pt("kd", "socket", "QF11", "kid"),
    ]
    g = _groups(points, groups={"QF10": {"rcd": "30 мА"}})
    keys = {k: shared_rcd_key("standard", v) for k, v in g.items()}
    assert keys == {
        "QF1": "public",
        "QF2": None,  # washer: RCBO, in the kitchen too
        "QF3": None,  # dryer: RCBO
        "QF4": "private",
        "QF5": "public",
        "QF6": None,  # wet room sockets: RCBO
        "QF7": "floor",  # floor heating of a bedroom and the bathroom under one RCD
        "QF8": "public",  # loggia: a closed dry room
        "QF9": None,  # bathroom lighting: a plain breaker
        "QF10": None,  # lighting with an rcd in the model: RCBO
        "QF11": "private",
    }
    assert g["QF2"].water and g["QF2"].zone == "public" and g["QF2"].rcd == "30 мА"
    assert g["QF9"].rcd is None and g["QF10"].rcd == "30 мА" and g["QF10"].rcd_from_model
    assert g["QF4"].zone == "private" and g["QF11"].zone == "private"
    economy = _groups(points, "economy", groups={"QF10": {"rcd": "30 мА"}})
    eco = {k: shared_rcd_key("economy", v) for k, v in economy.items()}
    assert eco == {  # economy as before: wet and floor heating under the one RCD
        k: ("wet" if k in ("QF6", "QF7", "QF10") else None) for k in g
    }
    premium = _groups(points, "premium")
    assert all(shared_rcd_key("premium", v) is None for v in premium.values())
    assert all(v.rcd == "30 мА" for v in premium.values())
