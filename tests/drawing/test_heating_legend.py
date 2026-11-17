"""Legend of the "Floor heating" sheet."""

from __future__ import annotations

import pytest

from floorplan_engine.drawing.heating_legend import heating_legend_rows, heating_legend_variants
from floorplan_engine.drawing.ids import object_id
from floorplan_engine.drawing.layers import H_CABLE, H_LEAD, H_SENSOR, H_TEXT, H_ZONE, new_document
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.texts import Language


def test_legend_variants_get_lower_with_more_columns() -> None:
    heights = [h for _, h, _ in heating_legend_variants("uk")]
    assert heights == sorted(heights) and len(heights) >= 2


@pytest.mark.parametrize("lang", ["ru", "uk"])
def test_legend_draws_every_sample(lang: Language) -> None:
    """The cable (two runs and a turn), the lead, the sensor conduit with its circle, two boxes
    (the area and the cut-out, the latter captioned inside), the controller block."""
    doc = new_document()
    psp = doc.layouts.new("legend")
    *_, draw = heating_legend_variants(lang)[0]
    draw(psp, Vec(0.0, 100.0))
    assert len(psp.query(f'LINE[layer=="{H_CABLE.name}"]')) == 2
    assert len(psp.query(f'ARC[layer=="{H_CABLE.name}"]')) == 1
    assert len(psp.query(f'LINE[layer=="{H_LEAD.name}"]')) == 1
    assert len(psp.query(f'CIRCLE[layer=="{H_SENSOR.name}"]')) == 1
    assert len(psp.query(f'LWPOLYLINE[layer=="{H_ZONE.name}"]')) == 2
    assert [t.dxf.text for t in psp.query(f'TEXT[layer=="{H_TEXT.name}"]')] == ["ванна"]
    (reg,) = psp.query("INSERT")  # the controller, on the sheet's text layer
    assert reg.dxf.layer == H_TEXT.name


def test_every_sample_is_its_legend_object() -> None:
    """The viewer badge takes the icons by legend:<key>: each row has its own sample, captions
    are not tagged."""
    doc = new_document()
    psp = doc.layouts.new("legend")
    *_, draw = heating_legend_variants("ru")[0]
    draw(psp, Vec(0.0, 100.0))
    keys = [k for k, _ in heating_legend_rows("ru")]
    tagged = {object_id(e) for e in psp if object_id(e) is not None}
    assert tagged == {("legend", k) for k in keys}
    captions = {t for _, t in heating_legend_rows("ru")}
    assert all(object_id(e) is None for e in psp.query("TEXT") if e.dxf.text in captions)
