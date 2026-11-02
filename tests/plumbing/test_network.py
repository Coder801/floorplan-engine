from __future__ import annotations

import itertools
from typing import Any

import pytest
from shapely.geometry import LineString

from floorplan_engine.model.geometry import room_geometries
from floorplan_engine.model.plumbing import Plumbing
from floorplan_engine.model.schema import Plan
from floorplan_engine.plumbing.network import (
    HOT_COLD_GAP,
    MAIN_D,
    SUPPLY_D,
    Network,
    build_network,
    fixture_outlets,
    partition_strips,
)
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_flat

RISER = {"id": "riser_1", "room": "bath", "at": [150, 150], "sewer": True, "water": True}


def network(**data: Any) -> Network:
    plan = make_flat()
    _, contours = validate_plan(plan)
    return build_network(plan, contours, Plumbing.model_validate({"risers": [RISER], **data}))


def wc(offset: float = 600) -> dict[str, Any]:
    return {"id": "wc", "room": "bath", "type": "wc", "wall": "w4", "offset": offset}


def test_outlets_hot_left_cold_right_drain_middle() -> None:
    plan = make_flat()
    _, contours = validate_plan(plan)
    geoms = {g.room.id: g for g in room_geometries(plan, contours)}
    fx = Plumbing.model_validate(
        {"fixtures": [{"id": "s", "room": "bath", "type": "sink", "wall": "w1", "offset": 1000}]}
    ).fixtures[0]
    out = {o.kind: o for o in fixture_outlets(fx, geoms)}
    assert out["hot"].offset == 1000 - HOT_COLD_GAP / 2
    assert out["cold"].offset == 1000 + HOT_COLD_GAP / 2
    assert out["sewer"].offset == 1000 and out["sewer"].d == 50
    assert out["cold"].assumed  # высота типовая


def test_collector_gives_each_outlet_own_pipe() -> None:
    net = network(
        fixtures=[wc(), {"id": "s", "room": "bath", "type": "sink", "wall": "w1", "offset": 1500}]
    )
    water = [p for p in net.pipes if p.kind != "sewer"]
    assert len(water) == 3  # холодная к унитазу, холодная и горячая к умывальнику
    assert all(p.source.startswith("collector_") and p.d == SUPPLY_D for p in water)
    assert {c.kind for c in net.collectors} == {"cold", "hot"}
    assert net.input_assumed  # узел ввода — у стояка допущением


def test_tee_branches_from_main() -> None:
    net = network(
        distribution="tee",
        fixtures=[
            {"id": "s", "room": "bath", "type": "sink", "wall": "w1", "offset": 1500},
            {"id": "k", "room": "kitchen", "type": "kitchen_sink", "wall": "w2", "offset": 2000},
        ],
    )
    cold = net.pipes_of("cold")
    assert len(cold) == 2
    branch = [p for p in cold if p.parent is not None]
    assert branch, "второй прибор — отводом от магистрали"
    parent = next(p for p in cold if p.id == branch[0].parent)
    assert parent.d == MAIN_D


def test_sewer_wc_goes_to_riser_with_110() -> None:
    net = network(fixtures=[wc()])
    sewer = net.pipes_of("sewer")
    assert len(sewer) == 1 and sewer[0].d == 110 and sewer[0].source == "riser_1"
    check = net.sewer[0]
    assert check.ok and check.drop > 0


def test_far_low_drain_needs_podium() -> None:
    net = network(
        fixtures=[{"id": "sh", "room": "kitchen", "type": "shower", "wall": "w3", "offset": 2000}]
    )
    check = next(s for s in net.sewer if s.fixture == "sh")
    assert not check.ok and check.podium > 0
    assert any(w.severity == "error" and w.target == "sh" for w in net.weak)


