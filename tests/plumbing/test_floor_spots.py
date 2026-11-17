from __future__ import annotations

import pytest

from floorplan_engine.model.plumbing import FIXTURE_SIZES, FixtureType, Plumbing
from floorplan_engine.plumbing.floor_spots import heating_spots
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_flat


def test_fixture_on_its_obstacle_is_not_cut_out_twice() -> None:
    """A bath drawn as an obstacle along the left wall, its mixer (the fixture) on the bottom wall
    at the bath's end: the obstacle is the footprint, no typical-size spot for the fixture; a
    bath elsewhere in the room still gets its typical spot."""
    plan = make_flat()
    _, contours = validate_plan(plan)
    bath = {
        "id": "b",
        "room": "bath",
        "type": "bath",
        "wall": "w1",
        "offset": 0,
        "width": 1700,
        "depth": 750,
    }

    def spots(offset: float) -> list[str | None]:
        plumbing = Plumbing.model_validate(
            {
                "fixtures": [
                    {"id": "tub", "room": "bath", "type": "bath", "wall": "w4", "offset": offset}
                ],
                "obstacles": [bath],
            }
        )
        return [s.note for s in heating_spots(plan, contours, plumbing)["bath"]]

    # w4 is the bottom wall, walked right to left from the corner with w3: 2000 − 400 = x 1600,
    # inside the bath (x ≤ 750 from the left wall is the bath's depth — 400 from w1 is on it)
    assert spots(2000 - 400) == ["plumbing.yaml: b"]
    assert spots(2000 - 1500) == ["plumbing.yaml: b", "plumbing.yaml (типовой размер): tub"]


def test_floor_obstacles_and_standing_fixtures_are_spots() -> None:
    plan = make_flat()
    _, contours = validate_plan(plan)
    plumbing = Plumbing.model_validate(
        {
            "fixtures": [
                {"id": "wc", "room": "bath", "type": "wc", "wall": "w4", "offset": 600},
                {"id": "s", "room": "bath", "type": "sink", "wall": "w1", "offset": 1500},
                {"id": "dw", "room": "kitchen", "type": "dishwasher", "wall": "w2", "offset": 900},
            ],
            "obstacles": [
                {
                    "id": "b",
                    "room": "bath",
                    "type": "bath",
                    "wall": "w1",
                    "offset": 0,
                    "width": 1700,
                    "depth": 750,
                },
                {"id": "c", "room": "kitchen", "type": "column", "rect": [100, 100, 400, 300]},
            ],
        }
    )
    spots = heating_spots(plan, contours, plumbing)
    bath = spots["bath"]
    # The bath along the left wall, then the WC at the bottom wall; a hanging sink is no spot
    # The obstacle by its real outline, the fixture by its typical size (an assumption)
    assert [s.note for s in bath] == ["plumbing.yaml: b", "plumbing.yaml (типовой размер): wc"]
    assert bath[0].at == pytest.approx((0, 0)) and bath[0].size == pytest.approx((750, 1700))
    w, d = FIXTURE_SIZES[FixtureType.WC]
    assert bath[1].at == pytest.approx((1400 - w / 2, 0)) and bath[1].size == pytest.approx((w, d))
    kitchen = spots["kitchen"]
    assert kitchen[0].at == pytest.approx((100, 100)) and kitchen[0].size == pytest.approx(
        (300, 200)
    )
    assert kitchen[1].note == "plumbing.yaml (типовой размер): dw"
    assert heating_spots(plan, contours, Plumbing()) == {}
