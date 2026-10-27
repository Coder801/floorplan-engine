"""Проводка через коробки: топология, длины, допущения."""

from __future__ import annotations

import itertools
import math
from typing import Any

import pytest
from ezdxf import bbox
from shapely.geometry import Point, Polygon
from shapely.geometry import box as shapely_box

from floorplan_engine.draw_wiring import (
    bundles,
    draw_wiring,
    fillet,
    lanes,
    offset_path,
    segments,
)
from floorplan_engine.geometry import Vec
from floorplan_engine.layers import W_TEXT, new_document
from floorplan_engine.schema import Electrical, Plan
from floorplan_engine.specification import specification
from floorplan_engine.validate import validate_plan
from floorplan_engine.wiring import (
    BOX_ABOVE_FLOOR,
    BOX_BELOW_CEILING,
    BOX_CLEARANCE,
    CHASE_NARROW,
    END_ALLOWANCE,
    HOLE_CABLES,
    box_wiring,
    section,
)
from tests.conftest import make_plan

RECT = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]
DOOR = {"wall": "w2", "type": "door", "offset": 1000, "width": 900}


def _wall(
    pid: str, kind: str, wall: str, offset: float, height: float, group: str
) -> dict[str, Any]:
    return {
        "id": pid,
        "room": "r",
        "type": kind,
        "wall": wall,
        "offset": offset,
        "height": height,
        "group": group,
    }


def _elec(cables: list[dict[str, Any]] | None = None) -> Electrical:
    return Electrical.model_validate(
        {
            "points": [
                {
                    "id": "l1",
                    "room": "r",
                    "type": "downlight",
                    "ceiling": [1000, 1500],
                    "group": "QF1",
                },
                {
                    "id": "l2",
                    "room": "r",
                    "type": "downlight",
                    "ceiling": [3000, 1500],
                    "group": "QF1",
                },
                _wall("k1", "switch", "w1", 2500, 900, "QF1"),
                _wall("s1", "socket", "w4", 1000, 300, "QF2"),  # одна точка группы — от щита
                _wall("s2", "socket", "w3", 500, 300, "QF3"),
                _wall("s3", "socket", "w3", 2500, 300, "QF3"),
                {
                    "id": "d1",
                    "room": "r",
                    "type": "data",
                    "wall": "w4",
                    "offset": 3000,
                    "height": 300,
                },  # без группы — не в расчёте
            ],
            "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700},
            "cables": cables or [],
        }
    )


def _wiring(plan: Plan, elec: Electrical) -> Any:
    issues, contours = validate_plan(plan)
    assert not issues
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    return wiring


def test_topology_board_box_point_only() -> None:
    w = _wiring(make_plan(RECT, [DOOR]), _elec())
    boxes = {b.id: b for b in w.boxes}
    assert sorted(b.group for b in w.boxes) == ["QF1", "QF3"]  # QF2 — одна точка, без коробки
    for r in w.runs:
        assert r.source == "board" or r.source in boxes  # от потребителя кабель не идёт
        if r.target in boxes:
            assert r.source == "board"  # к коробке — только от щита
    targets = {r.target: r.source for r in w.runs}
    assert targets["s1"] == "board"
    assert {targets["l1"], targets["l2"], targets["k1"]} == {"box_1"}
    assert w.skipped == ("d1",)


def test_run_length_parts() -> None:
    w = _wiring(make_plan(RECT, [DOOR]), _elec())
    s2 = next(r for r in w.runs if r.target == "s2")
    assert s2.vertical_mm == pytest.approx(BOX_BELOW_CEILING + 2700 - 300)
    assert s2.ends_mm == 2 * END_ALLOWANCE
    plan_mm = sum(abs(b.x - a.x) + abs(b.y - a.y) for a, b in itertools.pairwise(s2.path))
    assert s2.plan_mm == pytest.approx(plan_mm)
    # Трасса — только под прямыми углами
    assert all(
        abs(b.x - a.x) < 1e-6 or abs(b.y - a.y) < 1e-6 for a, b in itertools.pairwise(s2.path)
    )
    l1 = next(r for r in w.runs if r.target == "l1")
    assert l1.vertical_mm == pytest.approx(BOX_BELOW_CEILING)  # потолочная точка — без спуска