def test_pipes_avoid_bath() -> None:
    tub = {
        "id": "tub",
        "room": "bath",
        "type": "bath",
        "wall": "w2",
        "offset": 0,
        "width": 2000,
        "depth": 800,
    }
    net = network(
        fixtures=[{"id": "s", "room": "bath", "type": "sink", "wall": "w2", "offset": 1000}],
        obstacles=[tub],
    )
    poly = net.obstacles["tub"]
    for p in net.pipes:
        if p.kind == "sewer":
            continue  # канализации под ванной можно — скрытая зона
        floor = LineString([v.as_tuple() for v in p.path[:-1]])  # без хвоста в стене
        assert floor.intersection(poly.buffer(-1.0)).length < 1.0


def test_installation_fixture_connects_through_box() -> None:
    box = {
        "id": "inst",
        "room": "bath",
        "type": "installation",
        "wall": "w4",
        "offset": 300,
        "width": 600,
        "depth": 250,
    }
    net = network(fixtures=[wc(600)], obstacles=[box])
    sewer = net.pipes_of("sewer")[0]
    assert sewer.wall_run > 0  # последний участок — внутри короба


def test_boiler_is_hot_source() -> None:
    net = network(
        fixtures=[
            {"id": "b", "room": "bath", "type": "boiler", "wall": "w1", "offset": 2000},
            {"id": "s", "room": "bath", "type": "sink", "wall": "w1", "offset": 1000},
        ]
    )
    assert net.hot_source == "b"
    feed = [p for p in net.pipes_of("hot") if p.source == "b"]
    assert feed and feed[0].target == "collector_hot" and feed[0].d == MAIN_D


def test_partition_is_crossed_with_hole() -> None:
    plan = make_flat()
    _, contours = validate_plan(plan)
    strips = partition_strips(room_geometries(plan, contours))
    assert strips  # стена санузла с кухней — перегородка 100 мм
    net = network(
        fixtures=[
            {"id": "k", "room": "kitchen", "type": "kitchen_sink", "wall": "w1", "offset": 2200}
        ]
    )
    assert net.holes(("cold", "hot")) >= 1


def _thick_flat(partition: bool) -> Plan:
    """make_flat со стеной санузел–кухня 200 мм: толще PARTITION_MAX."""
    data = make_flat().model_dump()
    bath, kitchen = data["rooms"]
    kitchen["origin"] = [2200, 0]
    for wall in (bath["walls"][2], kitchen["walls"][0]):
        wall["thickness"] = 200
        wall["partition"] = partition
    return Plan.model_validate(data)


@pytest.mark.parametrize("partition", [False, True])
def test_thick_wall_is_partition_only_when_marked(partition: bool) -> None:
    plan = _thick_flat(partition)
    _, contours = validate_plan(plan)
    assert bool(partition_strips(room_geometries(plan, contours))) is partition


def _through_door(net: Network) -> list[str]:
    door = net.doors[0]
    return [
        p.id
        for p in net.pipes
        if LineString([v.as_tuple() for v in p.path]).intersection(door).length >= 1.0
    ]


def test_pipes_avoid_door_when_partition_is_there() -> None:
    net = network(
        fixtures=[
            {"id": "k", "room": "kitchen", "type": "kitchen_sink", "wall": "w2", "offset": 600}
        ]
    )
    assert net.doors and _through_door(net) == []
    assert not any(w.target == "k" and "дверн" in w.text["ru"] for w in net.weak)


def test_door_only_if_no_other_way_and_flagged() -> None:
    plan = make_flat()
    data = plan.model_dump(mode="json")
    data["rooms"][0]["walls"][2]["bearing"] = True  # стена санузла с кухней — несущая
    data["rooms"][1]["walls"][0]["bearing"] = True
    plan = type(plan).model_validate(data)
    _, contours = validate_plan(plan)
    net = build_network(
        plan,
        contours,
        Plumbing.model_validate(
            {
                "risers": [RISER],
                "fixtures": [
                    {
                        "id": "k",
                        "room": "kitchen",
                        "type": "kitchen_sink",
                        "wall": "w2",
                        "offset": 600,
                    }
                ],
            }
        ),
    )
    assert _through_door(net)
    assert any(w.target == "k" and "дверной проём" in w.text["ru"] for w in net.weak)
    # Канализации через дверь нельзя: прибор отрезан — ошибка, трубы нет
    assert not net.pipes_of("sewer")
    assert [e.reason for e in net.sewer_errors] == ["unreachable"]


