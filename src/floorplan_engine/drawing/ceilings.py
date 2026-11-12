"""Ceiling of a room on the "Elevations" sheets (decision 2026-11-12): one more plane next to the
room's walls, seen from above as on the plan, at the set's scale (electrical/ceilings.py:
ceiling_views; a floor route plane is drawn the same way).

The room: the inner outline thick, its walls light, wall codes outside, as on the elevations.
The lines of the plane: each on its own lane of the bundle (drawing/wiring.lay_out, as on the
wiring sheet), in its group colour, cut by the room with its walls (a passage through a wall
shows up to the neighbour). Fixings: one line across the bundle — the conduit clips snap
together, the pads stand side by side (electrical/mounting.plan_fixings) — with the number of
fixings, "×5", once per bundle piece; at a bundle turn the radii of the inner and the outer
line, "R130–160". Boxes "К3". Line ends: a ring with a dot is a drop down a wall (its cable is on
that wall's elevation), a ring with a cross a point on the ceiling, a square the panel; the point
numbers of the electrical sheet and the group beside. Below: offsets from the left wall, on the
right: from the bottom wall (ordinate dimensions as on the elevations), a dashed leader from every
dimensioned spot to its value; a value with its leaders and spots is its own object,
"dim:<room>.ceiling.x1450": hovering it in the viewer lights what it measures.

The whole view is the object "elevation:<room>.ceiling" (".floor" for a floor plane): the viewer
pages it with the walls. Cables, fixings and boxes are on their own layers.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence

from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.layout import Paperspace
from shapely.geometry import LineString, Point, Polygon

from floorplan_engine.drawing.elevations import (
    BOX,
    DARK,
    GREY,
    HEAD,
    JOG,
    LIGHT,
    LW_THIN,
    LW_WALL,
    ORD_GAP,
    SIDE_GAP,
    SIDE_H,
    TICK,
    TITLE_H,
    ElevationPanel,
    spread,
)
from floorplan_engine.drawing.ids import tagged
from floorplan_engine.drawing.layers import E_ELEV, M_FIX, MIN_TEXT_MM, W_BOX, text_width
from floorplan_engine.drawing.mounting import Bend, bend_label
from floorplan_engine.drawing.plan import add_text
from floorplan_engine.electrical.bundles import Bundle
from floorplan_engine.electrical.ceilings import (
    CeilingEnd,
    CeilingView,
    dimension_key,
    dimension_spots,
    view_offsets,
)
from floorplan_engine.electrical.mounting import (
    PRACTICE,
    MountingNorms,
    PlanFixing,
    plan_fixings,
    text,
)
from floorplan_engine.electrical.point_numbers import ranges
from floorplan_engine.electrical.wiring_model import Wiring
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.schema import Conduit
from floorplan_engine.model.texts import Language

# Labels at the smallest printable height (GOST 2.304, printing.py checks it): the thin cables of
# a bundle need room
LABEL_MM = MIN_TEXT_MM
CODE_GAP = 1.2  # from the outer face of a wall to its code, sheet mm
CODE_PAD = CODE_GAP + 2 * LABEL_MM  # room around the walls for the codes, sheet mm
DASH, DASH_GAP = 0.8, 0.6  # dashed leaders to the scales, sheet mm (as on the elevations)
STROKE_HALF = 0.8  # half a fixing line beyond the outermost cables, sheet mm
END_R = 0.7  # line end marker radius, sheet mm
MIN_BOX = 1.2  # box square side, not less than this on the sheet, mm
LW_CABLE = 25  # line weight of a cable, 1/100 mm
LW_OUTLINE = 70  # the room's inner outline: thicker than the cables
BEND_GAP = 2.0  # from the corner to the radius label, sheet mm
Box = tuple[float, float, float, float]  # x0, y0, x1, y1 in sheet mm
Spot = tuple[PlanFixing, float, float]  # a fixing spot and the bundle band across it, model mm


def fixing_bands(
    wiring: Wiring,
    plane_bundles: Sequence[Bundle],
    conduit: Conduit,
    norms: MountingNorms = PRACTICE,
) -> list[Spot]:
    """The plan fixing spots (mounting.plan_fixings) with the bundle band across them: the offsets
    of the outermost lanes there (wiring.lay_out bundles), model mm; a slanted piece has none."""
    by_line: dict[tuple[str, int], list[Bundle]] = defaultdict(list)
    for b in plane_bundles:
        by_line[(b.axis, round(b.fixed))].append(b)
    out: list[Spot] = []
    for f in plan_fixings(wiring, conduit, norms):
        lo = hi = 0.0
        if f.axis is not None:
            pos = f.at.x if f.axis == "h" else f.at.y
            ids = set(f.runs)
            for b in by_line.get((f.axis, round(f.fixed)), ()):
                if b.lo - 1 <= pos <= b.hi + 1 and {wiring.runs[k].id for k in b.runs} == ids:
                    lo, hi = b.band
                    break
        out.append((f, lo, hi))
    return out


def ceiling_panel(
    view: CeilingView,
    wiring: Wiring,
    paths: Sequence[Sequence[Vec]],
    bends: Sequence[Bend],
    colors: Mapping[str, int],
    cable_layers: Mapping[str, str],
    fixings: Sequence[Spot],
    scale: float,
    language: Language,
) -> ElevationPanel:
    """The view of one plane of one room at 1:scale; paths are the line lanes (lay_out), bends
    the bundle turns (bundle_bends), cable_layers the layer of each line (wiring.cable_layer),
    fixings the plan fixing spots (fixing_bands), all of the whole wiring; draw is from the
    block's top-left corner."""
    xs, ys = view_offsets(view, wiring)
    x0, y0, x1, y1 = view.clip.bounds
    w, h = (x1 - x0) / scale, (y1 - y0) / scale
    width = max(
        w + 2 * CODE_PAD + _ord_width(ys) + JOG,
        text_width(_title(view, scale, language), TITLE_H),
        text_width(_side(view, language), SIDE_H),
    )
    height = HEAD + CODE_PAD + h + CODE_PAD + _ord_width(xs) + JOG

    def draw(psp: Paperspace, top_left: Vec) -> None:
        origin = Vec(top_left.x + CODE_PAD, top_left.y - HEAD - CODE_PAD - h)
        with tagged(psp, "elevation", f"{view.room}.{view.plane}"):
            _draw(
                psp, view, wiring, paths, bends, colors, cable_layers, fixings, scale, language,
                top_left, origin,
            )  # fmt: skip
        _draw_dims(psp, view, wiring, scale, origin, (xs, ys))

    return ElevationPanel(width, height, draw)


