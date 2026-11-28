"""Wiring drawing through junction boxes and the cable table for its sheet.

The calculation is in wiring.py; here is only what goes into the DXF: boxes, cable lines by
group (group colour as on the electrical sheet) and the "group → cable type → length" table.

Cables whose routes lie on one line run as a bundle: each has its own lane offset by LANE_MM
on the sheet (lanes), overlapping cables never share a lane; a bundle is at most BAND_MM wide
and does not run onto walls: next to a wall it shifts away from it, and the step shrinks only
if the space between walls is less than the bundle needs (clearance). A line is cut into
pieces where the set of cables does not change (bundles); each piece gets one label on the
bundle, in a frame with a white background over the cables (beside the bundle if no spot on it
is free), in the group colour or dark grey for a bundle of several groups: piece length in m,
and the number of cables if more than one: "L2,0 ×3". The label is tagged wire_len with the
lines of its bundle: the viewer shows it only while one of them is selected.
At a wall point there is a drop "↓h1,9", at the panel a rise "↑h1,0"; floor routes (own
layer, dash-dot) are the other way round: a rise from the floor to the point "↑h0,3", a drop
at the panel "↓h1,7". Bundles are computed separately for ceiling and floor. A turn is drawn
round with the radius the cable takes, as on the ceiling views (decision 2026-11-17,
mounting.lane_turns: the inner cable of a bundle at its radius, the others concentric); a turn
of a cable without sizes (low voltage) gets a small FILLET_MM.
A label is never placed over other routes, boxes, points or other labels: the bundle itself,
then both sides, at several spots along the piece are tried; if nothing fits there is no
label (the length is in the table and the log). Lengths come from the original route
(wiring.py): lane shifts and rounding do not change them.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Iterable, Sequence
from pathlib import Path

from ezdxf.colors import RGB
from ezdxf.layouts.layout import Modelspace
from shapely import STRtree
from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry

from floorplan_engine.drawing.ids import tagged
from floorplan_engine.drawing.layers import (
    BOX_TEXT_MM,
    W_BOX,
    W_CABLES,
    W_TEXT,
    text_descender,
    text_width,
)
from floorplan_engine.drawing.mounting import lane_turns, rounded
from floorplan_engine.drawing.plan import add_text
from floorplan_engine.electrical.anchors import SYMBOL_DEPTH, symbol_key
from floorplan_engine.electrical.boxes import BOX_SIZE_MM, box_center, box_square
from floorplan_engine.electrical.bundles import Bundle, lane_paths
from floorplan_engine.electrical.chases import CHASE_CABLES, CHASE_SHARE
from floorplan_engine.electrical.colors import LED_LINE, group_colors, rgb
from floorplan_engine.electrical.panel import OTHER_LINE, LineClass
from floorplan_engine.electrical.sleeves import sleeve_counts
from floorplan_engine.electrical.wiring_model import (
    CHASE_NARROW,
    JunctionBox,
    Run,
    Wiring,
)
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.scale import sheet
from floorplan_engine.model.schema import Conduit, Electrical
from floorplan_engine.model.texts import CABLE_PASS_WORDS, Language, plural, tr

FILLET_MM = 1.5  # corner radius on the sheet of a cable without sizes (low voltage)
LENGTH_MM = 1.8  # length label height on the sheet
# Label notation (decision 2026-10-24): piece length "L1,4 ×3", vertical drop "↓h1,9",
# like the point height "h300" on the electrical sheet; bare digits were unreadable
LENGTH = "L"
VERT = "h"
LENGTH_OFFSET_MM = 1.2  # a label beside a line: from the line (bundle edge) to the label
WHITE = 0xFFFFFF
MIXED = 0x5A5A5A  # label of a bundle of several groups: dark grey, it has no group colour
LENGTH_KIND = "wire_len"  # object type of a length label, its id is the bundle lines with ","
FRAME_PAD_MM = 0.4  # from the length label text to its frame
LENGTH_SLOTS = (0.5, 0.3, 0.7, 0.15, 0.85)  # label spots along the piece, fractions of length
POINT_CLEAR_MM = 2.5  # no labels around a connection point


def draw_wiring(
    msp: Modelspace, wiring: Wiring, elec: Electrical, classes: dict[str, LineClass]
) -> None:
    """classes: what each group is (panel.line_classes), it gives the cable layer."""
    colors = group_colors(elec)
    layers = [cable_layer(r, classes) for r in wiring.runs]
    paths, plane_bundles = lay_out(wiring)
    labels = _Labels(paths)
    size = sheet(BOX_SIZE_MM)
    for b in wiring.boxes:
        labels.block(Point(_box_center(b, size).as_tuple()).buffer(size))
    walls = {p.id: sheet(SYMBOL_DEPTH[symbol_key(p)]) for p in elec.points if p.wall is not None}
    _draw_runs(msp, wiring, paths, layers, labels, colors, walls)
    _draw_bundle_lengths(msp, wiring, plane_bundles, layers, labels, colors)
    _draw_board_rises(msp, wiring, paths, labels)
    _draw_boxes(msp, wiring)


def lay_out(wiring: Wiring) -> tuple[list[list[Vec]], list[Bundle]]:
    """Line paths with lane shifts and bundle pieces (bundles.lane_paths)."""
    return lane_paths(wiring.runs, wiring.free)


def turned(wiring: Wiring, paths: Sequence[Sequence[Vec]], conduit: Conduit) -> list[list[Vec]]:
    """The lanes as drawn: every corner round, with the radius the cable takes
    (mounting.lane_turns) or FILLET_MM on the sheet for a cable without sizes."""
    fillets = lane_turns(wiring, paths, conduit).fillets
    small = sheet(FILLET_MM)
    out: list[list[Vec]] = []
    for k, path in enumerate(paths):
        radii = {i: fillets.get((k, i), small) for i in range(1, len(path) - 1)}
        out.append(rounded(path, radii))
    return out


def cable_layer(run: Run, classes: dict[str, LineClass]) -> str:
    """Layer of a line: low-voltage by its circuit, the rest by what its group is; a 12 V LED line
    from the panel is low voltage, but lighting, so it goes by its group."""
    low = run.circuit == "low" and not run.led
    line = LineClass("low", False) if low else classes.get(run.group, OTHER_LINE)
    return W_CABLES[(line.purpose, line.rcd, run.route == "floor")].name


def _draw_runs(
    msp: Modelspace,
    wiring: Wiring,
    paths: Sequence[Sequence[Vec]],
    layers: Sequence[str],
    labels: _Labels,
    colors: dict[str, int],
    walls: dict[str, float] | None = None,
) -> None:
    """Lines with rounded corners and a drop (a rise for floor routes) at the point; the drop label
    is on the line's layer, it goes away with the line. walls: wall point id → symbol depth (model
    mm); a line that goes down (up) to such a point is drawn right up to the wall face, not to the
    symbol tip (feedback 2026-11-17), the route and its length stay as they are."""
    walls = walls or {}
    for k, run in enumerate(wiring.runs):
        floor = run.route == "floor"
        attribs: dict[str, object] = {"layer": layers[k]}
        # A 12 V LED line from the panel: its own colour, not the group's (decision 2026-11-13)
        color = rgb(LED_LINE) if run.led else colors.get(run.group)
        if color is not None:
            attribs["true_color"] = color
        with tagged(msp, "wire", run.id):
            drawn = _to_walls(paths[k], walls, run)
            msp.add_lwpolyline(fillet(drawn, sheet(FILLET_MM)), format="xyb", dxfattribs=attribs)
            if run.rise_end_mm > 0 and not run.target.startswith("box_"):
                arrow = "↑" if floor else "↓"
                placed = labels.place_end(
                    paths[k], f"{arrow}{VERT}{_m(run.rise_end_mm)}", at_end=True
                )
                if placed is not None:
                    text, at, angle = placed
                    add_text(msp, text, at, LENGTH_MM, layers[k], angle, color=color)


def _to_walls(path: Sequence[Vec], walls: dict[str, float], run: Run) -> list[Vec]:
    """The path with its point ends carried on along the last (first) piece by the symbol depth:
    the route reaches a wall point at the symbol tip, the cable goes on to the wall."""
    out = list(path)
    if len(out) < 2:
        return out
    if run.rise_end_mm > 0 and run.target in walls:
        out[-1] = _extend(out[-2], out[-1], walls[run.target])
    if run.rise_start_mm > 0 and run.source in walls:
        out[0] = _extend(out[1], out[0], walls[run.source])
    return out


def _extend(before: Vec, end: Vec, by: float) -> Vec:
    d = end - before
    n = d.length()
    return end if n == 0 else end + d * (by / n)


def _draw_bundle_lengths(
    msp: Modelspace,
    wiring: Wiring,
    plane_bundles: Sequence[Bundle],
    layers: Sequence[str],
    labels: _Labels,
    colors: dict[str, int],
) -> None:
    """Label for a bundle piece: length in m and the number of cables if more than one. On the
    layer of the bundle's first line, in its group colour; a bundle of several groups in MIXED."""
    for bundle in plane_bundles:
        runs = [wiring.runs[k] for k in bundle.runs]
        text = length_label(bundle.length, len(runs))
        placed = labels.place_bundle(text, bundle)
        if placed is None:
            continue
        (text, at, angle), frame = placed
        groups = {r.group for r in runs}
        color = colors.get(next(iter(groups))) if len(groups) == 1 else None
        if color is None:
            color = MIXED
        # on a cable layer, not W-TEXT: the viewer enlarges *-TEXT labels on screen, the text
        # would grow out of its frame and read as another font
        layer = layers[bundle.runs[0]]
        # its own object, not the line's: the viewer shows the label only with a selected line
        # of the bundle (decision 2026-11-22); the DXF, the print and the album keep them all
        with tagged(msp, LENGTH_KIND, ",".join(r.id for r in runs)):
            _draw_frame(msp, frame, layer, color)
            add_text(msp, text, at, LENGTH_MM, layer, angle, color=color)


