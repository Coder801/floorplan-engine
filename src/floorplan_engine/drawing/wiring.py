"""Wiring drawing through junction boxes and the cable table for its sheet.

The calculation is in wiring.py; here is only what goes into the DXF: boxes, cable lines by
group (group colour as on the electrical sheet) and the "group → cable type → length" table.

Cables whose routes lie on one line run as a bundle: each has its own lane offset by LANE_MM
on the sheet (lanes), overlapping cables never share a lane; a bundle is at most BAND_MM wide
and does not run onto walls: next to a wall it shifts away from it, and the step shrinks only
if the space between walls is less than the bundle needs (clearance). A line is cut into
pieces where the set of cables does not change (bundles); each piece gets one label beside
the bundle: piece length in m, and the number of cables if more than one: "L2,0 ×3".
At a wall point there is a drop "↓h1,9", at the panel a rise "↑h1,0"; floor routes (own
layer, dash-dot) are the other way round: a rise from the floor to the point "↑h0,3", a drop
at the panel "↓h1,7". Bundles are computed separately for ceiling and floor. Corners are
rounded (an arc in the same polyline).
A label is never placed over routes, boxes, points or other labels: both sides and several
spots along the piece are tried; if nothing fits there is no label (the length is in the
table and the log). Lengths come from the original route (wiring.py): lane shifts and
rounding do not change them.
"""

from __future__ import annotations

import csv
import itertools
import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ezdxf.layouts.layout import Modelspace
from shapely import STRtree
from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry

from floorplan_engine.drawing.ids import tagged
from floorplan_engine.drawing.layers import (
    TEXT_SMALL_MM,
    W_BOX,
    W_CABLES,
    W_TEXT,
    text_descender,
    text_width,
)
from floorplan_engine.drawing.plan import add_text
from floorplan_engine.electrical.boxes import BOX_SIZE_MM
from floorplan_engine.electrical.chases import CHASE_CABLES, CHASE_SHARE
from floorplan_engine.electrical.colors import group_colors
from floorplan_engine.electrical.panel import OTHER_LINE, LineClass
from floorplan_engine.electrical.routing import CLEARANCE
from floorplan_engine.electrical.wiring import LED_MARK
from floorplan_engine.electrical.wiring_model import (
    CHASE_NARROW,
    HOLE_CABLES,
    JunctionBox,
    Run,
    Wiring,
)
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.scale import sheet
from floorplan_engine.model.schema import Electrical
from floorplan_engine.model.texts import Language, tr

LABEL_GAP_MM = 1.0
FILLET_MM = 1.5  # route corner radius on the sheet
LANE_MM = 0.7  # cable lane step on the sheet (decision 2026-10-24)
BAND_MM = 14.0  # a bundle is no wider than this on the sheet: a big bundle gets a smaller step
WALL_CLEAR_MM = 0.4  # from the outermost bundle line to a wall on the sheet
_SAMPLES = (0.1, 0.3, 0.5, 0.7, 0.9)  # where to measure room to walls, fractions
LENGTH_MM = 1.8  # length label height on the sheet
# Label notation (decision 2026-10-24): piece length "L1,4 ×3", vertical drop "↓h1,9",
# like the point height "h300" on the electrical sheet; bare digits were unreadable
LENGTH = "L"
VERT = "h"
LENGTH_OFFSET_MM = 0.6  # from the line (bundle edge) to the label
LENGTH_SLOTS = (0.5, 0.3, 0.7, 0.15, 0.85)  # label spots along the piece, fractions of length
POINT_CLEAR_MM = 2.5  # no labels around a connection point
_TOL = 1.0  # model mm: points on one line


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
    _draw_runs(msp, wiring, paths, layers, labels, colors)
    _draw_bundle_lengths(msp, wiring, plane_bundles, layers, labels, colors)
    _draw_board_rises(msp, wiring, paths, labels)
    _draw_boxes(msp, wiring)


