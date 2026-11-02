from __future__ import annotations

from typing import Any

from floorplan_engine.model.schema import Plan


def make_plan(walls: list[dict[str, Any]], openings: list[dict[str, Any]] | None = None) -> Plan:
    """Одна комната «r»; стенам без id даются w1, w2…, проёмам — o1, o2…"""
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
    """Санузел 2000×2500 (bath, wet) и кухня 3000×2500 (kitchen) справа за перегородкой 100 мм,
    дверь из санузла в кухню — на w3 санузла (offset 1500, ширина 700)."""
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