def _draw_frame(msp: Modelspace, frame: BaseGeometry, layer: str, color: int) -> None:
    """White background over the cables and an outline in the label colour (drawn after the
    lines, so it covers them)."""
    x0, y0, x1, y1 = frame.bounds
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    hatch = msp.add_hatch(dxfattribs={"layer": layer, "true_color": WHITE})
    hatch.set_solid_fill(rgb=RGB(255, 255, 255))
    hatch.paths.add_polyline_path(corners, is_closed=True)
    msp.add_lwpolyline(corners, close=True, dxfattribs={"layer": layer, "true_color": color})


def _draw_board_rises(
    msp: Modelspace, wiring: Wiring, paths: Sequence[Sequence[Vec]], labels: _Labels
) -> None:
    """At the panel: a rise to the ceiling "↑" and a drop to the floor "↓", one label per plane."""
    for route, arrow in (("ceiling", "↑"), ("floor", "↓")):
        board = next(
            (
                k
                for k, r in enumerate(wiring.runs)
                if r.source == "board" and r.rise_start_mm and r.route == route
            ),
            None,
        )
        if board is None:
            continue
        rise = wiring.runs[board].rise_start_mm
        placed = labels.place_end(paths[board], f"{arrow}{VERT}{_m(rise)}", at_end=False)
        if placed is not None:
            text, at, angle = placed
            with tagged(msp, "board", "board"):
                add_text(msp, text, at, LENGTH_MM, W_TEXT.name, angle)


