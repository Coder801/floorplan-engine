"""Junction box card: the cable in and the cables out, in the order the viewer draws them; the
joints card of a flush box (splice_card)."""

from __future__ import annotations

import json

from floorplan_engine.electrical.anchors import Anchor
from floorplan_engine.electrical.splices import back_box_joints
from floorplan_engine.electrical.wiring import box_wiring
from floorplan_engine.electrical.wiring_model import JunctionBox, Run, Wiring
from floorplan_engine.epd.box_card import box_card, splice_card
from floorplan_engine.epd.objects import describe_objects
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.schema import Electrical, ElectricalPoint, PointType
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan, room_wiring, wall_point

RECT = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]
PATH = (Vec(0, 0), Vec(1000, 0))


def _box(n: int) -> JunctionBox:
    return JunctionBox(f"box_{n}", f"К{n}", "r", "QF1", Anchor(Vec(0, 0), None, None, 0.0))


def _run(rid: str, source: str, target: str, plan_mm: float = 1000.0) -> Run:
    return Run(rid, "QF1", "3x1.5", False, source, target, PATH, plan_mm, 0.0, 0.0, 0.0)


def _point(pid: str, kind: str) -> ElectricalPoint:
    return ElectricalPoint.model_validate(
        {"id": pid, "room": "r", "type": kind, "wall": "w1", "offset": 500, "height": 300,
         "group": "QF1"}
    )  # fmt: skip


def test_box_card_cable_in_and_out_boxes_then_points_by_number() -> None:
    boxes = (_box(1), _box(2), _box(10))
    runs = (
        _run("wire_1", "board", "box_1", 3940.0),  # 3.94 m → 3.9
        _run("wire_2", "box_1", "p_late"),
        _run("wire_3", "box_1", "box_10"),
        _run("wire_4", "box_1", "p_early", 1550.0),
        _run("wire_5", "box_1", "box_2"),
    )
    wiring = Wiring(2700.0, False, boxes, runs)
    points = {"p_late": _point("p_late", "switch"), "p_early": _point("p_early", "socket")}
    numbers = {"p_late": 7, "p_early": 3}
    names = {"board": "ЩР", "box_2": "К2", "box_10": "К10", "p_late": "Вимикач, Коридор"}
    card = box_card(boxes[0], wiring, numbers, points, lambda e: names.get(e, e))
    assert card["label"] == "К1" and card["size"] == "100×100"
    assert card["in"] == {
        "key": "wire:wire_1",
        "from": "ЩР",
        "from_key": "board",
        "group": "QF1",
        "mark": "3x1.5",
        "length_m": 3.9,
    }
    out = card["out"]
    assert isinstance(out, list)
    assert [c["to_key"] for c in out] == [
        "box:box_2",
        "box:box_10",
        "point:p_early",
        "point:p_late",
    ]
    assert [c["kind"] for c in out] == ["box", "box", "point", "point"]
    assert [c["number"] for c in out] == [None, None, 3, 7]
    assert [c["point_type"] for c in out] == [None, None, "socket", PointType.SWITCH.value]
    assert out[3] == {
        "key": "wire:wire_2",
        "to": "Вимикач, Коридор",
        "to_key": "point:p_late",
        "kind": "point",
        "point_type": "switch",
        "number": 7,
        "group": "QF1",
        "mark": "3x1.5",
        "length_m": 1.0,
    }
    assert out[2]["length_m"] == 1.6  # 1.55 m, rounded to 0.1


def test_box_card_fed_by_another_box_and_box_without_feed() -> None:
    boxes = (_box(1), _box(2))
    wiring = Wiring(2700.0, False, boxes, (_run("wire_1", "box_1", "box_2"),))
    card = box_card(boxes[1], wiring, {}, {}, lambda e: {"box_1": "К1"}[e])
    cable_in = card["in"]
    assert isinstance(cable_in, dict)
    assert cable_in["from"] == "К1" and cable_in["from_key"] == "box:box_1"
    assert card["out"] == []
    first = box_card(boxes[0], wiring, {}, {}, lambda e: {"box_2": "К2"}[e])
    assert first["in"] is None


