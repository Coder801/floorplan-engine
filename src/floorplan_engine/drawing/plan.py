"""Plan drawing: walls, openings, dimensions, room names and areas, wall codes.

The walls of all rooms are first merged into one silhouette: a partition shared by two rooms
is drawn once, and where a partition meets an exterior wall there are no inner lines.
The silhouette boundary is drawn as segments by coordinates, openings are gaps with reveals.
Hatching: load-bearing (monolithic) walls are dense, partitions are sparse. Where a
load-bearing wall meets a partition, a material boundary line remains.
Every wall gets its code ("2.В", model/wall_names.py) inside the room along the wall, on a spot
free of dimensions, labels and door swings: the same code as on the elevations and in the viewer.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import shapely
from ezdxf.entities.lwpolyline import LWPolyline
from ezdxf.enums import MTextEntityAlignment, TextEntityAlignment
from ezdxf.layouts.base import BaseLayout
from ezdxf.layouts.layout import Modelspace
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from floorplan_engine.drawing.fields import add_area_field
from floorplan_engine.drawing.ids import tagged
from floorplan_engine.drawing.layers import (
    A_AREA,
    A_DIMS,
    A_DOOR,
    A_TEXT,
    A_WALL,
    A_WIND,
    DIM_STYLE,
    TEXT_DIM_MM,
    TEXT_ROOM_MM,
    TEXT_SMALL_MM,
    TEXT_STYLE,
    text_width,
)
from floorplan_engine.drawing.titleblock import StampText
from floorplan_engine.model.geometry import (
    Contour,
    RoomGeometry,
    Vec,
    WallSegment,
    point_in_polygon,
    room_geometries,
    signed_area,
)
from floorplan_engine.model.scale import DEFAULT_SCALE, sheet, sheet_scale
from floorplan_engine.model.schema import Opening, OpeningType, Plan, Room
from floorplan_engine.model.texts import Language, tr
from floorplan_engine.model.wall_names import wall_codes
from floorplan_engine.model.zones import Floor, plan_floors

HATCH_PATTERN = "ANSI31"
# Hatch scale at 1:50; at another sheet scale it is proportional, so the step on paper
# stays the same
HATCH_SCALE_BEARING = 12.0  # ANSI31 step 3.175 × 12 ≈ 38 mm, 0.8 mm on the sheet
HATCH_SCALE_PARTITION = 30.0  # ≈ 95 mm, 1.9 mm on the sheet
GRID = 0.1  # wall coordinate grid, mm: shared faces of neighbouring rooms match exactly
MIN_AREA = 1.0  # mm²: smaller pieces are noise and are not hatched
DIM_LEVEL_1_MM = 8.0  # first dimension row from the wall face, sheet mm
DIM_LEVEL_STEP_MM = 7.0  # step between rows
DIM_TEXT_GAP_MM = 0.8  # gap around a dimension label along the line (like dimgap)
DIM_LIFT_MM = TEXT_DIM_MM * 1.4  # a label with no room along the line goes one row up
DIM_GAP_MM = 0.8  # label above the dimension line (style dimgap)
DIM_LINE_BAND_MM = 0.4  # dimension line band for overlap checks
DIM_STEPS_MM = (0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0)  # how much farther to move the label
DIM_MAX_SHIFTS = 4  # how many levels a row may move if its place is taken
SHARED_WALL_TOLERANCE = 1.0
CODE_INSETS_MM = (3.0, 13.0, 18.0, 23.0)  # wall code from the inner face, sheet mm (dims at 8)
CODE_ALONG = (0.5, 0.35, 0.65, 0.2, 0.8, 0.1, 0.9)  # spots along the wall, middle first
CODE_GAP_MM = 0.6  # free margin around a wall code


def _xy(v: Vec) -> tuple[float, float]:
    return v.as_tuple()


def _gaps(room: Room, wall: str) -> list[tuple[float, float]]:
    """Sorted opening intervals on a wall."""
    spans = [(o.offset, o.offset + o.width) for o in room.openings if o.wall == wall]
    return sorted(spans)


def _solid_intervals(
    lo: float, hi: float, gaps: Sequence[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Parts of the segment [lo, hi] without openings."""
    result: list[tuple[float, float]] = []
    pos = lo
    for a, b in gaps:
        if a > pos:
            result.append((pos, min(a, hi)))
        pos = max(pos, b)
    if pos < hi:
        result.append((pos, hi))
    return [(a, b) for a, b in result if b - a > 1e-6]


