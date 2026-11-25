"""Joints in flush boxes (electrical/splices.py, decision 2026-11-25): which conductor joins how
many wires at a point of a socket loop or a light chain, clamps and sleeves, labels."""

from __future__ import annotations

from typing import Any

import pytest

from floorplan_engine.electrical.splices import (
    FlushBoxJoints,
    Joint,
    back_box_joints,
    clamp_counts,
    deep_label,
    splice_label,
    wago_clamps,
)
from tests.conftest import room_wiring
from tests.conftest import wall_point as _pt


def _clamps(joints: dict[str, FlushBoxJoints]) -> dict[str, dict[str, int]]:
    return {pid: dict(clamp_counts({pid: fb})) for pid, fb in joints.items()}


def _lamp(pid: str, x: float, y: float) -> dict[str, Any]:
    return {"id": pid, "room": "r", "type": "downlight", "ceiling": [x, y], "group": "QF1"}


@pytest.mark.parametrize(
    ("wires", "clamps"),
    [(0, []), (1, []), (2, ["412"]), (3, ["413"]), (4, ["415"]), (5, ["415"]),
     (6, ["415", "413"]), (8, ["415", "415"])],
)  # fmt: skip
def test_wago_clamps_by_wires(wires: int, clamps: list[str]) -> None:
    """The smallest clamp that takes the wires; more than five — two clamps with a jumper."""
    assert wago_clamps(wires) == clamps


@pytest.mark.parametrize(
    ("extra", "count"),
    [
        ({"plaster": "before"}, 1),
        ({"plaster": "before"}, 2),
        ({}, 2),  # after plaster, two chases (separate)
        ({"loop_conduit": "shared", "conduit": "walls"}, 2),
        ({"loop_conduit": "shared", "conduit": "walls"}, 1),
    ],
)
def test_socket_loop_has_no_joints(extra: dict[str, Any], count: int) -> None:
    """Sockets in a loop (decision 2026-11-25): the cables go into the double terminals, the
    sockets of a block are joined by jumpers, PE too — no joint in any way of laying the cable,
    single sockets and blocks alike."""
    sockets = [_pt(f"s{k}", "socket", 600 + 1000 * k, 300, "QF2", count=count) for k in range(3)]
    wiring, elec = room_wiring(sockets, distribution="loop", **extra)
    assert not wiring.boxes and any(r.source in ("s0", "s1", "s2") for r in wiring.runs)
    assert back_box_joints(wiring, elec) == {}


def test_light_chain_switch_passes_n_and_pe_on() -> None:
    """At the switch N and PE go on to the lights (2-wire clamps, no tap); the phase goes into
    the device and the switched wire out of it — no joint on L."""
    points = [
        _lamp("l1", 1000, 1500),
        _lamp("l2", 2000, 1500),
        _pt("k1", "switch", 2500, 900, "QF1"),
    ]
    wiring, elec = room_wiring(points, light_wiring="chain")
    assert not wiring.boxes
    joints = back_box_joints(wiring, elec)
    assert _clamps(joints) == {"k1": {"412": 2}}
    assert [(j.conductor, j.taps) for j in joints["k1"].joints] == [("N", 0), ("PE", 0)]


def test_light_chain_pass_switches_get_no_phase_joint() -> None:
    """Pass switches: panel → first → second (travellers, N, PE) → the light; at both only N and
    PE are joined."""
    points = [
        _lamp("l1", 1500, 2000),
        _pt("p1", "pass_switch", 500, 900, "QF1"),
        _pt("p2", "pass_switch", 2500, 900, "QF1"),
    ]
    wiring, elec = room_wiring(points, light_wiring="chain")
    assert {(r.source, r.target) for r in wiring.runs} & {("p1", "p2"), ("p2", "p1")}
    assert _clamps(back_box_joints(wiring, elec)) == {"p1": {"412": 2}, "p2": {"412": 2}}


def test_light_chain_switch_feeding_another_branches_the_phase() -> None:
    """One cable of a group into the room: the switch nearest to the panel feeds the other one —
    the phase joins in, the device and the feed on (3 wires, the feed is its only line out); N
    and PE go on. The fed switch gives N and PE on to its light."""
    points = [
        _lamp("l1", 1500, 2000),
        _pt("k1", "switch", 500, 900, "QF1"),
        _pt("k2", "switch", 2500, 900, "QF1"),
    ]
    wiring, elec = room_wiring(points, light_wiring="chain")
    assert {(r.source, r.target) for r in wiring.runs} == {
        ("board", "k2"),
        ("k2", "k1"),
        ("k1", "l1"),
    }
    joints = back_box_joints(wiring, elec)
    assert _clamps(joints) == {"k1": {"412": 2}, "k2": {"412": 2, "413": 1}}
    feed = next(r.id for r in wiring.runs if (r.source, r.target) == ("k2", "k1"))
    phase = joints["k2"].joints[0]
    assert (phase.conductor, phase.wires, phase.outs, phase.taps) == ("L", 3, (feed,), 1)


def test_boxes_have_no_flush_box_joints() -> None:
    points = [
        _lamp("l1", 1000, 1500),
        _pt("k1", "switch", 2500, 900, "QF1"),
        _pt("s1", "socket", 500, 300, "QF2"),
        _pt("s2", "socket", 1500, 300, "QF2"),
    ]
    wiring, elec = room_wiring(points)
    assert wiring.boxes and back_box_joints(wiring, elec) == {}


def test_labels_for_the_table_and_the_card() -> None:
    fb = FlushBoxJoints(
        "k", "w1", ("w2",), 1, (Joint("L", 3, ("w2",), 1), Joint("N", 2, ("w2",), 0))
    )
    assert splice_label(fb, "wago", "ru") == "Wago 1×412 + 1×413"
    assert splice_label(fb, "crimp", "ru") == "гильзы ×2"
    assert splice_label(fb, "crimp", "uk") == "гільзи ×2"
    assert deep_label("ru") == "глуб. ≥60" and deep_label("uk") == "глиб. ≥60"
