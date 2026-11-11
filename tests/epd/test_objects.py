"""Object cards for viewer hints: meaningful line names and data from the model."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from floorplan_engine.electrical.wiring import box_wiring
from floorplan_engine.electrical.wiring_model import Wiring
from floorplan_engine.epd.artifact import export_artifact
from floorplan_engine.epd.objects import (
    describe_objects,
    light_chains,
    page_objects,
    plan_areas,
    plan_chains,
    wire_titles,
)
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.sheets.document import build_project_document
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan

RECT = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]


def _pt(pid: str, kind: str, offset: float, group: str, **extra: Any) -> dict[str, Any]:
    return {"id": pid, "room": "r", "type": kind, "wall": "w3", "offset": offset,
            "height": 300, "group": group, **extra}  # fmt: skip


def _model() -> tuple[Plan, Any, Electrical, Wiring]:
    plan = make_plan(RECT, [{"wall": "w2", "type": "door", "offset": 1000, "width": 900}])
    _, contours = validate_plan(plan)
    elec = Electrical.model_validate(
        {
            "points": [
                _pt("s1", "socket", 500, "QF2", count=2, note="у дивана"),
                _pt("s2", "socket", 1500, "QF2"),
                _pt("s3", "socket", 2500, "QF3"),  # a group's single point comes from the panel
            ],
            "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700},
        }
    )
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    return plan, contours, elec, wiring


def test_wire_titles_say_where_from_and_to() -> None:
    plan, _, elec, wiring = _model()
    titles = set(wire_titles(plan, elec, wiring).values())
    assert "QF2: ЩР → К1" in titles  # panel → box
    assert "QF2: К1 → Розетка с заземлением, Комната" in titles  # box → point
    assert "QF3: ЩР → Розетка с заземлением, Комната" in titles  # straight from the panel
    assert not any("wire_" in t for t in titles)


def test_wire_card_has_group_cable_and_lengths() -> None:
    plan, contours, elec, wiring = _model()
    run = next(r for r in wiring.runs if r.target == "s3")
    card = describe_objects(plan, contours, elec, wiring)[f"wire:{run.id}"]
    rows = dict(card.rows)
    assert rows["Автомат (группа)"] == "QF3"
    assert rows["Кабель"] == "3x2.5 — допущение"  # no cable type in the model
    assert rows["Откуда"] == "ЩР" and rows["Трасса"] == "по потолку"
    assert rows["Длина"].startswith(f"{run.length_mm / 1000:.1f}".replace(".", ","))


def test_wire_and_box_brief_cards_say_only_where() -> None:
    plan, contours, elec, wiring = _model()
    cards = describe_objects(plan, contours, elec, wiring)
    run = next(r for r in wiring.runs if r.target == "s3")
    brief = cards[f"wire:{run.id}"].brief
    assert brief is not None and brief.title == "ЩР → Розетка с заземлением, Комната"
    assert [k for k, _ in brief.rows] == ["Откуда", "Куда", "Трасса"]  # no group, cable, length
    box = cards["box:box_1"]
    assert box.brief is not None and box.brief.title == box.title
    assert [k for k, _ in box.brief.rows] == ["Помещение", "Высота"]
    assert box.as_dict()["brief"] == box.brief.as_dict()
    assert "brief" not in cards["point:s1"].as_dict()


def test_socket_card_names_the_block_and_carries_its_scheme() -> None:
    plan, contours, elec, wiring = _model()
    cards = describe_objects(plan, contours, elec, wiring)
    s1 = cards["point:s1"]
    point = next(p for p in elec.points if p.id == "s1")
    assert "2-постовая" in s1.title
    assert (
        s1.block is not None
        and s1.block["posts"] == 2
        and s1.block["y"] == round(point.height or 0)
    )
    assert s1.block["wall"] in cards
    assert s1.as_dict()["block"] == s1.block
    assert "block" not in cards["room:r"].as_dict()


def test_point_box_board_cards() -> None:
    plan, contours, elec, wiring = _model()
    cards = describe_objects(plan, contours, elec, wiring)
    s1 = dict(cards["point:s1"].rows)
    assert s1["Постов"] == "2" and s1["Примечание"] == "у дивана"
    assert s1["Питание"] == "коробка К1, Комната" and s1["Автомат (группа)"] == "QF2"
    box = dict(cards["box:box_1"].rows)
    assert box["Линий"] == "3: 1 от щита, 2 к точкам"
    board = dict(cards["board:board"].rows)
    assert board["Автоматы"] == "QF2, QF3"
    assert dict(cards["room:r"].rows)["Площадь"] == "12,00 м²"
    assert dict(cards["wall:r.w1"].rows)["Длина"] == "3000 мм"


def test_label_card_lists_its_points() -> None:
    plan, contours, elec, wiring = _model()
    cards = describe_objects(plan, contours, elec, wiring)
    out = page_objects({"label:s1,s2", "point:s3", "unknown:x"}, cards, "ru")
    assert set(out) == {"label:s1,s2", "point:s3"}
    rows = out["label:s1,s2"]["rows"]
    assert isinstance(rows, list) and [r[0] for r in rows] == ["s1", "s2"]


def test_epd_pages_carry_only_their_objects(tmp_path: Path) -> None:
    plan, contours, elec, wiring = _model()
    doc = build_project_document(plan, contours, elec)
    path = export_artifact(
        doc, plan, tmp_path / "p.epd", describe_objects(plan, contours, elec, wiring)
    )
    with zipfile.ZipFile(path) as zf:
        pages = [json.loads(zf.read(f"pages/0{k}.json")) for k in (1, 2, 3)]
    for page in pages:
        drawn = {i["o"] for i in page["items"] if "o" in i}
        assert set(page["objects"]) <= drawn  # cards only for what is drawn
    assert not any(k.startswith("wire:") for k in pages[0]["objects"])  # not on the wiring plan
    assert any(k.startswith("wire:") for k in pages[2]["objects"])


def _two_rooms() -> Plan:
    """Rooms a and b share a partition with one door: a door in a, an opening in b."""

    def room(rid: str, x: float, inner: str, opening: dict[str, Any]) -> dict[str, Any]:
        walls = [
            {"id": f"w{k}", "length": 3000, **({"thickness": 100} if f"w{k}" == inner else {})}
            for k in range(1, 5)
        ]
        return {"id": rid, "name": rid, "origin": [x, 0], "walls": walls, "openings": [opening]}

    door = {"id": "a_door", "wall": "w3", "type": "door", "offset": 1000, "width": 800}
    gap = {"id": "b_gap", "wall": "w1", "type": "opening", "offset": 1200, "width": 800}
    return Plan.model_validate(
        {
            "name": "тест",
            "default_wall_thickness": 200,
            "source": "text",
            "rooms": [room("a", 0, "w3", door), room("b", 3100, "w1", gap)],
        }
    )


def test_plan_chains_link_walls_openings_and_dimensions() -> None:
    plan = _two_rooms()
    _, contours = validate_plan(plan)
    chains = plan_chains(plan, contours)
    # A wall: its door, the opening on the other side and the dimensions of both sides
    wall = chains["wall:a.w3"]
    assert {"wall:a.w3", "wall:b.w1", "opening:a_door", "opening:b_gap"} <= set(wall)
    assert {"dimension:a.w3", "dimension:b.w1"} <= set(wall)
    assert chains["dimension:a.w3"] == wall  # a click on the dimension is the same
    assert len(wall) == len(set(wall))
    # An opening: both sides and their dimensions, without the rest of the wall
    assert set(chains["opening:b_gap"]) == {
        "opening:a_door",
        "opening:b_gap",
        "dimension:a.w3",
        "dimension:b.w1",
    }
    # An outer wall has nothing else
    assert chains["wall:a.w1"] == ["wall:a.w1", "dimension:a.w1"]
    # A room: all its walls with their dimensions
    room = chains["room:a"]
    assert {f"dimension:a.w{k}" for k in range(1, 5)} <= set(room)
    assert "dimension:b.w3" not in room


def _pylon_room() -> Plan:
    """A room with a pylon in the corner: the thick wall w1 covers the short top of the pylon w2."""
    walls = [
        {"id": "w1", "length": 1175, "thickness": 590, "turn": 270},
        {"id": "w2", "length": 430, "thickness": 160},
        {"id": "w3", "length": 934, "thickness": 160},
        {"id": "w4", "length": 2109, "thickness": 160},
        {"id": "w5", "length": 2109},
        {"id": "w6", "length": 1679},
    ]
    return Plan.model_validate(
        {
            "name": "тест",
            "default_wall_thickness": 350,
            "source": "text",
            "rooms": [{"id": "r", "name": "r", "origin": [0, 0], "walls": walls}],
        }
    )


def test_wall_covered_by_its_neighbour_selects_with_it() -> None:
    plan = _pylon_room()
    _, contours = validate_plan(plan)
    areas = plan_areas(plan, contours)
    assert "wall:r.w2" not in areas and "wall:r.w1" in areas  # no hatching of its own
    chains = plan_chains(plan, contours)
    # The covering wall carries the dimension of the covered one, and the other way round
    assert "dimension:r.w2" in chains["wall:r.w1"]
    assert chains["dimension:r.w2"] == chains["wall:r.w1"]
    assert "dimension:r.w2" not in chains["wall:r.w5"]


def test_plan_page_gets_wall_areas_in_sheet_mm(tmp_path: Path) -> None:
    plan = _two_rooms()
    _, contours = validate_plan(plan)
    doc = build_project_document(plan, contours)
    areas = {"wall:a.w1": [[(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0)]], "wall:none": []}
    epd = export_artifact(doc, plan, tmp_path / "p.epd", plan_areas=areas)
    with zipfile.ZipFile(epd) as zf:
        page = json.loads(zf.read("pages/01.json"))
    k, tx, ty = page["model"]
    assert list(page["areas"]) == ["wall:a.w1"]  # only what is drawn
    assert page["areas"]["wall:a.w1"][0][1] == [round(k * 1000 + tx, 2), round(ty, 2)]


def test_plan_sheet_gets_only_drawn_chains(tmp_path: Path) -> None:
    plan = _two_rooms()
    _, contours = validate_plan(plan)
    doc = build_project_document(plan, contours)
    chains = {**plan_chains(plan, contours), "wall:a.w1": ["wall:a.w1", "dimension:nowhere"]}
    epd = export_artifact(doc, plan, tmp_path / "p.epd", plan_chains=chains)
    with zipfile.ZipFile(epd) as zf:
        pages = [json.loads(zf.read(n)) for n in zf.namelist() if n.startswith("pages/")]
    page = next(p for p in pages if p.get("stage") == "plan")
    assert page["chains"]["wall:a.w1"] == ["wall:a.w1"]
    # The opening side of the door and the second dimension are not drawn: only what is on the page;
    # the far side of the partition (b.w1) is, by its wall code
    assert page["chains"]["wall:a.w3"] == [
        "wall:a.w3",
        "dimension:a.w3",
        "wall:b.w1",
        "opening:a_door",
    ]
    assert all("chains" not in p for p in pages if p.get("stage") != "plan")


def test_line_chains_select_whole_line() -> None:
    from floorplan_engine.epd.objects import line_chains

    _, _, _, wiring = _model()
    chains = line_chains(wiring)
    via_box = next(r for r in wiring.runs if r.source.startswith("box_"))
    feed = next(r for r in wiring.runs if r.target == via_box.source)
    chain = chains[f"point:{via_box.target}"]
    assert chain == chains[f"wire:{via_box.id}"]  # a click on a point and on its line is the same
    assert f"wire:{feed.id}" in chain and f"box:{via_box.source}" in chain
    direct = next(r for r in wiring.runs if r.source == "board" and not r.target.startswith("box_"))
    assert chains[f"point:{direct.target}"] == [f"wire:{direct.id}", f"point:{direct.target}"]


def test_line_chains_daisy_chain_is_one_line() -> None:
    from floorplan_engine.electrical.wiring_model import Run, Wiring
    from floorplan_engine.epd.objects import line_chains
    from floorplan_engine.model.geometry import Vec

    def run(rid: str, source: str, target: str) -> Run:
        return Run(rid, "QF1", "3x2.5", False, source, target, (Vec(0, 0), Vec(1, 0)), 1, 0, 0, 0)

    wiring = Wiring(
        2700, False, (), (run("w1", "board", "a"), run("w2", "a", "b"), run("w3", "b", "c")),
        (), (), (), None, frozenset(), (),
    )  # fmt: skip
    chains = line_chains(wiring)
    whole = {"wire:w1", "wire:w2", "wire:w3", "point:a", "point:b", "point:c"}
    assert all(set(chains[key]) == whole for key in whole)


def test_line_chains_feed_and_box_include_children() -> None:
    from floorplan_engine.epd.objects import line_chains

    _, _, _, wiring = _model()
    chains = line_chains(wiring)
    box = wiring.boxes[0]
    feed = next(r for r in wiring.runs if r.target == box.id)
    kids = [r for r in wiring.runs if r.source == box.id]
    assert kids
    for chain in (chains[f"wire:{feed.id}"], chains[f"box:{box.id}"]):
        assert f"wire:{feed.id}" in chain and f"box:{box.id}" in chain
        assert all(f"wire:{k.id}" in chain and f"point:{k.target}" in chain for k in kids)


def test_line_groups_hold_group_lines_boxes_points() -> None:
    from floorplan_engine.epd.objects import line_groups

    _, _, _, wiring = _model()
    groups = line_groups(wiring)
    assert set(groups) == {r.group for r in wiring.runs}
    for r in wiring.runs:
        assert f"wire:{r.id}" in groups[r.group]
        assert not any(f"wire:{r.id}" in keys for g, keys in groups.items() if g != r.group)
    assert all(f"box:{b.id}" in groups[b.group] for b in wiring.boxes)


def test_light_chains_bundle_switches_that_share_a_light() -> None:
    def ceiling(pid: str, x: float) -> dict[str, Any]:
        return {"id": pid, "room": "r", "type": "downlight", "ceiling": [x, 1500], "group": "QF1"}

    elec = Electrical.model_validate(
        {
            "points": [
                _pt("sw1", "pass_switch", 500, "QF1", height=900, controls=["d1", "d2"]),
                _pt("sw2", "pass_switch", 2500, "QF1", height=900, controls=["d1", "d2"]),
                _pt("sw3", "switch", 1500, "QF1", height=900, controls=["d3"]),
                ceiling("d1", 800),
                ceiling("d2", 1600),
                ceiling("d3", 2400),
            ],
        }
    )
    chains = light_chains(elec)
    both = chains["point:sw1"]
    assert both == [
        "point:sw1", "point:sw2", "switch_link:sw1", "switch_link:sw2",
        "light_set:d1,d2", "point:d1", "point:d2",
    ]  # fmt: skip
    assert all(chains[k] == both for k in both)  # a click on any of them shows all of it
    assert chains["switch_link:sw3"] == ["point:sw3", "switch_link:sw3", "point:d3"]
