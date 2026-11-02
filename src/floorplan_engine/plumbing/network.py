"""Сеть водоснабжения и канализации из plumbing.yaml: подводы приборов, трассы, проверки.

Правила (docs/plumbing.md):
- трассы идут по полу (вода — в стяжке, канализация — по полу в коробе), под прямыми
  углами, в обход стен и препятствий (инсталляция, ванна, поддон, короб), через дверные
  проёмы, не ближе routing.CLEARANCE к стенам — та же сетка, что у проводки;
- к прибору труба подходит по полу к ближайшему свободному месту у его стены, дальше — в
  стене: вдоль стены (wall_run) и вверх до водорозетки или выпуска (rise). Так трасса
  обходит инсталляцию и ванну: к смесителю над ванной — сбоку, в стене;
- вода — лучевая (collector, по умолчанию): у каждой водорозетки своя труба Ø16 от
  коллектора холодной или горячей воды в узле ввода; тройниковая (tee, эконом): магистраль
  от узла ввода, к прибору — отвод от ближайшего места магистрали; труба, от которой есть
  отводы, — Ø20, концевые — Ø16. Коллектор горячей от бойлера — у бойлера. В лучевой
  соседи на одной стене (двойная тумба, посудомойка у мойки — supply_groups) — одной трубой
  Ø16 от коллектора на каждую воду, второй — тройником у первого; луч, что долго идёт рядом
  с другим или отводом от него заметно короче, — тройником от него, если общая труба
  пропустит расход (_merge_parallel). Горячая — из стояка или от
  бойлера (бойлер берёт холодную с коллектора, горячую отдаёт в коллектор горячей воды или в
  магистраль);
- водорозетки пары: горячая слева, холодная справа (вид изнутри) — в HOT_COLD_GAP / 2 от
  середины подводки;
- канализация (ТЗ трассировки 2026-11-02) — дерево к стояку: сначала унитазы (Ø110 —
  только в стояк или в трубу Ø110, отвод не длиннее WC_REACH), затем остальные — в стояк
  или в трубу Ø50 (унитаз — ближе всех к стояку). Своя сетка: через дверные проёмы и пороги
  жилых комнат — нельзя, скрытые зоны (короб, инсталляция, под ванной и поддоном —
  HIDDEN_HEIGHT) — в приоритете; поиск в восемь сторон, изломы — только отводами 45°
  (plumbing/bends.py), врезка — косым тройником. Высоты — обратным счётом от врезки в
  стояк, от плиты: уклон на всей трассе прибора один (SLOPE, у Ø110 — до SLOPE_MIN), выпуск
  выше — спуск в стене. В стяжке (SCREED_MM) низ трубы + Ø + SCREED_COVER не выше стяжки,
  Ø110 в стяжке нельзя. Что в стяжку не помещается, идёт по стене над полом (зона surface:
  у стены, в коробе; правка 2026-11-02) — не ошибка, а примечание с высотой короба; в
  стяжке остаются ошибкой только участки посреди помещения и через проёмы. Проходы: обычный,
  через скрытые зоны и только вдоль стен — берётся проход с меньшим числом ошибок
  (SewerError, трассы — SewerRoute, JSON — routes_json);
- слабые места (Weak) — на лист и в отчёт: стяжка, перепад, отвод унитаза, канализация
  через жилую комнату, много отводов, прибор недостижим, нет горячей воды.

Высоты подводов без данных — FIXTURE_SPECS (допущение, «*» в таблице приборов); ось
врезки в стояк без данных — SEWER_INLET_MM.
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

HOT_COLD_GAP = 150.0  # мм между водорозетками холодной и горячей
COLLECTOR_GAP = 200.0  # мм между коллекторами холодной и горячей воды в узле
SUPPLY_D = 16  # Ø луча коллектора и концевого отвода, мм (металлопластик / PEX 16)
MAIN_D = 20  # Ø магистрали, ввода и подачи от бойлера, мм
# Уклон канализации (ТЗ трассировки 2026-11-02): 2–3 см на метр, один на всей трассе
# прибора, из списка (_sewer_heights): 0,025 — по умолчанию; 0,02 — если с 0,025 трасса не
# годится, только Ø110 (Ø50 — не меньше 0,025 по ДБН В.2.5-64, как СНиП 2.04.01-85); 0,03 —
# если запас высоты позволяет (трасса без отводов от неё: магистраль не круче, чем ветки)
SLOPE = {50: 0.025, 110: 0.025}
SLOPE_MIN = {50: 0.025, 110: 0.02}
SLOPE_MAX = 0.03
SCREED_MM = 90.0  # стяжка: чистый пол на 90 мм выше плиты; высоты канализации — от плиты
SCREED_COVER = 15.0  # мм над трубой в стяжке — не меньше
RISER_TEE_D = 110  # тройник стояка: низ входа — ось врезки минус радиус Ø110
# Скрытые зоны канализации — препятствия, где трубу прячут: наибольшая высота верха трубы от
# чистого пола (у препятствия нет height — эта, допущение)
HIDDEN_HEIGHT = {
    ObstacleType.INSTALLATION: 1000.0,
    ObstacleType.BOX: 600.0,
    ObstacleType.BATH: 450.0,  # под ванной, за экраном
    ObstacleType.SHOWER_TRAY: 100.0,  # под поддоном
}
# Цена клетки сетки канализации — множитель длины шага (ТЗ трассировки, правка 2026-11-02):
# скрытая зона дешевле всего, у стены — 1, дальше — дороже. Свободные ячейки сетки — не ближе
# CLEARANCE (150 мм) к стене, поэтому «у стены» — первая полоса оси трубы, до WALL_BAND_MM
HIDDEN_COST = 0.7
WALL_COST = 1.0
NEAR_WALL_COST = 2.0
OPEN_ROOM_COST = 4.0  # ≥ 3: диагональ короче пути вдоль стен не больше чем в √2 раза
WALL_BAND_MM = CLEARANCE + STEP  # полоса у стены: над полом здесь можно в коробе
NEAR_WALL_MM = 400.0  # дальше — середина комнаты
# Варианты трассы канализации (проходы _sewer): цены скрытой, у стены, рядом, середины
SEWER_VARIANTS: tuple[tuple[float, float, float, float], ...] = (
    (HIDDEN_COST, WALL_COST, NEAR_WALL_COST, OPEN_ROOM_COST),  # обычный
    (0.2, WALL_COST * 3, NEAR_WALL_COST * 3, OPEN_ROOM_COST * 3),  # через скрытые зоны
    (HIDDEN_COST, WALL_COST, NEAR_WALL_COST * 5, OPEN_ROOM_COST * 10),  # только вдоль стен
)
# Вид ячейки сетки канализации (Grid.tag): скрытая зона, у стены, рядом, середина
TAG_HIDDEN, TAG_WALL, TAG_NEAR, TAG_OPEN = 0, 1, 2, 3
FALLBACK_COST = 1e6  # путь без отсечения по высоте — только если иначе к прибору не пройти
# Полые препятствия: трубы своего прибора идут внутри (короб, инсталляция), чужие — в обход
HOLLOW = frozenset({ObstacleType.INSTALLATION, ObstacleType.BOX})
PARTITION_MAX = 150.0  # мм: ненесущая тоньше — перегородка; толще — только с partition: true
PARTITION_COST = 1000.0  # мм за ячейку у перегородки: проход ≈ как 4 м обхода
UNDER_COST = 50.0  # мм за ячейку под гипсокартонной стенкой внутри помещения: почти свободно
DOOR_COST = 20000.0  # мм за ячейку в дверном проёме: трубы через дверь — в крайнем случае
HOLE_SHARE = 300.0  # мм: трубы ближе — в одном отверстии
RISER_WALL = 400.0  # мм: от стояка в стене до помещения — не больше (толщина стены с запасом)
RISER_REACH = 800.0  # мм: насколько от стояка искать подход с каждой стороны
WC_REACH = 1000.0  # мм по трубе до стояка: отвод унитаза длиннее — ошибка
SEWER_BENDS = 6  # отводов 45° по плану у трубы канализации — больше: ревизия
DROP_TURN = 150.0  # мм: спуск от выпуска не ниже — два поворота на 90° (вниз и на пол),
# меньше — сдвиг вниз двумя отводами 45° («утка»)
# Расход трубы (ТЗ «тройники» 2026-11-02): вес метра по диаметру и отвод 45° — в мм
# эквивалентной длины; тройники Ø50 — объединением пар приборов по экономии (_merge_drains)
PIPE_WEIGHT = {50: 1.0, 110: 2.2}
TURN_COST_MM = 175.0  # отвод 45° — в мм эквивалентной длины: в поиске, в экономии тройников
SEWER_BEND_COST = TURN_COST_MM
TEE_CANDIDATES = 20  # мест тройника на пару: лучшее недопустимо — следующее по стоимости
REACH = CLEARANCE + 1.6 * STEP  # насколько от стены ищется место подхода к прибору
ALONG_COST = 3.0  # метр в стене вдоль — как три метра по полу: штроба дороже
PAIR_GAP = 80.0  # мм между осями горячей и холодной, идущих парой к одному прибору
# Общая линия от коллектора (правка 2026-11-02): приборы-соседи одного помещения на одной стене
# не дальше SHARE_GAP — одна труба на воду, у прибора тройник Ø16: два умывальника (двойная
# тумба), посудомойка — от холодной мойки
SHARED_PAIRS = frozenset(
    {
        (FixtureType.SINK, FixtureType.SINK),
        (FixtureType.KITCHEN_SINK, FixtureType.DISHWASHER),
        (FixtureType.DISHWASHER, FixtureType.KITCHEN_SINK),
    }
)
SHARED_TYPES = frozenset(t for pair in SHARED_PAIRS for t in pair)
# Попутные линии (правка 2026-11-02): луч, что идёт рядом с другим (ближе PARALLEL_GAP) не
# меньше PARALLEL_MIN, отходит от него тройником, если так короче и труба пропустит расход
PARALLEL_GAP = 300.0  # мм между осями: идут рядом, одним пучком
PARALLEL_MIN = 2000.0  # мм рядом — уже «долго»
BRANCH_SAVING = 1000.0  # мм: идут рядом недолго — отвод, только если экономит столько трубы
# Расчётный расход водорозетки, л/с — ориентир: ДБН В.2.5-64 / СНиП 2.04.01-85 (прил. 3) для
# умывальника, мойки, душа, ванны, унитаза; стиральная и посудомоечная машины — по паспортам
# типовых моделей (≈ 9 и 6 л/мин)
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
# Пропуск трубы, л/с, без коэффициента одновременности (с запасом): Ø16 (внутр. 12 мм) и
# Ø20 (внутр. 16 мм) — при скорости около 1,75 м/с
CAPACITY: dict[int, float] = {16: 0.20, 20: 0.35}
SHARE_GAP = 1200.0  # мм между серединами подводок
COLLECTOR_HEIGHT = 400.0  # мм: ось выходов коллектора от пола (шкаф у пола) — допущение
COLLECTOR_HALF = 150.0  # мм: половина коллектора с кранами вдоль стены (место на стене)
BOILER_NEAR = 1500.0  # мм: бойлер ближе к узлу ввода — коллектор горячей в узле, дальше — у бойлера
# Жилые комнаты: канализация по полу через них — слабое место; совмещённые с кухней или
# коридором — нет (мойка там своя)
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
    """Подключение прибора на стене: водорозетка или выпуск. node — на грани стены."""

    fixture: str
    kind: Kind
    room: str
    wall: str
    offset: float  # от начала стены, мм
    height: float  # ось от чистого пола, мм
    node: Vec
    inward: Vec
    d: int
    assumed: bool  # высота типовая (FIXTURE_SPECS)


@dataclass(frozen=True)
class Collector:
    """Коллектор (лучевая) или начало магистрали (тройниковая) в узле ввода."""

    id: str  # collector_cold, collector_hot
    kind: Kind
    room: str
    wall: str
    offset: float
    node: Vec
    inward: Vec
    outputs: int
    height: float = 0.0  # ось выходов от чистого пола, мм (input.height или COLLECTOR_HEIGHT)


@dataclass(frozen=True)
class RiserNode:
    id: str
    room: str
    center: Vec
    sewer: bool
    water: bool
    inlet: float  # ось врезки канализации от пола, мм
    inlet_assumed: bool


@dataclass(frozen=True)
class Pipe:
    """Труба: путь по плану от источника к цели (мм модели) и участки в стене у цели."""

    id: str
    kind: Kind
    source: str  # коллектор, стояк, бойлер или труба-родитель (отвод)
    target: str  # прибор, коллектор горячей воды (подача от бойлера), узел ввода
    path: tuple[Vec, ...]
    d: int
    rise: float  # вверх в стене у цели, мм (до водорозетки или выпуска)
    wall_run: float  # вдоль стены у цели, мм (в стене)
    parent: str | None = None
    attach: float = 0.0  # мм от начала родителя до врезки
    room: str = ""  # помещение цели
    slope: float = 0.0  # канализация: уклон по плану
    z0: float = 0.0  # канализация: низ трубы у начала (стояк или врезка), мм от плиты
    # канализация по стене над полом (в стяжку не помещается): участки своей трубы, мм от
    # начала пути (от стояка или врезки), и верх трубы над чистым полом там — высота короба
    surface: tuple[tuple[float, float], ...] = ()
    surface_top: float = 0.0
    open_length: float = 0.0  # канализация: мм своей трубы посреди комнаты (оценка варианта)

    @property
    def length(self) -> float:
        """По плану, без участков в стене."""
        return sum((b - a).length() for a, b in itertools.pairwise(self.path)) - self.wall_run

    @property
    def total(self) -> float:
        """Вся труба: по полу, в стене вдоль и вверх."""
        return self.length + self.wall_run + self.rise

    @property
    def bends(self) -> int:
        """Отводов 45° по плану (поворот на 90° — два)."""
        return b45.bends(self.path)

    @property
    def surface_length(self) -> float:
        """По стене над полом, мм (в коробе, не в стяжке)."""
        return sum(b - a for a, b in self.surface)


@dataclass(frozen=True)
class SewerCheck:
    """Перепад канализации прибора до врезки в стояк. z — низ трубы от плиты."""

    fixture: str
    riser: str
    length: float  # по трубам до стояка, мм
    start: float  # ось выпуска у прибора, мм от чистого пола
    slope: float  # уклон трассы прибора
    d: int
    inlet: float  # ось врезки в стояк от чистого пола
    inlet_assumed: bool
    z_inlet: float  # низ трубы у стояка
    z_end: float  # низ трубы по полу у прибора: врезка плюс перепад
    z_outlet: float  # низ выпуска

    @property
    def drop(self) -> float:
        """Перепад по полу от прибора до стояка, мм."""
        return self.z_end - self.z_inlet

    @property
    def end_floor(self) -> float:
        """Ось трубы по полу у прибора, мм от чистого пола."""
        return self.z_end + self.d / 2 - SCREED_MM

    @property
    def ok(self) -> bool:
        return self.z_outlet >= self.z_end - 0.5

    @property
    def podium(self) -> float:
        """Насколько поднять выпуск (подиум, трап), чтобы хватило уклона, мм."""
        return max(0.0, self.z_end - self.z_outlet)


Zone = Literal["screed", "hidden", "wall", "surface"]  # surface — по стене над полом


@dataclass(frozen=True)
class RouteSegment:
    """Участок трассы канализации по течению: точки [x, y, z] (z — низ трубы от плиты)."""

    start: tuple[float, float, float]
    end: tuple[float, float, float]
    zone: Zone
    length: float


@dataclass(frozen=True)
class SewerRoute:
    """Трасса прибора до стояка (формат ТЗ, routes_json): участки по течению, спуск в стене,
    фасонные части своей трубы (до её врезки)."""

    fixture: str
    d: int
    slope: float
    drop: tuple[float, float] | None  # спуск в стене: от низа выпуска до низа трубы по полу
    segments: tuple[RouteSegment, ...]
    fittings: tuple[str, ...]
    into: str  # стояк или труба, в которую врезка
    ok: bool


@dataclass(frozen=True)
class SewerError:
    """Почему трасса прибора не годится: код причины и место на плане (мм модели)."""

    fixture: str
    reason: str  # screed_depth | screed_110 | hidden_height | drop | wc_far | unreachable
    at: Vec | None


@dataclass(frozen=True)
class Weak:
    """Слабое место сети: на лист «Сантехника» и в отчёт."""

    severity: Literal["error", "warning"]
    text: dict[str, str]  # ru, uk
    target: str  # id прибора, трубы или стояка; «» — сеть целиком


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
    sewer_direct: float = 0.0  # расход Ø50, если каждый прибор отдельно в стояк, мм экв.
    hidden: dict[str, tuple[Polygon, float]] = field(default_factory=dict)  # скрытые зоны:
    # препятствие → место и наибольшая высота верха трубы от чистого пола
    weak: list[Weak] = field(default_factory=list)
    hot_source: str | None = None  # riser | id бойлера | None — горячей нет
    input_assumed: bool = False  # узел ввода поставлен у стояка допущением
    free: BaseGeometry | None = None
    distribution: str = "collector"
    partitions: list[Polygon] = field(default_factory=list)  # перегородки: проход с отверстием
    under: list[Polygon] = field(default_factory=list)  # гипсокартонные стенки внутри помещения:
    # трубы — по полу под ними (кладутся до стенки), без отверстия
    doors: list[Polygon] = field(default_factory=list)  # дверные проёмы: трубы — в крайнем случае
    hollow: set[str] = field(default_factory=set)  # препятствия-короба (инсталляция)
    rooms: BaseGeometry | None = None  # помещения и проёмы без перегородок и препятствий:
    # грани — стены (за ванной — тоже стена)

    def holes(self, kinds: tuple[Kind, ...]) -> int:
        """Отверстий в перегородках: трубы этих сетей, что проходят перегородку рядом (ближе
        HOLE_SHARE), — в одном отверстии."""
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
    """Отводов 45° на спуске в стене от выпуска до трубы по полу: поворот на 90° — всегда
    два отвода 45°. Спуск от DROP_TURN — вниз из выпуска и на пол (4), меньше — сдвиг (2)."""
    if rise <= 0.5:
        return 0
    return 4 if rise >= DROP_TURN else 2


def text(key: str, language: Language, **values: object) -> str:
    return TEXT[key][language].format(**values)


def _weak(severity: Literal["error", "warning"], key: str, target: str, **values: object) -> Weak:
    """Слабое место на обоих языках; значение-словарь {ru, uk} — своё на каждом."""

    def on(lang: Language) -> dict[str, object]:
        return {k: v[lang] if isinstance(v, dict) else v for k, v in values.items()}

    langs: tuple[Language, ...] = ("ru", "uk")
    return Weak(severity, {lang: text(key, lang, **on(lang)) for lang in langs}, target)


def _m(mm: float) -> str:
    return f"{mm / 1000:.1f}".replace(".", ",")


# --- Геометрия -------------------------------------------------------------------


def obstacle_polygon(ob: Obstacle, g: RoomGeometry) -> Polygon:
    """Препятствие на плане, мм модели."""
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
    """Дверные проёмы на всю толщину стены (у соседа на том же месте — проём type: opening,
    он ложится на ту же полосу). Арка без двери — не дверь: через неё трубы идут свободно."""
    return [
        opening_strip(g, op) for g in geoms for op in g.room.openings if op.type is OpeningType.DOOR
    ]


def partition_strips(
    geoms: Sequence[RoomGeometry], doors: Sequence[Polygon] = (), inner: bool = False
) -> list[Polygon]:
    """Перегородки между помещениями квартиры (не несущие, не толще PARTITION_MAX или
    явно `partition: true` в room.yaml); inner=True — стены внутри помещения с
    `partition: true` (гипсокартонная стенка в санузле: с обеих сторон — то же помещение,
    трубы — под ней по полу, network.Network.under): полоса
    стены на всю толщину, без окон (стеклянная перегородка — не проход) и без дверей (их
    проход дороже, door_strips)."""
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
    # Общая стена описана в обоих помещениях — полосы совпадают: одна перегородка, иначе
    # каждое отверстие в ней считалось бы дважды (Network.holes)
    merged = shapely.unary_union(out) if out else None
    if merged is None:
        return []
    parts = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
    return [p for p in parts if isinstance(p, Polygon) and p.area > 1.0]


def riser_center(r: Riser, geoms: dict[str, RoomGeometry]) -> Vec:
    ox, oy = geoms[r.room].room.origin
    return Vec(ox + r.at[0], oy + r.at[1])


def nearest_wall(g: RoomGeometry, p: Vec) -> tuple[WallSegment, float]:
    """Ближайшая к точке стена помещения и отступ проекции на неё (в её пределах)."""
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
    """Поиск по сетке от одной ячейки: стоимость до каждой и путь."""

    grid: Grid
    prev: dict[int, int]
    dist: dict[int, float]
    ndirs: int = 4  # 4 — под 90° (вода), 8 — отводами 45° (канализация)

    offset: float = 0.0  # доплата ко всей стоимости: запасной поиск без отсечения

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
    """Место подхода к узлу на стене: ячейка сетки и хвост до узла (по полу к стене, в стене
    вдоль неё). along — сколько в стене вдоль."""

    cell: int
    tail: tuple[Vec, ...]  # от центра ячейки до узла
    along: float


def _approaches(grid: Grid, seg: WallSegment, offset: float) -> list[_Approach]:
    """Свободные ячейки у стены seg (не дальше REACH от её грани, против неё), от ближних
    к месту на стене — к дальним."""
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
    """Подходы к узлу внутри короба (инсталляция): свободные ячейки у короба с любой
    стороны; от ячейки — к грани короба и внутри него к узлу (в коробе, как в стене)."""
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
    """Подход к точке вне стены (стояк): свободная ячейка (по умолчанию — ближайшая) и
    излом под 90°."""
    cell = grid.nearest_free(p) if cell is None else cell
    c = grid.center(cell)
    if abs(c.x - p.x) < 1e-6 or abs(c.y - p.y) < 1e-6:
        return _Approach(cell, (c, p), 0.0)
    return _Approach(cell, (c, Vec(c.x, p.y), p), 0.0)


def _best(field_: _Field, options: Sequence[_Approach]) -> _Approach | None:
    """Подход с наименьшей стоимостью: путь по сетке плюс штраф за метры в стене."""
    best: tuple[float, _Approach] | None = None
    for a in options:
        c = field_.cost(a.cell)
        if math.isinf(c):
            continue
        total = c + a.along * ALONG_COST
        if best is None or total < best[0]:
            best = (total, a)
    return best[1] if best is not None else None


# --- Сеть ------------------------------------------------------------------------


@dataclass
class _Ctx:
    plan: Plan
    plumbing: Plumbing
    geoms: dict[str, RoomGeometry]
    grid: Grid
    net: Network
    boxes: dict[str, bool] = field(default_factory=dict)  # препятствие — короб: трубы внутри
    counter: dict[str, int] = field(default_factory=dict)
    sewer_grids: tuple[Grid, ...] = ()  # сетки канализации: обычная, через скрытые, у стен
    ndirs: int = 4  # поиск: 8 — канализация отводами 45°
    boxes_open: bool = False  # короба и инсталляции — проходимы (канализация)
    prune: Prune | None = None  # отсечение по высоте, не зависящее от длины (Ø110)

    def field(self, cell: int, prune: bool = True) -> _Field:
        return _Field.from_cell(self.grid, cell, self.ndirs, self.prune if prune else None)

    def name(self, fixture: str) -> dict[str, str]:
        """Прибор словами на обоих языках: «Мийка (Кухня)»."""
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
        """Подходы к месту на стене; прибор на коробе или инсталляции — через короб."""
        seg = self.geoms[room].contour.segment(wall)
        node = seg.point_at(offset)
        for oid, poly in self.net.obstacles.items():
            if self.boxes_open:
                break
            if self.boxes.get(oid) and poly.buffer(1.0).contains(shapely.Point(node.as_tuple())):
                return _box_approaches(self.grid, poly, node)
        return _approaches(self.grid, seg, offset)


def fixture_outlets(fx: Fixture, geoms: dict[str, RoomGeometry]) -> list[Outlet]:
    """Подводы прибора на его стене: горячая слева, холодная справа, выпуск по середине."""
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
    """Сеть по plumbing.yaml: подводы, коллекторы, трассы воды и канализации, проверки."""
    geoms = {g.room.id: g for g in room_geometries(plan, contours)}
    net = Network(distribution=plumbing.distribution)
    for ob in plumbing.obstacles:
        net.obstacles[ob.id] = obstacle_polygon(ob, geoms[ob.room])
    free = free_area(list(geoms.values()))
    rooms_only = free  # без перегородок: их грани — тоже стены, у них идёт канализация
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
    """Сетка трасс: сквозь перегородку — можно, но дорого (отверстие у пола); под
    гипсокартонной стенкой внутри помещения — почти свободно; через дверной проём — почти
    никогда (порог, полотно): только если иначе к прибору не пройти."""
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
    """Жилая комната: канализация через неё — слабое место, через её порог — нельзя."""
    return (
        bool(LIVING_NAME.search(room.name)) and not SERVICE_NAME.search(room.name) and not room.wet
    )


def _sewer_grid(
    geoms: Sequence[RoomGeometry], net: Network, costs: tuple[float, float, float, float]
) -> Grid:
    """Сетка канализации: без дверных проёмов и проёмов жилых комнат (пороги — запрет без
    исключений); цена шага — множитель по ячейке (Grid.mult, costs: скрытая зона — короб,
    инсталляция, под ванной и поддоном; у стены до WALL_BAND_MM; до NEAR_WALL_MM; дальше)
    и вид ячейки (Grid.tag) — для отсечения по высоте в поиске (_height_prune)."""
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
    edge = walls.boundary  # вдоль стен, ванны, короба
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
            far = edge.distance(p)  # ровно на границе полосы (+1 мм) — ещё у стены
            tag = TAG_WALL if far <= WALL_BAND_MM + 1.0 else TAG_NEAR
            if far > NEAR_WALL_MM + 1.0:
                tag = TAG_OPEN
        grid.tag[k], grid.mult[k] = tag, costs[tag]
    return grid


Prune = Callable[[int, float], bool]


def _height_prune(
    grid: Grid, z0: float, slope: float, d: int, lower: Vec | None = None
) -> Prune | None:
    """Отсечение в поиске канализации (ТЗ трассировки, п. 2): ячейка вне скрытой зоны и
    пристенной полосы недоступна, если низ трубы там — z0 + длина · уклон — с Ø и слоем
    SCREED_COVER уже выше стяжки. Длина — по пути от врезки (поиск от стояка); lower —
    поиск от прибора: длина неизвестна, берётся нижняя оценка — расстояние от этой точки
    (стояка) по прямой; Ø110 в стяжку не помещается вовсе."""
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
    """Прибор → прибор, с которым у него общая линия от коллектора (первый в группе; у
    одиночного — он сам): пары SHARED_PAIRS одного помещения на одной стене, соседние
    подводки не дальше SHARE_GAP (двойная тумба; посудомойка у мойки)."""
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
    """Узел ввода: из plumbing.yaml или у водяного стояка (иначе у первого) допущением."""
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
    """Откуда горячая: стояк (riser) или бойлер (id прибора); None — неоткуда."""
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
            continue  # магистраль горячей в тройниковой — от бойлера
        c_room, c_wall, c_seg, c_at = room, wall, seg, offset + shift
        c_h = inp.height if inp is not None and inp.height is not None else COLLECTOR_HEIGHT
        far = boiler_out and (boiler_out[0].node - seg.point_at(offset)).length() > BOILER_NEAR
        if kind == "hot" and far:
            # Горячая от бойлера вдали от узла — её коллектор у бойлера (правка 2026-11-02):
            # иначе горячая шла бы от бойлера к узлу ввода и обратно к приборам у бойлера
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
    # Бойлер отдаёт горячую в коллектор горячей воды (лучевая) или начинает магистраль
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
            for members in by_group.values():  # группы — до попутных линий (_merge_parallel)
                # Линия — к прибору группы с горячей (холодная к нему — парой с горячей), из
                # них — к ближнему к коллектору; остальные — тройником от неё
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
    """Труба и все отводы от неё (и от отводов)."""
    out, todo = [root], [root.id]
    while todo:
        pid = todo.pop()
        for p in pipes:
            if p.parent == pid:
                out.append(p)
                todo.append(p.id)
    return out


def _demand(ctx: _Ctx, pipes: Sequence[Pipe]) -> float:
    """Расчётный расход приборов этих труб, л/с (FLOW)."""
    types = {f.id: f.type for f in ctx.plumbing.fixtures}
    return sum(FLOW.get(types[p.target], 0.1) for p in pipes if p.target in types)


def _pipe_d(flow: float) -> int | None:
    """Ø трубы под расход; не пропустит и Ø20 — None."""
    return next((d for d in sorted(CAPACITY) if flow <= CAPACITY[d] + 1e-9), None)


def _alongside(a: Pipe, b: Pipe) -> float:
    """Сколько мм пути b по полу идёт рядом с a (ближе PARALLEL_GAP)."""
    if len(a.path) < 2 or len(b.path) < 2:
        return 0.0
    near = LineString([v.as_tuple() for v in a.path]).buffer(PARALLEL_GAP)
    return float(LineString([v.as_tuple() for v in b.path]).intersection(near).length)


def _merge_parallel(ctx: _Ctx, kind: Kind, col: Collector) -> None:
    """Попутные линии (правка 2026-11-02): луч от коллектора переносится тройником на другой
    луч, если идёт рядом с ним дольше PARALLEL_MIN и вода сети от этого короче, или отвод
    экономит не меньше BRANCH_SAVING; общая труба должна пропустить расход (FLOW, CAPACITY:
    Ø16, иначе Ø20; больше — нет). Линия бойлера — своя: он греет воду всей квартиры.
    Начинают пары с самым длинным общим участком; повторяется, пока есть что объединить."""
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
    """Перевесить трубы moved (луч и его отводы) тройником на трубу a; a — Ø d. Вода сети
    короче меньше чем на saving мм или отвод не нашёл места на a — вернуть как было (False)."""
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
    """Луч от коллектора к водорозетке; горячая — парой с холодной, если та уже есть."""
    net = ctx.net
    cold = next((p for p in net.pipes if p.kind == "cold" and p.target == o.fixture), None)
    if kind == "hot" and cold is not None and cold.parent is None and _pair(ctx, cold, col, o):
        return net.pipes[-1]
    return _route_one(ctx, kind, col.id, _wall_node(col), o.fixture, o, SUPPLY_D)


def _clear_offset(ctx: _Ctx, seg: WallSegment, offset: float) -> float:
    """Ближайшее к offset место на стене, где коллектор (COLLECTOR_HALF в обе стороны) не за
    препятствием: под бойлером над инсталляцией коллектор не встанет — рядом с ней."""
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
    """Ортогональная ломаная, сдвинутая влево по ходу на gap (вправо — gap < 0)."""
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
    """Горячая к прибору — парой с холодной: та же трасса, сдвинутая на PAIR_GAP в ту
    сторону, где она свободна; концы — к коллектору горячей и водорозетке. Нет места ни с
    одной стороны — False (горячая прокладывается сама)."""
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
    """Узел на стене — источник или цель трассы."""

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
    """Труба от узла src к подводу dst: по полу от стены к стене, хвосты — в стене."""
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
    """Отверстие в перегородке, через которое прошла труба воды, — следующим трубам воды без
    доплаты PARTITION_COST: они идут пучком через то же отверстие, а не пробивают своё
    (правка 2026-11-02: стиральная машина шла через гостиную, а не со всеми через санузел)."""
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
    """Места врезки отвода вдоль трубы по полу (без хвостов в стене): точка и мм от начала."""
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
    """Подходы к стояку с четырёх сторон: стояк в выступе стены или в коробе — к нему
    подходят с той стороны, где прибор (ближайшая свободная ячейка по каждой оси). В стене
    (вне помещений) — не больше RISER_WALL: вдоль стены внутри неё труба не идёт."""
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
    """Дерево от источника: приборы по стоимости от источника; каждый — отводом от
    ближайшего места уже проложенных труб (или от источника). only_into — отвод только в
    трубы этого диаметра (унитаз Ø110 — только в Ø110 или в стояк); attach_to — отводы только
    от этих труб (общая линия группы от коллектора); main_d — Ø трубы, от которой есть отвод
    (воды: магистраль тройниковой — Ø20, общая линия умывальников — Ø16)."""
    heads = _heads(ctx, src)
    if not heads:
        for o in outlets:
            ctx.unreachable(o.fixture, kind)
        return
    fields = [ctx.field(h.cell) for h in heads]
    if ctx.prune is not None:  # запасной поиск без отсечения: прибор иначе недостижим
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
        # Поиск от прибора: до источника и до каждого места врезки в уже проложенные трубы
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
            if kind != "sewer" and parent.d < main_d:  # с отводом — магистраль Ø20
                k = ctx.net.pipes.index(parent)
                ctx.net.pipes[k] = replace(parent, d=main_d)
                tree[tree.index(parent)] = ctx.net.pipes[k]
        ctx.net.pipes.append(pipe)
        _open_holes(ctx, pipe)
        tree.append(pipe)


def _shape45(
    path: Sequence[Vec], parent: Pipe | None = None, along: float = 0.0
) -> tuple[list[Vec], float]:
    """Канализация по плану — только отводами 45°: участки — в восемь сторон, врезка в трубу
    parent — косым тройником (место врезки along сдвигается к стояку), изломы — отводами."""
    pts = b45.octilinear(path)
    if parent is not None:
        pts, along = b45.tee45(pts, parent.path, along)
    return b45.chamfer(pts), along


DEPTH_ERRORS = frozenset({"screed_depth", "screed_110", "hidden_height"})


def _sewer(ctx: _Ctx) -> None:
    """Канализация вариантами (SEWER_VARIANTS): обычный, через скрытые зоны, только вдоль
    стен; берётся вариант с наименьшей оценкой _score (ТЗ трассировки, п. 6)."""
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
                break  # ни ошибок, ни подиума, ни короба, ни середины комнаты
        if best is not None and best[1] != k:
            _rollback(ctx, mark)
            ctx.grid = ctx.sewer_grids[best[1]]
            _sewer_trees(ctx)
    finally:
        ctx.grid, ctx.ndirs, ctx.boxes_open, ctx.prune = water, 4, False, None


SewerScore = tuple[int, int, float, float, float]


def _score(net: Network) -> SewerScore:
    """Оценка варианта канализации, сравнение — по порядку: ошибок стяжки и скрытых зон,
    подиумов (не хватает перепада), мм короба над полом, мм посреди комнаты (дальше
    WALL_BAND_MM от стен вне скрытых зон), мм трубы плюс отводы по TURN_COST_MM."""
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
    # Прибор — к стояку, до которого путь короче; у каждого стояка своё дерево
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
        # Ø110 в стяжку не помещается вовсе: середина комнаты закрыта на любой длине
        ctx.prune = _height_prune(ctx.grid, _riser_invert(r), SLOPE_MIN[110], 110)
        _route_tree(ctx, "sewer", r.id, r, wc, only_into=110)
        ctx.prune = None
        _merge_drains(ctx, r, rest)
    _sewer_heights(ctx)


def _riser_invert(r: RiserNode) -> float:
    """Низ трубы у врезки в стояк, мм от плиты: ось врезки от чистого пола плюс стяжка минус
    радиус тройника Ø110 (труба Ø50 — через переход, низ вровень с тройником). Высоты
    канализации везде — низ трубы; ось ↔ низ — здесь и в _outlet_invert."""
    return SCREED_MM + r.inlet - RISER_TEE_D / 2


def _outlet_invert(o: Outlet) -> float:
    """Низ выпуска прибора, мм от плиты: ось от чистого пола плюс стяжка минус радиус."""
    return SCREED_MM + o.height - o.d / 2


def _riser_fields(ctx: _Ctx, r: RiserNode, d: int) -> list[tuple[_Approach, _Field]]:
    """Поиск от стояка с каждой стороны: с отсечением по высоте для Ø d (самый пологий
    уклон, что ему можно) и запасной — без отсечения, дороже на FALLBACK_COST: к прибору,
    к которому иначе не пройти (ошибку стяжки найдёт _evaluate)."""
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
    """Узел дерева канализации Ø50: прибор (leaf) или тройник J над двумя узлами. У каждого
    прибора узла — длина по трубе от его места подхода до ячейки узла (для высот)."""

    cell: int
    fld: _Field
    cost: np.ndarray  # стоимость пути от узла до каждой ячейки сетки
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
    """Путь по сетке от ячейки cell к узлу a (по течению — обратно)."""
    if cell == a.cell:
        return [a.fld.grid.center(cell)]
    return list(reversed(a.fld.path(cell)))


def _merge_drains(ctx: _Ctx, r: RiserNode, outlets: Sequence[Outlet]) -> None:
    """Приборы Ø50 к стояку r деревом с наименьшим расходом трубы (ТЗ «тройники»): для
    каждой пары узлов (A, B) — место тройника J с наименьшей стоимостью
    d(A, J) + d(B, J) + k·d(J, R) (d — путь по сетке отводами 45°, отвод — SEWER_BEND_COST,
    k — PIPE_WEIGHT магистрали); экономия пары — d(A, R) + d(B, R) − стоимость. Пары
    объединяются по убыванию экономии, J — новый узел; тройник недопустим, если с ним прибор,
    который напрямую укладывался в стяжку или в перепад, перестаёт укладываться, — тогда
    следующее по стоимости место, — или если ветка до тройника идёт посреди комнаты выше
    стяжки (длина — по полному пути прибор → тройник → стояк). Поиск от стояка — с
    отсечением по высоте (_height_prune), от приборов — с нижней оценкой длины. Узел, что
    ближе к трубе Ø110 (унитаза), чем к стояку, врезается в неё тройником 110×50.
    Соосность и вход под 45° — при сборке трубы (_shape45)."""
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
    # Ветки от приборов: длина до стояка неизвестна — нижняя оценка по прямой
    ctx.prune = _height_prune(grid, z0, slope, 50, lower=r.center)

    def to_riser(cell: int) -> tuple[list[Vec], float]:
        """От стояка до ячейки: хвост к стояку и путь по сетке."""
        k = min(range(len(heads)), key=lambda i: hfields[i].cost(cell))
        path = [*reversed(heads[k].tail), *hfields[k].path(cell)[1:]]
        return path, _plan_length(path) - heads[k].along

    nodes: list[_Merge] = []
    direct: dict[str, float] = {}  # мм по трубе от места подхода прибора до стояка
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
        """Ветка от тройника (leg[0]) к узлу: посреди комнаты низ трубы с Ø и слоем — не выше
        стяжки; s0 — мм по трубе от стояка до тройника."""
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
            leg = legs[id(n)]  # от тройника к узлу
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
        best: tuple[float, int, int, int] | None = None  # экономия, A, B, J
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
    """Место врезки узла Ø50 в трубу Ø110 тройником 110×50 (ТЗ трассировки, п. 4), если
    дешевле, чем свой путь к стояку, и ветка не выходит посреди комнаты выше стяжки."""
    best: tuple[float, Pipe, Vec, float] | None = None
    for p in big:
        for at, along in _tree_points(p):
            c = n.fld.cost(ctx.grid.nearest_free(at))
            if c >= to_riser - 1e-6 or (best is not None and c >= best[0]):
                continue
            leg = _between(n, ctx.grid.nearest_free(at))  # от тройника к узлу
            if leg_ok([at, *leg], along):
                best = (c, p, at, along)
    return (best[1], best[2], best[3]) if best is not None else None


def _emit(
    ctx: _Ctx, r: RiserNode, node: _Merge, prefix: list[Vec], parent: Pipe | None, along: float
) -> None:
    """Трубы из дерева: от начала (стояк или место на трубе-родителе) по «соосной» ветке
    каждого тройника до прибора — одна труба; вторые ветки — отводами от неё."""
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
    """Насколько ветка к child из тройника в cell продолжает магистраль: косинус угла
    (1 — соосно); ветка нулевой длины (прибор у тройника) — отвод."""
    path = _between(child, cell)
    if len(path) < 2 or incoming is None or incoming.length() < 1e-6:
        return -2.0
    d = path[1] - path[0]
    return d.dot(incoming) / (d.length() * incoming.length())


def _equivalent(path: Sequence[Vec], d: int) -> float:
    """Расход трубы в мм эквивалентной длины: вес метра по диаметру плюс отводы 45°."""
    return PIPE_WEIGHT[_norm(d)] * _plan_length(path) + SEWER_BEND_COST * b45.bends(path)


def _check_doors(ctx: _Ctx) -> None:
    """Вода через дверной проём — слабое место (канализации через дверь нельзя: её сетка
    без дверных проёмов)."""
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
SAMPLE = 25.0  # мм: шаг, с которым участок трассы делится по зонам


@dataclass(frozen=True)
class _Zones:
    """Где лежит точка трассы канализации: скрытая зона, стяжка (пол) или стена; у пола —
    ещё и у стены ли она (полоса WALL_BAND_MM вдоль стен и препятствий, без проёмов):
    там труба, что не помещается в стяжку, идёт по стене над полом."""

    hidden: tuple[tuple[str, BaseGeometry, float], ...]  # препятствие, место, высота верха
    floor: BaseGeometry
    edge: BaseGeometry
    walls: BaseGeometry  # грани стен и препятствий: середина комнаты — дальше WALL_BAND_MM

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
        # Полоса трассы у стен (сетка) плюс шаг: срез угла отводами 45° — тоже у стены
        edge = walls.boundary.buffer(WALL_BAND_MM + STEP)
        # Через проём (дверь, арку) над полом трубу не ведут — там ходят
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
        """Посреди комнаты: дальше WALL_BAND_MM от стен (скрытые зоны — не в счёт)."""
        return self.walls.distance(shapely.Point(v.as_tuple())) > WALL_BAND_MM + 1.0

    def at(self, v: Vec, z: float, d: int) -> tuple[Zone, str, float]:
        """Зона точки трассы; z — низ трубы от плиты, d — её Ø."""
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
    """Кусок трассы в одной зоне, по течению; s — мм по трассе от прибора до начала."""

    a: Vec
    za: float
    b: Vec
    zb: float
    zone: Zone
    obstacle: str
    height: float
    s: float


def _upto(path: Sequence[Vec], s: float) -> list[tuple[Vec, float]]:
    """Точки ломаной от начала до s мм по ней и расстояние каждой от начала."""
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
    """Трасса прибора по течению — от выпуска по полу до стояка: точки и низ трубы."""
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
    """Трасса прибора с уже заданными уклоном и началом: участки по зонам, спуск в стене,
    проверки стяжки, скрытых зон, перепада и отвода унитаза."""
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
    """Участки своей трубы по стене над полом — мм от начала её пути (own — длина пути;
    куски трассы считаются от прибора) — и верх трубы над чистым полом там."""
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
    """Высоты канализации обратным счётом от врезки в стояк (от плиты), все — низ трубы:
    у каждой трубы — уклон и низ у начала; у отвода начало — на трубе-родителе, низ вровень
    с её низом (тройник 110×50 — низ ветки не ниже низа магистрали). Уклон — один на трубу,
    из списка (ТЗ трассировки, п. 5): SLOPE; если с ним трасса не годится — SLOPE_MIN
    (Ø110, без отводов); если годится — SLOPE_MAX, когда трасса без отводов от неё, уклон
    родителя не меньше и короба над полом и середины комнаты не больше (магистраль не
    положе веток)."""
    net = ctx.net
    pipes = {p.id: p for p in net.pipes if p.kind == "sewer"}
    if not pipes:
        return
    zones = _Zones.of(ctx)
    risers = {r.id: r for r in net.risers}
    parents = {p.parent for p in pipes.values() if p.parent is not None}
    order = [p.id for p in net.pipes if p.kind == "sewer"]  # родитель проложен раньше отвода
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
    """Предупреждения трубы: много отводов (ревизия), через жилую комнату."""
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
    """Трассы канализации в формате ТЗ трассировки (out/sewer-routes.json): по прибору —
    диаметр, уклон, спуск в стене, участки по течению с зоной (z — низ трубы, мм от плиты),
    фасонные части своей трубы; ошибки — с местом на плане (мм модели). Итоги:
    totalLength — мм всех труб канализации (по полу, в стене, спуски), totalFittings —
    фасонных частей, savingVsDirect — мм эквивалентной длины (PIPE_WEIGHT, SEWER_BEND_COST),
    сэкономленные тройниками против подключения каждого прибора Ø50 отдельно."""
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
