"""Wiring through boxes: topology, lengths, assumptions."""

from __future__ import annotations

import itertools
import math
from dataclasses import replace
from typing import Any

import pytest
from ezdxf import bbox
from shapely.geometry import Point, Polygon
from shapely.geometry import box as shapely_box

from floorplan_engine.drawing.layers import W_TEXT, new_document
from floorplan_engine.drawing.wiring import (
    bundles,
    cable_layer,
    draw_wiring,
    fillet,
    lanes,
    offset_path,
    segments,
)
from floorplan_engine.electrical.boxes import BOX_CLEARANCE
from floorplan_engine.electrical.chases import HOLE_CABLES
from floorplan_engine.electrical.estimate import PriceList, build_estimate
from floorplan_engine.electrical.panel import LineClass
from floorplan_engine.electrical.wiring import END_ALLOWANCE, box_wiring, section
from floorplan_engine.electrical.wiring_model import (
    BOX_ABOVE_FLOOR,
    BOX_BELOW_CEILING,
    CHASE_NARROW,
    Chase,
    Run,
    Wiring,
    line_starts,
)
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan

RECT = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]
DOOR = {"wall": "w2", "type": "door", "offset": 1000, "width": 900}


def _wall(
    pid: str, kind: str, wall: str, offset: float, height: float, group: str
) -> dict[str, Any]:
    return {
        "id": pid,
        "room": "r",
        "type": kind,
        "wall": wall,
        "offset": offset,
        "height": height,
        "group": group,
    }


def _elec(cables: list[dict[str, Any]] | None = None) -> Electrical:
    return Electrical.model_validate(
        {
            "points": [
                {
                    "id": "l1",
                    "room": "r",
                    "type": "downlight",
                    "ceiling": [1000, 1500],
                    "group": "QF1",
                },
                {
                    "id": "l2",
                    "room": "r",
                    "type": "downlight",
                    "ceiling": [3000, 1500],
                    "group": "QF1",
                },
                _wall("k1", "switch", "w1", 2500, 900, "QF1"),
                _wall("s1", "socket", "w4", 1000, 300, "QF2"),  # single point: from the panel
                _wall("s2", "socket", "w3", 500, 300, "QF3"),
                _wall("s3", "socket", "w3", 2500, 300, "QF3"),
                {
                    "id": "d1",
                    "room": "r",
                    "type": "data",
                    "wall": "w4",
                    "offset": 3000,
                    "height": 300,
                },  # no group: not in the calculation
            ],
            "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700},
            "cables": cables or [],
        }
    )


def _wiring(plan: Plan, elec: Electrical) -> Any:
    issues, contours = validate_plan(plan)
    assert not issues
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    return wiring


def test_topology_board_box_point_only() -> None:
    w = _wiring(make_plan(RECT, [DOOR]), _elec())
    boxes = {b.id: b for b in w.boxes}
    assert sorted(b.group for b in w.boxes) == ["QF1", "QF3"]  # QF2 has one point, no box
    for r in w.runs:
        assert r.source == "board" or r.source in boxes  # no cable runs from a load
        if r.target in boxes:
            assert r.source == "board"  # a box is fed only from the panel
    targets = {r.target: r.source for r in w.runs}
    assert targets["s1"] == "board"
    assert {targets["l1"], targets["l2"], targets["k1"]} == {"box_1"}
    assert w.skipped == ("d1",)


def test_run_length_parts() -> None:
    w = _wiring(make_plan(RECT, [DOOR]), _elec())
    s2 = next(r for r in w.runs if r.target == "s2")
    assert s2.vertical_mm == pytest.approx(2700 - 300)  # ceiling box: no drop
    assert s2.ends_mm == 2 * END_ALLOWANCE
    plan_mm = sum(abs(b.x - a.x) + abs(b.y - a.y) for a, b in itertools.pairwise(s2.path))
    assert s2.plan_mm == pytest.approx(plan_mm)
    # The route has right angles only
    assert all(
        abs(b.x - a.x) < 1e-6 or abs(b.y - a.y) < 1e-6 for a, b in itertools.pairwise(s2.path)
    )
    l1 = next(r for r in w.runs if r.target == "l1")
    assert l1.vertical_mm == 0.0  # box and light on the ceiling: no drops


def test_ceiling_height_default_is_assumption() -> None:
    w = _wiring(make_plan(RECT, [DOOR]), _elec())
    assert w.ceiling_height == 2700 and w.height_assumed
    data = make_plan(RECT, [DOOR]).model_dump(exclude={"ceiling_height"})
    plan = Plan.model_validate({**data, "ceiling_height": 3000})
    w2 = _wiring(plan, _elec())
    assert not w2.height_assumed
    s2 = next(r for r in w2.runs if r.target == "s2")
    assert s2.vertical_mm == pytest.approx(3000 - 300)


@pytest.mark.parametrize(
    ("note", "power", "mark"),
    [
        ("варильна поверхня", None, "3x6"),  # typical 7.2 kW: 31.3 A, breaker 32
        ("варильна поверхня", 5500.0, "3x4"),  # 23.9 A, breaker 25
        ("духова шафа", None, "3x2.5"),  # 15.2 A, breaker 16
        ("бойлер", None, "3x2.5"),  # 2 kW: never below the power default
    ],
)
def test_heavy_load_without_cable_gets_mark_by_load(
    note: str, power: float | None, mark: str
) -> None:
    point = {**_wall("h1", "outlet", "w4", 1000, 750, "QF9"), "note": note, "power": power}
    elec = _elec().model_copy(
        update={"points": Electrical.model_validate({"points": [point]}).points}
    )
    run = next(r for r in _wiring(make_plan(RECT, [DOOR]), elec).runs if r.group == "QF9")
    assert (run.mark, run.mark_assumed) == (mark, True)


