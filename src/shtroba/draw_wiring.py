"""Отрисовка проводки через коробки и таблица кабелей на её лист.

Расчёт — в wiring.py; здесь только то, что попадает в DXF: коробки, линии кабеля
по группам (цвет группы как на листе электрики) и таблица «группа → марка → длина».

Кабели, чьи трассы лежат на одной линии, идут пучком: у каждого своя полоса со сдвигом
LANE_MM на листе (lanes), перекрывающиеся кабели в одну полосу не попадают; пучок не шире
BAND_MM и не заходит на стены: у стены сдвигается от неё, а шаг сжимается, только если места
между стенами меньше, чем нужно пучку (clearance). Линия режется
на отрезки, где набор кабелей не меняется (bundles); над каждым — одна подпись сбоку
от пучка: длина отрезка, м, и число кабелей, если их больше одного: «L2,0 ×3».
У точки на стене — спуск «↓h1,9», у щита — подъём «↑h1,0»; у трасс по полу (свой слой,
штрихпунктир) наоборот: к точке — подъём от пола «↑h0,3», у щита — спуск «↓h1,7». Пучки
считаются отдельно для потолка и пола. Повороты скруглены (дуга в той же полилинии).
Подпись не ставится поверх трасс, коробок, точек и других подписей: пробуются
обе стороны и несколько мест вдоль отрезка; не нашлось места — подписи нет (длина есть
в таблице и в журнале). Длины считаются по исходной трассе (wiring.py): сдвиг полос
и скругления их не меняют.
"""

from __future__ import annotations

import csv
import itertools
import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ezdxf.layouts.layout import Modelspace
from shapely import STRtree
from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry

from shtroba.draw_electrical import group_colors
from shtroba.draw_plan import add_text
from shtroba.geometry import Vec
from shtroba.ids import tagged
from shtroba.layers import (
    TEXT_SMALL_MM,
    W_BOX,
    W_CABLE,
    W_CABLE_FLOOR,
    W_TEXT,
    sheet,
    text_width,
)
from shtroba.routing import CLEARANCE
from shtroba.schema import Electrical
from shtroba.tables import Column, Mark, Table
from shtroba.texts import Language, tr
from shtroba.wiring import (
    BOX_SIZE_MM,
    CHASE_CABLES,
    CHASE_NARROW,
    CHASE_SHARE,
    HOLE_CABLES,
    JunctionBox,
    Wiring,
)

LABEL_GAP_MM = 1.0
FILLET_MM = 1.5  # радиус поворота трассы на листе
LANE_MM = 0.7  # шаг полос кабелей в пучке на листе: линии не сливаются (решение 2026-10-24)
BAND_MM = 14.0  # пучок не шире этого на листе: в большом пучке шаг меньше
WALL_CLEAR_MM = 0.4  # от крайней линии пучка до стены на листе
_SAMPLES = (0.1, 0.3, 0.5, 0.7, 0.9)  # где вдоль участка мерить место до стен, доли длины
LENGTH_MM = 1.8  # высота подписи длины на листе
# Обозначения в подписях (решение 2026-10-24): длина участка «L1,4 ×3», спуск «↓h1,9» — по
# вертикали, как высота точки «h300» на листе электрики; цифры без букв не читались
LENGTH = "L"
VERT = "h"
LENGTH_OFFSET_MM = 0.6  # от линии (края пучка) до подписи
LENGTH_SLOTS = (0.5, 0.3, 0.7, 0.15, 0.85)  # места подписи вдоль отрезка, доли длины
POINT_CLEAR_MM = 2.5  # вокруг точки подключения подписи не ставим
_TOL = 1.0  # мм модели: точки на одной линии


def draw_wiring(msp: Modelspace, wiring: Wiring, elec: Electrical) -> None:
    colors = group_colors(elec)
    paths, plane_bundles = lay_out(wiring)
    labels = _Labels(paths)
    size = sheet(BOX_SIZE_MM)
    for b in wiring.boxes:
        labels.block(Point(_box_center(b, size).as_tuple()).buffer(size))
    _draw_runs(msp, wiring, paths, labels, colors)
    _draw_bundle_lengths(msp, wiring, plane_bundles, labels, colors)
    _draw_board_rises(msp, wiring, paths, labels)
    _draw_boxes(msp, wiring)


