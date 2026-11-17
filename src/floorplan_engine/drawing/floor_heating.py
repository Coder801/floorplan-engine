"""The "Floor heating" sheet (decision 2026-11-14): zones, the heating cable as a serpentine
(runs and half-circle turns), the cold lead and the floor sensor conduit to the controller, one
pitch dimension per zone and the zones table. The calculation is electrical/floor_heating.py.

A cut-out without cable (a fixture of plumbing.yaml, an `exclude`) is a thin outline with what it
is in the middle (decision 2026-11-17: no hatching — hatched it read as a wall); furniture is
not drawn here again, its own layer shows the piece with its label.

All of a zone is one object `heating:<id>` (the controller is `point:<id>`, as on the electrical
sheet): the viewer highlights the zone and shows its card.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.layout import Modelspace
from shapely.geometry.base import BaseGeometry

from floorplan_engine.drawing.electrical import insert_symbol, point_attribs
from floorplan_engine.drawing.furniture import rect_label
from floorplan_engine.drawing.ids import tagged
from floorplan_engine.drawing.layers import (
    DIM_STYLE,
    H_CABLE,
    H_LEAD,
    H_SENSOR,
    H_TEXT,
    H_ZONE,
    LW_HEAT,
    TEXT_DIM_MM,
    TEXT_SMALL_MM,
    text_width,
)
from floorplan_engine.drawing.plan import add_text
from floorplan_engine.drawing.symbols import SYMBOLS
from floorplan_engine.drawing.tables import CELL_PAD, TEXT_GAP, Column, Table, name_width
from floorplan_engine.drawing.titleblock import LW_THIN
from floorplan_engine.electrical.anchors import point_anchor, symbol_key
from floorplan_engine.electrical.floor_heating import (
    AREA_TOLERANCE,
    DEFAULT_DENSITY,
    PITCH_MAX,
    PITCH_MIN,
    SENSOR_DEPTH,
    WALL_GAP,
    BlockedSpot,
    HeatingZone,
)
from floorplan_engine.electrical.heating_layout import Arc, Straight
from floorplan_engine.electrical.point_numbers import number_points
from floorplan_engine.model.geometry import Contour, room_geometries
from floorplan_engine.model.scale import sheet
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.model.texts import Language, tr

SENSOR_MM = 1.2  # sensor circle radius on the sheet


def zone_label(zone: HeatingZone) -> str:
    """Zone name on the sheet and in the table: ТП1, ТП2… in electrical.yaml order."""
    return f"ТП{zone.index + 1}"


def _rings(geom: BaseGeometry) -> list[list[tuple[float, float]]]:
    out: list[list[tuple[float, float]]] = []
    for p in getattr(geom, "geoms", [geom]):
        if p.is_empty:
            continue
        out.append([(x, y) for x, y in list(p.exterior.coords)[:-1]])
        out += [[(x, y) for x, y in list(r.coords)[:-1]] for r in p.interiors]
    return out


def spot_label(spot: BlockedSpot, names: Mapping[str, str], lang: Language) -> str:
    """What a cut-out is, for the sheet: the fixture's name (names: id → name, lower case like
    the furniture labels), the exclude's note, else "no cable"."""
    if spot.kind == "fixture":
        return names.get(spot.name, spot.name).lower()
    return spot.name or tr("fh_cut", lang).lower()


def _draw_zone(
    msp: Modelspace, zone: HeatingZone, names: Mapping[str, str], lang: Language
) -> None:
    for ring in _rings(zone.area):
        msp.add_lwpolyline(
            ring, close=True, dxfattribs={"layer": H_ZONE.name, "lineweight": LW_THIN}
        )
    for spot in zone.blocked:
        if spot.kind == "furniture":
            continue  # the furniture layer draws the piece with its label
        for ring in _rings(spot.shape):
            msp.add_lwpolyline(
                ring, close=True, dxfattribs={"layer": H_ZONE.name, "lineweight": LW_THIN}
            )
        x0, y0, x1, y1 = spot.shape.bounds
        rect_label(msp, (x0, y0, x1 - x0, y1 - y0), spot_label(spot, names, lang), H_TEXT.name)
    if zone.route is None:
        return
    attribs = {"layer": H_CABLE.name, "lineweight": LW_HEAT}
    for piece in zone.route.pieces:
        if isinstance(piece, Straight):
            if piece.length > 1e-6:
                msp.add_line(piece.a.as_tuple(), piece.b.as_tuple(), dxfattribs=attribs)
        elif isinstance(piece, Arc) and abs(piece.sweep_deg) > 1e-6:
            start, end = piece.ccw()
            msp.add_arc(piece.center.as_tuple(), piece.radius, start, end, dxfattribs=attribs)
    if len(zone.lead) > 1:
        msp.add_lwpolyline(
            [v.as_tuple() for v in zone.lead],
            dxfattribs={"layer": H_LEAD.name, "lineweight": LW_HEAT},
        )
    if len(zone.sensor) > 1:
        msp.add_lwpolyline(
            [v.as_tuple() for v in zone.sensor],
            dxfattribs={"layer": H_SENSOR.name, "lineweight": LW_THIN},
        )
        tip = zone.sensor[-1]
        msp.add_circle(tip.as_tuple(), sheet(SENSOR_MM), dxfattribs={"layer": H_SENSOR.name})
        back = zone.sensor[-2]
        along = (tip - back) * (1 / max((tip - back).length(), 1e-6))
        at = tip + along * sheet(SENSOR_MM + 1.0)
        add_text(
            msp,
            zone_label(zone),
            at,
            TEXT_SMALL_MM,
            H_TEXT.name,
            align=TextEntityAlignment.MIDDLE_LEFT
            if along.x >= 0
            else TextEntityAlignment.MIDDLE_RIGHT,
        )
    if zone.gap_dim is not None:
        # Left to right or bottom to top: the value reads upright, above or left of the line
        a, b = sorted(zone.gap_dim, key=lambda v: (round(v.x, 3), round(v.y, 3)))
        dim = msp.add_aligned_dim(
            p1=a.as_tuple(),
            p2=b.as_tuple(),
            distance=sheet(4.0),
            dimstyle=DIM_STYLE,
            dxfattribs={"layer": H_TEXT.name},
        )
        dim.render()