# --- Walls -------------------------------------------------------------------


@dataclass(frozen=True)
class WallPiece:
    """Solid wall piece between openings.

    polygon is a quadrilateral from the inner face to the outer one with mitred ends: these
    make up the wall silhouette (outline). body is the wall body for hatching: a rectangle
    extended at convex corners by the thickness of the neighbouring wall. A corner belongs
    entirely to one wall, the neighbour butts into it at 90°, so plan joints are square,
    with no mitre seam (a load-bearing wall is continuous, a partition butts into it).
    """

    tag: str  # "room.wall": the FLOORPLAN_ENGINE tag
    bearing: bool
    polygon: BaseGeometry
    body: BaseGeometry


def convex(a: WallSegment, b: WallSegment) -> bool:
    """The corner between wall a and the next wall b is convex (clockwise walk turns right)."""
    return a.direction.x * b.direction.y - a.direction.y * b.direction.x < 0


def _snap(geometry: BaseGeometry) -> BaseGeometry:
    # A short wall at a reflex corner can produce a "bow tie": fix it, then snap to the grid
    return shapely.set_precision(shapely.make_valid(geometry), GRID)


def _open_at_end(room: Room, seg: WallSegment) -> bool:
    """The wall's opening reaches the wall end."""
    return any(b >= seg.length - 1e-6 for _, b in _gaps(room, seg.id))


def _open_at_start(room: Room, seg: WallSegment) -> bool:
    """The wall's opening starts at the wall start."""
    return any(a <= 1e-6 for a, _ in _gaps(room, seg.id))


def wall_pieces(g: RoomGeometry) -> list[WallPiece]:
    out: list[WallPiece] = []
    segs = g.contour.segments
    for seg in segs:
        prev, nxt = segs[seg.index - 1], segs[(seg.index + 1) % len(segs)]
        pieces = _solid_intervals(0.0, seg.length, _gaps(g.room, seg.id))
        for k, (a, b) in enumerate(pieces):
            first = k == 0 and a == 0.0
            last = k == len(pieces) - 1 and abs(b - seg.length) < 1e-6
            inner_a, inner_b = seg.point_at(a), seg.point_at(b)
            outer_a = g.outer_start(seg) if first else g.outer_point(seg, a)
            outer_b = g.outer_end(seg) if last else g.outer_point(seg, b)
            # The neighbour's window or door reaches the convex corner: the corner belongs wholly to
            # this wall, with a square end rather than a mitre
            if first and convex(prev, seg) and _open_at_end(g.room, prev):
                inner_a = seg.point_at(-prev.thickness)
                outer_a = g.outer_point(seg, -prev.thickness)
            if last and convex(seg, nxt) and _open_at_start(g.room, nxt):
                inner_b = seg.point_at(seg.length + nxt.thickness)
                outer_b = g.outer_point(seg, seg.length + nxt.thickness)
            quad = Polygon([_xy(inner_a), _xy(inner_b), _xy(outer_b), _xy(outer_a)])
            lo = a - (prev.thickness if first and convex(prev, seg) else 0.0)
            hi = b + (nxt.thickness if last and convex(seg, nxt) else 0.0)
            out_dir = seg.outward * seg.thickness
            body = Polygon(
                [
                    _xy(seg.point_at(lo)),
                    _xy(seg.point_at(hi)),
                    _xy(seg.point_at(hi) + out_dir),
                    _xy(seg.point_at(lo) + out_dir),
                ]
            )
            out.append(WallPiece(f"{g.room.id}.{seg.id}", seg.bearing, _snap(quad), _snap(body)))
    return out


def _owned(
    geoms: Sequence[RoomGeometry],
) -> tuple[list[WallPiece], BaseGeometry, BaseGeometry, list[BaseGeometry]]:
    """Wall pieces, the silhouette, the load-bearing part and what each piece owns on the plan."""
    # Load-bearing walls first: at a joint with a partition the spot goes to the load-bearing wall
    pieces = sorted((p for g in geoms for p in wall_pieces(g)), key=lambda p: not p.bearing)
    total = shapely.unary_union([p.polygon for p in pieces])
    bearing = shapely.unary_union([p.body for p in pieces if p.bearing]).intersection(total)
    covered: BaseGeometry = Polygon()
    owned: list[BaseGeometry] = []
    for p in pieces:
        # The wall body, not the mitred piece: the joint with the next wall is at 90°
        body = p.body.intersection(total)
        area = body.intersection(bearing) if p.bearing else body.difference(bearing)
        owned.append(area.difference(covered))
        covered = covered.union(area)
    return pieces, total, bearing, owned