def _box_center(b: JunctionBox, size: float) -> Vec:
    return box_center(b.anchor, size)


def _draw_boxes(msp: Modelspace, wiring: Wiring) -> None:
    """Boxes: a white square at the wall (on the ceiling, on the axes at the box point) over
    the lines, with its "К1" label inside (2026-11-18); what goes in and out of a box is in its
    card in the viewer (decision 2026-11-17, epd.box_card)."""
    size = sheet(BOX_SIZE_MM)
    for b in wiring.boxes:
        corners = list(box_square(b.anchor, size).exterior.coords)[:-1]
        with tagged(msp, "box", b.id):
            back = msp.add_hatch(dxfattribs={"layer": W_BOX.name, "true_color": WHITE})
            back.set_solid_fill(rgb=RGB(255, 255, 255))
            back.paths.add_polyline_path(corners, is_closed=True)
            msp.add_lwpolyline(corners, close=True, dxfattribs={"layer": W_BOX.name})
            add_text(msp, b.label, _box_center(b, size), BOX_TEXT_MM, W_BOX.name)


# --- Bundles -----------------------------------------------------------------


def fillet(path: Sequence[Vec], radius: float) -> list[tuple[float, float, float]]:
    """Polyline vertices (x, y, bulge) with rounded corners: the arc touches both pieces; on a short
    piece the radius is smaller, each piece gives the arc at most half its length."""
    if len(path) < 3:
        return [(p.x, p.y, 0.0) for p in path]
    out: list[tuple[float, float, float]] = [(path[0].x, path[0].y, 0.0)]
    for a, p, b in zip(path, path[1:], path[2:], strict=False):
        d_in, d_out = p - a, b - p
        if d_in.length() < 1e-9 or d_out.length() < 1e-9:
            continue
        u, v = _unit(d_in), _unit(d_out)
        cross = u.x * v.y - u.y * v.x
        turn = math.atan2(cross, u.dot(v))  # turn angle, signed: + is left
        if abs(turn) < 1e-6:
            continue  # straight: no vertex needed
        tangent = min(radius * math.tan(abs(turn) / 2), d_in.length() / 2, d_out.length() / 2)
        start, end = p - u * tangent, p + v * tangent
        out.append((start.x, start.y, math.tan(turn / 4)))
        out.append((end.x, end.y, 0.0))
    out.append((path[-1].x, path[-1].y, 0.0))
    return out


