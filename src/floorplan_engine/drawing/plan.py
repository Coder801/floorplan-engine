"""Plan drawing: walls, openings, dimensions, room names and areas, wall codes.

The walls of all rooms are first merged into one silhouette: a partition shared by two rooms
is drawn once, and where a partition meets an exterior wall there are no inner lines.
The silhouette boundary is drawn as segments by coordinates, openings are gaps with reveals.
Hatching: load-bearing (monolithic) walls are dense, partitions are sparse. Where a
load-bearing wall meets a partition, a material boundary line remains.
Every wall gets its code ("2.C", model/wall_names.py) inside the room along the wall, on a spot
free of dimensions, labels and door swings: the same code as on the elevations and in the viewer.
Labels (room names, sills, dimension numbers, wall codes) do not sit on each other or on the
linework; one with no free spot nearby goes on a 45° leader (`draw_plan`, `callouts`).
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

from floorplan_engine.drawing.callouts import (
    PAD_MM,
    Board,
    Candidate,
    Kind,
    Label,
    Obstacle,
    Spot,
    readable_angle,
    reading,
)
from floorplan_engine.drawing.dimensions import (
    Dim,
    dim_linework,
    dim_spots,
    draw_dimension,
    layout_dimensions,
    wall_gaps,
)
from floorplan_engine.drawing.fields import add_area_field
from floorplan_engine.drawing.ids import tagged
from floorplan_engine.drawing.layers import (
    A_AREA,
    A_DOOR,
    A_TEXT,
    A_WALL,
    A_WIND,
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

__all__ = ["readable_angle"]  # plan texts and their tests take it from here
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
CODE_INSETS_MM = (3.0, 13.0, 18.0, 23.0)  # wall code from the inner face, sheet mm (dims at 8)
CODE_ALONG = (0.5, 0.35, 0.65, 0.2, 0.8, 0.1, 0.9)  # spots along the wall, middle first
SILL_DEPTHS = (1.2, 2.4, 3.6)  # sill label centre from the inner face, in text heights
SILL_ALONG_MM = (0.0, 2.0, -2.0, 4.0, -4.0, 6.0, -6.0)  # and along the window from its middle
SWING_SAMPLES = 12  # points on a door arc for label checks
ROOM_LABEL_STEP_MM = 2.0  # search step around the room label point, over the floor, sheet mm
ROOM_LABEL_NEAR = 25  # spots nearest to the label point for a label wider than its floor
ROOM_LINE_GAP = 0.8  # room name above and area below the label point, in name heights
FRAME_MARGIN_MM = 3.0  # a moved label stays this close to the drawing extent
WALL_INSET_MM = 0.05  # walls as obstacles are this much thinner on each side, sheet mm
_ALL = frozenset({Kind.LINE, Kind.WALL, Kind.LABEL, Kind.LEADER, Kind.ZONE})
_NO_ZONES = frozenset({Kind.LINE, Kind.WALL, Kind.LABEL, Kind.LEADER})
_TEXTS = frozenset({Kind.LABEL, Kind.LEADER})


def _xy(v: Vec) -> tuple[float, float]:
    return v.as_tuple()


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
    return any(b >= seg.length - 1e-6 for _, b in wall_gaps(room, seg.id))


def _open_at_start(room: Room, seg: WallSegment) -> bool:
    """The wall's opening starts at the wall start."""
    return any(a <= 1e-6 for a, _ in wall_gaps(room, seg.id))


def wall_pieces(g: RoomGeometry) -> list[WallPiece]:
    out: list[WallPiece] = []
    segs = g.contour.segments
    for seg in segs:
        prev, nxt = segs[seg.index - 1], segs[(seg.index + 1) % len(segs)]
        pieces = _solid_intervals(0.0, seg.length, wall_gaps(g.room, seg.id))
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


def draw_openings(msp: Modelspace, g: RoomGeometry) -> None:
    """Door leaves and swings, windows; sill labels are placed by `draw_plan` (`_draw_sill`)."""
    for op in g.room.openings:
        with tagged(msp, "opening", op.id):
            seg = g.contour.segment(op.wall)
            if op.type is OpeningType.DOOR:
                _draw_door(msp, g, seg, op)
            elif op.type is OpeningType.WINDOW:
                _draw_window(msp, seg, op)


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


