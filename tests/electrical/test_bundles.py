"""Lane order of a bundle (decision 2026-11-17): cables lie in the order of where they leave it."""

from __future__ import annotations

import itertools

from shapely.geometry import LineString

from floorplan_engine.electrical.bundles import lanes, offset_path, segments, side
from floorplan_engine.model.geometry import Vec


def _laid(paths: list[list[Vec]]) -> list[list[Vec]]:
    segs = segments(paths)
    off = lanes(segs, 30.0, 1000.0, None, paths)
    return [
        offset_path(p, [off.get((k, i), 0.0) for i in range(len(p) - 1)])
        for k, p in enumerate(paths)
    ]


def test_cables_from_the_panel_do_not_cross() -> None:
    """From one panel point up, then right along one line; each leaves the line at its own spot,
    up or down. Laid in lanes, no two cables cross: the order at the panel already fits."""
    ends = [(1000, 1), (2000, -1), (3000, 1), (4000, -1), (5000, 1)]
    paths = [
        [Vec(0, 0), Vec(0, 1000), Vec(float(x), 1000), Vec(float(x), 1000 + 2000 * d)]
        for x, d in ends
    ]
    laid = _laid(paths)
    for a, b in itertools.combinations(laid, 2):
        # the start is the panel point, shifted into the lane: drop it, cables may touch there
        assert not LineString([p.as_tuple() for p in a[1:]]).intersects(
            LineString([p.as_tuple() for p in b[1:]])
        )


def test_cables_on_one_route_do_not_cross_at_turns() -> None:
    """Three cables the same way to one drop (an oven, a hob and a hood on one wall) never part:
    their order holds through both turns, so they do not cross at the panel."""
    route = [Vec(0, 0), Vec(0, 1000), Vec(3000, 1000), Vec(3000, -1000)]
    laid = _laid([list(route) for _ in range(3)])
    for a, b in itertools.combinations(laid, 2):
        assert not LineString([p.as_tuple() for p in a]).intersects(
            LineString([p.as_tuple() for p in b])
        )


def test_side_by_where_routes_part() -> None:
    """Along +x: the cable turning up (to the left) lies on + (up), one going on lies below it;
    a vertical line, along +y: the cable turning right lies on + (right)."""
    up = [Vec(0, 0), Vec(1000, 0), Vec(1000, 1000)]
    on = [Vec(0, 0), Vec(3000, 0)]
    segs = segments([up, on])
    assert side([up, on], segs[0], segs[2], 0.0, 1000.0) == 1
    assert side([up, on], segs[2], segs[0], 0.0, 1000.0) == -1
    right = [Vec(0, 0), Vec(0, 1000), Vec(1000, 1000)]
    left = [Vec(0, 0), Vec(0, 1000), Vec(-1000, 1000)]
    vs = segments([right, left])
    assert side([right, left], vs[0], vs[2], 0.0, 1000.0) == 1
    same = segments([on, on])
    assert side([on, on], same[0], same[1], 0.0, 3000.0) == 0  # never part