def lay_out(wiring: Wiring) -> tuple[list[list[Vec]], list[Bundle]]:
    """Пути линий со сдвигом полос и отрезки пучков — отдельно по потолку и по полу
    (номера линий в пучках — в общем списке wiring.runs)."""
    paths: list[list[Vec]] = [list(r.path) for r in wiring.runs]
    plane_bundles: list[Bundle] = []
    for route in ("ceiling", "floor"):
        idx = [k for k, r in enumerate(wiring.runs) if r.route == route]
        segs = segments([wiring.runs[k].path for k in idx])
        margin = max(sheet(WALL_CLEAR_MM), CLEARANCE)  # пучок — тоже не ближе CLEARANCE к стенам
        room = clearance(wiring.free, margin) if wiring.free is not None else None
        offsets = lanes(segs, sheet(LANE_MM), sheet(BAND_MM), room)
        for j, k in enumerate(idx):
            path = wiring.runs[k].path
            paths[k] = offset_path(path, [offsets.get((j, i), 0.0) for i in range(len(path) - 1)])
        plane_bundles += [
            Bundle(b.axis, b.fixed, b.lo, b.hi, tuple(idx[j] for j in b.runs), b.band)
            for b in bundles(segs, offsets)
        ]
    return paths, plane_bundles


def _draw_runs(
    msp: Modelspace,
    wiring: Wiring,
    paths: Sequence[Sequence[Vec]],
    labels: _Labels,
    colors: dict[str, int],
) -> None:
    """Линии со скруглёнными поворотами и спуск (подъём у трасс по полу) у точки."""
    for k, run in enumerate(wiring.runs):
        floor = run.route == "floor"
        attribs: dict[str, object] = {"layer": (W_CABLE_FLOOR if floor else W_CABLE).name}
        if run.group in colors:
            attribs["true_color"] = colors[run.group]
        with tagged(msp, "wire", run.id):
            msp.add_lwpolyline(fillet(paths[k], sheet(FILLET_MM)), format="xyb", dxfattribs=attribs)
            if run.rise_end_mm > 0 and not run.target.startswith("box_"):
                arrow = "↑" if floor else "↓"
                placed = labels.place_end(
                    paths[k], f"{arrow}{VERT}{_m(run.rise_end_mm)}", at_end=True
                )
                if placed is not None:
                    text, at, angle = placed
                    add_text(
                        msp, text, at, LENGTH_MM, W_TEXT.name, angle, color=colors.get(run.group)
                    )


def _draw_bundle_lengths(
    msp: Modelspace,
    wiring: Wiring,
    plane_bundles: Sequence[Bundle],
    labels: _Labels,
    colors: dict[str, int],
) -> None:
    """Подпись на отрезок пучка: длина, м, и число кабелей, если их больше одного."""
    for bundle in plane_bundles:
        runs = [wiring.runs[k] for k in bundle.runs]
        text = length_label(bundle.length, len(runs))
        placed = labels.place_bundle(text, bundle)
        if placed is None:
            continue
        text, at, angle = placed
        groups = {r.group for r in runs}
        color = colors.get(next(iter(groups))) if len(groups) == 1 else None
        with tagged(msp, "wire", runs[0].id):
            add_text(msp, text, at, LENGTH_MM, W_TEXT.name, angle, color=color)


def _draw_board_rises(
    msp: Modelspace, wiring: Wiring, paths: Sequence[Sequence[Vec]], labels: _Labels
) -> None:
    """У щита — подъём к потолку «↑» и спуск к полу «↓», по одной подписи на плоскость."""
    for route, arrow in (("ceiling", "↑"), ("floor", "↓")):
        board = next(
            (
                k
                for k, r in enumerate(wiring.runs)
                if r.source == "board" and r.rise_start_mm and r.route == route
            ),
            None,
        )
        if board is None:
            continue
        rise = wiring.runs[board].rise_start_mm
        placed = labels.place_end(paths[board], f"{arrow}{VERT}{_m(rise)}", at_end=False)
        if placed is not None:
            text, at, angle = placed
            with tagged(msp, "board", "board"):
                add_text(msp, text, at, LENGTH_MM, W_TEXT.name, angle)


def _box_center(b: JunctionBox, size: float) -> Vec:
    a = b.anchor
    return a.pos if a.inward is None else a.pos + a.inward * (size / 2)


