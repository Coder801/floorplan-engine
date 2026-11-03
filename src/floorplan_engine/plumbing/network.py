"""Water supply and sewer network from plumbing.yaml: fixture supplies, routes, checks.

Rules (docs/plumbing.md):
- routes run on the floor (water in the screed, sewer on the floor in a box), at right
  angles, around walls and obstacles (installation frame, bath, tray, box), through door
  openings, at least routing.CLEARANCE from walls, on the same grid as wiring;
- a pipe reaches a fixture on the floor at the nearest free spot by its wall, then continues
  in the wall: along it (wall_run) and up to the water outlet or drain (rise). This way the
  route goes around an installation frame and a bath: the mixer above a bath is reached from
  the side, in the wall;
- water is radial (collector, the default): each water outlet has its own Ø16 pipe from the
  cold or hot manifold in the supply unit; tee layout (tee, economy): a main from the supply
  unit, a branch to each fixture from the nearest point of the main; a pipe with branches is
  Ø20, end ones are Ø16. The hot manifold for a boiler sits at the boiler. In the radial
  layout, neighbours on one wall (a double vanity, a dishwasher by the sink: supply_groups)
  share one Ø16 pipe from the manifold per water, the second one via a tee at the first; a
  branch that runs alongside another for long, or is much shorter as a branch from it, is
  teed off it if the shared pipe can carry the flow (_merge_parallel). Hot water comes from
  a riser or from a boiler (the boiler takes cold from the manifold and feeds hot into the
  hot manifold or the main);
- the outlets of a pair: hot on the left, cold on the right (view from inside), HOT_COLD_GAP / 2
  from the middle of the supply;
- sewer (routing spec 2026-11-02) is a tree to the riser: WCs first (Ø110, only into the
  riser or a Ø110 pipe, branch no longer than WC_REACH), then the rest into the riser or a
  Ø50 pipe (the WC is closest to the riser). Its own grid: never through door openings or
  thresholds of living rooms, hidden zones (box, installation frame, under bath and tray,
  HIDDEN_HEIGHT) are preferred; the search goes in eight directions, corners only with 45°
  bends (plumbing/bends.py), branches join with an angled tee. Heights are computed backwards
  from the riser inlet, from the slab: one slope over the whole fixture route (SLOPE, down to
  SLOPE_MIN for Ø110), a higher drain means a drop in the wall. In the screed (SCREED_MM) the
  pipe bottom + Ø + SCREED_COVER must not exceed the screed, Ø110 is not allowed in the
  screed. What does not fit in the screed runs along the wall above the floor (zone surface:
  by the wall, in a box; change 2026-11-02): not an error but a note with the box height; in
  the screed only pieces in the middle of a room and through openings remain errors. Passes:
  normal, through hidden zones and only along walls; the pass with fewer errors wins
  (SewerError, routes in SewerRoute, JSON in routes_json);
- weak spots (Weak) go to the sheet and the report: screed, height drop, WC branch, sewer
  through a living room, many bends, unreachable fixture, no hot water.

Supply heights without data come from FIXTURE_SPECS (an assumption, "*" in the fixture table);
the riser inlet axis without data is SEWER_INLET_MM.
"""

from __future__ import annotations

import itertools
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from floorplan_engine.electrical.routing import (
    CLEARANCE,
    STEP,
    Grid,
    fit_path,
    free_area,
    opening_strip,
    simplify,
)
from floorplan_engine.model.geometry import (
    Contour,
    RoomGeometry,
    Vec,
    WallSegment,
    point_in_polygon,
    room_geometries,
)
from floorplan_engine.model.plumbing import (
    SEWER_INLET_MM,
    Fixture,
    FixtureType,
    Obstacle,
    ObstacleType,
    Plumbing,
    Riser,
)
from floorplan_engine.model.schema import OpeningType, Plan, Room
from floorplan_engine.model.texts import Language
from floorplan_engine.plumbing import bends as b45

Kind = Literal["cold", "hot", "sewer"]
KINDS: tuple[Kind, ...] = ("cold", "hot", "sewer")

HOT_COLD_GAP = 150.0  # mm between the cold and hot water outlets
COLLECTOR_GAP = 200.0  # mm between the cold and hot manifolds in the unit
SUPPLY_D = 16  # Ø of a manifold branch and an end branch, mm (multilayer / PEX 16)
MAIN_D = 20  # Ø of the main, inlet and boiler feed, mm
# Sewer slope (routing spec 2026-11-02): 2–3 cm per metre, one over the whole fixture route,
# from a list (_sewer_heights): 0.025 by default; 0.02 if the route fails at 0.025, Ø110
# only (Ø50 not below 0.025 per DBN V.2.5-64, like SNiP 2.04.01-85); 0.03 if the height
# allows it (a route with no branches off it: the main is no steeper than its branches)
SLOPE = {50: 0.025, 110: 0.025}
SLOPE_MIN = {50: 0.025, 110: 0.02}
SLOPE_MAX = 0.03
SCREED_MM = 90.0  # finished floor 90 mm above slab; sewer heights from slab
SCREED_COVER = 15.0  # mm above a pipe in the screed, at least
RISER_TEE_D = 110  # riser tee: inlet bottom is the inlet axis minus the Ø110 radius
# Hidden sewer zones are obstacles where the pipe is hidden: the highest pipe top from the
# finished floor (if the obstacle has no height, this one, as an assumption)
HIDDEN_HEIGHT = {
    ObstacleType.INSTALLATION: 1000.0,
    ObstacleType.BOX: 600.0,
    ObstacleType.BATH: 450.0,  # under the bath, behind the panel
    ObstacleType.SHOWER_TRAY: 100.0,  # under the tray
}
# Sewer grid cell cost is a step length multiplier (routing spec, change 2026-11-02): a hidden
# zone is cheapest, by a wall 1, farther out more expensive. Free grid cells are at least
# CLEARANCE (150 mm) from a wall, so "by the wall" is the first pipe axis band, up to WALL_BAND_MM
HIDDEN_COST = 0.7
WALL_COST = 1.0
NEAR_WALL_COST = 2.0
OPEN_ROOM_COST = 4.0  # ≥ 3: a diagonal is at most √2 times shorter than the path along walls
WALL_BAND_MM = CLEARANCE + STEP  # band by the wall: a box above the floor is allowed here
NEAR_WALL_MM = 400.0  # farther out: the middle of the room
# Sewer route variants (passes of _sewer): costs of hidden, by the wall, near, middle
SEWER_VARIANTS: tuple[tuple[float, float, float, float], ...] = (
    (HIDDEN_COST, WALL_COST, NEAR_WALL_COST, OPEN_ROOM_COST),  # normal
    (0.2, WALL_COST * 3, NEAR_WALL_COST * 3, OPEN_ROOM_COST * 3),  # through hidden zones
    (HIDDEN_COST, WALL_COST, NEAR_WALL_COST * 5, OPEN_ROOM_COST * 10),  # only along walls
)
# Sewer grid cell kind (Grid.tag): hidden zone, by the wall, near, middle
TAG_HIDDEN, TAG_WALL, TAG_NEAR, TAG_OPEN = 0, 1, 2, 3
FALLBACK_COST = 1e6  # path without height pruning, only if the fixture is otherwise unreachable
# Hollow obstacles: pipes of their own fixture go inside (box, installation frame), others go around
HOLLOW = frozenset({ObstacleType.INSTALLATION, ObstacleType.BOX})
PARTITION_MAX = 150.0  # mm: thinner non-bearing walls are partitions
PARTITION_COST = 1000.0  # mm per cell at a partition: a pass ≈ a 4 m detour
UNDER_COST = 50.0  # mm per cell under a plasterboard wall inside a room: almost free
DOOR_COST = 20000.0  # mm per cell in a door opening: pipes through a door only as a last resort
HOLE_SHARE = 300.0  # mm: closer pipes share one hole
RISER_WALL = 400.0  # mm: riser in the wall to the room, at most
RISER_REACH = 800.0  # mm: how far from the riser to look for an approach on each side
WC_REACH = 1000.0  # mm along the pipe to the riser: a longer WC branch is an error
SEWER_BENDS = 6  # 45° plan bends on a sewer pipe; more than this needs a cleanout
DROP_TURN = 150.0  # mm: a drop at least this high takes two 90° turns (down, onto the floor);
# less takes an offset down with two 45° bends (a "duck")
# Pipe consumption ("tees" spec 2026-11-02): weight per metre by diameter and a 45° bend in mm
# of equivalent length; Ø50 tees come from merging fixture pairs by savings (_merge_drains)
PIPE_WEIGHT = {50: 1.0, 110: 2.2}
TURN_COST_MM = 175.0  # 45° bend in mm of equivalent length: in the search and in tee savings
SEWER_BEND_COST = TURN_COST_MM
TEE_CANDIDATES = 20  # tee spots per pair: if the best is not allowed, the next by cost
REACH = CLEARANCE + 1.6 * STEP  # how far from the wall to look for the approach to a fixture
ALONG_COST = 3.0  # a metre along the wall counts as three on the floor: chasing costs more
PAIR_GAP = 80.0  # mm between hot and cold axes running as a pair to one fixture
# Shared line from the manifold (change 2026-11-02): neighbouring fixtures of one room on one
# wall no farther than SHARE_GAP share one pipe per water, with a Ø16 tee at the fixture: two
# basins (double vanity), a dishwasher off the sink's cold
SHARED_PAIRS = frozenset(
    {
        (FixtureType.SINK, FixtureType.SINK),
        (FixtureType.KITCHEN_SINK, FixtureType.DISHWASHER),
        (FixtureType.DISHWASHER, FixtureType.KITCHEN_SINK),
    }
)
SHARED_TYPES = frozenset(t for pair in SHARED_PAIRS for t in pair)
# Parallel lines (change 2026-11-02): a branch running alongside another (closer than PARALLEL_GAP)
# for at least PARALLEL_MIN is teed off it if that is shorter and the pipe can carry the flow
PARALLEL_GAP = 300.0  # mm between axes: running together, as one bundle
PARALLEL_MIN = 2000.0  # mm side by side already counts as "long"
BRANCH_SAVING = 1000.0  # mm: running together briefly; tee off only if it saves this much pipe
# Design flow of a water outlet, l/s, a guide: DBN V.2.5-64 / SNiP 2.04.01-85 (annex 3) for
# basin, sink, shower, bath, WC; washing machine and dishwasher from typical model datasheets
# (≈ 9 and 6 l/min)
FLOW: dict[FixtureType, float] = {
    FixtureType.SINK: 0.09,
    FixtureType.KITCHEN_SINK: 0.09,
    FixtureType.SHOWER: 0.09,
    FixtureType.HYGIENIC_SHOWER: 0.09,
    FixtureType.BATH: 0.18,
    FixtureType.WC: 0.10,
    FixtureType.WC_INSTALLATION: 0.10,
    FixtureType.WASHER: 0.15,
    FixtureType.DISHWASHER: 0.10,
    FixtureType.BOILER: 0.18,
}
# Pipe capacity, l/s, without a simultaneity factor (with a margin): Ø16 (12 mm inside) and
# Ø20 (16 mm inside) at about 1.75 m/s
CAPACITY: dict[int, float] = {16: 0.20, 20: 0.35}
SHARE_GAP = 1200.0  # mm between supply centres
COLLECTOR_HEIGHT = 400.0  # mm: manifold outlet axis from the floor (assumption)
COLLECTOR_HALF = 150.0  # mm: half a manifold with valves along the wall (wall space)
BOILER_NEAR = 1500.0  # mm: hot manifold in the unit if the boiler is closer
# Living rooms: sewer on the floor through them is a weak spot; rooms combined with a kitchen
# or hallway are not (they have their own sink)
LIVING_NAME = re.compile(
    r"спальн|кабінет|кабинет|вітальн|гостин|дитяч|детск|зал\b|кімнат|комнат", re.IGNORECASE
)
SERVICE_NAME = re.compile(r"кухн|коридор|передпок|прихож|хол\b", re.IGNORECASE)
FIXTURE_NAMES: dict[FixtureType, dict[str, str]] = {
    FixtureType.WC: {"ru": "Унитаз", "uk": "Унітаз"},
    FixtureType.WC_INSTALLATION: {"ru": "Унитаз на инсталляции", "uk": "Унітаз на інсталяції"},
    FixtureType.SINK: {"ru": "Умывальник", "uk": "Умивальник"},
    FixtureType.KITCHEN_SINK: {"ru": "Мойка", "uk": "Мийка"},
    FixtureType.BATH: {"ru": "Ванна", "uk": "Ванна"},
    FixtureType.SHOWER: {"ru": "Душ", "uk": "Душ"},
    FixtureType.WASHER: {"ru": "Стиральная машина", "uk": "Пральна машина"},
    FixtureType.DISHWASHER: {"ru": "Посудомоечная машина", "uk": "Посудомийна машина"},
    FixtureType.BOILER: {"ru": "Бойлер", "uk": "Бойлер"},
    FixtureType.HYGIENIC_SHOWER: {"ru": "Гигиенический душ", "uk": "Гігієнічний душ"},
}


