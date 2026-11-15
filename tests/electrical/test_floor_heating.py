from __future__ import annotations

import itertools
from typing import Any

import pytest

from floorplan_engine.electrical.floor_heating import (
    DEFAULT_DENSITY,
    PITCH_MAX,
    PITCH_MIN,
    SENSOR_DEPTH,
    WALL_GAP,
    choose_length,
    heated_area,
    heating_power,
    heating_zones,
    with_heating,
)
from floorplan_engine.electrical.heating_layout import Straight
from floorplan_engine.electrical.loads import point_load
from floorplan_engine.model.furniture import Furniture, solid_spots
from floorplan_engine.model.geometry import Contour, trace_contour
from floorplan_engine.model.heating_catalog import GENERIC
from floorplan_engine.model.schema import Electrical, FloorHeating, HeatingExclude, Plan, Room
from tests.conftest import make_flat, make_plan

# A room 4000 × 3000: w1 left (up), w2 top, w3 right (down), w4 bottom (to the left)
ROOM = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]


def _plan(zones: list[dict[str, Any]] | None = None) -> tuple[Plan, dict[str, Contour]]:
    plan = make_plan(ROOM)
    if zones:
        room = Room.model_validate(plan.rooms[0].model_dump() | {"zones": zones})
        plan = plan.model_copy(update={"rooms": [room]})
    room = plan.rooms[0]
    return plan, {room.id: trace_contour(room, plan.default_wall_thickness)}


def _elec(*zones: dict[str, Any], power: float | None = None) -> Electrical:
    zones = zones or ({},)
    reg: dict[str, Any] = {"id": "t1", "room": "r", "type": "thermostat", "wall": "w4"}
    reg |= {"offset": 500, "height": 900, "group": "QF1"}
    if power is not None:
        reg["power"] = power
    return Electrical.model_validate(
        {
            "points": [reg],
            "floor_heating": [{"id": "fh1", "room": "r", "thermostat": "t1"} | z for z in zones],
        }
    )


def test_heated_area_is_the_floor_less_the_wall_gap_and_exclusions() -> None:
    plan, contours = _plan()
    fh = FloorHeating(id="fh", room="r", thermostat="t1")
    found = heated_area(plan, contours, fh)
    assert found is not None
    floor, area, blocked = found.floor, found.area, found.blocked
    assert floor.area == pytest.approx(12e6) and blocked == () and found.furniture == ()
    assert area.area == pytest.approx((4000 - 2 * WALL_GAP) * (3000 - 2 * WALL_GAP))
    spot = HeatingExclude(at=(0, 0), size=(1700, 750), note="ванна")
    found = heated_area(plan, contours, fh.model_copy(update={"exclude": [spot]}))
    assert found is not None
    cut, blocked = found.area, found.blocked
    assert len(blocked) == 1  # the gap goes round the exclusion too
    # The exclusion with its own gap, clipped by the wall gap: 1700 × 750 less
    assert cut.area == pytest.approx(area.area - 1700 * 750)
    assert not cut.intersects(blocked[0])
    # Solid furniture is cut out too and named; a piece off this floor is not
    sofa = HeatingExclude(at=(0, 2000), size=(2000, 600), note="furniture.yaml: k")
    away = HeatingExclude(at=(5000, 0), size=(500, 500), note="furniture.yaml: far")
    found = heated_area(plan, contours, fh.model_copy(update={"furniture": [sofa, away]}))
    assert found is not None and found.furniture == ("k",) and len(found.blocked) == 1


def test_zone_of_a_room_is_its_own_floor() -> None:
    plan, contours = _plan([{"name": "Прихожая", "walls": ["w1", "w2"]}])
    fh = FloorHeating(id="fh", room="r", thermostat="t1", zone="Прихожая")
    found = heated_area(plan, contours, fh)
    assert found is not None
    assert found.floor.area == pytest.approx(6e6)  # the walls w1, w2 closed by a diagonal
    assert heated_area(plan, contours, fh.model_copy(update={"zone": "нет"})) is None


def test_length_from_the_series_that_lays_at_the_recommended_pitch() -> None:
    # 3 m² × 150 W/m² / 18 W/m = 25 m: 27 is nearest, but only 20 fits the pitch range given
    assert choose_length(3.0, 150.0, GENERIC, 26_000, 30_000) == (27, True)
    assert choose_length(3.0, 150.0, GENERIC, 15_000, 22_000) == (20, True)
    # None fits: the longest section that is laid whole, never one with a leftover cable
    assert choose_length(3.0, 150.0, GENERIC, 200_000, 300_000) == (120, False)
    assert choose_length(1.5, 150.0, GENERIC, 10_500, 13_000) == (10, False)  # not 15 (2 m over)
    assert choose_length(0.3, 150.0, GENERIC, 3_000, 5_000) == (10, False)  # even 10 m is too long
    # A few centimetres of route over the section at the sparsest pitch still fit (FIT_SLACK)
    assert choose_length(1.5, 150.0, GENERIC, 10_030, 13_000) == (10, True)


