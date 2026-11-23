"""Tests of electrical/wiring_links.py: the lines of one group through boxes, in a daisy
chain or straight from the panel."""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from floorplan_engine.electrical.anchors import SYMBOL_DEPTH
from floorplan_engine.electrical.wiring import box_wiring
from floorplan_engine.electrical.wiring_context import END_ALLOWANCE, LIGHT_LOOP
from floorplan_engine.electrical.wiring_links import section
from floorplan_engine.electrical.wiring_model import line_starts
from floorplan_engine.model.scale import sheet
from floorplan_engine.model.schema import Electrical
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan
from tests.electrical.conftest import (
    DOOR,
    RECT,
    base_elec,
    chain_wiring,
    four_sockets,
    two_rooms_with_door,
    wall_point,
    wiring_of,
)


def test_topology_board_box_point_only() -> None:
    w = wiring_of(make_plan(RECT, [DOOR]), base_elec())
    boxes = {b.id: b for b in w.boxes}
    assert sorted(b.group for b in w.boxes) == ["QF1", "QF3"]  # QF2 has one point, no box
    for r in w.runs:
        # no cable runs from a load, except from light to light of one set (2026-11-18)
        assert r.source in ("board", "l1", "l2") or r.source in boxes
        if r.target in boxes:
            assert r.source == "board"  # a box is fed only from the panel
    targets = {r.target: r.source for r in w.runs}
    assert targets["s1"] == "board"
    assert targets["k1"] == "box_1"
    # l1 and l2 light up together: one cable from the box to the nearer, then to the other
    assert {targets["l1"], targets["l2"]} - {"box_1"} in ({"l1"}, {"l2"})
    assert targets["d1"] == "board"
    assert w.skipped == ()


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
    point = {**wall_point("h1", "outlet", "w4", 1000, 750, "QF9"), "note": note, "power": power}
    elec = base_elec().model_copy(
        update={"points": Electrical.model_validate({"points": [point]}).points}
    )
    run = next(r for r in wiring_of(make_plan(RECT, [DOOR]), elec).runs if r.group == "QF9")
    assert (run.mark, run.mark_assumed) == (mark, True)


def test_mark_from_model_or_assumed() -> None:
    cable = {"id": "c1", "from": "board", "to": ["s1"], "group": "QF2", "cable": "3x4"}
    w = wiring_of(make_plan(RECT, [DOOR]), base_elec([cable]))
    marks = {r.group: (r.mark, r.mark_assumed) for r in w.runs}
    assert marks["QF2"] == ("3x4", False)
    assert marks["QF1"] == ("3x1.5", True) and marks["QF3"] == ("3x2.5", True)