def wall_areas(geoms: Sequence[RoomGeometry]) -> dict[str, BaseGeometry]:
    """Plan area of each wall, tag → area, as hatched; a wall covered by its neighbour (the top
    of a pylon inside a thick wall) has none."""
    pieces, _, _, owned = _owned(geoms)
    by_tag: dict[str, list[BaseGeometry]] = {}
    for p, own in zip(pieces, owned, strict=True):
        by_tag.setdefault(p.tag, []).append(own)
    areas = {tag: shapely.unary_union(parts) for tag, parts in by_tag.items()}
    return {tag: area for tag, area in areas.items() if area.area > 0}


def draw_walls(msp: Modelspace, geoms: Sequence[RoomGeometry]) -> None:
    """Walls of all rooms: hatching by material and the shared silhouette boundary."""
    pieces, total, bearing, owned = _owned(geoms)
    for p, own in zip(pieces, owned, strict=True):
        base = HATCH_SCALE_BEARING if p.bearing else HATCH_SCALE_PARTITION
        scale = base * sheet_scale() / DEFAULT_SCALE
        with tagged(msp, "wall", p.tag):
            _hatch(msp, own, scale)
    # Silhouette boundary and the "load-bearing | partition" line; shared parts drawn once
    edges = shapely.unary_union([total.boundary, bearing.boundary])
    by_tag: dict[str, list[shapely.LineString]] = {}
    for line in shapely.get_parts(edges):
        for a, b in itertools.pairwise(line.coords):
            seg = shapely.LineString([a, b])
            owner = _owner(pieces, seg.interpolate(0.5, normalized=True))
            by_tag.setdefault(owner, []).append(seg)
    layer = {"layer": A_WALL.name}
    for tag, segs in by_tag.items():
        merged = shapely.line_merge(shapely.MultiLineString(segs))
        with tagged(msp, "wall", tag):
            for line in shapely.get_parts(merged):
                # Collinear points (joints of pieces) are removed: one line from corner to corner
                pts = list(line.simplify(GRID / 2).coords)
                for a, b in itertools.pairwise(pts):
                    msp.add_line(a, b, dxfattribs=layer)


def _owner(pieces: Sequence[WallPiece], at: BaseGeometry) -> str:
    """The wall whose face contains the point; load-bearing walls are checked first."""
    for p in pieces:
        if p.polygon.boundary.distance(at) <= GRID or p.body.boundary.distance(at) <= GRID:
            return p.tag
    return min(pieces, key=lambda p: p.polygon.distance(at)).tag


def _hatch(msp: Modelspace, area: BaseGeometry, scale: float) -> None:
    for part in shapely.get_parts(area):
        if not isinstance(part, Polygon) or part.area < MIN_AREA:
            continue
        hatch = msp.add_hatch(color=256, dxfattribs={"layer": A_WALL.name})
        hatch.set_pattern_fill(HATCH_PATTERN, scale=scale)
        hatch.paths.add_polyline_path(list(part.exterior.coords)[:-1], is_closed=True)
        for hole in part.interiors:
            hatch.paths.add_polyline_path(list(hole.coords)[:-1], is_closed=True, flags=0)


# --- Openings ----------------------------------------------------------------


def draw_openings(msp: Modelspace, g: RoomGeometry, language: Language = "ru") -> None:
    for op in g.room.openings:
        with tagged(msp, "opening", op.id):
            seg = g.contour.segment(op.wall)
            if op.type is OpeningType.DOOR:
                _draw_door(msp, g, seg, op)
            elif op.type is OpeningType.WINDOW:
                _draw_window(msp, g, seg, op, language)


