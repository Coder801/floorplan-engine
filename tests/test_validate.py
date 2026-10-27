from __future__ import annotations

from pathlib import Path

import yaml

from shtroba.schema import Electrical, Plan
from shtroba.validate import (
    Severity,
    parse_model,
    validate_electrical,
    validate_plan,
    validate_project,
)
from tests.conftest import make_plan

RECT = [{"length": 3200}, {"length": 4100}, {"length": 3200}, {"length": 4100}]


def _errors(plan: Plan) -> list[str]:
    issues, _ = validate_plan(plan)
    return [f"{i.path}: {i.message}" for i in issues if i.severity is Severity.ERROR]


def test_rectangle_has_no_errors() -> None:
    assert _errors(make_plan(RECT)) == []


def test_unclosed_contour_reports_gap_and_walls() -> None:
    walls = [{"length": 3200}, {"length": 4100}, {"length": 3200}, {"length": 4000}]
    errors = _errors(make_plan(walls))
    assert len(errors) == 1
    msg = errors[0]
    assert msg.startswith("rooms[0].walls:")
    assert "ΔX = +100 мм" in msg
    assert "ΔY = +0 мм" in msg
    assert "стена w2: 4100 → 4000 мм" in msg
    assert "стена w4: 4000 → 4100 мм" in msg


def test_small_gap_within_tolerance_is_warning() -> None:
    walls = [{"length": 3200}, {"length": 4100}, {"length": 3205}, {"length": 4100}]
    issues, _ = validate_plan(make_plan(walls))
    assert [i.severity for i in issues] == [Severity.WARNING]


def test_wrong_angles_reported() -> None:
    walls = [{"length": 3000}, {"length": 3000}, {"length": 3000, "turn": 270}, {"length": 3000}]
    errors = _errors(make_plan(walls))
    assert any("walls[*].turn" in e and "360°" in e for e in errors)


def test_opening_beyond_wall() -> None:
    plan = make_plan(RECT, [{"wall": "w1", "type": "door", "offset": 2800, "width": 800}])
    errors = _errors(plan)
    assert len(errors) == 1
    assert errors[0].startswith("rooms[0].openings[0]:")
    assert "выходит за стену w1" in errors[0]
    assert "лишние 400 мм" in errors[0]


def test_openings_overlap() -> None:
    plan = make_plan(
        RECT,
        [
            {"wall": "w2", "type": "window", "offset": 500, "width": 1400, "sill": 850},
            {"wall": "w2", "type": "window", "offset": 1800, "width": 1000, "sill": 850},
        ],
    )
    errors = _errors(plan)
    assert len(errors) == 1
    assert "перекрывается" in errors[0] and "100 мм" in errors[0]


def test_opening_on_missing_wall() -> None:
    plan = make_plan(RECT, [{"wall": "w8", "type": "door", "offset": 0, "width": 800}])
    assert any("стены «w8» нет" in e and "есть: w1, w2, w3, w4" in e for e in _errors(plan))


def test_schema_errors_are_russian_with_path() -> None:
    data = {
        "name": "x",
        "default_wall_thickness": 120,
        "source": "photo",
        "rooms": [{"id": "r", "name": "К", "walls": [{"length": -5}, {"lenght": 1}, {}]}],
    }
    plan, issues = parse_model(Plan, data, "room.yaml")
    assert plan is None
    by_path = {i.path: i.message for i in issues}
    assert "должно быть больше 0" in by_path["rooms[0].walls[0].length"]
    assert "неизвестное поле" in by_path["rooms[0].walls[1].lenght"]
    assert by_path["rooms[0].walls[2].length"] == "обязательное поле не заполнено"


def _electrical(points: list[dict[str, object]], **extra: object) -> Electrical:
    elec, issues = parse_model(Electrical, {"points": points, **extra}, "electrical.yaml")
    assert elec is not None, issues
    return elec


def test_electrical_point_beyond_wall_and_height() -> None:
    plan = make_plan(RECT)
    _, contours = validate_plan(plan)
    elec = _electrical(
        [
            {
                "id": "p1",
                "room": "r",
                "wall": "w2",
                "offset": 5000,
                "type": "socket",
                "height": 300,
            },
            {
                "id": "p2",
                "room": "r",
                "wall": "w10",
                "offset": 100,
                "type": "socket",
                "height": 300,
            },
            {
                "id": "p3",
                "room": "r",
                "wall": "w1",
                "offset": 100,
                "type": "switch",
                "height": 3500,
            },
            {
                "id": "p4",
                "room": "nope",
                "wall": "w1",
                "offset": 100,
                "type": "switch",
                "height": 900,
            },
            {"id": "p5", "room": "r", "ceiling": [9000, 100], "type": "light"},
        ]
    )
    paths = {i.path for i in validate_electrical(elec, plan, contours)}
    assert paths == {
        "points[0].offset",
        "points[1].wall",
        "points[2].height",
        "points[3].room",
        "points[4].ceiling",
    }