def _draw_boxes(msp: Modelspace, wiring: Wiring) -> None:
    """Коробки — квадрат у стены (на потолке — по осям, в точке коробки) и подпись «К1»."""
    size = sheet(BOX_SIZE_MM)
    half = size / 2
    for b in wiring.boxes:
        a = b.anchor
        across, along = (a.inward, a.wall_dir) if a.inward is not None else (Vec(0, 1), Vec(1, 0))
        assert along is not None
        c = _box_center(b, size)
        corners = [
            c + along * sx * half + across * sy * half
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))
        ]
        with tagged(msp, "box", b.id):
            msp.add_lwpolyline(
                [p.as_tuple() for p in corners], close=True, dxfattribs={"layer": W_BOX.name}
            )
            label_at = c + across * (half + sheet(LABEL_GAP_MM)) + along * half
            add_text(msp, b.label, label_at, TEXT_SMALL_MM, W_TEXT.name)


# --- Пучки -------------------------------------------------------------------


@dataclass(frozen=True)
class Segment:
    """Прямой участок трассы вдоль оси: axis «h» — горизонталь (fixed = y), «v» — вертикаль
    (fixed = x); lo < hi — координаты концов вдоль оси."""

    run: int
    index: int  # номер участка в трассе
    axis: str
    fixed: float
    lo: float
    hi: float


@dataclass(frozen=True)
class Bundle:
    """Отрезок линии, на котором набор кабелей не меняется."""

    axis: str
    fixed: float
    lo: float
    hi: float
    runs: tuple[int, ...]
    band: tuple[float, float]  # сдвиги крайних полос, мм модели

    @property
    def length(self) -> float:
        return self.hi - self.lo


def segments(paths: Sequence[Sequence[Vec]]) -> list[Segment]:
    """Участки трасс вдоль осей; косые участки (их у трассировки нет) пропускаются."""
    out: list[Segment] = []
    for k, path in enumerate(paths):
        for i, (a, b) in enumerate(itertools.pairwise(path)):
            if abs(a.y - b.y) <= _TOL and abs(a.x - b.x) > _TOL:
                out.append(Segment(k, i, "h", round(a.y), min(a.x, b.x), max(a.x, b.x)))
            elif abs(a.x - b.x) <= _TOL and abs(a.y - b.y) > _TOL:
                out.append(Segment(k, i, "v", round(a.x), min(a.y, b.y), max(a.y, b.y)))
    return out


def _by_line(segs: Iterable[Segment]) -> dict[tuple[str, float], list[Segment]]:
    lines: dict[tuple[str, float], list[Segment]] = defaultdict(list)
    for s in segs:
        lines[(s.axis, s.fixed)].append(s)
    return lines


# Место до стен по обе стороны участка линии: (ось, координата, от, до) → (к −, к +), мм модели
Room = Callable[[str, float, float, float], tuple[float, float]]


def clearance(free: BaseGeometry, margin: float) -> Room:
    """Место по обе стороны участка до края свободной области (стены), за вычетом margin:
    наименьшее по нескольким точкам вдоль участка; точки вне области не в счёт."""
    edge = free.boundary
    reach = 1e6

    def side(p: Point, d: tuple[float, float]) -> float:
        ray = LineString([(p.x, p.y), (p.x + d[0] * reach, p.y + d[1] * reach)])
        hit = ray.intersection(edge)
        return reach if hit.is_empty else p.distance(hit)

    def room(axis: str, fixed: float, lo: float, hi: float) -> tuple[float, float]:
        neg = pos = math.inf
        for t in _SAMPLES:
            v = lo + (hi - lo) * t
            p = Point(v, fixed) if axis == "h" else Point(fixed, v)
            if not free.contains(p):
                continue
            up, down = ((0.0, 1.0), (0.0, -1.0)) if axis == "h" else ((1.0, 0.0), (-1.0, 0.0))
            pos = min(pos, side(p, up) - margin)
            neg = min(neg, side(p, down) - margin)
        return max(neg, 0.0), max(pos, 0.0)

    return room


