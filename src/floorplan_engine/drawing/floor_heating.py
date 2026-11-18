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

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace

import shapely
from ezdxf.colors import RGB
from ezdxf.entities.hatch import Hatch
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.base import BaseLayout
from ezdxf.layouts.layout import Modelspace
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import polylabel

from floorplan_engine.drawing.electrical import insert_symbol, point_attribs
from floorplan_engine.drawing.furniture import rect_label
from floorplan_engine.drawing.ids import tagged
from floorplan_engine.drawing.layers import (
    H_CABLE,
    H_LEAD,
    H_SENSOR,
    H_TEXT,
    H_ZONE,
    LW_HEAT,
    TEXT_DIM_MM,
    TEXT_ROOM_MM,
    TEXT_SMALL_MM,
    text_width,
)
from floorplan_engine.drawing.plan import add_text
from floorplan_engine.drawing.symbols import SYMBOLS
from floorplan_engine.drawing.tables import CELL_PAD, TEXT_GAP, Column, Table, name_width
from floorplan_engine.drawing.titleblock import LW_THIN
from floorplan_engine.electrical.anchors import THERMOSTAT_SIDE, Anchor, point_anchor, symbol_key
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
from floorplan_engine.model.geometry import Contour, Vec, room_geometries
from floorplan_engine.model.scale import sheet
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.model.texts import Language, tr

SENSOR_MM = 1.2  # sensor circle radius on the sheet
# The heated area (decision 2026-11-17): a warm orange, mostly transparent, under the serpentine
# — pale peach on paper, dim amber on the viewer's dark theme; the cut-outs are holes in it
ZONE_TINT = 0xFF9933
ZONE_ALPHA = 0.85  # transparency of the tint, 0 opaque … 1 invisible
# Its border: a red frame with slightly rounded corners, over the tint
FRAME_COLOR = 0xD32F2F  # the zone card frame on the sheet, the area frame in 3D
FRAME_RADIUS_MM = 1.2  # corner radius, sheet mm
# The cable inside is the same red, a little paler: the frame stays the strongest red line
CABLE_COLOR = 0xEF7B7B
LABEL_PAD_MM = 2.5  # the zone label block: padding of its white backing, the frame stays clear
LABEL_RADIUS_MM = 1.0  # its corner radius, sheet mm
LABEL_LW = 18  # 1/100 mm: its frame, thinner than the zone border
CARD_STEP_MM = 2.0  # the card moves off the centre in steps this long, sheet mm
LABEL_WIDTH_MM = 40.0  # a longer zone name wraps at this width, sheet mm
LABEL_SLACK = 1.3  # the backing is this much wider than the font metrics say: viewer fonts differ
LINE_GAP_MM = 0.8  # between the lines of the zone label block
REG_NUMBER_GAP_MM = 0.8  # the controller number this far past its symbol, sheet mm


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


def tint_hatch(layout: BaseLayout) -> Hatch:
    """An empty hatch in the tint of the heated area (the sheet and its legend add the path)."""
    hatch = layout.add_hatch(dxfattribs={"layer": H_ZONE.name, "true_color": ZONE_TINT})
    hatch.set_solid_fill(rgb=RGB.from_hex(f"#{ZONE_TINT:06x}"))
    hatch.transparency = ZONE_ALPHA
    return hatch


def rounded(geom: BaseGeometry, radius: float) -> BaseGeometry:
    """The area with its corners rounded to radius (model mm): opening rounds the outer corners,
    closing the inner ones. A shape the rounding would wipe out stays as it is."""
    if radius <= 0 or geom.is_empty:
        return geom
    out = geom.buffer(-radius, quad_segs=4).buffer(radius, quad_segs=4)
    out = out.buffer(radius, quad_segs=4).buffer(-radius, quad_segs=4)
    return geom if out.is_empty else out


def _tint(msp: Modelspace, geom: BaseGeometry) -> None:
    """The heated area as a pale solid fill: the cut-outs are its holes."""
    for p in getattr(geom, "geoms", [geom]):
        if p.is_empty:
            continue
        p = orient(p, 1.0)  # exterior ccw, holes cw: a nonzero fill keeps the holes empty
        hatch = tint_hatch(msp)
        hatch.paths.add_polyline_path(list(p.exterior.coords)[:-1], is_closed=True)
        for r in p.interiors:
            hatch.paths.add_polyline_path(list(r.coords)[:-1], is_closed=True)


def zone_block(zone: HeatingZone, lang: Language) -> list[tuple[str, float]]:
    """Lines of the zone label block on the sheet: (text, height mm). The room or zone name
    (decision 2026-11-18: not "ТП1", that stays in the table), wrapped to LABEL_WIDTH_MM, then
    area and power, then what the installer lays: section length and pitch."""
    lines = [(t, TEXT_ROOM_MM) for t in _wrap(zone.name, TEXT_ROOM_MM, LABEL_WIDTH_MM)]
    lines.append((f"{_num(zone.area_m2)} м² · {zone.power:.0f} Вт", TEXT_SMALL_MM))
    pitch = f" · {tr('fh_pitch_short', lang)} {zone.pitch:.0f}" if zone.pitch is not None else ""
    lines.append((f"{zone.length:g} м{pitch}", TEXT_SMALL_MM))
    return lines


def _wrap(text: str, height: float, width: float) -> list[str]:
    """Words of text in lines no wider than width (sheet mm, font metrics); a longer word keeps
    a line of its own."""
    out: list[str] = []
    for word in text.split():
        if out and text_width(f"{out[-1]} {word}", height) <= width:
            out[-1] = f"{out[-1]} {word}"
        else:
            out.append(word)
    return out or [text]