def door_leaf(g: RoomGeometry, seg: WallSegment, op: Opening) -> tuple[Vec, Vec, Vec]:
    """Hinge, edge of the closed leaf and the opening direction of a door."""
    hinge_off, free_off = (
        (op.offset, op.offset + op.width)
        if op.hinge == "start"
        else (op.offset + op.width, op.offset)
    )
    if op.swing == "in":
        return seg.point_at(hinge_off), seg.point_at(free_off), seg.inward
    return g.outer_point(seg, hinge_off), g.outer_point(seg, free_off), seg.outward


def _draw_door(msp: Modelspace, g: RoomGeometry, seg: WallSegment, op: Opening) -> None:
    layer = {"layer": A_DOOR.name}
    hinge, closed, normal = door_leaf(g, seg, op)
    leaf_end = hinge + normal * op.width
    msp.add_line(_xy(hinge), _xy(leaf_end), dxfattribs=layer)
    a_closed = math.degrees(math.atan2(closed.y - hinge.y, closed.x - hinge.x))
    a_open = math.degrees(math.atan2(leaf_end.y - hinge.y, leaf_end.x - hinge.x))
    # ARC goes counter-clockwise from start_angle to end_angle
    if (closed - hinge).cross(leaf_end - hinge) > 0:
        start, end = a_closed, a_open
    else:
        start, end = a_open, a_closed
    msp.add_arc(_xy(hinge), op.width, start, end, dxfattribs=layer)


def _draw_window(
    msp: Modelspace, g: RoomGeometry, seg: WallSegment, op: Opening, language: Language
) -> None:
    layer = {"layer": A_WIND.name}
    a, b = op.offset, op.offset + op.width
    for frac in (0.0, 0.5, 1.0):
        shift = seg.outward * (seg.thickness * frac)
        msp.add_line(_xy(seg.point_at(a) + shift), _xy(seg.point_at(b) + shift), dxfattribs=layer)
    if op.sill is not None:
        mid = sill_spot(seg, op)
        text = tr("sill", language, sill=f"{op.sill:g}")
        # On the plan labels layer: the other sheets take windows, but a sill is not for them
        add_text(msp, text, mid, TEXT_SMALL_MM, A_TEXT.name, seg.angle_deg)


def sill_spot(seg: WallSegment, op: Opening) -> Vec:
    """Centre of a window's sill label: inside the room by the middle of the window."""
    return seg.point_at(op.offset + op.width / 2) + seg.inward * sheet(TEXT_SMALL_MM * 1.2)


def _sill_box(g: RoomGeometry, op: Opening, language: Language) -> BaseGeometry:
    """Spot of a sill label (_draw_window): wall codes do not sit on it."""
    seg = g.contour.segment(op.wall)
    d, up = _reading(seg)
    c = sill_spot(seg, op)
    text = tr("sill", language, sill=f"{op.sill:g}")
    hw = sheet(text_width(text, TEXT_SMALL_MM) / 2 + CODE_GAP_MM)
    hh = sheet(TEXT_SMALL_MM / 2 + CODE_GAP_MM)
    return Polygon([_xy(c + d * sx * hw + up * sy * hh) for sx, sy in CORNERS])


# --- Dimensions --------------------------------------------------------------


def readable_angle(angle: float) -> float:
    """Text angle that keeps it from reading upside down."""
    angle = (angle + 180.0) % 360.0 - 180.0
    if angle > 90.0 + 1e-6 or angle <= -90.0 + 1e-6:
        angle += 180.0
    return angle


def _reading(seg: WallSegment) -> tuple[Vec, Vec]:
    """Reading direction of a dimension label along the wall and the "above the line" side."""
    d = seg.direction
    angle = math.degrees(math.atan2(d.y, d.x))
    if abs(readable_angle(angle) - angle) > 1e-6:
        d = d * -1.0
    return d, d.left()


def _dim_label(a: float, b: float) -> str:
    return f"{b - a:.0f}"


def _text_box(seg: WallSegment, a: float, b: float, offset: float, move: Vec) -> BaseGeometry:
    """Position of the label for segment a…b: above the dimension line at offset (+ is outward),
    shifted by move (model mm)."""
    d, up = _reading(seg)
    hw = sheet(text_width(_dim_label(a, b), TEXT_DIM_MM) / 2 + DIM_TEXT_GAP_MM)
    hh = sheet(TEXT_DIM_MM * 0.6)
    c = seg.point_at((a + b) / 2) + seg.outward * offset + up * (sheet(DIM_GAP_MM) + hh) + move
    return Polygon([_xy(c + d * sx * hw + up * sy * hh) for sx, sy in CORNERS])