def test_hot_runs_paired_with_cold() -> None:
    from floorplan_engine.plumbing.network import PAIR_GAP

    net = network(
        fixtures=[
            {"id": "k", "room": "kitchen", "type": "kitchen_sink", "wall": "w2", "offset": 1500}
        ]
    )
    cold = next(p for p in net.pipes_of("cold") if p.target == "k")
    hot = next(p for p in net.pipes_of("hot") if p.target == "k")
    line = LineString([v.as_tuple() for v in cold.path])
    # Середины участков по полу (без концов у коллектора и водорозетки): на углу вершина
    # сдвинутой линии — по диагонали от угла холодной
    floor = hot.path[1:-1]
    mids = [(a + b) * 0.5 for a, b in itertools.pairwise(floor)]
    gaps = [line.distance(shapely_point(v)) for v in mids[1:-1] or mids]
    assert gaps and max(gaps) <= PAIR_GAP + 1.0 and min(gaps) >= PAIR_GAP - 1.0


def shapely_point(v: Any) -> Any:
    from shapely.geometry import Point

    return Point(v.as_tuple())


def test_parallel_offsets_left_of_travel() -> None:
    from floorplan_engine.model.geometry import Vec
    from floorplan_engine.plumbing.network import parallel

    path = [Vec(0, 0), Vec(1000, 0), Vec(1000, 1000)]
    assert parallel(path, 50) == [Vec(0, 50), Vec(950, 50), Vec(950, 1000)]


def test_sewer_keeps_to_walls_and_drops_in_wall() -> None:
    from floorplan_engine.plumbing.network import WALL_BAND_MM

    net = network(
        fixtures=[
            wc(600),
            {"id": "s", "room": "bath", "type": "sink", "wall": "w2", "offset": 1600},
        ]
    )
    plan = make_flat()
    _, contours = validate_plan(plan)
    room = room_geometries(plan, contours)[0]
    walls = LineString([v.as_tuple() for v in [*room.contour.vertices, room.contour.vertices[0]]])
    sink = next(p for p in net.pipes_of("sewer") if p.target == "s")
    far = [v for v in sink.path[1:-1] if walls.distance(shapely_point(v)) > WALL_BAND_MM + 1]
    assert far == []  # по полу — только вдоль стен
    check = next(c for c in net.sewer if c.fixture == "s")
    assert sink.rise == pytest.approx(500 - check.end_floor)  # вниз в стене до трубы по полу


def _bends_ok(path: Any) -> bool:
    from floorplan_engine.plumbing.bends import is_octilinear, turn

    pts = list(path)
    if not all(is_octilinear(b - a) for a, b in itertools.pairwise(pts)):
        return False
    return all(
        abs(turn(b - a, c - b) - 45.0) < 0.5 or turn(b - a, c - b) < 0.5
        for a, b, c in zip(pts, pts[1:], pts[2:], strict=False)
    )


def test_sewer_bends_only_45() -> None:
    net = network(
        fixtures=[
            wc(600),
            {"id": "s", "room": "bath", "type": "sink", "wall": "w2", "offset": 1600},
            {"id": "k", "room": "kitchen", "type": "kitchen_sink", "wall": "w2", "offset": 1500},
        ]
    )
    sewer = net.pipes_of("sewer")
    assert len(sewer) == 3
    assert all(_bends_ok(p.path) for p in sewer)


def test_wc_outside_box_goes_along_wall() -> None:
    net = network(fixtures=[wc(1600)])
    # Ø110 в стяжку нельзя — вдоль стены над полом, в коробе: не ошибка, а примечание
    assert net.sewer_errors == []
    route = net.routes[0]
    assert route.ok and route.d == 110 and route.fittings[-1] == "tee45"
    assert "surface" in {s.zone for s in route.segments}
    pipe = net.pipes_of("sewer")[0]
    assert pipe.surface_length > 0 and pipe.surface_top > 0
    assert any(w.target == "wc" and "по стене над полом" in w.text["ru"] for w in net.weak)


