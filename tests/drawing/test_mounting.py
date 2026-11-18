"""The "Mounting" sheet parts: fixing spots on a lane, bundle turns, the tables."""

from __future__ import annotations

import itertools
import math

from floorplan_engine.drawing.mounting import (
    bend_label,
    bends_table,
    bundle_bends,
    fixings_table,
    lane_turns,
    rounded,
)
from floorplan_engine.drawing.wiring import lay_out
from floorplan_engine.electrical.wiring_model import Run, Wiring
from floorplan_engine.model.geometry import Vec
from tests.electrical.test_estimate import _wiring


def test_table_has_a_row_per_item() -> None:
    wiring, _ = _wiring()
    table = fixings_table(wiring, "ceiling", "uk")
    assert table is not None and table.title == "Кріплення за кресленням"
    assert len(table.columns) == 5 and len(table.rows) >= 2  # a clip and pads


def _line(rid: str, path: list[Vec], mark: str = "3x2.5") -> Run:
    plan = sum((b - a).length() for a, b in itertools.pairwise(path))
    return Run(rid, "QF1", mark, False, "board", rid, tuple(path), plan, 0.0, 0.0, 0.0)


def test_bundle_turn_gets_radii_inner_first_both_directions() -> None:
    """Lines bending at one corner between the same arms turn together, whichever way they run;
    radii grow outwards; a line with no sizes is left out."""
    corner = [Vec(0, 0), Vec(2000, 0), Vec(2000, 2000)]
    runs = (
        _line("a", corner),
        _line("b", list(reversed(corner))),
        _line("c", corner, mark="3x1.5"),
        _line("utp", corner, mark="UTP"),
    )
    wiring = Wiring(2700.0, False, (), runs)
    paths, _ = lay_out(wiring)
    bends = bundle_bends(wiring, paths, "none")
    assert len(bends) == 1
    bend = bends[0]
    assert bend.at == Vec(2000, 0) and set(bend.runs) == {"a", "b", "c"}
    assert list(bend.radii) == sorted(bend.radii) and bend.radii[0] == 70
    assert bend_label(bend).startswith("R")


def test_bends_table_lists_known_types() -> None:
    corner = [Vec(0, 0), Vec(1000, 0)]
    wiring = Wiring(2700.0, False, (), (_line("a", corner), _line("u", corner, "UTP")))
    table = bends_table(wiring, "ru")
    assert table is not None and [r[0] for r in table.rows] == ["3x2.5"]


def test_single_line_turn_is_signed_with_its_radius_and_rounded() -> None:
    """A turn of one line: its radius, "R70"; the lane corner gets it."""
    wiring = Wiring(
        2700.0, False, (), (_line("a", [Vec(0, 0), Vec(2000, 0), Vec(2000, 2000)], "3x1.5"),)
    )
    paths, _ = lay_out(wiring)
    turns = lane_turns(wiring, paths, "none")
    assert [bend_label(b) for b in turns.bends] == ["R70"]
    assert turns.fillets == {(0, 1): 70.0}
    assert bundle_bends(wiring, paths, "none") == []  # one line is not a bundle


def test_bundle_lanes_turn_around_the_centre_of_the_inner_line() -> None:
    """The reference (inner sized) lane turns at the bundle's inner radius; the other lanes of
    the turn, a line without sizes too, around the same centre: tangent to their arm there."""
    corner = [Vec(0, 0), Vec(2000, 0), Vec(2000, 2000)]
    runs = (_line("a", corner), _line("b", corner), _line("utp", corner, mark="UTP"))
    wiring = Wiring(2700.0, False, (), runs)
    paths, _ = lay_out(wiring)
    turns = lane_turns(wiring, paths, "none")
    (bend,) = turns.bends
    ref = [r.id for r in runs].index(bend.runs[0])
    assert math.isclose(turns.fillets[(ref, 1)], bend.radii[0])
    centre = paths[ref][1] + bend.inside * (bend.radii[0] / math.sin(math.pi / 4))
    assert len(turns.fillets) == 3
    for (k, i), r in turns.fillets.items():
        assert math.isclose(r, abs(centre.y - paths[k][i].y))  # its distance to the east arm


def test_rounded_replaces_a_corner_by_an_arc() -> None:
    path = [Vec(0, 0), Vec(1000, 0), Vec(1000, 1000)]
    out = rounded(path, {1: 200.0})
    assert out[0] == path[0] and out[-1] == path[-1] and len(out) > 4
    centre = Vec(800, 200)
    for p in out[1:-1]:
        assert math.isclose((p - centre).length(), 200.0, abs_tol=1e-6)
    assert out[1] == Vec(800, 0) and out[-2].x == 1000 and math.isclose(out[-2].y, 200.0)


def test_rounded_cuts_a_radius_the_pieces_cannot_hold() -> None:
    """Two rounded corners share the middle piece: each takes at most half of it."""
    path = [Vec(0, 0), Vec(1000, 0), Vec(1000, 100), Vec(2000, 100)]
    out = rounded(path, {1: 500.0, 2: 500.0})
    assert all(0 <= p.y <= 100 + 1e-9 for p in out)
    assert rounded(path, {}) == path
