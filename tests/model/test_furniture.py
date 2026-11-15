from __future__ import annotations

import pytest
from pydantic import ValidationError

from floorplan_engine.model.furniture import (
    FURNITURE_FILE,
    Furniture,
    FurnitureBase,
    FurnitureItem,
    FurnitureKind,
    solid_spots,
)
from floorplan_engine.model.schema import HeatingExclude


def _item(**kw: object) -> FurnitureItem:
    data: dict[str, object] = {"id": "f1", "room": "r", "at": [0, 0], "size": [600, 3000]}
    return FurnitureItem.model_validate(data | {"kind": "kitchen"} | kw)


def test_base_follows_the_kind_unless_given() -> None:
    assert _item().solid and _item().base_assumed
    assert _item(kind="island").resting is FurnitureBase.SOLID
    assert not _item(kind="bed").solid and not _item(kind="sofa").solid
    assert not _item(kind="table").solid
    given = _item(kind="bed", base="solid")
    assert given.solid and not given.base_assumed
    assert not _item(kind="wardrobe", base="legs").solid


def test_other_needs_a_base_and_sides_are_positive() -> None:
    with pytest.raises(ValidationError, match="kind: other"):
        _item(kind="other")
    assert _item(kind="other", base="legs").resting is FurnitureBase.LEGS
    with pytest.raises(ValidationError, match="больше нуля"):
        _item(size=[0, 100])
    with pytest.raises(ValidationError):
        _item(kind="chair")
    with pytest.raises(ValidationError):
        _item(angle=45)  # only rectangles along the room axes


def test_solid_spots_by_room_in_file_order() -> None:
    furniture = Furniture(
        items=[
            _item(id="k", at=[100, 200]),
            _item(id="bed", kind=FurnitureKind.BED),
            _item(id="w", room="b", kind="wardrobe", size=[1800, 600]),
        ]
    )
    assert solid_spots(furniture) == {
        "r": [HeatingExclude(at=(100, 200), size=(600, 3000), note=f"{FURNITURE_FILE}: k")],
        "b": [HeatingExclude(at=(0, 0), size=(1800, 600), note=f"{FURNITURE_FILE}: w")],
    }
    assert solid_spots(Furniture()) == {}