def lanes(
    segs: Sequence[Segment], pitch: float, band: float, room: Room | None = None
) -> dict[tuple[int, int], float]:
    """Сдвиг каждого участка от линии: (трасса, участок) → мм модели, по +y у горизонтали
    и +x у вертикали. Полосы считаются по группам перекрывающихся участков линии:
    перекрывающиеся — в разных полосах (раскраска интервалов), шаг pitch, вся группа
    не шире band. room — место до стен: пучок симметричен линии, а у стены сдвигается
    от неё; места меньше, чем нужно пучку, — шаг меньше, пучок во всю ширину места."""
    out: dict[tuple[int, int], float] = {}
    for line in _by_line(segs).values():
        for cluster in _overlapping(line):
            ends: list[float] = []  # конец последнего участка в каждой полосе
            lane_of: dict[tuple[int, int], int] = {}
            for s in cluster:
                free = next((n for n, end in enumerate(ends) if end <= s.lo + _TOL), None)
                if free is None:
                    free = len(ends)
                    ends.append(s.hi)
                else:
                    ends[free] = s.hi
                lane_of[(s.run, s.index)] = free
            count = len(ends)
            if count == 1:
                for key in lane_of:
                    out[key] = 0.0
                continue
            width = min(pitch * (count - 1), band)
            center = 0.0
            if room is not None:
                s0 = cluster[0]
                neg, pos = room(
                    s0.axis, s0.fixed, min(s.lo for s in cluster), max(s.hi for s in cluster)
                )
                if neg + pos < width:  # места мало: шаг меньше, во всю ширину
                    width, center = neg + pos, (pos - neg) / 2
                else:  # у стены — сдвиг от неё
                    center = min(max(0.0, width / 2 - neg), pos - width / 2)
            step = width / (count - 1)
            for key, n in lane_of.items():
                out[key] = center + (n - (count - 1) / 2) * step
    return out


def _overlapping(line: Sequence[Segment]) -> list[list[Segment]]:
    """Участки линии группами: в группе каждый перекрывается хотя бы с одним (не касанием)."""
    groups: list[list[Segment]] = []
    reach = -math.inf
    for s in sorted(line, key=lambda s: (s.lo, s.hi, s.run)):
        if s.lo < reach - _TOL:
            groups[-1].append(s)
            reach = max(reach, s.hi)
        else:
            groups.append([s])
            reach = s.hi
    return groups


def bundles(segs: Sequence[Segment], offsets: dict[tuple[int, int], float]) -> list[Bundle]:
    """Отрезки линий с постоянным набором кабелей: точки разреза — концы участков."""
    out: list[Bundle] = []
    for (axis, fixed), line in _by_line(segs).items():
        cuts = sorted({c for s in line for c in (s.lo, s.hi)})
        for lo, hi in itertools.pairwise(cuts):
            here = [s for s in line if s.lo <= lo + _TOL and s.hi >= hi - _TOL]
            if not here or hi - lo <= _TOL:
                continue
            shifts = [offsets.get((s.run, s.index), 0.0) for s in here]
            runs = tuple(sorted({s.run for s in here}))
            out.append(Bundle(axis, fixed, lo, hi, runs, (min(shifts), max(shifts))))
    return out


def offset_path(path: Sequence[Vec], shifts: Sequence[float]) -> list[Vec]:
    """Трасса со сдвигом каждого участка в свою полосу; вершина между горизонталью и
    вертикалью — пересечение сдвинутых участков, концы сдвигаются поперёк своего участка."""
    if len(path) < 2:
        return list(path)

    def normal(i: int) -> Vec:
        a, b = path[i], path[i + 1]
        return Vec(0.0, 1.0) if abs(a.y - b.y) <= _TOL else Vec(1.0, 0.0)

    out = [path[0] + normal(0) * shifts[0]]
    for i in range(1, len(path) - 1):
        n_in, n_out = normal(i - 1), normal(i)
        p = path[i]
        if n_in == n_out:
            out.append(p + n_out * shifts[i])
        else:
            out.append(p + n_in * shifts[i - 1] + n_out * shifts[i])
    out.append(path[-1] + normal(len(path) - 2) * shifts[-1])
    return out


def fillet(path: Sequence[Vec], radius: float) -> list[tuple[float, float, float]]:
    """Вершины полилинии (x, y, bulge) со скруглёнными поворотами: дуга касается обоих
    участков; на коротком участке радиус меньше — каждый отдаёт дуге не больше половины."""
    if len(path) < 3:
        return [(p.x, p.y, 0.0) for p in path]
    out: list[tuple[float, float, float]] = [(path[0].x, path[0].y, 0.0)]
    for a, p, b in zip(path, path[1:], path[2:], strict=False):
        d_in, d_out = p - a, b - p
        if d_in.length() < 1e-9 or d_out.length() < 1e-9:
            continue
        u, v = _unit(d_in), _unit(d_out)
        cross = u.x * v.y - u.y * v.x
        turn = math.atan2(cross, u.dot(v))  # угол поворота, со знаком: + — влево
        if abs(turn) < 1e-6:
            continue  # прямо — вершина не нужна
        tangent = min(radius * math.tan(abs(turn) / 2), d_in.length() / 2, d_out.length() / 2)
        start, end = p - u * tangent, p + v * tangent
        out.append((start.x, start.y, math.tan(turn / 4)))
        out.append((end.x, end.y, 0.0))
    out.append((path[-1].x, path[-1].y, 0.0))
    return out


