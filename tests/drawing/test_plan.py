from __future__ import annotations

import math
from pathlib import Path

import pytest
import shapely
from ezdxf.document import Drawing
from ezdxf.entities.dxfentity import DXFTagStorage
from ezdxf.entities.line import Line
from ezdxf.entities.lwpolyline import LWPolyline
from ezdxf.entities.mtext import MText
from ezdxf.entities.text import Text
from ezdxf.filemanagement import readfile
from shapely.geometry.base import BaseGeometry

from floorplan_engine.drawing.ids import object_id
from floorplan_engine.drawing.layers import A_SILL, A_TEXT, new_document
from floorplan_engine.drawing.plan import (
    BEARING_STYLE,
    HATCH_SCALE_BEARING,
    HATCH_SCALE_PARTITION,
    PARTITION_STYLE,
    draw_plan,
    readable_angle,
    wall_pieces,
)
from floorplan_engine.model.geometry import Vec, room_geometries
from floorplan_engine.model.scale import drawing_scale, sheet
from floorplan_engine.model.schema import Plan
from floorplan_engine.sheets.document import build_project_document
from floorplan_engine.sheets.stages import (
    ELECTRICAL_SHEET_LAYERS,
    LIGHTING_SHEET_LAYERS,
    PLAN_SHEET_LAYERS,
    PLUMBING_SHEET_LAYERS,
    WIRING_SHEET_LAYERS,
)
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
        if h.dxf.solid_fill:  # the wall colour under the pattern
            continue
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


def test_sill_label_only_on_the_plan_sheet() -> None:
    plan = make_plan(
        [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}],
        [{"wall": "w2", "type": "window", "offset": 1000, "width": 1000, "sill": 900}],
    )
    _, contours = validate_plan(plan)
    doc = new_document()
    msp = doc.modelspace()
    draw_plan(msp, plan, contours)
    labels = [t for t in msp.query("TEXT") if "900" in t.dxf.text]
    assert [t.dxf.layer for t in labels] == [A_SILL.name]
    assert A_SILL in PLAN_SHEET_LAYERS
    others = (ELECTRICAL_SHEET_LAYERS, LIGHTING_SHEET_LAYERS, WIRING_SHEET_LAYERS)
    assert all(A_SILL not in layers for layers in (*others, PLUMBING_SHEET_LAYERS))


def _sill_plan(width: float, thickness: float = 200) -> Plan:
    return make_plan(
        [
            {"length": 3000},
            {"length": 4000, "thickness": thickness},
            {"length": 3000},
            {"length": 4000},
        ],
        [{"wall": "w2", "type": "window", "offset": 1000, "width": width, "sill": 900}],
    )


def test_sill_label_sits_inside_the_window_on_a_white_background() -> None:
    plan = _sill_plan(1500)
    _, contours = validate_plan(plan)
    doc = new_document()
    msp = doc.modelspace()
    draw_plan(msp, plan, contours)
    (label,) = [t for t in msp.query("TEXT") if isinstance(t, Text) and "900" in t.dxf.text]
    at = Vec(*label.dxf.align_point.vec2)
    (g,) = room_geometries(plan, contours)
    seg = g.contour.segment("w2")
    window = shapely.Polygon(
        [(p.x, p.y) for p in (seg.point_at(1000), seg.point_at(2500))]
        + [
            (p.x, p.y)
            for p in (
                seg.point_at(2500) + seg.outward * 200,
                seg.point_at(1000) + seg.outward * 200,
            )
        ]
    )
    assert window.contains(shapely.Point(at.x, at.y))
    assert readable_angle(seg.angle_deg) == pytest.approx(label.dxf.rotation)  # along the window
    (bg,) = [h for h in msp.query("HATCH") if h.dxf.layer == A_SILL.name]
    assert bg.dxf.solid_fill and bg.dxf.true_color == 0xFFFFFF
    assert object_id(bg) == object_id(label)