def test_box_object_card_carries_box_in_its_epd_json() -> None:
    """End to end: the box:<id> card of a model has "box" next to its rows and brief."""
    plan = make_plan(RECT, [{"wall": "w2", "type": "door", "offset": 1000, "width": 900}])
    _, contours = validate_plan(plan)
    elec = Electrical.model_validate(
        {
            "points": [
                {"id": "s1", "room": "r", "type": "socket", "wall": "w3", "offset": 500,
                 "height": 300, "group": "QF2"},
                {"id": "s2", "room": "r", "type": "socket", "wall": "w3", "offset": 1500,
                 "height": 300, "group": "QF2"},
            ],
            "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700},
        }
    )  # fmt: skip
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None and wiring.boxes
    cards = describe_objects(plan, contours, elec, wiring)
    b = wiring.boxes[0]
    data = json.loads(json.dumps(cards[f"box:{b.id}"].as_dict(), ensure_ascii=False))
    assert data["rows"] and data["brief"]  # the rows stay
    box = data["box"]
    assert box["label"] == b.label
    assert box["in"]["from"] == "ЩР" and box["in"]["from_key"] == "board"
    assert box["in"]["key"] == f"wire:{next(r.id for r in wiring.runs if r.target == b.id)}"
    out = box["out"]
    assert {c["to_key"] for c in out} == {"point:s1", "point:s2"}
    assert [c["number"] for c in out] == sorted(c["number"] for c in out)
    assert all(c["to"] == "Розетка с заземлением, Комната" for c in out)
    assert all(c["point_type"] == "socket" and c["kind"] == "point" for c in out)
    # other cards have no "box"
    assert "box" not in cards["point:s1"].as_dict()


def _loop_sockets() -> list[dict[str, object]]:
    return [wall_point(f"s{k}", "socket", 600 + 1000 * k, 300, "QF2") for k in range(3)]


def test_splice_card_cables_and_joints_of_a_pass_socket() -> None:
    """A pass socket of a loop (decision 2026-11-25): the method, the deep box, the cable in and
    out as in the box card, one device, and L, N, PE each joining 3 wires (in, out, tap) with a
    221-413; with crimps — one sleeve per conductor and no clamps."""
    wiring, elec = room_wiring(_loop_sockets(), distribution="loop")
    joints = back_box_joints(wiring, elec)
    pid, fb = next(iter(joints.items()))
    points = {p.id: p for p in elec.points}
    numbers = {p.id: k for k, p in enumerate(elec.points, 1)}
    card = splice_card(fb, "wago", wiring, numbers, points, lambda e: f"name {e}")
    feed = next(r for r in wiring.runs if r.target == pid)
    out = next(r for r in wiring.runs if r.source == pid)
    assert card["method"] == "wago" and card["deep_mm"] == 60 and card["devices"] == 1
    assert card["in"] == {
        "key": f"wire:{feed.id}",
        "from": f"name {feed.source}",
        "from_key": "board" if feed.source == "board" else f"point:{feed.source}",
        "group": "QF2",
        "mark": feed.mark,
        "length_m": round(feed.length_mm / 1000, 1),
    }
    assert [o["key"] for o in card["out"]] == [f"wire:{out.id}"]  # type: ignore[attr-defined]
    assert card["out"][0]["to_key"] == f"point:{out.target}"  # type: ignore[index]
    assert card["joints"] == [
        {"conductor": c, "wires": 3, "out": [f"wire:{out.id}"], "taps": 1, "clamps": ["413"],
         "sleeves": 0}
        for c in ("L", "N", "PE")
    ]  # fmt: skip
    crimp = splice_card(fb, "crimp", wiring, numbers, points, str)
    assert all(j["clamps"] == [] and j["sleeves"] == 1 for j in crimp["joints"])  # type: ignore[attr-defined]


def test_point_card_carries_splice_and_its_row() -> None:
    """End to end: the point:<id> card of a joined flush box has the row "Соединение" and the
    splice key, method from describe_objects (the studio setting); a point without a joint —
    neither."""
    wiring, elec = room_wiring(_loop_sockets(), distribution="loop")
    plan = make_plan(RECT, [{"wall": "w2", "type": "door", "offset": 1000, "width": 900}])
    _, contours = validate_plan(plan)
    joints = back_box_joints(wiring, elec)
    cards = describe_objects(plan, contours, elec, wiring, splice="crimp")
    for p in elec.points:
        data = json.loads(json.dumps(cards[f"point:{p.id}"].as_dict(), ensure_ascii=False))
        rows = dict(data["rows"])
        if p.id in joints:
            assert data["splice"]["method"] == "crimp"
            assert rows["Соединение"] == "гильзы ×3, глуб. ≥60"
        else:
            assert "splice" not in data and "Соединение" not in rows