# --- Подписи -----------------------------------------------------------------

Label = tuple[str, Vec, float]  # текст, центр, угол


class _Labels:
    """Места подписей на листе проводки: подпись не пересекает трассы, коробки, точки
    подключения и уже поставленные подписи."""

    def __init__(self, paths: Sequence[Sequence[Vec]]) -> None:
        lines = [LineString([p.as_tuple() for p in path]) for path in paths if len(path) > 1]
        self.lines = STRtree(lines)
        self.taken: list[BaseGeometry] = [
            Point(path[-1].as_tuple()).buffer(sheet(POINT_CLEAR_MM)) for path in paths if path
        ]
        self.h = sheet(LENGTH_MM)
        self.gap = sheet(LENGTH_OFFSET_MM)

    def block(self, area: BaseGeometry) -> None:
        self.taken.append(area)

    def _rect(self, text: str, center: Vec, along: Vec) -> BaseGeometry:
        w = sheet(text_width(text, LENGTH_MM)) / 2
        h = self.h / 2
        across = Vec(-along.y, along.x)
        corners = [
            center + along * sx * w + across * sy * h
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))
        ]
        return box(
            min(c.x for c in corners),
            min(c.y for c in corners),
            max(c.x for c in corners),
            max(c.y for c in corners),
        )

    def _free(self, rect: BaseGeometry) -> bool:
        if any(rect.intersects(t) for t in self.taken):
            return False
        return not any(rect.intersects(self.lines.geometries[i]) for i in self.lines.query(rect))

    def _try(self, text: str, candidates: Iterable[tuple[Vec, Vec]]) -> Label | None:
        for center, along in candidates:
            rect = self._rect(text, center, along)
            if self._free(rect):
                self.taken.append(rect)
                return text, center, math.degrees(math.atan2(along.y, along.x))
        return None

    def place_bundle(self, text: str, b: Bundle) -> Label | None:
        """Подпись отрезка пучка — сбоку от крайней полосы; короткий отрезок — без подписи."""
        if sheet(text_width(text, LENGTH_MM)) + 2 * self.gap > b.length:
            return None
        along = Vec(1.0, 0.0) if b.axis == "h" else Vec(0.0, 1.0)
        across = Vec(0.0, 1.0) if b.axis == "h" else Vec(1.0, 0.0)
        reach = self.gap + self.h / 2
        sides = (across * (b.band[1] + reach), across * (b.band[0] - reach))
        spots = []
        for t in LENGTH_SLOTS:
            pos = b.lo + (b.hi - b.lo) * t
            on_line = Vec(pos, b.fixed) if b.axis == "h" else Vec(b.fixed, pos)
            spots += [(on_line + side, along) for side in sides]
        return self._try(text, spots)

    def place_end(self, path: Sequence[Vec], text: str, at_end: bool) -> Label | None:
        """Подпись у конца (или начала) трассы: по бокам последнего участка или за концом."""
        if len(path) < 2:
            return None
        tip, prev = (path[-1], path[-2]) if at_end else (path[0], path[1])
        if (tip - prev).length() < 1e-9:
            return None
        u = _unit(tip - prev)
        along = _readable(u)
        half_w = sheet(text_width(text, LENGTH_MM)) / 2
        clear = sheet(POINT_CLEAR_MM)
        side = Vec(-along.y, along.x) * (self.gap + self.h / 2)
        back = tip - u * (clear + half_w)
        beyond = tip + u * (clear + half_w)
        return self._try(text, [(back + side, along), (back - side, along), (beyond, along)])


def _unit(v: Vec) -> Vec:
    return v * (1.0 / v.length())


def _readable(direction: Vec) -> Vec:
    """Направление текста вдоль участка: слева направо или снизу вверх."""
    if direction.x < -1e-9 or (abs(direction.x) <= 1e-9 and direction.y < 0):
        return direction * -1.0
    return direction


def length_label(mm: float, cables: int) -> str:
    """Подпись участка пучка: «L1,4» — длина, м; «×3» — кабелей на участке, если больше одного."""
    return f"{LENGTH}{_m(mm)}" + (f" ×{cables}" if cables > 1 else "")


def _m(mm: float) -> str:
    return f"{mm / 1000:.1f}".replace(".", ",")