# --- Labels ------------------------------------------------------------------

Label = tuple[str, Vec, float]  # text, centre, angle


class _Labels:
    """Label spots on the wiring sheet: a label does not cross routes, boxes, connection points
    or labels already placed."""

    def __init__(self, paths: Sequence[Sequence[Vec]]) -> None:
        lines = [LineString([p.as_tuple() for p in path]) for path in paths if len(path) > 1]
        self.lines = STRtree(lines)
        self.taken: list[BaseGeometry] = [
            Point(path[-1].as_tuple()).buffer(sheet(POINT_CLEAR_MM)) for path in paths if path
        ]
        self.h = sheet(LENGTH_MM)
        self.descender = sheet(text_descender(LENGTH_MM))
        self.gap = sheet(LENGTH_OFFSET_MM)

    def block(self, area: BaseGeometry) -> None:
        self.taken.append(area)

    def _rect(self, text: str, center: Vec, along: Vec) -> BaseGeometry:
        """The real extents of centred text: half the height above the centre, half the height
        and the descender below it (across is the text's up direction)."""
        w = sheet(text_width(text, LENGTH_MM)) / 2
        h = self.h / 2
        across = Vec(-along.y, along.x)
        corners = [
            center + along * sx * w + across * up
            for sx in (-1, 1)
            for up in (-h - self.descender, h)
        ]
        return box(
            min(c.x for c in corners),
            min(c.y for c in corners),
            max(c.x for c in corners),
            max(c.y for c in corners),
        )

    def _free(self, rect: BaseGeometry, own: BaseGeometry | None = None) -> bool:
        """Nothing taken touches rect, and no route crosses it (but inside own: the bundle a
        framed label sits on)."""
        if any(rect.intersects(t) for t in self.taken):
            return False
        for i in self.lines.query(rect):
            line = self.lines.geometries[i]
            if not rect.intersects(line):
                continue
            if own is None or not own.contains(rect.intersection(line)):
                return False
        return True

    def place(self, text: str, candidates: Iterable[tuple[Vec, Vec]]) -> Label | None:
        """The first free spot of (centre, text direction); it is taken."""
        return self._try(text, candidates)

    def _try(self, text: str, candidates: Iterable[tuple[Vec, Vec]]) -> Label | None:
        for center, along in candidates:
            rect = self._rect(text, center, along)
            if self._free(rect):
                self.taken.append(rect)
                return text, center, math.degrees(math.atan2(along.y, along.x))
        return None

    def place_bundle(self, text: str, b: Bundle) -> tuple[Label, BaseGeometry] | None:
        """Bundle piece label in a frame: on the bundle (the frame may cover only its own
        cables), else beside the outermost lane; a short piece gets no label. Returns the label
        and its frame, which is taken."""
        pad = sheet(FRAME_PAD_MM)
        if sheet(text_width(text, LENGTH_MM)) + 2 * (pad + self.gap) > b.length:
            return None
        along = Vec(1.0, 0.0) if b.axis == "h" else Vec(0.0, 1.0)
        across = Vec(0.0, 1.0) if b.axis == "h" else Vec(1.0, 0.0)
        mid = (b.band[0] + b.band[1]) / 2
        reach = self.gap + pad + self.h / 2
        sides = (across * (b.band[1] + reach + self.descender), across * (b.band[0] - reach))
        corridor = _corridor(b).buffer(sheet(0.05))
        slots = [b.lo + (b.hi - b.lo) * t for t in LENGTH_SLOTS]

        def at(pos: float) -> Vec:
            return Vec(pos, b.fixed) if b.axis == "h" else Vec(b.fixed, pos)

        spots: list[tuple[Vec, Vec, BaseGeometry | None]]
        spots = [(at(pos) + across * mid, along, corridor) for pos in slots]
        spots += [(at(pos) + side, along, None) for pos in slots for side in sides]
        for center, d, own in spots:
            frame = self._rect(text, center, d).buffer(pad, join_style="mitre")
            if self._free(frame, own):
                self.taken.append(frame)
                return (text, center, math.degrees(math.atan2(d.y, d.x))), frame
        return None

    def place_end(self, path: Sequence[Vec], text: str, at_end: bool) -> Label | None:
        """Label at the end (or start) of a route: beside the last piece or past the end."""
        if len(path) < 2:
            return None
        tip, prev = (path[-1], path[-2]) if at_end else (path[0], path[1])
        if (tip - prev).length() < 1e-9:
            return None
        u = _unit(tip - prev)
        along = _readable(u)
        half_w = sheet(text_width(text, LENGTH_MM)) / 2
        clear = sheet(POINT_CLEAR_MM)
        side = Vec(-along.y, along.x) * (self.gap + self.h / 2)
        back = tip - u * (clear + half_w)
        beyond = tip + u * (clear + half_w)
        return self._try(text, [(back + side, along), (back - side, along), (beyond, along)])


