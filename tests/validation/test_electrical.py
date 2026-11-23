from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from floorplan_engine.model.schema import Electrical, Zone
from floorplan_engine.validation.electrical import validate_electrical
from floorplan_engine.validation.issues import Severity
from floorplan_engine.validation.plan import validate_plan
from floorplan_engine.validation.validate import validate_project
from tests.conftest import make_plan

ROOM = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]
REG = {"id": "t1", "room": "r", "type": "thermostat", "wall": "w4", "offset": 500, "height": 900}


def _issues(fh: dict[str, Any], points: list[dict[str, Any]] | None = None) -> list[str]:
    plan = make_plan(ROOM)
    _, contours = validate_plan(plan)
    elec = Electrical.model_validate(
        {"points": points or [REG], "floor_heating": [{"id": "fh", "room": "r"} | fh]}
    )
    return [f"{i.path}: {i.message}" for i in validate_electrical(elec, plan, contours)]


def test_floor_heating_references_with_paths() -> None:
    assert _issues({"thermostat": "t1"}) == []
    assert _issues({"thermostat": "nope"}) == [
        "floor_heating[0].thermostat: нет точки «nope» — регулятора зоны"
    ]
    socket = REG | {"id": "s1", "type": "socket"}
    (wrong,) = _issues({"thermostat": "s1"}, [socket])
    assert wrong.startswith("floor_heating[0].thermostat: точка «s1» — socket")
    (zone,) = _issues({"thermostat": "t1", "zone": "Кухня"})
    assert zone.startswith("floor_heating[0].zone: в помещении r нет зоны «Кухня»")
    (room,) = _issues({"thermostat": "t1", "room": "x"})
    assert room.startswith("floor_heating[0].room: нет помещения «x»")
    out = {"thermostat": "t1", "exclude": [{"at": [3500, 0], "size": [1000, 500]}]}
    (ex,) = _issues(out)
    assert ex.startswith("floor_heating[0].exclude[0]: прямоугольник at [3500.0, 0.0]")
    dup = _issues({"thermostat": "t1", "id": "t1"})
    assert any(i.startswith("floor_heating[0].id") for i in dup)


def test_layout_remarks_are_warnings_on_the_entry() -> None:
    (remark,) = _issues({"thermostat": "t1", "length": 20})
    assert remark.startswith("floor_heating[0]: тёплый пол «fh»: длины из источника 20 м")


def _project(tmp: Path, elec: dict[str, Any], plumbing: dict[str, Any] | None = None) -> Path:
    plan = make_plan(ROOM)
    (tmp / "room.yaml").write_text(
        yaml.safe_dump(plan.model_dump(mode="json", exclude_defaults=True), allow_unicode=True),
        "utf-8",
    )
    (tmp / "electrical.yaml").write_text(yaml.safe_dump(elec, allow_unicode=True), "utf-8")
    if plumbing is not None:
        (tmp / "plumbing.yaml").write_text(yaml.safe_dump(plumbing, allow_unicode=True), "utf-8")
    return tmp


def test_project_check_puts_plumbing_spots_and_power_in(tmp_path: Path) -> None:
    elec = {"points": [REG], "floor_heating": [{"id": "fh", "room": "r", "thermostat": "t1"}]}
    bath = {"id": "b", "room": "r", "type": "bath", "rect": [0, 0, 1700, 750]}
    report = validate_project(_project(tmp_path, elec, {"obstacles": [bath]}))
    assert report.ok, report.errors
    assert report.electrical is not None and report.source_electrical is not None
    (fh,) = report.electrical.floor_heating
    assert [s.note for s in fh.fixtures] == ["plumbing.yaml: b"]
    reg = report.electrical.points[0]
    assert reg.power is not None and reg.power % 18 == pytest.approx(0)
    assert report.source_electrical.points[0].power == reg.power


def test_fixtures_are_not_written_by_hand_and_own_power_is_compared(tmp_path: Path) -> None:
    spot = {"at": [0, 0], "size": [100, 100]}
    elec = {
        "points": [REG],
        "floor_heating": [{"id": "fh", "room": "r", "thermostat": "t1", "fixtures": [spot]}],
    }
    report = validate_project(_project(tmp_path, elec))
    assert [i.path for i in report.errors] == ["floor_heating[0].fixtures"]
    elec = {
        "points": [REG | {"power": 3000}],
        "floor_heating": [{"id": "fh", "room": "r", "thermostat": "t1"}],
    }
    report = validate_project(_project(tmp_path, elec))
    assert report.ok
    assert "points[0].power" in [i.path for i in report.warnings]
    assert report.electrical is not None and report.electrical.points[0].power == 3000


