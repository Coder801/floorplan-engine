"""Electrical drawing: sockets, switches, lights, panel, legend.

Cable routes are not drawn here, only on the wiring sheet (drawing/wiring.py), so the
drawing shows a single way of routing. Model cables give groups their cable type.

Every point is tied to a plan wall (room + wall + offset) or to the room ceiling
(ceiling: from the room origin). Symbols are block inserts from symbols.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.base import BaseLayout
from ezdxf.layouts.layout import Modelspace
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from floorplan_engine.drawing.ids import tagged
from floorplan_engine.drawing.labels import Align, LabelPlacer, Metrics, door_swing
from floorplan_engine.drawing.layers import (
    E_LED,
    E_TEXT,
    TEXT_DIM_MM,
    TEXT_SMALL_MM,
    W_TEXT,
    text_width,
)
from floorplan_engine.drawing.plan import add_text, door_leaf, wall_pieces
from floorplan_engine.drawing.symbols import LEGEND_ORDER, SYMBOLS, SymbolSpec
from floorplan_engine.drawing.tables import TEXT_GAP
from floorplan_engine.electrical.anchors import (
    BOARD_DEPTH,
    Anchor,
    board_anchor,
    point_anchor,
    room_geometry,
    stack_shifts,
    symbol_key,
)
from floorplan_engine.electrical.colors import family_colors
from floorplan_engine.electrical.point_numbers import number_points, ranges
from floorplan_engine.model.geometry import Contour, RoomGeometry, Vec, room_geometries
from floorplan_engine.model.scale import sheet, sheet_scale
from floorplan_engine.model.schema import (
    CEILING_TYPES,
    Electrical,
    ElectricalPoint,
    LedStrip,
    OpeningType,
    Plan,
)
from floorplan_engine.model.texts import Language, tr

LABEL_GAP_MM = 1.0
LINE_STEP_MM = TEXT_SMALL_MM * 1.5
LABEL_CLUSTER_GAP = 250.0  # mm: wall points closer than this share one label
LABEL_PROBE_MM = 1.0  # step for trying label positions, sheet mm
LABEL_REACH = 12  # steps a label may move from its symbol (along the wall and away)
LABEL_FAR = 40  # no room nearby: search up to this many steps, with a leader
LABEL_BAND_MM = 6.0  # how far a label may stick out of the plan extent, sheet mm
LEADER_MIN_MM = 3.0  # farther than this from the symbol: label with a leader
LW_LEADER = 13  # leader line weight, 1/100 mm
LED_INSET_MM = 1.0  # LED strip sits slightly inside the room from the wall face
LW_LED = 35


def insert_symbol(
    msp: BaseLayout,
    spec: SymbolSpec,
    anchor: Anchor,
    xscale: float = 1.0,
    yscale: float = 1.0,
    attribs: dict[str, str] | None = None,
) -> None:
    """Insert a symbol block; attribs: values of the invisible attributes ID, H, GROUP (model)."""
    ref = msp.add_blockref(
        spec.block,
        anchor.pos.as_tuple(),
        dxfattribs={
            "layer": spec.layer,
            "rotation": anchor.rotation,
            "xscale": xscale,
            "yscale": yscale,
        },
    )
    if attribs is not None:
        ref.add_auto_attribs(attribs)
        # The panel is stretched to its own width: attributes would stretch to tens of metres
        # with it and inflate the view extent. Invisible attributes need a normal size at the insert
        for attrib in ref.attribs:
            attrib.dxf.height = sheet(TEXT_SMALL_MM)
            attrib.dxf.width = 1.0
            attrib.dxf.insert = anchor.pos.as_tuple()


def point_attribs(pt: ElectricalPoint) -> dict[str, str]:
    height = "" if pt.height is None else f"{pt.height:g}"
    return {"ID": pt.id, "H": height, "GROUP": pt.group or ""}


# --- Labels ------------------------------------------------------------------


def label_clusters(points: Sequence[ElectricalPoint]) -> list[list[int]]:
    """Points on one wall that follow each other at most LABEL_CLUSTER_GAP apart share one label.
    Ceiling points are labelled one by one."""
    by_wall: dict[tuple[str, str], list[int]] = {}
    out: list[list[int]] = []
    for k, pt in enumerate(points):
        if pt.wall is None or pt.offset is None:
            out.append([k])
        else:
            by_wall.setdefault((pt.room, pt.wall), []).append(k)
    for idx in by_wall.values():
        idx.sort(key=lambda k: points[k].offset or 0.0)
        cluster = [idx[0]]
        for k in idx[1:]:
            prev = points[cluster[-1]].offset or 0.0
            if (points[k].offset or 0.0) - prev <= LABEL_CLUSTER_GAP:
                cluster.append(k)
            else:
                out.append(cluster)
                cluster = [k]
        out.append(cluster)
    return out


def symbol_area(a: Anchor, half: float | None = None) -> BaseGeometry:
    """Symbol extent for label placement: at a wall, depth away from the wall and two depths wide
    (or 2 × half); on the ceiling, a square by radius."""
    if a.inward is None:
        r = a.depth
        return box(a.pos.x - r, a.pos.y - r, a.pos.x + r, a.pos.y + r)
    half = half if half is not None else max(a.depth, sheet(1.5))
    u = a.inward.left() * half
    tip = a.pos + a.inward * a.depth
    corners = [a.pos + u, a.pos - u, tip - u, tip + u]
    return Polygon([c.as_tuple() for c in corners]).envelope


def strip_area(strip: LedStrip, geoms: dict[str, RoomGeometry]) -> BaseGeometry:
    """LED strip is a line along the wall: labels must not sit on it."""
    seg = room_geometry(geoms, strip.room).contour.segment(strip.wall)
    a = seg.point_at(strip.start) + seg.inward * sheet(LED_INSET_MM)
    b = seg.point_at(strip.end) + seg.inward * sheet(LED_INSET_MM)
    return LineString([a.as_tuple(), b.as_tuple()]).buffer(sheet(0.5))


def _opening_areas(geoms: Sequence[RoomGeometry]) -> list[BaseGeometry]:
    """Opening zones: door swings and windows (glazing inside the wall thickness)."""
    out: list[BaseGeometry] = []
    for g in geoms:
        for op in g.room.openings:
            seg = g.contour.segment(op.wall)
            if op.type is OpeningType.DOOR:
                hinge, closed, normal = door_leaf(g, seg, op)
                out.append(door_swing(hinge, closed, normal, op.width))
            elif op.type is OpeningType.WINDOW:
                a, b = op.offset, op.offset + op.width
                corners = [
                    seg.point_at(a),
                    seg.point_at(b),
                    g.outer_point(seg, b),
                    g.outer_point(seg, a),
                ]
                out.append(Polygon([c.as_tuple() for c in corners]))
    return out


def label_placer(
    geoms: Sequence[RoomGeometry],
    symbols: Sequence[BaseGeometry],
    strips: Sequence[BaseGeometry] = (),
) -> LabelPlacer:
    """Place the sheet labels: symbols block both the label and its leader, openings and LED strips
    block only the label."""
    metrics = Metrics(
        line_h=sheet(TEXT_SMALL_MM),
        step=sheet(LINE_STEP_MM),
        gap=sheet(LABEL_GAP_MM),
        probe=sheet(LABEL_PROBE_MM),
        reach=LABEL_REACH,
        far=LABEL_FAR,
        leader_min=sheet(LEADER_MIN_MM),
    )
    walls = unary_union([p.polygon for g in geoms for p in wall_pieces(g)])
    zones = [*_opening_areas(geoms), *strips]
    # Outside the flat outline only within LABEL_BAND_MM of the plan: otherwise the sheet view grows
    frame = box(*unary_union([walls, *zones]).bounds).buffer(
        sheet(LABEL_BAND_MM), join_style="mitre"
    )
    rooms = {g.room.id: Polygon([v.as_tuple() for v in g.contour.vertices]) for g in geoms}
    return LabelPlacer(walls, symbols, zones, metrics, frame, rooms)


ALIGN = {
    Align.LEFT: TextEntityAlignment.MIDDLE_LEFT,
    Align.RIGHT: TextEntityAlignment.MIDDLE_RIGHT,
    Align.CENTER: TextEntityAlignment.MIDDLE_CENTER,
}


def place_label(
    msp: Modelspace,
    placer: LabelPlacer,
    lines: Sequence[str],
    anchor: Anchor,
    own: BaseGeometry | None = None,
    room: str | None = None,
    layer: str = E_TEXT.name,
) -> None:
    """Horizontal label next to a symbol in a free spot (labels.py); far away, with a leader.
    layer is the label layer (the lighting sheet has its own)."""
    lines = [s for s in lines if s]
    if not lines:
        return
    h = sheet(TEXT_SMALL_MM)
    widths = [text_width(t, h) for t in lines]
    placed = placer.place(lines, widths, anchor.pos, anchor.inward, anchor.depth, own, room)
    for text, at in placed.lines:
        add_text(msp, text, at, TEXT_SMALL_MM, layer, align=ALIGN[placed.align])
    if placed.leader is not None:
        a, b = placed.leader
        attribs = {"layer": layer, "lineweight": LW_LEADER}
        msp.add_line(a.as_tuple(), b.as_tuple(), dxfattribs=attribs)


def draw_led_strip(msp: Modelspace, strip: LedStrip, geoms: dict[str, RoomGeometry]) -> None:
    seg = room_geometry(geoms, strip.room).contour.segment(strip.wall)
    a = seg.point_at(strip.start) + seg.inward * sheet(LED_INSET_MM)
    b = seg.point_at(strip.end) + seg.inward * sheet(LED_INSET_MM)
    msp.add_line(a.as_tuple(), b.as_tuple(), dxfattribs={"layer": E_LED.name, "lineweight": LW_LED})
    if strip.note:
        mid = a + (b - a) * 0.5 + seg.inward * sheet(TEXT_SMALL_MM)
        add_text(msp, strip.note, mid, TEXT_SMALL_MM, E_TEXT.name, seg.angle_deg)


# --- Legend ------------------------------------------------------------------


LEGEND_ROW = 9.0  # sheet mm
LEGEND_TEXT_X = 9.0  # from the legend left edge to the caption
LEGEND_SYMBOL_X = 3.0
LEGEND_LINE_W = 6.0  # LED and wire samples, sheet mm
WIRE_SHADES = 3  # wire legend: up to this many shades of a family, one under another
WIRE_SHADE_STEP = 1.2  # sheet mm between them


@dataclass(frozen=True)
class LegendRow:
    """Legend row: a block symbol (key), an LED line or a heading (text only)."""

    text: str
    height: float  # sheet mm
    step: float  # step from the previous row, sheet mm
    key: str | None = None
    led: bool = False
    family: str | None = None  # wire colour family (colors.FAMILIES)
    colors: tuple[int, ...] = ()  # its shades used in the project (true color)

    @property
    def tag(self) -> str | None:
        """Legend object on the sheet (legend:<tag>): the viewer takes the icon for its badge
        from it.
        """
        if self.family is not None:
            return f"wires_{self.family}"
        return LED_STRIP_KEY if self.led else self.key


LED_STRIP_KEY = "led_strip"


def legend_rows(elec: Electrical, language: Language = "ru") -> list[LegendRow]:
    """Legend: a heading, then only the icon and what it means: point symbols present on the sheet,
    the panel and the LED strip. No counts (they are in "Points") and no group colours
    (they are in "Groups")."""
    rows = [LegendRow(tr("legend", language), TEXT_DIM_MM, 0.0)]
    present = {symbol_key(p) for p in elec.points}
    if elec.board is not None:
        present.add("board")
    if elec.media is not None:
        present.add("media")
    for key in (k for k in LEGEND_ORDER if k in present):
        rows.append(LegendRow(tr(f"symbol_{key}", language), TEXT_SMALL_MM, LEGEND_ROW, key=key))
    if elec.led_strips:
        rows.append(
            LegendRow(tr("legend_led_strip", language), TEXT_SMALL_MM, LEGEND_ROW, led=True)
        )
    return rows


def wiring_legend_rows(elec: Electrical, language: Language = "ru") -> list[LegendRow]:
    """Legend of the wiring sheet: line colour families present in the project (lighting,
    sockets, heavy lines, low voltage), each with the shades its groups use. Which colour is
    which group is in "Groups"."""
    rows = [LegendRow(tr("legend_wires", language), TEXT_DIM_MM, 0.0)]
    for family, colors in family_colors(elec).items():
        text = tr(f"wires_{family}", language)
        rows.append(LegendRow(text, TEXT_SMALL_MM, LEGEND_ROW, family=family, colors=colors))
    return rows


def legend_size(rows: Sequence[LegendRow]) -> tuple[float, float]:
    """Legend width and height on the sheet, mm (width from font metrics)."""
    width = max(
        (LEGEND_TEXT_X if r.tag else 0.0) + text_width(r.text, r.height) + TEXT_GAP for r in rows
    )
    height = sum(r.step for r in rows) + rows[0].height + LEGEND_ROW / 2
    return width, height


def draw_legend(psp: BaseLayout, rows: Sequence[LegendRow], top_left: Vec) -> None:
    """Legend on the sheet (sheet mm) from the top-left corner: the symbols are the same symbol
    blocks scaled to the sheet. The icon is tagged as object legend:<tag> (ids.py): the viewer
    takes the primitives for its legend badge from it (epd/artifact.py), the caption is not."""
    x0 = top_left.x
    y = top_left.y - rows[0].height
    left = TextEntityAlignment.MIDDLE_LEFT
    for row in rows:
        y -= row.step
        if row.key is not None:
            spec = SYMBOLS[row.key]
            on_ceiling = row.key in {str(t) for t in CEILING_TYPES}
            depth = spec.depth
            sym_at = Vec(x0 + LEGEND_SYMBOL_X, y if on_ceiling else y - depth / 2)
            anchor = Anchor(sym_at, None if on_ceiling else Vec(0, 1), Vec(1, 0), depth)
            with tagged(psp, "legend", row.key):
                if row.key in ("board", "media"):
                    insert_symbol(psp, spec, anchor, xscale=6.0, yscale=BOARD_DEPTH)
                else:
                    insert_symbol(psp, spec, anchor)
        if row.led:
            with tagged(psp, "legend", LED_STRIP_KEY):
                psp.add_line(
                    (x0, y),
                    (x0 + LEGEND_LINE_W, y),
                    dxfattribs={"layer": E_LED.name, "lineweight": LW_LED},
                )
        if row.family is not None:
            shades = row.colors[:WIRE_SHADES]
            with tagged(psp, "legend", f"wires_{row.family}"):
                for k, color in enumerate(shades):
                    dy = ((len(shades) - 1) / 2 - k) * WIRE_SHADE_STEP
                    psp.add_line(
                        (x0, y + dy),
                        (x0 + LEGEND_LINE_W, y + dy),
                        dxfattribs={
                            "layer": W_TEXT.name,
                            "lineweight": LW_LED,
                            "true_color": color,
                        },
                    )
        x = x0 + (LEGEND_TEXT_X if row.tag else 0.0)
        add_text(psp, row.text, Vec(x, y), row.height, E_TEXT.name, align=left, scale=1.0)


# --- Assembly ----------------------------------------------------------------


def draw_electrical(
    msp: Modelspace, plan: Plan, contours: dict[str, Contour], elec: Electrical
) -> None:
    geoms_list = room_geometries(plan, contours)
    geoms = {g.room.id: g for g in geoms_list}
    for strip in elec.led_strips:
        with tagged(msp, "led_strip", strip.id):
            draw_led_strip(msp, strip, geoms)
    shifts = stack_shifts(elec.points)
    anchors = [point_anchor(pt, geoms, shifts[k]) for k, pt in enumerate(elec.points)]
    for k, pt in enumerate(elec.points):
        with tagged(msp, "point", pt.id):
            k_ins = sheet_scale()
            insert_symbol(
                msp,
                SYMBOLS[symbol_key(pt)],
                anchors[k],
                xscale=k_ins,
                yscale=k_ins,
                attribs=point_attribs(pt),
            )
    cabinets = {"board": elec.board, "media": elec.media}
    cabinet_area = {
        key: symbol_area(board_anchor(b, geoms), b.width / 2)
        for key, b in cabinets.items()
        if b is not None
    }
    symbols = [symbol_area(a) for a in anchors] + list(cabinet_area.values())
    strips = [strip_area(strip, geoms) for strip in elec.led_strips]
    placer = label_placer(geoms_list, symbols, strips)
    numbers = number_points(plan, elec)
    for cluster in label_clusters(elec.points):
        # The symbol carries only numbers (kind and height are in the "Points" table); the label is
        # centred on the group, past the symbol farthest from the wall
        lines = [ranges([numbers[elec.points[k].id] for k in cluster])]
        first, last = anchors[cluster[0]], anchors[cluster[-1]]
        deepest = max(
            (anchors[k] for k in cluster),
            key=lambda a: 0.0 if a.inward is None else (a.pos - first.pos).dot(a.inward) + a.depth,
        )
        center = first.pos + (last.pos - first.pos) * 0.5
        if deepest.inward is not None:
            center += deepest.inward * (deepest.pos - center).dot(deepest.inward)
        label_at = Anchor(center, deepest.inward, deepest.wall_dir, deepest.depth)
        own = unary_union([symbol_area(anchors[k]) for k in cluster])
        with tagged(msp, "label", ",".join(elec.points[k].id for k in cluster)):
            place_label(msp, placer, lines, label_at, own, elec.points[cluster[0]].room)
    for key, b in cabinets.items():
        if b is None:
            continue
        anchor = board_anchor(b, geoms)
        with tagged(msp, "board", key):
            attribs = {"ID": key, "H": f"{b.height:g}", "GROUP": ""}
            insert_symbol(
                msp,
                SYMBOLS[key],
                anchor,
                xscale=b.width,
                yscale=sheet(BOARD_DEPTH),
                attribs=attribs,
            )
            area = cabinet_area[key]
            place_label(msp, placer, [b.name, f"h{b.height:g}"], anchor, area, b.room)
