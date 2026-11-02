from __future__ import annotations

import pytest
from pydantic import ValidationError

from floorplan_engine.model.schema import Wall


def test_wall_partition_flag() -> None:
    assert Wall.model_validate({"id": "w1", "length": 1000, "partition": True}).partition
    assert not Wall.model_validate({"id": "w1", "length": 1000}).partition


def test_wall_cannot_be_bearing_and_partition() -> None:
    with pytest.raises(ValidationError, match="несущей"):
        Wall.model_validate({"id": "w1", "length": 1000, "bearing": True, "partition": True})