def test_code_set_fields_and_heating_rooms(tmp_path: Path) -> None:
    fh = {"id": "fh", "room": "r", "thermostat": "t1", "auto": True}
    fh |= {"furniture": [{"at": [0, 0], "size": [100, 100]}]}
    report = validate_project(_project(tmp_path, {"points": [REG], "floor_heating": [fh]}))
    assert [i.path for i in report.errors] == [
        "floor_heating[0].furniture",
        "floor_heating[0].auto",
    ]
    socket = {"id": "s1", "room": "r", "type": "socket", "wall": "w2", "offset": 9, "height": 300}
    reg2 = REG | {"id": "t2"}
    elec = {
        "points": [REG, reg2, socket],
        "floor_heating": [{"id": "fh", "room": "r", "thermostat": "t1"}],
        "heating_rooms": {"t1": "r", "t2": "garage", "s1": "r"},
    }
    report = validate_project(_project(tmp_path, elec))
    assert [i.path for i in report.errors] == ["heating_rooms.s1", "heating_rooms.t2"]
    assert "«garage»" in report.errors[1].message
    assert "heating_rooms.t1" in [i.path for i in report.warnings]


def test_auto_zone_and_area_warnings_point_to_their_fields(tmp_path: Path) -> None:
    # The written zone: the source says 4 m², the layout is 3.8 × 2.8
    elec = {
        "points": [REG],
        "floor_heating": [{"id": "fh", "room": "r", "thermostat": "t1", "area": 4}],
    }
    report = validate_project(_project(tmp_path, elec))
    (area,) = [i for i in report.warnings if i.path == "floor_heating[0].area"]
    assert "по проекту 4,00 м², по раскладке 10,64 м²" in area.message
    # The same controller with no entry: an auto zone, the area from its note
    elec = {"points": [REG | {"note": "тёплый пол, 4 м²"}]}
    report = validate_project(_project(tmp_path, elec))
    assert report.ok and report.electrical is not None
    (fh,) = report.electrical.floor_heating
    assert fh.auto and fh.id == "auto_t1"
    (note,) = [i for i in report.warnings if i.path == "points[0].note"]
    assert "(зона по регулятору)" in note.message and "по подписи регулятора" in note.message


def test_own_power_is_compared_with_the_zones_as_drawn(tmp_path: Path) -> None:
    elec = {"points": [REG], "floor_heating": [{"id": "fh", "room": "r", "thermostat": "t1"}]}
    plain = validate_project(_project(tmp_path, elec))
    assert plain.electrical is not None and plain.electrical.points[0].power is not None
    own = plain.electrical.points[0].power
    # The controller's own power fits the bare floor, but half the floor is under a bath block:
    # the sheet, the panel and the estimate count the smaller zone, so the check does too
    elec["points"] = [REG | {"power": own}]
    assert "points[0].power" not in [i.path for i in validate_project(tmp_path).warnings]
    block = {"id": "b", "room": "r", "type": "bath", "rect": [0, 0, 2000, 3000]}
    report = validate_project(_project(tmp_path, elec, {"obstacles": [block]}))
    (warning,) = [i for i in report.warnings if i.path == "points[0].power"]
    assert f"мощность {own:g} Вт" in warning.message
    # An auto zone counts too: a controller with no entry and its own power
    (tmp_path / "plumbing.yaml").unlink()
    report = validate_project(_project(tmp_path, {"points": [REG | {"power": 5000}]}))
    assert report.electrical is not None and report.electrical.floor_heating[0].auto
    assert "points[0].power" in [i.path for i in report.warnings]


def test_two_zones_on_one_floor_are_an_error() -> None:
    plan = make_plan(ROOM)
    room = plan.rooms[0].model_copy(update={"zones": [Zone(name="Кухня", walls=["w1", "w2"])]})
    plan = plan.model_copy(update={"rooms": [room]})
    _, contours = validate_plan(plan)

    def errors(*zones: dict[str, Any]) -> list[str]:
        fh = [{"id": f"fh{k}", "room": "r", "thermostat": "t1"} | z for k, z in enumerate(zones)]
        elec = Electrical.model_validate({"points": [REG], "floor_heating": fh})
        issues = validate_electrical(elec, plan, contours)
        return [f"{i.path}: {i.message}" for i in issues if i.severity is Severity.ERROR]

    assert errors({"zone": "Кухня"}) == []
    (same,) = errors({}, {})
    assert same.startswith("floor_heating[1].room: тёплый пол «fh1»: помещение r уже греет")
    assert "«fh0»" in same
    (part,) = errors({}, {"zone": "Кухня"})
    assert part.startswith("floor_heating[1].zone: тёплый пол «fh1»: зона «Кухня»")
    assert errors({"zone": "Кухня"}, {"zone": "Кухня"})[0].startswith("floor_heating[1].zone")


