"""Pipe paths on the sheet: lanes."""

from __future__ import annotations

from floorplan_engine.model.plumbing import Plumbing
from floorplan_engine.plumbing.network import build_network
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_flat


def test_lanes_do_not_push_pipes_into_walls() -> None:
    """A piece along a wall face (to the mixer behind the bath) is not shifted into the wall on
    the sheet.
    """
    import shapely
    from shapely.geometry import LineString

    from floorplan_engine.drawing.pipe_paths import lay_out
    from floorplan_engine.model.scale import drawing_scale

    plumbing = Plumbing.model_validate(
        {
            "risers": [{"id": "r1", "room": "bath", "at": [150, 150], "water": True}],
            "fixtures": [
                {"id": "b", "room": "bath", "type": "bath", "wall": "w2", "offset": 1700},
                {"id": "s", "room": "bath", "type": "sink", "wall": "w2", "offset": 400},
                {"id": "k", "room": "kitchen", "type": "kitchen_sink", "wall": "w2", "offset": 600},
            ],
            "obstacles": [
                {
                    "id": "tub",
                    "room": "bath",
                    "type": "bath",
                    "wall": "w2",
                    "offset": 900,
                    "width": 1100,
                    "depth": 700,
                }
            ],
        }
    )
    plan = make_flat()
    _, contours = validate_plan(plan)
    net = build_network(plan, contours, plumbing)
    assert net.free is not None
    area = shapely.unary_union([net.free]).buffer(1.0)
    with drawing_scale(40):
        paths = lay_out(net)
    for pipe, path in zip(net.pipes, paths, strict=True):
        drawn = LineString([v.as_tuple() for v in path]).difference(area).length
        model = LineString([v.as_tuple() for v in pipe.path]).difference(area).length
        assert drawn <= model + 1.0, pipe.id


def test_water_pipes_not_drawn_on_top_of_each_other() -> None:
    """Cold and hot do not lie on top of each other on the sheet: at a wall towards the outlets in
    lanes from the wall, on neighbouring lines as one bundle; a branch without a hairpin."""
    from shapely.geometry import LineString

    from floorplan_engine.drawing.pipe_paths import _square, lay_out
    from floorplan_engine.model.geometry import Vec
    from floorplan_engine.model.scale import drawing_scale, sheet

    plumbing = Plumbing.model_validate(
        {
            "risers": [{"id": "r1", "room": "bath", "at": [150, 150], "water": True}],
            "fixtures": [
                {"id": "s1", "room": "bath", "type": "sink", "wall": "w1", "offset": 900},
                {"id": "s2", "room": "bath", "type": "sink", "wall": "w1", "offset": 1500},
                {"id": "sh", "room": "bath", "type": "shower", "wall": "w2", "offset": 1000},
                {"id": "k", "room": "kitchen", "type": "kitchen_sink", "wall": "w2", "offset": 600},
                {"id": "d", "room": "kitchen", "type": "dishwasher", "wall": "w2", "offset": 1200},
            ],
        }
    )
    plan = make_flat()
    _, contours = validate_plan(plan)
    net = build_network(plan, contours, plumbing)
    with drawing_scale(40):
        paths = lay_out(net)
        tol = sheet(0.3)
    water = [(p, path) for p, path in zip(net.pipes, paths, strict=True) if p.kind != "sewer"]
    for i, (p, a) in enumerate(water):
        line = LineString([v.as_tuple() for v in a])
        for q, b in water[i + 1 :]:
            if p.id in (q.parent, q.source) or q.id in (p.parent, p.source):
                continue  # the branch starts on its own pipe
            common = line.intersection(LineString([v.as_tuple() for v in b]).buffer(tol))
            parts = getattr(common, "geoms", [common])
            # A crossing gives a piece of about 2·tol, which is not an overlap; along the line it is
            # longer
            along = sum(g.length for g in parts if g.length > 3 * tol)
            assert along < 50.0, (p.id, q.id)
    spike = [Vec(0, 0), Vec(0, 100), Vec(0, 300), Vec(0, 200), Vec(500, 200), Vec(510, 260)]
    # Going back along a line has no hairpin; a slanted tail becomes an elbow along the previous
    # piece
    assert _square(spike) == [Vec(0, 0), Vec(0, 200), Vec(510, 200), Vec(510, 260)]