def test_sill_label_too_wide_for_the_window_goes_into_the_room() -> None:
    plan = _sill_plan(300)
    _, contours = validate_plan(plan)
    doc = new_document()
    msp = doc.modelspace()
    draw_plan(msp, plan, contours)
    (label,) = [t for t in msp.query("TEXT") if isinstance(t, Text) and "900" in t.dxf.text]
    (g,) = room_geometries(plan, contours)
    room = shapely.Polygon([(v.x, v.y) for v in g.contour.vertices])
    assert room.contains(shapely.Point(*label.dxf.align_point.vec2))
    assert not [h for h in msp.query("HATCH") if h.dxf.layer == A_SILL.name]


def test_walls_are_filled_by_style_under_their_pattern(tmp_path: Path) -> None:
    _, doc = _wall_lines(tmp_path)
    fills: dict[str, list[tuple[bool, int]]] = {}
    for h in doc.modelspace().query("HATCH"):
        oid = object_id(h)
        assert oid is not None
        fills.setdefault(oid[1], []).append((bool(h.dxf.solid_fill), h.dxf.true_color))
    # Solid colour first, then the pattern over it
    assert fills["a.w2"] == [(True, BEARING_STYLE.fill), (False, BEARING_STYLE.color)]
    assert fills["a.w3"] == [(True, PARTITION_STYLE.fill), (False, PARTITION_STYLE.color)]


def test_every_wall_has_its_code_inside_the_room_off_the_door_swing() -> None:
    """A code per wall, tagged as that wall, inside the room and not on the door's swing square."""
    from ezdxf.entities.text import Text

    from floorplan_engine.drawing.plan import door_swing, draw_plan

    plan = make_plan(L_SHAPE, [{"wall": "w6", "type": "door", "offset": 1500, "width": 900}])
    _, contours = validate_plan(plan)
    doc = new_document()
    msp = doc.modelspace()
    draw_plan(msp, plan, contours)
    codes = {
        e.dxf.text: (object_id(e), Vec(e.dxf.align_point.x, e.dxf.align_point.y))
        for e in msp.query("TEXT")
        if isinstance(e, Text) and e.dxf.layer == A_TEXT.name and "." in e.dxf.text
    }
    assert sorted(codes) == ["1.A", "1.B", "1.C", "1.D", "1.E", "1.F"]
    assert codes["1.F"][0] == ("wall", "r.w6")
    g = room_geometries(plan, contours)[0]
    room = shapely.Polygon([(v.x, v.y) for v in g.contour.vertices])
    swing = door_swing(g, g.room.openings[0])
    for _, at in codes.values():
        assert room.contains(shapely.Point(at.x, at.y))
        assert not swing.contains(shapely.Point(at.x, at.y))


# --- Labels off each other and off the linework -----------------------------------------


def _crowded_hall() -> Plan:
    """Hallway 3000 × 1400 with doors on both long walls, short segments of 50–150 mm between
    them, three 50 mm openings 50 mm apart (their numbers have no room by the line) and a
    window with a sill."""
    return make_plan(
        [{"length": 1400}, {"length": 3000}, {"length": 1400}, {"length": 3000}],
        [
            {"wall": "w2", "type": "door", "offset": 100, "width": 700},
            {"wall": "w2", "type": "door", "offset": 850, "width": 700},
            {"wall": "w2", "type": "window", "offset": 1600, "width": 600, "sill": 900},
            {"wall": "w2", "type": "door", "offset": 2250, "width": 600},
            {"wall": "w4", "type": "door", "offset": 150, "width": 800},
            {"wall": "w4", "type": "opening", "offset": 1000, "width": 50},
            {"wall": "w4", "type": "opening", "offset": 1100, "width": 50},
            {"wall": "w4", "type": "opening", "offset": 1200, "width": 50},
            {"wall": "w4", "type": "door", "offset": 1300, "width": 800},
        ],
    )


