"""Wall elevations (elevations.py, drawing/elevations.py) on a synthetic room."""

from __future__ import annotations

import itertools

from floorplan_engine.drawing.elevations import elevation_panel, spread
from floorplan_engine.electrical.elevations import WallElevation, elevation_data, wall_elevations
from floorplan_engine.electrical.wiring import box_wiring
from floorplan_engine.model.geometry import DOOR_TOP_MM
from floorplan_engine.model.schema import CableChannel, Electrical, Plan
from floorplan_engine.validation.electrical import validate_electrical
from floorplan_engine.validation.issues import Severity, parse_model
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan

WALLS = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]
DOOR = {"wall": "w1", "type": "door", "offset": 300, "width": 800}


def _elec(points: list[dict[str, object]]) -> Electrical:
    data = {
        "points": points,
        "board": {"room": "r", "wall": "w1", "offset": 2000, "height": 1700},
    }
    elec, issues = parse_model(Electrical, data, "e.yaml")
    assert elec is not None, issues
    return elec


SOCKETS = {"room": "r", "wall": "w2", "type": "socket", "group": "QF1"}


def test_cable_channel_stands_between_its_heights() -> None:
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec([{"id": "s1", "offset": 1000, "height": 300, **SOCKETS}]).model_copy(
        update={
            "cable_channels": [
                CableChannel(id="tv", room="r", wall="w2", offset=1500, entry=400, exit=1100)
            ]
        }
    )
    wiring = box_wiring(plan, contours, elec)
    w2 = next(e for e in wall_elevations(plan, contours, elec, wiring) if e.wall == "w2")
    channel = next(c for c in w2.chases if c.x == 1500)
    assert (channel.y0, channel.y1, channel.wide) == (400, 1100, True)


def test_before_plaster_draws_no_chases() -> None:
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(
        [
            {"id": "s1", "offset": 1000, "height": 300, **SOCKETS},
            {"id": "s2", "offset": 2500, "height": 300, **SOCKETS},
        ]
    ).model_copy(update={"plaster": "before"})
    wiring = box_wiring(plan, contours, elec)
    assert all(not e.chases for e in wall_elevations(plan, contours, elec, wiring))


def test_walls_with_electrics_only_and_their_content() -> None:
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(
        [
            {"id": "s1", "offset": 1000, "height": 300, "count": 2, **SOCKETS},
            {"id": "s2", "offset": 2500, "height": 300, **SOCKETS},
            {"id": "l1", "room": "r", "ceiling": [1500, 2000], "type": "downlight", "group": "QF2"},
        ]
    )
    wiring = box_wiring(plan, contours, elec)
    walls = {e.wall: e for e in wall_elevations(plan, contours, elec, wiring)}
    assert set(walls) >= {"w1", "w2"} and "w3" not in walls  # nothing on w3
    w2 = walls["w2"]
    assert [(p.id, p.x, p.y, p.posts) for p in w2.points] == [
        ("s1", 1000, 300, 2),
        ("s2", 2500, 300, 1),
    ]
    assert w2.points[0].number < w2.points[1].number  # numbers as on the electrical sheet
    # Drops to sockets: chases from the ceiling down to the points
    assert w2.chases and all(c.y1 == w2.height for c in w2.chases)
    assert min(c.y0 for c in w2.chases) <= 300
    w1 = walls["w1"]
    assert w1.board is not None and w1.board.y == 1700
    (door,) = w1.openings
    assert (door.x0, door.x1, door.y1, door.assumed) == (300, 1100, DOOR_TOP_MM, True)
    assert {1000, 2500} <= set(w2.offsets()) and 300 in w2.heights()
    # A wall box with a mark below the ceiling
    assert all(b.y == w2.height - 200 for b in w2.boxes)


