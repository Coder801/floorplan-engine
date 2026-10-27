from __future__ import annotations

from typing import Any

from floorplan_engine.schema import Plan


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