def test_route_takes_the_whole_section_at_a_pitch_in_range() -> None:
    plan, contours = _plan()
    (zone,) = heating_zones(plan, contours, _elec())
    assert zone.density == DEFAULT_DENSITY and zone.density_assumed and zone.length_assumed
    assert zone.area_m2 == pytest.approx(3.8 * 2.8)
    assert zone.length in GENERIC.lengths
    assert zone.pitch is not None and PITCH_MIN <= zone.pitch <= PITCH_MAX
    assert zone.route is not None
    assert zone.route.length == pytest.approx(zone.length * 1000, abs=1e-6)
    assert zone.power == pytest.approx(18 * zone.length)
    assert zone.remarks == ()
    # Runs along the long side (X), the cable starts at the controller's wall
    assert zone.route.along_x and zone.route.start.y < 300
    # Cold lead: from the wall to the start; with the drop it is longer than the floor part
    assert zone.lead and (zone.lead[-1] - zone.route.start).length() < 1e-6
    assert zone.lead_m > 0.9
    # Sensor: between two neighbouring runs, SENSOR_DEPTH into the zone, not on a run
    tip = zone.sensor[-1]
    runs = [p for p in zone.route.pieces if isinstance(p, Straight)]
    gaps = sorted(abs(tip.y - r.a.y) for r in runs)
    assert gaps[0] == pytest.approx(zone.pitch / 2, abs=1e-3)
    assert min(tip.x - 100, 3900 - tip.x) == pytest.approx(SENSOR_DEPTH, abs=1.0)
    a, b = zone.gap_dim or (tip, tip)
    assert (b - a).length() == pytest.approx(zone.pitch)


def test_explicit_length_and_density() -> None:
    plan, contours = _plan()
    (dense,) = heating_zones(plan, contours, _elec({"density": 200}))
    (light,) = heating_zones(plan, contours, _elec({"density": 100}))
    assert dense.length > light.length and not dense.density_assumed
    (given,) = heating_zones(plan, contours, _elec({"length": 64}))
    assert given.length == 64 and not given.length_assumed
    assert given.route is not None and given.route.length == pytest.approx(64_000)
    (short,) = heating_zones(plan, contours, _elec({"length": 20}))
    assert short.pitch == PITCH_MAX and "не хватает" in short.remarks[0]
    assert short.route is not None and short.route.length == pytest.approx(20_000)
    (long,) = heating_zones(plan, contours, _elec({"length": 120}))
    assert long.pitch == PITCH_MIN and "не помещается" in long.remarks[0]
    assert long.route is not None and long.route.length < 120_000


def test_an_l_shaped_area_and_a_part_out_of_reach() -> None:
    plan, contours = _plan()
    corner = {"exclude": [{"at": [2000, 1500], "size": [2000, 1500]}]}
    (zone,) = heating_zones(plan, contours, _elec(corner))
    assert zone.route is not None and zone.route.covered == zone.route.cells
    assert zone.route.length == pytest.approx(zone.length * 1000)
    island = {"exclude": [{"at": [1500, 1000], "size": [1000, 1000]}]}
    (ring,) = heating_zones(plan, contours, _elec(island))
    assert any("не вся зона" in r for r in ring.remarks)


def test_controller_power_comes_from_its_sections() -> None:
    plan, contours = _plan()
    elec = _elec({}, {"id": "fh2", "length": 10})
    zones = heating_zones(plan, contours, elec)
    assert heating_power(zones) == {"t1": pytest.approx(sum(z.power for z in zones))}
    done = with_heating(plan, contours, elec)
    reg = done.points[0]
    assert reg.power == pytest.approx(sum(z.power for z in zones))
    load = point_load(reg, "Комната", "ru")
    assert load is not None and load.power == reg.power
    own = with_heating(plan, contours, _elec(power=2000))
    assert own.points[0].power == 2000  # the source wins
    assert with_heating(plan, contours, Electrical()) == Electrical()
    # The power with_heating puts on the controller does not change the layout: the same zones
    # come from the cache, the heavy layout is not run again
    assert heating_zones(plan, contours, done) is zones
    moved = done.model_copy(update={"points": [reg.model_copy(update={"offset": 900})]})
    assert heating_zones(plan, contours, moved) is not zones