def _draw_window(msp: Modelspace, seg: WallSegment, op: Opening) -> None:
    layer = {"layer": A_WIND.name}
    a, b = op.offset, op.offset + op.width
    for frac in (0.0, 0.5, 1.0):
        shift = seg.outward * (seg.thickness * frac)
        msp.add_line(_xy(seg.point_at(a) + shift), _xy(seg.point_at(b) + shift), dxfattribs=layer)


def _door_arc(g: RoomGeometry, op: Opening) -> shapely.LineString:
    """Leaf and swing arc of a door as one line (labels do not sit on them)."""
    hinge, closed, way = door_leaf(g, g.contour.segment(op.wall), op)
    radial = (closed - hinge) * (1 / op.width)
    pts: list[Vec] = []
    for k in range(SWING_SAMPLES + 1):
        t = math.pi / 2 * k / SWING_SAMPLES
        pts.append(hinge + (way * math.cos(t) + radial * math.sin(t)) * op.width)
    return shapely.LineString([_xy(hinge)] + [_xy(p) for p in pts])


def _opening_gap(g: RoomGeometry, op: Opening) -> Polygon:
    """The opening in the wall body, from the inner face to the outer one."""
    seg = g.contour.segment(op.wall)
    a, b = op.offset, op.offset + op.width
    out = seg.outward * seg.thickness
    corners = [seg.point_at(a), seg.point_at(b), seg.point_at(b) + out, seg.point_at(a) + out]
    return Polygon([_xy(c) for c in corners])


def _draw_sill(
    msp: Modelspace, board: Board, g: RoomGeometry, op: Opening, language: Language
) -> None:
    """Sill label of a window: inside the room by the middle of the window, else beside it or
    deeper in the room, else on a 45° leader from the window. On the plan labels layer: the
    other sheets take windows, but a sill is not for them."""
    seg = g.contour.segment(op.wall)
    text = tr("sill", language, sill=f"{op.sill:g}")
    d, up = reading(seg.direction)
    anchor = seg.point_at(op.offset + op.width / 2)
    h = sheet(TEXT_SMALL_MM)
    width = sheet(text_width(text, TEXT_SMALL_MM))
    label = Label(width, h, d, up, anchor, f"opening:{op.id}")
    spots = [
        Candidate(anchor + seg.inward * (h * depth) + d * sheet(along))
        for depth in SILL_DEPTHS
        for along in SILL_ALONG_MM
    ]
    room = Polygon([_xy(v) for v in g.contour.vertices])
    spot = board.place(label, spots, within=room, prefer=room)
    add_text(msp, text, spot.centre, TEXT_SMALL_MM, A_TEXT.name, seg.angle_deg)
    _draw_leader(msp, spot, A_TEXT.name)


def _draw_leader(msp: Modelspace, spot: Spot, layer: str) -> None:
    for a, b in itertools.pairwise(spot.leader):
        msp.add_line(_xy(a), _xy(b), dxfattribs={"layer": layer})


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


def _room_label_box(floor: Floor, at: Vec) -> Polygon:
    """Spot of the floor name and area (draw_room_label) at point at."""
    w = max(text_width(floor.name, TEXT_ROOM_MM), text_width("00,00 м²", TEXT_DIM_MM))
    # Two lines ROOM_LINE_GAP above and below the point, with the label margin
    hw = sheet(w / 2 + PAD_MM)
    hh = sheet(TEXT_ROOM_MM * ROOM_LINE_GAP + TEXT_ROOM_MM / 2 + PAD_MM)
    return Polygon(
        [
            (at.x - hw, at.y - hh),
            (at.x + hw, at.y - hh),
            (at.x + hw, at.y + hh),
            (at.x - hw, at.y + hh),
        ]
    )