def test_points_at_one_spot_share_a_frame_with_low_voltage_last() -> None:
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(
        [
            {"id": "int", "room": "r", "wall": "w2", "offset": 1000, "height": 300, "type": "data"},
            {"id": "s1", "offset": 1000, "height": 300, "count": 3, **SOCKETS},
            {"id": "s2", "offset": 2500, "height": 300, **SOCKETS},
        ]
    )
    wiring = box_wiring(plan, contours, elec)
    w2 = next(e for e in wall_elevations(plan, contours, elec, wiring) if e.wall == "w2")
    by_id = {p.id: p for p in w2.points}
    # One block of 4 posts centred on the offset: sockets on the left, INT on the right
    assert (by_id["s1"].slot, by_id["s1"].frame) == (-0.5, 4)
    assert (by_id["int"].slot, by_id["int"].frame) == (1.5, 4)
    assert (by_id["s2"].slot, by_id["s2"].frame) == (0.0, 1)
    assert by_id["int"].x == by_id["s1"].x == 1000
    data = {e["key"]: e for e in elevation_data(plan, contours, elec, wiring, {})}
    points = {p["id"]: p for p in data["elevation:r.w2"]["points"]}
    assert (points["int"]["slot"], points["int"]["block"]) == (1.5, 4)
    assert "slot" not in points["s2"]


def test_spread_keeps_order_gap_and_bounds() -> None:
    assert spread([0, 1, 2], 2.0, 0, 100) == [0, 2, 4]
    assert spread([10, 30], 2.0, 0, 100) == [10, 30]  # far apart: in their own places
    out = spread([98, 99, 100], 2.0, 0, 100)
    assert out == [96, 98, 100]  # at the edge: shifted back, not past the boundary


def test_point_above_ceiling_extends_view_and_warns() -> None:
    plan = make_plan(WALLS)
    _, contours = validate_plan(plan)
    elec = _elec([{"id": "hi", "offset": 1000, "height": 2900, **SOCKETS}])
    (e,) = [x for x in wall_elevations(plan, contours, elec, None) if x.wall == "w2"]
    assert e.height == 2700 and e.top > 2900 and e.above_ceiling() == ["hi"]
    warn = [i for i in validate_electrical(elec, plan, contours) if "выше потолка" in i.message]
    assert len(warn) == 1 and warn[0].severity is Severity.WARNING
    assert "по умолчанию" in warn[0].message


def test_panel_size_follows_scale() -> None:
    plan = make_plan(WALLS)
    _, contours = validate_plan(plan)
    elec = _elec([{"id": "s1", "offset": 1000, "height": 300, **SOCKETS}])
    (e,) = [x for x in wall_elevations(plan, contours, elec, None) if x.wall == "w2"]
    small, big = elevation_panel(e, 100, "ru"), elevation_panel(e, 50, "ru")
    assert big.width > small.width and big.height > small.height
    assert big.width >= 4000 / 50  # wall at scale


def test_behind_names_neighbour_and_its_wall() -> None:
    """A shared partition has two elevations, each naming the other side; an exterior wall has
    none.
    """
    from typing import Any

    from floorplan_engine.model.geometry import room_geometries
    from floorplan_engine.model.schema import Plan
    from floorplan_engine.model.wall_names import Behind, behind

    def room(rid: str, x: float) -> dict[str, Any]:
        walls = [{"id": f"w{k + 1}", "length": n} for k, n in enumerate((3000, 4000, 3000, 4000))]
        return {"id": rid, "name": rid.upper(), "origin": [x, 0], "walls": walls}

    plan = Plan.model_validate(
        {
            "name": "т",
            "default_wall_thickness": 100,
            "source": "text",
            "rooms": [room("a", 0), room("b", 4100)],
        }
    )
    _, contours = validate_plan(plan)
    geoms = room_geometries(plan, contours)
    a, b = geoms
    # The right wall of a (w3) is the left wall of b (w1)
    assert behind(a, a.contour.segments[2], geoms) == (Behind("b", "B", "w1"),)
    assert behind(b, b.contour.segments[0], geoms) == (Behind("a", "A", "w3"),)
    assert behind(a, a.contour.segments[0], geoms) == ()


