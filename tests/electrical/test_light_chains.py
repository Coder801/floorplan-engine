"""Tests of electrical/light_chains.py: light in a chain without boxes."""

from __future__ import annotations

from floorplan_engine.electrical.light_chains import PASS_MARK, TWO_KEY_MARK
from floorplan_engine.electrical.wiring_context import END_ALLOWANCE, LIGHT_LOOP
from floorplan_engine.model.schema import Electrical
from tests.conftest import make_plan
from tests.electrical.conftest import (
    DOOR,
    RECT,
    base_elec,
    chain_wiring,
    wall_point,
    wiring_of,
)


def test_light_chain_goes_panel_switch_lights_without_boxes() -> None:
    w = chain_wiring([])
    lit = [r for r in w.runs if r.group == "QF1"]
    assert not [b for b in w.boxes if b.group == "QF1"]
    assert {r.target: r.source for r in lit} == {"k1": "board", "l1": "k1", "l2": "l1"}
    loop = next(r for r in lit if r.target == "l2")  # ceiling light at the end of the chain
    assert loop.ends_mm == LIGHT_LOOP  # passes l1 (its loop counted on the way in), loop at l2
    first = next(r for r in lit if r.target == "l1")
    assert first.ends_mm == END_ALLOWANCE + LIGHT_LOOP  # at the switch and the loop at l1
    assert all(r.mark == "3x1.5" for r in lit)
    assert any(b.group == "QF3" for b in w.boxes)  # sockets keep their boxes


def test_light_chain_pass_and_two_key_switches() -> None:
    pts = [
        {"id": "l3", "room": "r", "type": "downlight", "ceiling": [2000, 3000], "group": "QF4"},
        wall_point("p1", "pass_switch", "w1", 1500, 900, "QF4"),
        wall_point("p2", "pass_switch", "w3", 1500, 900, "QF4"),
        {**wall_point("k2", "switch", "w2", 3500, 900, "QF5"), "keys": 2},
        {"id": "l4", "room": "r", "type": "downlight", "ceiling": [500, 3500], "group": "QF5"},
    ]
    w = chain_wiring(pts)
    by_target = {r.target: r for r in w.runs}
    pair = {by_target["p1"].source, by_target["p2"].source}
    assert pair in ({"board", "p1"}, {"board", "p2"})  # panel → first → second
    between = next(r for r in w.runs if r.source in ("p1", "p2") and r.target in ("p1", "p2"))
    assert between.mark == PASS_MARK and between.mark_assumed
    assert by_target["l3"].source in ("p1", "p2") and by_target["l3"].source != between.source
    assert by_target["l4"].source == "k2" and by_target["l4"].mark == TWO_KEY_MARK
    assert len({r.target for r in w.runs}) == len(w.runs)  # each point fed once


def test_light_chain_brings_one_cable_into_the_room() -> None:
    """Decision 2026-11-13: one cable of the group from the panel to the nearest switch, the
    other switches are fed from its flush box; a mechanism in the same frame by a jumper that
    stays in the wall."""
    pts = [
        wall_point("k2", "switch", "w1", 2500, 900, "QF1"),  # in one frame with k1
        {"id": "l3", "room": "r", "type": "downlight", "ceiling": [2000, 3000], "group": "QF1"},
        wall_point("k3", "switch", "w3", 1500, 900, "QF1"),
        {"id": "l4", "room": "r", "type": "downlight", "ceiling": [500, 3500], "group": "QF1"},
    ]
    links = [
        {"switch": "k1", "targets": ["l1", "l2"]},
        {"switch": "k2", "targets": ["l3"]},
        {"switch": "k3", "targets": ["l4"]},
    ]
    base = base_elec().model_dump(mode="json", by_alias=True, exclude_none=True)
    data = {**base, "points": [*base["points"], *pts], "light_wiring": "chain"}
    for lk in links:
        for p in data["points"]:
            if p["id"] == lk["switch"]:
                p["controls"] = lk["targets"]
    plan = make_plan(RECT, [DOOR])
    w = wiring_of(plan, Electrical.model_validate(data))
    lit = {r.target: r for r in w.runs if r.group == "QF1"}
    switches = {"k1", "k2", "k3"}
    fed = {k: lit[k].source for k in switches}
    assert sum(src == "board" for src in fed.values()) == 1  # one cable from the panel
    assert all(src == "board" or src in switches for src in fed.values())
    jumper = lit["k2"] if fed["k2"] == "k1" else lit["k1"]
    assert jumper.source in ("k1", "k2") and jumper.vertical_mm == 0  # inside the frame
    assert jumper.plan_mm < 100  # no route across the ceiling
    # Straight along the wall at any sheet scale: not out to the route lane and back (2026-11-15)
    assert len(jumper.path) == 2
    assert lit["k3"].vertical_mm > 0  # to the other wall: up to the ceiling and down
    assert all(lit[k].mark == "3x1.5" for k in switches)
    assert len(lit) == 7  # each point fed once

    premium = wiring_of(plan, Electrical.model_validate({**data, "mode": "proper"}))
    own = {r.target: r.source for r in premium.runs if r.target in switches}
    assert set(own.values()) == {"board"}  # a breaker per line: a panel line per switch