def _room_label_spots(floor: Floor) -> tuple[list[Vec], list[tuple[Vec, Polygon]]]:
    """Points for the floor name and area, nearest to the label point first, over the floor;
    and those where the label stays inside the floor, with its box (none if it is wider)."""
    at = label_point(floor.vertices)
    room = Polygon([_xy(v) for v in floor.vertices])
    step = sheet(ROOM_LABEL_STEP_MM)
    x0, y0, x1, y1 = room.bounds
    grid = sorted(
        (
            (i, j)
            for i in range(math.floor((x0 - at.x) / step), math.ceil((x1 - at.x) / step) + 1)
            for j in range(math.floor((y0 - at.y) / step), math.ceil((y1 - at.y) / step) + 1)
        ),
        key=lambda ij: (ij[0] ** 2 + ij[1] ** 2, ij),
    )
    spots = [at + Vec(i * step, j * step) for i, j in grid]
    inside = [(c, box) for c in spots for box in (_room_label_box(floor, c),) if room.contains(box)]
    return spots, inside


def _place_room_label(board: Board, floor: Floor) -> Vec:
    """Point of the floor name and area: the label point (`label_point`) or the nearest point
    of the floor where the label stays inside the floor off linework, labels and door swings
    (then off linework and labels only); with none free, the point where it touches the fewest
    labels and leaders, then lines: inside the floor, or near the label point if the label is
    wider than its floor."""
    spots, inside = _room_label_spots(floor)
    best = next(
        (
            (c, box)
            for kinds in (_ALL, _NO_ZONES)
            for c, box in inside
            if not board.blocked(box, kinds)
        ),
        None,
    )
    if best is None:
        options = inside or [(c, _room_label_box(floor, c)) for c in spots[:ROOM_LABEL_NEAR]]
        best = min(
            options,
            key=lambda o: 100 * board.count(o[1], _TEXTS) + board.count(o[1], _NO_ZONES),
        )
    board.add(Obstacle(best[1], Kind.LABEL, f"room:{floor.key}"))
    return best[0]


def _draw_room_label_at(msp: Modelspace, board: Board, floor: Floor, area: RoomArea) -> None:
    kind, _, object_id = floor.key.partition(":")
    at = _place_room_label(board, floor)
    with tagged(msp, kind, object_id):
        draw_room_label(msp, floor, area, at)