CORNERS = ((-1, -1), (1, -1), (1, 1), (-1, 1))


def _fits(a: float, b: float) -> bool:
    """The label fits between the segment's extension lines."""
    return sheet(text_width(_dim_label(a, b), TEXT_DIM_MM) + 2 * DIM_TEXT_GAP_MM) <= b - a


def _moves(seg: WallSegment, a: float, b: float) -> list[Vec]:
    """Where a narrow segment's label may go: along the line past the segment (closer first),
    then one row up, centred and along the line."""
    d, up = _reading(seg)
    reach = (b - a) / 2 + sheet(text_width(_dim_label(a, b), TEXT_DIM_MM) / 2 + DIM_TEXT_GAP_MM)
    along = [reach + sheet(step) for step in DIM_STEPS_MM]
    lift = up * sheet(DIM_LIFT_MM)
    out = [d * (sign * x) for x in along for sign in (1.0, -1.0)]
    return out + [lift] + [lift + v for v in out]


def _line_band(seg: WallSegment, offset: float) -> BaseGeometry:
    """Dimension line of a row: other labels must not sit on it. The ends are trimmed: at a room
    corner the lines of neighbouring walls always cross."""
    band = sheet(DIM_LINE_BAND_MM)
    trim = min(abs(offset) + sheet(DIM_GAP_MM), seg.length * 0.45)
    a, b, n = seg.point_at(trim), seg.point_at(seg.length - trim), seg.outward
    lo, hi = offset - band, offset + band
    return Polygon([_xy(a + n * lo), _xy(b + n * lo), _xy(b + n * hi), _xy(a + n * hi)])


def _hits(geom: BaseGeometry, taken: Sequence[BaseGeometry]) -> bool:
    return any(geom.intersection(t).area > 0 for t in taken)


def _place_rows(
    seg: WallSegment,
    rows: Sequence[Sequence[tuple[float, float]]],
    sign: float,
    base: float,
    taken: list[BaseGeometry],
) -> tuple[float, list[list[Vec | None]]]:
    """Wall dimension rows (segments of each row) at the first level where their labels do not touch
    what is already placed (taken); narrow labels move to a free spot nearby (_moves).
    Returns the level of the first row and the label shifts; adds what it placed to taken."""
    step = sheet(DIM_LEVEL_STEP_MM)
    zero = Vec(0.0, 0.0)

    def offsets(start: float) -> list[float]:
        return [sign * (start + r * step) for r in range(len(rows))]

    level = base
    for k in range(DIM_MAX_SHIFTS + 1):
        start = base + k * step
        boxes = [
            _text_box(seg, a, b, off, zero)
            for parts, off in zip(rows, offsets(start), strict=True)
            for a, b in parts
            if _fits(a, b)
        ]
        lines = [_line_band(seg, off) for off in offsets(start)]
        if not any(_hits(g, taken) for g in boxes + lines):
            level = start
            break
    moves: list[list[Vec | None]] = []
    for parts, off in zip(rows, offsets(level), strict=True):
        row: list[Vec | None] = []
        for a, b in parts:
            default = _text_box(seg, a, b, off, zero)
            if _fits(a, b) and not _hits(default, taken):
                taken.append(default)
                row.append(None)
                continue
            # Narrow, or landed on something else: nearest free spot nearby
            options = ([zero] if _fits(a, b) else []) + _moves(seg, a, b)
            move = next(
                (m for m in options if not _hits(_text_box(seg, a, b, off, m), taken)), options[0]
            )
            taken.append(_text_box(seg, a, b, off, move))
            row.append(None if move == zero else move)
        moves.append(row)
    taken.extend(_line_band(seg, off) for off in offsets(level))
    return level, moves


def _add_dim(
    msp: Modelspace, p1: Vec, p2: Vec, offset_outward: float, move: Vec | None = None
) -> None:
    """Dimension between points on the wall face, offset along the normal outward (+) or inward (−);
    move shifts the label from its default spot, model mm (narrow segment of a chain).

    For add_aligned_dim a positive distance is to the left of p1→p2, and "left" of a wall is
    outward.
    If the wall runs left or down, the points are swapped so the text is not upside down.
    """
    d = p2 - p1
    angle = math.degrees(math.atan2(d.y, d.x))
    if abs(readable_angle(angle) - angle) > 1e-6:
        p1, p2, offset_outward = p2, p1, -offset_outward
    dim = msp.add_aligned_dim(
        p1=_xy(p1),
        p2=_xy(p2),
        distance=offset_outward,
        dimstyle=DIM_STYLE,
        dxfattribs={"layer": A_DIMS.name},
    )
    if move is not None:
        dim.set_location(_xy(move), relative=True)
    dim.render()