def lay_out(wiring: Wiring) -> tuple[list[list[Vec]], list[Bundle]]:
    """Line paths with lane shifts and bundle pieces, separately for ceiling and floor
    (line numbers in bundles index the shared wiring.runs list)."""
    paths: list[list[Vec]] = [list(r.path) for r in wiring.runs]
    plane_bundles: list[Bundle] = []
    for route in ("ceiling", "floor"):
        idx = [k for k, r in enumerate(wiring.runs) if r.route == route]
        segs = segments([wiring.runs[k].path for k in idx])
        margin = max(sheet(WALL_CLEAR_MM), CLEARANCE)  # bundle also stays CLEARANCE from walls
        room = clearance(wiring.free, margin) if wiring.free is not None else None
        offsets = lanes(segs, sheet(LANE_MM), sheet(BAND_MM), room)
        for j, k in enumerate(idx):
            path = wiring.runs[k].path
            paths[k] = offset_path(path, [offsets.get((j, i), 0.0) for i in range(len(path) - 1)])
        plane_bundles += [
            Bundle(b.axis, b.fixed, b.lo, b.hi, tuple(idx[j] for j in b.runs), b.band)
            for b in bundles(segs, offsets)
        ]
    return paths, plane_bundles


def cable_layer(run: Run, classes: dict[str, LineClass]) -> str:
    """Layer of a line: low-voltage by its circuit, the rest by what its group is; a 12 V LED line
    from the panel is low voltage, but lighting, so it goes by its group."""
    low = run.circuit == "low" and run.mark != LED_MARK
    line = LineClass("low", False) if low else classes.get(run.group, OTHER_LINE)
    return W_CABLES[(line.purpose, line.rcd, run.route == "floor")].name


def _draw_runs(
    msp: Modelspace,
    wiring: Wiring,
    paths: Sequence[Sequence[Vec]],
    layers: Sequence[str],
    labels: _Labels,
    colors: dict[str, int],
) -> None:
    """Lines with rounded corners and a drop (a rise for floor routes) at the point; the drop label
    is on the line's layer, it goes away with the line."""
    for k, run in enumerate(wiring.runs):
        floor = run.route == "floor"
        attribs: dict[str, object] = {"layer": layers[k]}
        if run.group in colors:
            attribs["true_color"] = colors[run.group]
        with tagged(msp, "wire", run.id):
            msp.add_lwpolyline(fillet(paths[k], sheet(FILLET_MM)), format="xyb", dxfattribs=attribs)
            if run.rise_end_mm > 0 and not run.target.startswith("box_"):
                arrow = "↑" if floor else "↓"
                placed = labels.place_end(
                    paths[k], f"{arrow}{VERT}{_m(run.rise_end_mm)}", at_end=True
                )
                if placed is not None:
                    text, at, angle = placed
                    add_text(
                        msp, text, at, LENGTH_MM, layers[k], angle, color=colors.get(run.group)
                    )


def _draw_bundle_lengths(
    msp: Modelspace,
    wiring: Wiring,
    plane_bundles: Sequence[Bundle],
    layers: Sequence[str],
    labels: _Labels,
    colors: dict[str, int],
) -> None:
    """Label for a bundle piece: length in m and the number of cables if more than one. A bundle of
    one group is on the layer of its lines; a mixed one belongs to no cable layer."""
    for bundle in plane_bundles:
        runs = [wiring.runs[k] for k in bundle.runs]
        text = length_label(bundle.length, len(runs))
        placed = labels.place_bundle(text, bundle)
        if placed is None:
            continue
        text, at, angle = placed
        groups = {r.group for r in runs}
        one = len(groups) == 1
        color = colors.get(next(iter(groups))) if one else None
        layer = layers[bundle.runs[0]] if one and color is not None else W_TEXT.name
        with tagged(msp, "wire", runs[0].id):
            add_text(msp, text, at, LENGTH_MM, layer, angle, color=color)


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
    a = b.anchor
    return a.pos if a.inward is None else a.pos + a.inward * (size / 2)


def _draw_boxes(msp: Modelspace, wiring: Wiring) -> None:
    """Boxes: a square at the wall (on the ceiling, on the axes at the box point) and a "К1"
    label.
    """
    size = sheet(BOX_SIZE_MM)
    half = size / 2
    for b in wiring.boxes:
        a = b.anchor
        across, along = (a.inward, a.wall_dir) if a.inward is not None else (Vec(0, 1), Vec(1, 0))
        assert along is not None
        c = _box_center(b, size)
        corners = [
            c + along * sx * half + across * sy * half
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))
        ]
        with tagged(msp, "box", b.id):
            msp.add_lwpolyline(
                [p.as_tuple() for p in corners], close=True, dxfattribs={"layer": W_BOX.name}
            )
            label_at = c + across * (half + sheet(LABEL_GAP_MM)) + along * half
            add_text(msp, b.label, label_at, TEXT_SMALL_MM, W_TEXT.name)


