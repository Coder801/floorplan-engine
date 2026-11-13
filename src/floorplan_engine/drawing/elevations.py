"""Wall elevation on the sheet (elevations.py → sheet block): drawn directly on the sheet at
the set's scale, like the panel front view. Below: offsets from the left wall corner; on the
right: heights from the floor (ordinate dimensions: close values are spread out, a bent
leader points to the place).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from ezdxf.colors import RGB
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.layout import Paperspace

from floorplan_engine.drawing.ids import tagged
from floorplan_engine.drawing.layers import (
    E_ELEV,
    MIN_TEXT_MM,
    TEXT_DIM_MM,
    TEXT_SMALL_MM,
    text_width,
)
from floorplan_engine.drawing.plan import add_text
from floorplan_engine.electrical.elevations import (
    POST_PITCH_MM,
    CableView,
    WallElevation,
    behind_text,
)
from floorplan_engine.electrical.point_numbers import ranges
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.schema import PointType
from floorplan_engine.model.texts import Language, tr

DARK = 0x29251F
GREY = 0x9A9288
LIGHT = 0xD9D3C8
CHASE = 0xE4DED3
CHASE_LOW = 0xCFE3F3
BACK = 0xB0A99D  # outlets on the far side of the wall are drawn faint
LOW = 0x1F6FB2  # low-voltage
BOX = 0xB3261E
WATER = {"cold": 0x1F77B4, "hot": 0xD62728, "sewer": 0x8C564B}  # as on the "Plumbing" sheet

LW_FLOOR = 50
LW_WALL = 25
GLASS = 0xA9D3F2  # window glass
HANDLE_MM = 1000.0  # door handle above the floor: a mark on the drawing, not a size
HANDLE_INSET_MM, HANDLE_END_MM = 60.0, 180.0  # handle from the free edge of the leaf
LW_THIN = 13
FIXING_HALF_MM = 1.6  # half the fixing stroke across a cable drop, sheet mm
CABLE_PITCH_SHEET = 0.9  # cables of one drop side by side on the sheet, mm
LW_CABLE = 15  # cables along the wall, 1/100 mm
CABLE_OUT = 2.0  # a cable from the ceiling or floor goes on past the wall edge, sheet mm
FIXING_ALPHA = 0.5  # fixings are half transparent: the cables show through them
CABLE_ROOM = 0.5  # either side of a cable that labels keep off, sheet mm

TITLE_H = TEXT_DIM_MM
SIDE_H = TEXT_SMALL_MM  # line under the heading: view from inside, what is behind the wall
SIDE_GAP = 1.0
TITLE_GAP = 3.0
HEAD = TITLE_H + SIDE_GAP + SIDE_H + TITLE_GAP  # heading above the wall
ORD_TEXT = TEXT_SMALL_MM  # dimension labels
ORD_GAP = 0.8  # between neighbouring labels
TICK = 1.2  # leader up to the bend
JOG = 2.0  # bend
MIN_SYMBOL = 1.0  # symbol radius on the sheet, not less than this, mm
DASH, DASH_GAP = 0.8, 0.6  # dashed leaders from an outlet to the scales, sheet mm

SWITCHES = frozenset({PointType.SWITCH, PointType.PASS_SWITCH})
LOW_TYPES = frozenset({PointType.DATA, PointType.TV})

Box = tuple[float, float, float, float]  # x0, y0, x1, y1 in sheet mm


def spread(wanted: Sequence[float], gap: float, lo: float, hi: float) -> list[float]:
    """Label positions along an axis: as close to wanted as possible (ascending), at least gap
    apart, within lo…hi if they fit."""
    out: list[float] = []
    for w in wanted:
        out.append(max(w, lo, out[-1] + gap) if out else max(w, lo))
    if out and out[-1] > hi:
        out[-1] = hi
        for k in range(len(out) - 2, -1, -1):
            out[k] = min(out[k], out[k + 1] - gap)
    return out


@dataclass(frozen=True)
class ElevationPanel:
    width: float
    height: float
    draw: Callable[[Paperspace, Vec], None]


def elevation_panel(
    e: WallElevation, scale: float, language: Language, colors: Mapping[str, int] | None = None
) -> ElevationPanel:
    """Elevation of wall e on the sheet at 1:scale; draw is from the block's top-left corner;
    colors are the group colours of the cables (group_colors), dark without."""
    w, h = e.length / scale, e.top / scale
    right = _ord_width([*e.heights(), e.height])
    bottom = _ord_width([*e.offsets(), 0.0, e.length])
    width = max(
        w + right + JOG,
        text_width(_title(e, language), TITLE_H),
        text_width(_side(e, language), SIDE_H),
    )
    height = HEAD + h + bottom + JOG

    def draw(psp: Paperspace, top_left: Vec) -> None:
        with tagged(psp, "elevation", e.key):
            _draw(psp, e, scale, language, top_left, w, h, colors or {})

    return ElevationPanel(width, height, draw)


def _title(e: WallElevation, language: Language) -> str:
    return tr("elev_title", language, title=e.title, length=f"{e.length:.0f}")


def _side(e: WallElevation, language: Language) -> str:
    """Second line: which side the view is from and what is behind the wall. A shared partition has
    two elevations, and each names the other."""
    return tr("elev_side", language, behind=behind_text(e, language))


def _ord_width(values: Sequence[float]) -> float:
    """Room for ordinate dimensions: leader, bend and the longest label."""
    longest = max((text_width(f"{v:.0f}*", ORD_TEXT) for v in values), default=0.0)
    return TICK + JOG + 0.5 + longest


def _draw(
    psp: Paperspace,
    e: WallElevation,
    scale: float,
    language: Language,
    top_left: Vec,
    w: float,
    h: float,
    colors: Mapping[str, int],
) -> None:
    x0 = top_left.x
    floor = top_left.y - HEAD - h
    top = floor + h
    ceil = floor + e.height / scale  # ceiling; higher only if a point is above the ceiling

    def at(x: float, y: float) -> Vec:
        return Vec(x0 + x / scale, floor + y / scale)

    def line(a: Vec, b: Vec, lw: int = LW_THIN, color: int = DARK) -> None:
        psp.add_line(
            a.as_tuple(),
            b.as_tuple(),
            dxfattribs={"layer": E_ELEV.name, "lineweight": lw, "true_color": color},
        )

    def rect(b: Box, lw: int = LW_THIN, color: int = DARK, fill: int | None = None) -> None:
        bx0, by0, bx1, by1 = b
        if fill is not None:
            hatch = psp.add_hatch(dxfattribs={"layer": E_ELEV.name})
            hatch.set_solid_fill(rgb=RGB.from_hex(f"#{fill:06x}"))
            hatch.paths.add_polyline_path(
                [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)], is_closed=True
            )
        pts = [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)]
        psp.add_lwpolyline(
            pts,
            close=True,
            dxfattribs={"layer": E_ELEV.name, "lineweight": lw, "true_color": color},
        )

    def dashed(a: Vec, b: Vec, color: int = GREY) -> None:
        """Dashes as separate segments, so the line looks the same in DXF, PNG and the viewer."""
        length = (b - a).length()
        if length < 1e-6:
            return
        step = (b - a) * (1 / length)
        t = 0.0
        while t < length:
            line(a + step * t, a + step * min(t + DASH, length), LW_THIN, color)
            t += DASH + DASH_GAP

    def text(
        s: str,
        p: Vec,
        hgt: float = ORD_TEXT,
        angle: float = 0.0,
        align: TextEntityAlignment = TextEntityAlignment.MIDDLE_LEFT,
        color: int = DARK,
    ) -> None:
        size = max(hgt, MIN_TEXT_MM)
        add_text(psp, s, p, size, E_ELEV.name, angle, align, color=color, scale=1.0)

    text(
        _title(e, language),
        Vec(x0, top_left.y - TITLE_H / 2),
        TITLE_H,
        align=TextEntityAlignment.MIDDLE_LEFT,
    )
    text(
        _side(e, language),
        Vec(x0, top_left.y - TITLE_H - SIDE_GAP - SIDE_H / 2),
        SIDE_H,
        align=TextEntityAlignment.MIDDLE_LEFT,
    )

    # Chases go under everything else
    for ch in e.chases:
        half = max((50.0 if ch.wide else 30.0) / 2 / scale, 0.3)
        fill = CHASE_LOW if ch.low else CHASE
        a, b = at(ch.x, ch.y0), at(ch.x, ch.y1)
        if ch.x1 is not None:  # the turn past an opening, along the wall
            c = at(ch.x1, ch.y0)
            rect(
                (min(a.x, c.x) - half, a.y - half, max(a.x, c.x) + half, a.y + half),
                LW_THIN,
                GREY,
                fill,
            )
            continue
        rect((a.x - half, a.y, a.x + half, b.y), LW_THIN, GREY, fill)
    # Cables along the wall (decision 2026-11-12), those of one drop side by side, in the group
    # colour; a fixing is one line across the cables of its drop, their number at the top one.
    # A turn past an opening is an arc of its bend radius, one centre for the bundle, signed
    # "R130–160" (decision 2026-11-13). Labels keep off the cables: a moved one gets a dashed
    # leader to what it names
    pitch = CABLE_PITCH_SHEET
    by_x: dict[float, list[str]] = {}
    for cable in e.cables:
        if cable.x1 is None:
            by_x.setdefault(cable.x, []).append(cable.run)
    turns = _turns(e, by_x, pitch, scale, at)
    cable_boxes: list[Box] = []
    for cable in e.cables:
        color = colors.get(cable.group, DARK)
        turn = turns.get((cable.run, cable.x))
        if cable.x1 is not None:
            if turn is None:
                continue
            centre, radius, corner, end = turn
            psp.add_arc(
                centre.as_tuple(),
                radius,
                *_quarter(corner - centre),
                dxfattribs={"layer": E_ELEV.name, "lineweight": LW_CABLE, "true_color": color},
            )
            line(Vec(centre.x, corner.y), end, LW_CABLE, color)
            room = CABLE_ROOM
            cable_boxes += [
                (
                    min(corner.x, centre.x) - room,
                    min(corner.y, centre.y) - room,
                    max(corner.x, centre.x) + room,
                    max(corner.y, centre.y) + room,
                ),
                (min(centre.x, end.x), end.y - room, max(centre.x, end.x), end.y + room),
            ]
            continue
        dx = (by_x[cable.x].index(cable.run) - (len(by_x[cable.x]) - 1) / 2) * pitch
        a, b = at(cable.x, cable.y0), at(cable.x, cable.y1)
        # The end on the route plane goes on past the wall: the cable runs on in the floor or
        # ceiling; the end at a turn stops where its arc starts
        lo = a.y - CABLE_OUT if cable.y0 <= 0.5 else a.y
        hi = b.y + CABLE_OUT if cable.y1 >= e.height - 0.5 else b.y
        if turn is not None:
            if turn[0].y > turn[2].y:
                lo = turn[0].y
            else:
                hi = turn[0].y
        line(Vec(a.x + dx, lo), Vec(b.x + dx, hi), LW_CABLE, color)
        cable_boxes.append((a.x + dx - CABLE_ROOM, lo, a.x + dx + CABLE_ROOM, hi))
    bends = _bend_labels(e, turns)
    counts: list[tuple[str, Vec, float]] = []  # fixing counts: label, stroke middle, half
    tops = {f.x: max(g.y for g in e.fixings if g.x == f.x) for f in e.fixings}
    for f in e.fixings:
        spot = at(f.x, f.y)
        half = FIXING_HALF_MM + (max(f.count, len(by_x.get(f.x, ()))) - 1) / 2 * pitch
        stroke = psp.add_line(
            (spot.x - half, spot.y),
            (spot.x + half, spot.y),
            dxfattribs={"layer": E_ELEV.name, "lineweight": LW_WALL, "true_color": DARK},
        )
        stroke.transparency = FIXING_ALPHA
        if f.count > 1 and f.y == tops[f.x]:
            counts.append((f"×{f.count}", spot, half))

    # Wall: floor and ceiling lines are thicker, the ends are room corners
    line(Vec(x0, floor), Vec(x0 + w, floor), LW_FLOOR)
    line(Vec(x0, ceil), Vec(x0 + w, ceil), LW_FLOOR)
    line(Vec(x0, floor), Vec(x0, top), LW_WALL)
    line(Vec(x0 + w, floor), Vec(x0 + w, top), LW_WALL)

    for o in e.openings:
        a, b = at(o.x0, o.y0), at(o.x1, o.y1)
        color = GREY if o.assumed else DARK
        rect((a.x, a.y, b.x, b.y), LW_WALL, color, GLASS if o.kind == "window" else 0xFFFFFF)
        if o.kind == "window":  # window frame
            mid = (a.x + b.x) / 2
            line(Vec(mid, a.y), Vec(mid, b.y), LW_THIN, color)
        elif o.kind == "door":  # swing: a triangle pointing to the hinges
            line(Vec(a.x, a.y), Vec((a.x + b.x) / 2, b.y), LW_THIN, LIGHT)
            line(Vec(b.x, a.y), Vec((a.x + b.x) / 2, b.y), LW_THIN, LIGHT)
            if o.hinge is not None:
                free, back = (o.x1, -1.0) if o.hinge == "start" else (o.x0, 1.0)
                gap, grip = free + back * HANDLE_INSET_MM, free + back * HANDLE_END_MM
                line(at(gap, HANDLE_MM), at(grip, HANDLE_MM), LW_WALL, DARK)
        if o.assumed:
            text("*", Vec(b.x - 0.4, b.y - ORD_TEXT), align=TextEntityAlignment.MIDDLE_RIGHT)

    # Dimension scale zones: right of the wall and under the floor; point labels avoid them
    taken: list[Box] = [
        (x0 + w, floor - 1.0, x0 + w + TICK + JOG + 12.0, top + 1.0),
        (x0 - 1.0, floor - TICK - JOG - 12.0, x0 + w + 1.0, floor),
        *cable_boxes,
    ]

    def lead(a: Vec, b: Vec) -> None:
        dashed(a, b, GREY)

    wall = (x0, floor, x0 + w, top)

    if e.board is not None:
        bd = e.board
        a = at(bd.x - bd.width / 2, bd.y - bd.height / 2)
        b = at(bd.x + bd.width / 2, bd.y + bd.height / 2)
        rect((a.x, a.y, b.x, b.y), LW_WALL, DARK, 0xFFFFFF)
        centre = Vec((a.x + b.x) / 2, (a.y + b.y) / 2)
        text(bd.name, centre, align=TextEntityAlignment.MIDDLE_CENTER)
        taken.append((a.x, a.y, b.x, b.y))

    for bx in e.boxes:
        c = at(bx.x, bx.y)
        half = max(bx.size / 2 / scale, 0.8)
        rect((c.x - half, c.y - half, c.x + half, c.y + half), LW_WALL, BOX, 0xFFFFFF)
        taken.append((c.x - half, c.y - half, c.x + half, c.y + half))
        _label(bx.label, c, half, taken, text, BOX, lead)

    # Outlets on the far side of the wall are faint, below their own, without dimensions
    # (those are on the elevation of that side)
    r = max(34.0 / scale, MIN_SYMBOL)  # flush box Ø68
    pitch = max(POST_PITCH_MM / scale, 2 * r)
    for p in e.back:
        c = at(p.x, p.y)
        first = c.x + p.slot * pitch - pitch * (p.posts - 1) / 2
        for k in range(p.posts):
            cx = first + k * pitch
            if p.type in SWITCHES:
                rect((cx - r, c.y - r, cx + r, c.y + r), LW_THIN, BACK)
            else:
                psp.add_circle(
                    (cx, c.y),
                    r,
                    dxfattribs={"layer": E_ELEV.name, "lineweight": LW_THIN, "true_color": BACK},
                )

    # Points: dashes down to the offset scale and right to the height scale, the symbol (each
    # post of a block gets its own circle), the number
    labels: dict[tuple[float, float], tuple[list[int], float]] = {}
    for p in e.points:
        c = at(p.x, p.y)
        half_block = r + pitch * (p.frame - 1) / 2
        dashed(Vec(c.x, c.y - r), Vec(c.x, floor))
        dashed(Vec(c.x + half_block, c.y), Vec(x0 + w, c.y))
        color = LOW if p.type in LOW_TYPES else DARK
        first = c.x + p.slot * pitch - pitch * (p.posts - 1) / 2
        for k in range(p.posts):
            cx = first + k * pitch
            if p.type in SWITCHES:
                rect((cx - r, c.y - r, cx + r, c.y + r), LW_WALL, color, 0xFFFFFF)
            else:
                psp.add_circle(
                    (cx, c.y),
                    r,
                    dxfattribs={"layer": E_ELEV.name, "lineweight": LW_WALL, "true_color": color},
                )
            taken.append((cx - r, c.y - r, cx + r, c.y + r))
        key = (round(c.x, 1), round(c.y, 1))
        nums, half = labels.get(key, ([], 0.0))
        labels[key] = ([*nums, p.number], max(half, half_block))
    for (cx, cy), (nums, half) in labels.items():
        _label(ranges(nums), Vec(cx, cy), half, taken, text, DARK, lead)
    # Plumbing: pipe rise from the floor in the network colour, a water outlet is a filled circle,
    # a drain is a circle of the pipe diameter; fixture number as on the "Plumbing" sheet (* =
    # typical height)
    fixtures: dict[str, tuple[Vec, float, int, bool]] = {}
    for v in e.water:
        c = at(v.x, v.y)
        color = WATER[v.kind]
        rr = max(v.d / 2 / scale, MIN_SYMBOL) if v.kind == "sewer" else max(15.0 / scale, 0.6)
        line(Vec(c.x, floor), Vec(c.x, c.y - rr), LW_WALL, color)
        dashed(Vec(c.x + rr, c.y), Vec(x0 + w, c.y))
        if v.kind == "sewer":
            psp.add_circle(
                c.as_tuple(),
                rr,
                dxfattribs={"layer": E_ELEV.name, "lineweight": LW_FLOOR, "true_color": color},
            )
        else:
            hatch = psp.add_hatch(dxfattribs={"layer": E_ELEV.name, "true_color": color})
            hatch.set_solid_fill(rgb=RGB.from_hex(f"#{color:06x}"))
            hatch.paths.add_edge_path().add_arc(c.as_tuple(), rr, 0, 360)
        taken.append((c.x - rr, c.y - rr, c.x + rr, c.y + rr))
        top_c, top_r, _, assumed = fixtures.get(v.fixture, (c, rr, v.number, v.assumed))
        if c.y >= top_c.y:
            top_c, top_r = c, rr
        fixtures[v.fixture] = (top_c, top_r, v.number, assumed or v.assumed)
    for c, rr, number, assumed in fixtures.values():
        _label(f"{number}{'*' if assumed else ''}", c, rr, taken, text, WATER["sewer"], lead)
    # Fixing counts and turn radii after the numbers, where there is room
    for note, spot, half in counts:
        _label(note, spot, half, taken, text, DARK, lead, wall)
    for note, arc_mid in bends:
        _label(note, arc_mid, 0.3, taken, text, DARK, lead, wall)
    # Numbers of the far side's outlets come after our own: the spot by the symbol goes to ours
    # first
    for p in e.back:
        c = at(p.x, p.y)
        _label(str(p.number), c, r + pitch * (p.frame - 1) / 2, taken, text, BACK)

    _ordinates_x(e, scale, x0, floor, w, line, text)
    _ordinates_y(e, scale, x0 + w, floor, top, line, text)


Turn = tuple[Vec, float, Vec, Vec]  # arc centre, radius, lane corner, end at the point


def _turns(
    e: WallElevation,
    by_x: Mapping[float, Sequence[str]],
    pitch: float,
    scale: float,
    at: Callable[[float, float], Vec],
) -> dict[tuple[str, float], Turn]:
    """Turns past an opening on the sheet, by (run, drop x): the lanes of one corner bend round
    one centre, the inner lane (nearest the side the turn goes to) at its bend radius, each
    outer one a lane further (concentric, like the bundle); the radius never takes more than
    the arms have. A cable without a radius turns at a sharp corner."""
    verticals = {(c.run, c.x): c for c in e.cables if c.x1 is None}
    corners: dict[tuple[float, float, bool, bool], list[CableView]] = {}
    for c in e.cables:
        v = verticals.get((c.run, c.x))
        if c.x1 is None or v is None or c.run not in by_x.get(c.x, ()):
            continue
        up = v.y1 > c.y0 + 0.5  # the drop goes up from the turn: a ceiling route
        corners.setdefault((c.x, c.y0, c.x1 > c.x, up), []).append(c)
    out: dict[tuple[str, float], Turn] = {}
    for (x, y, right, up), turning in corners.items():
        sx, sy = (1.0 if right else -1.0), (1.0 if up else -1.0)
        runs = by_x[x]

        def lane(c: CableView, runs: Sequence[str] = runs) -> float:
            return (runs.index(c.run) - (len(runs) - 1) / 2) * pitch

        inner = max(turning, key=lambda c: lane(c) * sx)
        corner = at(x, y)
        ix, iy = corner.x + lane(inner), corner.y + lane(inner) * sx * sy
        reach = min(
            abs(at(c.x1, y).x - ix) for c in turning if c.x1 is not None
        )  # the horizontal arm
        rise = min(
            abs(at(x, verticals[(c.run, x)].y1 if up else verticals[(c.run, x)].y0).y - iy)
            for c in turning
        )
        r0 = min((inner.radius or 0.0) / scale, reach, rise)
        centre = Vec(ix + sx * r0, iy + sy * r0)
        for c in turning:
            t = (lane(inner) - lane(c)) * sx
            k = Vec(corner.x + lane(c), iy - sy * t)
            end = at(c.x1 if c.x1 is not None else x, y).x
            out[(c.run, x)] = (centre, r0 + t, k, Vec(end, k.y))
    return out


def _quarter(v: Vec) -> tuple[float, float]:
    """Start and end angle, degrees, of the quarter arc round a centre: the lane corner lies at
    v from the centre, the arc runs between the two tangent points either side of it."""
    a = 180.0 if v.x < 0 else 0.0  # the tangent point on the drop
    b = 270.0 if v.y < 0 else 90.0  # the tangent point on the arm along the wall
    return (a, b) if (b - a) % 360 == 90 else (b, a)


def _bend_labels(
    e: WallElevation, turns: Mapping[tuple[str, float], Turn]
) -> list[tuple[str, Vec]]:
    """One radius label per turning bundle: "R130–160" inner to outer, "R138" for one cable;
    with the middle of the outer lane's arc it names."""
    groups: dict[tuple[float, float], list[tuple[float, Vec, Vec]]] = {}
    for c in e.cables:
        turn = turns.get((c.run, c.x))
        if c.x1 is None or turn is None or c.radius is None:
            continue
        centre, radius, corner, _ = turn
        groups.setdefault((centre.x, centre.y), []).append((radius, corner, centre))
    out: list[tuple[str, Vec]] = []
    radii_by = {
        key: sorted(
            c.radius
            for c in e.cables
            if c.x1 is not None
            and c.radius is not None
            and (t := turns.get((c.run, c.x))) is not None
            and (t[0].x, t[0].y) == key
        )
        for key in groups
    }
    for key, members in groups.items():
        _, corner, centre = max(members, key=lambda m: m[0])  # the outer lane
        lo, hi = radii_by[key][0], radii_by[key][-1]
        label = f"R{lo:.0f}" if round(lo) == round(hi) else f"R{lo:.0f}–{hi:.0f}"
        out.append((label, centre + (corner - centre) * math.sqrt(0.5)))
    return out


