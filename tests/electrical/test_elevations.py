"""Развёртки стен (elevations.py, drawing/elevations.py) на синтетической комнате."""

from __future__ import annotations

from floorplan_engine.drawing.elevations import elevation_panel, spread
from floorplan_engine.electrical.elevations import elevation_data, wall_elevations
from floorplan_engine.electrical.wiring import box_wiring
from floorplan_engine.model.geometry import DOOR_TOP_MM
from floorplan_engine.model.schema import Electrical
from floorplan_engine.validation.electrical import validate_electrical
from floorplan_engine.validation.issues import Severity, parse_model
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan

WALLS = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]
DOOR = {"wall": "w1", "type": "door", "offset": 300, "width": 800}


def _elec(points: list[dict[str, object]]) -> Electrical:
    data = {
        "points": points,
        "board": {"room": "r", "wall": "w1", "offset": 2000, "height": 1700},
    }
    elec, issues = parse_model(Electrical, data, "e.yaml")
    assert elec is not None, issues
    return elec


SOCKETS = {"room": "r", "wall": "w2", "type": "socket", "group": "QF1"}


def test_walls_with_electrics_only_and_their_content() -> None:
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(
        [
            {"id": "s1", "offset": 1000, "height": 300, "count": 2, **SOCKETS},
            {"id": "s2", "offset": 2500, "height": 300, **SOCKETS},
            {"id": "l1", "room": "r", "ceiling": [1500, 2000], "type": "downlight", "group": "QF2"},
        ]
    )
    wiring = box_wiring(plan, contours, elec)
    walls = {e.wall: e for e in wall_elevations(plan, contours, elec, wiring)}
    assert set(walls) >= {"w1", "w2"} and "w3" not in walls  # на w3 ничего нет
    w2 = walls["w2"]
    assert [(p.id, p.x, p.y, p.posts) for p in w2.points] == [
        ("s1", 1000, 300, 2),
        ("s2", 2500, 300, 1),
    ]
    assert w2.points[0].number < w2.points[1].number  # номера — как на листе электрики
    # Спуски к розеткам — штробы от потолка вниз до точек
    assert w2.chases and all(c.y1 == w2.height for c in w2.chases)
    assert min(c.y0 for c in w2.chases) <= 300
    w1 = walls["w1"]
    assert w1.board is not None and w1.board.y == 1700
    (door,) = w1.openings
    assert (door.x0, door.x1, door.y1, door.assumed) == (300, 1100, DOOR_TOP_MM, True)
    assert {1000, 2500} <= set(w2.offsets()) and 300 in w2.heights()
    # Коробка на стене — с отметкой под потолком
    assert all(b.y == w2.height - 200 for b in w2.boxes)


def test_spread_keeps_order_gap_and_bounds() -> None:
    assert spread([0, 1, 2], 2.0, 0, 100) == [0, 2, 4]
    assert spread([10, 30], 2.0, 0, 100) == [10, 30]  # далеко — на своих местах
    out = spread([98, 99, 100], 2.0, 0, 100)
    assert out == [96, 98, 100]  # у края — сдвиг назад, не за границу


def test_point_above_ceiling_extends_view_and_warns() -> None:
    plan = make_plan(WALLS)
    _, contours = validate_plan(plan)
    elec = _elec([{"id": "hi", "offset": 1000, "height": 2900, **SOCKETS}])
    (e,) = [x for x in wall_elevations(plan, contours, elec, None) if x.wall == "w2"]
    assert e.height == 2700 and e.top > 2900 and e.above_ceiling() == ["hi"]
    warn = [i for i in validate_electrical(elec, plan, contours) if "выше потолка" in i.message]
    assert len(warn) == 1 and warn[0].severity is Severity.WARNING
    assert "по умолчанию" in warn[0].message


def test_panel_size_follows_scale() -> None:
    plan = make_plan(WALLS)
    _, contours = validate_plan(plan)
    elec = _elec([{"id": "s1", "offset": 1000, "height": 300, **SOCKETS}])
    (e,) = [x for x in wall_elevations(plan, contours, elec, None) if x.wall == "w2"]
    small, big = elevation_panel(e, 100, "ru"), elevation_panel(e, 50, "ru")
    assert big.width > small.width and big.height > small.height
    assert big.width >= 4000 / 50  # стена в масштабе


def test_behind_names_neighbour_and_its_wall() -> None:
    """Общая перегородка — две развёртки, и каждая называет другую сторону; наружная — пусто."""
    from typing import Any

    from floorplan_engine.electrical.elevations import behind
    from floorplan_engine.model.geometry import room_geometries
    from floorplan_engine.model.schema import Plan

    def room(rid: str, x: float) -> dict[str, Any]:
        walls = [{"id": f"w{k + 1}", "length": n} for k, n in enumerate((3000, 4000, 3000, 4000))]
        return {"id": rid, "name": rid.upper(), "origin": [x, 0], "walls": walls}

    plan = Plan.model_validate(
        {
            "name": "т",
            "default_wall_thickness": 100,
            "source": "text",
            "rooms": [room("a", 0), room("b", 4100)],
        }
    )
    _, contours = validate_plan(plan)
    geoms = room_geometries(plan, contours)
    a, b = geoms
    # Правая стена a (w3) — левая стена b (w1)
    assert behind(a, a.contour.segments[2], geoms) == (("B", 1),)
    assert behind(b, b.contour.segments[0], geoms) == (("A", 3),)
    assert behind(a, a.contour.segments[0], geoms) == ()