# --- Bundles -----------------------------------------------------------------


@dataclass(frozen=True)
class Segment:
    """Straight route piece along an axis: axis "h" is horizontal (fixed = y), "v" is vertical
    (fixed = x); lo < hi are the end coordinates along the axis."""

    run: int
    index: int  # piece index in the route
    axis: str
    fixed: float
    lo: float
    hi: float


@dataclass(frozen=True)
class Bundle:
    """Line piece on which the set of cables does not change."""

    axis: str
    fixed: float
    lo: float
    hi: float
    runs: tuple[int, ...]
    band: tuple[float, float]  # offsets of the outermost lanes, model mm

    @property
    def length(self) -> float:
        return self.hi - self.lo


def segments(paths: Sequence[Sequence[Vec]]) -> list[Segment]:
    """Route pieces along the axes; slanted pieces (economy, routing.any_angle) are not bundled:
    lines from a box fan out to the points and do not share a lane."""
    out: list[Segment] = []
    for k, path in enumerate(paths):
        for i, (a, b) in enumerate(itertools.pairwise(path)):
            if abs(a.y - b.y) <= _TOL and abs(a.x - b.x) > _TOL:
                out.append(Segment(k, i, "h", round(a.y), min(a.x, b.x), max(a.x, b.x)))
            elif abs(a.x - b.x) <= _TOL and abs(a.y - b.y) > _TOL:
                out.append(Segment(k, i, "v", round(a.x), min(a.y, b.y), max(a.y, b.y)))
    return out


def _by_line(segs: Iterable[Segment]) -> dict[tuple[str, float], list[Segment]]:
    lines: dict[tuple[str, float], list[Segment]] = defaultdict(list)
    for s in segs:
        lines[(s.axis, s.fixed)].append(s)
    return lines


# Room to walls on both sides of a line piece: (axis, coord, from, to) → (to −, to +), model mm
Room = Callable[[str, float, float, float], tuple[float, float]]


def clearance(free: BaseGeometry, margin: float) -> Room:
    """Room on both sides of a piece up to the edge of the free area (walls), minus margin: the
    smallest over several points along the piece; points outside the area do not count."""
    edge = free.boundary
    reach = 1e6

    def side(p: Point, d: tuple[float, float]) -> float:
        ray = LineString([(p.x, p.y), (p.x + d[0] * reach, p.y + d[1] * reach)])
        hit = ray.intersection(edge)
        return reach if hit.is_empty else p.distance(hit)

    def room(axis: str, fixed: float, lo: float, hi: float) -> tuple[float, float]:
        neg = pos = math.inf
        for t in _SAMPLES:
            v = lo + (hi - lo) * t
            p = Point(v, fixed) if axis == "h" else Point(fixed, v)
            if not free.contains(p):
                continue
            up, down = ((0.0, 1.0), (0.0, -1.0)) if axis == "h" else ((1.0, 0.0), (-1.0, 0.0))
            pos = min(pos, side(p, up) - margin)
            neg = min(neg, side(p, down) - margin)
        return max(neg, 0.0), max(pos, 0.0)

    return room


def lanes(
    segs: Sequence[Segment], pitch: float, band: float, room: Room | None = None
) -> dict[tuple[int, int], float]:
    """Offset of each piece from the line: (route, piece) → model mm, along +y for horizontal and
    +x for vertical. Lanes are computed per group of overlapping pieces of a line: overlapping
    ones go in different lanes (interval colouring), step pitch, the whole group no wider than
    band. room is the space to walls: the bundle is symmetric about the line, but next to a wall
    it shifts away; if there is less space than the bundle needs, the step shrinks and the
    bundle takes the full width."""
    out: dict[tuple[int, int], float] = {}
    for line in _by_line(segs).values():
        for cluster in _overlapping(line):
            ends: list[float] = []  # end of the last piece in each lane
            lane_of: dict[tuple[int, int], int] = {}
            for s in cluster:
                free = next((n for n, end in enumerate(ends) if end <= s.lo + _TOL), None)
                if free is None:
                    free = len(ends)
                    ends.append(s.hi)
                else:
                    ends[free] = s.hi
                lane_of[(s.run, s.index)] = free
            count = len(ends)
            if count == 1:
                for key in lane_of:
                    out[key] = 0.0
                continue
            width = min(pitch * (count - 1), band)
            center = 0.0
            if room is not None:
                s0 = cluster[0]
                neg, pos = room(
                    s0.axis, s0.fixed, min(s.lo for s in cluster), max(s.hi for s in cluster)
                )
                if neg + pos < width:  # not enough room: smaller step, full width
                    width, center = neg + pos, (pos - neg) / 2
                else:  # next to a wall: shift away from it
                    center = min(max(0.0, width / 2 - neg), pos - width / 2)
            step = width / (count - 1)
            for key, n in lane_of.items():
                out[key] = center + (n - (count - 1) / 2) * step
    return out


