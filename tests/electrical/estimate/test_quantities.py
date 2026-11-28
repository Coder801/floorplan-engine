"""Electrical estimate quantities from the model, without prices."""

from __future__ import annotations

from typing import Any

import pytest

from floorplan_engine.electrical.estimate.items import LINES
from floorplan_engine.electrical.estimate.quantities import quantities
from floorplan_engine.electrical.led_supply import (
    LED_V,
    STRIP_DEFAULT_M,
    STRIP_W_PER_M,
    led_mark,
    section_for,
)
from floorplan_engine.electrical.low_links import LED_MARK
from floorplan_engine.electrical.splices import Splice, back_box_joints
from floorplan_engine.electrical.wiring import RESERVE, box_wiring
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan, room_wiring
from tests.electrical.test_estimate import DOOR, ELEC, LED, RECT, _pt, _wiring


def test_quantities_from_model() -> None:
    wiring, elec = _wiring()
    q = quantities(wiring, elec)
    for mark, m in wiring.by_mark().items():
        assert q[f"cable.{mark}"] == pytest.approx(round(m * (1 + RESERVE), 1))
    assert q["socket_box"] == 4  # 2 + 1 sockets + a switch
    assert q["frame.1"] == 2 and q["frame.2"] == 1
    assert q["switch2"] == 1 and q["socket"] == 3
    boxes = len(wiring.boxes)
    assert sum(v for k, v in q.items() if k.startswith("junction_box.")) == boxes
    assert all(f"junction_box.{b.size}" in q for b in wiring.boxes)  # by size
    assert q["crimp"] == 3 * boxes + 2  # two-key switch from a box
    assert q["breaker"] == 2
    narrow, wide = wiring.chase_length(wide=False), wiring.chase_length(wide=True)
    assert narrow + wide == pytest.approx(wiring.chase_mm)
    assert q["work.chase"] == pytest.approx(round(narrow / 1000, 1))
    assert q.get("work.chase_wide", 0) == pytest.approx(round(wide / 1000, 1))
    assert "work.marking" not in q  # end marking is part of work.cable
    assert q["work.insulation_test"] == 2  # per power group
    assert q["work.cable"] == pytest.approx(round(sum(r.length_mm for r in wiring.runs) / 1000, 1))


def test_wet_boxes_and_wall_holes_in_estimate() -> None:
    data = make_plan(RECT, [DOOR]).model_dump()
    data["rooms"][0]["wet"] = True
    plan = Plan.model_validate(data)
    _, contours = validate_plan(plan)
    elec = Electrical.model_validate(ELEC)
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    q = quantities(wiring, elec)
    ip = sum(v for k, v in q.items() if k.startswith("junction_box_ip."))
    assert ip == len(wiring.boxes) and not any(k.startswith("junction_box.") for k in q)
    assert q.get("work.cable_pass", 0) == sum(len(h.sleeves) for h in wiring.holes)
    assert "work.wall_hole" not in q and "work.wall_hole_large" not in q  # plumbing only


def test_rough_light_per_room_with_lights() -> None:
    wiring, elec = _wiring()
    keys = ("rough_holder", "rough_lamp", "rough_switch", "work.rough_light", "work.rough_switch")
    assert not set(keys) & set(quantities(wiring, elec))
    q = quantities(wiring, elec.model_copy(update={"rough_light": True}))
    assert [q[k] for k in keys] == [1] * 5  # one room


def test_rough_light_without_lights_is_not_in_the_estimate() -> None:
    wiring, elec = _wiring()
    sockets = [p for p in elec.points if p.type.value == "socket"]
    q = quantities(wiring, elec.model_copy(update={"rough_light": True, "points": sockets}))
    assert "rough_holder" not in q and "work.rough_switch" not in q


def _led_wiring(supply: str) -> tuple[Any, Electrical]:
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    points = [*ELEC["points"], LED]
    elec = Electrical.model_validate({**ELEC, "points": points, "led_supply": supply})
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    return wiring, elec