def fixture_name(fx: Fixture, language: Language) -> str:
    return FIXTURE_NAMES[fx.type][language]


@dataclass(frozen=True)
class Outlet:
    """Fixture connection on a wall: a water outlet or a drain. node is on the wall face."""

    fixture: str
    kind: Kind
    room: str
    wall: str
    offset: float  # from the wall start, mm
    height: float  # axis from the finished floor, mm
    node: Vec
    inward: Vec
    d: int
    assumed: bool  # typical height (FIXTURE_SPECS)


@dataclass(frozen=True)
class Collector:
    """Manifold (radial) or main start (tee layout) in the supply unit."""

    id: str  # collector_cold, collector_hot
    kind: Kind
    room: str
    wall: str
    offset: float
    node: Vec
    inward: Vec
    outputs: int
    height: float = 0.0  # outlet axis from floor, mm (input.height or COLLECTOR_HEIGHT)


@dataclass(frozen=True)
class RiserNode:
    id: str
    room: str
    center: Vec
    sewer: bool
    water: bool
    inlet: float  # sewer inlet axis from the floor, mm
    inlet_assumed: bool


@dataclass(frozen=True)
class Pipe:
    """Pipe: plan path from source to target (model mm) and the parts in the wall at the target."""

    id: str
    kind: Kind
    source: str  # manifold, riser, boiler or parent pipe (branch)
    target: str  # fixture, hot manifold (boiler feed), supply unit
    path: tuple[Vec, ...]
    d: int
    rise: float  # up in the wall at the target, mm (to the water outlet or drain)
    wall_run: float  # along the wall at the target, mm (in the wall)
    parent: str | None = None
    attach: float = 0.0  # mm from the parent start to the tee
    room: str = ""  # target room
    slope: float = 0.0  # sewer: plan slope
    z0: float = 0.0  # sewer: pipe bottom at the start (riser or tee), mm from the slab
    # sewer along the wall above the floor (does not fit in the screed): parts of its own pipe, mm
    # from the path start (from the riser or tee), and the pipe top above the finished floor there:
    # the box height
    surface: tuple[tuple[float, float], ...] = ()
    surface_top: float = 0.0
    open_length: float = 0.0  # sewer: mm of its own pipe in the middle of a room (variant score)

    @property
    def length(self) -> float:
        """On the plan, without the parts in the wall."""
        return sum((b - a).length() for a, b in itertools.pairwise(self.path)) - self.wall_run

    @property
    def total(self) -> float:
        """The whole pipe: on the floor, along the wall and up."""
        return self.length + self.wall_run + self.rise

    @property
    def bends(self) -> int:
        """45° bends on the plan (a 90° turn counts as two)."""
        return b45.bends(self.path)

    @property
    def surface_length(self) -> float:
        """Along the wall above the floor, mm (in a box, not in the screed)."""
        return sum(b - a for a, b in self.surface)


@dataclass(frozen=True)
class SewerCheck:
    """Sewer height drop of a fixture to the riser inlet. z is the pipe bottom from the slab."""

    fixture: str
    riser: str
    length: float  # along pipes to the riser, mm
    start: float  # drain axis at the fixture, mm from the finished floor
    slope: float  # slope of the fixture route
    d: int
    inlet: float  # riser inlet axis from the finished floor
    inlet_assumed: bool
    z_inlet: float  # pipe bottom at the riser
    z_end: float  # floor pipe bottom at the fixture: inlet plus drop
    z_outlet: float  # drain bottom

    @property
    def drop(self) -> float:
        """Drop along the floor from the fixture to the riser, mm."""
        return self.z_end - self.z_inlet

    @property
    def end_floor(self) -> float:
        """Floor pipe axis at the fixture, mm from the finished floor."""
        return self.z_end + self.d / 2 - SCREED_MM

    @property
    def ok(self) -> bool:
        return self.z_outlet >= self.z_end - 0.5

    @property
    def podium(self) -> float:
        """How much to raise the drain (podium, floor drain) to get enough slope, mm."""
        return max(0.0, self.z_end - self.z_outlet)


Zone = Literal["screed", "hidden", "wall", "surface"]  # surface: along the wall above the floor


@dataclass(frozen=True)
class RouteSegment:
    """Sewer route piece along the flow: points [x, y, z] (z is the pipe bottom from the slab)."""

    start: tuple[float, float, float]
    end: tuple[float, float, float]
    zone: Zone
    length: float


@dataclass(frozen=True)
class SewerRoute:
    """Fixture route to the riser (spec format, routes_json): pieces along the flow, the drop in the
    wall, the fittings of its own pipe (up to its tee)."""

    fixture: str
    d: int
    slope: float
    drop: tuple[float, float] | None  # drop in the wall, drain to floor pipe
    segments: tuple[RouteSegment, ...]
    fittings: tuple[str, ...]
    into: str  # riser or the pipe it tees into
    ok: bool


@dataclass(frozen=True)
class SewerError:
    """Why a fixture route is not acceptable: reason code and place on the plan (model mm)."""

    fixture: str
    reason: str  # screed_depth | screed_110 | hidden_height | drop | wc_far | unreachable
    at: Vec | None


@dataclass(frozen=True)
class Weak:
    """Network weak spot: for the "Plumbing" sheet and the report."""

    severity: Literal["error", "warning"]
    text: dict[str, str]  # ru, uk
    target: str  # fixture, pipe or riser id; "" means the whole network


@dataclass
class Network:
    outlets: list[Outlet] = field(default_factory=list)
    pipes: list[Pipe] = field(default_factory=list)
    collectors: list[Collector] = field(default_factory=list)
    risers: list[RiserNode] = field(default_factory=list)
    obstacles: dict[str, Polygon] = field(default_factory=dict)
    sewer: list[SewerCheck] = field(default_factory=list)
    routes: list[SewerRoute] = field(default_factory=list)
    sewer_errors: list[SewerError] = field(default_factory=list)
    sewer_direct: float = 0.0  # Ø50 consumption if every fixture goes to the riser alone, mm eq.
    hidden: dict[str, tuple[Polygon, float]] = field(default_factory=dict)  # hidden zones:
    # obstacle → place and highest pipe top from the finished floor
    weak: list[Weak] = field(default_factory=list)
    hot_source: str | None = None  # riser | boiler id | None means no hot water
    input_assumed: bool = False  # supply unit placed at the riser as an assumption
    free: BaseGeometry | None = None
    distribution: str = "collector"
    partitions: list[Polygon] = field(default_factory=list)  # partitions: a pass with a hole
    under: list[Polygon] = field(default_factory=list)  # plasterboard walls inside a room:
    # pipes go on the floor under them (laid before the wall), no hole
    doors: list[Polygon] = field(default_factory=list)  # door openings: pipes only as a last resort
    hollow: set[str] = field(default_factory=set)  # box obstacles (installation frame)
    rooms: BaseGeometry | None = None  # rooms and openings without partitions and obstacles:
    # the edges are walls (behind a bath, too)

    def holes(self, kinds: tuple[Kind, ...]) -> int:
        """Holes in partitions: pipes of these networks passing a partition close together (closer
        than
        HOLE_SHARE) share one hole."""
        spots: list[tuple[int, Vec]] = []
        for p in self.pipes:
            if p.kind not in kinds:
                continue
            line = LineString([v.as_tuple() for v in p.path])
            for k, strip in enumerate(self.partitions):
                cut = line.intersection(strip)
                if cut.is_empty or cut.length < 1.0:
                    continue
                c = cut.centroid
                at = Vec(c.x, c.y)
                if not any(j == k and (at - v).length() < HOLE_SHARE for j, v in spots):
                    spots.append((k, at))
        return len(spots)

    def by_fixture(self, fixture: str) -> list[Outlet]:
        return [o for o in self.outlets if o.fixture == fixture]

    def pipes_of(self, kind: Kind) -> list[Pipe]:
        return [p for p in self.pipes if p.kind == kind]