def _low(cables: list[dict[str, Any]], media: bool = False) -> list[str]:
    """Issues of a room with internet points d1–d3 and a TV t1 without a group, a socket s1 of
    QF1 and a panel; the given cables (decision 2026-11-17: low-voltage topology)."""
    plan = make_plan(ROOM)
    _, contours = validate_plan(plan)

    def wall(pid: str, kind: str, offset: float, group: str | None = None) -> dict[str, Any]:
        point = {"id": pid, "room": "r", "type": kind, "wall": "w2", "offset": offset}
        return point | {"height": 300} | ({"group": group} if group else {})

    data: dict[str, Any] = {
        "points": [
            wall("d1", "data", 500),
            wall("d2", "data", 1500),
            wall("d3", "data", 2500),
            wall("t1", "tv", 3500),
            wall("s1", "socket", 1000, "QF1"),
        ],
        "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700},
        "cables": [{"cable": "UTP cat.6"} | c for c in cables],
    }
    if media:
        data["media"] = {"room": "r", "wall": "w3", "offset": 500, "height": 1500}
    elec = Electrical.model_validate(data)
    return [
        f"{i.path}: {i.message}"
        for i in validate_electrical(elec, plan, contours)
        if i.severity is Severity.ERROR
    ]


def test_low_voltage_cables_set_their_topology() -> None:
    ok = [
        {"id": "c1", "from": "board", "to": ["d1"]},
        {"id": "c2", "from": "d1", "to": ["d2", "t1"]},
        {"id": "c3", "from": "d2", "to": ["d3"]},
    ]
    assert _low(ok) == []
    assert _low([{"id": "c1", "from": "media", "to": ["d1", "d2"]}], media=True) == []
    (no_media,) = _low([{"id": "c1", "from": "media", "to": ["d1"]}])
    assert no_media == "cables[0].from: ссылка на media, но слаботочный щит не задан"


def test_low_voltage_cable_errors_name_the_field() -> None:
    (mixed,) = _low([{"id": "c1", "from": "board", "to": ["d1", "s1"]}])
    assert mixed.startswith("cables[0].to[1]: точка «s1» не слаботочная без группы")
    (power,) = _low([{"id": "c1", "from": "s1", "to": ["d1"]}])
    assert power.startswith("cables[0].from: слаботочная линия не идёт от точки «s1» (socket")
    (unknown,) = _low([{"id": "c1", "from": "nope", "to": ["d1"]}])
    assert unknown.startswith("cables[0].from: не найдена точка «nope»")
    twice = [
        {"id": "c1", "from": "board", "to": ["d1", "d2"]},
        {"id": "c2", "from": "d1", "to": ["d2"]},
    ]
    (fed,) = _low(twice)
    assert fed.startswith("cables[1].to[0]: точка «d2» уже получает линию: cables[0]")
    ring = [
        {"id": "c1", "from": "d1", "to": ["d2"]},
        {"id": "c2", "from": "d2", "to": ["d3"]},
        {"id": "c3", "from": "d3", "to": ["d1"]},
    ]
    (loop,) = _low(ring)
    assert loop.startswith("cables[2].to[0]: кольцо слаботочных линий: d1 → d2 → d3 → d1")
    (self_fed,) = _low([{"id": "c1", "from": "d1", "to": ["d1"]}])
    assert self_fed.startswith("cables[0].to[0]: кольцо слаботочных линий: d1 → d1")


@pytest.mark.parametrize("supply", ["room", "board"])
def test_long_led_strip_is_a_warning_on_its_entry(supply: str) -> None:
    """A strip of exactly STRIP_MAX_M passes; a longer one is a warning, panel or not."""
    plan = make_plan([{"length": 6000}, {"length": 4000}, {"length": 6000}, {"length": 4000}])
    _, contours = validate_plan(plan)
    strips = [
        {"id": "s_max", "room": "r", "wall": "w2", "start": 0, "end": 4000},
        {"id": "s_ok", "room": "r", "wall": "w1", "start": 500, "end": 5500},
        {"id": "s_long", "room": "r", "wall": "w3", "start": 0, "end": 5600},
    ]
    elec = Electrical.model_validate({"led_supply": supply, "led_strips": strips})
    found = [
        (i.path, i.message)
        for i in validate_electrical(elec, plan, contours)
        if i.severity is Severity.WARNING
    ]
    assert found == [
        (
            "led_strips[2]",
            "LED-лента s_long (Комната, стена w3): 5,6 м — у ленты 12 В длиннее 5 м от одного "
            "конца тускнеет дальний конец и греется ввод; питание с двух концов или из середины, "
            "лента 24 В или участки со своим блоком",
        )
    ]