def _title(view: CeilingView, scale: float, language: Language) -> str:
    size = view.size
    return text(
        "view_title",
        language,
        room=view.room_name,
        plane=text(f"plane_{view.plane}", language),
        w=f"{size.x:.0f}",
        h=f"{size.y:.0f}",
        scale=f"{scale:g}",
    )


def _side(view: CeilingView, language: Language) -> str:
    if view.left is not None and view.bottom is not None:
        return text("view_side", language, left=view.left, bottom=view.bottom)
    return text("view_side_corner", language)


def _ord_width(values: Sequence[float]) -> float:
    longest = max((text_width(f"{v:.0f}", LABEL_MM) for v in values), default=0.0)
    return TICK + JOG + 0.5 + longest


class _Pen:
    """Drawing on the sheet in model mm of the plan, on the current layer."""

    def __init__(self, psp: Paperspace, origin: Vec, x0: float, y0: float, scale: float) -> None:
        self.psp, self.origin, self.x0, self.y0, self.scale = psp, origin, x0, y0, scale
        self.layer = E_ELEV.name

    def at(self, p: Vec) -> Vec:
        o, k = self.origin, 1 / self.scale
        return Vec(o.x + (p.x - self.x0) * k, o.y + (p.y - self.y0) * k)

    def line(self, a: Vec, b: Vec, lw: int = LW_THIN, color: int = DARK) -> None:
        self.psp.add_line(
            a.as_tuple(),
            b.as_tuple(),
            dxfattribs={"layer": self.layer, "lineweight": lw, "true_color": color},
        )

    def poly(self, pts: Sequence[Vec], lw: int, color: int, close: bool = False) -> None:
        self.psp.add_lwpolyline(
            [p.as_tuple() for p in pts],
            close=close,
            dxfattribs={"layer": self.layer, "lineweight": lw, "true_color": color},
        )

    def circle(self, c: Vec, r: float, color: int, lw: int = LW_WALL) -> None:
        attribs = {"layer": self.layer, "lineweight": lw, "true_color": color}
        self.psp.add_circle(c.as_tuple(), r, dxfattribs=attribs)

    def label(
        self,
        s: str,
        p: Vec,
        hgt: float = LABEL_MM,
        angle: float = 0.0,
        align: TextEntityAlignment = TextEntityAlignment.MIDDLE_LEFT,
        color: int = DARK,
    ) -> None:
        size = max(hgt, MIN_TEXT_MM)
        add_text(self.psp, s, p, size, self.layer, angle, align, color=color, scale=1.0)


