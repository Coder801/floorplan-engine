from __future__ import annotations

from pathlib import Path

import pytest
import shapely
from ezdxf.document import Drawing
from ezdxf.entities.dxfentity import DXFTagStorage
from ezdxf.entities.lwpolyline import LWPolyline
from ezdxf.entities.mtext import MText
from ezdxf.filemanagement import readfile

from floorplan_engine.draw_plan import (
    HATCH_SCALE_BEARING,
    HATCH_SCALE_PARTITION,
    readable_angle,
    room_geometries,
    wall_pieces,
)
from floorplan_engine.geometry import Vec
from floorplan_engine.ids import object_id
from floorplan_engine.schema import Plan
from floorplan_engine.sheets import build_project_document
from floorplan_engine.validate import validate_plan
from tests.conftest import make_plan

L_SHAPE = [
    {"length": 3000, "bearing": True},
    {"length": 2500},
    {"length": 1000, "turn": 270},
    {"length": 1500},
    {"length": 2000},
    {"length": 4000},
]


def test_l_shape_builds(tmp_path: Path) -> None:
    plan = make_plan(L_SHAPE)
    issues, contours = validate_plan(plan)
    assert not issues
    path = tmp_path / "l.dxf"
    build_project_document(plan, contours).saveas(path)
    doc = readfile(path)
    assert not doc.audit().has_errors
    msp = doc.modelspace()
    assert "10,50 м²" in {m.text for m in msp.query("MTEXT") if isinstance(m, MText)}
    # Контур площади — отдельная замкнутая полилиния на непечатаемом слое
    (area,) = msp.query('LWPOLYLINE[layer=="A-AREA"]')
    assert isinstance(area, LWPolyline)
    assert area.closed and len(area) == 6
    assert doc.layers.get("A-AREA").dxf.plot == 0
    # Площадь в подписи и в экспликации — поля от этого контура; итог — поле-сумма
    fields = [o for o in doc.objects if isinstance(o, DXFTagStorage) and o.dxftype() == "FIELD"]
    targets = [t.value for f in fields for t in f.xtags.subclasses[1] if t.code == 331]
    assert targets.count(area.dxf.handle) == 3
    assert any(t.value == "AcExpr" for f in fields for t in f.xtags.subclasses[1] if t.code == 1)


@pytest.mark.parametrize(
    ("angle", "expected"), [(0, 0), (90, 90), (180, 0), (-90, 90), (270, 90), (45, 45)]
)
def test_readable_angle(angle: float, expected: float) -> None:
    assert readable_angle(angle) == pytest.approx(expected)


def _two_rooms() -> Plan:
    """Две комнаты 3000 × 3000 через перегородку 100; наружные стены несущие, 200."""

    def room(rid: str, x: float, inner: str) -> dict[str, object]:
        walls = []
        for k in range(1, 5):
            wall: dict[str, object] = {"id": f"w{k}", "length": 3000}
            if f"w{k}" == inner:
                wall["thickness"] = 100
            else:
                wall |= {"thickness": 200, "bearing": True}
            walls.append(wall)
        return {"id": rid, "name": rid, "origin": [x, 0], "walls": walls}

    return Plan.model_validate(
        {
            "name": "тест",
            "default_wall_thickness": 120,
            "source": "text",
            "rooms": [room("a", 0, "w3"), room("b", 3100, "w1")],
        }
    )


def _wall_lines(tmp_path: Path) -> tuple[list[tuple[Vec, Vec]], Drawing]:
    plan = _two_rooms()
    issues, contours = validate_plan(plan)
    assert not issues
    path = tmp_path / "two.dxf"
    build_project_document(plan, contours).saveas(path)
    doc = readfile(path)
    lines = [
        (Vec(e.dxf.start.x, e.dxf.start.y), Vec(e.dxf.end.x, e.dxf.end.y))
        for e in doc.modelspace().query('LINE[layer=="A-WALL"]')
    ]
    return lines, doc


def test_shared_partition_is_drawn_once(tmp_path: Path) -> None:
    lines, _ = _wall_lines(tmp_path)
    # Общая перегородка описана в обеих комнатах, но каждая её грань — одна линия
    faces = [(a, b) for a, b in lines if abs(a.x - b.x) < 1e-6 and a.x in (3000.0, 3100.0)]
    assert sorted(a.x for a, _ in faces) == [3000.0, 3100.0]
    assert all(abs(abs(b.y - a.y) - 3000) < 1e-6 for a, b in faces)  # торец до несущей
    # Внутренней грани наружной стены на стыке нет: верх и низ — по две линии, а не три
    inner_top = [(a, b) for a, b in lines if abs(a.y - 3000) < 1e-6 and abs(b.y - 3000) < 1e-6]
    assert len(inner_top) == 2


def test_hatch_density_by_material(tmp_path: Path) -> None:
    _, doc = _wall_lines(tmp_path)
    scales: dict[str, set[float]] = {}
    for h in doc.modelspace().query("HATCH"):
        oid = object_id(h)
        assert oid is not None
        scales.setdefault(oid[1], set()).add(round(h.dxf.pattern_scale, 3))
    # Перегородка штрихуется один раз — у первой комнаты; у второй она уже закрыта
    # Шаг штриховки пропорционален масштабу листа, соотношение материалов — постоянное
    (partition,) = scales["a.w3"]
    (bearing,) = scales["a.w2"]
    assert "b.w1" not in scales
    assert partition / bearing == pytest.approx(HATCH_SCALE_PARTITION / HATCH_SCALE_BEARING)
    assert bearing < partition  # несущие — чаще


def test_window_to_corner_keeps_square_corner() -> None:
    # Окно верхней стены доходит до правого угла: угол целиком за правой стеной, без среза
    plan = make_plan(
        [
            {"length": 3000},
            {"length": 4000, "thickness": 300},
            {"length": 3000, "thickness": 400},
            {"length": 4000},
        ],
        [{"wall": "w2", "type": "window", "offset": 2000, "width": 2000, "sill": 900}],
    )
    issues, contours = validate_plan(plan)
    assert not issues
    (g,) = room_geometries(plan, contours)
    total = shapely.unary_union([p.polygon for p in wall_pieces(g)])
    corner = shapely.box(4000, 3000, 4400, 3300)  # квадрат угла: толщина правой × верхней
    assert total.intersection(corner).area == pytest.approx(corner.area)