def draw_floor_heating(
    msp: Modelspace,
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical,
    zones: Sequence[HeatingZone],
    names: Mapping[str, str] | None = None,
) -> None:
    """Zones in the model on the floor heating layers; their controllers once more on H_TEXT (the
    sheet does not show the sockets layer). names: fixture or obstacle id → its name for the
    cut-out labels (plumbing/floor_spots.spot_names); without them the id is written."""
    for zone in zones:
        with tagged(msp, "heating", zone.spec.id):
            _draw_zone(msp, zone, names or {}, plan.language)
    geoms = {g.room.id: g for g in room_geometries(plan, contours)}
    regs = {z.spec.thermostat for z in zones}
    for pt in elec.points:
        if pt.id not in regs or pt.room not in geoms:
            continue
        spec = replace(SYMBOLS[symbol_key(pt)], layer=H_TEXT.name)
        with tagged(msp, "point", pt.id):
            k = sheet(1.0)
            insert_symbol(
                msp, spec, point_anchor(pt, geoms), xscale=k, yscale=k, attribs=point_attribs(pt)
            )


def _column(title: str, least: float) -> Column:
    """Centred column no narrower than its title (font metrics)."""
    return Column(title, max(least, text_width(title, TEXT_DIM_MM) + 2 * CELL_PAD + TEXT_GAP))


def _num(x: float, digits: int = 1) -> str:
    return f"{x:.{digits}f}".replace(".", ",")


def heating_table(
    plan: Plan, elec: Electrical, zones: Sequence[HeatingZone]
) -> tuple[Table, list[str]] | None:
    """The "Floor heating" table with its notes (assumptions); None without zones."""
    if not zones:
        return None
    lang: Language = plan.language
    numbers = number_points(plan, elec)
    given = any(z.spec.area is not None for z in zones)  # areas from the design: their column
    rows: list[tuple[str, ...]] = []
    for z in zones:
        star_d = "*" if z.density_assumed else ""
        star_l = "*" if z.length_assumed else ""
        reg = numbers.get(z.spec.thermostat)
        source = (_num(z.spec.area, 2) if z.spec.area is not None else "—",) if given else ()
        rows.append(
            (
                zone_label(z) + ("*" if z.spec.auto else ""),
                z.name,
                _num(z.floor_m2),
                *source,
                _num(z.area_m2),
                f"{z.length:g}{star_l}",
                f"{z.power:.0f}*",
                f"{z.pitch:.0f}" if z.pitch is not None else "—",
                f"{z.real_density:.0f} ({z.density:g}{star_d})",
                _num(z.lead_m),
                str(reg) if reg is not None else z.spec.thermostat,
            )
        )
    names = [r[1] for r in rows]
    columns = (
        _column(tr("fh_zone", lang), 12.0),
        Column(tr("fh_room", lang), name_width(names), "left"),
        _column(tr("fh_floor", lang), 18.0),
        *((_column(tr("fh_area_src", lang), 20.0),) if given else ()),
        _column(tr("fh_area", lang), 20.0),
        _column(tr("fh_length", lang), 18.0),
        _column(tr("fh_power", lang), 14.0),
        _column(tr("fh_pitch", lang), 16.0),
        _column(tr("fh_density", lang), 22.0),
        _column(tr("fh_lead", lang), 20.0),
        _column(tr("fh_reg", lang), 20.0),
    )
    total = (
        tr("fh_total", lang),
        "",
        _num(sum(z.floor_m2 for z in zones)),
        *((_num(sum(z.spec.area or 0.0 for z in zones), 2),) if given else ()),
        _num(sum(z.area_m2 for z in zones)),
        f"{sum(z.length for z in zones):g}",
        f"{sum(z.power for z in zones):.0f}",
        "",
        "",
        "",
        "",
    )
    series = {z.series.watts_per_m for z in zones}
    notes = [
        tr("fh_note_cable", lang, w=", ".join(f"{w:g}" for w in sorted(series))),
        tr("fh_note_area", lang, gap=f"{WALL_GAP:g}"),
        tr("fh_note_pitch", lang, a=f"{PITCH_MIN:g}", b=f"{PITCH_MAX:g}"),
        tr("fh_note_sensor", lang, depth=f"{SENSOR_DEPTH:g}"),
        tr("fh_note_assumed", lang, d=f"{DEFAULT_DENSITY:g}"),
    ]
    auto = [zone_label(z) for z in zones if z.spec.auto]
    if auto:
        notes.append(tr("fh_note_auto", lang, zones=", ".join(auto)))
    cut = [f"{zone_label(z)} — {', '.join(z.furniture)}" for z in zones if z.furniture]
    if cut:
        notes.append(tr("fh_note_furniture", lang, gap=f"{WALL_GAP:g}", items="; ".join(cut)))
    if given:
        notes.append(tr("fh_note_area_src", lang, tol=f"{AREA_TOLERANCE:.0%}"))
    return Table(tr("fh_title", lang), columns, tuple(rows), total), notes