def test_led_supply_at_the_strip_is_fed_from_the_room_box() -> None:
    wiring, elec = _led_wiring("room")
    run = next(r for r in wiring.runs if r.target == "led1")
    assert run.source != "board" and run.mark == "3x1.5"
    q = quantities(wiring, elec)
    assert q["led_psu"] == q["work.led_psu"] == 1
    assert "led_psu_din" not in q and "work.led_psu_din" not in q


def test_led_supply_in_the_panel_gives_a_12v_line_of_its_own() -> None:
    wiring, elec = _led_wiring("board")
    run = next(r for r in wiring.runs if r.target == "led1")
    assert (run.source, run.circuit, run.group, run.led) == ("board", "low", "QF1", True)
    # The 12 V line goes by the voltage drop: the default 5 m strip draws 6 A
    current = STRIP_DEFAULT_M * STRIP_W_PER_M / LED_V
    assert run.mark == led_mark(section_for(run.length_mm, current)) != LED_MARK
    q = quantities(wiring, elec)
    assert q["led_psu_din"] == q["work.led_psu_din"] == 1 and "led_psu" not in q
    assert q[f"cable.{run.mark}"] > 0
    assert q["work.board_install"] == 2  # the LED supplies box is a second panel
    assert q["work.insulation_test"] == 2  # the 12 V line is no power group of its own
    assert "led_psu_din" in LINES and "work.led_psu_din" in LINES  # items the estimate prices


def test_no_led_outputs_no_supplies() -> None:
    wiring, elec = _wiring()
    q = quantities(wiring, elec.model_copy(update={"led_supply": "board"}))
    assert not {"led_psu", "led_psu_din", "work.led_psu", "work.led_psu_din"} & set(q)


def test_before_plaster_leaves_no_chase_work() -> None:
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    elec = Electrical.model_validate({**ELEC, "plaster": "before"})
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    q = quantities(wiring, elec)
    assert "work.chase" not in q and "work.chase_wide" not in q and q["work.cable"] > 0


def test_conduit_floor_always_ceiling_only_premium() -> None:
    """Conduit (docs/wiring-variants.md): on the floor always, the whole line; on the ceiling in
    premium, only the ceiling part; the diameter follows the cable cross-section."""
    from floorplan_engine.electrical.estimate.quantities import conduit_mm
    from floorplan_engine.electrical.mounting import conduit_diameter

    assert [conduit_diameter(m) for m in ("3x1.5", "3x2.5", "3x4", "5x10", "UTP")] == [
        20,
        20,
        25,
        32,
        20,
    ]
    wiring, elec = _wiring()
    run = wiring.runs[0]
    assert conduit_mm(run, "none") == 0  # ceiling: no conduit unless chosen
    assert conduit_mm(run, "ceiling") == run.plan_mm  # the ceiling part
    assert conduit_mm(run, "walls") == run.length_mm  # and the drops in the walls
    assert not any(k.startswith("conduit.") for k in quantities(wiring, elec))
    proper = quantities(wiring, elec.model_copy(update={"mode": "proper"}))
    assert any(k.startswith("conduit.") for k in proper) and proper["work.conduit"] > 0

    floor_elec = elec.model_copy(update={"route": "floor"})
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    floor = box_wiring(plan, contours, floor_elec)
    assert floor is not None and any(r.route == "floor" for r in floor.runs)
    q = quantities(floor, floor_elec)
    total = sum(v for k, v in q.items() if k.startswith("conduit."))
    # on the floor the whole line with margin; lighting runs on the ceiling (no conduit in
    # standard). Lines lying together share a conduit (2026-11-13): their stretch counts once
    from floorplan_engine.electrical.mounting import plan_conduits, source_conduits

    on_floor = [r for r in floor.runs if r.route == "floor"]
    shared = [*plan_conduits(floor, "none"), *source_conduits(floor, "none")]
    saved = sum(p.length * (len(p.runs) - 1) for p in shared)
    assert saved > 0
    expected = (sum(r.length_mm for r in on_floor) - saved) / 1000 * (1 + RESERVE)
    assert total == pytest.approx(expected, abs=0.3)


