"""3D wiring scene for the viewer: the flat in 3D and routes by height, from the model.

No new calculations: route plan, boxes and rises are the same as for the wiring sheet and the
estimate (wiring.py), here they are only unfolded by height. Model mm, Z axis up, floor is 0.

- Walls are prisms along the outline pieces (inner face → outer corners, as on the plan),
  from floor to ceiling; a lintel above a door or opening, a sill part under a window. A
  shared partition is one piece with normals into both rooms (normals): the viewer uses them
  to cut away walls between the camera and the room. All pieces of one physical wall (body,
  lintel, sill, the neighbour's pieces behind it) share the same normals. The corner where a
  partition meets an exterior wall belongs to the exterior wall: a cut-down partition leaves
  no notch in it, the perimeter stays solid.
- The floor slab runs under the walls and across door openings, up to the outer outline with
  no holes: otherwise the background shows between rooms and in pockets between walls.
- Route: a rise from the source (panel, box) to the route plane, ceiling or floor (route
  floor), the plan path in that plane, a drop to the point. Matching routes form a bundle,
  cables PITCH_MM apart (lanes on the sheet are wider, that is a drawing device, not real
  space in the flat). Ends are at the wall face, not at the sheet symbol tip.
- Opening heights missing in room.yaml are assumptions: a door is DOOR_TOP_MM, a sill
  WINDOW_SILL_MM, the window top is the ceiling (in 3D a window without a height goes up to
  the ceiling: simpler to draw, no wall above the window; elevations use the typical
  WINDOW_HEIGHT_MM for such a window). They are listed in assumed; a window height from
  room.yaml is used as is.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from typing import Any

import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from floorplan_engine.drawing.plan import convex
from floorplan_engine.drawing.wiring import lanes as lane_offsets
from floorplan_engine.drawing.wiring import offset_path, segments
from floorplan_engine.electrical.anchors import Anchor, board_anchor, point_anchor
from floorplan_engine.electrical.groups import group_colors
from floorplan_engine.electrical.routing import fit_path
from floorplan_engine.electrical.wiring_model import JunctionBox, Wiring
from floorplan_engine.epd.thumbnail import room_kind
from floorplan_engine.model.geometry import (
    DOOR_TOP_MM,
    WINDOW_SILL_MM,
    Contour,
    RoomGeometry,
    Vec,
    WallSegment,
    room_geometries,
)
from floorplan_engine.model.schema import Electrical, Opening, OpeningType, Plan

PITCH_MM = 15.0  # cables of a bundle, apart from each other
WALL_GAP_MM = 20.0  # drop and point symbol off the wall face so they do not sink into it
FLOOR_Z_MM = 20.0  # floor route (in the screed) slightly above the scene floor so it is visible
MIN_AREA_MM2 = 100.0  # wall fragments smaller than this are not drawn
SHARED_SHARE = 0.25  # overlap above this fraction of a piece: a wall shared by two rooms
OPPOSITE = 0.9  # normals of a shared wall face each other (dot product < −0.9)
NO_COLOR = "#888888"  # point without a group


def _xy(v: Vec) -> list[float]:
    return [round(v.x, 1), round(v.y, 1)]


def _xyz(v: Vec, z: float) -> list[float]:
    return [round(v.x, 1), round(v.y, 1), round(z, 1)]


def _rings(geom: BaseGeometry) -> list[list[list[list[float]]]]:
    """Polygons: outer contour and holes, without repeating the first point."""
    polys = getattr(geom, "geoms", [geom])
    out = []
    for p in polys:
        if not isinstance(p, Polygon) or p.area < MIN_AREA_MM2:
            continue
        rings = [p.exterior, *p.interiors]
        out.append([[[round(x, 1), round(y, 1)] for x, y in r.coords[:-1]] for r in rings])
    return out


def _opening_span(op: Opening, ceiling: float) -> list[tuple[float, float]]:
    """Where an opening has wall, by height: a lintel above a door, plus the bottom for a window;
    a window without a height in room.yaml goes up to the ceiling (no lintel above it)."""
    if op.type is OpeningType.WINDOW:
        sill = op.sill if op.sill is not None else WINDOW_SILL_MM
        top = sill + op.height if op.height is not None else ceiling
        spans = [(0.0, sill), (top, ceiling)]
    else:
        spans = [(op.height if op.height is not None else DOOR_TOP_MM, ceiling)]
    return [(lo, hi) for lo, hi in spans if hi - lo > 1.0]


def _assumed_opening(op: Opening) -> bool:
    if op.type is OpeningType.WINDOW:
        return op.sill is None or op.height is None
    return op.height is None


class _Walls:
    """Wall pieces without overlaps: a shared partition piece appears once, with normals of both
    rooms. Overlap is checked on plan and by height at once: the under- and over-window parts of
    one window are not duplicates. Normals belong to the whole physical wall (unified): sill,
    body and lintel of one wall and of the neighbour's wall behind it are cut the same way in
    the viewer, not each piece on its own."""

    def __init__(self, links: Sequence[tuple[str, str]]) -> None:
        self.pieces: list[dict[str, Any]] = []
        self.shapes: list[tuple[BaseGeometry, tuple[float, float]]] = []
        self.links = links  # keys of walls shared by two rooms (_shared)
        self.normals: dict[str, list[list[float]]] = {}  # normals by wall key

    def add(self, key: str, geom: BaseGeometry, z: tuple[float, float], normal: Vec) -> None:
        n = [round(normal.x, 6) + 0.0, round(normal.y, 6) + 0.0]  # no -0.0
        if n not in self.normals.setdefault(key, []):
            self.normals[key].append(n)  # also for a wall fully covered by a neighbour's piece
        geom = shapely.make_valid(geom)
        overlap = [
            shape
            for shape, zz in self.shapes
            if zz[0] < z[1] - 1.0
            and z[0] < zz[1] - 1.0  # not one above the other
            and shape.intersection(geom).area > MIN_AREA_MM2
        ]
        rest = geom.difference(unary_union(overlap)) if overlap else geom
        rings = _rings(rest)
        if not rings:
            return
        self.shapes.append((rest, z))
        self.pieces.append({"key": key, "polys": rings, "z": [z[0], z[1]], "normals": [n]})

    def unified(self) -> list[dict[str, Any]]:
        """Pieces with the normals of the whole physical wall: the room's wall (all its pieces) and
        the
        neighbours' walls shared with it are one wall; every piece gets all their normals. Otherwise
        a sill or lintel that does not overlap the neighbour's piece keeps a single normal and, in a
        cut view, stands at full height above the cut body."""
        parent: dict[str, str] = {}

        def root(k: str) -> str:
            parent.setdefault(k, k)
            while parent[k] != k:
                parent[k] = parent[parent[k]]
                k = parent[k]
            return k

        for a, b in self.links:
            parent[root(a)] = root(b)
        normals: dict[str, list[list[float]]] = {}
        for key, own in self.normals.items():
            group = normals.setdefault(root(key), [])
            group += [n for n in own if n not in group]
        for piece in self.pieces:
            piece["normals"] = list(normals[root(piece["key"])])
        return self.pieces


def _wall_quad(g: RoomGeometry, seg: WallSegment) -> BaseGeometry:
    """Wall piece silhouette: inner face and outer corners (at a 180° joint the quadrilateral can
    self-intersect, so it is made valid)."""
    corners = (seg.start, seg.end, g.outer_end(seg), g.outer_start(seg))
    return shapely.make_valid(Polygon([p.as_tuple() for p in corners]))


def _slab(geoms: Sequence[RoomGeometry]) -> list[list[list[float]]]:
    """Floor slab: the outer ring of each separate part of the flat."""
    rooms = [shapely.make_valid(Polygon([v.as_tuple() for v in g.contour.vertices])) for g in geoms]
    quads = [_wall_quad(g, seg) for g in geoms for seg in g.contour.segments]
    parts = shapely.get_parts(unary_union([*rooms, *quads]))
    return [
        [_xy(Vec(x, y)) for x, y in p.exterior.coords[:-1]] for p in parts if isinstance(p, Polygon)
    ]


def _wall_body(g: RoomGeometry, seg: WallSegment, outline: BaseGeometry) -> BaseGeometry:
    """Wall body as on the plan (drawing.plan.WallPiece.body): a rectangle extended at convex
    corners by the thickness of the neighbouring wall, within the wall silhouette. The corner
    goes to the wall added first, so joints are square, not a mitre seam on the top face."""
    segs = g.contour.segments
    prev, nxt = segs[seg.index - 1], segs[(seg.index + 1) % len(segs)]
    lo = -prev.thickness if convex(prev, seg) else 0.0
    hi = seg.length + (nxt.thickness if convex(seg, nxt) else 0.0)
    out = seg.outward * seg.thickness
    a, b = seg.point_at(lo), seg.point_at(hi)
    rect = Polygon([p.as_tuple() for p in (a, b, b + out, a + out)])
    return shapely.make_valid(rect).intersection(outline)


def _shared(bodies: Sequence[tuple[str, BaseGeometry, Vec]]) -> list[tuple[str, str]]:
    """Walls shared by two rooms: the bodies overlap by a noticeable fraction of a piece and the
    normals face each other (a partition between two rooms faces both ways). A neighbouring wall's
    corner is a joint and does not count, even if it is large for a short piece: otherwise the wall
    gets a foreign normal and the cut hides it when it is the far one."""
    links = []
    for (ka, ga, na), (kb, gb, nb) in itertools.combinations(bodies, 2):
        if na.dot(nb) >= -OPPOSITE:
            continue
        if ga.intersection(gb).area > SHARED_SHARE * min(ga.area, gb.area):
            links.append((ka, kb))
    return links


def _strip(seg: WallSegment, op: Opening) -> Polygon:
    """Opening through the whole wall thickness (with a margin, it is intersected with the wall
    piece later).
    """
    a, b = seg.point_at(op.offset), seg.point_at(op.offset + op.width)
    out = seg.outward * (seg.thickness * 2 + 10)
    return Polygon([p.as_tuple() for p in (a, b, b + out, a + out)])


def _walls(geoms: Sequence[RoomGeometry], ceiling: float) -> list[dict[str, Any]]:
    outline = unary_union([_wall_quad(g, seg) for g in geoms for seg in g.contour.segments])
    bodies = [
        (f"wall:{g.room.id}.{seg.id}", g, seg, _wall_body(g, seg, outline))
        for g in geoms
        for seg in g.contour.segments
    ]
    links = _shared([(key, quad, seg.inward) for key, _, seg, quad in bodies])
    partitions = {key for pair in links for key in pair}
    walls = _Walls(links)
    # Exterior walls first: the corner at a partition joint goes to them (_wall_body), and
    # when a partition is cut down, the perimeter wall stays solid
    for key, g, seg, quad in sorted(bodies, key=lambda b: b[0] in partitions):
        ops = [o for o in g.room.openings if o.wall == seg.id]
        strips = [_strip(seg, o).intersection(quad) for o in ops]
        walls.add(key, quad.difference(unary_union(strips)), (0.0, ceiling), seg.inward)
        for op, strip in zip(ops, strips, strict=True):
            for span in _opening_span(op, ceiling):
                walls.add(key, strip, span, seg.inward)
    return walls.unified()


def _face(a: Anchor) -> Vec:
    """Spot at the wall face (a ceiling point is the point itself)."""
    return a.pos if a.inward is None else a.pos + a.inward * WALL_GAP_MM


def _box_z(b: JunctionBox, ceiling: float) -> float:
    return b.rise_mm if b.route == "floor" else ceiling - b.rise_mm


def _wires(
    wiring: Wiring,
    ends: dict[str, Anchor],
    colors: dict[str, str],
    ceiling: float,
    rooms: dict[str, str],
) -> dict[str, Any]:
    """Routes in 3D: rise from the source, plan path in the ceiling or floor plane, drop.
    A line's room is the room of its target (point or box): the viewer filters by it."""
    paths = [list(r.path) for r in wiring.runs]
    for route in ("ceiling", "floor"):
        idx = [k for k, r in enumerate(wiring.runs) if r.route == route]
        segs = segments([wiring.runs[k].path for k in idx])
        offsets = lane_offsets(segs, PITCH_MM, float("inf"))
        for j, k in enumerate(idx):
            run = wiring.runs[k].path
            shifts = [offsets.get((j, i), 0.0) for i in range(len(run) - 1)]
            paths[k] = offset_path(run, shifts)
    out: dict[str, Any] = {}
    for r, path in zip(wiring.runs, paths, strict=True):
        start, end = _face(ends[r.source]), _face(ends[r.target])
        plan = fit_path(path, start, end) if len(path) >= 2 else [start, end]
        floor = r.route == "floor"
        plane = FLOOR_Z_MM if floor else ceiling
        z0 = r.rise_start_mm if floor else ceiling - r.rise_start_mm
        z1 = r.rise_end_mm if floor else ceiling - r.rise_end_mm
        pts = [_xyz(plan[0], max(z0, 0.0))]
        pts += [_xyz(p, plane) for p in plan]
        pts.append(_xyz(plan[-1], max(z1, 0.0)))
        clean = [p for k, p in enumerate(pts) if k == 0 or p != pts[k - 1]]
        out[r.id] = {
            "group": r.group,
            "color": colors.get(r.group, NO_COLOR),
            "route": r.route,
            "from": r.source,
            "to": r.target,
            "room": rooms.get(r.target),
            "pts": clean,
        }
    return out


