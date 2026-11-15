from __future__ import annotations

import pytest
import shapely
from ezdxf.entities.mtext import MText

from floorplan_engine.drawing.callouts import Spot
from floorplan_engine.drawing.dimensions import (
    DIM_LEVEL_STEP_MM,
    Dim,
    dim_linework,
    dim_spots,
    draw_dimension,
    facing_walls,
    free_level,
    layout_dimensions,
    mirrored_wall,
)
from floorplan_engine.drawing.layers import DIM_EXO_MM, new_document
from floorplan_engine.model.geometry import Vec, WallSegment, room_geometries
from floorplan_engine.model.scale import drawing_scale, sheet
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan


def _wall() -> WallSegment:
    plan = make_plan([{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}])
    _, contours = validate_plan(plan)
    return contours["r"].segment("w2")  # top wall, 4000


def test_row_moves_to_next_level_when_taken() -> None:
    with drawing_scale(50):
        seg = _wall()
        rows = [[(0.0, seg.length)]]
        assert free_level("r.w2", seg, rows, 1.0, 400.0, []) == 400.0
        taken = [shapely.box(0.0, 3390.0, 4000.0, 3410.0)]  # on the first level
        assert free_level("r.w2", seg, rows, 1.0, 400.0, taken) == 400.0 + sheet(DIM_LEVEL_STEP_MM)


def test_inside_rows_stay_in_the_room() -> None:
    """A narrow room: the rows do not move across it to the opposite wall."""
    with drawing_scale(50):
        seg = _wall()
        room = shapely.box(0.0, 3000.0 - 700.0, 4000.0, 3000.0)  # 700 deep from the top wall
        rows = [[(0.0, 1000.0), (1000.0, seg.length)], [(0.0, seg.length)]]
        block = shapely.box(0.0, 2000.0, 4000.0, 3000.0 - 300.0)
        assert free_level("r.w2", seg, rows, -1.0, 400.0, [block], room) is None
        assert free_level("r.w2", seg, rows, -1.0, 400.0, [block]) is not None  # no room


def _l_room(k: float) -> list[Dim]:
    """L-shaped room, sizes × k; returns its dimensions at 1:50."""
    walls = [
        {"length": 3000 * k, "bearing": True},
        {"length": 2500 * k},
        {"length": 1000 * k, "turn": 270},
        {"length": 1500 * k},
        {"length": 2000 * k},
        {"length": 4000 * k},
    ]
    plan = make_plan(walls)
    _, contours = validate_plan(plan)
    return layout_dimensions(room_geometries(plan, contours), [])


@pytest.mark.parametrize(("k", "inside"), [(1.0, False), (3.0, True)])
def test_recessed_wall_rows_take_the_shorter_extension_lines(k: float, inside: bool) -> None:
    """The walls of the notch of an L: a shallow notch keeps its rows on the facade line with
    the other walls, a deep one (long extension lines across the void) dimensions them inside
    the room. Walls flush with the facade stay outside in both cases."""
    with drawing_scale(50):
        dims = _l_room(k)
        sides = {d.key: d.offset < 0 for d in dims}
        assert sides["r.w3"] is inside and sides["r.w4"] is inside
        assert not sides["r.w1"] and not sides["r.w2"]


def test_facing_walls_match_partition_sides_of_different_length() -> None:
    """A partition whose sides differ in length (and so do not mirror): still the other side."""
    from floorplan_engine.model.schema import Plan

    def room(rid: str, x: float, partition: int, side: float) -> dict[str, object]:
        lengths = [side, 3000, side, 3000]
        walls = [{"id": f"w{n + 1}", "length": v} for n, v in enumerate(lengths)]
        walls[partition - 1] |= {"thickness": 100}
        return {"id": rid, "name": rid, "origin": [x, 0], "walls": walls}

    plan = Plan.model_validate(
        {
            "name": "тест",
            "default_wall_thickness": 200,
            "source": "text",
            "rooms": [room("a", 0, 3, 3000), room("b", 3100, 1, 2000)],
        }
    )
    _, contours = validate_plan(plan)
    a, b = room_geometries(plan, contours)
    assert mirrored_wall(a, a.contour.segment("w3"), b) is None
    (side,) = facing_walls(a, a.contour.segment("w3"), b)
    assert side.id == "w1"
    assert facing_walls(a, a.contour.segment("w1"), b) == []


def test_label_centre_matches_ezdxf_with_and_without_a_move() -> None:
    """The plan places labels by Dim.centre: ezdxf must draw them exactly there (a moved label
    was once drawn centred on its dimension line)."""
    with drawing_scale(50):
        seg = _wall()
        dim = Dim("r.w2", seg, 0.0, 1000.0, 400.0)
        doc = new_document()
        msp = doc.modelspace()
        moved = dim.centre(Vec(800.0, 0.0))
        for centre in (dim.centre(), moved):
            draw_dimension(msp, dim, Spot(centre, dim.label().box(centre)))
            block = doc.blocks.get(msp[-1].dxf.geometry)
            (text,) = [e for e in block if isinstance(e, MText)]
            assert text.dxf.insert.x == pytest.approx(centre.x)
            assert text.dxf.insert.y == pytest.approx(centre.y)


def test_leader_is_drawn_on_the_dimension_layer() -> None:
    with drawing_scale(50):
        dim = Dim("r.w2", _wall(), 0.0, 100.0, 400.0)
        doc = new_document()
        msp = doc.modelspace()
        a = dim.at(50.0)
        elbow = a + Vec(200.0, 200.0)
        end = elbow + Vec(300.0, 0.0)
        centre = elbow + Vec(150.0, 90.0)
        draw_dimension(msp, dim, Spot(centre, dim.label().box(centre), (a, elbow, end)))
        assert [e.dxf.layer for e in msp.query("LINE")] == ["A-DIMS", "A-DIMS"]


def test_linework_follows_the_dimension_style() -> None:
    with drawing_scale(50):
        seg = _wall()
        dim = Dim("r.w2", seg, 1000.0, 2000.0, 400.0)
        line, ext_a, tick_a, _, tick_b = dim_linework(dim)
        assert line.owner == ext_a.owner == "dimension:r.w2"
        assert tick_a.owner == dim.tick(1000.0) and tick_b.owner == dim.tick(2000.0)
        # Extension line from DIM_EXO_MM off the wall face past the dimension line
        y0, y1 = sorted(y for _, y in ext_a.geom.coords)
        assert y0 == pytest.approx(seg.start.y + sheet(DIM_EXO_MM))
        assert y1 > seg.start.y + 400.0


def test_narrow_label_spots_skip_the_default() -> None:
    with drawing_scale(50):
        seg = _wall()
        narrow, wide = Dim("r.w2", seg, 1900.0, 2000.0, 400.0), Dim("r.w2", seg, 0.0, 1900.0, 400.0)
        assert not narrow.fits() and wide.fits()
        (first, *_) = dim_spots(wide)
        assert first.centre == wide.centre()
        assert first.ignore == {wide.tick(0.0), wide.tick(1900.0)}
        # A narrow label first goes along the line past its extension line, ignoring nothing
        spot = dim_spots(narrow)[0]
        assert spot.ignore == frozenset()
        assert abs((spot.centre - narrow.centre()).x) > 50.0