def test_screed_110_only_off_walls() -> None:
    from floorplan_engine.model.geometry import Vec
    from floorplan_engine.plumbing.network import _Zones

    net = network(fixtures=[wc(1600)])
    plan = make_flat()
    _, contours = validate_plan(plan)
    geoms = {g.room.id: g for g in room_geometries(plan, contours)}
    zones = _Zones.of(_ctx_stub(net, geoms))
    assert zones.at(Vec(100, 1000), 200.0, 110)[0] == "surface"  # у стены санузла
    assert zones.at(Vec(1000, 1250), 200.0, 110)[0] == "screed"  # посреди — ошибка стяжки
    assert zones.at(Vec(1000, 1250), 10.0, 50)[0] == "screed"  # Ø50 помещается — в стяжке
    # В дверном проёме над полом не идут — стяжка (и ошибка, если не помещается)
    assert zones.at(Vec(2050, 1850), 200.0, 50)[0] in ("screed", "wall")


def _ctx_stub(net: Network, geoms: Any) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(net=net, geoms=geoms)


def test_wc_in_installation_box_is_hidden() -> None:
    box = {
        "id": "inst",
        "room": "bath",
        "type": "installation",
        "wall": "w4",
        "offset": 0,
        "width": 2000,  # вдоль всей стены, стояк — в коробе
        "depth": 450,
    }
    wc_inst = {**wc(1400), "type": "wc_installation"}
    net = network(fixtures=[wc_inst], obstacles=[box])
    assert not [e for e in net.sewer_errors if e.reason == "screed_110"]
    zones = {s.zone for s in net.routes[0].segments}
    assert "hidden" in zones and "screed" not in zones


def test_sink_in_screed_needs_low_tee() -> None:
    sink = {"id": "s", "room": "bath", "type": "sink", "wall": "w4", "offset": 1500}
    high = network(fixtures=[sink])  # врезка 100 мм над полом — допущение
    # В стяжку не помещается — по стене над полом, не ошибка
    assert high.sewer_errors == []
    assert {seg.zone for seg in high.routes[0].segments} >= {"surface"}
    assert "screed" not in {seg.zone for seg in high.routes[0].segments}
    low = network(risers=[{**RISER, "sewer_inlet": -30}], fixtures=[sink])
    assert low.sewer_errors == []
    assert low.pipes_of("sewer")[0].surface == ()
    route = low.routes[0]
    assert route.ok and route.slope == 0.03  # запас высоты есть — круче (ТЗ, п. 5)
    assert route.drop is not None  # выпуск 500 мм — спуск в стене
    for seg in route.segments:
        if seg.zone == "screed":
            assert max(seg.start[2], seg.end[2]) + 50 + 15 <= 90 + 0.5


def test_route_slope_constant_down_to_riser() -> None:
    net = network(
        fixtures=[
            {"id": "s", "room": "bath", "type": "sink", "wall": "w4", "offset": 900},
            {"id": "s2", "room": "bath", "type": "sink", "wall": "w4", "offset": 1500},
        ],
    )
    for r in net.routes:
        for seg in r.segments:
            if seg.length > 1.0:
                drop = seg.start[2] - seg.end[2]  # z округлены до 0,1 мм
                assert drop == pytest.approx(r.slope * seg.length, abs=0.15)


def test_small_drain_into_wc_pipe_tee_110x50() -> None:
    net = network(
        fixtures=[
            wc(600),
            {"id": "s", "room": "bath", "type": "sink", "wall": "w4", "offset": 1500},
        ]
    )
    pipes = {p.id: p for p in net.pipes_of("sewer")}
    sink = next(p for p in pipes.values() if p.target == "s")
    wc_pipe = next(p for p in pipes.values() if p.target == "wc")
    # Ø50 — тройником 110×50 в трубу унитаза; Ø110 — только в стояк или в Ø110
    assert sink.parent == wc_pipe.id and wc_pipe.parent is None
    # Низ ветки Ø50 не ниже низа магистрали Ø110 в месте врезки
    assert sink.z0 >= wc_pipe.z0 + sink.attach * wc_pipe.slope - 0.01
    assert sink.slope <= wc_pipe.slope  # магистраль не положе ветки