def test_elevation_side_line() -> None:
    from dataclasses import replace

    from floorplan_engine.drawing.elevations import _side

    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec([{"id": "s1", "offset": 1000, "height": 300, **SOCKETS}])
    w2 = next(e for e in wall_elevations(plan, contours, elec, None) if e.wall == "w2")
    assert _side(w2, "ru") == "вид изнутри · за стеной: вне квартиры"
    neighbours = replace(w2, behind=(("Кухня, коридор", 2), ("Спальня", None)))
    assert _side(neighbours, "ru") == "вид изнутри · за стеной: Кухня, коридор (стена 2); Спальня"


def test_back_side_points_mirrored_onto_this_wall() -> None:
    """Розетка соседа на общей перегородке — на развёртке этой стороны, на своём месте:
    стена w3 комнаты a идёт сверху вниз, w1 комнаты b — снизу вверх, поэтому отступ 1000
    от низа у b — это 4000 − 1000 = 3000 от верхнего угла у a."""
    from typing import Any

    from floorplan_engine.model.schema import Plan

    def room(rid: str, x: float) -> dict[str, Any]:
        walls = [{"id": f"w{k + 1}", "length": n} for k, n in enumerate((4000, 3000, 4000, 3000))]
        return {"id": rid, "name": rid.upper(), "origin": [x, 0], "walls": walls}

    plan = Plan.model_validate(
        {
            "name": "т",
            "default_wall_thickness": 100,
            "source": "text",
            "rooms": [room("a", 0), room("b", 3100)],
        }
    )
    _, contours = validate_plan(plan)
    sock = {"type": "socket", "group": "QF1", "height": 300}
    elec, issues = parse_model(
        Electrical,
        {
            "points": [
                {"id": "a1", "room": "a", "wall": "w3", "offset": 500, **sock},
                {"id": "b1", "room": "b", "wall": "w1", "offset": 1000, **sock},
            ]
        },
        "e.yaml",
    )
    assert elec is not None, issues
    walls = {e.key: e for e in wall_elevations(plan, contours, elec, None)}
    (back,) = walls["a.w3"].back
    assert (back.id, back.x, back.y) == ("b1", 3000, 300)
    (mirror,) = walls["b.w1"].back
    assert (mirror.id, mirror.x) == ("a1", 3500)


def test_elevation_data_links_points_to_wiring() -> None:
    """Развёртка данными для просмотра: точки — с номером, группой и тем, откуда к ним
    линия проводки; ключи объектов — как на листах (point:, box:, board:)."""
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec(
        [
            {"id": "s1", "offset": 1000, "height": 300, "count": 2, **SOCKETS},
            {"id": "s2", "offset": 2500, "height": 300, **SOCKETS},
        ]
    )
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    walls = {e["key"]: e for e in elevation_data(plan, contours, elec, wiring, {"QF1": 0x112233})}
    w2 = walls["elevation:r.w2"]
    s1 = w2["points"][0]
    assert (s1["key"], s1["posts"], s1["group"], s1["color"]) == ("point:s1", 2, "QF1", "#112233")
    feeds = {r.target: r.source for r in wiring.runs}
    labels = {b.id: b.label for b in wiring.boxes}
    assert s1["from"] == labels.get(feeds["s1"], "ЩР")
    assert all(b["key"].startswith("box:") for b in w2["boxes"])
    assert walls["elevation:r.w1"]["board"]["key"] == "board:board"


def test_elevation_data_face_and_neighbours() -> None:
    """У развёртки — грань на плане и соседние стены в углах: угол и что на них (у стены без
    электрики — только проёмы)."""
    plan = make_plan(WALLS, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec([{"id": "s1", "offset": 1000, "height": 300, **SOCKETS}])
    walls = {e["key"]: e for e in elevation_data(plan, contours, elec, None, {})}
    w2 = walls["elevation:r.w2"]
    assert w2["face"] == [[0.0, 3000.0], [4000.0, 3000.0]]
    left, right = w2["left"], w2["right"]
    assert (left["key"], left["turn"], left["length"]) == ("elevation:r.w1", 90, 3000)
    assert [o["kind"] for o in left["openings"]] == ["door"]
    assert left["points"] == []
    assert (right["key"], right["turn"]) == ("elevation:r.w3", 90)
    # Сосед с электрикой — с её точками и щитом
    w1 = walls["elevation:r.w1"]
    assert [p["key"] for p in w1["right"]["points"]] == ["point:s1"]
    assert w1["left"]["key"] == "elevation:r.w4"
    assert "back" not in w1["right"]
    assert walls["elevation:r.w2"]["left"]["board"]["key"] == "board:board"
