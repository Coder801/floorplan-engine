"""Furniture on the plan and the floor heating sheet (drawing/furniture.py, sheets/stages.py)."""

from __future__ import annotations

from floorplan_engine.drawing.ids import object_id
from floorplan_engine.drawing.layers import F_FURN, LED_LINETYPE
from floorplan_engine.model.furniture import Furniture
from floorplan_engine.model.schema import Electrical
from floorplan_engine.sheets.stages import (
    FLOOR_HEATING_SHEET_LAYERS,
    PLAN_SHEET_LAYERS,
    draw_stages,
)
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan

WALLS = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]
FURNITURE = Furniture.model_validate(
    {
        "items": [
            {"id": "k", "room": "r", "kind": "kitchen", "at": [0, 0], "size": [600, 3000]},
            {"id": "bed", "room": "r", "kind": "bed", "at": [2000, 500], "size": [1600, 2000]},
            {"id": "tiny", "room": "r", "kind": "cabinet", "at": [3800, 0], "size": [100, 100]},
            {"id": "ghost", "room": "nope", "kind": "bed", "at": [0, 0], "size": [100, 100]},
        ]
    }
)


def test_pieces_are_tagged_on_their_layer() -> None:
    plan = make_plan(WALLS)
    _, contours = validate_plan(plan)
    doc, _ = draw_stages(plan, contours, None, furniture=FURNITURE)
    msp = doc.modelspace()
    outlines = msp.query(f'LWPOLYLINE[layer=="{F_FURN.name}"]')
    assert [object_id(e) for e in outlines] == [
        ("furniture", "k"),
        ("furniture", "bed"),
        ("furniture", "tiny"),
    ]
    kitchen, bed, _ = outlines
    assert kitchen.dxf.linetype != LED_LINETYPE and bed.dxf.linetype == LED_LINETYPE
    labels = msp.query(f'TEXT[layer=="{F_FURN.name}"]')
    # The kitchen label goes along its long side; the tiny cabinet has no room for one
    assert {object_id(t) for t in labels} == {("furniture", "k"), ("furniture", "bed")}
    turned = [t for t in labels if object_id(t) == ("furniture", "k")]
    assert all(t.dxf.rotation == 90 for t in turned)
    assert F_FURN in PLAN_SHEET_LAYERS and F_FURN in FLOOR_HEATING_SHEET_LAYERS
    plain, _ = draw_stages(plan, contours, Electrical())
    assert not plain.modelspace().query(f'*[layer=="{F_FURN.name}"]')