LABEL_RINGS = 6  # how far a label may go from its symbol, in label heights


def _label(
    s: str,
    c: Vec,
    half: float,
    taken: list[Box],
    text: Callable[..., None],
    color: int,
    lead: Callable[[Vec, Vec], None] | None = None,
    bounds: Box | None = None,
) -> None:
    """Label next to a symbol: right, left, above or below, wherever is free; if none is, further
    out ring by ring (also the corners), with a dashed leader to the symbol. With bounds (the
    wall) a moved label stays within them."""
    tw, th = text_width(s, ORD_TEXT), max(ORD_TEXT, MIN_TEXT_MM)
    gap = 0.6

    def ring(d: float) -> list[Box]:
        r = half + d
        return [
            (c.x + r, c.y - th / 2, c.x + r + tw, c.y + th / 2),
            (c.x - r - tw, c.y - th / 2, c.x - r, c.y + th / 2),
            (c.x - tw / 2, c.y + r, c.x + tw / 2, c.y + r + th),
            (c.x - tw / 2, c.y - r - th, c.x + tw / 2, c.y - r),
            (c.x + r, c.y + r, c.x + r + tw, c.y + r + th),
            (c.x - r - tw, c.y + r, c.x - r, c.y + r + th),
            (c.x + r, c.y - r - th, c.x + r + tw, c.y - r),
            (c.x - r - tw, c.y - r - th, c.x - r, c.y - r),
        ]

    def free(b: Box) -> bool:
        return not any(_hit(b, t) for t in taken)

    def inside(b: Box) -> bool:
        return bounds is None or (
            b[0] >= bounds[0] and b[1] >= bounds[1] and b[2] <= bounds[2] and b[3] <= bounds[3]
        )

    near = ring(gap)[:4]
    choice = next((b for b in near if free(b) and inside(b)), None)
    if choice is None:
        far = (b for k in range(1, LABEL_RINGS + 1) for b in ring(gap + k * th))
        choice = next((b for b in far if free(b) and inside(b)), None)
        if choice is not None and lead is not None:
            # From the nearest point of the label box to the symbol's edge
            px = min(max(c.x, choice[0]), choice[2])
            py = min(max(c.y, choice[1]), choice[3])
            to = Vec(px, py) - c
            if to.length() > half:
                lead(Vec(px, py), c + to * (half / to.length()))
    if choice is None:
        choice = near[0]
    taken.append(choice)
    text(s, Vec(choice[0], (choice[1] + choice[3]) / 2), color=color)