def test_heavy_lines_and_outlets_go_without_boxes() -> None:
    assert section("3x6") == 6 and section("5х2,5") == 2.5 and section("UTP") == 0
    pts = [
        wall_point("h1", "socket", "w3", 500, 900, "QF9"),
        wall_point("h2", "socket", "w3", 2500, 900, "QF9"),
        wall_point("ac", "outlet", "w4", 500, 2500, "QF7"),
        wall_point("tw", "outlet", "w4", 2500, 900, "QF7"),
        wall_point("r1", "socket", "w1", 1500, 300, "QF4"),
        wall_point("r2", "socket", "w1", 2500, 300, "QF4"),
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
    w = wiring_of(make_plan(RECT, [DOOR]), elec)
    assert [b.group for b in w.boxes] == ["QF4"]  # 3x6 and appliance outputs: no boxes
    src = {r.target: r.source for r in w.runs}
    assert all(src[p] == "board" for p in ("h1", "h2", "ac", "tw"))
    # direct: false in the model: through a box again
    forced = [{**cables[0], "direct": False}, cables[1]]
    w2 = wiring_of(make_plan(RECT, [DOOR]), elec.model_copy(update={"cables": []}))
    assert "QF9" in {b.group for b in w2.boxes}  # without a cable the type is 3x2.5: through a box
    assert "QF7" not in {b.group for b in w2.boxes}  # appliance outputs: still no boxes
    w3 = wiring_of(
        make_plan(RECT, [DOOR]),
        Electrical.model_validate({**elec.model_dump(by_alias=True), "cables": forced}),
    )
    assert "QF9" in {b.group for b in w3.boxes}


def test_box_lines_never_exceed_largest_regular_box() -> None:
    from floorplan_engine.electrical.boxes import BOX_BRANCHES

    plan = make_plan([{"length": 4000}, {"length": 6000}, {"length": 4000}, {"length": 6000}], [])
    # LED outputs: never in a light set, a box branch each
    pts = [wall_point(f"d{k}", "led_output", "w1", 300 + 250 * k, 2000, "QF1") for k in range(14)]
    elec = Electrical.model_validate(
        {"points": pts, "board": {"room": "r", "wall": "w4", "offset": 500, "height": 1700}}
    )
    w = wiring_of(plan, elec)
    ids = {b.id for b in w.boxes}
    branches = [sum(1 for r in w.runs if r.source == b.id) for b in w.boxes]
    assert len(w.boxes) >= 2 and max(branches) <= BOX_BRANCHES  # the feeds to boxes count too
    assert sum(1 for r in w.runs if r.source in ids and r.target not in ids) == 14
    # One cable of the group into the room (decision 2026-11-13): the other boxes from a box
    feeds = {r.target: r.source for r in w.runs if r.target in ids}
    assert sorted(feeds) == sorted(ids)
    assert sum(src == "board" for src in feeds.values()) == 1
    assert all(src == "board" or src in ids for src in feeds.values())


def test_proper_keeps_a_panel_line_for_every_box() -> None:
    """Where each line from the panel has its own breaker the cable is not shared."""
    plan = make_plan([{"length": 4000}, {"length": 6000}, {"length": 4000}, {"length": 6000}], [])
    # LED outputs: never in a light set, a box branch each
    pts = [wall_point(f"d{k}", "led_output", "w1", 300 + 250 * k, 2000, "QF1") for k in range(14)]
    board = {"room": "r", "wall": "w4", "offset": 500, "height": 1700}
    elec = Electrical.model_validate({"points": pts, "board": board, "mode": "proper"})
    w = wiring_of(plan, elec)
    assert len(w.boxes) == 2
    assert all(any(r.target == b.id and r.source == "board" for r in w.runs) for b in w.boxes)


def test_switch_outside_room_goes_into_its_light_box() -> None:
    plan = two_rooms_with_door()
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
    w = wiring_of(plan, elec)
    (box,) = w.boxes  # the switch has no box of its own
    assert box.room == "b"
    to_switch = next(r for r in w.runs if r.target == "k1")
    assert to_switch.source == box.id  # from the light box, not from the panel
    assert not any(r.source == "board" and r.target == "k1" for r in w.runs)
    assert box.size == "80"  # 3 lines: feed, the two lights in one set, switch


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


def test_floor_route_never_rises_through_the_room() -> None:
    """Floor route: cable to a ceiling point runs on the ceiling. A lighting group goes entirely on
    the ceiling, and in a mixed group the branch rises up the wall from the box and runs along the
    ceiling. No rise from the floor in the middle of a room (decision 2026-11-01)."""
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    light = {"id": "l1", "room": "r", "type": "downlight", "ceiling": [1500, 2000]}
    points = [
        {**light, "group": "QF1"},
        wall_point("k1", "switch", "w3", 2500, 900, "QF1"),
        {**light, "id": "l2", "ceiling": [1000, 1000], "group": "QF2"},  # mixed group
        wall_point("s1", "socket", "w3", 500, 300, "QF2"),
        wall_point("s2", "socket", "w3", 1500, 300, "QF2"),
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


def test_loop_chains_sockets_without_a_box() -> None:
    plan, elec = make_plan(walls=RECT), four_sockets(distribution="loop", route="floor")
    wiring = wiring_of(plan, elec)
    assert not wiring.boxes
    assert [r.source for r in wiring.runs if r.source == "board"] == ["board"]  # one panel line
    assert len(wiring.runs) == 4
    assert {r.target for r in wiring.runs} == {"s1", "s2", "s3", "s4"}
    head = next(r for r in wiring.runs if r.source == "board").target
    assert sum(r.source == head for r in wiring.runs) == 1  # a chain, not a star
    assert all(r.rise_start_mm == 300 for r in wiring.runs if r.source != "board")
    assert line_starts(wiring.runs) == dict.fromkeys(("s1", "s2", "s3", "s4"), head)


def test_loop_leaves_light_in_its_box() -> None:
    light = {"id": "l1", "room": "r", "type": "light", "ceiling": [1500, 2000], "group": "QF2"}
    switch = wall_point("sw1", "switch", "w2", 2500, 900, "QF2")
    base = four_sockets().model_dump(mode="json", by_alias=True, exclude_none=True)
    data = {**base, "points": [*base["points"], light, switch], "distribution": "loop"}
    wiring = wiring_of(make_plan(walls=RECT), Electrical.model_validate(data))
    assert len(wiring.boxes) == 1
    box = wiring.boxes[0].id
    assert {r.target for r in wiring.runs if r.source == box} == {"l1", "sw1"}
    assert sum(r.source == "board" for r in wiring.runs) == 2  # the box and the chain


def test_loop_long_chain_is_split_into_panel_lines() -> None:
    points = [wall_point(f"s{k}", "socket", "w3", 100 + k * 300, 300, "QF2") for k in range(10)]
    data = four_sockets().model_dump(mode="json", by_alias=True, exclude_none=True)
    elec = Electrical.model_validate({**data, "points": points, "distribution": "loop"})
    wiring = wiring_of(make_plan(walls=RECT), elec)
    assert sum(r.source == "board" for r in wiring.runs) >= 2


def test_fan_of_a_lighting_line_is_fed_from_its_switch() -> None:
    """Decision 2026-11-13: an appliance output in a lighting group of a light chain gets no
    panel line of its own, it is fed from the flush box of the group's switch."""
    fan = wall_point("f1", "outlet", "w3", 3000, 2400, "QF1")
    w = chain_wiring([fan])
    lit = {r.target: r.source for r in w.runs if r.group == "QF1"}
    assert lit["k1"] == "board" and lit["f1"] == "k1"
    assert list(lit.values()).count("board") == 1


def test_loop_sockets_of_one_frame_are_joined_in_the_wall() -> None:
    """Sockets side by side in one frame: the cable between them does not go up to the ceiling."""
    base = base_elec().model_dump(mode="json", by_alias=True, exclude_none=True)
    twin = wall_point("s4", "socket", "w3", 2500, 300, "QF3")  # in one frame with s3
    data = {**base, "points": [*base["points"], twin], "distribution": "loop"}
    w = wiring_of(make_plan(RECT, [DOOR]), Electrical.model_validate(data))
    runs = {r.target: r for r in w.runs if r.group == "QF3"}
    jumper = runs["s4"] if runs["s4"].source == "s3" else runs["s3"]
    assert jumper.source in ("s3", "s4") and jumper.vertical_mm == 0 and jumper.plan_mm < 500
    assert sum(r.source == "board" for r in runs.values()) == 1


def test_thermostats_get_lines_of_their_own_as_before_the_type() -> None:
    """Floor heating controllers go from the panel one by one, without boxes, with or without
    `direct: true`; the cable is the same as for the switch and the output they used to be."""

    def model(kind: str, direct: bool | None) -> Electrical:
        cable: dict[str, Any] = {"id": "c5", "from": "board", "to": ["t1", "t2"], "group": "QF5",
                                 "cable": "3x2.5"}  # fmt: skip
        if direct is not None:
            cable["direct"] = direct
        note = {"note": "регулятор ТП"}
        return Electrical.model_validate(
            {
                "points": [
                    {**wall_point("t1", kind, "w3", 500, 1500, "QF5"), **note},
                    {**wall_point("t2", kind, "w4", 2500, 1500, "QF5"), **note},
                ],
                "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700},
                "cables": [cable],
            }
        )

    plan = make_plan(RECT, [DOOR])

    def lines(elec: Electrical) -> list[tuple[str, str, str, float]]:
        w = wiring_of(plan, elec)
        assert not w.boxes
        return [(r.source, r.target, r.mark, round(r.length_mm, 1)) for r in w.runs]

    new = lines(model("thermostat", True))
    assert [(s, t, m) for s, t, m, _ in new] == [("board", "t1", "3x2.5"), ("board", "t2", "3x2.5")]
    # The same lines as for the switch and the output they used to be; a route ends at the symbol
    # tip (anchors.SYMBOL_DEPTH), so the length moves by the difference in symbol depth only
    for kind in ("switch", "outlet"):
        old = lines(model(kind, True))
        assert [x[:3] for x in old] == [x[:3] for x in new]
        gap = sheet(abs(SYMBOL_DEPTH["thermostat"] - SYMBOL_DEPTH[kind]))
        assert all(abs(a[3] - b[3]) <= gap + 0.1 for a, b in zip(old, new, strict=True))
    assert new == lines(model("thermostat", None))  # the type alone is enough
    # Without a cable in the model: still direct, and a power cable
    bare = model("thermostat", None).model_copy(update={"cables": []})
    assert [(s, t, m) for s, t, m, _ in lines(bare)] == [(s, t, m) for s, t, m, _ in new]
    # direct: false in the model wins, as for any group
    boxed = wiring_of(plan, model("thermostat", False))
    assert [b.group for b in boxed.boxes] == ["QF5"]


def _set_elec(points: list[dict[str, Any]]) -> Electrical:
    """A lighting group QF1 in room r: the given points and the panel."""
    return Electrical.model_validate(
        {
            "points": points,
            "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700},
        }
    )


def _dl(pid: str, x: float, y: float, kind: str = "downlight") -> dict[str, Any]:
    return {"id": pid, "room": "r", "type": kind, "ceiling": [x, y], "group": "QF1"}


def test_box_light_set_goes_in_a_chain() -> None:
    """Lights of one set behind a box share one cable (decision 2026-11-18): box → the nearest
    light → the next; a loop at each ceiling light, no box branch per light."""
    elec = _set_elec(
        [
            _dl("a", 1000, 2000),
            _dl("b", 2000, 2000),
            _dl("c", 3000, 2000),
            wall_point("k", "switch", "w1", 2500, 900, "QF1"),
        ]
    )
    w = wiring_of(make_plan(RECT), elec)
    (box,) = w.boxes
    by_target = {r.target: r for r in w.runs}
    from_box = sorted(r.target for r in w.runs if r.source == box.id)
    assert len(from_box) == 2 and "k" in from_box  # the switch and the head of the set
    head = next(t for t in from_box if t != "k")
    chain = [head]
    while (nxt := next((r.target for r in w.runs if r.source == chain[-1]), None)) is not None:
        chain.append(nxt)
    assert sorted(chain) == ["a", "b", "c"]
    assert by_target[head].ends_mm == END_ALLOWANCE + LIGHT_LOOP
    for a, b in itertools.pairwise(chain):
        assert by_target[b].source == a and by_target[b].ends_mm == LIGHT_LOOP
    assert box.size == "80"  # feed, switch, one set: three lines


def test_box_different_sets_get_own_branches() -> None:
    """Lights of different kinds or switches are different sets: the box joins them, each set
    gets its own branch; an LED output is never in a set."""
    elec = _set_elec(
        [
            _dl("a", 1000, 2000),
            _dl("b", 1500, 2000),
            _dl("p1", 2500, 2000, "pendant"),
            _dl("p2", 3000, 2000, "pendant"),
            wall_point("led1", "led_output", "w3", 1000, 2400, "QF1"),
            {**wall_point("k1", "switch", "w1", 2000, 900, "QF1"), "controls": ["a", "b"]},
            {**wall_point("k2", "switch", "w1", 2500, 900, "QF1"), "controls": ["p1", "p2"]},
        ]
    )
    w = wiring_of(make_plan(RECT), elec)
    (box,) = w.boxes
    sources = {r.target: r.source for r in w.runs}
    assert sources["led1"] == sources["k1"] == sources["k2"] == box.id
    assert {sources["a"], sources["b"]} in ({box.id, "a"}, {box.id, "b"})
    assert {sources["p1"], sources["p2"]} in ({box.id, "p1"}, {box.id, "p2"})
