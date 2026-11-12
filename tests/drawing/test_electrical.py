from __future__ import annotations

from pathlib import Path

import pytest
from ezdxf import bbox
from ezdxf.document import Drawing
from ezdxf.filemanagement import new as ezdxf_new
from ezdxf.filemanagement import readfile

from floorplan_engine.drawing.electrical import (
    draw_legend,
    legend_rows,
    legend_size,
    wiring_legend_rows,
)
from floorplan_engine.drawing.ids import object_id
from floorplan_engine.electrical.colors import FAMILIES, rgb
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.scale import SCALES
from floorplan_engine.model.schema import Electrical
from floorplan_engine.sheets.document import build_project_document, sheet_png_name
from floorplan_engine.sheets.preview import sheet_layouts
from floorplan_engine.validation.electrical import validate_electrical
from floorplan_engine.validation.issues import parse_model
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan


def _save(doc: Drawing, path: Path) -> Drawing:
    doc.saveas(path, encoding="utf-8")
    reread = readfile(path)
    assert not reread.audit().has_errors
    return reread


def test_board_must_fit_wall() -> None:
    plan = make_plan([{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}])
    elec, _ = parse_model(
        Electrical, {"board": {"room": "r", "wall": "w1", "offset": 100, "height": 1700}}, "e.yaml"
    )
    assert elec is not None
    issues = validate_electrical(elec, plan, {})
    assert [i.path for i in issues] == ["board"]
    assert "не помещается" in issues[0].message


def _rect_plan_elec(data: dict[str, object]) -> tuple[Electrical, Path | None]:
    elec, issues = parse_model(Electrical, data, "e.yaml")
    assert elec is not None, issues
    return elec, None


def test_new_point_types_and_led_strip(tmp_path: Path) -> None:
    plan = make_plan([{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}])
    issues, contours = validate_plan(plan)
    assert not issues
    elec, _ = _rect_plan_elec(
        {
            "points": [
                {
                    "id": "p1",
                    "room": "r",
                    "wall": "w2",
                    "offset": 1000,
                    "type": "sconce",
                    "height": 1300,
                },
                {
                    "id": "switch2",
                    "room": "r",
                    "wall": "w2",
                    "offset": 1500,
                    "type": "switch",
                    "keys": 2,
                    "height": 900,
                },
                {
                    "id": "p2",
                    "room": "r",
                    "wall": "w2",
                    "offset": 2000,
                    "type": "pass_switch",
                    "height": 700,
                },
                # Stack: a socket at the wall, an internet socket under it
                {
                    "id": "p3",
                    "room": "r",
                    "wall": "w1",
                    "offset": 700,
                    "type": "socket",
                    "height": 300,
                },
                {
                    "id": "p4",
                    "room": "r",
                    "wall": "w1",
                    "offset": 700,
                    "type": "data",
                    "height": 300,
                },
                {
                    "id": "p5",
                    "room": "r",
                    "wall": "w1",
                    "offset": 1400,
                    "type": "tv",
                    "height": 1400,
                },
                {
                    "id": "p6",
                    "room": "r",
                    "wall": "w1",
                    "offset": 1650,
                    "type": "led_output",
                    "height": 1650,
                },
                {"id": "p7", "room": "r", "ceiling": [1000, 1000], "type": "downlight"},
                {"id": "p8", "room": "r", "ceiling": [2000, 1500], "type": "pendant"},
            ],
            "led_strips": [{"id": "p9", "room": "r", "wall": "w3", "start": 0, "end": 1400}],
        }
    )
    assert not validate_electrical(elec, plan, contours)
    doc = _save(build_project_document(plan, contours, elec), tmp_path / "project.dxf")
    msp = doc.modelspace()
    names = {i.dxf.name for i in msp.query("INSERT")}
    assert {
        "E_SCONCE",
        "E_SWITCH2",
        "E_PASS_SWITCH",
        "E_DATA",
        "E_TV",
        "E_LED_OUTPUT",
        "E_DOWNLIGHT",
        "E_PENDANT",
    } <= names
    assert len(msp.query('LINE[layer=="E-LED"]')) == 1  # strip on the plan
    legend = sheet_layouts(doc)[1]
    (led_row,) = legend.query('LINE[layer=="E-LED"]')  # legend row on the sheet
    assert object_id(led_row) == ("legend", "led_strip")  # icon for the viewer badge
    assert {object_id(i) for i in legend.query("INSERT") if i.dxf.name == "E_PENDANT"} == {
        ("legend", "pendant")
    }
    # The stack symbols are spread apart: the internet one stands farther from the wall than the
    # socket
    sock = next(
        i for i in msp.query("INSERT") if i.dxf.name == "E_SOCKET" and i.dxf.insert.y < 3500
    )
    data = next(i for i in msp.query("INSERT") if i.dxf.name == "E_DATA" and i.dxf.insert.y < 3500)
    assert data.dxf.insert.x > sock.dxf.insert.x