def _box(at: Vec, angle: float, text: str, height: float) -> BaseGeometry:
    """Outline of a centred text (model mm), slightly shrunk: touching is not overlapping."""
    from floorplan_engine.drawing.callouts import rect
    from floorplan_engine.drawing.layers import text_width

    d = Vec(math.cos(math.radians(angle)), math.sin(math.radians(angle)))
    hw = sheet(text_width(text, height / sheet(1.0))) / 2 - sheet(0.1)
    return rect(at, d, d.left(), hw, height / 2 - sheet(0.1))


def _labels_and_lines(
    doc: Drawing,
) -> tuple[list[tuple[str, BaseGeometry]], list[BaseGeometry], list[Line]]:
    """Text outlines on the plan (codes, sills, room names and areas, dimension numbers),
    dimension and extension lines, and leaders."""
    msp = doc.modelspace()
    labels = [
        (e.dxf.text, _box(Vec(*e.dxf.align_point.vec2), e.dxf.rotation, e.dxf.text, e.dxf.height))
        for e in msp.query("TEXT")
        if isinstance(e, Text)
    ]
    lines: list[BaseGeometry] = []
    for dim in msp.query("DIMENSION"):
        for part in doc.blocks.get(dim.dxf.geometry):
            if isinstance(part, MText):
                at, text = Vec(*part.dxf.insert.vec2), str(part.plain_text())
                labels.append((text, _box(at, part.dxf.rotation, text, part.dxf.char_height)))
            elif isinstance(part, Line):
                lines.append(shapely.LineString([part.dxf.start.vec2, part.dxf.end.vec2]))
    for area in msp.query("MTEXT"):  # room area
        if isinstance(area, MText):
            at, text = Vec(*area.dxf.insert.vec2), str(area.plain_text())
            labels.append((text, _box(at, 0.0, text, area.dxf.char_height)))
    layers = ("A-DIMS", "A-TEXT")
    leaders = [e for e in msp.query("LINE") if isinstance(e, Line) and e.dxf.layer in layers]
    return labels, lines, leaders


def test_crowded_hall_labels_overlap_nothing() -> None:
    """No label sits on another label, a dimension or extension line, or a leader; no two
    leaders cross."""
    plan = _crowded_hall()
    _, contours = validate_plan(plan)
    with drawing_scale(50):
        doc = new_document()
        draw_plan(doc.modelspace(), plan, contours)
        labels, lines, leaders = _labels_and_lines(doc)
    strokes = lines + [shapely.LineString([e.dxf.start.vec2, e.dxf.end.vec2]) for e in leaders]
    assert len(labels) > 20 and leaders
    for k, (text, box) in enumerate(labels):
        for other, box2 in labels[k + 1 :]:
            assert not box.intersects(box2), f"{text} на {other}"
        assert not any(box.intersects(s) for s in strokes), f"{text} на линии"
    paths = [shapely.LineString([e.dxf.start.vec2, e.dxf.end.vec2]) for e in leaders]
    for k, a in enumerate(paths):
        assert not any(a.crosses(b) for b in paths[k + 1 :])


def test_moved_dimension_label_has_a_45_degree_leader() -> None:
    """A label with no room by its dimension line goes out on a leader: from the middle of its
    dimension line at 45°, then a shelf along the text, under it."""
    plan = _crowded_hall()
    _, contours = validate_plan(plan)
    with drawing_scale(50):
        doc = new_document()
        draw_plan(doc.modelspace(), plan, contours)
        _, lines, leaders = _labels_and_lines(doc)
    dims = [e for e in leaders if e.dxf.layer == "A-DIMS"]
    assert dims and len(dims) % 2 == 0
    for slant, shelf in zip(dims[::2], dims[1::2], strict=True):
        dx, dy = (slant.dxf.end - slant.dxf.start).vec2
        assert abs(abs(dx) - abs(dy)) < 1e-6  # 45°
        assert any(s.distance(shapely.Point(slant.dxf.start.vec2)) < 1e-6 for s in lines)
        assert shelf.dxf.start.isclose(slant.dxf.end)
        sx, sy = (shelf.dxf.end - shelf.dxf.start).vec2
        assert abs(sx) < 1e-6 or abs(sy) < 1e-6  # along the text: the walls are square
