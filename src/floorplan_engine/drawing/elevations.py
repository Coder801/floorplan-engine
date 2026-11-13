"""Wall elevation on the sheet (elevations.py → sheet block): drawn directly on the sheet at
the set's scale, like the panel front view. Below: offsets from the left wall corner; on the
right: heights from the floor (ordinate dimensions: close values are spread out, a bent
leader points to the place).
"""

from __future__ import annotations

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
from floorplan_engine.electrical.elevations import POST_PITCH_MM, WallElevation, behind_text
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
    # colour; a fixing is one line across the cables of its drop, their number at the top one
    pitch = CABLE_PITCH_SHEET
    by_x: dict[float, list[str]] = {}
    for cable in e.cables:
        if cable.x1 is None:
            by_x.setdefault(cable.x, []).append(cable.run)
    for cable in e.cables:
        color = colors.get(cable.group, DARK)
        if cable.x1 is not None:  # the turn past an opening: from the drop along the wall
            runs = by_x.get(cable.x, [cable.run])
            k = runs.index(cable.run) if cable.run in runs else 0
            dx = (k - (len(runs) - 1) / 2) * pitch
            a, b = at(cable.x, cable.y0), at(cable.x1, cable.y0)
            line(Vec(a.x + dx, a.y), Vec(a.x + dx, a.y + dx), LW_CABLE, color)  # the corner
            line(Vec(a.x + dx, a.y + dx), Vec(b.x, b.y + dx), LW_CABLE, color)
            continue
        runs = by_x[cable.x]
        dx = (runs.index(cable.run) - (len(runs) - 1) / 2) * pitch
        a, b = at(cable.x, cable.y0), at(cable.x, cable.y1)
        # The end on the route plane goes on past the wall: the cable runs on in the floor or
        # ceiling
        lo = a.y - CABLE_OUT if cable.y0 <= 0.5 else a.y
        hi = b.y + CABLE_OUT if cable.y1 >= e.height - 0.5 else b.y
        line(Vec(a.x + dx, lo), Vec(b.x + dx, hi), LW_CABLE, color)
    tops = {f.x: max(g.y for g in e.fixings if g.x == f.x) for f in e.fixings}
    for f in e.fixings:
        spot = at(f.x, f.y)
        half = FIXING_HALF_MM + (max(f.count, len(by_x.get(f.x, ()))) - 1) / 2 * pitch
        line(Vec(spot.x - half, spot.y), Vec(spot.x + half, spot.y), LW_WALL)
        if f.count > 1 and f.y == tops[f.x]:
            text(f"×{f.count}", Vec(spot.x + half + 0.4, spot.y))

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
    ]
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
        _label(bx.label, c, half, taken, text, BOX)

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
        _label(ranges(nums), Vec(cx, cy), half, taken, text, DARK)
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
        _label(f"{number}{'*' if assumed else ''}", c, rr, taken, text, WATER["sewer"])
    # Numbers of the far side's outlets come after our own: the spot by the symbol goes to ours
    # first
    for p in e.back:
        c = at(p.x, p.y)
        _label(str(p.number), c, r + pitch * (p.frame - 1) / 2, taken, text, BACK)

    _ordinates_x(e, scale, x0, floor, w, line, text)
    _ordinates_y(e, scale, x0 + w, floor, top, line, text)


def _label(
    s: str,
    c: Vec,
    half: float,
    taken: list[Box],
    text: Callable[..., None],
    color: int,
) -> None:
    """Label next to a symbol: right, left, above or below, wherever is free."""
    tw, th = text_width(s, ORD_TEXT), max(ORD_TEXT, MIN_TEXT_MM)
    gap = 0.6
    options = [
        ((c.x + half + gap, c.y - th / 2, c.x + half + gap + tw, c.y + th / 2), "left"),
        ((c.x - half - gap - tw, c.y - th / 2, c.x - half - gap, c.y + th / 2), "left"),
        ((c.x - tw / 2, c.y + half + gap, c.x + tw / 2, c.y + half + gap + th), "left"),
        ((c.x - tw / 2, c.y - half - gap - th, c.x + tw / 2, c.y - half - gap), "left"),
    ]
    choice = next((b for b, _ in options if not any(_hit(b, t) for t in taken)), options[0][0])
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