def test_floor_heating_zone_without_a_layout_buys_no_cable() -> None:
    """A zone with an empty heated area has no route: no section, no sensor, no work — the
    report already says why (a remark on the zone)."""
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    reg = _pt("t1", "thermostat", 2000, 1500, "QF5")
    whole = {"at": [0, 0], "size": [6000, 6000]}
    fh = [{"id": "fh1", "room": "r", "thermostat": "t1", "length": 20, "exclude": [whole]}]
    elec = Electrical.model_validate(
        {**ELEC, "points": [*ELEC["points"], reg], "floor_heating": fh}
    )
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    (zone,) = wiring.heating
    assert zone.route is None and zone.length == 20
    q = quantities(wiring, elec)
    assert not [k for k in q if "heating" in k]


def test_floor_heating_is_not_in_the_estimate_until_its_release() -> None:
    """Floor heating is held back (floor_heating.RELEASED, decision 2026-11-22): a zone is laid,
    but the estimate buys no section, sensor, conduit or laying work."""
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    reg = _pt("t1", "thermostat", 2000, 1500, "QF5")
    fh = [{"id": "fh1", "room": "r", "thermostat": "t1"}]
    elec = Electrical.model_validate(
        {**ELEC, "points": [*ELEC["points"], reg], "floor_heating": fh}
    )
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None and wiring.heating
    q = quantities(wiring, elec)
    assert not [k for k in q if "heating" in k]


def test_boxes_keep_crimps_and_no_splice_work() -> None:
    """Through junction boxes nothing changes: crimps as before, no splice work."""
    wiring, elec = _wiring()
    q = quantities(wiring, elec)
    assert q["crimp"] == 3 * len(wiring.boxes) + 2
    assert back_box_joints(wiring, elec) == {}
    assert "work.splice" not in q


def test_socket_loop_buys_no_clamps_and_no_splice_work() -> None:
    """Sockets in a loop (decision 2026-11-25): double terminals and jumpers, no joints — no
    sleeves, no splice work, whatever the studio's setting."""
    sockets = [_pt(f"s{k}", "socket", 600 + 1000 * k, 300, "QF2", count=2) for k in range(3)]
    wiring, elec = room_wiring(sockets, distribution="loop")
    assert not wiring.boxes and back_box_joints(wiring, elec) == {}
    splices: tuple[Splice, ...] = ("wago", "crimp")
    for splice in splices:
        q = quantities(wiring, elec, splice)
        assert not {"crimp", "work.splice", "work.splice_crimp"} & set(q)


def test_crimp_splice_leaves_box_crimps_as_they_are() -> None:
    """Light in a chain with sockets through boxes: box crimps as before; the switch joints are
    the work only, whatever the method."""
    points = [
        {"id": "l1", "room": "r", "type": "downlight", "ceiling": [1000, 1500], "group": "QF1"},
        {"id": "l2", "room": "r", "type": "downlight", "ceiling": [2000, 1500], "group": "QF1"},
        _pt("k1", "switch", 2500, 900, "QF1"),
        _pt("s1", "socket", 500, 300, "QF2"),
        _pt("s2", "socket", 1500, 300, "QF2"),
    ]
    wiring, elec = room_wiring(points, light_wiring="chain")
    assert wiring.boxes
    q = quantities(wiring, elec, "crimp")
    assert q["crimp"] == 3 * len(wiring.boxes) == quantities(wiring, elec, "wago")["crimp"]
    assert q["work.junction_box"] == len(wiring.boxes) and q["work.splice_crimp"] == 1