def _outside_is_free(g: RoomGeometry, seg: WallSegment, others: Sequence[RoomGeometry]) -> bool:
    """There is no other room outside the wall (dimensions may go there)."""
    mid = seg.point_at(seg.length / 2) + seg.outward * (seg.thickness + sheet(DIM_LEVEL_1_MM))
    return not any(point_in_polygon(mid, o.contour.vertices) for o in others if o is not g)


def mirrored_wall(g: RoomGeometry, seg: WallSegment, other: RoomGeometry) -> WallSegment | None:
    """The wall of another room that is the other side of this same partition."""
    far_start = seg.start + seg.outward * seg.thickness
    far_end = seg.end + seg.outward * seg.thickness
    mine = [(seg.length - b, seg.length - a) for a, b in _gaps(g.room, seg.id)]
    for o in other.contour.segments:
        if (o.start - far_end).length() <= SHARED_WALL_TOLERANCE and (
            o.end - far_start
        ).length() <= SHARED_WALL_TOLERANCE:
            theirs = _gaps(other.room, o.id)
            same = len(mine) == len(theirs) and all(
                abs(a1 - a2) <= SHARED_WALL_TOLERANCE and abs(b1 - b2) <= SHARED_WALL_TOLERANCE
                for (a1, b1), (a2, b2) in zip(mine, theirs, strict=True)
            )
            return o if same else None
    return None


def draw_dimensions(
    msp: Modelspace,
    g: RoomGeometry,
    all_rooms: Sequence[RoomGeometry],
    done: Sequence[RoomGeometry] = (),
    taken: list[BaseGeometry] | None = None,
) -> None:
    """Dimensions along the inner face of the wall.

    Free outside: place them beyond the building extent: row 1 is the chain of openings,
    row 2 the total length.
    A neighbouring room outside: the same rows go inside this room, but only if this partition
    has not been dimensioned from the neighbour's side yet (`done`).
    taken holds labels and dimension lines of rows already placed and room labels, shared by all
    rooms: a row whose labels land on them moves to the next level; a narrow label (does not fit
    between the extension lines) moves to a free spot nearby.
    """
    taken = taken if taken is not None else []
    for seg in g.contour.segments:
        with tagged(msp, "dimension", f"{g.room.id}.{seg.id}"):
            gaps = _gaps(g.room, seg.id)
            if _outside_is_free(g, seg, all_rooms):
                # Beyond the building extent on this wall's side: facade dimensions on one line
                reach = max(c.dot(seg.outward) for r in all_rooms for c in r.corners)
                sign, base = 1.0, reach - seg.start.dot(seg.outward) + sheet(DIM_LEVEL_1_MM)
            else:
                if any(mirrored_wall(g, seg, o) is not None for o in done):
                    continue
                sign, base = -1.0, sheet(DIM_LEVEL_1_MM)
            parts = [(0.0, seg.length)]
            if gaps:
                stops = sorted({0.0, seg.length, *(x for gap in gaps for x in gap)})
                parts = list(itertools.pairwise(stops))
            # Rows: chain of openings (if any), then the total length
            rows = [parts, [(0.0, seg.length)]] if gaps else [parts]
            level, moves = _place_rows(seg, rows, sign, base, taken)
            step = sheet(DIM_LEVEL_STEP_MM)
            for r, (row, row_moves) in enumerate(zip(rows, moves, strict=True)):
                for (a, b), move in zip(row, row_moves, strict=True):
                    _add_dim(msp, seg.point_at(a), seg.point_at(b), sign * (level + r * step), move)


# --- Labels ------------------------------------------------------------------