def _draw(
    psp: Paperspace,
    view: CeilingView,
    wiring: Wiring,
    paths: Sequence[Sequence[Vec]],
    bends: Sequence[Bend],
    colors: Mapping[str, int],
    cable_layers: Mapping[str, str],
    fixings: Sequence[Spot],
    scale: float,
    language: Language,
    top_left: Vec,
    origin: Vec,
) -> None:
    bx0, by0, _, _ = view.clip.bounds
    pen = _Pen(psp, origin, bx0, by0, scale)
    at = pen.at
    inner = Polygon([v.as_tuple() for v in view.outline]).buffer(0)
    taken: list[Box] = []

    pen.label(_title(view, scale, language), Vec(top_left.x, top_left.y - TITLE_H / 2), TITLE_H)
    side_at = Vec(top_left.x, top_left.y - TITLE_H - SIDE_GAP - SIDE_H / 2)
    pen.label(_side(view, language), side_at, SIDE_H)
    # The room: walls light, the inner outline thick, wall codes outside
    pen.poly([at(Vec(x, y)) for x, y in view.clip.exterior.coords], LW_THIN, LIGHT, close=True)
    pen.poly([at(v) for v in view.outline], LW_OUTLINE, DARK, close=True)
    for wall in view.walls:
        mid = (wall.start + wall.end) * 0.5
        spot = at(mid + wall.outward * wall.thickness) + wall.outward * (CODE_GAP + LABEL_MM / 2)
        pen.label(wall.code, spot, align=TextEntityAlignment.MIDDLE_CENTER, color=GREY)

    # Lines on their lanes, cut by the room with its walls
    index = {r.id: k for k, r in enumerate(wiring.runs)}
    for rid in view.runs:
        k = index[rid]
        lane = paths[k]
        if len(lane) < 2:
            continue
        pen.layer = cable_layers.get(rid, E_ELEV.name)
        color = colors.get(wiring.runs[k].group, DARK)
        for part in _parts(LineString([p.as_tuple() for p in lane]).intersection(view.clip)):
            pen.poly([at(Vec(x, y)) for x, y in part.coords], LW_CABLE, color)

    # Fixings: one line across the bundle, the number of clips or pads once per bundle piece
    pen.layer = M_FIX.name
    for fx, lo, hi in fixings:
        if not view.clip.contains(Point(fx.at.x, fx.at.y)):
            continue
        across = fx.along.left()
        pad = STROKE_HALF * scale
        p0, p1 = at(fx.at + across * (lo - pad)), at(fx.at + across * (hi + pad))
        pen.line(p0, p1, LW_WALL, DARK)
        if len(fx.runs) > 1 and fx.first:
            s = f"×{len(fx.runs)}"
            where = p1 + across * (0.4 + text_width(s, LABEL_MM) / 2)
            pen.label(s, where, align=TextEntityAlignment.MIDDLE_CENTER)
    for bend in bends:
        if not inner.contains(Point(bend.at.x, bend.at.y)):
            continue
        s = bend_label(bend)
        spot = at(bend.at) + bend.inside * (BEND_GAP + text_width(s, LABEL_MM) / 2)
        pen.label(s, spot, align=TextEntityAlignment.MIDDLE_CENTER)

    pen.layer = W_BOX.name
    for b in view.boxes:
        c = at(b.at)
        half = max(b.size / 2 / scale, MIN_BOX / 2)
        rect = (c.x - half, c.y - half, c.x + half, c.y + half)
        pen.poly(_corners(rect), LW_WALL, BOX, close=True)
        _place(b.label, c, half, taken, pen.label, BOX)
        taken.append(rect)

    for end in view.ends:
        first = end.runs[0] if end.runs else ""
        pen.layer = W_BOX.name if end.kind == "board" else cable_layers.get(first, E_ELEV.name)
        _draw_end(pen, end, at(end.at), taken, colors)


SPOT_R = 0.35  # a dimensioned spot on its leader, sheet mm


