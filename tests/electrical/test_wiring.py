"""Wiring through boxes: topology, lengths, assumptions."""

from __future__ import annotations

import itertools
import math
from dataclasses import replace
from typing import Any

import pytest
from ezdxf import bbox
from shapely.geometry import Point
from shapely.geometry import box as shapely_box

from floorplan_engine.drawing.ids import object_id
from floorplan_engine.drawing.layers import BOX_TEXT_MM, W_BOX, W_TEXT, new_document
from floorplan_engine.drawing.wiring import (
    cable_layer,
    draw_wiring,
    fillet,
    wiring_notes,
)
from floorplan_engine.electrical.boxes import BOX_SIZE_MM, box_square
from floorplan_engine.electrical.bundles import bundles, lanes, offset_path, segments
from floorplan_engine.electrical.chases import wall_chases, with_conduit
from floorplan_engine.electrical.estimate import build_estimate
from floorplan_engine.electrical.frames import POST_PITCH_MM
from floorplan_engine.electrical.panel import LineClass
from floorplan_engine.electrical.price_list import PriceList
from floorplan_engine.electrical.wiring import box_wiring
from floorplan_engine.electrical.wiring_context import END_ALLOWANCE
from floorplan_engine.electrical.wiring_model import (
    BOX_ABOVE_FLOOR,
    BOX_BELOW_CEILING,
    CHASE_NARROW,
    HOLE_CABLES,
    Chase,
    Run,
    Wiring,
)
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.scale import sheet
from floorplan_engine.model.schema import Electrical, ElectricalPoint, Plan
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan, room_wiring
from tests.conftest import wall_point as w3_point
from tests.electrical.conftest import (
    DOOR,
    RECT,
    base_elec,
    crossings_of,
    four_sockets,
    two_rooms_with_door,
    wall_point,
    wiring_of,
)


def test_run_length_parts() -> None:
    w = wiring_of(make_plan(RECT, [DOOR]), base_elec())
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
    w = wiring_of(make_plan(RECT, [DOOR]), base_elec())
    assert w.ceiling_height == 2700 and w.height_assumed
    data = make_plan(RECT, [DOOR]).model_dump(exclude={"ceiling_height"})
    plan = Plan.model_validate({**data, "ceiling_height": 3000})
    w2 = wiring_of(plan, base_elec())
    assert not w2.height_assumed
    s2 = next(r for r in w2.runs if r.target == "s2")
    assert s2.vertical_mm == pytest.approx(3000 - 300)


def test_no_board_no_wiring() -> None:
    plan = make_plan(RECT)
    _, contours = validate_plan(plan)
    elec = Electrical.model_validate(
        {"points": [wall_point("s1", "socket", "w1", 500, 300, "QF1")]}
    )
    assert box_wiring(plan, contours, elec) is None


def test_cable_to_other_room_goes_through_door() -> None:
    plan = two_rooms_with_door()
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
            # Panel facing the door: the way through it is not a detour
            "board": {"room": "a", "wall": "w1", "offset": 1500, "height": 1700},
        }
    )
    w = wiring_of(plan, elec)
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


def _socket_facing_panel(plan: Plan, route: str | None = None) -> Any:
    """Panel in a and a socket in b, both at y 300: through the door (y 1200…2000) is a detour."""
    socket = {"id": "s1", "room": "b", "type": "socket", "wall": "w3", "offset": 2700}
    data: dict[str, Any] = {
        "points": [{**socket, "height": 300, "group": "QF1"}],
        "board": {"room": "a", "wall": "w1", "offset": 300, "height": 1700},
    }
    if route is not None:
        data["cables"] = [{"id": "c1", "from": "board", "to": ["s1"], "group": "QF1"}]
        data["cables"][0] |= {"cable": "3x2.5", "route": route}
    return wiring_of(plan, Electrical.model_validate(data))


@pytest.mark.parametrize("route", ["ceiling", "floor"])
def test_cable_through_partition_when_door_is_a_detour(route: str) -> None:
    """Decision 2026-11-11: a non-bearing wall is drilled when the door is out of the way."""
    w = _socket_facing_panel(two_rooms_with_door(), route)
    (run,) = w.runs
    assert run.route == route
    assert [y for y in crossings_of(run) if not 1200 <= y <= 2000]  # straight through the wall
    (hole,) = w.holes  # on the floor too: no opening there, the wall is drilled
    assert hole.passage.startswith(f"wall:0:{route}:") and hole.runs == (run.id,)