def _overlapping(line: Sequence[Segment]) -> list[list[Segment]]:
    """Line pieces in groups: in a group each overlaps at least one other (touching does not
    count).
    """
    groups: list[list[Segment]] = []
    reach = -math.inf
    for s in sorted(line, key=lambda s: (s.lo, s.hi, s.run)):
        if s.lo < reach - _TOL:
            groups[-1].append(s)
            reach = max(reach, s.hi)
        else:
            groups.append([s])
            reach = s.hi
    return groups


def bundles(segs: Sequence[Segment], offsets: dict[tuple[int, int], float]) -> list[Bundle]:
    """Line pieces with a constant set of cables: cut points are the piece ends."""
    out: list[Bundle] = []
    for (axis, fixed), line in _by_line(segs).items():
        cuts = sorted({c for s in line for c in (s.lo, s.hi)})
        for lo, hi in itertools.pairwise(cuts):
            here = [s for s in line if s.lo <= lo + _TOL and s.hi >= hi - _TOL]
            if not here or hi - lo <= _TOL:
                continue
            shifts = [offsets.get((s.run, s.index), 0.0) for s in here]
            runs = tuple(sorted({s.run for s in here}))
            out.append(Bundle(axis, fixed, lo, hi, runs, (min(shifts), max(shifts))))
    return out


def offset_path(path: Sequence[Vec], shifts: Sequence[float]) -> list[Vec]:
    """Route with each piece shifted into its lane; a vertex between horizontal and vertical is the
    intersection of the shifted pieces, the ends move across their own piece."""
    if len(path) < 2:
        return list(path)

    def normal(i: int) -> Vec:
        a, b = path[i], path[i + 1]
        return Vec(0.0, 1.0) if abs(a.y - b.y) <= _TOL else Vec(1.0, 0.0)

    out = [path[0] + normal(0) * shifts[0]]
    for i in range(1, len(path) - 1):
        n_in, n_out = normal(i - 1), normal(i)
        p = path[i]
        if n_in == n_out:
            out.append(p + n_out * shifts[i])
        else:
            out.append(p + n_in * shifts[i - 1] + n_out * shifts[i])
    out.append(path[-1] + normal(len(path) - 2) * shifts[-1])
    return out


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

    def _free(self, rect: BaseGeometry) -> bool:
        if any(rect.intersects(t) for t in self.taken):
            return False
        return not any(rect.intersects(self.lines.geometries[i]) for i in self.lines.query(rect))

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

    def place_bundle(self, text: str, b: Bundle) -> Label | None:
        """Bundle piece label beside the outermost lane; a short piece gets no label."""
        if sheet(text_width(text, LENGTH_MM)) + 2 * self.gap > b.length:
            return None
        along = Vec(1.0, 0.0) if b.axis == "h" else Vec(0.0, 1.0)
        across = Vec(0.0, 1.0) if b.axis == "h" else Vec(1.0, 0.0)
        reach = self.gap + self.h / 2
        sides = (across * (b.band[1] + reach), across * (b.band[0] - reach))
        spots = []
        for t in LENGTH_SLOTS:
            pos = b.lo + (b.hi - b.lo) * t
            on_line = Vec(pos, b.fixed) if b.axis == "h" else Vec(b.fixed, pos)
            spots += [(on_line + side, along) for side in sides]
        return self._try(text, spots)

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
    if wiring.holes:
        large = sum(1 for h in wiring.holes if h.large)
        notes.append(tr("wiring_holes", language, n=len(wiring.holes), m=large, k=HOLE_CABLES))
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
