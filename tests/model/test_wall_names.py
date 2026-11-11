from __future__ import annotations

from typing import Any

from floorplan_engine.model.schema import Plan
from floorplan_engine.model.wall_names import LETTERS, letter, wall_codes, wall_names
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_flat, make_plan

SQUARE = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]


def _names(plan: Plan) -> dict[tuple[str, str], Any]:
    _, contours = validate_plan(plan)
    return wall_names(plan, contours)


def test_letters_skip_lookalikes_and_repeat_with_a_number() -> None:
    assert not set("ЗОЧЁЙЪЬЫЭЄІЇ") & set(LETTERS)
    assert [letter(k) for k in range(3)] == ["А", "Б", "В"]
    assert letter(len(LETTERS)) == "А2"


def test_codes_are_unique_in_the_flat_by_schedule_number() -> None:
    plan = make_flat()
    _, contours = validate_plan(plan)
    codes = wall_codes(plan, contours)
    assert codes[("bath", "w1")] == "1.А" and codes[("bath", "w3")] == "1.В"
    assert codes[("kitchen", "w1")] == "2.А"
    assert len(set(codes.values())) == len(codes)


def test_zones_that_split_the_floor_get_numbers_of_their_own() -> None:
    walls = [{"id": f"w{k}", "length": n} for k, n in enumerate((3000, 6000, 3000, 6000), 1)]
    plan = Plan.model_validate(
        {
            "name": "т",
            "default_wall_thickness": 120,
            "source": "text",
            "rooms": [
                {
                    "id": "hall",
                    "name": "Кухня-гостиная",
                    "walls": walls,
                    "zones": [
                        {"name": "Кухня", "walls": ["w1", "w2"]},
                        {"name": "Прихожая", "walls": ["w3", "w4"]},
                    ],
                }
            ],
        }
    )
    _, contours = validate_plan(plan)
    codes = wall_codes(plan, contours)
    assert [codes[("hall", w)] for w in ("w1", "w2", "w3", "w4")] == ["1.А", "1.Б", "2.А", "2.Б"]


def test_description_says_what_is_behind_and_in_the_wall() -> None:
    names = _names(make_flat())
    assert names[("bath", "w3")].text == "Кухня за стеной, дверь"
    assert names[("bath", "w1")].text == "наружная"
    assert names[("bath", "w3")].full == "1.В · Кухня за стеной, дверь"


def test_openings_are_counted_in_ukrainian() -> None:
    plan = make_plan(
        SQUARE,
        [
            {"wall": "w2", "type": "window", "offset": 300, "width": 1000},
            {"wall": "w2", "type": "window", "offset": 2000, "width": 1000},
        ],
    )
    plan = plan.model_copy(update={"language": "uk"})
    assert _names(plan)[("r", "w2")].text == "зовнішня, вікно ×2"


def test_name_from_yaml_replaces_the_description_but_not_the_code() -> None:
    walls = [{**w, "name": "стена с телевизором"} if k == 1 else w for k, w in enumerate(SQUARE)]
    names = _names(make_plan(walls))
    assert names[("r", "w2")].full == "1.Б · стена с телевизором"