def test_electrical_point_needs_placement() -> None:
    _, issues = parse_model(
        Electrical,
        {"points": [{"id": "p1", "room": "r", "type": "socket", "height": 300}]},
        "e.yaml",
    )
    assert issues and issues[0].path == "points[0]"
    assert "wall" in issues[0].message


def test_cable_refs_resolve() -> None:
    plan = make_plan(RECT)
    _, contours = validate_plan(plan)
    elec = _electrical(
        [{"id": "s1", "room": "r", "wall": "w2", "offset": 500, "type": "socket", "height": 300}],
        board={"room": "r", "wall": "w1", "offset": 200, "height": 1700},
        cables=[{"id": "c1", "from": "board", "to": ["s1", "s2"], "cable": "3x2.5"}],
    )
    issues = validate_electrical(elec, plan, contours)
    assert [i.path for i in issues] == ["cables[0].to[1]"]


def test_ids_unique_across_project() -> None:
    plan = make_plan(
        RECT, [{"id": "d1", "wall": "w1", "type": "door", "offset": 100, "width": 800}]
    )
    _, contours = validate_plan(plan)
    elec = _electrical(
        [
            {"id": "d1", "room": "r", "wall": "w2", "offset": 500, "type": "socket", "height": 300},
            {"id": "s1", "room": "r", "wall": "w2", "offset": 900, "type": "socket", "height": 300},
            {
                "id": "s1",
                "room": "r",
                "wall": "w2",
                "offset": 1300,
                "type": "socket",
                "height": 300,
            },
            {
                "id": "board",
                "room": "r",
                "wall": "w2",
                "offset": 1700,
                "type": "socket",
                "height": 300,
            },
        ]
    )
    issues = {i.path: i.message for i in validate_electrical(elec, plan, contours)}
    assert "room.yaml: rooms[0].openings[0]" in issues["points[0].id"]
    assert "points[1]" in issues["points[2].id"]
    assert "щита" in issues["points[3].id"]


def test_wall_ids_unique_in_room() -> None:
    plan = make_plan([{"id": "a", **w} if k < 2 else w for k, w in enumerate(RECT)])
    assert _errors(plan) == ["rooms[0].walls[1].id: стена «a» уже есть в rooms[0].walls[0]"]


def test_yaml_syntax_error(tmp_path: Path) -> None:
    (tmp_path / "room.yaml").write_text("rooms: [\n  - id: x\n", encoding="utf-8")
    report = validate_project(tmp_path)
    assert not report.ok
    assert "синтаксическая ошибка YAML" in report.errors[0].message


def test_studio_profile_fills_empty_stamp_fields(tmp_path: Path) -> None:
    project = tmp_path / "kv1"
    project.mkdir()
    room = {
        "name": "Кв",
        "default_wall_thickness": 120,
        "source": "text",
        "rooms": [
            {"id": "r", "name": "К", "walls": [{"id": f"w{i}", **w} for i, w in enumerate(RECT)]}
        ],
        "sheet": {"stage": "П"},
    }
    (project / "room.yaml").write_text(yaml.safe_dump(room, allow_unicode=True), "utf-8")
    studio = {
        "organization": "MV Group",
        "stage": "Р",
        "signatures": [{"role": "Розробив", "name": "Іваненко"}],
    }
    (tmp_path / "studio.yaml").write_text(yaml.safe_dump(studio, allow_unicode=True), "utf-8")
    report = validate_project(project)
    assert report.ok, report.issues
    assert report.plan is not None
    sheet = report.plan.sheet
    assert sheet.organization == "MV Group" and sheet.stage == "П"  # проект важнее профиля
    assert [(s.role, s.name) for s in sheet.signatures] == [("Розробив", "Іваненко")]


def test_studio_profile_errors_point_to_file(tmp_path: Path) -> None:
    project = tmp_path / "kv1"
    project.mkdir()
    (project / "room.yaml").write_text("name: Кв\n", "utf-8")
    (tmp_path / "studio.yaml").write_text("organisation: опечатка\n", "utf-8")
    report = validate_project(project)
    assert any(i.file == "studio.yaml" and "organisation" in i.path for i in report.errors)