@pytest.mark.parametrize("partition", [{"bearing": True}, {"thickness": 400}])
def test_bearing_or_thick_wall_is_not_drilled(partition: dict[str, Any]) -> None:
    """A load-bearing wall and a thick one (shaft, pylon) only through the door."""
    w = _socket_facing_panel(two_rooms_with_door(**partition))
    (run,) = w.runs
    assert all(1200 <= y <= 2000 for y in crossings_of(run))
    assert w.holes and not [h for h in w.holes if h.passage.startswith("wall:")]


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
    elec = base_elec()
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


def test_wiring_sheet_box_is_its_square_and_name_only() -> None:
    """Decision 2026-11-17: no description block beside a box and no note about it under the
    table: the sheet shows the square and "К1" (inside it, on white, 2026-11-18); where the
    cables go is in the box card."""
    plan = make_plan(RECT, [DOOR])
    issues, contours = validate_plan(plan)
    assert not issues
    elec = base_elec()
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None and wiring.boxes
    msp = new_document().modelspace()
    draw_wiring(msp, wiring, elec, {})
    for b in wiring.boxes:
        own = [e for e in msp if object_id(e) == ("box", b.id)]
        assert sorted(e.dxftype() for e in own) == ["HATCH", "LWPOLYLINE", "TEXT"]
        assert [e.dxf.text for e in own if e.dxftype() == "TEXT"] == [b.label]
        # 2026-11-18: a white square over the lines, the label inside it
        (back,) = [e for e in own if e.dxftype() == "HATCH"]
        assert back.dxf.true_color == 0xFFFFFF
        (label,) = [e for e in own if e.dxftype() == "TEXT"]
        assert label.dxf.layer == W_BOX.name  # red, as the square
        assert label.dxf.height == pytest.approx(sheet(BOX_TEXT_MM))
        square = box_square(b.anchor, sheet(BOX_SIZE_MM))
        assert square.contains(Point(label.dxf.align_point.x, label.dxf.align_point.y))
    texts = [t.dxf.text for t in msp.query("TEXT")]
    assert not any(t.startswith(("← ", "→ ")) for t in texts)
    notes = " ".join(wiring_notes(wiring, "ru"))
    assert "распаечная коробка" not in notes


def testcable_layer_by_purpose_protection_and_route() -> None:
    """Layer of a line: what its group is and where it runs; low-voltage by its circuit."""
    plan = make_plan(RECT, [DOOR])
    issues, contours = validate_plan(plan)
    assert not issues
    elec = base_elec()
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    run = wiring.runs[0]
    assert (
        cable_layer(replace(run, route="floor"), {run.group: LineClass("device", True)})
        == "W-CABLE-DEVICE-RCD-FLOOR"
    )
    assert cable_layer(run, {run.group: LineClass("light", False)}) == "W-CABLE-LIGHT"
    assert cable_layer(replace(run, circuit="low"), {}) == "W-CABLE-LOW"
    led = replace(run, circuit="low", mark="2x4", led=True)  # 12 V from a LED supply in the panel
    assert cable_layer(led, {run.group: LineClass("light", False)}) == "W-CABLE-LIGHT"
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
    return wall_point(pid, "socket", "w3", offset, height, group)


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
    w = wiring_of(plan, elec)
    channel = next(c for c in w.chases if c.kind == "channel")
    assert channel.targets == ("tv",) and channel.wide and channel.circuit == "low"
    assert channel.length_mm == pytest.approx(700)
    assert channel.span == (400, 1100)  # low to high, whichever end is the entry
    # Only the chase: the channel has no cable and no line from the panel
    assert not any(r.target == "tv" for r in w.runs)
    without = wiring_of(plan, elec.model_copy(update={"cable_channels": []}))
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
    w = wiring_of(plan, elec)
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
                {**wall_point("ac", "outlet", "w3", 500, 2500, "QF7"), "note": "кондиціонер"},
                wall_point("led", "led_output", "w3", 1500, 2200, "QF1"),
            ],
            "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700},
        }
    )
    w = wiring_of(make_plan(RECT, [DOOR]), elec)
    ac = next(r for r in w.runs if r.target == "ac")
    assert ac.source == "board" and ac.mark == "3x2.5"  # power, not lighting
    names = {ln.name: ln.qty for ln in build_estimate(w, elec, PriceList(), "ru").lines}
    assert names["Вывод кабеля к технике"] == 1 and names["Вывод под подсветку"] == 1


def test_board_tail_reaches_floor() -> None:
    w = wiring_of(make_plan(RECT, [DOOR]), base_elec())
    s1 = next(r for r in w.runs if r.target == "s1")  # from the panel
    assert s1.ends_mm == pytest.approx(END_ALLOWANCE + 1700)  # inside the panel down to the floor
    k1 = next(r for r in w.runs if r.target == "k1")  # from the box
    assert k1.source == "box_1" and k1.ends_mm == 2 * END_ALLOWANCE


