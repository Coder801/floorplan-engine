from __future__ import annotations

import pytest
from pydantic import ValidationError

from floorplan_engine.model.schema import (
    LIGHT_TYPES,
    SWITCH_TYPES,
    ElectricalPoint,
    PointType,
    Wall,
)


def test_wall_partition_flag() -> None:
    assert Wall.model_validate({"id": "w1", "length": 1000, "partition": True}).partition
    assert not Wall.model_validate({"id": "w1", "length": 1000}).partition


def test_wall_cannot_be_bearing_and_partition() -> None:
    with pytest.raises(ValidationError, match="несущей"):
        Wall.model_validate({"id": "w1", "length": 1000, "bearing": True, "partition": True})


def test_thermostat_is_a_wall_point_with_no_switch_fields() -> None:
    """A floor heating controller: on a wall like a switch, but it controls no light."""
    base = {"id": "t1", "room": "r", "type": "thermostat"}
    wall = {**base, "wall": "w1", "offset": 500, "height": 1500}
    assert ElectricalPoint.model_validate(wall).type is PointType.THERMOSTAT
    assert PointType.THERMOSTAT not in SWITCH_TYPES | LIGHT_TYPES
    with pytest.raises(ValidationError, match="на потолке"):
        ElectricalPoint.model_validate({**base, "ceiling": [500, 500]})
    with pytest.raises(ValidationError):
        ElectricalPoint.model_validate({**wall, "controls": ["l1"]})
    with pytest.raises(ValidationError):
        ElectricalPoint.model_validate({**wall, "keys": 2})