def test_wc_far_from_riser_is_error() -> None:
    net = network(fixtures=[wc(1800)], risers=[{**RISER, "at": [150, 2300]}])
    assert "wc_far" in [e.reason for e in net.sewer_errors]


def test_routes_json_format() -> None:
    from floorplan_engine.plumbing.network import routes_json

    sink = {"id": "s", "room": "kitchen", "type": "shower", "wall": "w3", "offset": 2000}
    data = routes_json(network(fixtures=[wc(1600), sink]))
    route = data["routes"][0]
    assert set(route) >= {"fixture", "diameter", "slope", "verticalDrop", "segments", "ok"}
    assert {s["zone"] for r in data["routes"] for s in r["segments"]} <= {
        "screed",
        "hidden",
        "wall",
        "surface",
    }
    assert data["errors"] and set(data["errors"][0]) == {"fixture", "reason", "at"}


KITCHEN_PAIR = [
    {"id": "k", "room": "kitchen", "type": "kitchen_sink", "wall": "w2", "offset": 1500},
    {"id": "d", "room": "kitchen", "type": "dishwasher", "wall": "w2", "offset": 2100},
    {"id": "s", "room": "bath", "type": "sink", "wall": "w2", "offset": 1000},
]


def test_drains_merge_with_tee_at_45() -> None:
    from floorplan_engine.plumbing.bends import point_at, turn

    net = network(fixtures=KITCHEN_PAIR)
    sewer = {p.id: p for p in net.pipes_of("sewer")}
    roots = [p for p in sewer.values() if p.parent is None]
    assert len(roots) == 1  # одна врезка в стояк, остальные — тройниками
    for p in sewer.values():
        if p.parent is None:
            continue
        _, d_parent, _ = point_at(sewer[p.parent].path, p.attach)
        flow_main, flow_branch = d_parent * -1.0, p.path[0] - p.path[1]
        assert turn(flow_branch, flow_main) == pytest.approx(45.0, abs=0.5)


def test_saving_vs_direct() -> None:
    from floorplan_engine.plumbing.network import routes_json

    merged = routes_json(network(fixtures=KITCHEN_PAIR))
    assert merged["savingVsDirect"] > 0
    assert merged["totalLength"] > 0 and merged["totalFittings"] > 0
    alone = routes_json(network(fixtures=KITCHEN_PAIR[:1]))
    assert alone["savingVsDirect"] == pytest.approx(0.0, abs=0.5)  # тройников нет


def test_tee_does_not_break_screed() -> None:
    near = {"id": "n", "room": "bath", "type": "sink", "wall": "w4", "offset": 1500}
    net = network(risers=[{**RISER, "sewer_inlet": -30}], fixtures=[near, *KITCHEN_PAIR[:2]])
    # Напрямую умывальник укладывается в стяжку — тройник с кухней этого не ломает
    assert not [e for e in net.sewer_errors if e.fixture == "n"]


def test_surface_spans_on_pipe_from_riser() -> None:
    sink = {"id": "k", "room": "kitchen", "type": "kitchen_sink", "wall": "w3", "offset": 1200}
    # Врезка на 30 мм ниже пола: у стояка труба в стяжке, дальше — по стене над полом
    net = network(risers=[{**RISER, "sewer_inlet": -30}], fixtures=[sink])
    pipe = net.pipes_of("sewer")[0]
    floor = [seg.zone for seg in net.routes[0].segments if seg.zone != "wall"]
    assert floor[0] == "surface" and floor[-1] == "screed"  # по течению: у стояка — в стяжке
    assert "screed" not in floor[: floor.index("screed")] and set(floor) == {"surface", "screed"}
    assert pipe.surface[0][0] > 0  # над полом — не от самого стояка
    assert pipe.surface_length > 0.5 * pipe.length
    assert not [e for e in net.sewer_errors if e.reason == "screed_depth"]