def add_text(
    msp: BaseLayout,
    text: str,
    at: Vec,
    height_mm: float,
    layer: str,
    angle: float = 0.0,
    align: TextEntityAlignment = TextEntityAlignment.MIDDLE_CENTER,
    color: int | None = None,
    scale: float | None = None,
) -> None:
    """Text in the project style; color is a true color (0xRRGGBB) instead of the layer colour.

    height_mm is the height on the sheet; scale is how many drawing units per sheet mm:
    None means model space (current sheet scale), 1 means on the sheet itself.
    """
    if scale is None:
        scale = sheet_scale()
    attribs: dict[str, object] = {"layer": layer, "style": TEXT_STYLE}
    if color is not None:
        attribs["true_color"] = color
    msp.add_text(
        text,
        height=height_mm * scale,
        rotation=readable_angle(angle),
        dxfattribs=attribs,
    ).set_placement(_xy(at), align=align)


def polygon_centroid(points: Sequence[Vec]) -> Vec:
    area = signed_area(points)
    if abs(area) < 1e-9:
        n = len(points)
        return Vec(sum(p.x for p in points) / n, sum(p.y for p in points) / n)
    cx = cy = 0.0
    for i, a in enumerate(points):
        b = points[(i + 1) % len(points)]
        k = a.cross(b)
        cx += (a.x + b.x) * k
        cy += (a.y + b.y) * k
    return Vec(cx / (6 * area), cy / (6 * area))


def label_point(pts: Sequence[Vec]) -> Vec:
    """Label point of an outline: the centroid, or the nearest node inside if the centroid is
    outside (L shape).
    """
    c = polygon_centroid(pts)
    if point_in_polygon(c, pts):
        return c
    xs, ys = [p.x for p in pts], [p.y for p in pts]
    best: Vec | None = None
    steps = 20
    for i in range(1, steps):
        for j in range(1, steps):
            p = Vec(
                min(xs) + (max(xs) - min(xs)) * i / steps,
                min(ys) + (max(ys) - min(ys)) * j / steps,
            )
            if point_in_polygon(p, pts) and (
                best is None or (p - c).length() < (best - c).length()
            ):
                best = p
    return best if best is not None else c


@dataclass(frozen=True)
class RoomArea:
    """Floor area outline in the model (a room, or a zone of it) and its current area, for
    AutoCAD fields; name is the room schedule row."""

    contour: LWPolyline
    area_mm2: float
    name: str


def draw_area_contour(msp: Modelspace, floor: Floor) -> RoomArea:
    """Inner floor outline as a separate polyline: the area fields refer to it."""
    poly = msp.add_lwpolyline(
        [_xy(v) for v in floor.vertices], close=True, dxfattribs={"layer": A_AREA.name}
    )
    return RoomArea(poly, floor.area_mm2, floor.name)


def _room_label_box(floor: Floor) -> BaseGeometry:
    """Spot of the floor name and area (draw_room_label): dimensions do not sit on it."""
    at = label_point(floor.vertices)
    w = max(text_width(floor.name, TEXT_ROOM_MM), text_width("00,00 м²", TEXT_DIM_MM))
    hw, hh = sheet(w / 2 + 1.0), sheet(TEXT_ROOM_MM * 1.6)
    return Polygon(
        [
            (at.x - hw, at.y - hh),
            (at.x + hw, at.y - hh),
            (at.x + hw, at.y + hh),
            (at.x - hw, at.y + hh),
        ]
    )


def draw_room_label(msp: Modelspace, floor: Floor, area: RoomArea) -> None:
    """Floor name and area; the area is an AutoCAD field from the area outline."""
    doc = msp.doc
    assert doc is not None
    at = label_point(floor.vertices)
    gap = sheet(TEXT_ROOM_MM) * 0.8
    add_text(msp, floor.name, at + Vec(0, gap), TEXT_ROOM_MM, A_TEXT.name)
    mtext = msp.add_mtext(
        "",
        dxfattribs={"layer": A_TEXT.name, "style": TEXT_STYLE, "char_height": sheet(TEXT_DIM_MM)},
    )
    mtext.set_location(_xy(at - Vec(0, gap)), attachment_point=MTextEntityAlignment.MIDDLE_CENTER)
    add_area_field(doc, mtext, area.contour, area.area_mm2, suffix=" м²")


# --- Assembly ----------------------------------------------------------------


