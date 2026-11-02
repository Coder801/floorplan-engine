from __future__ import annotations

import pytest
from pydantic import ValidationError

from floorplan_engine.model.plumbing import FIXTURE_SPECS, FixtureType, Obstacle, Plumbing


def test_every_fixture_has_spec() -> None:
    assert set(FIXTURE_SPECS) == set(FixtureType)
    for spec in FIXTURE_SPECS.values():
        assert (spec.sewer is None) == (spec.drain_height is None)


def test_obstacle_by_wall_or_rect_only() -> None:
    Obstacle.model_validate({"id": "a", "room": "r", "type": "bath", "rect": [0, 0, 10, 10]})
    with pytest.raises(ValidationError, match="что-то одно"):
        Obstacle.model_validate(
            {"id": "a", "room": "r", "type": "bath", "rect": [0, 0, 10, 10], "wall": "w1"}
        )
    with pytest.raises(ValidationError, match="все четыре"):
        Obstacle.model_validate({"id": "a", "room": "r", "type": "box", "wall": "w1"})
    with pytest.raises(ValidationError, match="x1 > x0"):
        Obstacle.model_validate({"id": "a", "room": "r", "type": "box", "rect": [5, 0, 1, 10]})


def test_defaults() -> None:
    p = Plumbing.model_validate({})
    assert p.distribution == "collector" and p.route == "floor" and p.input is None