def test_ceiling_height_default_is_assumption() -> None:
    w = _wiring(make_plan(RECT, [DOOR]), _elec())
    assert w.ceiling_height == 2700 and w.height_assumed
    data = make_plan(RECT, [DOOR]).model_dump(exclude={"ceiling_height"})
    plan = Plan.model_validate({**data, "ceiling_height": 3000})
    w2 = _wiring(plan, _elec())
    assert not w2.height_assumed
    s2 = next(r for r in w2.runs if r.target == "s2")
    assert s2.vertical_mm == pytest.approx(BOX_BELOW_CEILING + 3000 - 300)


def test_mark_from_model_or_assumed() -> None:
    cable = {"id": "c1", "from": "board", "to": ["s1"], "group": "QF2", "cable": "3x4"}
    w = _wiring(make_plan(RECT, [DOOR]), _elec([cable]))
    marks = {r.group: (r.mark, r.mark_assumed) for r in w.runs}
    assert marks["QF2"] == ("3x4", False)
    assert marks["QF1"] == ("3x1.5", True) and marks["QF3"] == ("3x2.5", True)


def test_box_not_in_doorway() -> None:
    w = _wiring(make_plan(RECT, [DOOR]), _elec())
    for b in w.boxes:
        a = b.anchor
        # Коробка на верхней стене (w2, y = 3000) не попадает в дверь 1000…1900 с отступом
        if abs(a.pos.y - 3000) < 1e-6:
            assert not (1000 - BOX_CLEARANCE < a.pos.x < 1900 + BOX_CLEARANCE)


def test_no_board_no_wiring() -> None:
    plan = make_plan(RECT)
    _, contours = validate_plan(plan)
    elec = Electrical.model_validate({"points": [_wall("s1", "socket", "w1", 500, 300, "QF1")]})
    assert box_wiring(plan, contours, elec) is None


def _two_rooms_with_door() -> Plan:
    """Комнаты a и b 3000 × 3000 через перегородку 100 с дверью 800 (в a — дверь, в b — проём)."""

    def room(rid: str, x: float, inner: str, opening: dict[str, Any]) -> dict[str, Any]:
        walls = [
            {"id": f"w{k}", "length": 3000, **({"thickness": 100} if f"w{k}" == inner else {})}
            for k in range(1, 5)
        ]
        return {"id": rid, "name": rid, "origin": [x, 0], "walls": walls, "openings": [opening]}

    door = {"id": "a_door_1", "wall": "w3", "type": "door", "offset": 1000, "width": 800}
    gap = {"id": "b_opening_1", "wall": "w1", "type": "opening", "offset": 1200, "width": 800}
    return Plan.model_validate(
        {
            "name": "тест",
            "default_wall_thickness": 200,
            "source": "text",
            "rooms": [room("a", 0, "w3", door), room("b", 3100, "w1", gap)],
        }
    )


def test_cable_to_other_room_goes_through_door() -> None:
    plan = _two_rooms_with_door()
    elec = Electrical.model_validate(
        {
            "points": [
                {"id": "l1", "room": "b", "type": "light", "ceiling": [1500, 1500], "group": "QF1"},
                {
                    "id": "s1",
                    "room": "b",
                    "type": "socket",
                    "wall": "w3",
                    "offset": 2500,
                    "height": 300,
                    "group": "QF2",
                },
            ],
            "board": {"room": "a", "wall": "w1", "offset": 500, "height": 1700},
        }
    )
    w = _wiring(plan, elec)
    # Один светильник — всё равно через коробку; одна розетка — от щита
    assert [b.group for b in w.boxes] == ["QF1"] and w.boxes[0].room == "b"
    assert {r.target: r.source for r in w.runs}["s1"] == "board"
    for run in w.runs:
        for a, b in itertools.pairwise(run.path):
            # Пересечение перегородки (x 3000…3100) — только в проёме: y 1200…2000
            if min(a.x, b.x) < 3000 and max(a.x, b.x) > 3100:
                assert 1200 <= a.y <= 2000 and a.y == b.y
    # Кабели коробки не выходят из её комнаты
    for run in w.runs:
        if run.source == w.boxes[0].id:
            assert all(p.x >= 3100 for p in run.path)