TEXT: dict[str, dict[str, str]] = {
    "unreachable": {
        "ru": "{f}: не проложить {k} — прибор отрезан стенами или препятствиями",
        "uk": "{f}: не прокласти {k} — прилад відрізаний стінами або перешкодами",
    },
    "no_hot": {
        "ru": "Нет источника горячей воды: ни стояка ГВС, ни бойлера — горячая не проложена",
        "uk": "Немає джерела гарячої води: ні стояка ГВП, ні бойлера — гаряча не прокладена",
    },
    "no_riser": {
        "ru": "Нет стояка канализации — выпуски приборов не проложены",
        "uk": "Немає стояка каналізації — випуски приладів не прокладені",
    },
    "unreachable_sewer": {
        "ru": "{f}: не проложить канализацию — нет пути без дверных проёмов, порогов жилых "
        "комнат и препятствий",
        "uk": "{f}: не прокласти каналізацію — немає шляху без дверних прорізів, порогів "
        "житлових кімнат і перешкод",
    },
    "screed_depth": {
        "ru": "{f}: Ø{d} не помещается в стяжку {s} мм — низ трубы {z} мм от плиты, нужно не "
        "выше {lim} (слой над трубой {c} мм); участок в «{room}», {L} м от стояка: короб, "
        "ниша или врезка ниже",
        "uk": "{f}: Ø{d} не вміщується в стяжку {s} мм — низ труби {z} мм від плити, треба не "
        "вище {lim} (шар над трубою {c} мм); ділянка в «{room}», {L} м від стояка: короб, "
        "ніша або врізка нижче",
    },
    "screed_110": {
        "ru": "{f}: Ø110 в стяжке нельзя — участок в «{room}», {L} м от стояка, вне короба, "
        "инсталляции или ванны: нужен короб",
        "uk": "{f}: Ø110 у стяжці не можна — ділянка в «{room}», {L} м від стояка, поза "
        "коробом, інсталяцією або ванною: потрібен короб",
    },
    "hidden_height": {
        "ru": "{f}: труба выше скрытой зоны ({zone}) — верх {z} мм от пола при {max} мм",
        "uk": "{f}: труба вище прихованої зони ({zone}) — верх {z} мм від підлоги при {max} мм",
    },
    "drop": {
        "ru": "{f}: не хватает перепада канализации — {L} м до стояка, при уклоне {i} нужно "
        "{d} мм, выпуск {h} мм над врезкой {r} мм: подиум {p} мм или ближе к стояку",
        "uk": "{f}: не вистачає перепаду каналізації — {L} м до стояка, при ухилі {i} треба "
        "{d} мм, випуск {h} мм над врізкою {r} мм: подіум {p} мм або ближче до стояка",
    },
    "surface": {
        "ru": "{f}: канализация {L} м — по стене над полом (в стяжку не помещается): короб у "
        "стены, верх трубы до {h} мм от пола",
        "uk": "{f}: каналізація {L} м — по стіні над підлогою (у стяжку не вміщується): короб "
        "біля стіни, верх труби до {h} мм від підлоги",
    },
    "wc_far": {
        "ru": "{f}: отвод унитаза {L} м по трубе — длиннее 1 м: унитаз ставят ближе всех к стояку",
        "uk": "{f}: відвід унітаза {L} м по трубі — довший за 1 м: унітаз ставлять найближче до "
        "стояка",
    },
    "turns": {
        "ru": "{f}: у канализации {n} отводов 45° — нужна ревизия для прочистки",
        "uk": "{f}: у каналізації {n} відводів 45° — потрібна ревізія для прочищення",
    },
    "door_water": {
        "ru": "{f}: {k} через дверной проём ({room}) — иначе не пройти; под порогом в стяжке "
        "или переложить",
        "uk": "{f}: {k} через дверний проріз ({room}) — інакше не пройти; під порогом у "
        "стяжці або перекласти",
    },
    "living": {
        "ru": "{f}: канализация идёт через жилую комнату «{room}»",
        "uk": "{f}: каналізація йде через житлову кімнату «{room}»",
    },
    "kind_cold": {"ru": "холодную воду", "uk": "холодну воду"},
    "kind_hot": {"ru": "горячую воду", "uk": "гарячу воду"},
    "kind_sewer": {"ru": "канализацию", "uk": "каналізацію"},
}


def drop_bends(rise: float) -> int:
    """45° bends on the drop in the wall from the drain to the floor pipe: a 90° turn is always
    two 45° bends. A drop of DROP_TURN or more goes down from the drain and onto the floor (4),
    less is an offset (2)."""
    if rise <= 0.5:
        return 0
    return 4 if rise >= DROP_TURN else 2


def text(key: str, language: Language, **values: object) -> str:
    return TEXT[key][language].format(**values)


def _weak(severity: Literal["error", "warning"], key: str, target: str, **values: object) -> Weak:
    """Weak spot in both languages; a dict value {ru, uk} has its own per language."""

    def on(lang: Language) -> dict[str, object]:
        return {k: v[lang] if isinstance(v, dict) else v for k, v in values.items()}

    langs: tuple[Language, ...] = ("ru", "uk")
    return Weak(severity, {lang: text(key, lang, **on(lang)) for lang in langs}, target)


def _m(mm: float) -> str:
    return f"{mm / 1000:.1f}".replace(".", ",")


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
class _Field:
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
    ) -> _Field:
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
class _Approach:
    """Approach to a node on a wall: the grid cell and the tail to the node (on the floor to the
    wall, then in the wall along it). along is how much runs in the wall."""

    cell: int
    tail: tuple[Vec, ...]  # from the cell centre to the node
    along: float


def _approaches(grid: Grid, seg: WallSegment, offset: float) -> list[_Approach]:
    """Free cells by wall seg (no farther than REACH from its face, facing it), from the ones
    nearest to the wall spot to the farthest."""
    out: list[tuple[float, _Approach]] = []
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
        out.append((along * ALONG_COST + depth, _Approach(k, tail, along)))
    out.sort(key=lambda x: x[0])
    return [a for _, a in out]


def _box_approaches(grid: Grid, poly: Polygon, node: Vec) -> list[_Approach]:
    """Approaches to a node inside a box (installation frame): free cells by the box on any side;
    from the cell to the box face and inside it to the node (in the box, as in a wall)."""
    out: list[tuple[float, _Approach]] = []
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
        out.append((along * ALONG_COST + (foot - c).length(), _Approach(k, (c, *inside), along)))
    out.sort(key=lambda x: x[0])
    return [a for _, a in out]


def _point_approach(grid: Grid, p: Vec, cell: int | None = None) -> _Approach:
    """Approach to a point off the wall (riser): a free cell (the nearest by default) and a 90°
    bend."""
    cell = grid.nearest_free(p) if cell is None else cell
    c = grid.center(cell)
    if abs(c.x - p.x) < 1e-6 or abs(c.y - p.y) < 1e-6:
        return _Approach(cell, (c, p), 0.0)
    return _Approach(cell, (c, Vec(c.x, p.y), p), 0.0)


def _best(field_: _Field, options: Sequence[_Approach]) -> _Approach | None:
    """Approach with the lowest cost: grid path plus a penalty for metres in the wall."""
    best: tuple[float, _Approach] | None = None
    for a in options:
        c = field_.cost(a.cell)
        if math.isinf(c):
            continue
        total = c + a.along * ALONG_COST
        if best is None or total < best[0]:
            best = (total, a)
    return best[1] if best is not None else None


# --- Network ---------------------------------------------------------------------


@dataclass
class _Ctx:
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

    def field(self, cell: int, prune: bool = True) -> _Field:
        return _Field.from_cell(self.grid, cell, self.ndirs, self.prune if prune else None)

    def name(self, fixture: str) -> dict[str, str]:
        """Fixture in words in both languages: "Мийка (Кухня)"."""
        fx = next((f for f in self.plumbing.fixtures if f.id == fixture), None)
        if fx is None:
            return {"ru": fixture, "uk": fixture}
        room = self.geoms[fx.room].room.name
        return {lang: f"{FIXTURE_NAMES[fx.type][lang]} ({room})" for lang in ("ru", "uk")}

    def unreachable(self, fixture: str, kind: Kind) -> None:
        if kind == "sewer":
            self.net.weak.append(_weak("error", "unreachable_sewer", fixture, f=self.name(fixture)))
            self.net.sewer_errors.append(SewerError(fixture, "unreachable", None))
            return
        self.net.weak.append(
            _weak("error", "unreachable", fixture, f=self.name(fixture), k=TEXT[f"kind_{kind}"])
        )

    def new_id(self, kind: str) -> str:
        self.counter[kind] = self.counter.get(kind, 0) + 1
        return f"{kind}_{self.counter[kind]}"

    def wall_approaches(self, room: str, wall: str, offset: float) -> list[_Approach]:
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


def fixture_outlets(fx: Fixture, geoms: dict[str, RoomGeometry]) -> list[Outlet]:
    """Fixture supplies on its wall: hot on the left, cold on the right, drain in the middle."""
    spec = fx.spec
    seg = geoms[fx.room].contour.segment(fx.wall)
    supply_h = fx.supply_height if fx.supply_height is not None else spec.supply_height
    supply_assumed = fx.supply_height is None
    pair = spec.cold and (spec.hot or spec.hot_source)
    out: list[Outlet] = []

    def add(kind: Kind, offset: float, height: float, d: int, assumed: bool) -> None:
        offset = min(max(offset, 0.0), seg.length)
        out.append(
            Outlet(
                fx.id,
                kind,
                fx.room,
                fx.wall,
                offset,
                height,
                seg.point_at(offset),
                seg.inward,
                d,
                assumed,
            )
        )

    half = HOT_COLD_GAP / 2 if pair else 0.0
    if spec.hot or spec.hot_source:
        add("hot", fx.offset - half, supply_h, SUPPLY_D, supply_assumed)
    if spec.cold:
        add("cold", fx.offset + half, supply_h, SUPPLY_D, supply_assumed)
    if spec.sewer is not None:
        assert spec.drain_height is not None
        drain = fx.drain_height if fx.drain_height is not None else spec.drain_height
        add("sewer", fx.offset, drain, spec.sewer, fx.drain_height is None)
    return out


def build_network(plan: Plan, contours: dict[str, Contour], plumbing: Plumbing) -> Network:
    """Network from plumbing.yaml: supplies, manifolds, water and sewer routes, checks."""
    geoms = {g.room.id: g for g in room_geometries(plan, contours)}
    net = Network(distribution=plumbing.distribution)
    for ob in plumbing.obstacles:
        net.obstacles[ob.id] = obstacle_polygon(ob, geoms[ob.room])
    free = free_area(list(geoms.values()))
    rooms_only = free  # no partitions: their faces are walls too, sewer runs along them
    net.doors = door_strips(list(geoms.values()))
    net.partitions = partition_strips(list(geoms.values()), net.doors)
    net.under = partition_strips(list(geoms.values()), net.doors, inner=True)
    if net.partitions or net.under:
        free = shapely.make_valid(shapely.unary_union([free, *net.partitions, *net.under]))
    if net.obstacles:
        free = shapely.make_valid(
            free.difference(shapely.unary_union(list(net.obstacles.values())))
        )
    net.free = free
    boxes = {ob.id: ob.type in HOLLOW for ob in plumbing.obstacles}
    net.hollow = {k for k, v in boxes.items() if v}
    grid = _grid(free, net)
    net.rooms = rooms_only
    for ob in plumbing.obstacles:
        if ob.type in HIDDEN_HEIGHT:
            h = ob.height if ob.height is not None else HIDDEN_HEIGHT[ob.type]
            net.hidden[ob.id] = (net.obstacles[ob.id], h)
    sewer_grids = tuple(_sewer_grid(list(geoms.values()), net, v) for v in SEWER_VARIANTS)
    ctx = _Ctx(plan, plumbing, geoms, grid, net, boxes, sewer_grids=sewer_grids)
    for r in plumbing.risers:
        inlet = r.sewer_inlet if r.sewer_inlet is not None else SEWER_INLET_MM
        net.risers.append(
            RiserNode(
                r.id, r.room, riser_center(r, geoms), r.sewer, r.water, inlet, r.sewer_inlet is None
            )
        )
    for fx in plumbing.fixtures:
        net.outlets += fixture_outlets(fx, geoms)
    _supply(ctx)
    _sewer(ctx)
    _check_doors(ctx)
    return net


def _grid(free: BaseGeometry, net: Network) -> Grid:
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


def _sewer_grid(
    geoms: Sequence[RoomGeometry], net: Network, costs: tuple[float, float, float, float]
) -> Grid:
    """Sewer grid: without door openings and openings of living rooms (thresholds are forbidden, no
    exceptions); the step cost is a per-cell multiplier (Grid.mult, costs: hidden zone (box,
    installation frame, under bath and tray); by the wall up to WALL_BAND_MM; up to
    NEAR_WALL_MM; farther) and the cell kind (Grid.tag) for height pruning in the search
    (_height_prune)."""
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
    grid = _grid(shapely.make_valid(area), net)
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


