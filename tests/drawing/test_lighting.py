"""План освещения (lighting.py): что чем включается — из controls или допущением по группе,
помещению и подписи выключателя; таблица «Выключатели»; проверка controls."""

from __future__ import annotations

import pytest

from floorplan_engine.drawing.lighting import chain, switch_links, switch_rows
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.schema import Electrical
from floorplan_engine.validation.electrical import validate_electrical
from floorplan_engine.validation.issues import parse_model
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan

WALLS = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]
SW = {"room": "r", "wall": "w1", "height": 900, "group": "QF1"}
CEIL = {"room": "r", "type": "downlight", "group": "QF1"}


def _elec(points: list[dict[str, object]]) -> Electrical:
    elec, issues = parse_model(Electrical, {"points": points}, "e.yaml")
    assert elec is not None, issues
    return elec


def _links(elec: Electrical) -> dict[str, tuple[tuple[str, ...], bool]]:
    return {lk.switch: (lk.targets, lk.assumed) for lk in switch_links(elec)}


def test_controls_from_source_win() -> None:
    elec = _elec(
        [
            {"id": "s1", "type": "switch", "offset": 500, "controls": ["l2"], **SW},
            {"id": "l1", "ceiling": [1000, 1000], **CEIL},
            {"id": "l2", "ceiling": [2000, 1000], **CEIL},
        ]
    )
    assert _links(elec) == {"s1": (("l2",), False)}


def test_note_hints_and_rest() -> None:
    elec = _elec(
        [
            {"id": "s_bra", "type": "switch", "offset": 500, "note": "бра", **SW},
            {"id": "s_main", "type": "switch", "offset": 800, **SW},
            {"id": "s_led", "type": "switch", "offset": 1100, "note": "підсвітка кухні", **SW},
            {"id": "sc", "type": "sconce", "room": "r", "wall": "w2", "offset": 900,
             "height": 1500, "group": "QF1"},
            {"id": "l1", "ceiling": [1000, 1000], **CEIL},
            {"id": "led", "type": "led_output", "room": "r", "wall": "w3", "offset": 500,
             "height": 2200, "group": "QF1", "note": "підсвітка кухні"},
            # Свет другой группы — не связан
            {"id": "other", "ceiling": [2000, 2000], "room": "r", "type": "downlight",
             "group": "QF2"},
        ]
    )  # fmt: skip
    links = _links(elec)
    assert links["s_bra"] == (("sc",), True)
    assert links["s_led"] == (("led",), True)
    assert links["s_main"] == (("l1",), True)  # то, что не разобрали подсказанные


def test_no_group_no_link() -> None:
    sw = {k: v for k, v in SW.items() if k != "group"}
    elec = _elec(
        [
            {"id": "s1", "type": "switch", "offset": 500, **sw},
            {"id": "l1", "ceiling": [1000, 1000], **CEIL},
        ]
    )
    assert switch_links(elec) == []  # связь не выдумывается


def test_switch_rows_mark_assumed() -> None:
    plan = make_plan(WALLS)
    elec = _elec(
        [
            {"id": "s1", "type": "switch", "offset": 500, **SW},
            {"id": "l1", "ceiling": [1000, 1000], **CEIL},
            {"id": "l2", "ceiling": [2000, 1000], **CEIL},
        ]
    )
    (row,) = switch_rows(plan, elec)
    assert row.controls.endswith("*") and row.group == "QF1"
    assert row.point_ids == ("s1", "l1", "l2")


def test_controls_validation() -> None:
    with pytest.raises(AssertionError):  # controls — только у выключателя
        _elec([{"id": "x", "type": "socket", "offset": 1, "controls": ["l1"], **SW}])
    plan = make_plan(WALLS)
    _, contours = validate_plan(plan)
    elec = _elec(
        [
            {"id": "s1", "type": "switch", "offset": 500, "controls": ["nope"], **SW},
            {"id": "l1", "ceiling": [1000, 1000], **CEIL},
        ]
    )
    issues = validate_electrical(elec, plan, contours)
    assert [i.path for i in issues] == ["points[0].controls[0]"]


def test_chain_goes_to_nearest() -> None:
    order = chain(Vec(0, 0), [("far", Vec(10, 0)), ("near", Vec(1, 0)), ("mid", Vec(5, 0))])
    assert [k for k, _ in order] == ["near", "mid", "far"]


def test_arc_link_draws_arcs_between_points() -> None:
    """Связь — дуги между соседними точками: выпуклость у всех вершин, кроме последней."""
    from ezdxf.entities.lwpolyline import LWPolyline
    from ezdxf.filemanagement import new

    from floorplan_engine.drawing.lighting import LINK_BULGE, arc_link
    from floorplan_engine.model.geometry import Vec

    msp = new().modelspace()
    arc_link(msp, [Vec(0, 0), Vec(1000, 0), Vec(1000, 1000)], {"layer": "E-LINK"})
    (pl,) = msp.query("LWPOLYLINE")
    assert isinstance(pl, LWPolyline)
    bulges = [b for *_, b in pl.get_points("xyb")]
    assert bulges == [LINK_BULGE, LINK_BULGE, 0.0]
    assert 0 < LINK_BULGE < 1  # дуга меньше полуокружности