DOUBLE_SINK = [
    {"id": "s1", "room": "bath", "type": "sink", "wall": "w1", "offset": 900},
    {"id": "s2", "room": "bath", "type": "sink", "wall": "w1", "offset": 1500},
]


def test_supply_groups_double_sink() -> None:
    from floorplan_engine.plumbing.network import supply_groups

    far = {"id": "s3", "room": "bath", "type": "sink", "wall": "w1", "offset": 2900}
    other = {"id": "k", "room": "kitchen", "type": "kitchen_sink", "wall": "w2", "offset": 1000}
    fixtures = Plumbing.model_validate({"fixtures": [*DOUBLE_SINK, far, other]}).fixtures
    assert supply_groups(fixtures) == {"s1": "s1", "s2": "s1", "s3": "s3", "k": "k"}


def test_double_sink_one_line_from_collector() -> None:
    net = network(fixtures=DOUBLE_SINK)
    for kind in ("cold", "hot"):
        pipes = net.pipes_of(kind)
        roots = [p for p in pipes if p.parent is None]
        branches = [p for p in pipes if p.parent is not None]
        assert len(roots) == 1 and len(branches) == 1  # одна линия, второй — тройником
        assert branches[0].parent == roots[0].id
        assert all(p.d == SUPPLY_D for p in pipes)  # общая линия умывальников — Ø16
    assert {c.kind: c.outputs for c in net.collectors} == {"cold": 1, "hot": 1}


def test_water_pipes_share_partition_hole() -> None:
    fixtures = [
        {"id": "k", "room": "kitchen", "type": "kitchen_sink", "wall": "w2", "offset": 2500},
        {"id": "d", "room": "kitchen", "type": "dishwasher", "wall": "w4", "offset": 600},
    ]
    net = network(fixtures=fixtures)
    # Перегородку санузел–кухня трубы воды проходят пучком: одно отверстие на всех
    assert net.holes(("cold", "hot")) == 1


def test_hot_collector_next_to_far_boiler_clear_of_box() -> None:
    boiler = {"id": "b", "room": "kitchen", "type": "boiler", "wall": "w2", "offset": 1500}
    box = {
        "id": "box",
        "room": "kitchen",
        "type": "box",
        "wall": "w2",
        "offset": 1200,
        "width": 600,
        "depth": 250,
    }
    sink = {"id": "k", "room": "kitchen", "type": "kitchen_sink", "wall": "w3", "offset": 1200}
    net = network(fixtures=[boiler, sink], obstacles=[box])
    cols = {c.kind: c for c in net.collectors}
    # Бойлер далеко от узла ввода — коллектор горячей у бойлера; под бойлером короб — рядом
    assert (cols["hot"].room, cols["hot"].wall) == ("kitchen", "w2")
    assert not 1200 - 150 < cols["hot"].offset < 1800 + 150
    assert (cols["hot"].node - cols["cold"].node).length() > 1000


def test_boiler_near_input_collectors_together_at_input_height() -> None:
    boiler = {"id": "b", "room": "bath", "type": "boiler", "wall": "w1", "offset": 900}
    sink = {"id": "k", "room": "kitchen", "type": "kitchen_sink", "wall": "w2", "offset": 1500}
    inp = {"room": "bath", "wall": "w1", "offset": 500, "height": 1300}
    net = network(fixtures=[boiler, sink], input=inp)
    cols = {c.kind: c for c in net.collectors}
    assert (cols["hot"].node - cols["cold"].node).length() < 500  # оба в узле ввода
    assert cols["hot"].height == cols["cold"].height == 1300
    to_sink = next(p for p in net.pipes_of("cold") if p.target == "k")
    assert to_sink.rise == 1300 + 550  # вниз от коллектора и вверх к водорозетке


