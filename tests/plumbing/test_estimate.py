from __future__ import annotations

from collections.abc import Sequence

from floorplan_engine.electrical.pricing import MockPriceService, Prices
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.plumbing import Plumbing
from floorplan_engine.model.texts import Language
from floorplan_engine.plumbing.estimate import (
    LINES,
    MOCK_PRICES,
    build_estimate,
    elbows,
    quantities,
    water_fittings,
)
from floorplan_engine.plumbing.network import DROP_TURN, Network, Pipe, build_network, drop_bends
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_flat
from tests.plumbing.test_network import network

PLUMBING = Plumbing.model_validate(
    {
        "risers": [{"id": "r1", "room": "bath", "at": [150, 150], "water": True}],
        "fixtures": [
            {"id": "wc", "room": "bath", "type": "wc", "wall": "w4", "offset": 600},
            {"id": "s", "room": "bath", "type": "sink", "wall": "w1", "offset": 1500},
        ],
    }
)


def _net() -> Network:
    plan = make_flat()
    _, contours = validate_plan(plan)
    return build_network(plan, contours, PLUMBING)


def test_quantities_follow_network() -> None:
    net = _net()
    q = quantities(net, PLUMBING)
    assert q["water.outlet16"] == 3 == q["work.water_outlet"]
    assert q["sewer.riser_tee"] == len([p for p in net.pipes_of("sewer") if p.parent is None])
    assert q["water.collector"] == sum(c.outputs for c in net.collectors)
    assert q["water.valve"] == 2  # cold and hot from the riser
    assert "water.meter" not in q  # meters only from the source
    assert set(q) <= set(LINES)


def test_mock_covers_all_lines_and_totals() -> None:
    assert set(MOCK_PRICES) == set(LINES)
    est = build_estimate(_net(), PLUMBING, Prices(None, MockPriceService(extra=MOCK_PRICES)))
    assert est.unpriced == 0 and est.total > 0
    assert all(ln.service for ln in est.lines)


def test_no_prices_is_volumes() -> None:
    est = build_estimate(_net(), PLUMBING, Prices())
    assert est.unpriced == len(est.lines)


def test_all_plumbing_works_are_rough() -> None:
    """Water and sewer go in before screed and tiles: all work is rough; the estimate has no
    finishing work (fixtures, mixers)."""
    assert {v[0] for k, v in LINES.items() if k.startswith("work.")} == {"rough"}
    assert {v[0] for k, v in LINES.items() if not k.startswith("work.")} == {"material"}
    est = build_estimate(_net(), PLUMBING, Prices(None, MockPriceService(extra=MOCK_PRICES)))
    assert est.subtotal("finish") == 0 and est.subtotal("rough") > 0
    assert est.total == est.subtotal("material") + est.work


def test_units_follow_language() -> None:
    def unit(language: Language) -> str:
        est = build_estimate(_net(), PLUMBING, Prices(), language)
        return next(ln.unit for ln in est.lines if ln.key == "water.collector")

    assert unit("ru") == "вых." and unit("uk") == "вих."


def _pipe(path: Sequence[tuple[float, float]], parent: str | None = None) -> Pipe:
    pts = tuple(Vec(x, y) for x, y in path)
    return Pipe("cold_1", "cold", "collector_cold", "s", pts, 16, 900.0, 0.0, parent=parent)


def test_elbow_on_each_plan_turn_and_at_foot_of_each_riser() -> None:
    zigzag = [(0, 0), (1000, 0), (1000, 1000), (2000, 1000)]
    assert elbows(_pipe(zigzag)) == 2 + 2  # two plan turns, verticals at both ends
    assert elbows(_pipe(zigzag, parent="cold_0")) == 2 + 1  # the branch starts with a tee


def test_collector_fittings_rehau() -> None:
    net = _net()  # radial: three Ø16 pipes from the manifolds
    f = water_fittings(net)
    water = [p for p in net.pipes if p.kind != "sewer"]
    n = sum(elbows(p) for p in water)
    assert f["water.outlet16"] == 3 and f["water.eurocone16"] == 3
    assert f["water.elbow16"] == n
    assert f["water.sleeve16"] == 2 * len(water) + 2 * n  # a sleeve for each pipe end in a fitting
    assert not any(k.startswith(("water.tee", "water.adapter")) for k in f)


def test_tee_fittings_rehau() -> None:
    net = network(
        distribution="tee",
        fixtures=[
            {"id": "s", "room": "bath", "type": "sink", "wall": "w1", "offset": 1500},
            {"id": "k", "room": "kitchen", "type": "kitchen_sink", "wall": "w2", "offset": 2000},
        ],
    )
    f = water_fittings(net)
    water = [p for p in net.pipes if p.kind != "sewer"]
    branches = [p for p in water if p.parent is not None]
    roots = [p for p in water if p.parent is None]
    assert branches
    assert f["water.tee20_16"] == len(branches)  # Ø20 main, Ø16 branch
    assert f.get("water.adapter20", 0) + f.get("water.adapter16", 0) == len(roots)  # supply unit
    assert "water.eurocone16" not in f  # no manifold, no eurocones
    sleeves = f.get("water.sleeve16", 0) + f.get("water.sleeve20", 0)
    assert sleeves == sum(2 + 2 * elbows(p) for p in water) + 2 * len(branches)


def test_sewer_turn_90_is_two_bends_45() -> None:
    assert drop_bends(0) == 0
    assert drop_bends(DROP_TURN - 1) == 2  # short offset down: two 45° bends
    assert drop_bends(DROP_TURN) == 4  # down from the drain and onto the floor: two 45° bends each
    net = _net()
    q = quantities(net, PLUMBING)
    sewer = net.pipes_of("sewer")
    assert q["sewer.bend50"] + q["sewer.bend110"] == sum(
        p.bends + drop_bends(p.rise) for p in sewer
    )


def test_sewer_above_floor_is_box_not_floor_chase() -> None:
    sink = {"id": "s", "room": "bath", "type": "sink", "wall": "w4", "offset": 1500}
    plumbing = Plumbing.model_validate(
        {"risers": [{"id": "r1", "room": "bath", "at": [150, 150]}], "fixtures": [sink]}
    )
    plan = make_flat()
    _, contours = validate_plan(plan)
    net = build_network(plan, contours, plumbing)  # a 100 mm inlet does not fit in the screed
    pipe = net.pipes_of("sewer")[0]
    q = quantities(net, plumbing)
    assert q["work.sewer_box"] == round(pipe.surface_length / 1000, 2) > 0
    floor = max(0.0, pipe.length - pipe.surface_length) / 1000
    assert q.get("work.chase_sewer_floor", 0.0) == round(floor, 2)