def test_legend_rows_only_symbol_and_meaning() -> None:
    """The legend is an icon and what it means: no counts and no group colours (those are in
    "Points" and "Groups")."""
    elec, _ = _rect_plan_elec(
        {
            "points": [
                {
                    "id": "a",
                    "room": "r",
                    "wall": "w1",
                    "offset": 500,
                    "type": "socket",
                    "height": 300,
                    "group": "QF1",
                },
                {
                    "id": "b",
                    "room": "r",
                    "wall": "w1",
                    "offset": 900,
                    "type": "switch",
                    "height": 900,
                    "group": "QF2",
                },
            ],
            "board": {"room": "r", "wall": "w2", "offset": 500, "height": 1700},
        }
    )
    rows = legend_rows(elec)
    assert rows[0].text == "Условные обозначения" and rows[0].tag is None
    assert [r.tag for r in rows[1:]] == ["socket", "switch", "board"]
    assert not any("QF" in r.text for r in rows)
    width, height = legend_size(rows)
    assert width > 0 and height > 0


def test_wiring_legend_colour_families() -> None:
    """Wiring legend: one row per colour family present, the sample is its shades in use."""
    elec = Electrical.model_validate(
        {
            "points": [
                {"id": "l", "room": "r", "ceiling": [1, 1], "type": "light", "group": "QF1"},
                *(
                    {
                        "id": f"s{k}",
                        "room": "r",
                        "wall": "w1",
                        "offset": 500 * k,
                        "type": "socket",
                        "height": 300,
                        "group": f"QF{k + 1}",
                    }
                    for k in range(1, 5)
                ),
            ]
        }
    )
    rows = wiring_legend_rows(elec, "uk")
    assert [(r.tag, r.text) for r in rows] == [
        (None, "Кольори ліній"),
        ("wires_light", "Освітлення"),
        ("wires_sockets", "Розетки"),
    ]
    assert len(rows[2].colors) == 4
    doc = ezdxf_new()
    psp = doc.paperspace()
    draw_legend(psp, rows, Vec(0, 100))
    lines = psp.query("LINE")
    sockets = {rgb(c) for c in FAMILIES["sockets"][:3]}  # three shades at most in the sample
    assert {ln.dxf.true_color for ln in lines} == {rgb(FAMILIES["light"][0])} | sockets


@pytest.mark.parametrize(
    ("point", "message"),
    [
        (
            {
                "id": "p10",
                "room": "r",
                "wall": "w1",
                "offset": 1,
                "type": "downlight",
                "height": 2500,
            },
            "только на потолок",
        ),
        (
            {"id": "p11", "room": "r", "ceiling": [1, 1], "type": "socket"},
            "на потолке может быть только",
        ),
        (
            {
                "id": "p12",
                "room": "r",
                "wall": "w1",
                "offset": 1,
                "type": "socket",
                "keys": 2,
                "height": 300,
            },
            "keys",
        ),
    ],
)
def test_point_type_rules(point: dict[str, object], message: str) -> None:
    elec, issues = parse_model(Electrical, {"points": [point]}, "e.yaml")
    assert elec is None
    assert message in " ".join(i.message for i in issues)


def test_led_strip_must_fit_wall() -> None:
    plan = make_plan([{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}])
    elec, _ = _rect_plan_elec(
        {"led_strips": [{"id": "p13", "room": "r", "wall": "w1", "start": 0, "end": 3500}]}
    )
    issues = validate_electrical(elec, plan, {})
    assert [i.path for i in issues] == ["led_strips[0].end"]


def test_cable_channel_is_checked_like_a_wall_object() -> None:
    plan = make_plan([{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}])
    channel = {"id": "tv", "room": "r", "wall": "w1", "offset": 3500, "entry": 400, "exit": 9000}
    elec, _ = _rect_plan_elec({"cable_channels": [channel]})
    issues = validate_electrical(elec, plan, {})
    assert {i.path for i in issues} == {"cable_channels[0].offset", "cable_channels[0].exit"}
    same = {**channel, "exit": 400}
    assert parse_model(Electrical, {"cable_channels": [same]}, "e.yaml")[0] is None