def _corridor(b: Bundle) -> BaseGeometry:
    """The strip the bundle piece's lanes fill, model mm."""
    lo, hi = b.lo, b.hi
    if b.axis == "h":
        return box(lo, b.fixed + b.band[0], hi, b.fixed + b.band[1])
    return box(b.fixed + b.band[0], lo, b.fixed + b.band[1], hi)


def _unit(v: Vec) -> Vec:
    return v * (1.0 / v.length())


def _readable(direction: Vec) -> Vec:
    """Text direction along a piece: left to right or bottom to top."""
    if direction.x < -1e-9 or (abs(direction.x) <= 1e-9 and direction.y < 0):
        return direction * -1.0
    return direction


def length_label(mm: float, cables: int) -> str:
    """Bundle piece label: "L1,4" is the length in m; "×3" is the cable count if more than one."""
    return f"{LENGTH}{_m(mm)}" + (f" ×{cables}" if cables > 1 else "")


def _m(mm: float) -> str:
    return f"{mm / 1000:.1f}".replace(".", ",")


def wiring_notes(wiring: Wiring, language: Language) -> list[str]:
    """Calculation assumptions as rows under the table."""
    default = tr("wiring_default", language) if wiring.height_assumed else ""
    notes = [
        tr("wiring_note", language, h=f"{wiring.ceiling_height:g}", default=default),
        tr("wiring_lengths_note", language),
        tr("wiring_drops_note", language),
    ]
    if any(r.route == "floor" for r in wiring.runs):
        notes += [tr("wiring_floor_note", language), tr("wiring_floor_arrows", language)]
    if wiring.before_plaster:
        notes.append(tr("wiring_before_plaster", language))
    if wiring.chases:
        notes.append(
            tr(
                "wiring_chases",
                language,
                n=len(wiring.chases),
                m=_m(wiring.chase_mm),
                k=CHASE_CABLES,
                d=f"{CHASE_SHARE:g}",
            )
        )
        notes.append(
            tr(
                "wiring_chase_kinds",
                language,
                narrow=_m(wiring.chase_length(wide=False)),
                wide=_m(wiring.chase_length(wide=True)),
                k=CHASE_NARROW,
            )
        )
    sleeves = sleeve_counts(wiring.holes)
    if sleeves:  # cable passes, one sleeve each (decision 2026-11-28)
        n = sum(sleeves.values())
        listed = ", ".join(f"Ø{d} ×{k}" for d, k in sleeves.items())
        word = plural(n, CABLE_PASS_WORDS[language])
        notes.append(tr("wiring_holes", language, n=n, word=word, sleeves=listed))
    if any(r.mark_assumed for r in wiring.runs):
        notes.append(tr("wiring_mark_note", language))
    if wiring.skipped:
        notes.append(tr("wiring_skipped", language, n=len(wiring.skipped)))
    return notes


