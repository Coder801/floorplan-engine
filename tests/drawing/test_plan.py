from __future__ import annotations

from pathlib import Path

import pytest
import shapely
from ezdxf.document import Drawing
from ezdxf.entities.dxfentity import DXFTagStorage
from ezdxf.entities.lwpolyline import LWPolyline
from ezdxf.entities.mtext import MText
from ezdxf.filemanagement import readfile
from shapely.geometry.base import BaseGeometry

from floorplan_engine.drawing.ids import object_id
from floorplan_engine.drawing.plan import (
    HATCH_SCALE_BEARING,
    HATCH_SCALE_PARTITION,
    _fits,
    _place_rows,
    _text_box,
    readable_angle,
    wall_pieces,
)
from floorplan_engine.model.geometry import Vec, WallSegment, room_geometries
from floorplan_engine.model.scale import drawing_scale
from floorplan_engine.model.schema import Plan
from floorplan_engine.sheets.document import build_project_document
from floorplan_engine.validation.plan import validate_plan
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
    # The area outline is a separate closed polyline on a non-printing layer
    (area,) = msp.query('LWPOLYLINE[layer=="A-AREA"]')
    assert isinstance(area, LWPolyline)
    assert area.closed and len(area) == 6
    assert doc.layers.get("A-AREA").dxf.plot == 0
    # The area in the label and in the room schedule are fields from this outline; the total is a
    # sum field
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
    """Two 3000 × 3000 rooms with a 100 partition; exterior walls are load-bearing, 200."""

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
    # The shared partition is described in both rooms, but each of its faces is a single line
    faces = [(a, b) for a, b in lines if abs(a.x - b.x) < 1e-6 and a.x in (3000.0, 3100.0)]
    assert sorted(a.x for a, _ in faces) == [3000.0, 3100.0]
    assert all(abs(abs(b.y - a.y) - 3000) < 1e-6 for a, b in faces)  # end up to the bearing wall
    # No inner face of the exterior wall at the joint: top and bottom have two lines each, not three
    inner_top = [(a, b) for a, b in lines if abs(a.y - 3000) < 1e-6 and abs(b.y - 3000) < 1e-6]
    assert len(inner_top) == 2


def test_hatch_density_by_material(tmp_path: Path) -> None:
    _, doc = _wall_lines(tmp_path)
    scales: dict[str, set[float]] = {}
    for h in doc.modelspace().query("HATCH"):
        oid = object_id(h)
        assert oid is not None
        scales.setdefault(oid[1], set()).add(round(h.dxf.pattern_scale, 3))
    # The partition is hatched once, in the first room; in the second it is already covered
    # The hatch step is proportional to the sheet scale, the material ratio is constant
    (partition,) = scales["a.w3"]
    (bearing,) = scales["a.w2"]
    assert "b.w1" not in scales
    assert partition / bearing == pytest.approx(HATCH_SCALE_PARTITION / HATCH_SCALE_BEARING)
    assert bearing < partition  # load-bearing is denser


def test_window_to_corner_keeps_square_corner() -> None:
    # The top wall's window reaches the right corner: the corner belongs wholly to the right wall,
    # no mitre
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
    corner = shapely.box(4000, 3000, 4400, 3300)  # corner square: right × top thickness
    assert total.intersection(corner).area == pytest.approx(corner.area)


def _wall() -> WallSegment:
    plan = make_plan([{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}])
    _, contours = validate_plan(plan)
    return contours["r"].segment("w2")  # top wall, 4000


def test_row_moves_to_next_level_when_taken() -> None:
    with drawing_scale(50):
        seg = _wall()
        taken: list[BaseGeometry] = []
        first, _ = _place_rows(seg, [[(0.0, seg.length)]], 1.0, 400.0, taken)
        second, _ = _place_rows(seg, [[(0.0, seg.length)]], 1.0, 400.0, taken)
        assert first == 400.0 and second > first  # the same spot is taken: next level


def test_narrow_part_text_is_moved_off_its_part() -> None:
    with drawing_scale(50):
        seg = _wall()
        parts = [(0.0, 1900.0), (1900.0, 2000.0), (2000.0, seg.length)]  # 100 mm is 2 sheet mm
        assert not _fits(1900.0, 2000.0) and _fits(0.0, 1900.0)
        taken: list[BaseGeometry] = []
        level, moves = _place_rows(seg, [parts], 1.0, 400.0, taken)
        assert moves[0][0] is None and moves[0][2] is None
        move = moves[0][1]
        assert move is not None
        narrow = _text_box(seg, 1900.0, 2000.0, level, move)
        for a, b in (parts[0], parts[2]):
            assert narrow.intersection(_text_box(seg, a, b, level, Vec(0.0, 0.0))).area == 0
