from __future__ import annotations

from pathlib import Path

import pytest
from ezdxf import bbox
from ezdxf.document import Drawing
from ezdxf.filemanagement import readfile

from floorplan_engine.draw_electrical import point_label
from floorplan_engine.layers import SCALES
from floorplan_engine.preview import sheet_layouts
from floorplan_engine.schema import Electrical, ElectricalPoint, PointType
from floorplan_engine.sheets import build_project_document, sheet_png_name
from floorplan_engine.validate import (
    parse_model,
    validate_electrical,
    validate_plan,
)
from tests.conftest import make_plan


def _save(doc: Drawing, path: Path) -> Drawing:
    doc.saveas(path, encoding="utf-8")
    reread = readfile(path)
    assert not reread.audit().has_errors
    return reread


def test_point_label() -> None:
    pt = ElectricalPoint(
        id="p1",
        room="r",
        wall="w1",
        offset=1,
        type=PointType.SOCKET,
        height=300,
        count=2,
        group="QF1",
    )
    assert point_label(pt) == "2× h300"  # группа — на трассе и в легенде


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
                # Стопка: розетка у стены, под ней интернет
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
    assert len(msp.query('LINE[layer=="E-LED"]')) == 1  # лента на плане
    legend = sheet_layouts(doc)[1]
    assert len(legend.query('LINE[layer=="E-LED"]')) == 1  # строка легенды — на листе
    # Символы стопки разведены: интернет стоит дальше от стены, чем розетка
    sock = next(
        i for i in msp.query("INSERT") if i.dxf.name == "E_SOCKET" and i.dxf.insert.y < 3500
    )
    data = next(i for i in msp.query("INSERT") if i.dxf.name == "E_DATA" and i.dxf.insert.y < 3500)
    assert data.dxf.insert.x > sock.dxf.insert.x


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
    plan_sheet, elec_sheet = sheet_layouts(doc)
    assert [plan_sheet.name, elec_sheet.name] == ["01 План", "02 Электрика"]
    assert "Layout1" not in doc.layout_names()

    # Масштаб — один из стандартных и общий для всех листов
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

    # План: без электрики; электрика: стены и проёмы без размеров, подписей и контуров
    assert {"E-SOCKET", "W-CABLE", "E-TEXT", "A-AREA"} <= frozen(plan_sheet)
    assert {"A-WALL", "A-DOOR", "A-DIMS", "A-TEXT"}.isdisjoint(frozen(plan_sheet))
    assert {"A-DIMS", "A-TEXT", "A-AREA"} <= frozen(elec_sheet)
    assert {"A-WALL", "A-DOOR", "E-SOCKET"}.isdisjoint(frozen(elec_sheet))
    # Рамка и штамп — на листе, в модели их нет
    assert not doc.modelspace().query('*[layer=="A-SHEET"]')
    assert plan_sheet.query('LINE[layer=="A-SHEET"]')
    assert plan_sheet.dxf_layout.dxf.paper_size.startswith("ISO_full_bleed_A")
    # Легенда — вставки УГО на листе электрики
    assert "E_SOCKET" in {i.dxf.name for i in elec_sheet.query("INSERT")}


def test_board_attributes_do_not_inflate_view(tmp_path: Path) -> None:
    """Щит растянут под ширину; его невидимые атрибуты — нет, иначе вид листа раздувается."""
    plan = make_plan([{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}])
    _, contours = validate_plan(plan)
    elec, _ = _rect_plan_elec(
        {"board": {"room": "r", "wall": "w2", "offset": 1000, "height": 1700, "width": 348}}
    )
    doc = _save(build_project_document(plan, contours, elec), tmp_path / "project.dxf")
    (board,) = doc.modelspace().query("INSERT[name=='E_BOARD']")
    box = bbox.extents([board])
    assert box.size.x < 1000 and box.size.y < 1000
    _, elec_sheet = sheet_layouts(doc)
    # Маленькая комната — маленький формат, а не A0 из-за раздутого габарита
    assert elec_sheet.dxf_layout.dxf.paper_size.split("_(")[0][-2:] in ("A4", "A3")


@pytest.mark.parametrize(
    ("tab", "name"),
    [
        ("01 План", "01-plan.png"),
        ("02 Электрика", "02-electrical.png"),
        ("02 Електрика", "02-electrical.png"),
        ("03 Проводка", "03-wiring.png"),
        ("04 Что-то новое", "04-sheet.png"),
    ],
)
def test_sheet_png_name(tab: str, name: str) -> None:
    assert sheet_png_name(tab) == name


def test_all_sheets_share_one_format(tmp_path: Path) -> None:
    """Формат комплекта — по самому большому листу, у всех листов одинаковый."""
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
    assert len(sheet_layouts(doc)) == 3 and len(sizes) == 1