def build_scene(
    plan: Plan, contours: dict[str, Contour], elec: Electrical, wiring: Wiring
) -> dict[str, Any]:
    """Scene for the `scene` key of the .epd wiring page. Call at the sheet scale
    (scale.drawing_scale): route ends are the same nodes as on the drawing."""
    ceiling = plan.ceiling_height
    geoms = room_geometries(plan, contours)
    by_room = {g.room.id: g for g in geoms}
    colors = {g: f"#{c:06x}" for g, c in group_colors(elec).items()}
    anchors = {p.id: point_anchor(p, by_room) for p in elec.points}
    ends: dict[str, Anchor] = {**anchors, **{b.id: b.anchor for b in wiring.boxes}}
    if elec.board is not None:
        ends["board"] = board_anchor(elec.board, by_room)
    if elec.media is not None:
        ends["media"] = board_anchor(elec.media, by_room)

    def inward(a: Anchor) -> list[float] | None:
        return None if a.inward is None else [round(a.inward.x, 6), round(a.inward.y, 6)]

    points = {}
    for p in elec.points:
        a = anchors[p.id]
        z = ceiling if p.ceiling is not None else float(p.height or 0.0)
        points[p.id] = {
            "pos": _xyz(_face(a), z),
            "inward": inward(a),
            "type": p.type.value,
            "room": p.room,
            "group": p.group,
            "color": colors.get(p.group or "", NO_COLOR),
        }
    boxes = {
        b.id: {
            "pos": _xyz(_face(b.anchor), _box_z(b, ceiling)),
            "inward": inward(b.anchor),
            "label": b.label,
            "room": b.room,
            "group": b.group,
        }
        for b in wiring.boxes
    }
    scene: dict[str, Any] = {
        "ceiling": ceiling,
        "assumed": {
            "ceiling": "ceiling_height" not in plan.model_fields_set,
            "openings": sorted(o.id for r in plan.rooms for o in r.openings if _assumed_opening(o)),
        },
        "floors": [
            {
                "key": f"room:{g.room.id}",
                "kind": room_kind(g.room.name, g.room.wet),
                "rings": [[_xy(v) for v in g.contour.vertices]],
            }
            for g in geoms
        ],
        "slab": _slab(geoms),
        "walls": _walls(geoms, ceiling),
        "wires": _wires(
            wiring,
            ends,
            colors,
            ceiling,
            {**{p.id: p.room for p in elec.points}, **{b.id: b.room for b in wiring.boxes}},
        ),
        "points": points,
        "boxes": boxes,
    }
    if elec.board is not None:
        a = ends["board"]
        scene["board"] = {"pos": _xyz(_face(a), elec.board.height), "inward": inward(a)}
    if elec.media is not None:
        a = ends["media"]
        scene["media"] = {"pos": _xyz(_face(a), elec.media.height), "inward": inward(a)}
    return scene