def test_elevation_side_line() -> None:
    from dataclasses import replace

    from floorplan_engine.drawing.elevations import _side

    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec([{"id": "s1", "offset": 1000, "height": 300, **SOCKETS}])
    w2 = next(e for e in wall_elevations(plan, contours, elec, None) if e.wall == "w2")
    assert _side(w2, "ru") == "вид изнутри · за стеной: вне квартиры"
    neighbours = replace(w2, behind=(("Кухня, коридор", "2.B"), ("Спальня", None)))
    assert _side(neighbours, "ru") == "вид изнутри · за стеной: Кухня, коридор (2.B); Спальня"


def test_back_side_points_mirrored_onto_this_wall() -> None:
    """The neighbour's socket on a shared partition appears on this side's elevation in its place:
    wall w3 of room a runs top to bottom, w1 of room b bottom to top, so an offset of 1000 from
    the bottom in b is 4000 − 1000 = 3000 from the top corner in a."""
    from typing import Any

    from floorplan_engine.model.schema import Plan

    def room(rid: str, x: float) -> dict[str, Any]:
        walls = [{"id": f"w{k + 1}", "length": n} for k, n in enumerate((4000, 3000, 4000, 3000))]
        return {"id": rid, "name": rid.upper(), "origin": [x, 0], "walls": walls}

    plan = Plan.model_validate(
        {
            "name": "т",
            "default_wall_thickness": 100,
            "source": "text",
            "rooms": [room("a", 0), room("b", 3100)],
        }
    )
    _, contours = validate_plan(plan)
    sock = {"type": "socket", "group": "QF1", "height": 300}
    elec, issues = parse_model(
        Electrical,
        {
            "points": [
                {"id": "a1", "room": "a", "wall": "w3", "offset": 500, **sock},
                {"id": "b1", "room": "b", "wall": "w1", "offset": 1000, **sock},
            ]
        },
        "e.yaml",
    )
    assert elec is not None, issues
    walls = {e.key: e for e in wall_elevations(plan, contours, elec, None)}
    (back,) = walls["a.w3"].back
    assert (back.id, back.x, back.y) == ("b1", 3000, 300)
    (mirror,) = walls["b.w1"].back
    assert (mirror.id, mirror.x) == ("a1", 3500)


def test_elevation_data_links_points_to_wiring() -> None:
    """Elevation as data for the viewer: points carry their number, group and where the wiring line
    comes from; object keys match the sheets (point:, box:, board:)."""
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(
        [
            {"id": "s1", "offset": 1000, "height": 300, "count": 2, **SOCKETS},
            {"id": "s2", "offset": 2500, "height": 300, **SOCKETS},
        ]
    )
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    walls = {e["key"]: e for e in elevation_data(plan, contours, elec, wiring, {"QF1": 0x112233})}
    w2 = walls["elevation:r.w2"]
    s1 = w2["points"][0]
    assert (s1["key"], s1["posts"], s1["group"], s1["color"]) == ("point:s1", 2, "QF1", "#112233")
    feeds = {r.target: r.source for r in wiring.runs}
    labels = {b.id: b.label for b in wiring.boxes}
    assert s1["from"] == labels.get(feeds["s1"], "ЩР")
    assert all(b["key"].startswith("box:") for b in w2["boxes"])
    assert walls["elevation:r.w1"]["board"]["key"] == "board:board"


def test_elevation_data_face_and_neighbours() -> None:
    """An elevation has its face on the plan and the neighbouring walls at the corners: the angle
    and
    what is on them (a wall without electrical items has openings only)."""
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec([{"id": "s1", "offset": 1000, "height": 300, **SOCKETS}])
    walls = {e["key"]: e for e in elevation_data(plan, contours, elec, None, {})}
    w2 = walls["elevation:r.w2"]
    assert w2["face"] == [[0.0, 3000.0], [4000.0, 3000.0]]
    left, right = w2["left"], w2["right"]
    assert (left["key"], left["turn"], left["length"]) == ("elevation:r.w1", 90, 3000)
    assert [o["kind"] for o in left["openings"]] == ["door"]
    assert left["points"] == []
    assert (right["key"], right["turn"]) == ("elevation:r.w3", 90)
    # A neighbour with electrical items lists its points and panel
    w1 = walls["elevation:r.w1"]
    assert [p["key"] for p in w1["right"]["points"]] == ["point:s1"]
    assert w1["left"]["key"] == "elevation:r.w4"
    assert "back" not in w1["right"]
    assert walls["elevation:r.w2"]["left"]["board"]["key"] == "board:board"


