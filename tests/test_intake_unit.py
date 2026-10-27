"""Пути к полям по id: get_target, set_target, index_path на синтетических словарях."""

from __future__ import annotations

import re
from typing import Any

import pytest

from floorplan_engine.intake import TargetError, get_target, index_path, set_target


def _data() -> dict[str, Any]:
    return {
        "name": "тест",
        "rooms": [
            {"id": "hall", "walls": [{"id": "w1", "length": 1000}]},
            {
                "id": "kitchen",
                "walls": [{"id": "w1", "length": 3000}, {"id": "w2", "length": 4000}],
                "openings": [{"id": "kitchen_door_1", "offset": 300}],
            },
        ],
    }


def test_target_error_is_value_error() -> None:
    assert issubclass(TargetError, ValueError)


@pytest.mark.parametrize(
    ("target", "value"),
    [
        ("name", "тест"),
        ("rooms.kitchen.walls.w2.length", 4000),
        ("rooms.hall.walls.w1.length", 1000),
        ("rooms.kitchen.openings.kitchen_door_1.offset", 300),
    ],
)
def test_get_target_by_ids(target: str, value: Any) -> None:
    assert get_target(_data(), target) == value


def test_get_target_missing_last_field_is_none() -> None:
    assert get_target(_data(), "rooms.kitchen.walls.w1.thickness") is None


def test_get_target_returns_list_field_as_is() -> None:
    assert [w["id"] for w in get_target(_data(), "rooms.kitchen.walls")] == ["w1", "w2"]


@pytest.mark.parametrize(
    ("target", "message"),
    [
        ("rooms.bath.walls.w1.length", "нет объекта с id «bath»"),
        ("plan.rooms", "нет поля «plan»"),
        ("name.x.y", "не объект и не список"),
        ("rooms.kitchen", "«rooms» — не объект"),  # последний шаг — в списке
        ("rooms.kitchen.walls.w1.length.x", "не объект"),
    ],
)
def test_get_target_bad_path_raises(target: str, message: str) -> None:
    with pytest.raises(TargetError, match=message):
        get_target(_data(), target)


def test_get_target_error_names_path_of_parent() -> None:
    with pytest.raises(
        TargetError, match=re.escape("в «rooms.kitchen.walls» нет объекта с id «w9»")
    ):
        get_target(_data(), "rooms.kitchen.walls.w9.length")


def test_get_target_root_is_named_in_error() -> None:
    with pytest.raises(TargetError, match="«<корень>»"):
        get_target(_data(), "missing.length")


def test_set_target_replaces_value() -> None:
    data = _data()
    set_target(data, "rooms.kitchen.walls.w2.length", 4500)
    assert data["rooms"][1]["walls"][1]["length"] == 4500
    assert data["rooms"][1]["walls"][0]["length"] == 3000


def test_set_target_creates_missing_field() -> None:
    data = _data()
    set_target(data, "rooms.hall.walls.w1.thickness", 120)
    assert data["rooms"][0]["walls"][0] == {"id": "w1", "length": 1000, "thickness": 120}


def test_set_target_does_not_create_objects() -> None:
    data = _data()
    with pytest.raises(TargetError):
        set_target(data, "rooms.bath.walls.w1.length", 1)
    assert [r["id"] for r in data["rooms"]] == ["hall", "kitchen"]


def test_set_target_by_id_in_list_is_error() -> None:
    with pytest.raises(TargetError, match="не объект"):
        set_target(_data(), "rooms.kitchen", {})


@pytest.mark.parametrize(
    ("target", "path"),
    [
        ("name", "name"),
        ("rooms.kitchen.walls.w2.length", "rooms[1].walls[1].length"),
        ("rooms.hall.walls.w1.length", "rooms[0].walls[0].length"),
        ("rooms.kitchen.openings.kitchen_door_1.offset", "rooms[1].openings[0].offset"),
        ("rooms.kitchen", "rooms[1]"),
    ],
)
def test_index_path_converts_ids_to_indexes(target: str, path: str) -> None:
    assert index_path(_data(), target) == path


def test_index_path_missing_dict_keys_stay_named() -> None:
    assert index_path({}, "sheet.title.text") == "sheet.title.text"


def test_index_path_unknown_id_raises_stop_iteration() -> None:
    # validate._question_paths ловит именно StopIteration
    with pytest.raises(StopIteration):
        index_path(_data(), "rooms.bath.walls")
