from __future__ import annotations

from typing import Any

import pytest

from floorplan_engine.electrical.estimate import quantities as estimate_quantities
from floorplan_engine.electrical.wiring import box_wiring
from floorplan_engine.electrical.wiring_model import Wiring
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.sheets import stages


@pytest.fixture
def heating_released(monkeypatch: pytest.MonkeyPatch) -> None:
    """Floor heating switched on as after its release (floor_heating.RELEASED): the sheet and
    the estimate rows; the tests of the held-back feature itself keep running."""
    monkeypatch.setattr(estimate_quantities, "HEATING_RELEASED", True)
    monkeypatch.setattr(stages, "HEATING_RELEASED", True)


def make_plan(walls: list[dict[str, Any]], openings: list[dict[str, Any]] | None = None) -> Plan:
    """One room "r"; walls without an id get w1, w2…, openings o1, o2…"""
    walls = [{"id": f"w{k + 1}", **w} for k, w in enumerate(walls)]
    openings = [{"id": f"o{k + 1}", **o} for k, o in enumerate(openings or [])]
    return Plan.model_validate(
        {
            "name": "тест",
            "default_wall_thickness": 120,
            "source": "text",
            "rooms": [{"id": "r", "name": "Комната", "walls": walls, "openings": openings}],
        }
    )


def make_flat() -> Plan:
    """Bathroom 2000×2500 (bath, wet) and a kitchen 3000×2500 (kitchen) to its right behind a
    100 mm partition; the door from the bathroom into the kitchen is on the bathroom's w3
    (offset 1500, width 700)."""
    return Plan.model_validate(
        {
            "name": "тест",
            "default_wall_thickness": 200,
            "source": "text",
            "rooms": [
                {
                    "id": "bath",
                    "name": "Санузел",
                    "wet": True,
                    "origin": [0, 0],
                    "walls": [
                        {"id": "w1", "length": 2500},
                        {"id": "w2", "length": 2000},
                        {"id": "w3", "length": 2500, "thickness": 100},
                        {"id": "w4", "length": 2000},
                    ],
                    "openings": [
                        {
                            "id": "bath_door",
                            "wall": "w3",
                            "type": "door",
                            "offset": 1500,
                            "width": 700,
                        }
                    ],
                },
                {
                    "id": "kitchen",
                    "name": "Кухня",
                    "origin": [2100, 0],
                    "walls": [
                        {"id": "w1", "length": 2500, "thickness": 100},
                        {"id": "w2", "length": 3000},
                        {"id": "w3", "length": 2500},
                        {"id": "w4", "length": 3000},
                    ],
                    "openings": [
                        {
                            "id": "kitchen_open",
                            "wall": "w1",
                            "type": "opening",
                            "offset": 300,
                            "width": 700,
                        }
                    ],
                },
            ],
        }
    )


def wall_point(
    pid: str, kind: str, offset: float, height: float, group: str, **extra: Any
) -> dict[str, Any]:
    """A point on wall w3 of room "r" (make_plan)."""
    return {"id": pid, "room": "r", "type": kind, "wall": "w3", "offset": offset,
            "height": height, "group": group, **extra}  # fmt: skip


def room_wiring(points: list[dict[str, Any]], **extra: Any) -> tuple[Wiring, Electrical]:
    """Wiring of points in one room 3000×4000 with a door on w2 and the panel on w1 (offset 500,
    height 1700); extra — Electrical options (distribution, light_wiring…)."""
    from floorplan_engine.validation.plan import validate_plan

    walls = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]
    plan = make_plan(walls, [{"wall": "w2", "type": "door", "offset": 1000, "width": 900}])
    _, contours = validate_plan(plan)
    board = {"room": "r", "wall": "w1", "offset": 500, "height": 1700}
    elec = Electrical.model_validate({"points": points, "board": board, **extra})
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    return wiring, elec