def test_sheets_show_own_layers_at_common_scale(tmp_path: Path) -> None:
    plan = make_plan(
        [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}],
        [{"wall": "w1", "type": "door", "offset": 300, "width": 800}],
    )
    issues, contours = validate_plan(plan)
    assert not issues
    elec, _ = _rect_plan_elec(
        {
            "points": [
                {
                    "id": "s1",
                    "room": "r",
                    "wall": "w2",
                    "offset": 500,
                    "type": "socket",
                    "height": 300,
                }
            ]
        }
    )
    doc = _save(build_project_document(plan, contours, elec), tmp_path / "project.dxf")
    plan_sheet, elec_sheet, points_sheet, walls_sheet = sheet_layouts(doc)
    assert [plan_sheet.name, elec_sheet.name] == ["01 План", "02 Электрика"]
    assert points_sheet.name == "03 Точки"  # point schedule as an appendix at the end
    assert walls_sheet.name == "04 Развёртки"  # and wall elevations
    assert "Layout1" not in doc.layout_names()

    # The scale is a standard one, shared by all sheets
    scales = {
        round(v.dxf.view_height / v.dxf.height, 6)
        for lay in (plan_sheet, elec_sheet)
        for v in lay.viewports()
        if v.dxf.id != 1
    }
    assert len(scales) == 1
    (scale,) = scales
    assert scale in SCALES

    def frozen(layout: object) -> set[str]:
        (vp,) = [v for v in layout.viewports() if v.dxf.id != 1]  # type: ignore[attr-defined]
        assert vp.dxf.view_height / vp.dxf.height == pytest.approx(scale)
        return set(vp.frozen_layers)

    # Plan: no electrical; electrical: walls and openings without dimensions, labels or outlines
    assert {"E-SOCKET", "W-CABLE-SOCKET", "E-TEXT", "A-AREA"} <= frozen(plan_sheet)
    assert {"A-WALL", "A-DOOR", "A-DIMS", "A-TEXT"}.isdisjoint(frozen(plan_sheet))
    assert {"A-DIMS", "A-TEXT", "A-AREA"} <= frozen(elec_sheet)
    assert {"A-WALL", "A-DOOR", "E-SOCKET"}.isdisjoint(frozen(elec_sheet))
    # Frame and title block are on the sheet, not in the model
    assert not doc.modelspace().query('*[layer=="A-SHEET"]')
    assert plan_sheet.query('LINE[layer=="A-SHEET"]')
    assert plan_sheet.dxf_layout.dxf.paper_size.startswith("ISO_full_bleed_A")
    # Legend: symbol block inserts on the electrical sheet
    assert "E_SOCKET" in {i.dxf.name for i in elec_sheet.query("INSERT")}


def test_board_attributes_do_not_inflate_view(tmp_path: Path) -> None:
    """The panel is stretched to its width; its invisible attributes are not, otherwise the sheet
    view inflates.
    """
    plan = make_plan([{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}])
    _, contours = validate_plan(plan)
    elec, _ = _rect_plan_elec(
        {"board": {"room": "r", "wall": "w2", "offset": 1000, "height": 1700, "width": 348}}
    )
    doc = _save(build_project_document(plan, contours, elec), tmp_path / "project.dxf")
    (board,) = doc.modelspace().query("INSERT[name=='E_BOARD']")
    box = bbox.extents([board])
    assert box.size.x < 1000 and box.size.y < 1000
    _, elec_sheet, _ = sheet_layouts(doc)  # no points: no Points sheet; elevation shows the panel
    # A small room gets small paper, not A0 from an inflated extent
    assert elec_sheet.dxf_layout.dxf.paper_size.split("_(")[0][-2:] in ("A4", "A3")


@pytest.mark.parametrize(
    ("tab", "name"),
    [
        ("01 План", "01-plan.png"),
        ("02 Электрика", "02-electrical.png"),
        ("02 Електрика", "02-electrical.png"),
        ("03 Проводка", "03-wiring.png"),
        ("04 Щит", "04-panel.png"),
        ("05 Что-то новое", "05-sheet.png"),
    ],
)
def test_sheet_png_name(tab: str, name: str) -> None:
    assert sheet_png_name(tab) == name


def test_all_sheets_share_one_format(tmp_path: Path) -> None:
    """The set's paper size follows the largest sheet and is the same for all sheets."""
    plan = make_plan([{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}])
    _, contours = validate_plan(plan)
    point = {"room": "r", "wall": "w2", "type": "socket", "height": 300, "group": "QF1"}
    elec, _ = _rect_plan_elec(
        {
            "points": [{"id": f"s{k}", "offset": 500 * k, **point} for k in range(1, 5)],
            "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700},
        }
    )
    doc = _save(build_project_document(plan, contours, elec), tmp_path / "project.dxf")
    sizes = {lay.dxf_layout.dxf.paper_size for lay in sheet_layouts(doc)}
    # plan, electrical, wiring, panel, points, elevations (the notes, the ceiling and the walls:
    # on small paper they take a continuation sheet)
    names = [lay.name for lay in sheet_layouts(doc)]
    assert len(sizes) == 1 and sum("Развёртки" in n for n in names) >= 1
    assert names[:5] == [n for n in names if "Развёртки" not in n][:5]
