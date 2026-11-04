"""Routing context of a plumbing network: obstacles, grids, search fields, approaches."""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from floorplan_engine.electrical.routing import (
    CLEARANCE,
    STEP,
    Grid,
    opening_strip,
)
from floorplan_engine.model.geometry import (
    RoomGeometry,
    Vec,
    WallSegment,
    point_in_polygon,
)
from floorplan_engine.model.plumbing import (
    Obstacle,
    Plumbing,
    Riser,
)
from floorplan_engine.model.schema import OpeningType, Plan, Room
from floorplan_engine.plumbing.network_model import TEXT, Network, SewerError, weak_spot
from floorplan_engine.plumbing.rules import (
    ALONG_COST,
    DOOR_COST,
    FIXTURE_NAMES,
    LIVING_NAME,
    NEAR_WALL_MM,
    PARTITION_COST,
    PARTITION_MAX,
    REACH,
    SCREED_COVER,
    SCREED_MM,
    SERVICE_NAME,
    TAG_HIDDEN,
    TAG_NEAR,
    TAG_OPEN,
    TAG_WALL,
    TURN_COST_MM,
    UNDER_COST,
    WALL_BAND_MM,
    Kind,
)

# --- Geometry --------------------------------------------------------------------


def obstacle_polygon(ob: Obstacle, g: RoomGeometry) -> Polygon:
    """Obstacle on the plan, model mm."""
    if ob.rect is not None:
        ox, oy = g.room.origin
        x0, y0, x1, y1 = ob.rect
        return Polygon(
            [(ox + x0, oy + y0), (ox + x1, oy + y0), (ox + x1, oy + y1), (ox + x0, oy + y1)]
        )
    assert ob.wall is not None and ob.offset is not None
    assert ob.width is not None and ob.depth is not None
    seg = g.contour.segment(ob.wall)
    a, b = seg.point_at(ob.offset), seg.point_at(ob.offset + ob.width)
    d = seg.inward * ob.depth
    return Polygon([a.as_tuple(), b.as_tuple(), (b + d).as_tuple(), (a + d).as_tuple()])


def door_strips(geoms: Sequence[RoomGeometry]) -> list[Polygon]:
    """Door openings through the whole wall thickness (the neighbour has an opening of type: opening
    at the same spot, it lands on the same band). An arch without a door is not a door: pipes pass
    through it freely."""
    return [
        opening_strip(g, op) for g in geoms for op in g.room.openings if op.type is OpeningType.DOOR
    ]


def partition_strips(
    geoms: Sequence[RoomGeometry], doors: Sequence[Polygon] = (), inner: bool = False
) -> list[Polygon]:
    """Partitions between rooms of the flat (non-load-bearing, no thicker than PARTITION_MAX, or
    explicitly `partition: true` in room.yaml); inner=True means walls inside a room with
    `partition: true` (a plasterboard wall in a bathroom: the same room on both sides, pipes go on
    the floor under it, network.Network.under): a band through the whole wall thickness, without
    windows (a glass partition is not a pass) and without doors (passing them costs more,
    door_strips)."""
    blocked = shapely.unary_union(list(doors)).buffer(1.0) if doors else None
    out: list[Polygon] = []
    for g in geoms:
        for seg in g.contour.segments:
            if seg.bearing or (seg.thickness > PARTITION_MAX and not seg.partition):
                continue
            probe = seg.point_at(seg.length / 2) + seg.outward * (seg.thickness + 50.0)
            beyond = [o for o in geoms if point_in_polygon(probe, o.contour.vertices)]
            if not beyond:
                continue
            within = all(o is g for o in beyond)
            if within != inner or (within and not seg.partition):
                continue
            out_v = seg.outward * seg.thickness
            strip: BaseGeometry = Polygon(
                [
                    seg.start.as_tuple(),
                    seg.end.as_tuple(),
                    (seg.end + out_v).as_tuple(),
                    (seg.start + out_v).as_tuple(),
                ]
            )
            for op in g.room.openings:
                if op.wall == seg.id and op.type is OpeningType.WINDOW:
                    strip = strip.difference(opening_strip(g, op))
            if blocked is not None:
                strip = strip.difference(blocked)
            parts = list(strip.geoms) if hasattr(strip, "geoms") else [strip]
            out += [p for p in parts if isinstance(p, Polygon) and p.area > 1.0]
    # A shared wall is described in both rooms, so the bands match: one partition, otherwise
    # each hole in it would be counted twice (Network.holes)
    merged = shapely.unary_union(out) if out else None
    if merged is None:
        return []
    parts = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
    return [p for p in parts if isinstance(p, Polygon) and p.area > 1.0]