def test_plumbing_spots_go_into_the_zone() -> None:
    plan, contours = _plan()
    spot = HeatingExclude(at=(0, 0), size=(1700, 750), note="plumbing.yaml: bath")
    plain = with_heating(plan, contours, _elec())
    spotted = with_heating(plan, contours, _elec(), {"r": [spot], "other": [spot]})
    assert spotted.floor_heating[0].fixtures == [spot]
    (a,), (b,) = heating_zones(plan, contours, plain), heating_zones(plan, contours, spotted)
    assert b.area_m2 < a.area_m2 and len(b.blocked) == 1


def test_empty_area_and_a_controller_in_another_room() -> None:
    plan, contours = _plan()
    elec = _elec({"exclude": [{"at": [0, 0], "size": [4000, 3000]}]})
    (empty,) = heating_zones(plan, contours, elec)
    assert empty.route is None and "пустая" in empty.remarks[0]
    missing = _elec({"room": "nope"})
    assert heating_zones(plan, contours, missing) == ()
    flat = make_flat()
    rooms = {r.id: trace_contour(r, flat.default_wall_thickness) for r in flat.rooms}
    reg = {"id": "t1", "room": "kitchen", "type": "thermostat", "wall": "w4", "offset": 500}
    other = Electrical.model_validate(
        {
            "points": [reg | {"height": 900}],
            "floor_heating": [{"id": "fh", "room": "bath", "thermostat": "t1"}],
        }
    )
    (zone,) = heating_zones(flat, rooms, other)
    # Over the floor through an opening of the partition (the door y 1500…2200 or the open
    # passage y 300…1000), at right angles
    assert zone.route is not None and zone.lead and zone.sensor
    assert (zone.lead[-1] - zone.route.start).length() < 1e-6
    crossing = [(a, b) for a, b in itertools.pairwise(zone.lead) if (a.x - 2050) * (b.x - 2050) < 0]
    assert crossing and all(1500 < a.y < 2200 or 300 < a.y < 1000 for a, _ in crossing)
    assert all(abs(a.x - b.x) < 1e-6 or abs(a.y - b.y) < 1e-6 for a, b in crossing)
    assert zone.lead_m > 0.9 + 2.0 and zone.sensor_m > 0.9
    assert not any("другом помещении" in r for r in zone.remarks)
    # No door between the rooms: a straight line with a remark, as before
    shut = Plan.model_validate(
        {
            **flat.model_dump(),
            "rooms": [r.model_dump() | {"openings": []} for r in flat.rooms],
        }
    )
    (blind,) = heating_zones(shut, rooms, other)
    assert blind.lead == () and blind.sensor == () and blind.lead_m > 0.9
    assert any("другом помещении" in r for r in blind.remarks)


def test_solid_furniture_is_cut_out_legs_are_not() -> None:
    plan, contours = _plan()
    furniture = Furniture.model_validate(
        {
            "items": [
                {"id": "k", "room": "r", "kind": "kitchen", "at": [0, 0], "size": [600, 3000]},
                {"id": "bed", "room": "r", "kind": "bed", "at": [2000, 500], "size": [1600, 2000]},
            ]
        }
    )
    plain = with_heating(plan, contours, _elec())
    cut = with_heating(plan, contours, _elec(), furniture=solid_spots(furniture))
    assert [ex.note for ex in cut.floor_heating[0].furniture] == ["furniture.yaml: k"]
    (a,), (b,) = heating_zones(plan, contours, plain), heating_zones(plan, contours, cut)
    # The kitchen with its WALL_GAP: 600 + 100 off the 100 mm wall strip, the whole depth
    assert a.area_m2 - b.area_m2 == pytest.approx(0.6 * 2.8)
    assert b.furniture == ("k",) and a.furniture == ()


def test_auto_zone_and_the_area_from_the_source() -> None:
    plan, contours = _plan()
    reg = {"id": "t1", "room": "r", "type": "thermostat", "wall": "w4", "offset": 500}
    elec = Electrical.model_validate({"points": [reg | {"note": "ТП, 5 м²", "height": 900}]})
    done = with_heating(plan, contours, elec)
    (fh,) = done.floor_heating
    assert fh.auto and fh.room == "r" and fh.area == 5.0
    (zone,) = heating_zones(plan, contours, done)
    assert zone.area_off  # 10.6 m² by the layout against 5 from the note
    assert done.points[0].power == pytest.approx(zone.power)
    close = _elec({"area": round(zone.area_m2 * 1.05, 2)})
    (near,) = heating_zones(plan, contours, close)
    assert not near.area_off
