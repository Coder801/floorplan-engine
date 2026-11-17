"""Ceiling views for the "Mounting" sheet (electrical/ceilings.py) on a synthetic room."""

from __future__ import annotations

import itertools
from dataclasses import replace

from floorplan_engine.electrical.ceilings import (
    ceiling_data,
    ceiling_lines,
    ceiling_views,
    dimension_key,
    dimension_runs,
    dimension_spots,
    lane_key,
    view_offsets,
)
from floorplan_engine.electrical.wiring import box_wiring
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.schema import Electrical
from floorplan_engine.validation.issues import parse_model
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan

WALLS = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]
DOOR = {"wall": "w1", "type": "door", "offset": 300, "width": 800}


def _elec(points: list[dict[str, object]], **extra: object) -> Electrical:
    data = {
        "points": points,
        "board": {"room": "r", "wall": "w1", "offset": 2000, "height": 1700, "name": "ЩР"},
        **extra,
    }
    elec, issues = parse_model(Electrical, data, "e.yaml")
    assert elec is not None, issues
    return elec


SOCKET = {"room": "r", "wall": "w2", "type": "socket", "group": "QF1", "height": 300}


def _points() -> list[dict[str, object]]:
    """Two sockets on w2 and a downlight on the ceiling."""
    return [
        {"id": "s1", "offset": 1000, **SOCKET},
        {"id": "s2", "offset": 2500, **SOCKET},
        {"id": "l1", "room": "r", "ceiling": [1500, 2000], "type": "downlight", "group": "QF2"},
    ]


def test_one_ceiling_view_per_room_with_its_lines_and_ends() -> None:
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(_points())
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    views = ceiling_views(plan, contours, elec, wiring)
    assert [v.key for v in views] == ["r.ceiling"]  # no floor routes, no floor view
    view = views[0]
    assert set(view.runs) == {r.id for r in wiring.runs if r.route == "ceiling"}
    assert len(view.walls) == 4 and all(w.code for w in view.walls)
    kinds = {e.kind for e in view.ends}
    assert {"drop", "light", "board"} <= kinds
    board = next(e for e in view.ends if e.kind == "board")
    assert board.groups == ("ЩР",) and board.numbers == ()
    light = next(e for e in view.ends if e.kind == "light")
    assert light.numbers and light.groups == ("QF2",)
    assert {b.id for b in view.boxes} == {b.id for b in wiring.boxes}
    assert view.left is not None and view.bottom is not None


def test_offsets_start_at_zero_end_at_the_room_and_skip_close_values() -> None:
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(_points())
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    view = ceiling_views(plan, contours, elec, wiring)[0]
    xs, ys = view_offsets(view, wiring)
    size = view.size
    assert xs[0] == 0 and xs[-1] == round(size.x)
    assert ys[0] == 0 and ys[-1] == round(size.y)
    for values in (xs, ys):
        assert values == sorted(values)
        inner = values[1:-1]  # the room size may come closer to the last value
        assert all(b - a >= 30 for a, b in itertools.pairwise(inner))


def test_floor_route_gets_its_own_floor_view() -> None:
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(_points(), route="floor")
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    planes = {v.plane for v in ceiling_views(plan, contours, elec, wiring)}
    assert "floor" in planes


def test_each_scale_value_knows_what_it_measures() -> None:
    """The ceiling light is measured on both scales; the scale ends (walls) measure nothing of
    their own; every value has its object key."""
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(_points())
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    view = ceiling_views(plan, contours, elec, wiring)[0]
    xs, ys = dimension_spots(view, wiring)
    assert list(xs) == view_offsets(view, wiring)[0] and list(ys) == view_offsets(view, wiring)[1]
    light = next(e.at for e in view.ends if e.kind == "light")
    assert any(light in spots for spots in xs.values())
    assert any(light in spots for spots in ys.values())
    assert xs[0.0] == [] and xs[max(xs)] == []
    assert dimension_key(view, "x", 1450.0) == "dim:r.ceiling.x1450"