def write_chases(wiring: Wiring, path: Path) -> Path:
    """Chase schedule: each chase with wall, place, length, cables and points, m."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "kind",
                "room",
                "wall",
                "offset_mm",
                "length_m",
                "cables",
                "width",
                "route",
                "circuit",
                "points",
            ]
        )
        for c in wiring.chases:
            w.writerow(
                [
                    c.kind,
                    c.room,
                    c.wall,
                    f"{c.offset:.0f}",
                    f"{c.length_mm / 1000:.2f}",
                    c.cables,
                    "wide" if c.wide else "narrow",
                    c.route,
                    c.circuit,
                    " ".join(c.targets),
                ]
            )
    return path


def write_journal(wiring: Wiring, path: Path, titles: dict[str, str] | None = None) -> Path:
    """Cable log: each line with lengths by part, m; titles are meaningful line names
    (objects.wire_titles), otherwise the label column is empty."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "id",
                "label",
                "group",
                "mark",
                "from",
                "to",
                "route",
                "plan_m",
                "vertical_m",
                "ends_m",
                "length_m",
            ]
        )
        for r in wiring.runs:
            w.writerow(
                [
                    r.id,
                    (titles or {}).get(r.id, ""),
                    r.group,
                    r.mark,
                    r.source,
                    r.target,
                    r.route,
                    f"{r.plan_mm / 1000:.2f}",
                    f"{r.vertical_mm / 1000:.2f}",
                    f"{r.ends_mm / 1000:.2f}",
                    f"{r.length_mm / 1000:.2f}",
                ]
            )
    return path
