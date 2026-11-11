"""Wiring through boxes, the result: junction boxes (size, spot, ceiling or floor), cable lines
with lengths by part, wall chases, holes in openings; Wiring holds everything together for
the wiring sheet, estimate, elevations and 3D."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from shapely.geometry.base import BaseGeometry

from floorplan_engine.electrical.anchors import Anchor
from floorplan_engine.model.geometry import Vec

BOX_BELOW_CEILING = 200.0  # mm: from the ceiling to the box
BOX_ABOVE_FLOOR = 300.0  # mm: from the floor to the box for floor routes
CHASE_NARROW = 2  # up to this many cables a chase is narrow, more is wide
# A conduit is wider than a flat cable: a narrow chase takes one, two side by side need a wide one
CHASE_NARROW_CONDUIT = 1


Route = Literal["ceiling", "floor"]


Circuit = Literal["power", "low"]  # 230 V power and low-voltage


ChaseKey = tuple[str, str, Route, Circuit]  # room, wall, route plane, circuit


@dataclass(frozen=True)
class JunctionBox:
    id: str
    label: str  # "К1" on the drawing
    room: str
    group: str
    anchor: Anchor
    route: Route = "ceiling"
    wet: bool = False  # IP44 box in a wet room
    size: str = "100x100"  # size by number of lines (box_size), a BOX_SIZES key

    @property
    def on_ceiling(self) -> bool:
        return self.anchor.inward is None

    @property
    def rise_mm(self) -> float:
        """From the box to the route plane, ceiling or floor; 0 for a ceiling box."""
        if self.on_ceiling:
            return 0.0
        return BOX_ABOVE_FLOOR if self.route == "floor" else BOX_BELOW_CEILING


@dataclass(frozen=True)
class Run:
    """One cable line: panel → box, panel → point, box → point, or point → point in a daisy
    chain."""

    id: str
    group: str
    mark: str
    mark_assumed: bool  # cable type not in the model, taken from the point types
    source: str  # board, a box id or, in a daisy chain, a point id
    target: str  # box or point id
    path: tuple[Vec, ...]
    plan_mm: float
    rise_start_mm: float  # from the line start (panel, box, point) to the ceiling or floor
    rise_end_mm: float  # along the wall from ceiling (floor) to line end; 0 for ceiling
    ends_mm: float
    route: Route = "ceiling"
    circuit: Circuit = "power"

    @property
    def vertical_mm(self) -> float:
        return self.rise_start_mm + self.rise_end_mm

    @property
    def length_mm(self) -> float:
        return self.plan_mm + self.vertical_mm + self.ends_mm


def line_starts(runs: Sequence[Run]) -> dict[str, str]:
    """For each line end, what the panel feeds it through: a box, the head of a daisy chain, or
    the end itself."""
    source = {r.target: r.source for r in runs}

    def start(target: str) -> str:
        while source.get(target, "board") != "board":
            target = source[target]
        return target

    return {r.target: start(r.target) for r in runs}


@dataclass(frozen=True)
class Chase:
    """Wall chase from the ceiling down (route floor: from the floor up): kind is point (to points),
    board (at the panel), box (at a box), channel (a cable channel between two heights, span)."""

    kind: str
    room: str
    wall: str  # wall id; "" for a box
    offset: float  # from the wall start to the chase centre; 0 for a box
    length_mm: float
    cables: int
    targets: tuple[str, ...] = ()  # ids of points the chase cables go to
    route: Route = "ceiling"
    circuit: Circuit = "power"
    span: tuple[float, float] | None = None  # heights from the floor, low to high: only a channel
    conduit: bool = False  # the cables go down the chase in conduit (chases.with_conduit)

    @property
    def wide(self) -> bool:
        return self.cables > (CHASE_NARROW_CONDUIT if self.conduit else CHASE_NARROW)


@dataclass(frozen=True)
class Hole:
    """Hole in the wall above a door or opening for ceiling routes."""

    passage: str  # door or opening id
    cables: int
    circuit: Circuit = "power"
    runs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Wiring:
    ceiling_height: float
    height_assumed: bool  # ceiling height missing in room.yaml: 2700 by default
    boxes: tuple[JunctionBox, ...]
    runs: tuple[Run, ...]
    skipped: tuple[str, ...] = field(default=())  # points without a group
    chases: tuple[Chase, ...] = field(default=())
    holes: tuple[Hole, ...] = field(default=())
    # Rooms and openings (routing.free_area), so a bundle on the sheet does not run onto walls
    free: BaseGeometry | None = field(default=None, compare=False, repr=False)
    # Manual edits: applied "wire:id" and "box:id"; remarks are (path in wiring.yaml, text)
    edited: frozenset[str] = field(default=frozenset())
    edit_notes: tuple[tuple[str, str], ...] = field(default=())
    before_plaster: bool = False  # cable laid before the plaster: chases only with conduit

    @property
    def chase_mm(self) -> float:
        return sum(c.length_mm for c in self.chases)

    def chase_length(self, wide: bool) -> float:
        """Length of narrow or wide chases, mm."""
        return sum(c.length_mm for c in self.chases if c.wide == wide)

    def by_mark(self) -> dict[str, float]:
        """Length by cable type, m, without margin."""
        out: dict[str, float] = defaultdict(float)
        for r in self.runs:
            out[r.mark] += r.length_mm / 1000
        return dict(sorted(out.items()))