def test_mark_from_model_or_assumed() -> None:
    cable = {"id": "c1", "from": "board", "to": ["s1"], "group": "QF2", "cable": "3x4"}
    w = _wiring(make_plan(RECT, [DOOR]), _elec([cable]))
    marks = {r.group: (r.mark, r.mark_assumed) for r in w.runs}
    assert marks["QF2"] == ("3x4", False)
    assert marks["QF1"] == ("3x1.5", True) and marks["QF3"] == ("3x2.5", True)


def test_box_not_in_doorway() -> None:
    w = _wiring(make_plan(RECT, [DOOR]), _elec())
    for b in w.boxes:
        a = b.anchor
        # The box on the top wall (w2, y = 3000) stays clear of the door 1000…1900 with a margin
        if abs(a.pos.y - 3000) < 1e-6:
            assert not (1000 - BOX_CLEARANCE < a.pos.x < 1900 + BOX_CLEARANCE)


def test_no_board_no_wiring() -> None:
    plan = make_plan(RECT)
    _, contours = validate_plan(plan)
    elec = Electrical.model_validate({"points": [_wall("s1", "socket", "w1", 500, 300, "QF1")]})
    assert box_wiring(plan, contours, elec) is None


def _two_rooms_with_door() -> Plan:
    """Rooms a and b, 3000 × 3000, with a 100 partition and an 800 door (a door in a, an opening
    in b).
    """

    def room(rid: str, x: float, inner: str, opening: dict[str, Any]) -> dict[str, Any]:
        walls = [
            {"id": f"w{k}", "length": 3000, **({"thickness": 100} if f"w{k}" == inner else {})}
            for k in range(1, 5)
        ]
        return {"id": rid, "name": rid, "origin": [x, 0], "walls": walls, "openings": [opening]}

    door = {"id": "a_door_1", "wall": "w3", "type": "door", "offset": 1000, "width": 800}
    gap = {"id": "b_opening_1", "wall": "w1", "type": "opening", "offset": 1200, "width": 800}
    return Plan.model_validate(
        {
            "name": "тест",
            "default_wall_thickness": 200,
            "source": "text",
            "rooms": [room("a", 0, "w3", door), room("b", 3100, "w1", gap)],
        }
    )


def test_cable_to_other_room_goes_through_door() -> None:
    plan = _two_rooms_with_door()
    elec = Electrical.model_validate(
        {
            "points": [
                {"id": "l1", "room": "b", "type": "light", "ceiling": [1500, 1500], "group": "QF1"},
                {
                    "id": "s1",
                    "room": "b",
                    "type": "socket",
                    "wall": "w3",
                    "offset": 2500,
                    "height": 300,
                    "group": "QF2",
                },
            ],
            "board": {"room": "a", "wall": "w1", "offset": 500, "height": 1700},
        }
    )
    w = _wiring(plan, elec)
    # A single light still goes through a box; a single socket comes from the panel
    assert [b.group for b in w.boxes] == ["QF1"] and w.boxes[0].room == "b"
    assert {r.target: r.source for r in w.runs}["s1"] == "board"
    for run in w.runs:
        for a, b in itertools.pairwise(run.path):
            # Crossing the partition (x 3000…3100) only in the opening: y 1200…2000
            if min(a.x, b.x) < 3000 and max(a.x, b.x) > 3100:
                assert 1200 <= a.y <= 2000 and a.y == b.y
    # Box cables do not leave its room
    for run in w.runs:
        if run.source == w.boxes[0].id:
            assert all(p.x >= 3100 for p in run.path)


def test_fillet_rounds_right_angles() -> None:
    path = [Vec(0, 0), Vec(1000, 0), Vec(1000, 1000), Vec(2000, 1000)]
    pts = fillet(path, 50)
    # Each turn is two tangent vertices, a 90° arc (bulge = tan 22.5°) signed by the turn direction
    assert len(pts) == 6
    assert pts[1] == pytest.approx((950, 0, math.tan(math.radians(22.5))))  # left
    assert pts[2] == pytest.approx((1000, 50, 0))
    assert pts[3] == pytest.approx((1000, 950, -math.tan(math.radians(22.5))))  # right
    # A short piece gives the arc at most half
    short = fillet([Vec(0, 0), Vec(40, 0), Vec(40, 1000)], 50)
    assert short[1][0] == pytest.approx(20)
    # A straight line has no extra vertices
    assert fillet([Vec(0, 0), Vec(500, 0), Vec(1000, 0)], 50) == [(0, 0, 0), (1000, 0, 0)]


def test_wiring_sheet_labels_lengths_and_drops() -> None:
    plan = make_plan(RECT, [DOOR])
    issues, contours = validate_plan(plan)
    assert not issues
    elec = _elec()
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    doc = new_document()
    msp = doc.modelspace()
    draw_wiring(msp, wiring, elec, {})
    texts = [t.dxf.text for t in msp.query("TEXT")]
    s2 = next(r for r in wiring.runs if r.target == "s2")
    assert f"↓h{s2.rise_end_mm / 1000:.1f}".replace(".", ",") in texts  # drop to the socket
    assert any(t.startswith("↑") for t in texts)  # rise from the panel
    # Length labels follow bundle pieces: length and cable count if more than one
    segs = segments([r.path for r in wiring.runs])
    expected = {_length_label(b.length, len(b.runs)) for b in bundles(segs, lanes(segs, 1.0, 3.0))}
    numbers = [t for t in texts if t.startswith("L")]
    assert numbers and set(numbers) <= expected
    assert any("×" in t for t in numbers)  # cables run as a bundle at the box
    # Labels do not overlap each other
    boxes = []
    for t in msp.query("TEXT"):
        if t.dxf.layer != W_TEXT.name:
            continue
        ext = bbox.extents([t])
        boxes.append(shapely_box(ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y))
    for a, b in itertools.combinations(boxes, 2):
        assert a.intersection(b).area < 1e-6


