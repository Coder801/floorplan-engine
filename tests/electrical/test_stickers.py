"""Sticker content: short names and icons from the group purpose and the device."""

from __future__ import annotations

import pytest

from floorplan_engine.electrical.loads import Breaker, Kind, Load, PanelGroup
from floorplan_engine.electrical.panel import BoardPanel, Device
from floorplan_engine.electrical.stickers import (
    build_stickers,
    group_icon,
    short_name,
)
from floorplan_engine.model.panel_catalog import DeviceKind


def group(name: str, purpose: str, kind: Kind = Kind.SOCKETS, room: str = "Кухня") -> PanelGroup:
    load = Load("p1", room, "Розетка", 1, 300.0, False)
    return PanelGroup(
        name,
        kind,
        purpose,
        False,
        (load,),
        "3x2.5",
        2.5,
        Breaker("C", 16, False),
        None,
        False,
        False,
    )


def board(devices: tuple[Device, ...], groups: tuple[PanelGroup, ...]) -> BoardPanel:
    return BoardPanel(
        "standard", None, False, groups, devices, Breaker("C", 63, False), 0.0, 1.0, (), None, None,
        rows=(devices[:1], devices[1:]),
    )  # fmt: skip


@pytest.mark.parametrize(
    ("purpose", "rooms", "expected"),
    [
        ("Розетка: бойлер — Санвузол", ["Санвузол"], ("Бойлер", "Санвузол")),
        ("Вивід: кондиціонер — Спальня", ["Спальня"], ("Кондиціонер", "Спальня")),
        ("Освітлення, вивід — Санвузол", ["Санвузол"], ("Освітлення", "Санвузол")),
        ("Холодильник", [], ("Холодильник",)),
        ("Кондиціонер — зал", ["Зал-вітальня"], ("Кондиціонер", "Зал")),
        ("Тепла підлога — коридор, санвузол", [], ("Тепла підлога", "Коридор +1")),
        (
            "Розетки — Кухня-вітальня, коридор, передпокій",
            ["Кухня-вітальня, коридор, передпокій"],
            ("Розетки", "Кухня-вітальня"),
        ),
        (
            "Освітлення — Кімната (кабінет), Лоджія",
            ["Кімната (кабінет)", "Лоджія"],
            ("Освітлення", "Кімната +1"),
        ),
    ],
)
def test_short_name(purpose: str, rooms: list[str], expected: tuple[str, ...]) -> None:
    assert short_name(purpose, rooms) == expected


@pytest.mark.parametrize(
    ("purpose", "kind", "icon"),
    [
        ("Розетка: бойлер — Санвузол", Kind.SOCKETS, "droplet-bolt"),
        ("Розетка: посудомийка — Кухня", Kind.SOCKETS, "tools-kitchen-2"),
        ("Розетка: стиральная машина — Ванная", Kind.SOCKETS, "wash-machine"),
        ("Розетки — Санвузол 2 (пральня)", Kind.SOCKETS, "plug"),
        ("Освещение — Спальня", Kind.LIGHT, "bulb"),
        ("Группа 7", Kind.LIGHT, "bulb"),
        ("Сауна", Kind.HEAVY, "bolt"),
    ],
)
def test_group_icon(purpose: str, kind: Kind, icon: str) -> None:
    assert group_icon(group("QF1", purpose, kind)) == icon


def test_stickers_follow_the_rails_and_name_devices_without_a_group() -> None:
    relay = Device("KV1", DeviceKind.RELAY, "63 А", "Реле напряжения")
    spd = Device("FV1", DeviceKind.SPD, "", "УЗИП (защита от перенапряжения)")
    line = Device("QF1", DeviceKind.BREAKER, "C16", "Розетки", group="QF1")
    g = group("QF1", "Розетки — Кухня")
    stickers = build_stickers(board((relay, spd, line), (g,)))
    assert [(s.id, s.row) for s in stickers] == [("KV1", 0), ("FV1", 1), ("QF1", 1)]
    assert stickers[0].icon == "gauge"
    assert stickers[1].lines == ("УЗИП",)
    assert stickers[2].lines == ("Розетки", "Кухня")
    assert stickers[2].title == "Розетки — Кухня"


def test_device_outside_the_rails_still_gets_a_sticker() -> None:
    relay = Device("KV1", DeviceKind.RELAY, "63 А", "Реле напряжения")
    panel = board((relay,), ())
    from dataclasses import replace

    assert [s.id for s in build_stickers(replace(panel, rows=()))] == ["KV1"]