def _draw_dims(
    psp: Paperspace,
    view: CeilingView,
    wiring: Wiring,
    scale: float,
    origin: Vec,
    offsets: tuple[list[float], list[float]],
) -> None:
    """The scales: offsets from the left wall below the view, from the bottom wall on the right;
    from every dimensioned spot a dashed leader to its value. A value with its leaders and spots
    is one object (dimension_key): hovering it in the viewer lights what it measures."""
    bx0, by0, bx1, _ = view.clip.bounds
    pen = _Pen(psp, origin, bx0, by0, scale)
    at = pen.at
    base_x = origin.y - CODE_PAD
    base_y = origin.x + (bx1 - bx0) / scale + CODE_PAD
    lows, rights = dimension_spots(view, wiring)
    o = at(view.origin)
    th = max(LABEL_MM, MIN_TEXT_MM)
    xs, ys = offsets
    wanted = [o.x + v / scale for v in xs]
    places = spread(wanted, th + ORD_GAP, o.x - th, o.x + view.size.x / scale + th)
    for v, want, place in zip(xs, wanted, places, strict=True):
        with tagged(psp, *dimension_key(view, "x", v).split(":", 1)):
            for p in lows.get(v, ()):
                a = at(p)
                _dashed(pen, Vec(a.x, a.y - SPOT_R), Vec(a.x, base_x))
                pen.circle(a, SPOT_R, GREY, LW_THIN)
            pen.line(Vec(want, base_x), Vec(want, base_x - TICK))
            pen.line(Vec(want, base_x - TICK), Vec(place, base_x - TICK - JOG))
            pen.label(
                f"{v:.0f}",
                Vec(place, base_x - TICK - JOG - 0.5),
                angle=90.0,
                align=TextEntityAlignment.MIDDLE_RIGHT,
            )
    wanted = [o.y + v / scale for v in ys]
    places = spread(wanted, th + ORD_GAP, o.y - th, o.y + view.size.y / scale + th)
    for v, want, place in zip(ys, wanted, places, strict=True):
        with tagged(psp, *dimension_key(view, "y", v).split(":", 1)):
            for p in rights.get(v, ()):
                a = at(p)
                _dashed(pen, Vec(a.x + SPOT_R, a.y), Vec(base_y, a.y))
                pen.circle(a, SPOT_R, GREY, LW_THIN)
            pen.line(Vec(base_y, want), Vec(base_y + TICK, want))
            pen.line(Vec(base_y + TICK, want), Vec(base_y + TICK + JOG, place))
            pen.label(f"{v:.0f}", Vec(base_y + TICK + JOG + 0.5, place))


def _dashed(pen: _Pen, a: Vec, b: Vec) -> None:
    """Dashes as separate segments, so the line looks the same in DXF, PNG and the viewer."""
    length = (b - a).length()
    if length < 1e-6:
        return
    step = (b - a) * (1 / length)
    t = 0.0
    while t < length:
        pen.line(a + step * t, a + step * min(t + DASH, length), LW_THIN, LIGHT)
        t += DASH + DASH_GAP


def _draw_end(
    pen: _Pen, end: CeilingEnd, c: Vec, taken: list[Box], colors: Mapping[str, int]
) -> None:
    """A drop: a ring with a dot (the cable goes down); a ceiling point: a ring with a cross;
    the panel: a square. The label is the point numbers and the groups."""
    color = colors.get(end.groups[0], DARK) if end.groups else DARK
    r = END_R
    if end.kind == "board":
        pen.poly(_corners((c.x - r, c.y - r, c.x + r, c.y + r)), LW_WALL, DARK, close=True)
    else:
        pen.circle(c, r, color)
        if end.kind == "drop":
            pen.circle(c, r / 3, color)
        else:
            d = r * 0.7
            pen.line(Vec(c.x - d, c.y - d), Vec(c.x + d, c.y + d), LW_THIN, color)
            pen.line(Vec(c.x - d, c.y + d), Vec(c.x + d, c.y - d), LW_THIN, color)
    arrow = "↓" if end.kind == "drop" else ""
    nums = ranges(list(end.numbers)) if end.numbers else ""
    groups = ", ".join(end.groups)
    _place(f"{arrow}{nums} · {groups}" if nums else groups, c, r, taken, pen.label, DARK)
    taken.append((c.x - r, c.y - r, c.x + r, c.y + r))


def _place(
    s: str, c: Vec, half: float, taken: list[Box], label: Callable[..., None], color: int
) -> None:
    """A label next to a symbol: right, left, above or below, wherever is free."""
    tw, th = text_width(s, LABEL_MM), max(LABEL_MM, MIN_TEXT_MM)
    gap = 0.5
    options: list[Box] = [
        (c.x + half + gap, c.y - th / 2, c.x + half + gap + tw, c.y + th / 2),
        (c.x - half - gap - tw, c.y - th / 2, c.x - half - gap, c.y + th / 2),
        (c.x - tw / 2, c.y + half + gap, c.x + tw / 2, c.y + half + gap + th),
        (c.x - tw / 2, c.y - half - gap - th, c.x + tw / 2, c.y - half - gap),
    ]
    choice = next((b for b in options if not any(_hit(b, t) for t in taken)), options[0])
    taken.append(choice)
    label(s, Vec(choice[0], (choice[1] + choice[3]) / 2), color=color)


def _hit(a: Box, b: Box) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _corners(b: Box) -> list[Vec]:
    x0, y0, x1, y1 = b
    return [Vec(x0, y0), Vec(x1, y0), Vec(x1, y1), Vec(x0, y1)]


def _parts(geom: object) -> list[LineString]:
    if isinstance(geom, LineString):
        return [geom] if not geom.is_empty else []
    parts = getattr(geom, "geoms", ())
    return [g for p in parts for g in _parts(p)]