def test_dishwasher_takes_cold_from_kitchen_sink() -> None:
    net = network(fixtures=KITCHEN_PAIR[:2])
    cold = net.pipes_of("cold")
    sink = next(p for p in cold if p.target == "k")
    dish = next(p for p in cold if p.target == "d")
    assert sink.parent is None and dish.parent == sink.id  # тройник от холодной мойки
    hot = net.pipes_of("hot")
    assert [p.target for p in hot] == ["k"] and hot[0].parent is None
    assert {c.kind: c.outputs for c in net.collectors} == {"cold": 1, "hot": 1}


def test_parallel_line_branches_off_with_capacity() -> None:
    fixtures = [
        {"id": "k", "room": "kitchen", "type": "kitchen_sink", "wall": "w2", "offset": 2500},
        {"id": "w", "room": "kitchen", "type": "washer", "wall": "w2", "offset": 1200},
    ]
    net = network(fixtures=fixtures)
    cold = {p.target: p for p in net.pipes_of("cold")}
    # Линия стиральной шла бы рядом с линией мойки — отходит от неё тройником
    assert cold["w"].parent == cold["k"].id
    assert cold["k"].d == 20  # 0,09 + 0,15 л/с — больше пропуска Ø16
    assert {c.kind: c.outputs for c in net.collectors}["cold"] == 1


def test_parallel_lines_stay_apart_over_capacity() -> None:
    baths = [
        {"id": "b1", "room": "kitchen", "type": "bath", "wall": "w2", "offset": 2500},
        {"id": "b2", "room": "kitchen", "type": "bath", "wall": "w2", "offset": 1000},
    ]
    net = network(fixtures=baths)
    # Две ванны — 0,36 л/с: Ø20 не пропустит, у каждой своя линия
    assert all(p.parent is None for p in net.pipes_of("cold"))


def test_pipe_d_by_flow() -> None:
    from floorplan_engine.plumbing.network import _pipe_d

    assert (_pipe_d(0.18), _pipe_d(0.33), _pipe_d(0.4)) == (16, 20, None)


def _room_with_drywall(partition: bool) -> Plan:
    """Комната 3000×3000 с коробом 1000×200 от левой стены (w2–w4) — гипсокартон, если
    partition."""
    wall = {"thickness": 200, "partition": partition} if partition else {"thickness": 200}
    return Plan.model_validate(
        {
            "name": "тест",
            "default_wall_thickness": 200,
            "source": "text",
            "rooms": [
                {
                    "id": "bath",
                    "name": "Санузел",
                    "wet": True,
                    "origin": [0, 0],
                    "walls": [
                        {"id": "w1", "length": 1000},
                        {"id": "w2", "length": 1000, "turn": 270, **wall},
                        {"id": "w3", "length": 200, "turn": 270, **wall},
                        {"id": "w4", "length": 1000, **wall},
                        {"id": "w5", "length": 1800},
                        {"id": "w6", "length": 3000},
                        {"id": "w7", "length": 3000},
                        {"id": "w8", "length": 3000},
                    ],
                }
            ],
        }
    )


@pytest.mark.parametrize("partition", [False, True])
def test_pipes_under_drywall_wall_in_room(partition: bool) -> None:
    plan = _room_with_drywall(partition)
    _, contours = validate_plan(plan)
    assert bool(partition_strips(room_geometries(plan, contours), inner=True)) is partition
    plumbing = Plumbing.model_validate(
        {
            "risers": [{"id": "r", "room": "bath", "at": [2800, 2800]}],
            "input": {"room": "bath", "wall": "w5", "offset": 300},
            "fixtures": [{"id": "s", "room": "bath", "type": "sink", "wall": "w1", "offset": 500}],
        }
    )
    net = build_network(plan, contours, plumbing)
    cold = net.pipes_of("cold")[0]
    # Под гипсокартонной стенкой — напрямую и без отверстия; иначе — в обход короба
    assert (cold.length < 2000) is partition
    assert net.holes(("cold", "hot")) == 0


