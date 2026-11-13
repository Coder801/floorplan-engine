"""LED supplies in the panel (electrical/led_supply.py): strips by output, the default strip,
the supply by power, the 12 V line by voltage drop; the LED box under the panel."""

from __future__ import annotations

from typing import Any

import pytest

from floorplan_engine.electrical.estimate import build_estimate, quantities
from floorplan_engine.electrical.led_supply import (
    DROP_MAX,
    SECTIONS,
    STRIP_DEFAULT_M,
    STRIP_W_PER_M,
    drop,
    led_lines,
    led_loads,
    section_for,
    supply_for,
)
from floorplan_engine.electrical.panel import build_panel
from floorplan_engine.electrical.pricing import MockPriceService, Prices
from floorplan_engine.electrical.wiring import box_wiring
from floorplan_engine.epd.panel_data import panel_data
from floorplan_engine.model.panel_catalog import DeviceKind
from floorplan_engine.model.schema import Electrical
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan
from tests.electrical.test_estimate import DOOR, ELEC, RECT, _pt


def _elec(supply: str = "board", **extra: Any) -> Electrical:
    points = [
        *ELEC["points"],
        _pt("led1", "led_output", 500, 1500, "QF1"),
        _pt("led2", "led_output", 2500, 1500, "QF1", wall="w1"),
    ]
    return Electrical.model_validate({**ELEC, "points": points, "led_supply": supply, **extra})


def test_strip_goes_to_the_nearest_output_on_its_wall_others_to_the_first() -> None:
    strips = [
        {"id": "s_w1", "room": "r", "wall": "w1", "start": 2000, "end": 3000},  # led2's wall
        {"id": "s_w2", "room": "r", "wall": "w2", "start": 0, "end": 1500},  # no output there
    ]
    loads = {ld.point: ld for ld in led_loads(_elec(led_strips=strips))}
    assert loads["led2"].strips == ("s_w1",) and loads["led2"].metres == 1.0
    assert loads["led1"].strips == ("s_w2",) and loads["led1"].metres == 1.5
    assert not loads["led1"].metres_assumed


def test_output_without_a_strip_gets_the_default_five_metres() -> None:
    ld = led_loads(_elec())[0]
    assert ld.metres == STRIP_DEFAULT_M == 5.0 and ld.metres_assumed and ld.power_assumed
    assert ld.power == pytest.approx(5 * STRIP_W_PER_M)
    assert ld.supply == 100  # 72 W loaded to 80 % at most


def test_output_power_from_the_source_beats_the_strip() -> None:
    elec = _elec()
    points = [p.model_copy(update={"power": 20.0}) if p.id == "led1" else p for p in elec.points]
    ld = led_loads(elec.model_copy(update={"points": points}))[0]
    assert (ld.power, ld.power_assumed, ld.supply) == (20.0, False, 30)


def test_supply_series_and_oversize() -> None:
    assert supply_for(10) == (15, False)
    assert supply_for(48) == (60, False)
    assert supply_for(200) == (150, True)


def test_no_loads_with_supplies_at_the_strip_or_without_a_panel() -> None:
    assert led_loads(_elec("room")) == []
    assert led_loads(_elec().model_copy(update={"board": None})) == []


def test_section_by_voltage_drop() -> None:
    assert section_for(3000, 2.0) == 1.5
    assert drop(15000, 6.0, 1.5) == pytest.approx(2 * 15 * 6 * 0.0175 / 1.5 / 12)
    s = section_for(15000, 6.0)
    assert drop(15000, 6.0, s) <= DROP_MAX and s == 6.0
    assert section_for(40000, 10.0) == SECTIONS[-1]  # nothing is enough: the largest


def _plan_and_wiring(elec: Electrical) -> tuple[Any, Any]:
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    return plan, wiring


def test_led_box_under_the_panel_with_a_supply_per_output() -> None:
    elec = _elec()
    plan, wiring = _plan_and_wiring(elec)
    panel = build_panel(plan, elec)
    assert panel is not None and panel.led is not None
    led = panel.led
    assert [d.id for d in led.devices] == ["G1", "G2"]
    assert all(d.kind is DeviceKind.LED_PSU and d.label == "100 Вт 12 В" for d in led.devices)
    assert led.devices[0].model.modules == 4  # width by power
    assert [d.point for d in led.devices] == ["led1", "led2"]
    room = plan.rooms[0].name
    assert led.devices[0].title == f"Подсветка LED — {room}"  # no note: the default
    assert all(d not in panel.devices for d in led.devices)  # not in the main panel
    assert set(led.devices) <= set(panel.all_devices)
    assert any("5 м" in w.text["ru"] for w in panel.warnings)  # the default strip is a remark
    lines = led_lines(wiring, led.loads)
    assert set(lines) == {"led1", "led2"}
    run = next(r for r in wiring.runs if r.target == "led1")
    assert lines["led1"].mark == run.mark and lines["led1"].length_mm == run.length_mm


def test_led_line_is_titled_by_the_output_note_and_room() -> None:
    elec = _elec()
    points = [
        p.model_copy(update={"note": "подсветка шкафа"}) if p.id == "led1" else p
        for p in elec.points
    ]
    elec = elec.model_copy(update={"points": points})
    plan, _ = _plan_and_wiring(elec)
    panel = build_panel(plan, elec)
    assert panel is not None and panel.led is not None
    assert panel.led.devices[0].title == f"Подсветка шкафа — {plan.rooms[0].name}"


def test_supplies_at_the_strip_have_no_box() -> None:
    elec = _elec("room")
    plan, _ = _plan_and_wiring(elec)
    panel = build_panel(plan, elec)
    assert panel is not None and panel.led is None


def test_estimate_lists_supplies_by_power_and_the_box_enclosure() -> None:
    elec = _elec()
    plan, wiring = _plan_and_wiring(elec)
    panel = build_panel(plan, elec)
    assert panel is not None
    prices = Prices(None, MockPriceService())
    est = build_estimate(wiring, elec, prices, "ru", panel)
    keys = [ln.key for ln in est.lines]
    assert "led_psu_din" not in keys  # replaced by the devices of the LED box
    psu = next(ln for ln in est.lines if ln.key == "led_psu_din.100 Вт 12 В")
    assert psu.qty == 2 and "100 Вт 12 В" in psu.name
    assert "led_enclosure" in keys
    assert quantities(wiring, elec)["work.board_install"] == 2


def test_panel_data_gives_the_viewer_the_led_box_and_its_lines() -> None:
    elec = _elec()
    plan, wiring = _plan_and_wiring(elec)
    panel = build_panel(plan, elec)
    assert panel is not None
    data = panel_data(panel, {}, "ЩР", "ru", wiring)
    led = data["led"]
    assert isinstance(led, dict)
    assert [d["id"] for d in led["devices"]] == ["G1", "G2"]
    line = led["lines"][0]
    assert line["point"] == "led1" and line["metres_assumed"] is True
    assert line["title"].startswith("Подсветка LED — ")
    assert line["cable"].startswith("2x") and line["length"] > 0 and "drop_ok" in line
    no_wiring = panel_data(panel, {}, "ЩР", "ru")["led"]
    assert isinstance(no_wiring, dict) and "cable" not in no_wiring["lines"][0]
