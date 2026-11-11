"""Group colours by kind: lighting warm, sockets cool, heavy red, low-voltage green; shades in
number order within a family, in a circle."""

from __future__ import annotations

from typing import Any

from floorplan_engine.electrical.colors import (
    FAMILIES,
    LOW_VOLTAGE,
    family_colors,
    group_colors,
    rgb,
)
from floorplan_engine.electrical.loads import Kind
from floorplan_engine.model.schema import Electrical


def _pt(pid: str, kind: str, group: str, **extra: Any) -> dict[str, Any]:
    return {"id": pid, "room": "r", "type": kind, "wall": "w3", "offset": 500,
            "height": 300, "group": group, **extra}  # fmt: skip


def _colors(
    points: list[dict[str, Any]], cables: list[dict[str, Any]] | None = None
) -> dict[str, int]:
    return group_colors(Electrical.model_validate({"points": points, "cables": cables or []}))


def test_family_by_kind() -> None:
    colors = _colors(
        [
            _pt("l1", "sconce", "QF1"),
            _pt("k1", "switch", "QF1"),
            _pt("s1", "socket", "QF2"),
            _pt("b1", "outlet", "QF3", note="бойлер", power=2000),
            _pt("t1", "data", "QF4"),
        ],
        [{"id": "c1", "from": "board", "to": ["b1"], "group": "QF3", "cable": "3x4"}],
    )
    assert colors == {
        "QF1": rgb(FAMILIES[Kind.LIGHT][0]),
        "QF2": rgb(FAMILIES[Kind.SOCKETS][0]),
        "QF3": rgb(FAMILIES[Kind.HEAVY][0]),
        "QF4": rgb(FAMILIES[LOW_VOLTAGE][0]),
    }


def test_shades_in_number_order_and_in_a_circle() -> None:
    n = len(FAMILIES[Kind.SOCKETS])
    points = [_pt(f"s{k}", "socket", f"QF{k}") for k in range(1, n + 2)]
    points.append(_pt("l1", "light", "QF20"))
    colors = _colors(points)
    sockets = FAMILIES[Kind.SOCKETS]
    assert [colors[f"QF{k}"] for k in range(1, n + 1)] == [rgb(c) for c in sockets]
    assert colors[f"QF{n + 1}"] == rgb(sockets[0])  # in a circle
    assert colors["QF20"] == rgb(FAMILIES[Kind.LIGHT][0])  # a light group does not shift sockets


def test_family_colours_distinct() -> None:
    every = [c for family in FAMILIES.values() for c in family]
    assert len(every) == len(set(every))


def test_family_colors_only_present_families_and_used_shades() -> None:
    elec = Electrical.model_validate(
        {
            "points": [
                _pt("l1", "light", "QF1"),
                _pt("s1", "socket", "QF2"),
                _pt("s2", "socket", "QF3"),
            ]
        }
    )
    sockets = FAMILIES[Kind.SOCKETS]
    assert family_colors(elec) == {
        Kind.LIGHT: (rgb(FAMILIES[Kind.LIGHT][0]),),
        Kind.SOCKETS: (rgb(sockets[0]), rgb(sockets[1])),
    }