def test_sewer_grid_costs_by_distance_to_wall() -> None:
    from floorplan_engine.plumbing.network import (
        HIDDEN_COST,
        NEAR_WALL_COST,
        OPEN_ROOM_COST,
        TAG_HIDDEN,
        TAG_OPEN,
        TAG_WALL,
        WALL_COST,
    )

    box = {"id": "tub", "room": "kitchen", "type": "bath", "rect": [1500, 1000, 2500, 1700]}
    net = network(fixtures=[wc(600)], obstacles=[box])
    assert OPEN_ROOM_COST >= 3 * WALL_COST and WALL_COST < NEAR_WALL_COST < OPEN_ROOM_COST
    plan = make_flat()
    _, contours = validate_plan(plan)
    from floorplan_engine.plumbing.network import SEWER_VARIANTS, _sewer_grid

    grid = _sewer_grid(room_geometries(plan, contours), net, SEWER_VARIANTS[0])
    assert grid.tag is not None and grid.mult is not None
    at_wall = grid.nearest_free(_v(2300, 200))  # кухня, у нижней стены
    middle = grid.nearest_free(_v(2900, 1250))  # кухня, посредине (ванна — x 3600–4600)
    under_tub = grid.nearest_free(_v(4100, 1350))  # под ванной — скрытая зона
    assert grid.tag[at_wall] == TAG_WALL and grid.mult[at_wall] == WALL_COST
    assert grid.tag[middle] == TAG_OPEN and grid.mult[middle] == OPEN_ROOM_COST
    assert grid.tag[under_tub] == TAG_HIDDEN and grid.mult[under_tub] == HIDDEN_COST


def _v(x: float, y: float) -> Any:
    from floorplan_engine.model.geometry import Vec

    return Vec(x, y)


def test_far_drain_hugs_walls_instead_of_diagonal() -> None:
    """Мойка в дальнем углу кухни: середина комнаты дороже (п. 1) и закрыта, где труба уже
    выше стяжки (п. 2), — трасса вдоль стен, а не по диагонали через комнату."""
    sink = {"id": "k", "room": "kitchen", "type": "kitchen_sink", "wall": "w2", "offset": 2700}
    net = network(risers=[{**RISER, "sewer_inlet": -30}], fixtures=[sink])
    pipe = net.pipes_of("sewer")[0]
    assert pipe.open_length < 300.0  # посреди комнаты — разве что у самого стояка
    assert not [e for e in net.sewer_errors if e.reason == "screed_depth"]


def test_score_prefers_fewer_errors_then_box_then_length() -> None:
    from floorplan_engine.plumbing.network import _score

    net = network(fixtures=[wc(600)])
    score = _score(net)
    assert len(score) == 5 and score[0] == 0
    assert score[4] >= sum(p.total for p in net.pipes_of("sewer"))


def test_height_prune_open_cells_only_above_screed() -> None:
    from floorplan_engine.plumbing.network import (
        SEWER_VARIANTS,
        TAG_OPEN,
        TAG_WALL,
        _height_prune,
        _sewer_grid,
    )

    net = network(fixtures=[wc(600)])
    plan = make_flat()
    _, contours = validate_plan(plan)
    grid = _sewer_grid(room_geometries(plan, contours), net, SEWER_VARIANTS[0])
    assert grid.tag is not None
    open_cell = next(k for k, t in enumerate(grid.tag) if t == TAG_OPEN and grid.free[k])
    wall_cell = next(k for k, t in enumerate(grid.tag) if t == TAG_WALL and grid.free[k])
    prune = _height_prune(grid, z0=0.0, slope=0.025, d=50)  # в стяжку — до 25 мм: 1 м трубы
    assert prune is not None
    assert not prune(open_cell, 900.0) and prune(open_cell, 1100.0)
    assert not prune(wall_cell, 5000.0)  # у стены — короб над полом, не отсекается
    big = _height_prune(grid, z0=0.0, slope=0.02, d=110)
    assert big is not None and big(open_cell, 0.0)  # Ø110 в стяжку не помещается вовсе
    # От прибора длина неизвестна — нижняя оценка: расстояние до стояка по прямой
    far = _height_prune(grid, z0=0.0, slope=0.025, d=50, lower=grid.center(open_cell) + _v(5000, 0))
    assert far is not None and far(open_cell, 0.0)
