"""What every part of the wiring shares: the context of a build (plan, connection points, panel,
routers from it), a link (a line of the topology before routing), the point kinds and the cable
allowances, and the small rules used by more than one part.

Line length = plan path + vertical from the connection point to the ceiling (or floor) at
both ends + tails: at the panel the cable runs down to the floor (the panel height, Context.tail),
at other connections END_ALLOWANCE. A chain of lights leaves a LIGHT_LOOP loop at each ceiling
light (light_chains.py, wiring_links.py).

A cable between two points is on the ceiling wherever a ceiling point is at either end
(between_plane); from a point to the route plane it rises to the ceiling or drops to the floor
(rise, rise_from). Two mechanisms of one frame (FRAME_SPAN along the wall at one height,
same_frame) are joined by a jumper that stays in the wall. With one_feed (decision 2026-11-13)
one cable of a group comes into a room and branches there; where every panel line has its own
breaker (premium panel, proper layout: lines.per_line) each box and each switch keeps a panel
line of its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from floorplan_engine.electrical.anchors import Anchor
from floorplan_engine.electrical.detours import drop_offset
from floorplan_engine.electrical.panel import scheme_of
from floorplan_engine.electrical.routing import Crossing, End, Router
from floorplan_engine.electrical.wiring_model import Circuit, Route
from floorplan_engine.model.geometry import RoomGeometry, Vec
from floorplan_engine.model.schema import Board, Electrical, ElectricalPoint, Plan, PointType

END_ALLOWANCE = 200.0  # mm: cable tail at every connection except the panel
LIGHT_LOOP = 600.0  # mm: cable loop at each ceiling light of a chain, 30 cm each way
SWITCH_TYPES = frozenset({PointType.SWITCH, PointType.PASS_SWITCH})
# Lighting in a room goes through a box (decision 2026-10-21), unless in a chain (light_wiring)
LIGHT_TYPES = frozenset(
    {
        PointType.LIGHT,
        PointType.DOWNLIGHT,
        PointType.PENDANT,
        PointType.SCONCE,
        PointType.SWITCH,
        PointType.PASS_SWITCH,
        PointType.LED_OUTPUT,
    }
)
LAMP_TYPES = LIGHT_TYPES - SWITCH_TYPES  # lights and LED outputs, without switches
FRAME_SPAN = 100.0  # mm along the wall: mechanisms this close at one height share a frame


def one_feed(elec: Electrical) -> bool:
    """One cable of a group into a room, branching there; False where every line from the panel
    has its own breaker (premium panel or proper layout, as lines.per_line)."""
    return not (elec.mode == "proper" or scheme_of(elec) == "premium")


def same_frame(a: ElectricalPoint, b: ElectricalPoint) -> bool:
    """Two wall points side by side in one frame: the cable between them does not leave the wall."""
    if a.room != b.room or a.wall != b.wall or a.offset is None or b.offset is None:
        return False
    return a.height == b.height and abs(a.offset - b.offset) <= FRAME_SPAN


def rise_from(height: float, ceiling: float, route: Route) -> float:
    """From a connection at height (mm from the floor) to the route plane: down to the floor or
    up to the ceiling."""
    return height if route == "floor" else max(ceiling - height, 0.0)


def rise(pt: ElectricalPoint, ceiling: float, route: Route) -> float:
    """From the connection point to the route plane, mm: up to the ceiling (a ceiling point
    gives 0) or down to the floor (a ceiling point gives the whole wall height)."""
    if pt.ceiling is not None:
        return ceiling if route == "floor" else 0.0
    assert pt.height is not None  # a wall point always has a height (validated)
    return rise_from(pt.height, ceiling, route)


def between_plane(route: Route, a: ElectricalPoint, b: ElectricalPoint) -> Route:
    """Plane of a cable from point to point: the ceiling if the route is there or either end is a
    ceiling point (no cable crosses the room volume, decision 2026-11-01), else the floor."""
    on_ceiling = route == "ceiling" or a.ceiling is not None or b.ceiling is not None
    return "ceiling" if on_ceiling else "floor"


@dataclass(frozen=True)
class Link:
    """A line of the topology before routing: from source to target, with what is known of its
    cable and vertical parts."""

    group: str
    mark: str
    mark_assumed: bool
    source: str
    target: str
    target_anchor: Anchor
    source_rise: float
    target_rise: float
    route: Route
    circuit: Circuit
    cross: bool = False  # box branch into a neighbouring room: a switch by the door outside
    ends: float | None = None  # cable at both ends, mm; None: END_ALLOWANCE and the source tail
    led: bool = False  # 12 V line from an LED supply in the panel
    wall: bool = False  # a jumper between mechanisms of one frame: straight along the wall
    weight: float = (
        1.0  # cost of a millimetre of route (routing.Router weight): more for a LED line
    )


@dataclass(frozen=True)
class Context:
    """Shared by all groups: plan, connection points, panel and routes from it."""

    plan: Plan
    geoms: dict[str, RoomGeometry]
    anchors: dict[str, Anchor]
    board: Board
    board_end: End  # where the panel's cables start
    free: BaseGeometry  # the whole flat with openings, for branches to switches behind a door
    any_angle: bool = False  # ceiling and floor routes at any angle (routing.py)
    rooms: dict[str, str] = field(default_factory=dict)  # room of each point
    media: Board | None = None  # low-voltage cabinet (source "media")
    media_end: End | None = None
    walls: Sequence[Polygon] = ()  # drillable walls (routing.drillable_walls)
    passes: Sequence[Polygon] = ()  # openings lower than the ceiling (routing.ceiling_passes)
    points: dict[str, ElectricalPoint] = field(default_factory=dict)
    # Routers from the panel and the cabinet by plane, without ready holes (from_source)
    routers: dict[tuple[str, Route], Router] = field(default_factory=dict, repr=False)

    def bands(self, route: Route) -> tuple[Polygon, ...]:
        """What a route of the plane pays to cross: drillable walls on both planes, openings
        lower than the ceiling on the ceiling only (decision 2026-11-23)."""
        return (*self.walls, *self.passes) if route == "ceiling" else tuple(self.walls)

    def flat_router(self, end: End, route: Route, holes: Sequence[Crossing] = ()) -> Router:
        """Router through the whole flat from the end on the plane: via openings and drillable
        walls, with the ready holes of the plane."""
        passes = self.passes if route == "ceiling" else ()
        return Router(self.free, end, self.any_angle, self.walls, passes=passes, holes=holes)

    def from_source(self, source: str, route: Route) -> Router:
        """Router from the panel ("board") or the low-voltage cabinet ("media") on the plane,
        without ready holes: the costs the topology is chosen by (what is nearest to the panel)
        and the first search of the lines from it."""
        key = (source, route)
        if key not in self.routers:
            end = self.media_end if source == "media" else self.board_end
            assert end is not None  # "media" only with a cabinet (low_links.low_link)
            self.routers[key] = self.flat_router(end, route)
        return self.routers[key]

    def drop(self, pid: str, route: Route) -> tuple[Anchor, float] | None:
        """Where the cable goes down to a wall point beside an opening (detours.py): the route
        end there and the wall offset of the drop; None when it goes straight above the point."""
        p = self.points.get(pid)
        if p is None or p.offset is None:
            return None
        at = drop_offset(self.geoms[p.room], p, self.ceiling, route)
        a = self.anchors[pid]
        if at is None or a.wall_dir is None:
            return None
        return Anchor(a.pos + a.wall_dir * (at - p.offset), a.inward, a.wall_dir, a.depth), at

    def tail(self, source: str) -> float:
        """Tail inside the panel or the cabinet down to the floor; END_ALLOWANCE elsewhere."""
        if source == "media" and self.media is not None:
            return self.media.height
        return self.board.height if source == "board" else END_ALLOWANCE

    def source_rise(self, route: Route, source: str = "board") -> float:
        """From the panel's (or the cabinet's) connection height to the route plane."""
        return rise_from(self.tail(source), self.ceiling, route)

    def nearest_chain(self, at: Vec, left: list[ElectricalPoint]) -> list[ElectricalPoint]:
        """The points in the order a cable from `at` visits them: the nearest not yet taken each
        time, equal distances by id. `left` is emptied."""
        out: list[ElectricalPoint] = []
        while left:
            p = min(left, key=lambda q: ((self.anchors[q.id].node - at).length(), q.id))
            left.remove(p)
            out.append(p)
            at = self.anchors[p.id].node
        return out

    @property
    def ceiling(self) -> float:
        return self.plan.ceiling_height
