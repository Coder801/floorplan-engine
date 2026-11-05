"""The "Plumbing" sheet: object tags in the model, tables."""

from __future__ import annotations

from collections import Counter

from floorplan_engine.drawing.ids import object_id
from floorplan_engine.drawing.layers import new_document
from floorplan_engine.drawing.plumbing import draw_plumbing, fixtures_table, pipes_table
from floorplan_engine.model.plumbing import Plumbing
from floorplan_engine.model.schema import Plan
from floorplan_engine.plumbing.network import build_network
from floorplan_engine.plumbing.network_model import Network
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_flat

PLUMBING = Plumbing.model_validate(
    {
        "risers": [{"id": "r1", "room": "bath", "at": [150, 150]}],
        "fixtures": [
            {"id": "wc", "room": "bath", "type": "wc", "wall": "w4", "offset": 600},
            {"id": "s", "room": "bath", "type": "sink", "wall": "w1", "offset": 1500},
        ],
        "obstacles": [
            {"id": "tub", "room": "bath", "type": "bath", "rect": [1000, 1500, 1900, 2400]}
        ],
    }
)


def _setup() -> tuple[Plan, Network]:
    plan = make_flat()
    _, contours = validate_plan(plan)
    return plan, build_network(plan, contours, PLUMBING)


def test_every_object_is_tagged() -> None:
    plan, net = _setup()
    doc = new_document()
    msp = doc.modelspace()
    draw_plumbing(msp, plan, PLUMBING, net)
    kinds = Counter(t[0] for e in msp if (t := object_id(e)) is not None)
    assert kinds["pipe"] >= len(net.pipes)
    assert kinds["fixture"] and kinds["riser"] and kinds["obstacle"] and kinds["collector"]


def test_tables() -> None:
    plan, net = _setup()
    fixtures = fixtures_table(plan, PLUMBING, net)
    assert fixtures is not None and len(fixtures.rows) == 2
    assert fixtures.rows[0][0] == "1" and fixtures.rows[1][3] == "Г, Х"
    pipes = pipes_table(plan, net)
    assert pipes is not None and pipes.total is not None
    assert pipes.total[2] == str(len(net.pipes))


def test_bath_drawn_as_fixture_boxes_hatched_not_like_walls() -> None:
    plan, net = _setup()
    doc = new_document()
    msp = doc.modelspace()
    draw_plumbing(msp, plan, PLUMBING, net)
    hatches = [e for e in msp if e.dxftype() == "HATCH" and e.dxf.layer == "P-OBST"]
    assert hatches == []  # the only obstacle is a bath: drawn, no hatch
    symbols = Counter(t for e in msp if e.dxf.layer == "P-SYMB" and (t := object_id(e)))
    assert any(k == "obstacle" for k, _ in symbols)  # the bath is inside the obstacle outline
    assert {i for k, i in symbols if k == "fixture"} == {"wc", "s"}
