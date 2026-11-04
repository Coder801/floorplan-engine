"""What the plumbing network is made of: outlets, pipes, manifolds, risers, checks, weak spots.

Result types only; built by plumbing/network.py.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Literal

from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from floorplan_engine.model.geometry import (
    Vec,
)
from floorplan_engine.model.plumbing import (
    Fixture,
)
from floorplan_engine.model.texts import Language
from floorplan_engine.plumbing import bends as b45
from floorplan_engine.plumbing.rules import DROP_TURN, FIXTURE_NAMES, HOLE_SHARE, SCREED_MM, Kind


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


def weak_spot(
    severity: Literal["error", "warning"], key: str, target: str, **values: object
) -> Weak:
    """Weak spot in both languages; a dict value {ru, uk} has its own per language."""

    def on(lang: Language) -> dict[str, object]:
        return {k: v[lang] if isinstance(v, dict) else v for k, v in values.items()}

    langs: tuple[Language, ...] = ("ru", "uk")
    return Weak(severity, {lang: text(key, lang, **on(lang)) for lang in langs}, target)


def metres(mm: float) -> str:
    return f"{mm / 1000:.1f}".replace(".", ",")