def _hit(a: Box, b: Box) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _ordinates_x(
    e: WallElevation,
    scale: float,
    x0: float,
    floor: float,
    w: float,
    line: Callable[..., None],
    text: Callable[..., None],
) -> None:
    """Offsets from the left corner, under the floor: vertical labels spread out across the
    width.
    """
    values = sorted({0.0, *e.offsets(), e.length})
    wanted = [x0 + v / scale for v in values]
    th = max(ORD_TEXT, MIN_TEXT_MM)
    places = spread(wanted, th + ORD_GAP, x0 - th, x0 + w + th)
    for v, want, place in zip(values, wanted, places, strict=True):
        line(Vec(want, floor), Vec(want, floor - TICK))
        line(Vec(want, floor - TICK), Vec(place, floor - TICK - JOG))
        text(
            f"{v:.0f}",
            Vec(place, floor - TICK - JOG - 0.5),
            angle=90.0,
            align=TextEntityAlignment.MIDDLE_RIGHT,
        )


def _ordinates_y(
    e: WallElevation,
    scale: float,
    right: float,
    floor: float,
    ceil: float,
    line: Callable[..., None],
    text: Callable[..., None],
) -> None:
    """Heights from the floor, right of the wall; ceiling height gets "*" when it is an
    assumption.
    """
    values = sorted({*e.heights(), e.height})
    wanted = [floor + v / scale for v in values]
    th = max(ORD_TEXT, MIN_TEXT_MM)
    places = spread(wanted, th + ORD_GAP, floor, ceil + th)
    for v, want, place in zip(values, wanted, places, strict=True):
        line(Vec(right, want), Vec(right + TICK, want))
        line(Vec(right + TICK, want), Vec(right + TICK + JOG, place))
        mark = "*" if v == e.height and e.height_assumed else ""
        text(f"{v:.0f}{mark}", Vec(right + TICK + JOG + 0.5, place))
