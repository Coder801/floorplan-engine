"""Карточки объектов для подсказок просмотра: названия линий по смыслу и данные из модели."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from shtroba.artifact import export_artifact
from shtroba.objects import describe_objects, page_objects, wire_titles
from shtroba.schema import Electrical, Plan
from shtroba.sheets import build_project_document
from shtroba.validate import validate_plan
from shtroba.wiring import Wiring, box_wiring
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
                _pt("s3", "socket", 2500, "QF3"),  # одна точка группы — от щита
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
    assert "QF2: ЩР → К1" in titles  # щит → коробка
    assert "QF2: К1 → Розетка с заземлением, Комната" in titles  # коробка → точка
    assert "QF3: ЩР → Розетка с заземлением, Комната" in titles  # напрямую от щита
    assert not any("wire_" in t for t in titles)


def test_wire_card_has_group_cable_and_lengths() -> None:
    plan, contours, elec, wiring = _model()
    run = next(r for r in wiring.runs if r.target == "s3")
    card = describe_objects(plan, contours, elec, wiring)[f"wire:{run.id}"]
    rows = dict(card.rows)
    assert rows["Автомат (группа)"] == "QF3"
    assert rows["Кабель"] == "3x2.5 — допущение"  # марки в модели нет
    assert rows["Откуда"] == "ЩР" and rows["Трасса"] == "по потолку"
    assert rows["Длина"].startswith(f"{run.length_mm / 1000:.1f}".replace(".", ","))


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
        assert set(page["objects"]) <= drawn  # карточки — только нарисованного
    assert not any(k.startswith("wire:") for k in pages[0]["objects"])  # на плане проводки нет
    assert any(k.startswith("wire:") for k in pages[2]["objects"])


def test_line_chains_select_whole_line() -> None:
    from shtroba.objects import line_chains

    _, _, _, wiring = _model()
    chains = line_chains(wiring)
    via_box = next(r for r in wiring.runs if r.source.startswith("box_"))
    feed = next(r for r in wiring.runs if r.target == via_box.source)
    chain = chains[f"point:{via_box.target}"]
    assert chain == chains[f"wire:{via_box.id}"]  # клик по точке и по её линии — одно
    assert f"wire:{feed.id}" in chain and f"box:{via_box.source}" in chain
    direct = next(r for r in wiring.runs if r.source == "board" and not r.target.startswith("box_"))
    assert chains[f"point:{direct.target}"] == [f"wire:{direct.id}", f"point:{direct.target}"]


def test_line_chains_feed_and_box_include_children() -> None:
    from shtroba.objects import line_chains

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
    from shtroba.objects import line_groups

    _, _, _, wiring = _model()
    groups = line_groups(wiring)
    assert set(groups) == {r.group for r in wiring.runs}
    for r in wiring.runs:
        assert f"wire:{r.id}" in groups[r.group]
        assert not any(f"wire:{r.id}" in keys for g, keys in groups.items() if g != r.group)
    assert all(f"box:{b.id}" in groups[b.group] for b in wiring.boxes)
