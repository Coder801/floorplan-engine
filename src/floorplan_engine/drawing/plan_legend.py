"""Legend of the plan sheet: load-bearing walls, partitions and a window with its sill, each row
only if the plan has it; samples are drawn as on the plan (`plan.wall_fill`,
`plan.draw_sill_in_window`)."""

from __future__ import annotations

from ezdxf.layouts.layout import Paperspace
from shapely.geometry import Polygon

from floorplan_engine.drawing.layers import A_WALL, A_WIND
from floorplan_engine.drawing.plan import (
    BEARING_STYLE,
    PARTITION_STYLE,
    SILL_PAD_MM,
    WallStyle,
    draw_sill_in_window,
    wall_fill,
)
from floorplan_engine.drawing.sample_legend import LegendDraw, LegendRow, legend_variants
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.schema import OpeningType, Plan
from floorplan_engine.model.texts import Language, tr

SAMPLE_MM = 14.0  # sample width: a window sample holds its sill label
WALL_MM = 3.0  # sample wall thickness, sheet mm
STUB_MM = 2.5  # wall on each side of the window sample
SILL_SAMPLE = "900"


def _box(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _outline(psp: Paperspace, area: Polygon) -> None:
    psp.add_lwpolyline(
        list(area.exterior.coords)[:-1], close=True, dxfattribs={"layer": A_WALL.name}
    )


def _wall(style: WallStyle) -> LegendDraw:
    def draw(psp: Paperspace, mid: Vec) -> None:
        area = _box(mid.x, mid.y - WALL_MM / 2, mid.x + SAMPLE_MM, mid.y + WALL_MM / 2)
        wall_fill(psp, area, style, scale=1.0)
        _outline(psp, area)

    return draw


def _window(psp: Paperspace, mid: Vec) -> None:
    """A wall stub, the window (three lines across the wall) with a sill label, a wall stub."""
    y0, y1 = mid.y - WALL_MM / 2, mid.y + WALL_MM / 2
    x0, x1 = mid.x + STUB_MM, mid.x + SAMPLE_MM - STUB_MM
    for area in (_box(mid.x, y0, x0, y1), _box(x1, y0, mid.x + SAMPLE_MM, y1)):
        wall_fill(psp, area, BEARING_STYLE, scale=1.0)
        _outline(psp, area)
    for y in (y0, mid.y, y1):
        psp.add_line((x0, y), (x1, y), dxfattribs={"layer": A_WIND.name})
    centre = Vec((x0 + x1) / 2, mid.y)
    pad = SILL_PAD_MM
    half = (x1 - x0) / 2 - pad
    background = _box(centre.x - half, y0 + pad / 2, centre.x + half, y1 - pad / 2)
    draw_sill_in_window(psp, SILL_SAMPLE, centre, background, 0.0, 1.0)


def legend_rows(plan: Plan, language: Language) -> list[LegendRow]:
    """Rows of the plan legend: what the plan has. Walls not marked load-bearing are drawn and
    named as partitions."""
    walls = [w for r in plan.rooms for w in r.walls]
    rows: list[LegendRow] = []
    if any(w.bearing for w in walls):
        rows.append((tr("legend_bearing", language), _wall(BEARING_STYLE)))
    if any(not w.bearing for w in walls):
        rows.append((tr("legend_partition", language), _wall(PARTITION_STYLE)))
    if any(op.type is OpeningType.WINDOW for r in plan.rooms for op in r.openings):
        rows.append((tr("legend_window", language), _window))
    return rows


def plan_legend_variants(plan: Plan) -> list[tuple[float, float, LegendDraw]]:
    """Legend variants next to the title block (layout.fit_legend); none if the plan has nothing
    to show."""
    rows = legend_rows(plan, plan.language)
    if not rows:
        return []
    return legend_variants(tr("legend", plan.language), rows, SAMPLE_MM)
