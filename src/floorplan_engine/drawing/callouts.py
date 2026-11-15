"""Free spots for plan labels and 45° leaders (plan sheet: dimension numbers, wall codes, sill
labels, room names).

A label is a rectangle in its reading frame: d along the text, up across it (the text never
reads upside down, `reading`). Obstacles lie on a `Board`: linework (dimension and extension
lines, ticks, walls, windows, door leaves; leaders already drawn), zones (door swings: only
for labels that ask for them) and labels placed so far. A label first tries its own spots
(the caller's list, nearest first). With all of them taken it goes along one of the four 45°
diagonals of its reading frame from its anchor (what it labels), farther step by step, and
sits on a shelf at the end of the leader: anchor → elbow at 45° → shelf under the text.
The shortest free leader wins: the text off everything, the leader crossing no label, no other
leader and no wall; at the same length the text inside the preferred area (the room of a wall
code), then the leader crossing the fewest lines (`Board.find_leader_spot`). With no spot at all
the label takes the spot that touches the fewest labels, then lines.

Geometry is model mm; sizes "on the sheet" are converted with `scale.sheet`.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from enum import Enum

import shapely
from shapely import STRtree
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.scale import sheet

CORNERS = ((-1, -1), (1, -1), (1, 1), (-1, 1))
PAD_MM = 0.5  # free margin around a label: the viewer draws labels larger about their centre
SHELF_GAP_MM = 0.5  # text above its shelf and past its ends
LEADER_START_MM = 2.5  # first elbow distance from the anchor along the diagonal
ANCHOR_TOUCH_MM = 0.5  # a label this close to the anchor counts as covering it
LEADER_STEP_MM = 1.0
LEADER_MAX_MM = 30.0


def readable_angle(angle: float) -> float:
    """Text angle that keeps it from reading upside down."""
    angle = (angle + 180.0) % 360.0 - 180.0
    if angle > 90.0 + 1e-6 or angle <= -90.0 + 1e-6:
        angle += 180.0
    return angle


def reading(direction: Vec) -> tuple[Vec, Vec]:
    """Reading direction of a text laid along direction, and its "up" side."""
    d = direction
    angle = math.degrees(math.atan2(d.y, d.x))
    if abs(readable_angle(angle) - angle) > 1e-6:
        d = d * -1.0
    return d, d.left()


def rect(c: Vec, d: Vec, up: Vec, hw: float, hh: float) -> Polygon:
    """Rectangle centred at c, half-width hw along d and half-height hh along up."""
    return Polygon([(c + d * (sx * hw) + up * (sy * hh)).as_tuple() for sx, sy in CORNERS])


class Kind(Enum):
    LINE = "line"  # linework: no label sits on it; a strict leader does not cross it
    ZONE = "zone"  # door swing: only labels that ask for it keep off
    LABEL = "label"  # placed label: neither labels nor leaders touch it
    LEADER = "leader"  # drawn leader: neither labels nor other leaders cross it
    WALL = "wall"  # wall or opening in it: no label sits on it, no leader crosses it


@dataclass(frozen=True)
class Obstacle:
    """Something on the sheet; owner is what it belongs to (a label's own lines do not block its
    leader), group the larger object (all rows of one wall's dimensions)."""

    geom: BaseGeometry
    kind: Kind
    owner: str = ""
    group: str = ""


@dataclass(frozen=True)
class Label:
    """Text of width × height (model mm) read along d with up across; the leader starts at
    anchor; owner names its own obstacles."""

    width: float
    height: float
    d: Vec
    up: Vec
    anchor: Vec
    owner: str

    def box(self, centre: Vec) -> Polygon:
        """The text at centre with its free margin."""
        pad = sheet(PAD_MM)
        return rect(centre, self.d, self.up, self.width / 2 + pad, self.height / 2 + pad)


@dataclass(frozen=True)
class Candidate:
    """Own spot of a label (text centre); ignore are obstacle owners it may touch there (the
    ticks at the ends of its own dimension)."""

    centre: Vec
    ignore: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Spot:
    """Where the label went: text centre, its box with the margin and the leader polyline
    (anchor, elbow, shelf end), empty without a leader."""

    centre: Vec
    box: Polygon
    leader: tuple[Vec, ...] = ()


@dataclass
class Board:
    """Obstacles of the plan sheet; frame is the drawing extent a moved label should stay in."""

    fixed: Sequence[Obstacle]
    frame: BaseGeometry | None = None
    placed: list[Obstacle] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._fixed_tree = STRtree([o.geom for o in self.fixed])
        self._tree: STRtree | None = None

    def add(self, obstacle: Obstacle) -> None:
        self.placed.append(obstacle)
        self._tree = None

    def _near(self, geom: BaseGeometry) -> Iterator[Obstacle]:
        for k in self._fixed_tree.query(geom, predicate="intersects"):
            yield self.fixed[int(k)]
        if self.placed:
            if self._tree is None:
                self._tree = STRtree([o.geom for o in self.placed])
            for k in self._tree.query(geom, predicate="intersects"):
                yield self.placed[int(k)]

    def blocked(
        self,
        geom: BaseGeometry,
        kinds: frozenset[Kind],
        ignore: frozenset[str] = frozenset(),
    ) -> bool:
        """Something of these kinds touches geom (except what ignore names)."""
        return any(
            o.kind in kinds and o.owner not in ignore and o.group not in ignore
            for o in self._near(geom)
        )

    def count(
        self,
        geom: BaseGeometry,
        kinds: frozenset[Kind],
        ignore: frozenset[str] = frozenset(),
    ) -> int:
        """How many obstacles of these kinds touch geom."""
        return sum(
            o.kind in kinds and o.owner not in ignore and o.group not in ignore
            for o in self._near(geom)
        )

    def place(
        self,
        label: Label,
        spots: Sequence[Candidate],
        *,
        zones: bool = False,
        within: BaseGeometry | None = None,
        prefer: BaseGeometry | None = None,
    ) -> Spot:
        """The label's first free own spot (inside within, if given), else a spot along a 45°
        diagonal with a leader (`find_leader_spot`), else the spot that touches the fewest
        obstacles. What is placed (text box, leader) becomes an obstacle for the next labels."""
        kinds = _kinds(zones)
        spot = next(
            (
                Spot(c.centre, box)
                for c in spots
                for box in (label.box(c.centre),)
                if (within is None or within.contains(box))
                and not self.blocked(box, kinds, c.ignore)
            ),
            None,
        )
        if spot is None:
            spot = self.find_leader_spot(label, zones=zones, prefer=prefer)
        if spot is None:
            spot = self._least_bad(label, spots, kinds)
        self.take(label, spot)
        return spot

    def find_leader_spot(
        self, label: Label, *, zones: bool = False, prefer: BaseGeometry | None = None
    ) -> Spot | None:
        """Free spot on a shelf at the end of the shortest 45° leader from the anchor: the text
        off everything, the leader crossing no label, no other leader and no wall (but its own).
        At the same length: text inside prefer first, then the leader crossing the fewest lines.
        The text stays inside the drawing frame if it can. Last, if the anchor is under or touches
        a label (a room name wider than its room), the leader may start across that label."""
        kinds = _kinds(zones)
        own = frozenset({label.owner})
        options = list(_diagonal_spots(label))
        frame = self.frame

        for area in (frame, None) if frame is not None else (None,):
            for _, group in itertools.groupby(options, key=_reach):
                valid = [
                    (spot, path)
                    for spot, path in group
                    if (area is None or area.contains(spot.box))
                    and not self.blocked(spot.box, kinds)
                    and not self.blocked(path, _HARD, own)
                ]
                if valid:
                    return min(
                        valid,
                        key=lambda o: (
                            prefer is not None and not prefer.contains(o[0].box),
                            self.count(o[1], _LINES, own),
                        ),
                    )[0]
        # only a label the anchor is under or touches: a label merely near it stays a hard
        # obstacle (a leader across a sill label beside the wall code reads as pointing at it)
        at = Point(label.anchor.as_tuple()).buffer(sheet(ANCHOR_TOUCH_MM))
        cover = [o.geom for o in self._near(at) if o.kind is Kind.LABEL]
        if cover:
            under = shapely.unary_union(cover).buffer(sheet(0.1))
            for spot, path in options:
                if self.blocked(spot.box, kinds):
                    continue
                if self.blocked(path.difference(under), _HARD, own):
                    continue
                return spot
        return None

    def _least_bad(self, label: Label, spots: Sequence[Candidate], kinds: frozenset[Kind]) -> Spot:
        """With no free spot: the own spot or leader spot whose text touches the fewest labels
        (and whose leader crosses the fewest labels, leaders and walls), then the fewest lines;
        the first such."""
        own = frozenset({label.owner})
        options: list[tuple[Spot, frozenset[str], BaseGeometry | None]] = [
            (Spot(c.centre, label.box(c.centre)), c.ignore, None) for c in spots
        ]
        options += [(spot, own, path) for spot, path in _diagonal_spots(label)]

        def cost(option: tuple[Spot, frozenset[str], BaseGeometry | None]) -> int:
            spot, ignore, path = option
            hits = 100 * self.count(spot.box, _LABELS, ignore)
            hits += self.count(spot.box, kinds, ignore)
            if path is not None:
                hits += 100 * self.count(path, _HARD, own) + 1
            return hits

        return min(options, key=cost)[0]

    def take(self, label: Label, spot: Spot) -> None:
        """The placed text and leader become obstacles for everyone, the labels of the same
        object too (they are not its linework)."""
        self.add(Obstacle(spot.box, Kind.LABEL))
        if spot.leader:
            self.add(Obstacle(LineString([p.as_tuple() for p in spot.leader]), Kind.LEADER))


_LABELS = frozenset({Kind.LABEL, Kind.LEADER})
_HARD = frozenset({Kind.LABEL, Kind.LEADER, Kind.WALL})  # a leader never crosses these
_LINES = frozenset({Kind.LINE})
_ANY_LINE = frozenset({Kind.LINE, Kind.LABEL, Kind.LEADER, Kind.WALL})


def _kinds(zones: bool) -> frozenset[Kind]:
    """What a label's text keeps off."""
    return _ANY_LINE | {Kind.ZONE} if zones else _ANY_LINE


def _reach(option: tuple[Spot, LineString]) -> float:
    """Length of the slanted part of a leader, rounded so one step makes one group."""
    anchor, elbow = option[0].leader[0], option[0].leader[1]
    return round((elbow - anchor).length(), 3)


def _diagonal_spots(label: Label) -> Iterator[tuple[Spot, LineString]]:
    """Spots along the four 45° diagonals of the reading frame, nearest first: the text sits on
    a shelf that starts at the elbow and runs away from the anchor; on a rising leader the
    shelf may also run back over the anchor (the text stays above the leader). The path for the
    obstacle check leaves out the first millimetre at the anchor (it touches what it labels)."""
    gap = sheet(SHELF_GAP_MM)
    shelf = label.width + 2 * gap
    diag = 1 / math.sqrt(2)
    steps = round((LEADER_MAX_MM - LEADER_START_MM) / LEADER_STEP_MM)
    for k in range(steps + 1):
        t = sheet(LEADER_START_MM + k * LEADER_STEP_MM)
        for sx, sy, back in _DIAGONALS:
            v = (label.d * sx + label.up * sy) * diag
            elbow = label.anchor + v * t
            way = -sx if back else sx
            end = elbow + label.d * (way * shelf)
            centre = elbow + label.d * (way * shelf / 2) + label.up * (gap + label.height / 2)
            start = label.anchor + v * min(sheet(1.0), t / 2)
            path = LineString([start.as_tuple(), elbow.as_tuple(), end.as_tuple()])
            yield Spot(centre, label.box(centre), (label.anchor, elbow, end)), path


# (along, across, shelf back over the anchor): up first, the shelf away from the anchor first
_DIAGONALS = (
    (1, 1, False),
    (-1, 1, False),
    (1, -1, False),
    (-1, -1, False),
    (1, 1, True),
    (-1, 1, True),
)