def test_fillet_rounds_right_angles() -> None:
    path = [Vec(0, 0), Vec(1000, 0), Vec(1000, 1000), Vec(2000, 1000)]
    pts = fillet(path, 50)
    # Каждый поворот — две вершины касания, дуга 90° (bulge = tan 22,5°) со знаком поворота
    assert len(pts) == 6
    assert pts[1] == pytest.approx((950, 0, math.tan(math.radians(22.5))))  # влево
    assert pts[2] == pytest.approx((1000, 50, 0))
    assert pts[3] == pytest.approx((1000, 950, -math.tan(math.radians(22.5))))  # вправо
    # Короткий участок отдаёт дуге не больше половины
    short = fillet([Vec(0, 0), Vec(40, 0), Vec(40, 1000)], 50)
    assert short[1][0] == pytest.approx(20)
    # Прямая — без лишних вершин
    assert fillet([Vec(0, 0), Vec(500, 0), Vec(1000, 0)], 50) == [(0, 0, 0), (1000, 0, 0)]


def test_wiring_sheet_labels_lengths_and_drops() -> None:
    plan = make_plan(RECT, [DOOR])
    issues, contours = validate_plan(plan)
    assert not issues
    elec = _elec()
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    doc = new_document()
    msp = doc.modelspace()
    draw_wiring(msp, wiring, elec)
    texts = [t.dxf.text for t in msp.query("TEXT")]
    s2 = next(r for r in wiring.runs if r.target == "s2")
    assert f"↓h{s2.rise_end_mm / 1000:.1f}".replace(".", ",") in texts  # спуск к розетке
    assert any(t.startswith("↑") for t in texts)  # подъём от щита
    # Подписи длин — по отрезкам пучков: длина и число кабелей, если их больше одного
    segs = segments([r.path for r in wiring.runs])
    expected = {_length_label(b.length, len(b.runs)) for b in bundles(segs, lanes(segs, 1.0, 3.0))}
    numbers = [t for t in texts if t.startswith("L")]
    assert numbers and set(numbers) <= expected
    assert any("×" in t for t in numbers)  # у коробки кабели идут пучком
    # Подписи не пересекаются друг с другом
    boxes = []
    for t in msp.query("TEXT"):
        if t.dxf.layer != W_TEXT.name:
            continue
        ext = bbox.extents([t])
        boxes.append(shapely_box(ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y))
    for a, b in itertools.combinations(boxes, 2):
        assert a.intersection(b).area < 1e-6


def _length_label(mm: float, n: int) -> str:
    return "L" + f"{mm / 1000:.1f}".replace(".", ",") + (f" ×{n}" if n > 1 else "")


def test_lanes_separate_overlapping_cables() -> None:
    paths = [
        [Vec(0, 0), Vec(3000, 0)],
        [Vec(1000, 0), Vec(4000, 0)],  # перекрывает первую на 1000..3000
        [Vec(3000, 0), Vec(5000, 0)],  # касается первой концом — может лечь в её полосу
    ]
    segs = segments(paths)
    off = lanes(segs, 30.0, 90.0)
    assert off[(0, 0)] != off[(1, 0)]
    assert off[(2, 0)] == off[(0, 0)]
    assert sorted({off[(0, 0)], off[(1, 0)]}) == [-15.0, 15.0]  # полосы симметрично линии
    shared = [(b.lo, b.hi, b.runs) for b in bundles(segs, off)]
    assert (1000, 3000, (0, 1)) in shared and (0, 1000, (0,)) in shared


