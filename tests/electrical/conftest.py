"""Shared fixtures of the wiring tests: a 3000 × 4000 room with a door, the points of the
base electrical model, two rooms with a partition and a door, four sockets of one group."""

from __future__ import annotations

import itertools
from typing import Any

from floorplan_engine.electrical.wiring import box_wiring
from floorplan_engine.electrical.wiring_model import Run
from floorplan_engine.model.schema import Electrical, Plan, WiringEdits
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan

RECT = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]


DOOR = {"wall": "w2", "type": "door", "offset": 1000, "width": 900}


def wall_point(
    pid: str, kind: str, wall: str, offset: float, height: float, group: str | None
) -> dict[str, Any]:
    return {
        "id": pid,
        "room": "r",
        "type": kind,
        "wall": wall,
        "offset": offset,
        "height": height,
        "group": group,
    }


def base_elec(cables: list[dict[str, Any]] | None = None) -> Electrical:
    return Electrical.model_validate(
        {
            "points": [
                {
                    "id": "l1",
                    "room": "r",
                    "type": "downlight",
                    "ceiling": [1000, 1500],
                    "group": "QF1",
                },
                {
                    "id": "l2",
                    "room": "r",
                    "type": "downlight",
                    "ceiling": [3000, 1500],
                    "group": "QF1",
                },
                wall_point("k1", "switch", "w1", 2500, 900, "QF1"),
                wall_point("s1", "socket", "w4", 1000, 300, "QF2"),  # single point: from the panel
                wall_point("s2", "socket", "w3", 500, 300, "QF3"),
                wall_point("s3", "socket", "w3", 2500, 300, "QF3"),
                {
                    "id": "d1",
                    "room": "r",
                    "type": "data",
                    "wall": "w4",
                    "offset": 3000,
                    "height": 300,
                },  # no group: low-voltage, a line of its own (from the panel without media)
            ],
            "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700},
            "cables": cables or [],
        }
    )


def wiring_of(plan: Plan, elec: Electrical) -> Any:
    issues, contours = validate_plan(plan)
    assert not issues
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    return wiring


def two_rooms_with_door(**partition: Any) -> Plan:
    """Rooms a and b, 3000 × 3000, with a 100 partition and an 800 door at y 1200…2000 (a door in
    a, an opening in b); partition: extra fields of the partition in both rooms.
    """

    def room(rid: str, x: float, inner: str, opening: dict[str, Any]) -> dict[str, Any]:
        walls = [
            {
                "id": f"w{k}",
                "length": 3000,
                **({"thickness": 100, **partition} if f"w{k}" == inner else {}),
            }
            for k in range(1, 5)
        ]
        return {"id": rid, "name": rid, "origin": [x, 0], "walls": walls, "openings": [opening]}

    door = {"id": "a_door_1", "wall": "w3", "type": "door", "offset": 1000, "width": 800}
    gap = {"id": "b_opening_1", "wall": "w1", "type": "opening", "offset": 1200, "width": 800}
    return Plan.model_validate(
        {
            "name": "тест",
            "default_wall_thickness": 200,
            "source": "text",
            "rooms": [room("a", 0, "w3", door), room("b", 3100, "w1", gap)],
        }
    )


def crossings_of(run: Run) -> list[float]:
    """y of the pieces crossing the partition x 3000…3100."""
    return [
        a.y
        for a, b in itertools.pairwise(run.path)
        if min(a.x, b.x) < 3000 and max(a.x, b.x) > 3100
    ]


def edited_wiring(edits: dict[str, Any], elec: Electrical | None = None) -> Any:
    """Wiring of the room with the manual edits of wiring.yaml (box spots, line routes)."""
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    wiring = box_wiring(plan, contours, elec or base_elec(), WiringEdits.model_validate(edits))
    assert wiring is not None
    return wiring


def four_sockets(**extra: Any) -> Electrical:
    """Four sockets of one group on one wall: at the panel end and at the far end."""
    points = [
        wall_point(f"s{k}", "socket", "w3", offset, 300, "QF2")
        for k, offset in enumerate((500, 1500, 2500, 3500), start=1)
    ]
    data = {
        "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1500, "name": "ЩР"},
        "points": points,
        **extra,
    }
    return Electrical.model_validate(data)


def chain_wiring(points: list[dict[str, Any]]) -> Any:
    """Light without boxes: the points of base_elec plus the given ones, light_wiring chain."""
    base = base_elec().model_dump(mode="json", by_alias=True, exclude_none=True)
    data = {**base, "points": [*base["points"], *points], "light_wiring": "chain"}
    return wiring_of(make_plan(RECT, [DOOR]), Electrical.model_validate(data))
