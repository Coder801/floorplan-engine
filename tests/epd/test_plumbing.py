"""Сантехника для просмотра: карточки, таблицы боковой панели, 3D, развёртки."""

from __future__ import annotations

from floorplan_engine.electrical.elevations import wall_elevations
from floorplan_engine.electrical.pricing import Prices
from floorplan_engine.epd.plumbing import plumbing_objects, plumbing_scene, plumbing_tables
from floorplan_engine.model.geometry import Contour
from floorplan_engine.model.plumbing import Plumbing
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.plumbing.network import Network, build_network
from floorplan_engine.plumbing.rows import water_views
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_flat

PLUMBING = Plumbing.model_validate(
    {
        "risers": [{"id": "r1", "room": "bath", "at": [150, 150]}],
        "fixtures": [
            {"id": "wc", "room": "bath", "type": "wc", "wall": "w4", "offset": 600},
            {
                "id": "s",
                "room": "bath",
                "type": "sink",
                "wall": "w1",
                "offset": 1500,
                "supply_height": 600,
            },
        ],
    }
)


def _setup() -> tuple[Plan, dict[str, Contour], Network]:
    plan = make_flat()
    _, contours = validate_plan(plan)
    return plan, contours, build_network(plan, contours, PLUMBING)


def test_objects_cover_drawn_kinds() -> None:
    plan, _, net = _setup()
    cards = plumbing_objects(plan, PLUMBING, net)
    assert {"fixture:wc", "fixture:s", "riser:r1"} <= set(cards)
    assert all(f"pipe:{p.id}" in cards for p in net.pipes)
    assert cards["fixture:s"].title.startswith("2. ")


def test_tables_and_estimate() -> None:
    plan, _, net = _setup()
    tables = plumbing_tables(plan, PLUMBING, net, Prices())
    assert [t.title for t in tables["plumbing"]] == ["Сантехприборы", "Трубы"]
    assert tables["plumbing"][0].rows[0].keys == ("fixture:wc",)
    assert tables["plumbing_estimate"][0].title == "Ведомость объёмов сантехники"


def test_scene_water_rises_to_outlet_sewer_slopes_down() -> None:
    _, _, net = _setup()
    scene = plumbing_scene(net, 2700)
    cold = next(
        p for p in scene["pipes"].values() if p["kind"] == "cold" and p["key"].endswith("_2")
    )
    assert cold["pts"][-1][2] == 600  # водорозетка умывальника — из источника
    sewer = next(p for p in scene["pipes"].values() if p["kind"] == "sewer")
    zs = [pt[2] for pt in sewer["pts"]]
    assert zs == sorted(zs)  # от стояка к прибору — вверх по уклону
    assert scene["risers"][0]["z"] == [0.0, 2700.0]


def test_water_on_elevations_even_without_electrics() -> None:
    plan, contours, net = _setup()
    walls = wall_elevations(plan, contours, Electrical(), None, water=water_views(PLUMBING, net))
    keys = {e.key: e for e in walls}
    assert set(keys) == {"bath.w4", "bath.w1"}
    sink = keys["bath.w1"]
    assert {v.kind for v in sink.water} == {"cold", "hot", "sewer"}
    assert 600 in sink.heights()


def test_elevation_data_water_has_fixture_name() -> None:
    from floorplan_engine.electrical.elevations import elevation_data

    plan, contours, net = _setup()
    data = elevation_data(plan, contours, Electrical(), None, {}, water=water_views(PLUMBING, net))
    water = [v for e in data for v in e["water"]]
    assert water and all(v["name"] and v["key"] == f"fixture:{v['fixture']}" for v in water)
    assert "Умывальник" in {v["name"] for v in water}  # язык проекта — ru
