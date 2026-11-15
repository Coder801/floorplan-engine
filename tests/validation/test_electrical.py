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
