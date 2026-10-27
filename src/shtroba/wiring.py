"""Проводка через распаечные коробки: топология, трассы и длины кабеля — из модели.

Правила варианта:
- кабель идёт только от щита к коробке, от щита к потребителю или от коробки к
  потребителю; от потребителя к коробке и от коробки к коробке — никогда;
- помещение — отдельная зона: коробка стоит в помещении и питает только его точки, её
  кабели не выходят за стены; в другое помещение кабель приходит от щита через дверные
  проёмы (routing.py). Исключение — выключатель: он врезается в коробку своего света, и
  если в помещении у группы только выключатели (у двери снаружи), ветка к ним идёт от
  ближайшей коробки группы через проём; своей коробки и линии от щита у них нет
  (решение 2026-10-25);
- коробка — на группу в помещении, если у группы там свет (любой) или две точки и
  больше; одна розетка группы в помещении питается прямо от щита; линий в коробке
  (питающая + ветки) не больше, чем вводов у 150×110 (BOX_SIZES, по нижней границе), —
  больше точек: коробки по зонам (split_points), каждая своей линией от щита; типоразмер —
  наименьший по числу линий (box_size), 190×140 — только в крайнем случае;
- отдельные линии (direct) идут от щита к каждой точке без коробок: сечение от
  HEAVY_SECTION мм² (варочная, духовка, бойлер), группа только из выводов к технике
  (кондиционер, рушникосушка) и слаботочка; в модели — Cable.direct;
- коробка стоит на стене в месте, где путь от щита плюс ветки до её точек — по трассе
  в обход стен, с поворотами (branch_reach) — наименьшие: под потолком, у группы по
  полу — на BOX_ABOVE_FLOOR от пола; если линии
  из такой коробки расходятся веером на FAN_ANGLE и больше (точки не только на её стене),
  коробка — на потолке внутри помещения, в самом выгодном месте не ближе
  routing.CLEARANCE к стенам (правило 2026-10-24; у трасс по полу — всегда на стене);
- трассы — под прямыми углами, в обход стен (тот же путь, что на листе): по потолку,
  у группы с route: floor — по полу в стяжке; не ближе routing.CLEARANCE (150 мм)
  к стенам, кроме подхода к точке на стене и прохода в проёме.

Длина линии = путь по плану + вертикаль от точки подключения до потолка (или пола) на
обоих концах + выпуски: у щита кабель выпускается до пола (BOARD_TAIL — высота щита),
на остальных подключениях — END_ALLOWANCE. Итог по марке — с запасом RESERVE.
Точки без группы (обычно слаботочка) в расчёт не входят.

Штробы (wall_chases) — вертикальные: от потолка вниз (или от пола вверх) к точке на
стене, у щита и у коробки. Спуски одной стены, если они ближе CHASE_SHARE друг к другу,
идут в общей штробе, не больше CHASE_CABLES кабелей в одной; длина общей штробы — до
самой дальней точки. У щита и коробки — по штробе на каждые CHASE_CABLES кабелей.
Силовые кабели и слаботочка (circuit) в одну штробу не кладутся, трассы потолка и пола —
тоже. Штроба до CHASE_NARROW кабелей — узкая, больше — широкая (своя цена в смете).

Ручные правки (wiring.yaml, из просмотра): коробка ставится в указанное место (на стене —
вдоль своей стены, не ближе BOX_CLEARANCE к углам; на потолке — внутри помещения), её
линии без ручной трассы прокладываются от нового места заново; линия с ручной трассой
идёт по ней, концы пристёгиваются к узлам источника и цели под прямыми углами. Правка,
у которой id теперь означает другую линию или коробку, не применяется (edit_notes).

Проходы через стены (wall_holes): трасса по потолку проходит в соседнее помещение над
дверью или проёмом — стену над ним сверлят; в одно отверстие — до HOLE_CABLES кабелей,
силовые и слаботочка — в разные. Трасса по полу проходит под проёмом — без сверления.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from shtroba.draw_electrical import (
    Anchor,
    board_anchor,
    group_key,
    point_anchor,
    stack_shifts,
)
from shtroba.draw_plan import RoomGeometry, room_geometries
from shtroba.geometry import Contour, Vec, WallSegment
from shtroba.layers import sheet
from shtroba.routing import (
    End,
    Grid,
    Router,
    fit_path,
    free_area,
    length,
    opening_strip,
    room_area,
)
from shtroba.schema import (
    Board,
    Cable,
    Electrical,
    ElectricalPoint,
    OpeningType,
    Plan,
    PointType,
    WireEdit,
    WiringEdits,
)

BOX_BELOW_CEILING = 200.0  # мм: от потолка до коробки
BOX_ABOVE_FLOOR = 300.0  # мм: от пола до коробки у трасс по полу
END_ALLOWANCE = 200.0  # мм: выпуск кабеля на каждое подключение, кроме щита
RESERVE = 0.15  # запас на итог по марке
BOX_STEP = 100.0  # мм: шаг перебора мест коробки вдоль стены
BOX_CLEARANCE = 150.0  # мм: от угла и от проёма до коробки
BOX_SPACING = 200.0  # мм: коробки разных групп в помещении не ближе этого
BOX_SIZE_MM = 2.5  # сторона квадрата коробки, мм листа
# Типоразмеры коробок и сколько линий (вводов) в них заводить — по нижней границе
# практики (решение 2026-10-25); 190×140 — только в крайнем случае
# Ключ — для прайса (junction_box.100x100), название — для сметы и подсказок
BOX_SIZES: tuple[tuple[str, int], ...] = (("80", 3), ("100x100", 6), ("150x110", 8))
BOX_LARGE = ("190x140", 10)
BOX_ORDER = (*(k for k, _ in BOX_SIZES), BOX_LARGE[0])
BOX_TITLES = {"80": "Ø80", "100x100": "100×100", "150x110": "150×110", "190x140": "190×140"}
BOX_BRANCHES = BOX_SIZES[-1][1] - 1  # веток на коробку: одна линия — питающая от щита
FAN_ANGLE = 90.0  # градусов: линии из коробки на стене расходятся шире — коробка на потолок
ON_WALL = 50.0  # мм: точка на линии стены коробки — «на её стене»
CHASE_SHARE = 150.0  # мм вдоль стены: спуски ближе — в общей штробе
CHASE_CABLES = 4  # кабелей в одной штробе, не больше
CHASE_NARROW = 2  # до стольких кабелей штроба узкая, больше — широкая
HOLE_CABLES = 4  # кабелей в одном отверстии через стену, не больше
HEAVY_SECTION = 4.0  # мм²: от этого сечения линия идёт от щита без коробок
POWER_TYPES = frozenset({PointType.SOCKET, PointType.OUTLET})
LOW_TYPES = frozenset({PointType.DATA, PointType.TV})  # слаботочка
SWITCH_TYPES = frozenset({PointType.SWITCH, PointType.PASS_SWITCH})
# Свет в помещении всегда идёт через коробку (решение 2026-10-21)
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
DEFAULT_MARK = {"power": "3x2.5", "light": "3x1.5", "data": "UTP cat.6", "tv": "RG-6"}

Route = Literal["ceiling", "floor"]
Circuit = Literal["power", "low"]  # силовые 230 В и слаботочка
ChaseKey = tuple[str, str, Route, Circuit]  # помещение, стена, плоскость трассы, цепь


@dataclass(frozen=True)
class JunctionBox:
    id: str
    label: str  # «К1» на чертеже
    room: str
    group: str
    anchor: Anchor
    route: Route = "ceiling"
    wet: bool = False  # во влажном помещении — коробка IP44
    size: str = "100x100"  # типоразмер по числу линий (box_size), ключ BOX_SIZES

    @property
    def on_ceiling(self) -> bool:
        return self.anchor.inward is None

    @property
    def rise_mm(self) -> float:
        """От коробки до плоскости трассы: потолка или пола; коробка на потолке — 0."""
        if self.on_ceiling:
            return 0.0
        return BOX_ABOVE_FLOOR if self.route == "floor" else BOX_BELOW_CEILING


@dataclass(frozen=True)
class Run:
    """Одна линия кабеля: щит → коробка, щит → точка или коробка → точка."""

    id: str
    group: str
    mark: str
    mark_assumed: bool  # марки нет в модели — взята по типу точек
    source: str  # board или id коробки
    target: str  # id коробки или точки
    path: tuple[Vec, ...]
    plan_mm: float
    rise_start_mm: float  # от начала линии (щит или коробка) до потолка или пола
    rise_end_mm: float  # по стене от потолка (пола) до конца линии; потолочная точка — 0
    ends_mm: float
    route: Route = "ceiling"
    circuit: Circuit = "power"

    @property
    def vertical_mm(self) -> float:
        return self.rise_start_mm + self.rise_end_mm

    @property
    def length_mm(self) -> float:
        return self.plan_mm + self.vertical_mm + self.ends_mm


@dataclass(frozen=True)
class Chase:
    """Штроба по стене от потолка вниз (route floor — от пола вверх): kind — point
    (к точкам), board (у щита), box (у коробки)."""

    kind: str
    room: str
    wall: str  # id стены; у коробки — ""
    offset: float  # от начала стены до середины штробы; у коробки — 0
    length_mm: float
    cables: int
    targets: tuple[str, ...] = ()  # id точек, к которым идут кабели штробы
    route: Route = "ceiling"
    circuit: Circuit = "power"

    @property
    def wide(self) -> bool:
        return self.cables > CHASE_NARROW


@dataclass(frozen=True)
class Hole:
    """Отверстие в стене над дверью или проёмом для трасс по потолку."""

    passage: str  # id двери или проёма
    cables: int
    circuit: Circuit = "power"
    runs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Wiring:
    ceiling_height: float
    height_assumed: bool  # высоты потолка нет в room.yaml — 2700 по умолчанию
    boxes: tuple[JunctionBox, ...]
    runs: tuple[Run, ...]
    skipped: tuple[str, ...] = field(default=())  # точки без группы
    chases: tuple[Chase, ...] = field(default=())
    holes: tuple[Hole, ...] = field(default=())
    # Помещения и проёмы (routing.free_area) — чтобы пучок на листе не заходил на стены
    free: BaseGeometry | None = field(default=None, compare=False, repr=False)
    # Ручные правки: «wire:id» и «box:id», что применены; замечания — (путь в wiring.yaml, текст)
    edited: frozenset[str] = field(default=frozenset())
    edit_notes: tuple[tuple[str, str], ...] = field(default=())

    @property
    def chase_mm(self) -> float:
        return sum(c.length_mm for c in self.chases)

    def chase_length(self, wide: bool) -> float:
        """Длина узких или широких штроб, мм."""
        return sum(c.length_mm for c in self.chases if c.wide == wide)

    def by_mark(self) -> dict[str, float]:
        """Длина по маркам, м, без запаса."""
        out: dict[str, float] = defaultdict(float)
        for r in self.runs:
            out[r.mark] += r.length_mm / 1000
        return dict(sorted(out.items()))


def _manhattan(a: Vec, b: Vec) -> float:
    return abs(a.x - b.x) + abs(a.y - b.y)


def _end(a: Anchor) -> End:
    return End(a.node, a.wall_is_vertical)


def _box_candidates(g: RoomGeometry, depth: float) -> list[Anchor]:
    out: list[Anchor] = []
    for seg in g.contour.segments:
        spans = [(o.offset, o.offset + o.width) for o in g.room.openings if o.wall == seg.id]
        offset = BOX_CLEARANCE
        while offset <= seg.length - BOX_CLEARANCE:
            if all(not (a - BOX_CLEARANCE < offset < b + BOX_CLEARANCE) for a, b in spans):
                out.append(Anchor(seg.point_at(offset), seg.inward, seg.direction, depth))
            offset += BOX_STEP
    return out


# Стоимость веток из места коробки до её точек: сумма путей по трассе в обход стен
Reach = Callable[[Vec], float]


def branch_reach(g: RoomGeometry, targets: Sequence[Anchor]) -> Reach:
    """Сумма путей от места до точек по трассе внутри помещения (с поворотами), а не по
    прямой: коробка не встанет за перегородку от своих точек."""
    area = room_area(g)
    routers = [Router(area, _end(t)) for t in targets]
    return lambda p: sum(r.cost(p) for r in routers)


def _place_box(g: RoomGeometry, board: Router, reach: Reach, taken: Sequence[Vec]) -> Anchor | None:
    """Место на стене, где путь от щита плюс ветки до точек наименьшие."""
    best: tuple[float, Anchor] | None = None
    for cand in _box_candidates(g, sheet(BOX_SIZE_MM)):
        if any(_manhattan(cand.node, t) < BOX_SPACING for t in taken):
            continue
        cost = board.cost(cand.node) + reach(cand.node)
        if best is None or cost < best[0] - 1e-6:
            best = (cost, cand)
    return None if best is None else best[1]


def box_size(lines: int) -> str:
    """Коробка под число линий (питающая + ветки) — по нижней границе вводов; 190×140 —
    только если линий больше, чем у 150×110 (на практике — не бывает: группа делится)."""
    return next((name for name, cap in BOX_SIZES if lines <= cap), BOX_LARGE[0])


def split_points(points: Sequence[Vec], cap: int) -> list[list[int]]:
    """Точки по зонам не больше cap в каждой: деление пополам (с учётом числа зон) по более
    протяжённой оси — соседние точки попадают в одну коробку."""
    idx = list(range(len(points)))

    def split(part: list[int]) -> list[list[int]]:
        if len(part) <= cap:
            return [part]
        k = math.ceil(len(part) / cap)
        xs = [points[i].x for i in part]
        ys = [points[i].y for i in part]
        axis = 0 if max(xs) - min(xs) >= max(ys) - min(ys) else 1
        part = sorted(part, key=lambda i: (points[i].x, points[i].y)[axis])
        cut = round(len(part) * (k // 2) / k)
        return split(part[:cut]) + split(part[cut:])

    return split(idx)


def fan_angle(box: Anchor, targets: Sequence[Anchor]) -> float:
    """На сколько градусов расходятся линии из коробки на стене к её точкам: наибольший угол
    между направлениями на точки. Все точки на стене коробки (ряд розеток под ней) — 0."""
    assert box.wall_dir is not None
    d = box.wall_dir

    def on_wall(t: Anchor) -> bool:
        v = t.pos - box.pos
        return abs(d.x * v.y - d.y * v.x) < ON_WALL

    if all(on_wall(t) for t in targets):
        return 0.0
    angles = [math.atan2(t.node.y - box.node.y, t.node.x - box.node.x) for t in targets]
    widest = 0.0
    for a in angles:
        for b in angles:
            diff = abs(a - b) % (2 * math.pi)
            widest = max(widest, min(diff, 2 * math.pi - diff))
    return math.degrees(widest)


def _place_ceiling_box(
    g: RoomGeometry, board: Router, reach: Reach, taken: Sequence[Vec], depth: float
) -> Anchor | None:
    """Коробка на потолке: место внутри помещения не ближе CLEARANCE к стенам, где путь от
    щита плюс ветки до точек наименьшие (ближе к середине точек — к центру помещения)."""
    best: tuple[float, Vec] | None = None
    for p in Grid.of(room_area(g)).free_points():
        if any(_manhattan(p, t) < BOX_SPACING for t in taken):
            continue
        cost = board.cost(p) + reach(p)
        if best is None or cost < best[0] - 1e-6:
            best = (cost, p)
    return None if best is None else Anchor(best[1], None, None, depth)


def _cable(elec: Electrical, group: str) -> Cable | None:
    return next((c for c in elec.cables if c.group == group), None)


def _mark(cable: Cable | None, points: Sequence[ElectricalPoint]) -> tuple[str, bool]:
    if cable is not None:
        return cable.cable, False
    if all(p.type in LOW_TYPES for p in points):
        kind = "tv" if all(p.type is PointType.TV for p in points) else "data"
    else:
        kind = "power" if any(p.type in POWER_TYPES for p in points) else "light"
    return DEFAULT_MARK[kind], True


def section(mark: str) -> float:
    """Сечение жилы из марки: «3x6» → 6, «5х2,5» → 2.5; не разобрать — 0."""
    m = re.search(r"[xх×]\s*(\d+(?:[.,]\d+)?)", mark)
    return float(m.group(1).replace(",", ".")) if m else 0.0


def _direct(
    cable: Cable | None, mark: str, points: Sequence[ElectricalPoint], circuit: Circuit
) -> bool:
    """Отдельные линии от щита без коробок."""
    if cable is not None and cable.direct is not None:
        return cable.direct
    return (
        circuit == "low"
        or section(mark) >= HEAVY_SECTION
        or all(p.type is PointType.OUTLET for p in points)
    )


def _rise(pt: ElectricalPoint, ceiling: float, route: Route) -> float:
    """От точки подключения до плоскости трассы, мм: до потолка (потолочная точка — 0)
    или до пола (потолочная точка — вся высота стены)."""
    if pt.ceiling is not None:
        return ceiling if route == "floor" else 0.0
    assert pt.height is not None  # у точки на стене высота обязательна (валидация)
    return pt.height if route == "floor" else max(ceiling - pt.height, 0.0)


@dataclass(frozen=True)
class _Link:
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
    cross: bool = False  # ветка коробки в соседнее помещение: выключатель у двери снаружи


@dataclass(frozen=True)
class _Context:
    """Общее для всех групп: план, точки подключения, щит и трассы от него."""

    plan: Plan
    geoms: dict[str, RoomGeometry]
    anchors: dict[str, Anchor]
    board: Board
    from_board: Router
    free: BaseGeometry  # вся квартира с проёмами — для веток к выключателям за дверью

    @property
    def ceiling(self) -> float:
        return self.plan.ceiling_height


def box_wiring(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical,
    edits: WiringEdits | None = None,
) -> Wiring | None:
    """Проводка через коробки; None — нет щита или точек с группами. edits — ручные правки
    из wiring.yaml: места коробок и трассы линий."""
    if elec.board is None:
        return None
    grouped = [p for p in elec.points if p.group]
    if not grouped:
        return None
    geoms = {g.room.id: g for g in room_geometries(plan, contours)}
    shifts = stack_shifts(elec.points)
    free = free_area(list(geoms.values()))
    ctx = _Context(
        plan,
        geoms,
        {p.id: point_anchor(p, geoms, shifts[k]) for k, p in enumerate(elec.points)},
        elec.board,
        Router(free, _end(board_anchor(elec.board, geoms))),
        free,
    )
    boxes: list[JunctionBox] = []
    links: list[_Link] = []
    for group in sorted({p.group for p in grouped if p.group}, key=group_key):
        pts = [p for p in grouped if p.group == group]
        links += _group_links(ctx, elec, group, pts, boxes)
    boxes = _sized(boxes, links)
    edited: set[str] = set()
    notes: list[tuple[str, str]] = []
    if edits is not None:
        boxes, links = _moved_boxes(ctx, boxes, links, edits, edited, notes)
    runs = _route_runs(ctx, links, boxes)
    if edits is not None:
        runs = _manual_runs(runs, edits.wires, free, edited, notes)
    height_assumed = "ceiling_height" not in plan.model_fields_set
    skipped = tuple(p.id for p in elec.points if not p.group)
    chases = wall_chases(runs, elec.points, elec.board, boxes)
    holes = wall_holes(runs, passages(list(geoms.values())))
    return Wiring(
        ctx.ceiling,
        height_assumed,
        tuple(boxes),
        tuple(runs),
        skipped,
        chases,
        holes,
        free,
        frozenset(edited),
        tuple(notes),
    )


def box_wall(g: RoomGeometry, anchor: Anchor) -> WallSegment | None:
    """Стена, на которой стоит коробка (символ); на потолке — None."""
    if anchor.wall_dir is None:
        return None
    for seg in g.contour.segments:
        v = anchor.pos - seg.start
        along = v.dot(seg.direction)
        if (
            seg.direction.dot(anchor.wall_dir) > 0.99
            and abs(seg.direction.cross(v)) < 1.0
            and -1.0 <= along <= seg.length + 1.0
        ):
            return seg
    return None


def moved_anchor(g: RoomGeometry, anchor: Anchor, at: Vec) -> Anchor | None:
    """Новое место коробки: на стене — проекция на её стену, не ближе BOX_CLEARANCE к углам;
    на потолке — точка, если она внутри помещения. None — места нет."""
    if anchor.inward is None:
        inside = room_area(g).contains(Point(at.x, at.y))
        return Anchor(at, None, None, anchor.depth) if inside else None
    seg = box_wall(g, anchor)
    if seg is None or seg.length < 2 * BOX_CLEARANCE:
        return None
    offset = min(
        max((at - seg.start).dot(seg.direction), BOX_CLEARANCE), seg.length - BOX_CLEARANCE
    )
    return Anchor(seg.point_at(offset), seg.inward, seg.direction, anchor.depth)


def _moved_boxes(
    ctx: _Context,
    boxes: Sequence[JunctionBox],
    links: Sequence[_Link],
    edits: WiringEdits,
    edited: set[str],
    notes: list[tuple[str, str]],
) -> tuple[list[JunctionBox], list[_Link]]:
    """Коробки — в места из wiring.yaml; линия щит → коробка ведёт к новому месту."""
    by_id = {b.id: b for b in boxes}
    out = list(boxes)
    moved: dict[str, Anchor] = {}
    for bid, e in sorted(edits.boxes.items()):
        b = by_id.get(bid)
        where = f"boxes.{bid}"
        if b is None or (b.room, b.group) != (e.room, e.group):
            now = "её нет" if b is None else f"это коробка {b.group} в {b.room}"
            notes.append(
                (where, f"коробка {e.group} в {e.room} не найдена ({now}) — не перенесена")
            )
            continue
        spot = moved_anchor(ctx.geoms[b.room], b.anchor, Vec(*e.at))
        if spot is None:
            notes.append((where, f"место {e.at} вне помещения {b.room} — коробка не перенесена"))
            continue
        moved[bid] = spot
        out[out.index(b)] = replace(b, anchor=spot)
        edited.add(f"box:{bid}")
    new_links = [
        replace(ln, target_anchor=moved[ln.target]) if ln.target in moved else ln for ln in links
    ]
    return out, new_links


def _manual_runs(
    runs: Sequence[Run],
    wires: dict[str, WireEdit],
    free: BaseGeometry,
    edited: set[str],
    notes: list[tuple[str, str]],
) -> list[Run]:
    """Линии с ручной трассой из wiring.yaml; концы — в узлах источника и цели."""
    by_id = {r.id: r for r in runs}
    manual: dict[str, Run] = {}
    inside = free.buffer(1.0)
    for rid, e in sorted(wires.items()):
        r = by_id.get(rid)
        where = f"wires.{rid}"
        if r is None or (r.source, r.target) != (e.from_, e.to):
            now = "её нет" if r is None else f"это линия {r.source} → {r.target}"
            notes.append((where, f"линия {e.from_} → {e.to} не найдена ({now}) — автотрасса"))
            continue
        path = tuple(fit_path([Vec(*p) for p in e.path], r.path[0], r.path[-1]))
        if not inside.covers(LineString([v.as_tuple() for v in path])):
            notes.append((where, "ручная трасса проходит сквозь стену"))
        manual[rid] = replace(r, path=path, plan_mm=length(path))
        edited.add(f"wire:{rid}")
    return [manual.get(r.id, r) for r in runs]


def _group_links(
    ctx: _Context,
    elec: Electrical,
    group: str,
    pts: Sequence[ElectricalPoint],
    boxes: list[JunctionBox],
) -> list[_Link]:
    """Линии одной группы по помещениям: через коробку или каждая точка от щита.
    Новые коробки дописываются в boxes."""
    cable = _cable(elec, group)
    mark, assumed = _mark(cable, pts)
    route: Route = "floor" if cable is not None and cable.route == "floor" else "ceiling"
    circuit: Circuit = "low" if all(p.type in LOW_TYPES for p in pts) else "power"
    no_boxes = _direct(cable, mark, pts, circuit)
    height = ctx.board.height
    board_rise = height if route == "floor" else max(ctx.ceiling - height, 0.0)
    links: list[_Link] = []

    def link(src: str, dst: str, b: Anchor, up: float, down: float, cross: bool = False) -> None:
        links.append(_Link(group, mark, assumed, src, dst, b, up, down, route, circuit, cross))

    def direct(p: ElectricalPoint) -> None:
        link("board", p.id, ctx.anchors[p.id], board_rise, _rise(p, ctx.ceiling, route))

    # Выключатель врезается в коробку своего света: в помещении, где у группы только
    # выключатели (у двери снаружи), отдельной коробки и линии от щита у них нет
    lit = {p.room for p in pts if p.type not in SWITCH_TYPES}
    outside = [] if no_boxes else [p for p in pts if p.type in SWITCH_TYPES and p.room not in lit]
    for room in ctx.plan.rooms:
        here = [p for p in pts if p.room == room.id and p not in outside]
        if not here:
            continue
        has_light = any(p.type in LIGHT_TYPES for p in here)
        if no_boxes or not (len(here) >= 2 or has_light):
            for p in here:
                direct(p)
            continue
        # Не больше BOX_BRANCHES веток на коробку: больше точек — коробки по зонам
        zones = split_points([ctx.anchors[p.id].node for p in here], BOX_BRANCHES)
        for zone in zones:
            part = [here[i] for i in zone]
            spot = _box_spot(ctx, room.id, part, boxes, route)
            if spot is None:  # на стенах нет места под коробку — каждая точка от щита
                for p in part:
                    direct(p)
                continue
            n = len(boxes) + 1
            size = box_size(len(part) + 1)
            box = JunctionBox(f"box_{n}", f"К{n}", room.id, group, spot, route, room.wet, size)
            boxes.append(box)
            link("board", box.id, spot, board_rise, box.rise_mm)
            for p in part:
                link(box.id, p.id, ctx.anchors[p.id], box.rise_mm, _rise(p, ctx.ceiling, route))
    own = [b for b in boxes if b.group == group]
    for p in outside:
        near = _nearest_box(ctx, own, ctx.anchors[p.id])
        if near is None:  # у группы нет коробки — выключатель от щита
            direct(p)
            continue
        rise = _rise(p, ctx.ceiling, route)
        link(near.id, p.id, ctx.anchors[p.id], near.rise_mm, rise, cross=True)
    return links


def _nearest_box(ctx: _Context, boxes: Sequence[JunctionBox], target: Anchor) -> JunctionBox | None:
    """Коробка группы, от которой путь до точки по квартире (через проёмы) короче."""
    best: tuple[float, JunctionBox] | None = None
    for b in boxes:
        cost = Router(ctx.free, _end(b.anchor)).cost(target.node)
        if best is None or cost < best[0]:
            best = (cost, b)
    return None if best is None else best[1]


def _sized(boxes: Sequence[JunctionBox], links: Sequence[_Link]) -> list[JunctionBox]:
    """Типоразмер коробки — по итоговому числу линий, с выключателями из-за двери."""
    lines = {b.id: 1 + sum(1 for ln in links if ln.source == b.id) for b in boxes}
    return [replace(b, size=box_size(lines[b.id])) for b in boxes]


def _box_spot(
    ctx: _Context,
    room: str,
    part: Sequence[ElectricalPoint],
    boxes: Sequence[JunctionBox],
    route: Route,
) -> Anchor | None:
    """Место коробки для точек зоны: на стене, а при веере линий — на потолке."""
    g = ctx.geoms[room]
    taken = [b.anchor.node for b in boxes if b.room == room]
    fan = [ctx.anchors[p.id] for p in part]
    reach = branch_reach(g, fan)
    spot = _place_box(g, ctx.from_board, reach, taken)
    if spot is not None and route == "ceiling" and fan_angle(spot, fan) >= FAN_ANGLE:
        depth = sheet(BOX_SIZE_MM)
        spot = _place_ceiling_box(g, ctx.from_board, reach, taken, depth) or spot
    return spot


def _route_runs(ctx: _Context, links: Sequence[_Link], boxes: Sequence[JunctionBox]) -> list[Run]:
    """Трассы линий: от щита — по всей квартире, от коробки — только внутри её помещения."""
    routers = {b.id: Router(room_area(ctx.geoms[b.room]), _end(b.anchor)) for b in boxes}
    # Ветка к выключателю за дверью — по всей квартире через проём
    wide = {
        b.id: Router(ctx.free, _end(b.anchor))
        for b in boxes
        if any(ln.cross and ln.source == b.id for ln in links)
    }
    board_tail = ctx.board.height  # выпуск в щите — до пола
    runs: list[Run] = []
    for k, ln in enumerate(links):
        if ln.source == "board":
            router = ctx.from_board
        else:
            router = wide[ln.source] if ln.cross else routers[ln.source]
        path = tuple(router.route(_end(ln.target_anchor)))
        runs.append(
            Run(
                id=f"wire_{k + 1}",
                group=ln.group,
                mark=ln.mark,
                mark_assumed=ln.mark_assumed,
                source=ln.source,
                target=ln.target,
                path=path,
                plan_mm=length(path),
                rise_start_mm=ln.source_rise,
                rise_end_mm=ln.target_rise,
                ends_mm=END_ALLOWANCE + (board_tail if ln.source == "board" else END_ALLOWANCE),
                route=ln.route,
                circuit=ln.circuit,
            )
        )
    return runs


def wall_chases(
    runs: Sequence[Run],
    points: Sequence[ElectricalPoint],
    board: Board | None,
    boxes: Sequence[JunctionBox],
) -> tuple[Chase, ...]:
    """Штробы по стенам: общие для спусков рядом (CHASE_SHARE), до CHASE_CABLES кабелей."""
    by_id = {p.id: p for p in points}
    drops: dict[ChaseKey, list[tuple[float, float, str]]] = defaultdict(list)
    for r in runs:
        p = by_id.get(r.target)
        if r.rise_end_mm <= 0 or p is None or p.wall is None or p.offset is None:
            continue
        drops[(p.room, p.wall, r.route, r.circuit)].append((p.offset, r.rise_end_mm, p.id))
    out: list[Chase] = []
    for key, items in sorted(drops.items()):
        group: list[tuple[float, float, str]] = []
        for item in sorted(items):
            if group and (item[0] - group[0][0] > CHASE_SHARE or len(group) == CHASE_CABLES):
                out.append(_shared(key, group))
                group = []
            group.append(item)
        out.append(_shared(key, group))

    def bundle(kind: str, room: str, wall: str, offset: float, rs: Sequence[Run]) -> None:
        by_kind: dict[tuple[Route, Circuit], list[Run]] = defaultdict(list)
        for r in rs:
            by_kind[(r.route, r.circuit)].append(r)
        for (route, circuit), same in sorted(by_kind.items()):
            n = len(same)
            for k in range(math.ceil(n / CHASE_CABLES)):
                cables = min(CHASE_CABLES, n - k * CHASE_CABLES)
                rise = same[0].rise_start_mm
                out.append(Chase(kind, room, wall, offset, rise, cables, (), route, circuit))

    from_board = [r for r in runs if r.source == "board" and r.rise_start_mm > 0]
    if board is not None and from_board:
        bundle("board", board.room, board.wall, board.offset, from_board)
    for b in boxes:
        if b.on_ceiling:  # на потолке — без штробы в стене
            continue
        n = sum(1 for r in runs if b.id in (r.source, r.target))
        for k in range(math.ceil(n / CHASE_CABLES)):
            cables = min(CHASE_CABLES, n - k * CHASE_CABLES)
            out.append(Chase("box", b.room, "", 0.0, b.rise_mm, cables, (), b.route))
    return tuple(out)


def _shared(key: ChaseKey, group: Sequence[tuple[float, float, str]]) -> Chase:
    """Общая штроба группы спусков: середина по стене, длина — до самой дальней точки."""
    room, wall, route, circuit = key
    offsets = [g[0] for g in group]
    return Chase(
        "point",
        room,
        wall,
        (min(offsets) + max(offsets)) / 2,
        max(g[1] for g in group),
        len(group),
        tuple(g[2] for g in group),
        route,
        circuit,
    )


def passages(geoms: Sequence[RoomGeometry]) -> list[tuple[str, Polygon]]:
    """Двери и проёмы между помещениями: id и место на плане. Пара «дверь в одной
    комнате — проём в соседней на том же месте» — один проход с id двери."""
    out: list[tuple[str, Polygon]] = []
    for g in geoms:
        for op in g.room.openings:
            if op.type is OpeningType.WINDOW:
                continue
            strip = opening_strip(g, op)
            same = next(
                (
                    k
                    for k, (_, s) in enumerate(out)
                    if s.intersection(strip).area > 0.5 * min(s.area, strip.area)
                ),
                None,
            )
            if same is None:
                out.append((op.id, strip))
            elif op.type is OpeningType.DOOR:
                out[same] = (op.id, out[same][1])
    return out


def wall_holes(runs: Sequence[Run], passes: Sequence[tuple[str, Polygon]]) -> tuple[Hole, ...]:
    """Отверстия над дверями и проёмами для трасс по потолку, до HOLE_CABLES кабелей."""
    lines = [
        (r, LineString([v.as_tuple() for v in r.path]))
        for r in runs
        if r.route == "ceiling" and len(r.path) > 1
    ]
    out: list[Hole] = []
    for pid, strip in passes:
        through: dict[Circuit, list[str]] = defaultdict(list)
        for r, line in lines:
            if line.intersection(strip).length > 1.0:
                through[r.circuit].append(r.id)
        for circuit, ids in sorted(through.items()):
            for k in range(0, len(ids), HOLE_CABLES):
                chunk = tuple(ids[k : k + HOLE_CABLES])
                out.append(Hole(pid, len(chunk), circuit, chunk))
    return tuple(out)