def riser_center(r: Riser, geoms: dict[str, RoomGeometry]) -> Vec:
    ox, oy = geoms[r.room].room.origin
    return Vec(ox + r.at[0], oy + r.at[1])


def nearest_wall(g: RoomGeometry, p: Vec) -> tuple[WallSegment, float]:
    """The room wall nearest to the point and the offset of the projection onto it (within it)."""
    best: tuple[float, WallSegment, float] | None = None
    for seg in g.contour.segments:
        t = min(max((p - seg.start).dot(seg.direction), 0.0), seg.length)
        d = (seg.point_at(t) - p).length()
        if best is None or d < best[0]:
            best = (d, seg, t)
    assert best is not None
    return best[1], best[2]


@dataclass(frozen=True)
class SearchField:
    """Grid search from one cell: cost to each cell and the path."""

    grid: Grid
    prev: dict[int, int]
    dist: dict[int, float]
    ndirs: int = 4  # 4 for 90° turns (water), 8 for 45° bends (sewer)

    offset: float = 0.0  # extra cost on the whole cost: fallback search without pruning

    @classmethod
    def from_cell(
        cls,
        grid: Grid,
        cell: int,
        ndirs: int = 4,
        prune: Prune | None = None,
        start_len: float = 0.0,
        offset: float = 0.0,
    ) -> SearchField:
        if ndirs == 8:
            prev, dist = grid.search45(cell, TURN_COST_MM, prune, start_len)
        else:
            prev, dist = grid.search(cell)
        return cls(grid, prev, dist, ndirs, offset)

    def cost(self, cell: int) -> float:
        n = self.ndirs
        return self.offset + min(
            (self.dist[s] for s in range(cell * n, cell * n + n) if s in self.dist),
            default=math.inf,
        )

    def path(self, cell: int) -> list[Vec]:
        return self.grid.path(self.prev, self.dist, cell, self.ndirs)


@dataclass(frozen=True)
class Approach:
    """Approach to a node on a wall: the grid cell and the tail to the node (on the floor to the
    wall, then in the wall along it). along is how much runs in the wall."""

    cell: int
    tail: tuple[Vec, ...]  # from the cell centre to the node
    along: float


def _approaches(grid: Grid, seg: WallSegment, offset: float) -> list[Approach]:
    """Free cells by wall seg (no farther than REACH from its face, facing it), from the ones
    nearest to the wall spot to the farthest."""
    out: list[tuple[float, Approach]] = []
    node = seg.point_at(offset)
    for k, free in enumerate(grid.free):
        if not free:
            continue
        c = grid.center(k)
        rel = c - seg.start
        t = rel.dot(seg.direction)
        depth = rel.dot(seg.inward)
        if not (0.0 <= t <= seg.length) or not (0.0 < depth <= REACH):
            continue
        foot = seg.point_at(t)
        along = abs(t - offset)
        tail = (c, foot, node) if along > 1.0 else (c, node)
        out.append((along * ALONG_COST + depth, Approach(k, tail, along)))
    out.sort(key=lambda x: x[0])
    return [a for _, a in out]


def _box_approaches(grid: Grid, poly: Polygon, node: Vec) -> list[Approach]:
    """Approaches to a node inside a box (installation frame): free cells by the box on any side;
    from the cell to the box face and inside it to the node (in the box, as in a wall)."""
    out: list[tuple[float, Approach]] = []
    edge = poly.exterior
    near = poly.buffer(REACH)
    for k, free in enumerate(grid.free):
        if not free:
            continue
        c = grid.center(k)
        if not near.contains(shapely.Point(c.as_tuple())):
            continue
        hit = edge.interpolate(edge.project(shapely.Point(c.as_tuple())))
        foot = Vec(hit.x, hit.y)
        inside = [foot, Vec(foot.x, node.y), node] if abs(foot.x - node.x) > 1.0 else [foot, node]
        along = sum((b - a).length() for a, b in itertools.pairwise(inside))
        out.append((along * ALONG_COST + (foot - c).length(), Approach(k, (c, *inside), along)))
    out.sort(key=lambda x: x[0])
    return [a for _, a in out]