def card_centre(area: BaseGeometry, width: float, height: float) -> Vec | None:
    """Centre of the zone card (decision 2026-11-18): the centre of the largest piece of the
    heated area if the card (width × height, model mm) fits inside there, else the spot
    nearest to it where it fits (a CARD_STEP_MM grid on the sheet), else the point deepest
    inside the piece; None for an empty area."""
    piece = max(getattr(area, "geoms", [area]), key=lambda g: float(g.area))
    if piece.is_empty:
        return None
    mid = piece.centroid
    step = sheet(CARD_STEP_MM)
    x0, y0, x1, y1 = piece.bounds
    xs = range(math.floor((x0 - mid.x) / step), math.ceil((x1 - mid.x) / step) + 1)
    ys = range(math.floor((y0 - mid.y) / step), math.ceil((y1 - mid.y) / step) + 1)
    spots = sorted((i * i + j * j, i, j) for i in xs for j in ys)
    shapely.prepare(piece)
    hw, hh = width / 2, height / 2
    for _, i, j in spots:
        x, y = mid.x + i * step, mid.y + j * step
        if piece.contains(box(x - hw, y - hh, x + hw, y + hh)):
            return Vec(x, y)
    p = polylabel(piece, tolerance=10.0)
    return Vec(p.x, p.y)


def _label_block(msp: Modelspace, zone: HeatingZone, lang: Language) -> None:
    """The zone's data in a white card with rounded corners and a thin red frame, in the
    middle of the heated area (card_centre). Drawn after every zone, so nothing on the sheet
    covers it."""
    lines = zone_block(zone, lang)
    k = sheet(1.0)
    width = LABEL_SLACK * max(text_width(t, h) for t, h in lines) + 2 * LABEL_PAD_MM
    height = sum(h for _, h in lines) + LINE_GAP_MM * (len(lines) - 1) + 2 * LABEL_PAD_MM
    c = card_centre(zone.area, k * width, k * height)
    if c is None:
        return
    r = k * LABEL_RADIUS_MM
    card = box(
        c.x - k * width / 2 + r, c.y - k * height / 2 + r,
        c.x + k * width / 2 - r, c.y + k * height / 2 - r,
    ).buffer(r, quad_segs=4)  # fmt: skip
    ring = [(x, y) for x, y in list(card.exterior.coords)[:-1]]
    back = msp.add_hatch(dxfattribs={"layer": H_TEXT.name, "true_color": 0xFFFFFF})
    back.set_solid_fill(rgb=RGB.from_hex("#ffffff"))
    back.paths.add_polyline_path(ring, is_closed=True)
    msp.add_lwpolyline(
        ring,
        close=True,
        dxfattribs={"layer": H_TEXT.name, "lineweight": LABEL_LW, "true_color": FRAME_COLOR},
    )
    y = c.y + k * (height / 2 - LABEL_PAD_MM)
    for text, h in lines:
        add_text(msp, text, Vec(c.x, y - k * h / 2), h, H_TEXT.name)
        y -= k * (h + LINE_GAP_MM)


def _draw_zone(
    msp: Modelspace, zone: HeatingZone, names: Mapping[str, str], lang: Language
) -> None:
    area = rounded(zone.area, sheet(FRAME_RADIUS_MM))
    _tint(msp, area)
    # No red border round the area (decision 2026-11-18): the tint and the cable show it
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
    attribs = {"layer": H_CABLE.name, "lineweight": LW_HEAT, "true_color": CABLE_COLOR}
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
    numbers = number_points(plan, elec)
    for pt in elec.points:
        if pt.id not in regs or pt.room not in geoms:
            continue
        spec = replace(SYMBOLS[symbol_key(pt)], layer=H_TEXT.name)
        anchor = point_anchor(pt, geoms)
        with tagged(msp, "point", pt.id):
            k = sheet(1.0)
            insert_symbol(msp, spec, anchor, xscale=k, yscale=k, attribs=point_attribs(pt))
            number = numbers.get(pt.id)
            if number is not None:
                lines = [v for z in zones if z.spec.thermostat == pt.id for v in z.lead + z.sensor]
                _reg_number(msp, str(number), anchor, lines)
    # Zone cards last: over the tint, the cable, the leads and the controllers
    for zone in zones:
        if zone.route is None:
            continue
        with tagged(msp, "heating", zone.spec.id):
            _label_block(msp, zone, plan.language)


def _reg_number(msp: Modelspace, text: str, anchor: Anchor, lines: Sequence[Vec]) -> None:
    """The controller's number (as in the "Points" table and the zones table) beside its symbol,
    along the wall: the installer finds which controller a zone's lead goes to. The lead and the
    sensor conduit leave the symbol into the room, so the number takes the side of the symbol
    they lean away from (lines: their vertices)."""
    if anchor.inward is None or anchor.wall_dir is None:
        return
    side = anchor.wall_dir
    if lines and sum((v - anchor.pos).dot(side) for v in lines) > 0:
        side = side * -1.0
    mid = anchor.pos + anchor.inward * (anchor.depth - sheet(THERMOSTAT_SIDE / 2))
    at = mid + side * sheet(THERMOSTAT_SIDE / 2 + REG_NUMBER_GAP_MM)
    if abs(side.x) >= abs(side.y):
        align = TextEntityAlignment.MIDDLE_LEFT if side.x > 0 else TextEntityAlignment.MIDDLE_RIGHT
    else:
        align = TextEntityAlignment.BOTTOM_CENTER if side.y > 0 else TextEntityAlignment.TOP_CENTER
    add_text(msp, text, at, TEXT_SMALL_MM, H_TEXT.name, align=align)


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
