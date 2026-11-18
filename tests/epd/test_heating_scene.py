"""Floor heating in the 3D scene (epd/heating_scene.py): the sheet's zone lifted by height."""

from __future__ import annotations

import itertools
import math
from types import SimpleNamespace
from typing import Any, cast

import pytest

from floorplan_engine.electrical.floor_heating import heating_zones
from floorplan_engine.electrical.wiring_model import Wiring
from floorplan_engine.epd.heating_scene import CABLE_Z_MM, feed, heating_scene
from floorplan_engine.model.schema import Electrical
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan

WALLS = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]
REG = {"id": "t1", "room": "r", "type": "thermostat", "wall": "w4", "offset": 500, "height": 900}
SPOT = [20.0, 500.0, 900.0]  # the controller in the scene (build_scene points[…].pos)


def _wiring(*runs: tuple[str, str, str], boxes: tuple[str, ...] = ()) -> Wiring:
    """Only what feed reads: runs (id, source, target) and box ids."""
    return cast(
        Wiring,
        SimpleNamespace(
            runs=[SimpleNamespace(id=i, source=s, target=t) for i, s, t in runs],
            boxes=[SimpleNamespace(id=b) for b in boxes],
        ),
    )


def _scene(heating: bool = True, wiring: Wiring | None = None) -> dict[str, Any]:
    plan = make_plan(WALLS)
    _, contours = validate_plan(plan)
    fh = [{"id": "fh1", "room": "r", "thermostat": "t1"}] if heating else []
    elec = Electrical.model_validate({"points": [REG], "floor_heating": fh})
    return heating_scene(plan, contours, elec, wiring, {"t1": {"pos": SPOT}})


def test_zone_is_the_sheet_zone_on_the_floor() -> None:
    plan = make_plan(WALLS)
    _, contours = validate_plan(plan)
    elec = Electrical.model_validate(
        {"points": [REG], "floor_heating": [{"id": "fh1", "room": "r", "thermostat": "t1"}]}
    )
    (zone,) = heating_zones(plan, contours, elec)
    z = heating_scene(plan, contours, elec, None, {"t1": {"pos": SPOT}})["heating"]["fh1"]
    assert (z["key"], z["room"], z["thermostat"]) == ("heating:fh1", "r", "t1")
    assert z["area"] and len(z["area"][0][0]) >= 3
    # The serpentine at the screed height, as long as the section (turns as chords: a bit shorter)
    assert {p[2] for p in z["cable"]} == {CABLE_Z_MM}
    length = sum(math.dist(a, b) for a, b in itertools.pairwise(z["cable"]))
    assert length == pytest.approx(zone.route.length if zone.route else 0, rel=0.01)
    assert all(a != b for a, b in itertools.pairwise(z["cable"]))


@pytest.mark.parametrize("part", ["lead", "sensor"])
def test_lead_and_sensor_drop_from_the_controller(part: str) -> None:
    pts = _scene()["heating"]["fh1"][part]
    assert pts[0] == SPOT
    assert pts[1] == [SPOT[0], SPOT[1], CABLE_Z_MM]
    assert all(p[2] == CABLE_Z_MM for p in pts[1:])


def test_no_zones_no_key() -> None:
    assert _scene(heating=False) == {}


def test_feed_walks_from_the_controller_to_the_panel() -> None:
    wiring = _wiring(
        ("wire_1", "board", "box_1"),
        ("wire_2", "box_1", "t1"),
        ("wire_3", "box_1", "s1"),  # another point of the box is not the feed
        boxes=("box_1",),
    )
    assert feed(wiring, "t1") == (["wire_2", "wire_1"], ["box_1"])
    assert _scene(wiring=wiring)["heating"]["fh1"]["feed"] == {
        "wires": ["wire_2", "wire_1"],
        "boxes": ["box_1"],
    }


def test_feed_stops_at_a_daisy_chain_point_and_without_a_line() -> None:
    wiring = _wiring(("wire_1", "board", "s1"), ("wire_2", "s1", "t1"))
    assert feed(wiring, "t1") == (["wire_2"], [])
    assert feed(wiring, "nowhere") == ([], [])
