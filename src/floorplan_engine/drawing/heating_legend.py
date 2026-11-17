"""Legend of the "Floor heating" sheet (decision 2026-11-17): the heating cable, the cold lead,
the sensor conduit with the sensor, the heated area outline, a cut-out without cable and the
controller; samples drawn as on the sheet, laid out as the plumbing and plan legends
(`drawing/sample_legend.py`). Each sample is the object `legend:<key>` (keys of HEATING_LEGEND):
the viewer takes it as the icon of its legend badge (epd/side.side_legends)."""

from __future__ import annotations

from dataclasses import replace

from ezdxf.layouts.layout import Paperspace

from floorplan_engine.drawing.electrical import insert_symbol
from floorplan_engine.drawing.furniture import rect_label
from floorplan_engine.drawing.ids import tagged
from floorplan_engine.drawing.layers import (
    H_CABLE,
    H_LEAD,
    H_SENSOR,
    H_TEXT,
    H_ZONE,
    LW_HEAT,
)
from floorplan_engine.drawing.sample_legend import LegendDraw, LegendRow, legend_variants
from floorplan_engine.drawing.symbols import SYMBOLS
from floorplan_engine.drawing.titleblock import LW_THIN
from floorplan_engine.electrical.anchors import Anchor
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.schema import PointType
from floorplan_engine.model.texts import Language, tr

SAMPLE_MM = 16.0  # sample width: the cut-out sample holds a label like the sheet ("ванна")
SENSOR_R_MM = 1.2  # as on the sheet (drawing/floor_heating.SENSOR_MM)
BOX_H_MM = 4.5  # the area and cut-out samples: a rectangle this tall
CUT_SAMPLE = "ванна"  # the label inside the cut-out sample: the same in both languages
TURN_MM = 1.2  # serpentine turns in the cable sample: half the pitch


def _cable(psp: Paperspace, mid: Vec) -> None:
    """Two runs with a turn, as the serpentine."""
    attribs = {"layer": H_CABLE.name, "lineweight": LW_HEAT}
    x0, x1 = mid.x, mid.x + SAMPLE_MM - TURN_MM
    psp.add_line((x0, mid.y + TURN_MM), (x1, mid.y + TURN_MM), dxfattribs=attribs)
    psp.add_arc((x1, mid.y), TURN_MM, -90, 90, dxfattribs=attribs)
    psp.add_line((x1, mid.y - TURN_MM), (x0, mid.y - TURN_MM), dxfattribs=attribs)


def _lead(psp: Paperspace, mid: Vec) -> None:
    psp.add_line(
        mid.as_tuple(),
        (mid.x + SAMPLE_MM, mid.y),
        dxfattribs={"layer": H_LEAD.name, "lineweight": LW_HEAT},
    )


def _sensor(psp: Paperspace, mid: Vec) -> None:
    tip = Vec(mid.x + SAMPLE_MM - SENSOR_R_MM, mid.y)
    psp.add_line(
        mid.as_tuple(), tip.as_tuple(), dxfattribs={"layer": H_SENSOR.name, "lineweight": LW_THIN}
    )
    psp.add_circle(tip.as_tuple(), SENSOR_R_MM, dxfattribs={"layer": H_SENSOR.name})


def _box(psp: Paperspace, mid: Vec) -> list[tuple[float, float]]:
    pts = [
        (mid.x, mid.y - BOX_H_MM / 2),
        (mid.x + SAMPLE_MM, mid.y - BOX_H_MM / 2),
        (mid.x + SAMPLE_MM, mid.y + BOX_H_MM / 2),
        (mid.x, mid.y + BOX_H_MM / 2),
    ]
    psp.add_lwpolyline(pts, close=True, dxfattribs={"layer": H_ZONE.name, "lineweight": LW_THIN})
    return pts


def _area(psp: Paperspace, mid: Vec) -> None:
    _box(psp, mid)


def _cut(psp: Paperspace, mid: Vec) -> None:
    """A cut-out as on the sheet: the outline with what it is inside."""
    _box(psp, mid)
    rect_label(
        psp, (mid.x, mid.y - BOX_H_MM / 2, SAMPLE_MM, BOX_H_MM), CUT_SAMPLE, H_TEXT.name, scale=1.0
    )


def _controller(psp: Paperspace, mid: Vec) -> None:
    """The controller symbol on a wall below it, as in the electrical legend."""
    # On H_TEXT, as on the sheet: the symbol's own layer is not shown there
    spec = replace(SYMBOLS[PointType.THERMOSTAT], layer=H_TEXT.name)
    at = Vec(mid.x + SAMPLE_MM / 2, mid.y - spec.depth / 2)
    insert_symbol(psp, spec, Anchor(at, Vec(0, 1), Vec(1, 0), spec.depth))


# Legend rows: the object key of the sample (legend:<key>), the caption text key, the sample
HEATING_LEGEND: tuple[tuple[str, str, LegendDraw], ...] = (
    ("fh_cable", "fh_legend_cable", _cable),
    ("fh_lead", "fh_legend_lead", _lead),
    ("fh_sensor", "fh_legend_sensor", _sensor),
    ("fh_area", "fh_legend_area", _area),
    ("fh_cut", "fh_legend_cut", _cut),
    ("fh_thermostat", "symbol_thermostat", _controller),
)


def _tagged(key: str, draw: LegendDraw) -> LegendDraw:
    def run(psp: Paperspace, mid: Vec) -> None:
        with tagged(psp, "legend", key):
            draw(psp, mid)

    return run


def heating_legend_rows(lang: Language) -> list[tuple[str, str]]:
    """Legend rows for the viewer badge: (key of the sample object, caption), as on the sheet."""
    return [(key, tr(text, lang)) for key, text, _ in HEATING_LEGEND]


def _rows(lang: Language) -> list[LegendRow]:
    return [(tr(text, lang), _tagged(key, draw)) for key, text, draw in HEATING_LEGEND]


def heating_legend_variants(lang: Language) -> list[tuple[float, float, LegendDraw]]:
    """Legend variants next to the title block: (width, height, drawing from the top-left corner),
    k rows per column; the layout takes the lowest one that fits (layout.fit_legend)."""
    return legend_variants(tr("legend", lang), _rows(lang), sample=SAMPLE_MM)