def point_approach(grid: Grid, p: Vec, cell: int | None = None) -> Approach:
    """Approach to a point off the wall (riser): a free cell (the nearest by default) and a 90°
    bend."""
    cell = grid.nearest_free(p) if cell is None else cell
    c = grid.center(cell)
    if abs(c.x - p.x) < 1e-6 or abs(c.y - p.y) < 1e-6:
        return Approach(cell, (c, p), 0.0)
    return Approach(cell, (c, Vec(c.x, p.y), p), 0.0)


def best_approach(field_: SearchField, options: Sequence[Approach]) -> Approach | None:
    """Approach with the lowest cost: grid path plus a penalty for metres in the wall."""
    best: tuple[float, Approach] | None = None
    for a in options:
        c = field_.cost(a.cell)
        if math.isinf(c):
            continue
        total = c + a.along * ALONG_COST
        if best is None or total < best[0]:
            best = (total, a)
    return best[1] if best is not None else None


# --- Routing context -------------------------------------------------------------


@dataclass
class Ctx:
    plan: Plan
    plumbing: Plumbing
    geoms: dict[str, RoomGeometry]
    grid: Grid
    net: Network
    boxes: dict[str, bool] = field(default_factory=dict)  # box obstacle: pipes inside
    counter: dict[str, int] = field(default_factory=dict)
    sewer_grids: tuple[Grid, ...] = ()  # sewer grids: normal, through hidden zones, by walls
    ndirs: int = 4  # search: 8 means sewer with 45° bends
    boxes_open: bool = False  # boxes and installation frames are passable (sewer)
    prune: Prune | None = None  # height pruning independent of length (Ø110)

    def field(self, cell: int, prune: bool = True) -> SearchField:
        return SearchField.from_cell(self.grid, cell, self.ndirs, self.prune if prune else None)

    def name(self, fixture: str) -> dict[str, str]:
        """Fixture in words in both languages: "Мийка (Кухня)"."""
        fx = next((f for f in self.plumbing.fixtures if f.id == fixture), None)
        if fx is None:
            return {"ru": fixture, "uk": fixture}
        room = self.geoms[fx.room].room.name
        return {lang: f"{FIXTURE_NAMES[fx.type][lang]} ({room})" for lang in ("ru", "uk")}

    def unreachable(self, fixture: str, kind: Kind) -> None:
        if kind == "sewer":
            self.net.weak.append(
                weak_spot("error", "unreachable_sewer", fixture, f=self.name(fixture))
            )
            self.net.sewer_errors.append(SewerError(fixture, "unreachable", None))
            return
        self.net.weak.append(
            weak_spot("error", "unreachable", fixture, f=self.name(fixture), k=TEXT[f"kind_{kind}"])
        )

    def new_id(self, kind: str) -> str:
        self.counter[kind] = self.counter.get(kind, 0) + 1
        return f"{kind}_{self.counter[kind]}"

    def wall_approaches(self, room: str, wall: str, offset: float) -> list[Approach]:
        """Approaches to a wall spot; a fixture on a box or installation frame goes through the
        box.
        """
        seg = self.geoms[room].contour.segment(wall)
        node = seg.point_at(offset)
        for oid, poly in self.net.obstacles.items():
            if self.boxes_open:
                break
            if self.boxes.get(oid) and poly.buffer(1.0).contains(shapely.Point(node.as_tuple())):
                return _box_approaches(self.grid, poly, node)
        return _approaches(self.grid, seg, offset)


