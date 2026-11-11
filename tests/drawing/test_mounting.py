"""The "Mounting" sheet drawing: a stroke per plan fixing, the fixings table."""

from __future__ import annotations

import itertools

from floorplan_engine.drawing.layers import M_FIX, new_document
from floorplan_engine.drawing.mounting import (
    bend_label,
    bends_table,
    bundle_bends,
    draw_bends,
    draw_fixings,
    fixing_at,
    fixings_table,
)
from floorplan_engine.drawing.wiring import lay_out
from floorplan_engine.electrical.mounting import run_fixings
from floorplan_engine.electrical.wiring_model import Run, Wiring
from floorplan_engine.model.geometry import Vec
from tests.electrical.test_estimate import _wiring


def test_a_stroke_per_plan_fixing_on_its_layer() -> None:
    wiring, elec = _wiring()
    doc = new_document()
    msp = doc.modelspace()
    draw_fixings(msp, wiring, elec.conduit_level)
    strokes = msp.query(f'LINE[layer=="{M_FIX.name}"]')
    plan = sum(
        1 for r in wiring.runs for f in run_fixings(r, elec.conduit_level) if f.piece is not None
    )
    assert plan > 0 and len(strokes) == plan


def test_fixing_at_clamps_to_the_piece() -> None:
    path = [Vec(0, 0), Vec(100, 0)]
    spot = fixing_at(path, 0, 30.0)
    assert spot is not None and spot[0] == Vec(30, 0) and spot[1] == Vec(1, 0)
    end = fixing_at(path, 0, 500.0)
    assert end is not None and end[0] == Vec(100, 0)
    assert fixing_at([Vec(0, 0), Vec(0, 0)], 0, 10.0) is None


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
    assert list(bend.radii) == sorted(bend.radii) and bend.radii[0] >= 115 + 2 * 11.5
    assert bend_label(bend).startswith("R")


def test_radius_labels_on_the_mounting_layer() -> None:
    corner = [Vec(0, 0), Vec(3000, 0), Vec(3000, 3000)]
    wiring = Wiring(2700.0, False, (), (_line("a", corner), _line("b", corner)))
    doc = new_document()
    msp = doc.modelspace()
    bends = draw_bends(msp, wiring, "none")
    texts = [t.dxf.text for t in msp.query(f'TEXT[layer=="{M_FIX.name}"]')]
    assert len(bends) == 1 and texts == [bend_label(bends[0])]


def test_bends_table_lists_known_types() -> None:
    corner = [Vec(0, 0), Vec(1000, 0)]
    wiring = Wiring(2700.0, False, (), (_line("a", corner), _line("u", corner, "UTP")))
    table = bends_table(wiring, "ru")
    assert table is not None and [r[0] for r in table.rows] == ["3x2.5"]