def testcable_layer_by_purpose_protection_and_route() -> None:
    """Layer of a line: what its group is and where it runs; low-voltage by its circuit."""
    plan = make_plan(RECT, [DOOR])
    issues, contours = validate_plan(plan)
    assert not issues
    elec = _elec()
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    run = wiring.runs[0]
    assert (
        cable_layer(replace(run, route="floor"), {run.group: LineClass("device", True)})
        == "W-CABLE-DEVICE-RCD-FLOOR"
    )
    assert cable_layer(run, {run.group: LineClass("light", False)}) == "W-CABLE-LIGHT"
    assert cable_layer(replace(run, circuit="low"), {}) == "W-CABLE-LOW"
    assert cable_layer(run, {}) == "W-CABLE-SOCKET"  # a group the panel does not know
    doc = new_document()
    msp = doc.modelspace()
    draw_wiring(msp, wiring, elec, {run.group: LineClass("light", False)})
    drawn = {e.dxf.layer for e in msp.query("LWPOLYLINE") if e.dxf.layer.startswith("W-CABLE")}
    assert "W-CABLE-LIGHT" in drawn


def _length_label(mm: float, n: int) -> str:
    return "L" + f"{mm / 1000:.1f}".replace(".", ",") + (f" ×{n}" if n > 1 else "")


def test_lanes_separate_overlapping_cables() -> None:
    paths = [
        [Vec(0, 0), Vec(3000, 0)],
        [Vec(1000, 0), Vec(4000, 0)],  # overlaps the first on 1000..3000
        [Vec(3000, 0), Vec(5000, 0)],  # touches the first at an end: may share its lane
    ]
    segs = segments(paths)
    off = lanes(segs, 30.0, 90.0)
    assert off[(0, 0)] != off[(1, 0)]
    assert off[(2, 0)] == off[(0, 0)]
    assert sorted({off[(0, 0)], off[(1, 0)]}) == [-15.0, 15.0]  # lanes symmetric about the line
    shared = [(b.lo, b.hi, b.runs) for b in bundles(segs, off)]
    assert (1000, 3000, (0, 1)) in shared and (0, 1000, (0,)) in shared


def test_offset_path_moves_corner_to_both_lanes() -> None:
    path = [Vec(0, 0), Vec(1000, 0), Vec(1000, 1000)]
    out = offset_path(path, [30.0, -20.0])  # horizontal up by 30, vertical left by 20
    assert out == [Vec(0, 30), Vec(980, 30), Vec(980, 1000)]


def test_lanes_only_where_cables_overlap_and_band_is_limited() -> None:
    far = [[Vec(0, 0), Vec(1000, 0)], [Vec(500, 0), Vec(1500, 0)], [Vec(5000, 0), Vec(6000, 0)]]
    off = lanes(segments(far), 30.0, 90.0)
    assert off[(2, 0)] == 0.0  # a single piece on the same line: no shift
    many = [[Vec(0, 0), Vec(1000 + k, 0)] for k in range(11)]
    shifts = sorted(lanes(segments(many), 30.0, 90.0).values())
    assert shifts[-1] - shifts[0] == pytest.approx(90.0)  # 11 cables in a band of 90, not 300


def _point(pid: str, offset: float, height: float, group: str = "QF5") -> dict[str, Any]:
    return _wall(pid, "socket", "w3", offset, height, group)


def test_cable_channel_is_a_wide_chase_between_two_heights() -> None:
    plan = make_plan(RECT, [DOOR])
    elec = Electrical.model_validate(
        {
            "points": [_point("a", 500, 300)],
            "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700},
            "cable_channels": [
                {"id": "tv", "room": "r", "wall": "w1", "offset": 1000, "entry": 1100, "exit": 400}
            ],
        }
    )
    w = _wiring(plan, elec)
    channel = next(c for c in w.chases if c.kind == "channel")
    assert channel.targets == ("tv",) and channel.wide and channel.circuit == "low"
    assert channel.length_mm == pytest.approx(700)
    assert channel.span == (400, 1100)  # low to high, whichever end is the entry
    # Only the chase: the channel has no cable and no line from the panel
    assert not any(r.target == "tv" for r in w.runs)
    without = _wiring(plan, elec.model_copy(update={"cable_channels": []}))
    assert w.chase_length(wide=True) == pytest.approx(without.chase_length(wide=True) + 700)