def test_door_shows_on_both_sides_with_its_hinge() -> None:
    def room(rid: str, x: float, inner: str, opening: dict[str, object]) -> dict[str, object]:
        walls = [
            {"id": f"w{k}", "length": 3000, **({"thickness": 100} if f"w{k}" == inner else {})}
            for k in range(1, 5)
        ]
        return {"id": rid, "name": rid, "origin": [x, 0], "walls": walls, "openings": [opening]}

    door = {"id": "a_door", "wall": "w3", "type": "door", "offset": 1000, "width": 800,
            "hinge": "start", "height": 2050}  # fmt: skip
    gap = {"id": "b_gap", "wall": "w1", "type": "opening", "offset": 1200, "width": 800}
    plan = Plan.model_validate(
        {
            "name": "тест",
            "default_wall_thickness": 200,
            "source": "text",
            "rooms": [room("a", 0, "w3", door), room("b", 3100, "w1", gap)],
        }
    )
    _, contours = validate_plan(plan)
    elec = _elec(
        [
            {
                "id": "s1",
                "room": "a",
                "wall": "w3",
                "offset": 200,
                "height": 300,
                "type": "socket",
                "group": "QF1",
            },
            {
                "id": "s2",
                "room": "b",
                "wall": "w1",
                "offset": 200,
                "height": 300,
                "type": "socket",
                "group": "QF1",
            },
        ]
    ).model_copy(update={"board": None})
    wiring = box_wiring(plan, contours, elec)
    views = {(e.room, e.wall): e for e in wall_elevations(plan, contours, elec, wiring)}
    (near,) = views[("a", "w3")].openings
    (far,) = views[("b", "w1")].openings
    assert (near.kind, near.hinge) == ("door", "start")
    # From the other room the door is the same one, its hinges on the opposite side
    assert (far.kind, far.hinge) == ("door", "end")


def _two_sockets(plaster: str) -> tuple[Plan, Electrical, list[WallElevation]]:
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(
        [
            {"id": "s1", "offset": 1000, "height": 300, **SOCKETS},
            {"id": "s2", "offset": 2500, "height": 300, **SOCKETS},
        ]
    ).model_copy(update={"plaster": plaster})
    wiring = box_wiring(plan, contours, elec)
    return plan, elec, list(wall_elevations(plan, contours, elec, wiring))


def test_drop_fixings_follow_the_wall_step_from_the_ceiling() -> None:
    """Fixings on a drop (decision 2026-11-11): first 50 mm under the ceiling, last 50 mm above
    the flush box, no farther apart than the wall step."""
    _, _, walls = _two_sockets("after")
    w2 = next(e for e in walls if e.wall == "w2")
    chase = next(c for c in w2.chases if c.y0 > 0)
    on = sorted(f.y for f in w2.fixings if f.x == chase.x)
    assert on and on[-1] == chase.y1 - 50 and on[0] == chase.y0 + 50
    assert max(b - a for a, b in itertools.pairwise(on)) <= 500 + 1e-6


def test_before_plaster_keeps_fixings_without_chases() -> None:
    _, _, walls = _two_sockets("before")
    w2 = next(e for e in walls if e.wall == "w2")
    assert not w2.chases and w2.fixings
    data_fixings = {(f.x, f.y) for f in w2.fixings}
    assert len(data_fixings) == len(w2.fixings)  # no duplicates