def draw_room_label(msp: Modelspace, floor: Floor, area: RoomArea, at: Vec | None = None) -> None:
    """Floor name and area at point at (the label point by default); the area is an AutoCAD
    field from the area outline."""
    doc = msp.doc
    assert doc is not None
    if at is None:
        at = label_point(floor.vertices)
    gap = sheet(TEXT_ROOM_MM) * ROOM_LINE_GAP
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

    Labels go in two passes. First every wall gets its dimension rows (`layout_dimensions`):
    they keep off walls and room names at their label points (door swings do not count: in a
    hallway with three doors the rows would otherwise have nowhere to go). Then, with all
    linework known (walls, openings, door leaves, every dimension and extension line), labels
    are placed one by one, each off the linework and the labels before it, the most tied first:
    room names wider than their floor (by the label point), dimension numbers (larger rooms
    first), sills, the other room names (anywhere in their floor), wall codes (the smallest,
    they move most easily). Dimension numbers, sills and codes with no
    free spot nearby go on a 45° leader (`callouts`).

    Returns the area outlines by floor key (`zones.plan_floors`: a room, or each zone of an
    open-plan room), in schedule order: the room schedule fields refer to them.
    """
    geoms = room_geometries(plan, contours)
    floors = plan_floors(plan, contours)
    areas: dict[str, RoomArea] = {}
    draw_walls(msp, geoms)
    for g in geoms:
        draw_openings(msp, g)
    for f in floors:
        kind, _, object_id = f.key.partition(":")
        with tagged(msp, kind, object_id):
            areas[f.key] = draw_area_contour(msp, f)
    pieces = [p for g in geoms for p in wall_pieces(g)]
    taken: list[BaseGeometry] = [_room_label_box(f, label_point(f.vertices)) for f in floors]
    taken += [p.polygon for p in pieces]
    dims = layout_dimensions(geoms, taken)
    board = _board(geoms, pieces, dims)
    # A name wider than its floor crosses lines anyway: it goes first, by its label point, so
    # that dimension numbers keep off it
    wide = {f.key for f in floors if not _room_label_spots(f)[1]}
    for f in floors:
        if f.key in wide:
            _draw_room_label_at(msp, board, f, areas[f.key])
    for dim in dims:
        spot = board.place(dim.label(), dim_spots(dim))
        with tagged(msp, "dimension", dim.key):
            draw_dimension(msp, dim, spot)
    for g in geoms:
        for op in g.room.openings:
            if op.type is OpeningType.WINDOW and op.sill is not None:
                with tagged(msp, "opening", op.id):
                    _draw_sill(msp, board, g, op, plan.language)
    for f in floors:
        if f.key not in wide:
            _draw_room_label_at(msp, board, f, areas[f.key])
    codes = wall_codes(plan, contours)
    for g in geoms:
        draw_wall_codes(msp, g, codes, board)
    return areas


def _board(
    geoms: Sequence[RoomGeometry], pieces: Sequence[WallPiece], dims: Sequence[Dim]
) -> Board:
    """Obstacles for plan labels: walls, openings in them, door leaves and arcs, every dimension
    line, extension line and tick; door swings as zones (only wall codes and room names keep off
    them). The frame is the extent of all that plus a margin: a moved label stays inside, so the
    view does not grow."""
    # Walls a hair thinner: a leader starting at a wall face may run along the next wall's face
    inset = -sheet(WALL_INSET_MM)
    fixed = [
        Obstacle(p.polygon.buffer(inset), Kind.WALL, f"wall:{p.tag}", f"wall:{p.tag}")
        for p in pieces
    ]
    for g in geoms:
        for op in g.room.openings:
            owner = f"opening:{op.id}"
            gap = _opening_gap(g, op).buffer(inset)
            fixed.append(Obstacle(gap, Kind.WALL, owner, owner))
            if op.type is OpeningType.DOOR:
                fixed.append(Obstacle(_door_arc(g, op), Kind.LINE, owner, owner))
                fixed.append(Obstacle(door_swing(g, op), Kind.ZONE, owner, owner))
    for dim in dims:
        fixed += dim_linework(dim)
    x0, y0, x1, y1 = shapely.unary_union([o.geom for o in fixed]).bounds
    frame = shapely.box(x0, y0, x1, y1).buffer(sheet(FRAME_MARGIN_MM), join_style="mitre")
    return Board(fixed, frame)


def door_swing(g: RoomGeometry, op: Opening) -> BaseGeometry:
    """Square the door leaf sweeps (holds its arc), in whichever room it opens into."""
    hinge, edge, way = door_leaf(g, g.contour.segment(op.wall), op)
    reach = way * op.width
    return Polygon([_xy(hinge), _xy(edge), _xy(edge + reach), _xy(hinge + reach)])


def draw_wall_codes(
    msp: Modelspace,
    g: RoomGeometry,
    codes: dict[tuple[str, str], str],
    board: Board,
) -> None:
    """Code of every wall inside the room along it: the first spot (middle first, close to the
    face first) that is inside the room and off linework, labels and door swings; else on a 45°
    leader from the middle of the wall, preferably inside the room; with no spot at all, the
    middle by the face. Placed codes become obstacles for the next labels."""
    room = Polygon([_xy(v) for v in g.contour.vertices])
    for seg in g.contour.segments:
        code = codes[(g.room.id, seg.id)]
        d, up = reading(seg.direction)
        width = sheet(text_width(code, TEXT_DIM_MM))
        anchor = seg.point_at(seg.length / 2)
        label = Label(width, sheet(TEXT_DIM_MM), d, up, anchor, f"wall:{g.room.id}.{seg.id}")
        spots = [
            Candidate(seg.point_at(seg.length * k) + seg.inward * sheet(inset))
            for inset in CODE_INSETS_MM
            for k in CODE_ALONG
        ]
        spot = board.place(label, spots, zones=True, within=room, prefer=room)
        with tagged(msp, "wall", f"{g.room.id}.{seg.id}"):
            angle = math.degrees(math.atan2(d.y, d.x))
            add_text(msp, code, spot.centre, TEXT_DIM_MM, A_TEXT.name, angle)
            _draw_leader(msp, spot, A_TEXT.name)


def plan_stamp(
    plan: Plan, image_key: str, sheet_no: int = 1, sheets: int = 1, today: date | None = None
) -> StampText:
    """Sheet title block; image_key is the drawing title key in texts.TEXTS."""
    object_name = plan.sheet.object if plan.sheet.object is not None else plan.name
    image = tr(image_key, plan.language, scale=f"{sheet_scale():g}")
    return StampText(plan.sheet, object_name, image, sheet_no, sheets, today, plan.language)