def test_wall_chases_share_nearby_drops_up_to_four() -> None:
    plan = make_plan(RECT, [DOOR])
    pts = [
        _point("a", 500, 300),
        _point("b", 600, 900),  # 100 mm from a: same chase
        _point("c", 1200, 300),  # beyond 150: its own chase
        *(_point(f"d{k}", 2000 + 20 * k, 300) for k in range(5)),  # five in a row: 4 + 1
    ]
    elec = Electrical.model_validate(
        {"points": pts, "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700}}
    )
    w = _wiring(plan, elec)
    points = [c for c in w.chases if c.kind == "point"]
    shared = next(c for c in points if "a" in c.targets)
    assert shared.targets == ("a", "b") and shared.cables == 2
    assert shared.length_mm == pytest.approx(2700 - 300)  # down to the lowest point
    assert next(c for c in points if "c" in c.targets).cables == 1
    near = sorted(c.cables for c in points if any(t.startswith("d") for t in c.targets))
    assert near == [1, 4]
    # Above a wall box: one chase per 4 cables, length from the ceiling to the box;
    # a ceiling box has no chase
    box = [c for c in w.chases if c.kind == "box"]
    on_wall = {b.id for b in w.boxes if not b.on_ceiling}
    n_box = sum(1 for r in w.runs if r.source in on_wall or r.target in on_wall)
    assert sum(c.cables for c in box) == n_box
    assert all(c.length_mm == BOX_BELOW_CEILING for c in box)
    assert w.chase_mm == pytest.approx(sum(c.length_mm for c in w.chases))


def test_outlet_is_power_point_with_own_estimate_line() -> None:
    elec = Electrical.model_validate(
        {
            "points": [
                {**_wall("ac", "outlet", "w3", 500, 2500, "QF7"), "note": "кондиціонер"},
                _wall("led", "led_output", "w3", 1500, 2200, "QF1"),
            ],
            "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700},
        }
    )
    w = _wiring(make_plan(RECT, [DOOR]), elec)
    ac = next(r for r in w.runs if r.target == "ac")
    assert ac.source == "board" and ac.mark == "3x2.5"  # power, not lighting
    names = {ln.name: ln.qty for ln in build_estimate(w, elec, PriceList(), "ru").lines}
    assert names["Вывод кабеля к технике"] == 1 and names["Вывод под подсветку"] == 1


def test_board_tail_reaches_floor() -> None:
    w = _wiring(make_plan(RECT, [DOOR]), _elec())
    s1 = next(r for r in w.runs if r.target == "s1")  # from the panel
    assert s1.ends_mm == pytest.approx(END_ALLOWANCE + 1700)  # inside the panel down to the floor
    l1 = next(r for r in w.runs if r.target == "l1")  # from the box
    assert l1.ends_mm == 2 * END_ALLOWANCE


def test_floor_route_rises_from_floor() -> None:
    cable = {"id": "c3", "from": "board", "to": ["s2", "s3"], "group": "QF3", "cable": "3x2.5"}
    w = _wiring(make_plan(RECT, [DOOR]), _elec([{**cable, "route": "floor"}]))
    box = next(b for b in w.boxes if b.group == "QF3")
    assert box.route == "floor" and box.rise_mm == BOX_ABOVE_FLOOR
    feed = next(r for r in w.runs if r.target == box.id)
    assert feed.route == "floor"
    assert feed.vertical_mm == pytest.approx(1700 + BOX_ABOVE_FLOOR)  # down from panel, to box
    s2 = next(r for r in w.runs if r.target == "s2")
    assert s2.vertical_mm == pytest.approx(BOX_ABOVE_FLOOR + 300)  # from the floor to the socket
    floor = [c for c in w.chases if c.route == "floor"]
    assert floor and all(c.length_mm < 2000 for c in floor)
    # Rises from the floor and drops from the ceiling never share a chase
    assert all(c.route == "ceiling" for c in w.chases if c.targets and "l1" in c.targets)


def test_heavy_lines_and_outlets_go_without_boxes() -> None:
    assert section("3x6") == 6 and section("5х2,5") == 2.5 and section("UTP") == 0
    pts = [
        _wall("h1", "socket", "w3", 500, 900, "QF9"),
        _wall("h2", "socket", "w3", 2500, 900, "QF9"),
        _wall("ac", "outlet", "w4", 500, 2500, "QF7"),
        _wall("tw", "outlet", "w4", 2500, 900, "QF7"),
        _wall("r1", "socket", "w1", 1500, 300, "QF4"),
        _wall("r2", "socket", "w1", 2500, 300, "QF4"),
    ]
    cables = [
        {"id": "c9", "from": "board", "to": ["h1", "h2"], "group": "QF9", "cable": "3x6"},
        {"id": "c4", "from": "board", "to": ["r1", "r2"], "group": "QF4", "cable": "3x2.5"},
    ]
    elec = Electrical.model_validate(
        {
            "points": pts,
            "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700},
            "cables": cables,
        }
    )
    w = _wiring(make_plan(RECT, [DOOR]), elec)
    assert [b.group for b in w.boxes] == ["QF4"]  # 3x6 and appliance outputs: no boxes
    src = {r.target: r.source for r in w.runs}
    assert all(src[p] == "board" for p in ("h1", "h2", "ac", "tw"))
    # direct: false in the model: through a box again
    forced = [{**cables[0], "direct": False}, cables[1]]
    w2 = _wiring(make_plan(RECT, [DOOR]), elec.model_copy(update={"cables": []}))
    assert "QF9" in {b.group for b in w2.boxes}  # without a cable the type is 3x2.5: through a box
    assert "QF7" not in {b.group for b in w2.boxes}  # appliance outputs: still no boxes
    w3 = _wiring(
        make_plan(RECT, [DOOR]),
        Electrical.model_validate({**elec.model_dump(by_alias=True), "cables": forced}),
    )
    assert "QF9" in {b.group for b in w3.boxes}


def test_low_voltage_in_own_chases() -> None:
    pts = [
        _wall("s1", "socket", "w3", 500, 300, "QF5"),
        _wall("s2", "socket", "w3", 1500, 300, "QF5"),
        _wall("lan", "data", "w3", 560, 300, "LAN"),  # 60 mm from the socket
    ]
    elec = Electrical.model_validate(
        {"points": pts, "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700}}
    )
    w = _wiring(make_plan(RECT, [DOOR]), elec)
    lan = next(r for r in w.runs if r.target == "lan")
    assert lan.circuit == "low" and lan.source == "board" and lan.mark == "UTP cat.6"
    chases = [c for c in w.chases if c.kind == "point"]
    assert all(not ({"s1", "lan"} <= set(c.targets)) for c in chases)  # close, but separate
    board = [c for c in w.chases if c.kind == "board"]
    assert {c.circuit for c in board} == {"power", "low"}


def test_chase_width_by_cables() -> None:
    plan = make_plan(RECT, [DOOR])
    pts = [_point(f"d{k}", 2000 + 20 * k, 300) for k in range(4)]
    elec = Electrical.model_validate(
        {"points": pts, "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700}}
    )
    w = _wiring(plan, elec)
    shared = next(c for c in w.chases if c.kind == "point")
    assert shared.cables == 4 and shared.wide and CHASE_NARROW == 2
    assert w.chase_length(wide=True) + w.chase_length(wide=False) == pytest.approx(w.chase_mm)


def test_wall_holes_over_doors_for_ceiling_runs() -> None:
    plan = _two_rooms_with_door()
    pts = [
        {
            "id": f"s{k}",
            "room": "b",
            "type": "socket",
            "wall": "w3",
            "offset": 300 + 500 * k,
            "height": 300,
            "group": f"QF{k + 1}",
        }
        for k in range(5)
    ]
    board = {"room": "a", "wall": "w1", "offset": 500, "height": 1700}
    w = _wiring(plan, Electrical.model_validate({"points": pts, "board": board}))
    # A door in a and an opening in b at the same spot: one pass, the door id
    assert {h.passage for h in w.holes} == {"a_door_1"}
    assert sorted(h.cables for h in w.holes) == [1, HOLE_CABLES]  # 5 cables: 4 + 1
    cables = [
        {"id": f"c{k}", "from": "board", "to": [f"s{k}"], "group": f"QF{k + 1}", "cable": "3x2.5"}
        for k in range(5)
    ]
    floor = [{**c, "route": "floor"} for c in cables]
    w2 = _wiring(plan, Electrical.model_validate({"points": pts, "board": board, "cables": floor}))
    assert w2.holes == ()  # on the floor: under the opening, no drilling


def test_boxes_in_wet_rooms_marked() -> None:
    data = make_plan(RECT, [DOOR]).model_dump()
    data["rooms"][0]["wet"] = True
    w = _wiring(Plan.model_validate(data), _elec())
    assert w.boxes and all(b.wet for b in w.boxes)


def test_lanes_keep_clear_of_walls() -> None:
    from shapely.geometry import box

    from floorplan_engine.drawing.wiring import clearance

    many = [[Vec(0, 50), Vec(1000 + k, 50)] for k in range(5)]  # 5 cables 50 mm from the wall y=0
    room = clearance(box(-100, 0, 2000, 3000), 10.0)
    shifts = sorted(lanes(segments(many), 30.0, 300.0, room).values())
    assert shifts[-1] - shifts[0] == pytest.approx(120.0)  # step not compressed
    assert 50 + shifts[0] == pytest.approx(10.0)  # the bundle moves away from the wall, not onto it
    tight = clearance(box(-100, 0, 2000, 100), 10.0)  # 100 mm corridor: 80 of room
    shifts = sorted(lanes(segments(many), 30.0, 300.0, tight).values())
    assert 50 + shifts[0] == pytest.approx(10.0) and 50 + shifts[-1] == pytest.approx(90.0)


def test_ceiling_box_in_center_of_its_points() -> None:
    """A ceiling box sits at the centre of its points, not at the wall on the panel side."""
    plan = make_plan(RECT, [DOOR])
    pts = [
        _wall("s1", "socket", "w1", 1500, 300, "QF1"),
        _wall("s2", "socket", "w3", 1500, 300, "QF1"),
    ]
    elec = Electrical.model_validate(
        {"points": pts, "board": {"room": "r", "wall": "w4", "offset": 500, "height": 1700}}
    )
    (box,) = _wiring(plan, elec).boxes
    assert box.on_ceiling
    assert abs(box.anchor.node.x - 2000) <= 100 and abs(box.anchor.node.y - 1500) <= 100


def test_ceiling_route_box_is_on_ceiling_away_from_walls() -> None:
    from floorplan_engine.electrical.routing import CLEARANCE

    plan = make_plan(RECT, [DOOR])
    pts = [
        _wall("l1", "light", "w1", 1500, 2400, "QF1"),
        _wall("s1", "socket", "w2", 2000, 300, "QF1"),
        _wall("s2", "socket", "w3", 1500, 300, "QF1"),
    ]
    elec = Electrical.model_validate(
        {"points": pts, "board": {"room": "r", "wall": "w4", "offset": 500, "height": 1700}}
    )
    w = _wiring(plan, elec)
    (box,) = w.boxes
    assert box.on_ceiling and box.rise_mm == 0.0
    assert not [c for c in w.chases if c.kind == "box"]
    room = Polygon([(0, 0), (0, 3000), (4000, 3000), (4000, 0)])
    p = box.anchor.node
    assert room.exterior.distance(Point(p.x, p.y)) >= CLEARANCE - 1e-6


def test_box_size_by_lines() -> None:
    from floorplan_engine.electrical.boxes import box_size

    assert [box_size(n) for n in (2, 3, 4, 6, 7, 8, 9)] == [
        "80", "80", "100x100", "100x100", "150x110", "150x110", "190x140",
    ]  # fmt: skip


def test_split_points_by_zones() -> None:
    from floorplan_engine.electrical.boxes import split_points

    left = [Vec(100 + 10 * k, 500) for k in range(6)]
    right = [Vec(5000 + 10 * k, 500) for k in range(6)]
    zones = split_points(left + right, 7)
    assert sorted(len(z) for z in zones) == [6, 6]
    assert all(max(z) < 6 or min(z) >= 6 for z in zones)  # neighbours go together
    assert split_points(left, 7) == [list(range(6))]


def test_box_lines_never_exceed_largest_regular_box() -> None:
    from floorplan_engine.electrical.boxes import BOX_BRANCHES

    plan = make_plan([{"length": 4000}, {"length": 6000}, {"length": 4000}, {"length": 6000}], [])
    pts = [_wall(f"d{k}", "sconce", "w1", 300 + 250 * k, 2000, "QF1") for k in range(14)]
    elec = Electrical.model_validate(
        {"points": pts, "board": {"room": "r", "wall": "w4", "offset": 500, "height": 1700}}
    )
    w = _wiring(plan, elec)
    branches = [sum(1 for r in w.runs if r.source == b.id) for b in w.boxes]
    assert len(w.boxes) >= 2 and max(branches) <= BOX_BRANCHES
    assert sum(branches) == 14
    assert all(any(r.target == b.id and r.source == "board" for r in w.runs) for b in w.boxes)


def test_switch_outside_room_goes_into_its_light_box() -> None:
    plan = _two_rooms_with_door()
    elec = Electrical.model_validate(
        {
            "points": [
                {"id": "l1", "room": "b", "type": "light", "ceiling": [1500, 1500], "group": "QF1"},
                {"id": "l2", "room": "b", "type": "light", "ceiling": [800, 800], "group": "QF1"},
                # switch for room b's light is in room a, by the door
                {
                    "id": "k1",
                    "room": "a",
                    "type": "switch",
                    "wall": "w3",
                    "offset": 700,
                    "height": 900,
                    "group": "QF1",
                },
            ],
            "board": {"room": "a", "wall": "w1", "offset": 500, "height": 1700},
        }
    )
    w = _wiring(plan, elec)
    (box,) = w.boxes  # the switch has no box of its own
    assert box.room == "b"
    to_switch = next(r for r in w.runs if r.target == "k1")
    assert to_switch.source == box.id  # from the light box, not from the panel
    assert not any(r.source == "board" and r.target == "k1" for r in w.runs)
    assert box.size == "100x100"  # 4 lines: feed, two lights, switch


# --- Manual edits (wiring.yaml) ---------------------------------------------


def _edited(edits: dict[str, Any], elec: Electrical | None = None) -> Any:
    from floorplan_engine.model.schema import WiringEdits

    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    wiring = box_wiring(plan, contours, elec or _elec(), WiringEdits.model_validate(edits))
    assert wiring is not None
    return wiring


def test_manual_wire_path_replaces_route() -> None:
    auto = _wiring(make_plan(RECT, [DOOR]), _elec())
    run = next(r for r in auto.runs if r.target == "s1")
    a, b = run.path[0], run.path[-1]
    # Detour through the room middle: right from the panel, up to 1500, to the socket
    path = [[a.x, a.y], [1500, a.y], [1500, b.y], [b.x, b.y]]
    w = _edited({"wires": {run.id: {"from": "board", "to": "s1", "path": path}}})
    manual = next(r for r in w.runs if r.id == run.id)
    assert [v.as_tuple() for v in manual.path] == [tuple(p) for p in path]
    assert manual.plan_mm == pytest.approx(abs(1500 - a.x) + abs(b.y - a.y) + abs(b.x - 1500))
    assert w.edited == {f"wire:{run.id}"} and not w.edit_notes


def test_stale_wire_edit_is_ignored() -> None:
    w = _edited({"wires": {"wire_1": {"from": "box_9", "to": "s1", "path": [[0, 0], [0, 10]]}}})
    assert not w.edited
    [(path, msg)] = w.edit_notes
    assert path == "wires.wire_1" and "не найдена" in msg


def test_wall_box_slides_along_its_wall() -> None:
    # A wall box only for a floor route
    elec = _elec().model_copy(update={"route": "floor"})
    auto = _wiring(make_plan(RECT, [DOOR]), elec)
    box = next(b for b in auto.boxes if not b.on_ceiling)
    a = box.anchor
    assert a.wall_dir is not None and a.inward is not None
    # Far along the wall and away from it: the box goes to the wall end, on the wall
    far = a.pos + a.wall_dir * 100000 + a.inward * 700
    edit = {"room": box.room, "group": box.group, "at": list(far.as_tuple())}
    w = _edited({"boxes": {box.id: edit}}, elec)
    moved = next(b for b in w.boxes if b.id == box.id)
    assert moved.anchor.inward == a.inward
    assert abs((moved.anchor.pos - a.pos).cross(a.wall_dir)) < 1e-6  # on the same wall
    assert moved.anchor.pos != a.pos
    # Box lines start from the new spot
    for r in w.runs:
        if r.source == box.id:
            assert r.path[0] == moved.anchor.node
        if r.target == box.id:
            assert r.path[-1] == moved.anchor.node


def test_ceiling_box_moves_only_inside_room() -> None:
    from floorplan_engine.electrical.anchors import Anchor
    from floorplan_engine.electrical.boxes import moved_anchor
    from floorplan_engine.model.geometry import room_geometries

    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    [g] = room_geometries(plan, contours)
    box = Anchor(Vec(1000, 1000), None, None, 75.0)
    assert moved_anchor(g, box, Vec(2000, 1500)) == Anchor(Vec(2000, 1500), None, None, 75.0)
    assert moved_anchor(g, box, Vec(-5000, -5000)) is None
    # Closer than 150 mm to a wall: moved to 150 mm from it
    assert moved_anchor(g, box, Vec(50, 1500)) == Anchor(Vec(150, 1500), None, None, 75.0)


def test_stale_box_edit_is_ignored() -> None:
    auto = _wiring(make_plan(RECT, [DOOR]), _elec())
    box = auto.boxes[0]
    w = _edited({"boxes": {box.id: {"room": box.room, "group": "QF99", "at": [100, 100]}}})
    assert next(b for b in w.boxes if b.id == box.id).anchor == box.anchor
    assert w.edit_notes[0][0] == f"boxes.{box.id}"


def test_diagonal_wire_edit_only_in_economy() -> None:
    """A slanted edit piece is not applied in standard (a warning) and is applied in economy
    (docs/wiring-variants.md)."""
    from floorplan_engine.model.schema import WiringEdits

    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    auto = _wiring(plan, _elec())
    run = next(r for r in auto.runs if r.target == "s1")
    a, b = run.path[0], run.path[-1]
    path = [[a.x, a.y], [1500, 1500], [b.x, b.y]]  # straight through the room middle
    edits = WiringEdits.model_validate(
        {"wires": {run.id: {"from": run.source, "to": "s1", "path": path}}}
    )
    standard = box_wiring(plan, contours, _elec(), edits)
    assert standard is not None and not standard.edited
    [(where, msg)] = standard.edit_notes
    assert where == f"wires.{run.id}" and "кратчайшем пути" in msg
    economy_elec = _elec().model_copy(update={"mode": "economy"})
    economy = box_wiring(plan, contours, economy_elec, edits)
    assert economy is not None and economy.edited == {f"wire:{run.id}"}


def test_economy_routes_shorter_at_any_angle() -> None:
    """Economy: on the ceiling along the shortest path at any angle, at least 150 mm from walls;
    standard at right angles. The economy variant uses no more cable."""
    from shapely.geometry import LineString

    from floorplan_engine.electrical.routing import CLEARANCE, free_area, is_ortho
    from floorplan_engine.model.geometry import room_geometries

    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    standard = _wiring(plan, _elec())
    economy = _wiring(plan, _elec().model_copy(update={"mode": "economy"}))
    assert all(is_ortho(r.path) for r in standard.runs)
    assert any(not is_ortho(r.path) for r in economy.runs)  # has slanted pieces
    assert sum(r.plan_mm for r in economy.runs) < sum(r.plan_mm for r in standard.runs)
    # Cut pieces do not enter the band by the walls (except the approach to a point right at the
    # wall)
    inner = free_area(room_geometries(plan, contours)).buffer(-CLEARANCE + 2)
    for r in economy.runs:
        for p, q in itertools.pairwise(r.path[1:-1]):
            if abs(p.x - q.x) > 1 and abs(p.y - q.y) > 1:
                assert inner.covers(LineString([p.as_tuple(), q.as_tuple()]))


def test_wiring_handles_lane_follows_path() -> None:
    from floorplan_engine.epd.objects import wiring_handles

    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    w = _wiring(plan, _elec())
    wires = wiring_handles(plan, contours, w)["wires"]
    for r in w.runs:
        h = wires[r.id]
        assert len(h["lane"]) == len(h["path"])  # a lane is the same vertices with a shift
        for (ax, ay), (bx, by) in itertools.pairwise(h["lane"]):
            assert abs(ax - bx) < 0.2 or abs(ay - by) < 0.2  # right angles


@pytest.mark.parametrize(
    ("mark", "value"),
    [
        ("3x1.5", 1.5),
        ("3x2,5", 2.5),
        ("3х6", 6.0),  # Cyrillic "х"
        ("5×10", 10.0),
        ("3 x 4", 4.0),
        ("ВВГнг-LS 3x2.5", 2.5),
        ("UTP", 0.0),
        ("", 0.0),
        ("3x", 0.0),
    ],
)
def test_section_from_mark(mark: str, value: float) -> None:
    assert section(mark) == value


def _chase(cables: int, length: float = 1000.0) -> Chase:
    return Chase("point", "r", "w1", 500.0, length, cables)


@pytest.mark.parametrize(
    ("cables", "wide"), [(1, False), (CHASE_NARROW, False), (CHASE_NARROW + 1, True)]
)
def test_chase_wide_above_narrow_limit(cables: int, wide: bool) -> None:
    assert _chase(cables).wide is wide


def _run(mark: str, plan: float, start: float, end: float, ends: float) -> Run:
    return Run(
        id="r1",
        group="1",
        mark=mark,
        mark_assumed=False,
        source="board",
        target="p1",
        path=(Vec(0, 0), Vec(1000, 0)),
        plan_mm=plan,
        rise_start_mm=start,
        rise_end_mm=end,
        ends_mm=ends,
    )


def test_run_vertical_and_total_length() -> None:
    r = _run("3x2.5", plan=4000, start=150, end=2400, ends=300)
    assert r.vertical_mm == 2550
    assert r.length_mm == 6850


def test_run_ceiling_point_has_no_drop() -> None:
    r = _run("3x1.5", plan=1000, start=150, end=0, ends=0)
    assert r.vertical_mm == 150 and r.length_mm == 1150


def _bare_wiring(runs: tuple[Run, ...] = (), chases: tuple[Chase, ...] = ()) -> Wiring:
    return Wiring(2700.0, False, (), runs, chases=chases)


def test_chase_lengths_split_by_width() -> None:
    w = _bare_wiring(chases=(_chase(1, 1000), _chase(2, 500), _chase(3, 700), _chase(4, 300)))
    assert w.chase_length(wide=False) == 1500
    assert w.chase_length(wide=True) == 1000
    assert w.chase_mm == 2500


def test_by_mark_sums_meters_sorted_by_mark() -> None:
    w = _bare_wiring(
        runs=(
            _run("3x2.5", 1000, 0, 0, 0),
            _run("3x1.5", 2000, 500, 0, 0),
            _run("3x2.5", 1500, 0, 0, 0),
        )
    )
    assert list(w.by_mark()) == ["3x1.5", "3x2.5"]
    assert w.by_mark() == pytest.approx({"3x1.5": 2.5, "3x2.5": 2.5})


def test_empty_wiring_totals_are_zero() -> None:
    w = _bare_wiring()
    assert w.chase_mm == 0 and w.chase_length(wide=True) == 0 and w.by_mark() == {}


def test_floor_route_never_rises_through_the_room() -> None:
    """Floor route: cable to a ceiling point runs on the ceiling. A lighting group goes entirely on
    the ceiling, and in a mixed group the branch rises up the wall from the box and runs along the
    ceiling. No rise from the floor in the middle of a room (decision 2026-11-01)."""
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    light = {"id": "l1", "room": "r", "type": "downlight", "ceiling": [1500, 2000]}
    points = [
        {**light, "group": "QF1"},
        _wall("k1", "switch", "w3", 2500, 900, "QF1"),
        {**light, "id": "l2", "ceiling": [1000, 1000], "group": "QF2"},  # mixed group
        _wall("s1", "socket", "w3", 500, 300, "QF2"),
        _wall("s2", "socket", "w3", 1500, 300, "QF2"),
    ]
    elec = Electrical.model_validate(
        {
            "points": points,
            "route": "floor",
            "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700},
        }
    )
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    ceiling_points = {"l1", "l2"}
    for r in wiring.runs:
        if r.target in ceiling_points:
            assert r.route == "ceiling" and r.rise_end_mm == 0
    assert {r.route for r in wiring.runs if r.group == "QF1"} == {"ceiling"}  # lighting
    qf2 = [r for r in wiring.runs if r.group == "QF2"]
    assert {r.route for r in qf2 if r.target in {"s1", "s2"}} == {"floor"}  # sockets on the floor
    up = next(r for r in qf2 if r.target == "l2")
    box = next(b for b in wiring.boxes if b.id == up.source)
    assert box.route == "floor"  # box at the floor, the branch to the light goes up the wall
    assert up.rise_start_mm == pytest.approx(plan.ceiling_height - box.rise_mm)


def _sockets(**extra: Any) -> Electrical:
    """Four sockets of one group on one wall: at the panel end and at the far end."""
    points = [
        _wall(f"s{k}", "socket", "w3", offset, 300, "QF2")
        for k, offset in enumerate((500, 1500, 2500, 3500), start=1)
    ]
    data = {
        "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1500, "name": "ЩР"},
        "points": points,
        **extra,
    }
    return Electrical.model_validate(data)


def test_before_plaster_drops_chases_of_bare_cable() -> None:
    plan = make_plan(walls=RECT)
    after = _wiring(plan, _sockets(route="ceiling"))
    assert after.chases and not after.before_plaster
    before = _wiring(plan, _sockets(route="ceiling", plaster="before"))
    assert before.before_plaster and not before.chases
    assert before.runs == after.runs  # the same routes and cable


def test_before_plaster_keeps_chases_with_conduit() -> None:
    """Conduit in the walls is thicker than the plaster: its chases stay. Conduit only on the
    ceiling ends there, the drops go under the plaster."""
    plan = make_plan(walls=RECT)
    walls = _wiring(plan, _sockets(route="ceiling", plaster="before", conduit="walls"))
    assert walls.chases == _wiring(plan, _sockets(route="ceiling", conduit="walls")).chases
    ceiling = _wiring(plan, _sockets(route="ceiling", plaster="before", conduit="ceiling"))
    assert not ceiling.chases
    floor = _wiring(plan, _sockets(route="floor", plaster="before"))  # the floor is always in it
    assert floor.chases == _wiring(plan, _sockets(route="floor")).chases


def test_before_plaster_keeps_a_cable_channel() -> None:
    channel = {"id": "tv", "room": "r", "wall": "w2", "offset": 1500, "entry": 400, "exit": 1100}
    wiring = _wiring(
        make_plan(walls=RECT),
        _sockets(route="ceiling", plaster="before", cable_channels=[channel]),
    )
    assert [c.kind for c in wiring.chases] == ["channel"]


def test_loop_chains_sockets_without_a_box() -> None:
    plan, elec = make_plan(walls=RECT), _sockets(distribution="loop", route="floor")
    wiring = _wiring(plan, elec)
    assert not wiring.boxes
    assert [r.source for r in wiring.runs if r.source == "board"] == ["board"]  # one panel line
    assert len(wiring.runs) == 4
    assert {r.target for r in wiring.runs} == {"s1", "s2", "s3", "s4"}
    head = next(r for r in wiring.runs if r.source == "board").target
    assert sum(r.source == head for r in wiring.runs) == 1  # a chain, not a star
    assert all(r.rise_start_mm == 300 for r in wiring.runs if r.source != "board")
    assert line_starts(wiring.runs) == dict.fromkeys(("s1", "s2", "s3", "s4"), head)


def test_loop_point_has_a_chase_for_both_cables() -> None:
    plan, elec = make_plan(walls=RECT), _sockets(distribution="loop", route="floor")
    wiring = _wiring(plan, elec)
    middle = [c for c in wiring.chases if c.kind == "point" and c.cables == 2]
    assert len(middle) == 3  # in and out: all but the tail of the chain
    assert all(len(c.targets) == 1 for c in middle)


def test_loop_leaves_light_in_its_box() -> None:
    light = {"id": "l1", "room": "r", "type": "light", "ceiling": [1500, 2000], "group": "QF2"}
    switch = _wall("sw1", "switch", "w2", 2500, 900, "QF2")
    base = _sockets().model_dump(mode="json", by_alias=True, exclude_none=True)
    data = {**base, "points": [*base["points"], light, switch], "distribution": "loop"}
    wiring = _wiring(make_plan(walls=RECT), Electrical.model_validate(data))
    assert len(wiring.boxes) == 1
    box = wiring.boxes[0].id
    assert {r.target for r in wiring.runs if r.source == box} == {"l1", "sw1"}
    assert sum(r.source == "board" for r in wiring.runs) == 2  # the box and the chain


def test_loop_long_chain_is_split_into_panel_lines() -> None:
    points = [_wall(f"s{k}", "socket", "w3", 100 + k * 300, 300, "QF2") for k in range(10)]
    data = _sockets().model_dump(mode="json", by_alias=True, exclude_none=True)
    elec = Electrical.model_validate({**data, "points": points, "distribution": "loop"})
    wiring = _wiring(make_plan(walls=RECT), elec)
    assert sum(r.source == "board" for r in wiring.runs) >= 2


def test_any_angle_and_conduit_follow_their_own_option() -> None:
    plan = make_plan(walls=RECT)
    assert _sockets(mode="economy").shortest_path
    assert not _sockets(mode="economy", path="right").shortest_path
    assert _sockets(path="shortest").shortest_path
    assert _sockets(mode="proper").conduit_level == "ceiling"
    assert _sockets(mode="proper", conduit="none").conduit_level == "none"
    assert _sockets(conduit="walls").conduit_level == "walls"
    assert _sockets(conduit=True).conduit_level == "ceiling"  # electrical.yaml before 2026-11-08
    assert _sockets(conduit=False).conduit_level == "none"
    right = _wiring(plan, _sockets())
    short = _wiring(plan, _sockets(path="shortest"))
    assert sum(r.plan_mm for r in short.runs) <= sum(r.plan_mm for r in right.runs)