def test_floor_route_rises_from_floor() -> None:
    cable = {"id": "c3", "from": "board", "to": ["s2", "s3"], "group": "QF3", "cable": "3x2.5"}
    w = wiring_of(make_plan(RECT, [DOOR]), base_elec([{**cable, "route": "floor"}]))
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


def test_low_voltage_in_own_chases() -> None:
    pts = [
        wall_point("s1", "socket", "w3", 500, 300, "QF5"),
        wall_point("s2", "socket", "w3", 1500, 300, "QF5"),
        wall_point("lan", "data", "w3", 560, 300, "LAN"),  # 60 mm from the socket
    ]
    elec = Electrical.model_validate(
        {"points": pts, "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700}}
    )
    w = wiring_of(make_plan(RECT, [DOOR]), elec)
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
    w = wiring_of(plan, elec)
    shared = next(c for c in w.chases if c.kind == "point")
    assert shared.cables == 4 and shared.wide and CHASE_NARROW == 2
    assert w.chase_length(wide=True) + w.chase_length(wide=False) == pytest.approx(w.chase_mm)


def test_wall_holes_over_doors_for_ceiling_runs() -> None:
    plan = two_rooms_with_door()
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
    board = {"room": "a", "wall": "w1", "offset": 1500, "height": 1700}  # facing the door
    w = wiring_of(plan, Electrical.model_validate({"points": pts, "board": board}))
    # A door in a and an opening in b at the same spot: one pass, the door id; one hole per entry
    # into a room (decision 2026-11-11): 5 cables are one ordinary hole
    (hole,) = w.holes
    assert hole.passage == "a_door_1" and hole.cables == HOLE_CABLES and not hole.large
    six = [*pts, {**pts[0], "id": "s5", "offset": 2800, "group": "QF6"}]
    (big,) = wiring_of(plan, Electrical.model_validate({"points": six, "board": board})).holes
    assert big.cables == HOLE_CABLES + 1 and big.large
    cables = [
        {"id": f"c{k}", "from": "board", "to": [f"s{k}"], "group": f"QF{k + 1}", "cable": "3x2.5"}
        for k in range(5)
    ]
    floor = [{**c, "route": "floor"} for c in cables]
    w2 = wiring_of(
        plan, Electrical.model_validate({"points": pts, "board": board, "cables": floor})
    )
    assert w2.holes == ()  # on the floor: under the opening, no drilling


def test_boxes_in_wet_rooms_marked() -> None:
    data = make_plan(RECT, [DOOR]).model_dump()
    data["rooms"][0]["wet"] = True
    w = wiring_of(Plan.model_validate(data), base_elec())
    assert w.boxes and all(b.wet for b in w.boxes)


def test_lanes_keep_clear_of_walls() -> None:
    from shapely.geometry import box

    from floorplan_engine.electrical.bundles import clearance

    many = [[Vec(0, 50), Vec(1000 + k, 50)] for k in range(5)]  # 5 cables 50 mm from the wall y=0
    room = clearance(box(-100, 0, 2000, 3000), 10.0)
    shifts = sorted(lanes(segments(many), 30.0, 300.0, room).values())
    assert shifts[-1] - shifts[0] == pytest.approx(120.0)  # step not compressed
    assert 50 + shifts[0] == pytest.approx(10.0)  # the bundle moves away from the wall, not onto it
    tight = clearance(box(-100, 0, 2000, 100), 10.0)  # 100 mm corridor: 80 of room
    shifts = sorted(lanes(segments(many), 30.0, 300.0, tight).values())
    assert 50 + shifts[0] == pytest.approx(10.0) and 50 + shifts[-1] == pytest.approx(90.0)


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


# --- Manual edits (wiring.yaml) ---------------------------------------------


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


def test_wiring_handles_lane_follows_path() -> None:
    from floorplan_engine.epd.objects import wiring_handles

    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    w = wiring_of(plan, base_elec())
    wires = wiring_handles(plan, contours, w)["wires"]
    for r in w.runs:
        h = wires[r.id]
        assert len(h["lane"]) == len(h["path"])  # a lane is the same vertices with a shift
        for (ax, ay), (bx, by) in itertools.pairwise(h["lane"]):
            assert abs(ax - bx) < 0.2 or abs(ay - by) < 0.2  # right angles


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


def test_before_plaster_drops_chases_of_bare_cable() -> None:
    plan = make_plan(walls=RECT)
    after = wiring_of(plan, four_sockets(route="ceiling"))
    assert after.chases and not after.before_plaster
    before = wiring_of(plan, four_sockets(route="ceiling", plaster="before"))
    assert before.before_plaster and not before.chases
    assert before.runs == after.runs  # the same routes and cable


def test_before_plaster_keeps_chases_with_conduit() -> None:
    """Conduit in the walls is thicker than the plaster: its chases stay. Conduit only on the
    ceiling ends there, the drops go under the plaster."""
    plan = make_plan(walls=RECT)
    walls = wiring_of(plan, four_sockets(route="ceiling", plaster="before", conduit="walls"))
    assert walls.chases == wiring_of(plan, four_sockets(route="ceiling", conduit="walls")).chases
    ceiling = wiring_of(plan, four_sockets(route="ceiling", plaster="before", conduit="ceiling"))
    assert not ceiling.chases
    floor = wiring_of(
        plan, four_sockets(route="floor", plaster="before")
    )  # the floor is always in it
    assert floor.chases == wiring_of(plan, four_sockets(route="floor")).chases


def test_chase_with_conduit_is_narrow_for_one_conduit_only() -> None:
    """A conduit is wider than a flat cable: two side by side need a wide chase (2026-11-11)."""
    two = Chase("point", "r", "w1", 500.0, 1200.0, 2)
    assert not two.wide and Chase("point", "r", "w1", 500.0, 1200.0, 1, conduit=True).wide is False
    floor = Chase("point", "r", "w1", 500.0, 1200.0, 2, route="floor")
    channel = Chase("channel", "r", "w2", 1500.0, 700.0, 2)
    assert [c.wide for c in with_conduit([two, floor, channel], "none")] == [False, True, False]
    assert [c.wide for c in with_conduit([two, floor, channel], "ceiling")] == [False, True, False]
    assert [c.wide for c in with_conduit([two, floor, channel], "walls")] == [True, True, False]


def test_conduit_in_the_walls_widens_the_chases() -> None:
    plan = make_plan(walls=RECT)
    bare = wiring_of(plan, four_sockets(route="ceiling"))
    walls = wiring_of(plan, four_sockets(route="ceiling", conduit="walls"))
    assert [c.length_mm for c in walls.chases] == [c.length_mm for c in bare.chases]
    assert all(c.conduit for c in walls.chases) and not any(c.conduit for c in bare.chases)
    wide = walls.chase_length(wide=True)
    assert wide >= bare.chase_length(wide=True)
    assert wide == sum(c.length_mm for c in walls.chases if c.cables > 1)


def test_before_plaster_keeps_a_cable_channel() -> None:
    channel = {"id": "tv", "room": "r", "wall": "w2", "offset": 1500, "entry": 400, "exit": 1100}
    wiring = wiring_of(
        make_plan(walls=RECT),
        four_sockets(route="ceiling", plaster="before", cable_channels=[channel]),
    )
    assert [c.kind for c in wiring.chases] == ["channel"]


def test_loop_point_has_a_chase_for_both_cables() -> None:
    plan, elec = make_plan(walls=RECT), four_sockets(distribution="loop", route="floor")
    wiring = wiring_of(plan, elec)
    middle = [c for c in wiring.chases if c.kind == "point" and c.cables == 2]
    assert len(middle) == 3  # in and out: all but the tail of the chain
    assert all(len(c.targets) == 1 for c in middle)


def test_loop_shared_conduit_keeps_the_chain_chase_narrow() -> None:
    """loop_conduit shared (decision 2026-11-11): a chain point's cable in and cable out go in one
    conduit, so its chase holds one conduit and stays narrow."""
    plan = make_plan(walls=RECT)
    two = wiring_of(plan, four_sockets(distribution="loop", route="floor"))
    one = wiring_of(plan, four_sockets(distribution="loop", route="floor", loop_conduit="shared"))
    middle = [c for c in one.chases if c.kind == "point" and c.cables == 2]
    assert len(middle) == 3 and all(c.pairs == 1 and c.conduits == 1 for c in middle)
    assert not any(c.wide for c in middle)
    assert all(c.wide for c in two.chases if c.kind == "point" and c.cables == 2)
    assert one.chase_length(wide=True) < two.chase_length(wide=True)
    assert [c.length_mm for c in one.chases] == [c.length_mm for c in two.chases]


def test_shared_pair_counts_only_in_conduit() -> None:
    pair = Chase("point", "r", "w1", 500.0, 1200.0, 2, ("s1",))
    assert with_conduit([pair], "none", "shared")[0].pairs == 0  # bare cable: no conduit to share
    assert with_conduit([pair], "walls", "shared")[0].pairs == 1
    assert with_conduit([pair], "walls")[0].pairs == 0
    board = Chase("board", "r", "w1", 500.0, 1200.0, 2)
    assert with_conduit([board], "walls", "shared")[0].pairs == 0  # panel lines are not a chain


def test_a_full_chase_does_not_split_a_chain_pair() -> None:
    """Drops closer than CHASE_SHARE share a chase up to CHASE_CABLES: when a chain point's
    cable in would fill it, its cable out would land in the next one; the pair moves on
    together instead."""

    def run(rid: str, source: str, target: str, rise_start: float = 0.0) -> Run:
        return Run(rid, "QF1", "3x2.5", False, source, target, (), 0.0, rise_start, 300.0, 0.0)

    runs = [
        run("a", "board", "s1"),
        run("b", "board", "s2"),
        run("c", "board", "s3"),
        run("d", "board", "s4"),
        run("e", "s4", "s5", rise_start=300.0),
    ]
    offsets = {"s1": 1000, "s2": 1020, "s3": 1040, "s4": 1060, "s5": 3000}
    points = [
        ElectricalPoint.model_validate(wall_point(p, "socket", "w1", x, 300, "QF1"))
        for p, x in offsets.items()
    ]
    chases = {c.targets: c.cables for c in wall_chases(runs, points, None, [])}
    assert chases[("s1", "s2", "s3")] == 3
    assert chases[("s4",)] == 2  # in and out together


def test_any_angle_and_conduit_follow_their_own_option() -> None:
    plan = make_plan(walls=RECT)
    assert four_sockets(mode="economy").shortest_path
    assert not four_sockets(mode="economy", path="right").shortest_path
    assert four_sockets(path="shortest").shortest_path
    assert four_sockets(mode="proper").conduit_level == "ceiling"
    assert four_sockets(mode="proper", conduit="none").conduit_level == "none"
    assert four_sockets(conduit="walls").conduit_level == "walls"
    assert (
        four_sockets(conduit=True).conduit_level == "ceiling"
    )  # electrical.yaml before 2026-11-08
    assert four_sockets(conduit=False).conduit_level == "none"
    right = wiring_of(plan, four_sockets())
    short = wiring_of(plan, four_sockets(path="shortest"))
    assert sum(r.plan_mm for r in short.runs) <= sum(r.plan_mm for r in right.runs)


def test_stacked_point_is_wired_at_the_wall_not_at_its_symbol() -> None:
    """A socket drawn behind another at the same spot gets its cable where it is on the wall:
    the route end does not move with the stack."""
    plan = make_plan(RECT, [DOOR])
    lone = base_elec()
    under = wall_point("s0", "socket", "w4", 1000, 300, "QF2")
    stacked = lone.model_copy(update={"points": [ElectricalPoint(**under), *lone.points]})

    def end(elec: Electrical) -> Vec:
        point: Vec = next(r for r in wiring_of(plan, elec).runs if r.target == "s1").path[-1]
        return point

    assert (end(stacked) - end(lone)).length() == pytest.approx(0.0, abs=1.0)


@pytest.mark.parametrize("plaster", ["after", "before"])
def test_shared_loop_pulls_the_cable_out_through_the_block(plaster: str) -> None:
    """One chase for both cables of a loop (shared, after plaster; decision 2026-11-25): the
    cable out of a block is pulled from its first flush box to its last — POST_PITCH_MM per post
    past the first on its line; a single socket and two chases add nothing; before plaster both
    cables are at the block edges, nothing either."""
    sockets = [
        w3_point("s0", "socket", 600, 300, "QF2", count=3),
        w3_point("s1", "socket", 1600, 300, "QF2"),
        w3_point("s2", "socket", 2600, 300, "QF2", count=3),
    ]
    base = {"distribution": "loop", "conduit": "walls", "plaster": plaster}
    shared, _ = room_wiring(sockets, loop_conduit="shared", **base)
    separate, _ = room_wiring(sockets, loop_conduit="separate", **base)
    assert shared.shared_rises
    counts = {"s0": 3, "s1": 1, "s2": 3}
    for a, b in zip(shared.runs, separate.runs, strict=True):
        extra = 0.0
        if plaster == "after" and a.id in shared.shared_rises:
            extra = POST_PITCH_MM * (counts[a.source] - 1)
        assert a.ends_mm == pytest.approx(b.ends_mm + extra)
    if plaster == "after":
        added = sum(
            a.length_mm - b.length_mm for a, b in zip(shared.runs, separate.runs, strict=True)
        )
        assert added == pytest.approx(2 * POST_PITCH_MM)  # one 3-post block passes the loop on