def base_grid(free: BaseGeometry, net: Network) -> Grid:
    """Route grid: through a partition is allowed but costly (a hole at the floor); under a
    plasterboard wall inside a room almost free; through a door opening almost never (threshold,
    leaf): only if the fixture is otherwise unreachable."""
    grid = Grid.of(free)
    grid.penalty = {}
    for strips, cost, reach in (
        (net.under, UNDER_COST, CLEARANCE),
        (net.partitions, PARTITION_COST, CLEARANCE),
        (net.doors, DOOR_COST, STEP / 2),
    ):
        if not strips:
            continue
        zone = shapely.unary_union(strips).buffer(reach)
        shapely.prepare(zone)
        for k, ok in enumerate(grid.free):
            if ok and zone.contains(shapely.Point(grid.center(k).as_tuple())):
                grid.penalty[k] = cost
    return grid


def is_living(room: Room) -> bool:
    """Living room: sewer through it is a weak spot, through its threshold is not allowed."""
    return (
        bool(LIVING_NAME.search(room.name)) and not SERVICE_NAME.search(room.name) and not room.wet
    )


def sewer_grid(
    geoms: Sequence[RoomGeometry], net: Network, costs: tuple[float, float, float, float]
) -> Grid:
    """Sewer grid: without door openings and openings of living rooms (thresholds are forbidden, no
    exceptions); the step cost is a per-cell multiplier (Grid.mult, costs: hidden zone (box,
    installation frame, under bath and tray); by the wall up to WALL_BAND_MM; up to
    NEAR_WALL_MM; farther) and the cell kind (Grid.tag) for height pruning in the search
    (height_prune)."""
    assert net.rooms is not None
    blocked: list[BaseGeometry] = list(net.doors)
    blocked += [
        opening_strip(g, op)
        for g in geoms
        for op in g.room.openings
        if op.type is not OpeningType.WINDOW and is_living(g.room)
    ]
    area: BaseGeometry = net.rooms
    if blocked:
        area = area.difference(shapely.unary_union(blocked).buffer(1.0))
    if net.partitions or net.under:
        area = shapely.unary_union([area, *net.partitions, *net.under])
    solid = [poly for oid, poly in net.obstacles.items() if oid not in net.hidden]
    if solid:
        area = area.difference(shapely.unary_union(solid))
    grid = base_grid(shapely.make_valid(area), net)
    hidden = shapely.unary_union([poly for poly, _ in net.hidden.values()]) if net.hidden else None
    if hidden is not None:
        shapely.prepare(hidden)
    walls = net.rooms
    if net.obstacles:
        walls = walls.difference(shapely.unary_union(list(net.obstacles.values())))
    edge = walls.boundary  # along walls, bath, box
    shapely.prepare(edge)
    grid.mult = [costs[TAG_OPEN]] * len(grid.free)
    grid.tag = [TAG_OPEN] * len(grid.free)
    for k, ok in enumerate(grid.free):
        if not ok:
            continue
        p = shapely.Point(grid.center(k).as_tuple())
        if hidden is not None and hidden.contains(p):
            tag = TAG_HIDDEN
        else:
            far = edge.distance(p)  # exactly on the band edge (+1 mm): by the wall
            tag = TAG_WALL if far <= WALL_BAND_MM + 1.0 else TAG_NEAR
            if far > NEAR_WALL_MM + 1.0:
                tag = TAG_OPEN
        grid.tag[k], grid.mult[k] = tag, costs[tag]
    return grid


Prune = Callable[[int, float], bool]


def height_prune(
    grid: Grid, z0: float, slope: float, d: int, lower: Vec | None = None
) -> Prune | None:
    """Sewer search pruning (routing spec, item 2): a cell outside a hidden zone and the wall band
    is
    unavailable if the pipe bottom there (z0 + length · slope) plus Ø and the SCREED_COVER layer is
    already above the screed. Length is the path from the tee (search from the riser); lower means
    a search from the fixture: the length is unknown, so a lower bound is used, the straight
    distance from this point (the riser); Ø110 never fits in the screed."""
    tags = grid.tag
    if tags is None:
        return None
    limit = SCREED_MM - d - SCREED_COVER

    def prune(cell: int, length: float) -> bool:
        if tags[cell] in (TAG_HIDDEN, TAG_WALL):
            return False
        if lower is not None:
            length = (grid.center(cell) - lower).length()
        return z0 + length * slope > limit + 0.5

    return prune