def test_offset_path_moves_corner_to_both_lanes() -> None:
    path = [Vec(0, 0), Vec(1000, 0), Vec(1000, 1000)]
    out = offset_path(path, [30.0, -20.0])  # горизонталь вверх на 30, вертикаль влево на 20
    assert out == [Vec(0, 30), Vec(980, 30), Vec(980, 1000)]


def test_lanes_only_where_cables_overlap_and_band_is_limited() -> None:
    far = [[Vec(0, 0), Vec(1000, 0)], [Vec(500, 0), Vec(1500, 0)], [Vec(5000, 0), Vec(6000, 0)]]
    off = lanes(segments(far), 30.0, 90.0)
    assert off[(2, 0)] == 0.0  # одиночный участок на той же линии — без сдвига
    many = [[Vec(0, 0), Vec(1000 + k, 0)] for k in range(11)]
    shifts = sorted(lanes(segments(many), 30.0, 90.0).values())
    assert shifts[-1] - shifts[0] == pytest.approx(90.0)  # 11 кабелей — в полосе 90, не 300


def _point(pid: str, offset: float, height: float, group: str = "QF5") -> dict[str, Any]:
    return _wall(pid, "socket", "w3", offset, height, group)


def test_wall_chases_share_nearby_drops_up_to_four() -> None:
    plan = make_plan(RECT, [DOOR])
    pts = [
        _point("a", 500, 300),
        _point("b", 600, 900),  # 100 мм от a — в ту же штробу
        _point("c", 1200, 300),  # дальше 150 — своя штроба
        *(_point(f"d{k}", 2000 + 20 * k, 300) for k in range(5)),  # пять рядом — 4 + 1
    ]
    elec = Electrical.model_validate(
        {"points": pts, "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700}}
    )
    w = _wiring(plan, elec)
    points = [c for c in w.chases if c.kind == "point"]
    shared = next(c for c in points if "a" in c.targets)
    assert shared.targets == ("a", "b") and shared.cables == 2
    assert shared.length_mm == pytest.approx(2700 - 300)  # до самой низкой точки
    assert next(c for c in points if "c" in c.targets).cables == 1
    near = sorted(c.cables for c in points if any(t.startswith("d") for t in c.targets))
    assert near == [1, 4]
    # Над коробкой на стене — по штробе на каждые 4 кабеля, длина — от потолка до коробки;
    # у коробки на потолке штробы нет
    box = [c for c in w.chases if c.kind == "box"]
    on_wall = {b.id for b in w.boxes if not b.on_ceiling}
    n_box = sum(1 for r in w.runs if r.source in on_wall or r.target in on_wall)
    assert sum(c.cables for c in box) == n_box
    assert all(c.length_mm == BOX_BELOW_CEILING for c in box)
    assert w.chase_mm == pytest.approx(sum(c.length_mm for c in w.chases))


def test_outlet_is_power_point_with_own_spec_line() -> None:
    elec = Electrical.model_validate(
        {
            "points": [
                {**_wall("ac", "outlet", "w3", 500, 2500, "QF7"), "note": "кондиціонер"},
                _wall("led", "led_output", "w3", 1500, 2200, "QF1"),
            ],
            "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700},
        }
    )
    w = _wiring(make_plan(RECT, [DOOR]), elec)
    ac = next(r for r in w.runs if r.target == "ac")
    assert ac.source == "board" and ac.mark == "3x2.5"  # силовой, не свет
    names = {i.name: i.quantity for i in specification(elec, "ru")}
    assert names["Вывод кабеля к технике"] == 1 and names["Вывод под подсветку"] == 1


def test_board_tail_reaches_floor() -> None:
    w = _wiring(make_plan(RECT, [DOOR]), _elec())
    s1 = next(r for r in w.runs if r.target == "s1")  # от щита
    assert s1.ends_mm == pytest.approx(END_ALLOWANCE + 1700)  # в щите — до пола
    l1 = next(r for r in w.runs if r.target == "l1")  # от коробки
    assert l1.ends_mm == 2 * END_ALLOWANCE


def test_floor_route_rises_from_floor() -> None:
    cable = {"id": "c3", "from": "board", "to": ["s2", "s3"], "group": "QF3", "cable": "3x2.5"}
    w = _wiring(make_plan(RECT, [DOOR]), _elec([{**cable, "route": "floor"}]))
    box = next(b for b in w.boxes if b.group == "QF3")
    assert box.route == "floor" and box.rise_mm == BOX_ABOVE_FLOOR
    feed = next(r for r in w.runs if r.target == box.id)
    assert feed.route == "floor"
    assert feed.vertical_mm == pytest.approx(1700 + BOX_ABOVE_FLOOR)  # из щита вниз, к коробке
    s2 = next(r for r in w.runs if r.target == "s2")
    assert s2.vertical_mm == pytest.approx(BOX_ABOVE_FLOOR + 300)  # от пола до розетки
    floor = [c for c in w.chases if c.route == "floor"]
    assert floor and all(c.length_mm < 2000 for c in floor)
    # Подъёмы от пола и спуски с потолка в одну штробу не попадают
    assert all(c.route == "ceiling" for c in w.chases if c.targets and "l1" in c.targets)


def test_heavy_lines_and_outlets_go_without_boxes() -> None:
    assert section("3x6") == 6 and section("5х2,5") == 2.5 and section("UTP") == 0
    pts = [
        _wall("h1", "socket", "w3", 500, 900, "QF9"),
        _wall("h2", "socket", "w3", 2500, 900, "QF9"),
        _wall("ac", "outlet", "w4", 500, 2500, "QF7"),
        _wall("tw", "outlet", "w4", 2500, 900, "QF7"),
        _wall("r1", "socket", "w1", 1500, 300, "QF4"),
        _wall("r2", "socket", "w1", 2500, 300, "QF4"),
    ]
    cables = [
        {"id": "c9", "from": "board", "to": ["h1", "h2"], "group": "QF9", "cable": "3x6"},
        {"id": "c4", "from": "board", "to": ["r1", "r2"], "group": "QF4", "cable": "3x2.5"},
    ]
    elec = Electrical.model_validate(
        {
            "points": pts,
            "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700},
            "cables": cables,
        }
    )
    w = _wiring(make_plan(RECT, [DOOR]), elec)
    assert [b.group for b in w.boxes] == ["QF4"]  # 3x6 и выводы к технике — без коробок
    src = {r.target: r.source for r in w.runs}
    assert all(src[p] == "board" for p in ("h1", "h2", "ac", "tw"))
    # direct: false в модели — снова через коробку
    forced = [{**cables[0], "direct": False}, cables[1]]
    w2 = _wiring(make_plan(RECT, [DOOR]), elec.model_copy(update={"cables": []}))
    assert "QF9" in {b.group for b in w2.boxes}  # без кабеля марка 3x2.5 — через коробку
    assert "QF7" not in {b.group for b in w2.boxes}  # выводы к технике — всё равно без коробок
    w3 = _wiring(
        make_plan(RECT, [DOOR]),
        Electrical.model_validate({**elec.model_dump(by_alias=True), "cables": forced}),
    )
    assert "QF9" in {b.group for b in w3.boxes}


def test_low_voltage_in_own_chases() -> None:
    pts = [
        _wall("s1", "socket", "w3", 500, 300, "QF5"),
        _wall("s2", "socket", "w3", 1500, 300, "QF5"),
        _wall("lan", "data", "w3", 560, 300, "LAN"),  # 60 мм от розетки
    ]
    elec = Electrical.model_validate(
        {"points": pts, "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700}}
    )
    w = _wiring(make_plan(RECT, [DOOR]), elec)
    lan = next(r for r in w.runs if r.target == "lan")
    assert lan.circuit == "low" and lan.source == "board" and lan.mark == "UTP cat.6"
    chases = [c for c in w.chases if c.kind == "point"]
    assert all(not ({"s1", "lan"} <= set(c.targets)) for c in chases)  # рядом, но раздельно
    board = [c for c in w.chases if c.kind == "board"]
    assert {c.circuit for c in board} == {"power", "low"}


def test_chase_width_by_cables() -> None:
    plan = make_plan(RECT, [DOOR])
    pts = [_point(f"d{k}", 2000 + 20 * k, 300) for k in range(4)]
    elec = Electrical.model_validate(
        {"points": pts, "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700}}
    )
    w = _wiring(plan, elec)
    shared = next(c for c in w.chases if c.kind == "point")
    assert shared.cables == 4 and shared.wide and CHASE_NARROW == 2
    assert w.chase_length(wide=True) + w.chase_length(wide=False) == pytest.approx(w.chase_mm)


def test_wall_holes_over_doors_for_ceiling_runs() -> None:
    plan = _two_rooms_with_door()
    pts = [
        {
            "id": f"s{k}",
            "room": "b",
            "type": "socket",
            "wall": "w3",
            "offset": 300 + 500 * k,
            "height": 300,
            "group": f"QF{k + 1}",
        }
        for k in range(5)
    ]
    board = {"room": "a", "wall": "w1", "offset": 500, "height": 1700}
    w = _wiring(plan, Electrical.model_validate({"points": pts, "board": board}))
    # Дверь в a и проём в b на том же месте — один проход, id двери
    assert {h.passage for h in w.holes} == {"a_door_1"}
    assert sorted(h.cables for h in w.holes) == [1, HOLE_CABLES]  # 5 кабелей: 4 + 1
    cables = [
        {"id": f"c{k}", "from": "board", "to": [f"s{k}"], "group": f"QF{k + 1}", "cable": "3x2.5"}
        for k in range(5)
    ]
    floor = [{**c, "route": "floor"} for c in cables]
    w2 = _wiring(plan, Electrical.model_validate({"points": pts, "board": board, "cables": floor}))
    assert w2.holes == ()  # по полу — под проёмом, без сверления


def test_boxes_in_wet_rooms_marked() -> None:
    data = make_plan(RECT, [DOOR]).model_dump()
    data["rooms"][0]["wet"] = True
    w = _wiring(Plan.model_validate(data), _elec())
    assert w.boxes and all(b.wet for b in w.boxes)


def test_lanes_keep_clear_of_walls() -> None:
    from shapely.geometry import box

    from floorplan_engine.draw_wiring import clearance

    many = [[Vec(0, 50), Vec(1000 + k, 50)] for k in range(5)]  # 5 кабелей в 50 мм от стены y=0
    room = clearance(box(-100, 0, 2000, 3000), 10.0)
    shifts = sorted(lanes(segments(many), 30.0, 300.0, room).values())
    assert shifts[-1] - shifts[0] == pytest.approx(120.0)  # шаг не сжат
    assert 50 + shifts[0] == pytest.approx(10.0)  # пучок сдвинут от стены, а не на неё
    tight = clearance(box(-100, 0, 2000, 100), 10.0)  # коридор 100 мм: места 80
    shifts = sorted(lanes(segments(many), 30.0, 300.0, tight).values())
    assert 50 + shifts[0] == pytest.approx(10.0) and 50 + shifts[-1] == pytest.approx(90.0)


def test_fan_angle_ignores_row_on_box_wall() -> None:
    from floorplan_engine.draw_electrical import Anchor
    from floorplan_engine.wiring import fan_angle

    box = Anchor(Vec(1000, 0), Vec(0, 1), Vec(1, 0), 10.0)  # на нижней стене, в комнату — вверх
    row = [Anchor(Vec(x, 0), Vec(0, 1), Vec(1, 0), 10.0) for x in (300, 1800)]
    assert fan_angle(box, row) == 0.0  # ряд розеток под коробкой — коробка остаётся на стене
    spread = [*row, Anchor(Vec(0, 2000), Vec(1, 0), Vec(0, 1), 10.0)]
    assert fan_angle(box, spread) >= 90.0


def test_fanned_box_goes_to_ceiling_inside_room() -> None:
    from floorplan_engine.routing import CLEARANCE

    plan = make_plan(RECT, [DOOR])
    pts = [
        _wall("l1", "light", "w1", 1500, 2400, "QF1"),
        _wall("s1", "socket", "w2", 2000, 300, "QF1"),
        _wall("s2", "socket", "w3", 1500, 300, "QF1"),
    ]
    elec = Electrical.model_validate(
        {"points": pts, "board": {"room": "r", "wall": "w4", "offset": 500, "height": 1700}}
    )
    w = _wiring(plan, elec)
    (box,) = w.boxes
    assert box.on_ceiling and box.rise_mm == 0.0
    assert not [c for c in w.chases if c.kind == "box"]
    room = Polygon([(0, 0), (0, 3000), (4000, 3000), (4000, 0)])
    p = box.anchor.node
    assert room.exterior.distance(Point(p.x, p.y)) >= CLEARANCE - 1e-6


def test_box_size_by_lines() -> None:
    from floorplan_engine.wiring import box_size

    assert [box_size(n) for n in (2, 3, 4, 6, 7, 8, 9)] == [
        "80", "80", "100x100", "100x100", "150x110", "150x110", "190x140",
    ]  # fmt: skip


def test_split_points_by_zones() -> None:
    from floorplan_engine.wiring import split_points

    left = [Vec(100 + 10 * k, 500) for k in range(6)]
    right = [Vec(5000 + 10 * k, 500) for k in range(6)]
    zones = split_points(left + right, 7)
    assert sorted(len(z) for z in zones) == [6, 6]
    assert all(max(z) < 6 or min(z) >= 6 for z in zones)  # соседние — вместе
    assert split_points(left, 7) == [list(range(6))]


def test_box_lines_never_exceed_largest_regular_box() -> None:
    from floorplan_engine.wiring import BOX_BRANCHES

    plan = make_plan([{"length": 4000}, {"length": 6000}, {"length": 4000}, {"length": 6000}], [])
    pts = [_wall(f"d{k}", "sconce", "w1", 300 + 250 * k, 2000, "QF1") for k in range(14)]
    elec = Electrical.model_validate(
        {"points": pts, "board": {"room": "r", "wall": "w4", "offset": 500, "height": 1700}}
    )
    w = _wiring(plan, elec)
    branches = [sum(1 for r in w.runs if r.source == b.id) for b in w.boxes]
    assert len(w.boxes) >= 2 and max(branches) <= BOX_BRANCHES
    assert sum(branches) == 14
    assert all(any(r.target == b.id and r.source == "board" for r in w.runs) for b in w.boxes)


def test_switch_outside_room_goes_into_its_light_box() -> None:
    plan = _two_rooms_with_door()
    elec = Electrical.model_validate(
        {
            "points": [
                {"id": "l1", "room": "b", "type": "light", "ceiling": [1500, 1500], "group": "QF1"},
                {"id": "l2", "room": "b", "type": "light", "ceiling": [800, 800], "group": "QF1"},
                # выключатель света комнаты b — в комнате a, у двери
                {
                    "id": "k1",
                    "room": "a",
                    "type": "switch",
                    "wall": "w3",
                    "offset": 700,
                    "height": 900,
                    "group": "QF1",
                },
            ],
            "board": {"room": "a", "wall": "w1", "offset": 500, "height": 1700},
        }
    )
    w = _wiring(plan, elec)
    (box,) = w.boxes  # у выключателя нет своей коробки
    assert box.room == "b"
    to_switch = next(r for r in w.runs if r.target == "k1")
    assert to_switch.source == box.id  # от коробки света, не от щита
    assert not any(r.source == "board" and r.target == "k1" for r in w.runs)
    assert box.size == "100x100"  # 4 линии: питающая, два светильника, выключатель


# --- Ручные правки (wiring.yaml) ---------------------------------------------


def _edited(edits: dict[str, Any]) -> Any:
    from floorplan_engine.schema import WiringEdits

    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    wiring = box_wiring(plan, contours, _elec(), WiringEdits.model_validate(edits))
    assert wiring is not None
    return wiring


def test_manual_wire_path_replaces_route() -> None:
    auto = _wiring(make_plan(RECT, [DOOR]), _elec())
    run = next(r for r in auto.runs if r.target == "s1")
    a, b = run.path[0], run.path[-1]
    # Обход через середину комнаты: от щита вправо, вверх до 1500, к розетке
    path = [[a.x, a.y], [1500, a.y], [1500, b.y], [b.x, b.y]]
    w = _edited({"wires": {run.id: {"from": "board", "to": "s1", "path": path}}})
    manual = next(r for r in w.runs if r.id == run.id)
    assert [v.as_tuple() for v in manual.path] == [tuple(p) for p in path]
    assert manual.plan_mm == pytest.approx(abs(1500 - a.x) + abs(b.y - a.y) + abs(b.x - 1500))
    assert w.edited == {f"wire:{run.id}"} and not w.edit_notes


def test_stale_wire_edit_is_ignored() -> None:
    w = _edited({"wires": {"wire_1": {"from": "box_9", "to": "s1", "path": [[0, 0], [0, 10]]}}})
    assert not w.edited
    [(path, msg)] = w.edit_notes
    assert path == "wires.wire_1" and "не найдена" in msg


def test_wall_box_slides_along_its_wall() -> None:
    auto = _wiring(make_plan(RECT, [DOOR]), _elec())
    box = next(b for b in auto.boxes if not b.on_ceiling)
    a = box.anchor
    assert a.wall_dir is not None and a.inward is not None
    # Далеко вдоль стены и в сторону от неё — коробка у конца стены, на стене
    far = a.pos + a.wall_dir * 100000 + a.inward * 700
    edit = {"room": box.room, "group": box.group, "at": list(far.as_tuple())}
    w = _edited({"boxes": {box.id: edit}})
    moved = next(b for b in w.boxes if b.id == box.id)
    assert moved.anchor.inward == a.inward
    assert abs((moved.anchor.pos - a.pos).cross(a.wall_dir)) < 1e-6  # на той же стене
    assert moved.anchor.pos != a.pos
    # Линии коробки — от нового места
    for r in w.runs:
        if r.source == box.id:
            assert r.path[0] == moved.anchor.node
        if r.target == box.id:
            assert r.path[-1] == moved.anchor.node


def test_ceiling_box_moves_only_inside_room() -> None:
    from floorplan_engine.draw_electrical import Anchor
    from floorplan_engine.draw_plan import room_geometries
    from floorplan_engine.wiring import moved_anchor

    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    [g] = room_geometries(plan, contours)
    box = Anchor(Vec(1000, 1000), None, None, 75.0)
    assert moved_anchor(g, box, Vec(2000, 1500)) == Anchor(Vec(2000, 1500), None, None, 75.0)
    assert moved_anchor(g, box, Vec(-5000, -5000)) is None


def test_stale_box_edit_is_ignored() -> None:
    auto = _wiring(make_plan(RECT, [DOOR]), _elec())
    box = auto.boxes[0]
    w = _edited({"boxes": {box.id: {"room": box.room, "group": "QF99", "at": [100, 100]}}})
    assert next(b for b in w.boxes if b.id == box.id).anchor == box.anchor
    assert w.edit_notes[0][0] == f"boxes.{box.id}"


def test_wire_edit_must_be_orthogonal() -> None:
    from pydantic import ValidationError

    from floorplan_engine.schema import WireEdit

    with pytest.raises(ValidationError, match="прямые"):
        WireEdit.model_validate({"from": "board", "to": "s1", "path": [[0, 0], [100, 100]]})


def test_wiring_handles_lane_follows_path() -> None:
    from floorplan_engine.objects import wiring_handles

    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    w = _wiring(plan, _elec())
    wires = wiring_handles(plan, contours, w)["wires"]
    for r in w.runs:
        h = wires[r.id]
        assert len(h["lane"]) == len(h["path"])  # полоса — те же вершины со сдвигом
        for (ax, ay), (bx, by) in itertools.pairwise(h["lane"]):
            assert abs(ax - bx) < 0.2 or abs(ay - by) < 0.2  # углы прямые