def _height_prune(
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


def supply_groups(fixtures: Sequence[Fixture]) -> dict[str, str]:
    """Fixture → the fixture it shares a manifold line with (the first in the group; a single one
    maps
    to itself): SHARED_PAIRS pairs of one room on one wall with neighbouring supplies no farther
    than SHARE_GAP (double vanity; dishwasher by the sink)."""
    out = {f.id: f.id for f in fixtures}
    shared = sorted(
        (f for f in fixtures if f.type in SHARED_TYPES), key=lambda f: (f.room, f.wall, f.offset)
    )
    for a, b in itertools.pairwise(shared):
        near = (a.room, a.wall) == (b.room, b.wall) and b.offset - a.offset <= SHARE_GAP
        if near and (a.type, b.type) in SHARED_PAIRS:
            out[b.id] = out[a.id]
    return out


def _input_place(ctx: _Ctx) -> tuple[str, str, float] | None:
    """Supply unit: from plumbing.yaml, or at the water riser (else the first riser) as an
    assumption.
    """
    inp = ctx.plumbing.input
    if inp is not None:
        return inp.room, inp.wall, inp.offset
    risers = sorted(ctx.net.risers, key=lambda r: not r.water)
    if not risers:
        return None
    r = risers[0]
    seg, t = nearest_wall(ctx.geoms[r.room], r.center)
    ctx.net.input_assumed = True
    return r.room, seg.id, t


def _hot_source(ctx: _Ctx) -> str | None:
    """Where hot water comes from: a riser (riser) or a boiler (fixture id); None if from
    nowhere.
    """
    inp = ctx.plumbing.input
    boiler = next((f.id for f in ctx.plumbing.fixtures if f.spec.hot_source), None)
    if inp is not None and inp.hot is not None:
        return "riser" if inp.hot else boiler
    return boiler if boiler is not None else ("riser" if ctx.net.risers else None)


def _supply(ctx: _Ctx) -> None:
    net = ctx.net
    users = {k: [o for o in net.outlets if o.kind == k] for k in ("cold", "hot")}
    if not users["cold"] and not users["hot"]:
        return
    place = _input_place(ctx)
    if place is None:
        return
    room, wall, offset = place
    seg = ctx.geoms[room].contour.segment(wall)
    inp = ctx.plumbing.input
    hot = _hot_source(ctx)
    net.hot_source = hot
    boiler_out = [o for o in users["hot"] if o.fixture == hot] if hot not in (None, "riser") else []
    hot_users = [o for o in users["hot"] if o.fixture != hot]
    if hot is None and hot_users:
        net.weak.append(_weak("warning", "no_hot", ""))
        hot_users = []
    tee = ctx.plumbing.distribution == "tee"
    water: tuple[tuple[Kind, float, list[Outlet]], ...] = (
        ("cold", COLLECTOR_GAP / 2, users["cold"]),
        ("hot", -COLLECTOR_GAP / 2, hot_users),
    )
    for kind, shift, outlets in water:
        if not outlets or (kind == "hot" and tee and boiler_out):
            continue  # hot main in the tee layout starts at the boiler
        c_room, c_wall, c_seg, c_at = room, wall, seg, offset + shift
        c_h = inp.height if inp is not None and inp.height is not None else COLLECTOR_HEIGHT
        far = boiler_out and (boiler_out[0].node - seg.point_at(offset)).length() > BOILER_NEAR
        if kind == "hot" and far:
            # Hot water from a boiler far from the unit: its manifold is at the boiler (change
            # 2026-11-02);
            # otherwise hot water would run from the boiler to the unit and back to fixtures by the
            # boiler
            b = boiler_out[0]
            c_room, c_wall = b.room, b.wall
            c_seg = ctx.geoms[b.room].contour.segment(b.wall)
            c_at = _clear_offset(ctx, c_seg, b.offset)
            c_h = COLLECTOR_HEIGHT
        at = min(max(c_at, 0.0), c_seg.length)
        col = Collector(
            f"collector_{kind}",
            kind,
            c_room,
            c_wall,
            at,
            c_seg.point_at(at),
            c_seg.inward,
            len(outlets),
            c_h,
        )
        net.collectors.append(col)
    collectors = {c.kind: c for c in net.collectors}
    # The boiler feeds hot water into the hot manifold (radial) or starts the main
    if boiler_out and "hot" in collectors and ctx.plumbing.distribution == "collector":
        _route_one(
            ctx,
            "hot",
            boiler_out[0].fixture,
            boiler_out[0],
            collectors["hot"].id,
            _target_node(collectors["hot"]),
            MAIN_D,
            target_id=collectors["hot"].id,
        )
    groups = supply_groups(ctx.plumbing.fixtures)
    with_hot = {o.fixture for o in users["hot"]}
    for kind, _, outlets in water:
        found = collectors.get(kind)
        if not tee and found is not None:
            by_group: dict[str, list[Outlet]] = {}
            for o in outlets:
                by_group.setdefault(groups.get(o.fixture, o.fixture), []).append(o)
            for members in by_group.values():  # groups come before parallel lines (_merge_parallel)
                # The line goes to the group fixture with hot water (cold goes to it paired with
                # hot), and of
                # those to the one nearest the manifold; the others are teed off it
                lead, *rest = sorted(
                    members,
                    key=lambda o: (o.fixture not in with_hot, (o.node - found.node).length()),
                )
                pipe = _radial(ctx, kind, found, lead)
                if rest and pipe is not None:
                    _route_tree(
                        ctx,
                        kind,
                        found.id,
                        _wall_node(found),
                        rest,
                        attach_to=[pipe.id],
                        main_d=SUPPLY_D,
                    )
            _merge_parallel(ctx, kind, found)
            for k, c in enumerate(net.collectors):
                lines = [p for p in net.pipes if p.source == c.id and p.parent is None]
                net.collectors[k] = replace(c, outputs=len(lines))
        elif tee and kind == "hot" and boiler_out:
            _route_tree(ctx, kind, boiler_out[0].fixture, boiler_out[0], outlets)
        elif tee and found is not None:
            _route_tree(ctx, kind, found.id, _wall_node(found), outlets)


def _subtree(pipes: Sequence[Pipe], root: Pipe) -> list[Pipe]:
    """A pipe and all branches off it (and off its branches)."""
    out, todo = [root], [root.id]
    while todo:
        pid = todo.pop()
        for p in pipes:
            if p.parent == pid:
                out.append(p)
                todo.append(p.id)
    return out


def _demand(ctx: _Ctx, pipes: Sequence[Pipe]) -> float:
    """Design flow of the fixtures on these pipes, l/s (FLOW)."""
    types = {f.id: f.type for f in ctx.plumbing.fixtures}
    return sum(FLOW.get(types[p.target], 0.1) for p in pipes if p.target in types)


def _pipe_d(flow: float) -> int | None:
    """Pipe Ø for the flow; None if even Ø20 cannot carry it."""
    return next((d for d in sorted(CAPACITY) if flow <= CAPACITY[d] + 1e-9), None)


def _alongside(a: Pipe, b: Pipe) -> float:
    """How many mm of path b on the floor run next to a (closer than PARALLEL_GAP)."""
    if len(a.path) < 2 or len(b.path) < 2:
        return 0.0
    near = LineString([v.as_tuple() for v in a.path]).buffer(PARALLEL_GAP)
    return float(LineString([v.as_tuple() for v in b.path]).intersection(near).length)


def _merge_parallel(ctx: _Ctx, kind: Kind, col: Collector) -> None:
    """Parallel lines (change 2026-11-02): a branch from the manifold is moved onto another branch
    with a tee if it runs alongside it for more than PARALLEL_MIN and the network water gets
    shorter, or if the tee saves at least BRANCH_SAVING; the shared pipe must carry the flow
    (FLOW, CAPACITY: Ø16, else Ø20; no larger). The boiler line stays separate: it heats water
    for the whole flat. Pairs with the longest shared piece go first; repeat while something can
    be merged."""
    net = ctx.net
    rejected: set[tuple[str, str]] = set()
    boilers = {f.id for f in ctx.plumbing.fixtures if f.spec.hot_source}
    while True:
        water = [p for p in net.pipes if p.kind == kind]
        roots = [
            p for p in water if p.source == col.id and p.parent is None and p.target not in boilers
        ]
        pairs = sorted(
            (
                (_alongside(a, b), a, b)
                for a in roots
                for b in roots
                if a is not b and (a.target, b.target) not in rejected
            ),
            key=lambda x: -x[0],
        )
        if not pairs:
            return
        along, a, b = pairs[0]
        moved = _subtree(water, b)
        d = _pipe_d(_demand(ctx, _subtree(water, a)) + _demand(ctx, moved))
        saving = 1.0 if along >= PARALLEL_MIN else BRANCH_SAVING
        if d is None or not _rehang(ctx, kind, col, a, moved, d, saving):
            rejected.add((a.target, b.target))


def _rehang(
    ctx: _Ctx, kind: Kind, col: Collector, a: Pipe, moved: list[Pipe], d: int, saving: float
) -> bool:
    """Re-hang the moved pipes (a branch and its sub-branches) onto pipe a with a tee; a is Ø d.
    If the network water gets shorter by less than saving mm, or the branch finds no spot on a,
    put things back (False)."""
    net = ctx.net
    before = list(net.pipes)
    old = sum(p.total for p in net.pipes if p.kind == kind)
    gone = {p.id for p in moved}
    outlets = [o for p in moved for o in net.outlets if o.fixture == p.target and o.kind == kind]
    net.pipes = [p for p in net.pipes if p.id not in gone]
    k = net.pipes.index(a)
    net.pipes[k] = replace(a, d=d)
    _route_tree(ctx, kind, col.id, _wall_node(col), outlets, attach_to=[a.id], main_d=d)
    new = [p for p in net.pipes if p.kind == kind]
    hung = all(p.parent is not None for p in new if p.target in {o.fixture for o in outlets})
    if hung and sum(p.total for p in new) <= old - saving:
        return True
    net.pipes = before
    return False


def _radial(ctx: _Ctx, kind: Kind, col: Collector, o: Outlet) -> Pipe | None:
    """Branch from the manifold to a water outlet; hot goes paired with cold if cold is already
    there.
    """
    net = ctx.net
    cold = next((p for p in net.pipes if p.kind == "cold" and p.target == o.fixture), None)
    if kind == "hot" and cold is not None and cold.parent is None and _pair(ctx, cold, col, o):
        return net.pipes[-1]
    return _route_one(ctx, kind, col.id, _wall_node(col), o.fixture, o, SUPPLY_D)


def _clear_offset(ctx: _Ctx, seg: WallSegment, offset: float) -> float:
    """Wall spot closest to offset where the manifold (COLLECTOR_HALF each way) is not behind an
    obstacle: under a boiler above an installation frame the manifold cannot go, so next to it."""
    obstacles = list(ctx.net.obstacles.values())
    if not obstacles:
        return offset
    blocked = shapely.unary_union(obstacles).buffer(1.0)

    def clear(t: float) -> bool:
        a, b = seg.point_at(t - COLLECTOR_HALF), seg.point_at(t + COLLECTOR_HALF)
        return not blocked.intersects(LineString([a.as_tuple(), b.as_tuple()]))

    lo, hi = COLLECTOR_HALF, seg.length - COLLECTOR_HALF
    for k in range(int(seg.length // 50) + 1):
        for t in (offset - 50 * k, offset + 50 * k):
            if lo <= t <= hi and clear(t):
                return t
    return offset


def parallel(path: Sequence[Vec], gap: float) -> list[Vec]:
    """Orthogonal polyline shifted left along its direction by gap (right if gap < 0)."""
    pts = simplify(path)
    if len(pts) < 2:
        return list(pts)

    def normal(i: int) -> Vec:
        d = pts[i + 1] - pts[i]
        u = d * (1 / d.length())
        return Vec(-u.y, u.x)

    out = [pts[0] + normal(0) * gap]
    for i in range(1, len(pts) - 1):
        a, b = normal(i - 1), normal(i)
        same = abs(a.x - b.x) < 1e-9 and abs(a.y - b.y) < 1e-9
        out.append(pts[i] + a * gap if same else pts[i] + (a + b) * gap)
    out.append(pts[-1] + normal(len(pts) - 2) * gap)
    return out


def _pair(ctx: _Ctx, cold: Pipe, col: Collector, o: Outlet) -> bool:
    """Hot water to a fixture goes paired with cold: the same route, shifted by PAIR_GAP to the side
    where it is free; the ends go to the hot manifold and the water outlet. No room on either
    side gives False (hot water is routed on its own)."""
    free = ctx.net.free
    if free is None or len(cold.path) < 3:
        return False
    inside = free.buffer(CLEARANCE - 1.0)
    best: list[Vec] | None = None
    for gap in (PAIR_GAP, -PAIR_GAP):
        shifted = parallel(cold.path, gap)
        if len(shifted) < 2:
            continue
        path = fit_path(shifted, col.node, o.node)
        floor = path[1:-1]
        if len(floor) >= 2 and not inside.covers(LineString([v.as_tuple() for v in floor])):
            continue
        if best is None or _plan_length(path) < _plan_length(best):
            best = path
    if best is None:
        return False
    along = cold.wall_run
    pipe = Pipe(
        ctx.new_id("hot"),
        "hot",
        col.id,
        o.fixture,
        tuple(best),
        SUPPLY_D,
        rise=o.height + col.height,
        wall_run=along,
        room=o.room,
    )
    ctx.net.pipes.append(pipe)
    return True


def _plan_length(path: Sequence[Vec]) -> float:
    return sum((b - a).length() for a, b in itertools.pairwise(path))


@dataclass(frozen=True)
class _Node:
    """Node on a wall: route source or target."""

    room: str
    wall: str
    offset: float
    node: Vec
    height: float


def _wall_node(c: Collector) -> _Node:
    return _Node(c.room, c.wall, c.offset, c.node, c.height)


def _target_node(c: Collector) -> Outlet:
    return Outlet(c.id, c.kind, c.room, c.wall, c.offset, c.height, c.node, c.inward, MAIN_D, False)


def _start(ctx: _Ctx, src: _Node | Outlet) -> tuple[_Field, _Approach] | None:
    options = ctx.wall_approaches(src.room, src.wall, src.offset)
    if not options:
        return None
    a = options[0]
    return _Field.from_cell(ctx.grid, a.cell), a


def _route_one(
    ctx: _Ctx,
    kind: Kind,
    source: str,
    src: _Node | Outlet,
    target: str,
    dst: Outlet,
    d: int,
    target_id: str | None = None,
) -> Pipe | None:
    """Pipe from node src to supply dst: on the floor from wall to wall, the tails in the wall."""
    started = _start(ctx, src)
    approach = None
    if started is not None:
        fld, head = started
        approach = _best(fld, ctx.wall_approaches(dst.room, dst.wall, dst.offset))
    if started is None or approach is None:
        ctx.unreachable(target, kind)
        return None
    fld, head = started
    middle = fld.path(approach.cell)
    path = simplify([*reversed(head.tail), *middle, *approach.tail[1:]])
    pipe = Pipe(
        ctx.new_id(kind),
        kind,
        source,
        target_id or target,
        tuple(path),
        d,
        rise=dst.height + src.height,
        wall_run=approach.along + head.along,
        room=dst.room,
    )
    ctx.net.pipes.append(pipe)
    _open_holes(ctx, pipe)
    return pipe


def _open_holes(ctx: _Ctx, pipe: Pipe) -> None:
    """A hole in a partition already used by a water pipe is free (no PARTITION_COST) for the next
    water pipes: they go as a bundle through the same hole instead of making their own (change
    2026-11-02: the washing machine pipe went through the living room instead of through the
    bathroom with the rest)."""
    net, grid = ctx.net, ctx.grid
    if pipe.kind == "sewer" or not net.partitions or grid.penalty is None:
        return
    line = LineString([v.as_tuple() for v in pipe.path])
    for strip in net.partitions:
        cut = line.intersection(strip)
        if cut.is_empty or cut.length < 1.0:
            continue
        near = cut.buffer(max(HOLE_SHARE / 2, CLEARANCE))
        shapely.prepare(near)
        for k, cost in list(grid.penalty.items()):
            if cost == PARTITION_COST and near.contains(shapely.Point(grid.center(k).as_tuple())):
                grid.penalty[k] = 0.0


def _tree_points(pipe: Pipe) -> list[tuple[Vec, float]]:
    """Spots along a floor pipe where a branch can tee in (without the wall tails): point and mm
    from the start.
    """
    out: list[tuple[Vec, float]] = []
    acc = 0.0
    floor = pipe.path[1:-1] if len(pipe.path) > 2 else pipe.path
    pts = list(pipe.path)
    for a, b in itertools.pairwise(pts):
        seg_len = (b - a).length()
        if a in floor and b in floor and seg_len > 1e-6:
            n = max(1, int(seg_len // STEP))
            for k in range(n + 1):
                out.append((a + (b - a) * (k / n), acc + seg_len * k / n))
        acc += seg_len
    return out


def _riser_heads(grid: Grid, center: Vec, rooms: BaseGeometry | None = None) -> list[_Approach]:
    """Approaches to a riser from four sides: a riser in a wall projection or in a box is reached
    from the fixture's side (the nearest free cell on each axis). Inside a wall (outside rooms) at
    most RISER_WALL: a pipe does not run along the inside of a wall."""
    out: list[_Approach] = []
    inside = rooms.buffer(1.0) if rooms is not None else None
    seen: set[int] = set()
    reach = int(RISER_REACH // STEP) + 1
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        for k in range(reach + 1):
            p = Vec(center.x + dx * k * STEP, center.y + dy * k * STEP)
            ix = round((p.x - grid.x0) / STEP)
            iy = round((p.y - grid.y0) / STEP)
            if not (0 <= ix < grid.nx and 0 <= iy < grid.ny):
                break
            cell = iy * grid.nx + ix
            if grid.free[cell]:
                head = _point_approach(grid, center, cell)
                tail = LineString([v.as_tuple() for v in head.tail])
                in_wall = tail.difference(inside).length if inside is not None else 0.0
                if cell not in seen and in_wall <= RISER_WALL:
                    seen.add(cell)
                    out.append(head)
                break
    if not out:
        out.append(_point_approach(grid, center))
    return out


def _heads(ctx: _Ctx, src: _Node | Outlet | RiserNode) -> list[_Approach]:
    if isinstance(src, RiserNode):
        return _riser_heads(ctx.grid, src.center, ctx.net.rooms)
    options = ctx.wall_approaches(src.room, src.wall, src.offset)
    return options[:1]


def _root(pipes: dict[str, Pipe], p: Pipe) -> str:
    while p.parent is not None:
        p = pipes[p.parent]
    return p.source


def _route_tree(
    ctx: _Ctx,
    kind: Kind,
    source: str,
    src: _Node | Outlet | RiserNode,
    outlets: Sequence[Outlet],
    only_into: int | None = None,
    attach_to: Sequence[str] | None = None,
    main_d: int = MAIN_D,
) -> None:
    """Tree from a source: fixtures by cost from the source; each is a branch off the nearest spot
    of
    the pipes already laid (or off the source). only_into restricts branches to pipes of this
    diameter (a Ø110 WC only into Ø110 or the riser); attach_to restricts branches to these pipes
    (a group's shared line from the manifold); main_d is the Ø of a pipe with branches (water:
    the tee layout main is Ø20, the shared basin line Ø16)."""
    heads = _heads(ctx, src)
    if not heads:
        for o in outlets:
            ctx.unreachable(o.fixture, kind)
        return
    fields = [ctx.field(h.cell) for h in heads]
    if ctx.prune is not None:  # fallback: no pruning, else unreachable
        fields += [replace(ctx.field(h.cell, prune=False), offset=FALLBACK_COST) for h in heads]
    lift = src.height if not isinstance(src, RiserNode) else 0.0

    def reach(o: Outlet) -> float:
        options = ctx.wall_approaches(o.room, o.wall, o.offset)
        best = math.inf
        for fld in fields:
            a = _best(fld, options)
            if a is not None:
                best = min(best, fld.cost(a.cell) + a.along * ALONG_COST)
        return best

    order = sorted(outlets, key=reach)
    by_id = {p.id: p for p in ctx.net.pipes if p.kind == kind}
    if attach_to is not None:
        tree = [by_id[i] for i in attach_to if i in by_id]
    else:
        tree = [p for p in by_id.values() if _root(by_id, p) == source]
    for o in order:
        if math.isinf(reach(o)):
            ctx.unreachable(o.fixture, kind)
            continue
        options = ctx.wall_approaches(o.room, o.wall, o.offset)
        here = min(
            (a for fld in fields if (a := _best(fld, options)) is not None),
            key=lambda a: min(f.cost(a.cell) for f in fields) + a.along * ALONG_COST,
        )
        # Search from the fixture: to the source and to each tee spot on pipes already laid
        back = ctx.field(here.cell)
        if all(math.isinf(back.cost(h.cell)) for h in heads):
            back = ctx.field(here.cell, prune=False)
        head = min(heads, key=lambda h: back.cost(h.cell))
        best_cost = back.cost(head.cell)
        best: tuple[Pipe, Vec, float] | None = None
        for p in tree:
            if only_into is not None and p.d != only_into:
                continue
            for at, along in _tree_points(p):
                c = back.cost(ctx.grid.nearest_free(at))
                if c < best_cost - 1e-6:
                    best_cost, best = c, (p, at, along)
        d = o.d if kind == "sewer" else SUPPLY_D
        if best is None:
            middle = list(reversed(back.path(head.cell)))
            path = simplify([*reversed(head.tail), *middle, *here.tail[1:]])
            if kind == "sewer":
                path, _ = _shape45(path)
            pipe = Pipe(
                ctx.new_id(kind),
                kind,
                source,
                o.fixture,
                tuple(path),
                d,
                o.height + lift,
                here.along + head.along,
                room=o.room,
            )
        else:
            parent, at, along = best
            cell = ctx.grid.nearest_free(at)
            middle = list(reversed(back.path(cell)))
            path = simplify([at, *middle, *here.tail[1:]])
            if kind == "sewer":
                path, along = _shape45(path, parent, along)
            pipe = Pipe(
                ctx.new_id(kind),
                kind,
                parent.id,
                o.fixture,
                tuple(path),
                d,
                o.height,
                here.along,
                parent=parent.id,
                attach=along,
                room=o.room,
            )
            if kind != "sewer" and parent.d < main_d:  # with a branch: a Ø20 main
                k = ctx.net.pipes.index(parent)
                ctx.net.pipes[k] = replace(parent, d=main_d)
                tree[tree.index(parent)] = ctx.net.pipes[k]
        ctx.net.pipes.append(pipe)
        _open_holes(ctx, pipe)
        tree.append(pipe)


def _shape45(
    path: Sequence[Vec], parent: Pipe | None = None, along: float = 0.0
) -> tuple[list[Vec], float]:
    """Sewer on the plan with 45° bends only: pieces in eight directions, the tee into pipe parent
    is an angled tee (the tee spot along moves towards the riser), corners use bends."""
    pts = b45.octilinear(path)
    if parent is not None:
        pts, along = b45.tee45(pts, parent.path, along)
    return b45.chamfer(pts), along


DEPTH_ERRORS = frozenset({"screed_depth", "screed_110", "hidden_height"})


def _sewer(ctx: _Ctx) -> None:
    """Sewer in variants (SEWER_VARIANTS): normal, through hidden zones, only along walls; the
    variant with the lowest _score wins (routing spec, item 6)."""
    net = ctx.net
    if not any(o.kind == "sewer" for o in net.outlets):
        return
    water = ctx.grid
    mark = (len(net.pipes), len(net.weak), dict(ctx.counter))
    ctx.ndirs, ctx.boxes_open = 8, True
    try:
        best: tuple[SewerScore, int] | None = None
        for k, grid in enumerate(ctx.sewer_grids):
            _rollback(ctx, mark)
            ctx.grid = grid
            _sewer_trees(ctx)
            score = _score(net)
            if best is None or score < best[0]:
                best = (score, k)
            if score[:4] == (0, 0, 0.0, 0.0):
                break  # no errors, no podium, no box, no room middle
        if best is not None and best[1] != k:
            _rollback(ctx, mark)
            ctx.grid = ctx.sewer_grids[best[1]]
            _sewer_trees(ctx)
    finally:
        ctx.grid, ctx.ndirs, ctx.boxes_open, ctx.prune = water, 4, False, None


SewerScore = tuple[int, int, float, float, float]


def _score(net: Network) -> SewerScore:
    """Sewer variant score, compared in order: screed and hidden zone errors, podiums (not enough
    drop), mm of box above the floor, mm in the middle of a room (farther than WALL_BAND_MM from
    walls outside hidden zones), mm of pipe plus bends at TURN_COST_MM."""
    sewer = net.pipes_of("sewer")
    fittings = sum(f == "bend45" for r in net.routes for f in r.fittings)
    return (
        sum(1 for e in net.sewer_errors if e.reason in DEPTH_ERRORS),
        sum(1 for e in net.sewer_errors if e.reason in ("drop", "unreachable")),
        round(sum(p.surface_length for p in sewer), 1),
        round(sum(p.open_length for p in sewer), 1),
        round(sum(p.total for p in sewer) + fittings * TURN_COST_MM, 1),
    )


def _rollback(ctx: _Ctx, mark: tuple[int, int, dict[str, int]]) -> None:
    pipes, weak, counter = mark
    net = ctx.net
    del net.pipes[pipes:]
    del net.weak[weak:]
    net.sewer.clear()
    net.routes.clear()
    net.sewer_errors.clear()
    net.sewer_direct = 0.0
    ctx.counter = dict(counter)


def _sewer_trees(ctx: _Ctx) -> None:
    net = ctx.net
    drains = [o for o in net.outlets if o.kind == "sewer"]
    risers = [r for r in net.risers if r.sewer]
    if not risers:
        net.weak.append(_weak("error", "no_riser", ""))
        return
    # A fixture goes to the riser with the shorter path; each riser has its own tree
    fields = {r.id: [f for _, f in _riser_fields(ctx, r, 50)] for r in risers}

    def cost(r: RiserNode, o: Outlet) -> float:
        options = ctx.wall_approaches(o.room, o.wall, o.offset)
        out = math.inf
        for fld in fields[r.id]:
            a = _best(fld, options)
            if a is not None:
                out = min(out, fld.cost(a.cell))
        return out

    by_riser: dict[str, list[Outlet]] = {r.id: [] for r in risers}
    for o in drains:
        r = min(risers, key=lambda r: (cost(r, o), (r.center - o.node).length()))
        by_riser[r.id].append(o)
    for r in risers:
        mine = by_riser[r.id]
        if not mine:
            continue
        wc = [o for o in mine if o.d >= 110]
        rest = [o for o in mine if o.d < 110]
        # Ø110 never fits in the screed: the room middle is closed at any length
        ctx.prune = _height_prune(ctx.grid, _riser_invert(r), SLOPE_MIN[110], 110)
        _route_tree(ctx, "sewer", r.id, r, wc, only_into=110)
        ctx.prune = None
        _merge_drains(ctx, r, rest)
    _sewer_heights(ctx)


def _riser_invert(r: RiserNode) -> float:
    """Pipe bottom at the riser inlet, mm from the slab: inlet axis from the finished floor plus the
    screed minus the radius of the Ø110 tee (a Ø50 pipe goes through a reducer, bottom flush with
    the tee). Sewer heights are always the pipe bottom; axis ↔ bottom conversion happens here and
    in _outlet_invert."""
    return SCREED_MM + r.inlet - RISER_TEE_D / 2


def _outlet_invert(o: Outlet) -> float:
    """Fixture drain bottom, mm from the slab: axis from the finished floor plus the screed minus
    the radius.
    """
    return SCREED_MM + o.height - o.d / 2


def _riser_fields(ctx: _Ctx, r: RiserNode, d: int) -> list[tuple[_Approach, _Field]]:
    """Search from the riser on each side: with height pruning for Ø d (the flattest slope allowed
    for it) and a fallback without pruning, FALLBACK_COST dearer, for a fixture that is otherwise
    unreachable (_evaluate will find the screed error)."""
    out: list[tuple[_Approach, _Field]] = []
    heads = _riser_heads(ctx.grid, r.center, ctx.net.rooms)
    prune = _height_prune(ctx.grid, _riser_invert(r), SLOPE_MIN[_norm(d)], d)
    for h in heads:
        tail = _plan_length(h.tail)
        out.append((h, _Field.from_cell(ctx.grid, h.cell, 8, prune, tail)))
    for h in heads:
        out.append((h, _Field.from_cell(ctx.grid, h.cell, 8, offset=FALLBACK_COST)))
    return out


@dataclass
class _Merge:
    """Node of the Ø50 sewer tree: a fixture (leaf) or a tee J over two nodes. Each fixture of the
    node has the pipe length from its approach spot to the node cell (for heights)."""

    cell: int
    fld: _Field
    cost: np.ndarray  # path cost from the node to every grid cell
    members: list[Outlet]
    length: dict[str, float]
    leaf: Outlet | None = None
    approach: _Approach | None = None
    children: tuple[_Merge, _Merge] | None = None


def _cost_array(fld: _Field) -> np.ndarray:
    out = np.full(fld.grid.nx * fld.grid.ny, math.inf)
    for state, d in fld.dist.items():
        cell = state // fld.ndirs
        if d < out[cell]:
            out[cell] = d
    return out + fld.offset


def _node(ctx: _Ctx, cell: int, members: list[Outlet], length: dict[str, float]) -> _Merge:
    fld = ctx.field(cell)
    return _Merge(cell, fld, _cost_array(fld), members, length)


def _between(a: _Merge, cell: int) -> list[Vec]:
    """Grid path from cell to node a (backwards along the flow)."""
    if cell == a.cell:
        return [a.fld.grid.center(cell)]
    return list(reversed(a.fld.path(cell)))


def _merge_drains(ctx: _Ctx, r: RiserNode, outlets: Sequence[Outlet]) -> None:
    """Ø50 fixtures joined to riser r as a tree with the least pipe consumption ("tees" spec): for
    each pair of nodes (A, B), the tee spot J with the lowest cost d(A, J) + d(B, J) + k·d(J, R)
    (d is a grid path with 45° bends, a bend costs SEWER_BEND_COST, k is the main's PIPE_WEIGHT);
    the pair saving is d(A, R) + d(B, R) − cost. Pairs are merged in order of decreasing saving,
    J becomes a new node; a tee is not allowed if a fixture that fitted the screed or the drop on
    its own stops fitting with it (then the next spot by cost is tried), or if the branch to the
    tee runs through the middle of a room above the screed (length is the full path fixture →
    tee → riser). The search from the riser uses height pruning (_height_prune), the search from
    fixtures a lower length bound. A node closer to the Ø110 (WC) pipe than to the riser tees into
    it with a 110×50 tee. Alignment and the 45° entry are handled when the pipe is assembled
    (_shape45)."""
    if not outlets:
        return
    grid = ctx.grid
    pairs = _riser_fields(ctx, r, 50)
    heads = [h for h, _ in pairs]
    hfields = [f for _, f in pairs]
    rcost = np.minimum.reduce([_cost_array(f) for f in hfields])
    z0 = _riser_invert(r)
    slope = SLOPE_MIN[50]
    limit = SCREED_MM - 50 - SCREED_COVER
    tags = grid.tag
    # Branches from fixtures: the length to the riser is unknown, use a straight-line lower bound
    ctx.prune = _height_prune(grid, z0, slope, 50, lower=r.center)

    def to_riser(cell: int) -> tuple[list[Vec], float]:
        """From the riser to the cell: the tail to the riser and the grid path."""
        k = min(range(len(heads)), key=lambda i: hfields[i].cost(cell))
        path = [*reversed(heads[k].tail), *hfields[k].path(cell)[1:]]
        return path, _plan_length(path) - heads[k].along

    nodes: list[_Merge] = []
    direct: dict[str, float] = {}  # mm along the pipe from the fixture approach spot to the riser
    for o in outlets:
        options = ctx.wall_approaches(o.room, o.wall, o.offset)
        found = [x for f in hfields if (x := _best(f, options)) is not None]
        here = min(found, key=lambda x: float(rcost[x.cell]) + x.along * ALONG_COST, default=None)
        if here is None or math.isinf(rcost[here.cell]):
            ctx.unreachable(o.fixture, "sewer")
            continue
        node = _node(ctx, here.cell, [o], {o.fixture: 0.0})
        node.leaf, node.approach = o, here
        nodes.append(node)
        direct[o.fixture] = to_riser(here.cell)[1]
        path = simplify([*to_riser(here.cell)[0], *here.tail[1:]])
        shaped, _ = _shape45(path)
        ctx.net.sewer_direct += _equivalent(shaped, 50)

    def leg_ok(leg: Sequence[Vec], s0: float) -> bool:
        """Branch from the tee (leg[0]) to the node: in the room middle the pipe bottom plus Ø and
        the
        cover must not exceed the screed; s0 is mm along the pipe from the riser to the tee."""
        if tags is None:
            return True
        s = s0
        for a, b in itertools.pairwise(leg):
            s += (b - a).length()
            c = grid.nearest_free(b)
            if tags[c] in (TAG_NEAR, TAG_OPEN) and z0 + s * slope > limit + 0.5:
                return False
        return True

    def admissible(na: _Merge, nb: _Merge, cell: int) -> bool:
        tail = to_riser(cell)[1]
        legs = {id(n): _between(n, cell) for n in (na, nb)}
        for n in (na, nb):
            leg = legs[id(n)]  # from the tee to the node
            if not leg_ok(leg, tail):
                return False
            for o in n.members:
                zd = z0 + direct[o.fixture] * slope
                zv = z0 + (n.length[o.fixture] + _plan_length(leg) + tail) * slope
                zout = _outlet_invert(o)
                if (zd <= limit + 0.5 < zv) or (zd <= zout + 0.5 < zv):
                    return False
        return True

    k = PIPE_WEIGHT[50]
    while len(nodes) > 1:
        best: tuple[float, int, int, int] | None = None  # saving, A, B, J
        for i, j in itertools.combinations(range(len(nodes)), 2):
            na, nb = nodes[i], nodes[j]
            total = na.cost + nb.cost + k * rcost
            gain = float(rcost[na.cell] + rcost[nb.cell])
            order = np.argsort(total, kind="stable")[:TEE_CANDIDATES]
            for cell in (int(c) for c in order):
                saving = gain - float(total[cell])
                if not math.isfinite(saving) or saving <= 1e-6:
                    break
                if best is not None and saving <= best[0] + 1e-6:
                    break
                if admissible(na, nb, cell):
                    best = (saving, i, j, cell)
                    break
        if best is None:
            break
        _, i, j, cell = best
        a, b = nodes[i], nodes[j]
        length = {
            o.fixture: a.length[o.fixture] + _plan_length(_between(a, cell)) for o in a.members
        }
        length |= {
            o.fixture: b.length[o.fixture] + _plan_length(_between(b, cell)) for o in b.members
        }
        joint = _node(ctx, cell, [*a.members, *b.members], length)
        joint.children = (a, b)
        nodes = [n for n in nodes if n is not a and n is not b] + [joint]
    ctx.prune = None
    sewer = {p.id: p for p in ctx.net.pipes if p.kind == "sewer"}
    big = [p for p in sewer.values() if p.d >= 100 and _root(sewer, p) == r.id]
    for n in nodes:
        into = _into_110(ctx, n, big, float(rcost[n.cell]), leg_ok)
        if into is not None:
            parent, at, along = into
            _emit(ctx, r, n, [at, *_between(n, ctx.grid.nearest_free(at))], parent, along)
            continue
        path = to_riser(n.cell)[0]
        k_head = min(range(len(heads)), key=lambda i: hfields[i].cost(n.cell))
        _emit(ctx, r, n, path, None, heads[k_head].along)


def _into_110(
    ctx: _Ctx,
    n: _Merge,
    big: Sequence[Pipe],
    to_riser: float,
    leg_ok: Callable[[Sequence[Vec], float], bool],
) -> tuple[Pipe, Vec, float] | None:
    """Tee spot of a Ø50 node into a Ø110 pipe with a 110×50 tee (routing spec, item 4), if that is
    cheaper than its own path to the riser and the branch does not run in the room middle above
    the screed."""
    best: tuple[float, Pipe, Vec, float] | None = None
    for p in big:
        for at, along in _tree_points(p):
            c = n.fld.cost(ctx.grid.nearest_free(at))
            if c >= to_riser - 1e-6 or (best is not None and c >= best[0]):
                continue
            leg = _between(n, ctx.grid.nearest_free(at))  # from the tee to the node
            if leg_ok([at, *leg], along):
                best = (c, p, at, along)
    return (best[1], best[2], best[3]) if best is not None else None


def _emit(
    ctx: _Ctx, r: RiserNode, node: _Merge, prefix: list[Vec], parent: Pipe | None, along: float
) -> None:
    """Pipes from the tree: from the start (riser or a spot on the parent pipe) along the "aligned"
    branch of each tee to a fixture is one pipe; the other branches are branches off it."""
    pts = list(prefix)
    branches: list[tuple[_Merge, int]] = []
    cur = node
    while cur.children is not None:
        incoming = ctx.grid.center(cur.cell) - pts[-2] if len(pts) >= 2 else None
        main, other = sorted(
            cur.children, key=lambda c: _straightness(c, cur.cell, incoming), reverse=True
        )
        branches.append((other, cur.cell))
        pts += _between(main, cur.cell)[1:]
        cur = main
    assert cur.leaf is not None and cur.approach is not None
    o, here_a = cur.leaf, cur.approach
    path = simplify([*pts, *here_a.tail[1:]])
    if parent is None:
        path, _ = _shape45(path)
        pipe = Pipe(
            ctx.new_id("sewer"),
            "sewer",
            r.id,
            o.fixture,
            tuple(path),
            o.d,
            o.height,
            here_a.along + along,
            room=o.room,
        )
    else:
        path, attach = _shape45(path, parent, along)
        pipe = Pipe(
            ctx.new_id("sewer"),
            "sewer",
            parent.id,
            o.fixture,
            tuple(path),
            o.d,
            o.height,
            here_a.along,
            parent=parent.id,
            attach=attach,
            room=o.room,
        )
    ctx.net.pipes.append(pipe)
    line = LineString([v.as_tuple() for v in pipe.path])
    for other, cell in branches:
        c = ctx.grid.center(cell)
        at = line.project(shapely.Point(c.as_tuple()))
        hit = line.interpolate(at)
        start = Vec(hit.x, hit.y)
        _emit(ctx, r, other, [start, *_between(other, cell)], pipe, at)


def _straightness(child: _Merge, cell: int, incoming: Vec | None) -> float:
    """How much the branch to child from the tee at cell continues the main: the cosine of the angle
    (1 means aligned); a zero-length branch (fixture at the tee) is a side branch."""
    path = _between(child, cell)
    if len(path) < 2 or incoming is None or incoming.length() < 1e-6:
        return -2.0
    d = path[1] - path[0]
    return d.dot(incoming) / (d.length() * incoming.length())


def _equivalent(path: Sequence[Vec], d: int) -> float:
    """Pipe consumption in mm of equivalent length: weight per metre by diameter plus 45° bends."""
    return PIPE_WEIGHT[_norm(d)] * _plan_length(path) + SEWER_BEND_COST * b45.bends(path)


def _check_doors(ctx: _Ctx) -> None:
    """Water through a door opening is a weak spot (sewer through a door is impossible: its grid has
    no door openings)."""
    net = ctx.net
    names = {g.room.id: g.room.name for g in ctx.geoms.values()}
    seen: set[tuple[str, str, str]] = set()
    for p in net.pipes:
        if p.kind == "sewer" or not net.doors:
            continue
        line = LineString([v.as_tuple() for v in p.path])
        for g in ctx.geoms.values():
            for op in g.room.openings:
                if op.type is not OpeningType.DOOR:
                    continue
                if line.intersection(opening_strip(g, op)).length < 1.0:
                    continue
                key = (p.target, p.kind, op.id)
                if key in seen:
                    continue
                seen.add(key)
                net.weak.append(
                    _weak(
                        "warning",
                        "door_water",
                        p.target,
                        f=ctx.name(p.target),
                        k=TEXT[f"kind_{p.kind}"],
                        room=names[g.room.id],
                    )
                )


HIDDEN_NAMES: dict[ObstacleType, dict[str, str]] = {
    ObstacleType.INSTALLATION: {"ru": "инсталляция", "uk": "інсталяція"},
    ObstacleType.BOX: {"ru": "короб", "uk": "короб"},
    ObstacleType.BATH: {"ru": "под ванной", "uk": "під ванною"},
    ObstacleType.SHOWER_TRAY: {"ru": "под поддоном", "uk": "під піддоном"},
}
SAMPLE = 25.0  # mm: step for splitting a route piece into zones


@dataclass(frozen=True)
class _Zones:
    """Where a sewer route point lies: a hidden zone, the screed (floor) or a wall; on the floor
    also whether it is by a wall (the WALL_BAND_MM band along walls and obstacles, without
    openings): there a pipe that does not fit the screed runs along the wall above the floor."""

    hidden: tuple[tuple[str, BaseGeometry, float], ...]  # obstacle, place, top height
    floor: BaseGeometry
    edge: BaseGeometry
    walls: BaseGeometry  # wall and obstacle faces: the room middle is farther than WALL_BAND_MM

    @classmethod
    def of(cls, ctx: _Ctx) -> _Zones:
        net = ctx.net
        assert net.rooms is not None
        hidden = tuple((oid, poly.buffer(1.0), h) for oid, (poly, h) in net.hidden.items())
        for _, g, _ in hidden:
            shapely.prepare(g)
        floor = net.rooms.buffer(-1.0)
        walls = net.rooms
        if net.obstacles:
            walls = walls.difference(shapely.unary_union(list(net.obstacles.values())))
        # The route band by walls (grid) plus a step: a corner cut by 45° bends is also by the wall
        edge = walls.boundary.buffer(WALL_BAND_MM + STEP)
        # A pipe is not run through an opening (door, arch) above the floor: people walk there
        openings = [
            opening_strip(g, op)
            for g in ctx.geoms.values()
            for op in g.room.openings
            if op.type is not OpeningType.WINDOW
        ]
        if openings:
            edge = edge.difference(shapely.unary_union(openings).buffer(1.0))
        line = walls.boundary
        for geom in (floor, edge, line):
            shapely.prepare(geom)
        return cls(hidden, floor, edge, line)

    def open_room(self, v: Vec) -> bool:
        """In the middle of a room: farther than WALL_BAND_MM from walls (hidden zones do not
        count).
        """
        return self.walls.distance(shapely.Point(v.as_tuple())) > WALL_BAND_MM + 1.0

    def at(self, v: Vec, z: float, d: int) -> tuple[Zone, str, float]:
        """Zone of a route point; z is the pipe bottom from the slab, d its Ø."""
        p = shapely.Point(v.as_tuple())
        for oid, g, h in self.hidden:
            if g.contains(p):
                return "hidden", oid, h
        if not self.floor.contains(p):
            return "wall", "", 0.0
        fits = d < 100 and z <= SCREED_MM - d - SCREED_COVER + 0.5
        if not fits and self.edge.contains(p):
            return "surface", "", 0.0
        return "screed", "", 0.0


@dataclass(frozen=True)
class _Piece:
    """Route part in one zone, along the flow; s is mm along the route from the fixture to its
    start.
    """

    a: Vec
    za: float
    b: Vec
    zb: float
    zone: Zone
    obstacle: str
    height: float
    s: float


def _upto(path: Sequence[Vec], s: float) -> list[tuple[Vec, float]]:
    """Polyline points from the start up to s mm along it, and the distance of each from the
    start.
    """
    out = [(path[0], 0.0)]
    acc = 0.0
    for a, b in itertools.pairwise(path):
        n = (b - a).length()
        if acc + n >= s - 1e-6:
            if n > 1e-9:
                out.append((a + (b - a) * ((s - acc) / n), s))
            return out
        acc += n
        out.append((b, acc))
    return out


def _flow(pipes: dict[str, Pipe], p: Pipe) -> list[tuple[Vec, float]]:
    """Fixture route along the flow, from the drain on the floor to the riser: points and pipe
    bottom.
    """
    out: list[tuple[Vec, float]] = []
    cur, end = p, _plan_length(p.path)
    while True:
        part = [(v, cur.z0 + s * cur.slope) for v, s in reversed(_upto(cur.path, end))]
        out += part[1:] if out else part
        if cur.parent is None:
            return out
        cur, end = pipes[cur.parent], cur.attach


def _pieces(zones: _Zones, flow: Sequence[tuple[Vec, float]], d: int) -> list[_Piece]:
    out: list[_Piece] = []
    s = 0.0
    for (a, za), (b, zb) in itertools.pairwise(flow):
        n = (b - a).length()
        if n < 1e-6:
            continue
        k = max(1, math.ceil(n / SAMPLE))
        for i in range(k):
            t0, t1 = i / k, (i + 1) / k
            pa, pb = a + (b - a) * t0, a + (b - a) * t1
            z0, z1 = za + (zb - za) * t0, za + (zb - za) * t1
            zone, oid, h = zones.at(a + (b - a) * ((t0 + t1) / 2), max(z0, z1), d)
            last = out[-1] if out else None
            straight = last is not None and (last.b - pa).length() < 1e-6 and i > 0
            if last is not None and straight and (last.zone, last.obstacle) == (zone, oid):
                out[-1] = replace(last, b=pb, zb=z1)
            else:
                out.append(_Piece(pa, z0, pb, z1, zone, oid, h, s + n * t0))
        s += n
    return out


def _room_at(ctx: _Ctx, v: Vec) -> str:
    for g in ctx.geoms.values():
        if point_in_polygon(v, g.contour.vertices):
            return g.room.name
    g = min(
        ctx.geoms.values(),
        key=lambda g: Polygon([u.as_tuple() for u in g.contour.vertices]).distance(
            shapely.Point(v.as_tuple())
        ),
    )
    return g.room.name


@dataclass(frozen=True)
class _Eval:
    pipe: Pipe
    route: SewerRoute
    check: SewerCheck
    errors: tuple[tuple[SewerError, Weak], ...]


def _evaluate(ctx: _Ctx, zones: _Zones, pipes: dict[str, Pipe], p: Pipe) -> _Eval:
    """Fixture route with a given slope and start: parts by zone, the drop in the wall, checks of
    screed, hidden zones, drop and WC branch."""
    net = ctx.net
    outlet = next(o for o in net.outlets if o.fixture == p.target and o.kind == "sewer")
    flow = _flow(pipes, p)
    total = sum((b - a).length() for (a, _), (b, _) in itertools.pairwise(flow))
    root = p
    while root.parent is not None:
        root = pipes[root.parent]
    riser = next(r for r in net.risers if r.id == root.source)
    name = ctx.name(p.target)
    errors: list[tuple[SewerError, Weak]] = []
    seen: set[str] = set()

    def error(reason: str, at: Vec | None, **values: object) -> None:
        if reason in seen:
            return
        seen.add(reason)
        weak = _weak("error", reason, p.target, f=name, **values)
        errors.append((SewerError(p.target, reason, at), weak))

    pieces = _pieces(zones, flow, p.d)
    for piece in pieces:
        if piece.zone == "screed" and p.d >= 100:
            at = (piece.a + piece.b) * 0.5
            error("screed_110", at, room=_room_at(ctx, at), L=_m(total - piece.s))
        elif piece.zone == "screed":
            limit = SCREED_MM - p.d - SCREED_COVER
            if piece.za > limit + 0.5:
                error(
                    "screed_depth",
                    piece.a,
                    d=p.d,
                    s=f"{SCREED_MM:g}",
                    z=round(piece.za),
                    lim=round(limit),
                    c=f"{SCREED_COVER:g}",
                    room=_room_at(ctx, piece.a),
                    L=_m(total - piece.s),
                )
        elif piece.zone == "hidden":
            top = piece.za + p.d - SCREED_MM
            if top > piece.height + 0.5:
                kind = next(ob.type for ob in ctx.plumbing.obstacles if ob.id == piece.obstacle)
                error(
                    "hidden_height",
                    piece.a,
                    zone=HIDDEN_NAMES[kind],
                    z=round(top),
                    max=f"{piece.height:g}",
                )
    z_end = flow[0][1]
    z_outlet = SCREED_MM + outlet.height - p.d / 2
    check = SewerCheck(
        p.target,
        riser.id,
        total,
        outlet.height,
        p.slope,
        p.d,
        riser.inlet,
        riser.inlet_assumed,
        root.z0,
        z_end,
        z_outlet,
    )
    if not check.ok:
        error(
            "drop",
            outlet.node,
            L=_m(total),
            i=f"{p.slope:g}".replace(".", ","),
            d=round(check.drop),
            h=f"{outlet.height:g}",
            r=f"{riser.inlet:g}",
            p=round(check.podium),
        )
    fx = next(f for f in ctx.plumbing.fixtures if f.id == p.target)
    if fx.type in (FixtureType.WC, FixtureType.WC_INSTALLATION) and total > WC_REACH + 0.5:
        error("wc_far", outlet.node, L=_m(total))
    rise = max(0.0, z_outlet - z_end)
    own = _plan_length(p.path)
    surface, surface_top = _surface(pieces, own, p.d)
    open_length = sum(
        min(x.s + (x.b - x.a).length(), own) - x.s
        for x in pieces
        if x.zone == "screed" and x.s < own and zones.open_room((x.a + x.b) * 0.5)
    )
    fittings = ["bend45"] * (drop_bends(rise) + p.bends) + ["tee45"]
    segments = tuple(
        RouteSegment(
            (round(x.a.x, 1), round(x.a.y, 1), round(x.za, 1)),
            (round(x.b.x, 1), round(x.b.y, 1), round(x.zb, 1)),
            x.zone,
            round((x.b - x.a).length(), 1),
        )
        for x in pieces
    )
    route = SewerRoute(
        p.target,
        p.d,
        p.slope,
        (round(z_outlet, 1), round(z_end, 1)) if rise > 0.5 else None,
        segments,
        tuple(fittings),
        p.parent or p.source,
        not errors,
    )
    pipe = replace(p, rise=rise, surface=surface, surface_top=surface_top, open_length=open_length)
    return _Eval(pipe, route, check, tuple(errors))


def _surface(
    pieces: Sequence[_Piece], own: float, d: int
) -> tuple[tuple[tuple[float, float], ...], float]:
    """Parts of its own pipe along the wall above the floor, in mm from the start of its path (own
    is
    the path length; route parts are counted from the fixture), and the pipe top above the
    finished floor there."""
    spans: list[tuple[float, float]] = []
    top = 0.0
    for x in pieces:
        if x.zone != "surface" or x.s >= own:
            continue
        end = min(x.s + (x.b - x.a).length(), own)
        a, b = own - end, own - x.s
        if spans and abs(spans[-1][0] - b) < 1.0:
            spans[-1] = (a, spans[-1][1])
        else:
            spans.append((a, b))
        top = max(top, max(x.za, x.zb) + d - SCREED_MM)
    return tuple(sorted(spans)), top


def _sewer_heights(ctx: _Ctx) -> None:
    """Sewer heights computed backwards from the riser inlet (from the slab), all as pipe bottom:
    each pipe has a slope and a bottom at its start; a branch starts on the parent pipe with its
    bottom flush with the parent's (a 110×50 tee: the branch bottom is not below the main's).
    One slope per pipe, from a list (routing spec, item 5): SLOPE; if the route fails with it,
    SLOPE_MIN (Ø110, no branches); if it passes, SLOPE_MAX when the route has no branches off it,
    the parent slope is not smaller and the box above the floor and the room middle do not grow
    (the main is not flatter than its branches)."""
    net = ctx.net
    pipes = {p.id: p for p in net.pipes if p.kind == "sewer"}
    if not pipes:
        return
    zones = _Zones.of(ctx)
    risers = {r.id: r for r in net.risers}
    parents = {p.parent for p in pipes.values() if p.parent is not None}
    order = [p.id for p in net.pipes if p.kind == "sewer"]  # the parent is laid before the branch
    results: dict[str, _Eval] = {}
    for pid in order:
        p = pipes[pid]
        cap = SLOPE_MAX
        if p.parent is None:
            z0 = _riser_invert(risers[p.source])
        else:
            parent = pipes[p.parent]
            z0 = parent.z0 + p.attach * parent.slope
            cap = parent.slope
        d = _norm(p.d)
        leaf = pid not in parents

        def run(slope: float, p: Pipe = p, z0: float = z0, pid: str = pid) -> _Eval:
            pipes[pid] = replace(p, slope=slope, z0=z0)
            return _evaluate(ctx, zones, pipes, pipes[pid])

        best = run(min(SLOPE[d], cap))
        if best.errors and leaf and SLOPE_MIN[d] < best.pipe.slope:
            low = run(SLOPE_MIN[d])
            if len(low.errors) < len(best.errors):
                best = low
        elif not best.errors and leaf and cap + 1e-9 >= SLOPE_MAX:
            steep = run(SLOPE_MAX)
            no_worse = (
                steep.pipe.surface_length <= best.pipe.surface_length + 0.5
                and steep.pipe.open_length <= best.pipe.open_length + 0.5
            )
            if not steep.errors and no_worse:
                best = steep
        pipes[pid] = best.pipe
        results[pid] = best
    for k, p in enumerate(net.pipes):
        if p.id in pipes:
            net.pipes[k] = pipes[p.id]
    for pid in order:
        res = results[pid]
        net.sewer.append(res.check)
        net.routes.append(res.route)
        for err, weak in res.errors:
            net.sewer_errors.append(err)
            net.weak.append(weak)
        _sewer_warnings(ctx, pipes[pid])


def _sewer_warnings(ctx: _Ctx, p: Pipe) -> None:
    """Pipe warnings: many bends (cleanout), through a living room."""
    net = ctx.net
    name = ctx.name(p.target)
    fx = next(f for f in ctx.plumbing.fixtures if f.id == p.target)
    if p.surface_length > 1.0:
        net.weak.append(
            _weak(
                "warning",
                "surface",
                p.target,
                f=name,
                L=_m(p.surface_length),
                h=round(p.surface_top),
            )
        )
    if p.bends > SEWER_BENDS:
        net.weak.append(_weak("warning", "turns", p.target, f=name, n=p.bends))
    line = LineString([v.as_tuple() for v in p.path])
    for g in ctx.geoms.values():
        if not is_living(g.room) or g.room.id == fx.room:
            continue
        inside = line.intersection(Polygon([v.as_tuple() for v in g.contour.vertices]))
        if inside.length > 1.0:
            net.weak.append(_weak("warning", "living", p.target, f=name, room=g.room.name))


def _norm(d: int) -> int:
    return 110 if d >= 100 else 50


def routes_json(net: Network) -> dict[str, Any]:
    """Sewer routes in the routing spec format (out/sewer-routes.json): per fixture the diameter,
    slope, drop in the wall, parts along the flow with their zone (z is the pipe bottom, mm from
    the slab), fittings of its own pipe; errors with their place on the plan (model mm). Totals:
    totalLength is mm of all sewer pipes (on the floor, in walls, drops), totalFittings the number
    of fittings, savingVsDirect the mm of equivalent length (PIPE_WEIGHT, SEWER_BEND_COST) saved
    by tees compared with connecting each Ø50 fixture separately."""
    sewer = net.pipes_of("sewer")
    small = [p for p in sewer if p.d < 100]
    saving = net.sewer_direct - sum(_equivalent(p.path, p.d) for p in small) if small else 0.0
    return {
        "screed": SCREED_MM,
        "totalLength": round(sum(p.total for p in sewer), 1),
        "totalFittings": sum(len(r.fittings) for r in net.routes),
        "savingVsDirect": round(saving, 1),
        "routes": [
            {
                "fixture": r.fixture,
                "diameter": r.d,
                "slope": r.slope,
                "verticalDrop": {"from": r.drop[0], "to": r.drop[1]} if r.drop else None,
                "segments": [
                    {"from": list(s.start), "to": list(s.end), "zone": s.zone, "length": s.length}
                    for s in r.segments
                ],
                "fittings": list(r.fittings),
                "into": r.into,
                "ok": r.ok,
            }
            for r in net.routes
        ],
        "errors": [
            {
                "fixture": e.fixture,
                "reason": e.reason,
                "at": [round(e.at.x, 1), round(e.at.y, 1)] if e.at is not None else None,
            }
            for e in net.sewer_errors
        ],
    }
