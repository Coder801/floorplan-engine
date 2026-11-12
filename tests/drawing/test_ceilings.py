"""Ceiling view on the "Elevations" sheets (drawing/ceilings.py) on a synthetic room."""

from __future__ import annotations

from floorplan_engine.drawing.ceilings import ceiling_panel, fixing_bands
from floorplan_engine.drawing.ids import object_id
from floorplan_engine.drawing.layers import E_ELEV, M_FIX, new_document
from floorplan_engine.drawing.mounting import bundle_bends
from floorplan_engine.drawing.wiring import cable_layer, lay_out
from floorplan_engine.electrical.ceilings import ceiling_views
from floorplan_engine.electrical.colors import group_colors
from floorplan_engine.electrical.panel import line_classes
from floorplan_engine.electrical.wiring import box_wiring
from floorplan_engine.model.geometry import Vec
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan
from tests.electrical.test_ceilings import DOOR, WALLS, _elec, _points


def test_ceiling_is_one_elevation_object_with_layers() -> None:
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(_points())
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    view = ceiling_views(plan, contours, elec, wiring)[0]
    paths, plane_bundles = lay_out(wiring)
    bends = bundle_bends(wiring, paths, elec.conduit_level)
    fixings = fixing_bands(wiring, plane_bundles, elec.conduit_level)
    classes = line_classes(plan, elec)
    layers = {r.id: cable_layer(r, classes) for r in wiring.runs}
    panel = ceiling_panel(
        view, wiring, paths, bends, group_colors(elec), layers, fixings, 40.0, "ru"
    )
    assert panel.width > view.size.x / 40 and panel.height > view.size.y / 40
    doc = new_document()
    psp = doc.layouts.new("t")
    panel.draw(psp, Vec(0, 0))
    entities = list(psp)
    # The view is one object (the viewer pages it with the walls), each scale value with its
    # leaders and spots another: hovering it lights what it measures
    ids = {object_id(e) for e in entities}
    assert ("elevation", "r.ceiling") in ids
    dims = {i for i in ids if i is not None and i[0] == "dim"}
    assert dims and all(i[1].startswith("r.ceiling.") for i in dims)
    assert ids <= {("elevation", "r.ceiling"), *dims}
    # Layers the viewer switches: the room, the cables by purpose, the fixings
    drawn = {e.dxf.layer for e in entities}
    assert {E_ELEV.name, M_FIX.name} <= drawn and drawn & set(layers.values())
    texts = [e.dxf.text for e in psp.query("TEXT")]
    assert any("потолок" in t and "М 1:40" in t for t in texts)
    for e in psp.query("LINE"):
        for p in (e.dxf.start, e.dxf.end):
            assert -1 <= p.x <= panel.width + 1 and -panel.height - 1 <= p.y <= 1