def wiring_table(wiring: Wiring, language: Language, colors: dict[str, int] | None = None) -> Table:
    """По группам: марка, коробки, линии, длина без запаса; итог — по всем группам.
    colors — цвет группы: кружок у её имени, как цвет её линий."""
    groups: dict[str, list[float]] = {}
    marks: dict[str, str] = {}
    for run in wiring.runs:
        groups.setdefault(run.group, []).append(run.length_mm)
        marks[run.group] = run.mark + ("*" if run.mark_assumed else "")
    boxes = {g: sum(1 for b in wiring.boxes if b.group == g) for g in groups}
    columns = (
        Column(tr("wiring_group", language), 26.0),
        Column(tr("wiring_mark", language), 18.0),
        Column(tr("wiring_boxes", language), 18.0),
        Column(tr("wiring_lines", language), 16.0),
        Column(tr("wiring_length", language), 22.0),
    )
    rows = tuple(
        (
            Mark(g, colors[g]) if colors and g in colors else g,
            marks[g],
            str(boxes[g]),
            str(len(lens)),
            _m(sum(lens)),
        )
        for g, lens in groups.items()
    )
    total = (
        tr("wiring_total", language),
        "",
        str(len(wiring.boxes)),
        str(len(wiring.runs)),
        _m(sum(r.length_mm for r in wiring.runs)),
    )
    return Table(tr("wiring_title", language), columns, rows, total=total)


def wiring_notes(wiring: Wiring, language: Language) -> list[str]:
    """Допущения расчёта — строками под таблицей."""
    default = tr("wiring_default", language) if wiring.height_assumed else ""
    notes = [
        tr("wiring_note", language, h=f"{wiring.ceiling_height:g}", default=default),
        tr("wiring_lengths_note", language),
        tr("wiring_drops_note", language),
    ]
    if any(r.route == "floor" for r in wiring.runs):
        notes += [tr("wiring_floor_note", language), tr("wiring_floor_arrows", language)]
    if wiring.chases:
        notes.append(
            tr(
                "wiring_chases",
                language,
                n=len(wiring.chases),
                m=_m(wiring.chase_mm),
                k=CHASE_CABLES,
                d=f"{CHASE_SHARE:g}",
            )
        )
        notes.append(
            tr(
                "wiring_chase_kinds",
                language,
                narrow=_m(wiring.chase_length(wide=False)),
                wide=_m(wiring.chase_length(wide=True)),
                k=CHASE_NARROW,
            )
        )
    if wiring.holes:
        notes.append(tr("wiring_holes", language, n=len(wiring.holes), k=HOLE_CABLES))
    if any(r.mark_assumed for r in wiring.runs):
        notes.append(tr("wiring_mark_note", language))
    if wiring.skipped:
        notes.append(tr("wiring_skipped", language, n=len(wiring.skipped)))
    return notes


def write_chases(wiring: Wiring, path: Path) -> Path:
    """Ведомость штроб: каждая штроба — стена, место, длина, кабели и точки, м."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "kind",
                "room",
                "wall",
                "offset_mm",
                "length_m",
                "cables",
                "width",
                "route",
                "circuit",
                "points",
            ]
        )
        for c in wiring.chases:
            w.writerow(
                [
                    c.kind,
                    c.room,
                    c.wall,
                    f"{c.offset:.0f}",
                    f"{c.length_mm / 1000:.2f}",
                    c.cables,
                    "wide" if c.wide else "narrow",
                    c.route,
                    c.circuit,
                    " ".join(c.targets),
                ]
            )
    return path


def write_journal(wiring: Wiring, path: Path, titles: dict[str, str] | None = None) -> Path:
    """Кабельный журнал: каждая линия с длинами по частям, м; titles — названия линий по
    смыслу (objects.wire_titles), иначе колонка label пустая."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "id",
                "label",
                "group",
                "mark",
                "from",
                "to",
                "route",
                "plan_m",
                "vertical_m",
                "ends_m",
                "length_m",
            ]
        )
        for r in wiring.runs:
            w.writerow(
                [
                    r.id,
                    (titles or {}).get(r.id, ""),
                    r.group,
                    r.mark,
                    r.source,
                    r.target,
                    r.route,
                    f"{r.plan_mm / 1000:.2f}",
                    f"{r.vertical_mm / 1000:.2f}",
                    f"{r.ends_mm / 1000:.2f}",
                    f"{r.length_mm / 1000:.2f}",
                ]
            )
    return path