def test_cables_run_from_the_ceiling_to_their_points_and_fixings_count_them() -> None:
    """A wall shows each cable from the ceiling down to its point (decision 2026-11-12); a drop
    fixing knows how many cables it holds in one line."""
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(
        [
            {"id": "s1", "offset": 1000, "height": 300, **SOCKETS},
            {"id": "s2", "offset": 2500, "height": 300, **SOCKETS},
        ]
    )
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    w2 = next(e for e in wall_elevations(plan, contours, elec, wiring) if e.wall == "w2")
    assert w2.cables
    ceiling = wiring.ceiling_height
    to_points = {(c.x, c.y0, c.y1) for c in w2.cables if c.x in (1000, 2500)}
    assert {(1000, 300, ceiling), (2500, 300, ceiling)} <= to_points
    assert all(f.count >= 1 for f in w2.fixings)
    data = next(
        d for d in elevation_data(plan, contours, elec, wiring, {}) if d["key"] == "elevation:r.w2"
    )
    assert data["cables"] and all(c["key"].startswith("wire:") for c in data["cables"])


def test_socket_under_a_window_is_reached_beside_it() -> None:
    """The cable cannot go down through a window: it drops beside it (OPENING_GAP from the
    edge) to the socket height and turns along the wall to the socket; the chase and the
    cable on the wall turn the same way, the turn is in the length."""
    window = {"wall": "w2", "type": "window", "offset": 800, "width": 1500, "sill": 700}
    window["height"] = 2000  # to the ceiling
    plan = make_plan(WALLS, [DOOR, window])
    _, contours = validate_plan(plan)
    elec = _elec([{"id": "s1", "offset": 1000, "height": 300, **SOCKETS}])
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    run = next(r for r in wiring.runs if r.target == "s1")
    assert run.end_drop == 700
    assert run.rise_end_mm == 2700 - 300 + 300  # down, then 300 mm along the wall
    chase = next(c for c in wiring.chases if "s1" in c.targets)
    assert (chase.offset, chase.bend, chase.length_mm) == (700, (1000, 300), 2700)
    w2 = next(e for e in wall_elevations(plan, contours, elec, wiring) if e.wall == "w2")
    assert {(c.x, c.y0, c.y1, c.x1) for c in w2.chases} == {
        (700, 300, 2700, None),
        (700, 300, 300, 1000),
    }
    assert {(c.x, c.y0, c.y1, c.x1) for c in w2.cables} == {
        (700, 300, 2700, None),
        (700, 300, 300, 1000),
    }
    assert all(f.x == 700 and 300 < f.y < 2700 for f in w2.fixings)
    data = next(
        d for d in elevation_data(plan, contours, elec, wiring, {}) if d["key"] == "elevation:r.w2"
    )
    assert [c.get("x1") for c in data["chases"]].count(1000) == 1
    assert next(c for c in data["cables"] if "x1" in c)["x1"] == 1000


def test_turn_radii_bundle_inner_first_by_turn_side() -> None:
    """Cables turning at one corner bend as a bundle: the inner lane (nearest the side the turn
    goes to) is the reference, the next ones go out; a cable without sizes keeps no radius."""
    from floorplan_engine.electrical.elevations import CableView, turn_radii
    from floorplan_engine.electrical.mounting import BendSize, bundle_radii

    flat = BendSize(11.5, 115.0)
    turning = [
        CableView("a", "QF1", 300.0, 300.0, 300.0, 900.0),
        CableView("b", "QF1", 300.0, 300.0, 300.0, 900.0),
        CableView("c", "QF2", 300.0, 300.0, 300.0, 900.0),
    ]
    drop = CableView("a", "QF1", 300.0, 300.0, 2700.0)
    sizes = {"a": (True, flat), "b": (True, flat), "c": (True, None)}
    out = turn_radii([drop, *turning], sizes)
    assert out[0] == drop  # the drop itself has no radius
    r_inner, r_next = bundle_radii([flat, flat])
    # Turning right: the rightmost lane (last run) is inner; "c" has no sizes
    radius = {c.run: c.radius for c in out[1:]}
    assert radius == {"a": r_next, "b": r_inner, "c": None}
    # Turning left: the leftmost lane is inner
    left = [CableView(c.run, c.group, c.x, c.y0, c.y1, 0.0) for c in turning]
    radius = {c.run: c.radius for c in turn_radii(left, sizes)}
    assert radius == {"a": r_inner, "b": r_next, "c": None}
