from typing import Any

import pytest
from pydantic import ValidationError

from floorplan_engine.model.schema import ElectricalPoint, Plan
from floorplan_engine.model.zones import place_of, point_places

# 4000 × 3000 clockwise from the origin: w1 up (left), w2 right (top), w3 down (right), w4 left
WALLS = [{"id": f"w{k + 1}", "length": n} for k, n in enumerate((3000, 4000, 3000, 4000))]


def _plan(zones: list[dict[str, Any]]) -> Plan:
    return Plan.model_validate(
        {
            "name": "тест",
            "default_wall_thickness": 120,
            "source": "text",
            "rooms": [{"id": "r", "name": "Кухня + прихожая", "walls": WALLS, "zones": zones}],
        }
    )


ZONES = [{"name": "Кухня", "walls": ["w2", "w3"]}, {"name": "Прихожая", "walls": ["w1"]}]


def _pt(pid: str, **kw: Any) -> ElectricalPoint:
    return ElectricalPoint.model_validate({"id": pid, "room": "r", "type": "socket", **kw})


def test_wall_point_takes_the_zone_of_its_wall() -> None:
    plan = _plan(ZONES)
    assert place_of(plan, _pt("a", wall="w3", offset=100, height=300)) == "Кухня"
    assert place_of(plan, _pt("b", wall="w1", offset=100, height=300)) == "Прихожая"


def test_wall_of_no_zone_and_room_without_zones_take_the_room_name() -> None:
    assert place_of(_plan(ZONES), _pt("a", wall="w4", offset=100, height=300)) == "Кухня + прихожая"
    assert place_of(_plan([]), _pt("a", wall="w1", offset=100, height=300)) == "Кухня + прихожая"


def test_ceiling_point_takes_the_zone_whose_outline_holds_it() -> None:
    # The kitchen outline: w2 and w3 closed by the diagonal (0, 3000) → (4000, 0)
    plan = _plan(ZONES)
    inside = _pt("a", type="light", ceiling=[3700, 1500])
    on_diagonal = _pt("b", type="light", ceiling=[2000, 1500])
    assert point_places(plan, [inside, on_diagonal]) == {"a": "Кухня", "b": "Кухня"}


def test_ceiling_point_outside_every_outline_takes_the_nearest_wall() -> None:
    # The hall has one wall, so no outline: by the nearest wall, w1 (hall) or w4 (no zone)
    plan = _plan(ZONES)
    near_w1 = _pt("a", type="light", ceiling=[300, 1500])
    near_w4 = _pt("b", type="light", ceiling=[1500, 200])
    assert point_places(plan, [near_w1, near_w4]) == {"a": "Прихожая", "b": "Кухня + прихожая"}


def test_unknown_room_gives_its_id() -> None:
    pt = ElectricalPoint.model_validate(
        {"id": "a", "room": "x", "type": "light", "ceiling": [1, 1]}
    )
    assert place_of(_plan(ZONES), pt) == "x"


@pytest.mark.parametrize(
    ("zones", "message"),
    [
        ([{"name": "Кухня", "walls": ["w9"]}], "нет стены w9"),
        (
            [{"name": "Кухня", "walls": ["w1"]}, {"name": "Прихожая", "walls": ["w1"]}],
            "уже в другой",
        ),
    ],
)
def test_zone_walls_are_checked(zones: list[dict[str, Any]], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _plan(zones)


def _floors(zones: list[dict[str, Any]]) -> list[Any]:
    from floorplan_engine.model.zones import plan_floors
    from floorplan_engine.validation.plan import validate_plan

    plan = _plan(zones)
    _, contours = validate_plan(plan)
    return plan_floors(plan, contours)


def test_zones_that_take_every_wall_split_the_floor() -> None:
    """On the plan each zone is its own floor (2026-11-11): its outline closes along the
    boundary with the next zone, the zone areas add up to the room."""
    floors = _floors(
        [{"name": "Кухня", "walls": ["w1", "w2"]}, {"name": "Прихожая", "walls": ["w3", "w4"]}]
    )
    assert [(f.key, f.name, f.walls) for f in floors] == [
        ("zone:r.1", "Кухня", ("w1", "w2")),
        ("zone:r.2", "Прихожая", ("w3", "w4")),
    ]
    assert [len(f.vertices) for f in floors] == [3, 3]  # a corner cut by the diagonal
    assert sum(f.area_mm2 for f in floors) == pytest.approx(12e6)


def test_zones_that_leave_a_wall_keep_one_floor() -> None:
    (floor,) = _floors(ZONES)  # w4 is in no zone
    assert (floor.key, floor.name, floor.area_m2) == (
        "room:r",
        "Кухня + прихожая",
        pytest.approx(12),
    )