def test_each_line_knows_the_scale_values_that_measure_it() -> None:
    """A pinned line keeps its scale values in the viewer: the line to the ceiling light is
    measured at the light on both scales; every value of a line is a value of the view; the data
    for the viewer carries them per line."""
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(_points())
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    view = ceiling_views(plan, contours, elec, wiring)[0]
    dims = dimension_runs(view, wiring)
    assert set(dims) == set(view.runs)
    xs, ys = view_offsets(view, wiring)
    every = {dimension_key(view, "x", v) for v in xs} | {dimension_key(view, "y", v) for v in ys}
    assert all(set(keys) <= every and len(set(keys)) == len(keys) for keys in dims.values())
    light = next(e for e in view.ends if e.kind == "light")
    o = view.origin
    for rid in light.runs:
        assert any(k.startswith(f"dim:r.ceiling.x{round(light.at.x - o.x)}") for k in dims[rid])
        assert any(k.startswith(f"dim:r.ceiling.y{round(light.at.y - o.y)}") for k in dims[rid])
    (data,) = ceiling_data(plan, contours, elec, wiring, {})
    assert all(x["dims"] == list(dims[x["key"].rsplit(".", 1)[1]]) for x in data["lines"])


def test_ceiling_lines_name_their_ends_and_measure_the_room_part() -> None:
    """Decision 2026-11-17: the side panel of a ceiling lists its lines — ends as on the sheets
    (the panel by name, a box by its label, a point as "N · kind"), cable, length in the room."""
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(_points())
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    view = ceiling_views(plan, contours, elec, wiring)[0]
    lines = ceiling_lines(plan, elec, wiring, view)
    assert [ln.run for ln in lines] == list(view.runs)
    runs = {r.id: r for r in wiring.runs}
    labels = {b.label for b in wiring.boxes}
    for ln in lines:
        r = runs[ln.run]
        assert (ln.group, ln.mark) == (r.group, r.mark)
        assert 0 < ln.length <= r.plan_mm + 1
        for end, name in ((r.source, ln.source), (r.target, ln.target)):
            if end == "board":
                assert name == "ЩР"
            elif end.startswith("box_"):
                assert name in labels
            else:
                assert " · " in name and name.split(" · ")[0].isdigit()
    (data,) = ceiling_data(plan, contours, elec, wiring, {"QF1": 0xFF0000})
    assert data["key"] == "elevation:r.ceiling" and data["plane"] == "ceiling"
    first = data["lines"][0]
    assert first["key"] == lane_key(view, lines[0].run) == f"lane:r.ceiling.{lines[0].run}"
    assert "wire" not in first
    assert (first["source"], first["target"]) == (
        runs[lines[0].run].source,
        runs[lines[0].run].target,
    )
    assert all(x["transit"] is False for x in data["lines"])  # every line ends in the one room
    qf1 = [x for x in data["lines"] if x["group"] == "QF1"]
    assert qf1 and all(x["color"] == "#ff0000" for x in qf1)


def test_a_line_without_an_end_in_the_room_is_transit() -> None:
    """Decision 2026-11-17: a line that only passes through the room (both ends elsewhere) is
    marked transit in the side panel; a line with a box of the view or a point in the room at
    either end is not."""
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(_points())
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    view = ceiling_views(plan, contours, elec, wiring)[0]
    o, size = view.origin, view.size
    y = o.y + size.y / 2
    model = wiring.runs[0]
    through = replace(
        model,
        id="through",
        source="box_far",  # a box of another room
        target="s9",  # a point elsewhere
        path=(Vec(o.x - 2000, y), Vec(o.x + size.x + 2000, y)),
    )
    into = replace(through, id="into", path=(Vec(o.x - 2000, y), Vec(o.x + size.x / 2, y)))
    wiring = replace(wiring, runs=(*wiring.runs, through, into))
    view = replace(view, runs=(*view.runs, "through", "into"))
    lines = {ln.run: ln for ln in ceiling_lines(plan, elec, wiring, view)}
    assert lines["through"].transit
    assert not lines["into"].transit  # its point end lies in the room
    assert (lines["through"].source_id, lines["through"].target_id) == ("box_far", "s9")
    box = view.boxes[0].id
    from_box = replace(through, id="from_box", source=box)
    wiring = replace(wiring, runs=(*wiring.runs, from_box))
    view = replace(view, runs=(*view.runs, "from_box"))
    lines = {ln.run: ln for ln in ceiling_lines(plan, elec, wiring, view)}
    assert not lines["from_box"].transit  # starts at a box of this view, wherever its path is