def draw_plan(msp: Modelspace, plan: Plan, contours: dict[str, Contour]) -> dict[str, RoomArea]:
    """Plan in the model at 1:1: walls, openings, area outlines, labels, dimensions.

    Returns the area outlines by floor key (`zones.plan_floors`: a room, or each zone of an
    open-plan room), in schedule order: the room schedule fields refer to them.
    """
    geoms = room_geometries(plan, contours)
    floors = plan_floors(plan, contours)
    areas: dict[str, RoomArea] = {}
    draw_walls(msp, geoms)
    for g in geoms:
        draw_openings(msp, g, plan.language)
    for f in floors:
        kind, _, object_id = f.key.partition(":")
        with tagged(msp, kind, object_id):
            areas[f.key] = draw_area_contour(msp, f)
            draw_room_label(msp, f, areas[f.key])
    # Shared partitions are dimensioned from the larger room
    done: list[RoomGeometry] = []
    # Dimension labels do not sit on room names or walls. Door swings do not count: in a
    # hallway with three doors the labels would otherwise have nowhere to go near their segment
    taken = [_room_label_box(f) for f in floors]
    taken += [p.polygon for g in geoms for p in wall_pieces(g)]
    for g in sorted(geoms, key=lambda r: r.contour.area_mm2, reverse=True):
        draw_dimensions(msp, g, geoms, done, taken)
        done.append(g)
    codes = wall_codes(plan, contours)
    # Codes stay off door swings and sill labels too, and off each other
    taken += [
        door_swing(g, op) for g in geoms for op in g.room.openings if op.type is OpeningType.DOOR
    ]
    taken += [
        _sill_box(g, op, plan.language)
        for g in geoms
        for op in g.room.openings
        if op.type is OpeningType.WINDOW and op.sill is not None
    ]
    for g in geoms:
        draw_wall_codes(msp, g, codes, taken)
    return areas


def door_swing(g: RoomGeometry, op: Opening) -> BaseGeometry:
    """Square the door leaf sweeps (holds its arc), in whichever room it opens into."""
    hinge, edge, way = door_leaf(g, g.contour.segment(op.wall), op)
    reach = way * op.width
    return Polygon([_xy(hinge), _xy(edge), _xy(edge + reach), _xy(hinge + reach)])


def _code_box(seg: WallSegment, code: str, at: float, inset: float) -> tuple[Vec, BaseGeometry]:
    """Centre and outline of a wall code at offset at along the wall, inset from its inner face
    (model mm)."""
    d, up = _reading(seg)
    c = seg.point_at(at) + seg.inward * inset
    hw = sheet(text_width(code, TEXT_DIM_MM) / 2 + CODE_GAP_MM)
    hh = sheet(TEXT_DIM_MM / 2 + CODE_GAP_MM)
    return c, Polygon([_xy(c + d * sx * hw + up * sy * hh) for sx, sy in CORNERS])


def draw_wall_codes(
    msp: Modelspace,
    g: RoomGeometry,
    codes: dict[tuple[str, str], str],
    taken: list[BaseGeometry],
) -> None:
    """Code of every wall inside the room along it: the first spot (middle first, close to the
    face first) that is inside the room and off what is in taken (dimensions, labels, door
    swings); with no free spot, the middle by the face. Placed codes are added to taken."""
    room = Polygon([_xy(v) for v in g.contour.vertices])
    for seg in g.contour.segments:
        code = codes[(g.room.id, seg.id)]
        spots = [
            _code_box(seg, code, seg.length * k, sheet(inset))
            for inset in CODE_INSETS_MM
            for k in CODE_ALONG
        ]
        at, box = next(
            ((c, b) for c, b in spots if room.contains(b) and not _hits(b, taken)),
            spots[0],
        )
        taken.append(box)
        d, _ = _reading(seg)
        with tagged(msp, "wall", f"{g.room.id}.{seg.id}"):
            add_text(msp, code, at, TEXT_DIM_MM, A_TEXT.name, math.degrees(math.atan2(d.y, d.x)))


def plan_stamp(
    plan: Plan, image_key: str, sheet_no: int = 1, sheets: int = 1, today: date | None = None
) -> StampText:
    """Sheet title block; image_key is the drawing title key in texts.TEXTS."""
    object_name = plan.sheet.object if plan.sheet.object is not None else plan.name
    image = tr(image_key, plan.language, scale=f"{sheet_scale():g}")
    return StampText(plan.sheet, object_name, image, sheet_no, sheets, today, plan.language)
