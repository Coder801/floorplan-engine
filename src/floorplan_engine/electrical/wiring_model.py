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
from floorplan_engine.electrical.floor_heating import HeatingZone
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.schema import WallMaterial

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
    # Wall offset of the drop at the line end (start) when it goes down beside an opening, not
    # above the point (detours.py): the path ends (starts) there, the rise includes the turn
    # along the wall at the point height
    end_drop: float | None = None
    start_drop: float | None = None
    # 12 V line from an LED supply in the panel (led_supply "board"): low voltage, but lighting;
    # its cross-section goes by the voltage drop (led_supply.section_for)
    led: bool = False

    @property
    def lay(self) -> Circuit:
        """Which cables the line lies with, in a chase, a wall hole and a conduit: a 12 V LED line
        from the panel goes with the power cables (decision 2026-11-13: its cable has 230 V
        insulation), internet and TV stay apart."""
        return "power" if self.led else self.circuit

    @property
    def vertical_mm(self) -> float:
        return self.rise_start_mm + self.rise_end_mm

    @property
    def length_mm(self) -> float:
        return self.plan_mm + self.vertical_mm + self.ends_mm


def line_starts(runs: Sequence[Run]) -> dict[str, str]:
    """For each line end, what the panel (or the low-voltage cabinet) feeds it through: a box,
    the head of a daisy chain, or the end itself."""
    source = {r.target: r.source for r in runs}

    def start(target: str) -> str:
        while source.get(target, "board") not in ("board", "media"):
            target = source[target]
        return target

    return {r.target: start(r.target) for r in runs}


@dataclass(frozen=True)
class Chase:
    """Wall chase from the ceiling down (route floor: from the floor up), past an opening with a
    turn along the wall (bend): kind is point (to points),
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
    material: WallMaterial | None = None  # wall material (chases.with_material); None — unknown
    # Daisy chain points whose cable in and cable out share one conduit (Electrical.loop_conduit
    # "shared", chases.with_conduit): each pair is one conduit, not two
    pairs: int = 0
    # Past an opening (detours.py): the chase goes along the wall at height y to offset x after
    # its drop at offset; length_mm includes that turn
    bend: tuple[float, float] | None = None

    @property
    def conduits(self) -> int:
        """Conduits down the chase: a cable each, a shared pair one."""
        return self.cables - self.pairs

    @property
    def wide(self) -> bool:
        if self.conduit:
            return self.conduits > CHASE_NARROW_CONDUIT
        return self.cables > CHASE_NARROW


@dataclass(frozen=True)
class Sleeve:
    """One cable pass through a wall (decision 2026-11-28, sleeves.py): a smooth rigid PVC
    sleeve, its outer Ø and the cross-section its cables take; the gap between them is sealed
    with firestop foam."""

    diameter: int  # outer Ø, mm (sleeves.SLEEVE_INNER)
    cables_mm2: float  # cross-section of its cables, mm²; a cable without sizes counts as 0
    runs: tuple[str, ...] = ()
    # A power cable with a cross-section but no known size (mounting.FLAT_CABLE: 3×10, 5×16): alone
    # in the sleeve of its conduit size (sleeves.fit_sleeves), to check against the cable
    by_section: bool = False


@dataclass(frozen=True)
class Hole:
    """Where routes pass through a wall: above a door or opening for ceiling routes, or through
    a drillable wall. Its cables go through cable passes side by side, one PVC sleeve each
    (sleeves, decision 2026-11-28: no large core-drilled hole, the cables one Ø40 does not hold
    go in the next pass), sealed with firestop foam; wall_mm is the wall thickness there."""

    passage: str  # door or opening id, "wall:…" for a drillable wall
    cables: int
    circuit: Circuit = "power"
    runs: tuple[str, ...] = ()
    wall_mm: float = 0.0  # wall thickness at the pass; 0 — unknown
    wall_assumed: bool = False  # room.yaml gives that wall no thickness: default_wall_thickness
    sleeves: tuple[Sleeve, ...] = ()  # the cable passes, sleeves.with_sleeves


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
    # Cable drops along the walls, chased or not (the chases before before_plaster, without cable
    # channels): the elevations put the wall fixings on them
    drops: tuple[Chase, ...] = field(default=())
    # Lines whose rise from a chain point goes in the conduit of the cable coming in
    # (Electrical.loop_conduit "shared", chases.shared_rises): that rise has no conduit of its own
    shared_rises: frozenset[str] = field(default=frozenset())
    # Floor heating zones (floor_heating.py): heating cable, sensor and its conduit for the estimate
    heating: tuple[HeatingZone, ...] = field(default=(), compare=False, repr=False)
    # Boxes left on lines that do not go into them (decision 2026-11-17, box_spots.clear_boxes):
    # (box id, what was done), warnings in the report
    box_notes: tuple[tuple[str, str], ...] = field(default=())
    # Where the cable goes into a wall mechanism's frame (frames.entries, decision 2026-11-17):
    # (point id, wall offset), at the side of the block, not above its middle
    entries: tuple[tuple[str, float], ...] = field(default=())

    def entry(self, point: str, offset: float) -> float:
        """Wall offset of the cable drop to a point: its frame entry, else the point offset."""
        return dict(self.entries).get(point, offset)

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
