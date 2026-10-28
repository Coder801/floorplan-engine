"""Отрисовка плана: стены, проёмы, размеры, названия и площади помещений.

Стены всех помещений сначала объединяются в один силуэт: общая перегородка соседних
комнат рисуется один раз, а на стыке перегородки с наружной стеной нет внутренних линий.
Рисуется граница силуэта отрезками по координатам, проёмы — разрывы с откосами. Штриховка:
несущие (монолитные) стены — частая, перегородки — редкая. Где несущая стена встречается
с перегородкой, остаётся линия раздела материалов.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import shapely
from ezdxf.entities.lwpolyline import LWPolyline
from ezdxf.enums import MTextEntityAlignment, TextEntityAlignment
from ezdxf.layouts.base import BaseLayout
from ezdxf.layouts.layout import Modelspace
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from floorplan_engine.fields import add_area_field
from floorplan_engine.geometry import (
    Contour,
    Vec,
    WallSegment,
    outer_corners,
    point_in_polygon,
    signed_area,
)
from floorplan_engine.ids import tagged
from floorplan_engine.layers import (
    A_AREA,
    A_DIMS,
    A_DOOR,
    A_TEXT,
    A_WALL,
    A_WIND,
    DEFAULT_SCALE,
    DIM_STYLE,
    TEXT_DIM_MM,
    TEXT_ROOM_MM,
    TEXT_SMALL_MM,
    TEXT_STYLE,
    sheet,
    sheet_scale,
    text_width,
)
from floorplan_engine.schema import Opening, OpeningType, Plan, Room
from floorplan_engine.texts import Language, tr
from floorplan_engine.titleblock import StampText

HATCH_PATTERN = "ANSI31"
# Масштаб штриховки при 1:50; при другом масштабе листа — пропорционально, чтобы шаг
# на бумаге не менялся
HATCH_SCALE_BEARING = 12.0  # шаг ANSI31 3,175 × 12 ≈ 38 мм — 0,8 мм на листе
HATCH_SCALE_PARTITION = 30.0  # ≈ 95 мм — 1,9 мм на листе
GRID = 0.1  # сетка координат стен, мм: общие грани соседних комнат совпадают точно
MIN_AREA = 1.0  # мм²: обрезки меньше — погрешность, не штрихуются
DIM_LEVEL_1_MM = 8.0  # первый ряд размеров от грани стены, мм листа
DIM_LEVEL_STEP_MM = 7.0  # шаг между рядами
DIM_TEXT_GAP_MM = 0.8  # зазор вокруг подписи размера вдоль линии (как dimgap)
DIM_LIFT_MM = TEXT_DIM_MM * 1.4  # подпись, которой нет места вдоль линии, — строкой выше
DIM_GAP_MM = 0.8  # подпись над размерной линией (dimgap стиля)
DIM_LINE_BAND_MM = 0.4  # полоса размерной линии для проверки наложений
DIM_STEPS_MM = (0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0)  # насколько дальше от участка уводить подпись
DIM_MAX_SHIFTS = 4  # на сколько уровней ряд может уйти, если его место занято
SHARED_WALL_TOLERANCE = 1.0


@dataclass(frozen=True)
class RoomGeometry:
    room: Room
    contour: Contour
    corners: list[Vec]  # внешние углы стен

    def outer_point(self, seg: WallSegment, offset: float) -> Vec:
        return seg.point_at(offset) + seg.outward * seg.thickness

    def outer_start(self, seg: WallSegment) -> Vec:
        return self.corners[seg.index]

    def outer_end(self, seg: WallSegment) -> Vec:
        return self.corners[(seg.index + 1) % len(self.corners)]


def _xy(v: Vec) -> tuple[float, float]:
    return v.as_tuple()


def _gaps(room: Room, wall: str) -> list[tuple[float, float]]:
    """Отсортированные интервалы проёмов на стене."""
    spans = [(o.offset, o.offset + o.width) for o in room.openings if o.wall == wall]
    return sorted(spans)


def _solid_intervals(
    lo: float, hi: float, gaps: Sequence[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Части отрезка [lo, hi] без проёмов."""
    result: list[tuple[float, float]] = []
    pos = lo
    for a, b in gaps:
        if a > pos:
            result.append((pos, min(a, hi)))
        pos = max(pos, b)
    if pos < hi:
        result.append((pos, hi))
    return [(a, b) for a, b in result if b - a > 1e-6]


# --- Стены -------------------------------------------------------------------


@dataclass(frozen=True)
class WallPiece:
    """Сплошной участок стены между проёмами.

    polygon — четырёхугольник от внутренней грани до внешней со срезанными под углом
    концами: из них складывается силуэт стен (контур). body — тело стены для штриховки:
    прямоугольник, продлённый в выпуклых углах на толщину соседней стены. Угол достаётся
    одной стене целиком, соседняя упирается в неё торцом под 90° — стыки на плане прямые,
    без шва «на ус» (несущая — сплошная, перегородка — торцом в неё).
    """

    tag: str  # «комната.стена» — метка FLOORPLAN_ENGINE
    bearing: bool
    polygon: BaseGeometry
    body: BaseGeometry


def convex(a: WallSegment, b: WallSegment) -> bool:
    """Угол между стеной a и следующей b выпуклый (обход по часовой — поворот вправо)."""
    return a.direction.x * b.direction.y - a.direction.y * b.direction.x < 0


def _snap(geometry: BaseGeometry) -> BaseGeometry:
    # Короткая стена у входящего угла может дать «бабочку» — чиним, затем на сетку
    return shapely.set_precision(shapely.make_valid(geometry), GRID)


def _open_at_end(room: Room, seg: WallSegment) -> bool:
    """Проём стены доходит до её конца."""
    return any(b >= seg.length - 1e-6 for _, b in _gaps(room, seg.id))


def _open_at_start(room: Room, seg: WallSegment) -> bool:
    """Проём стены начинается от её начала."""
    return any(a <= 1e-6 for a, _ in _gaps(room, seg.id))


def wall_pieces(g: RoomGeometry) -> list[WallPiece]:
    out: list[WallPiece] = []
    segs = g.contour.segments
    for seg in segs:
        prev, nxt = segs[seg.index - 1], segs[(seg.index + 1) % len(segs)]
        pieces = _solid_intervals(0.0, seg.length, _gaps(g.room, seg.id))
        for k, (a, b) in enumerate(pieces):
            first = k == 0 and a == 0.0
            last = k == len(pieces) - 1 and abs(b - seg.length) < 1e-6
            inner_a, inner_b = seg.point_at(a), seg.point_at(b)
            outer_a = g.outer_start(seg) if first else g.outer_point(seg, a)
            outer_b = g.outer_end(seg) if last else g.outer_point(seg, b)
            # Окно или дверь соседа доходит до выпуклого угла — угол целиком за этой
            # стеной, прямым торцом, а не срезом под углом
            if first and convex(prev, seg) and _open_at_end(g.room, prev):
                inner_a = seg.point_at(-prev.thickness)
                outer_a = g.outer_point(seg, -prev.thickness)
            if last and convex(seg, nxt) and _open_at_start(g.room, nxt):
                inner_b = seg.point_at(seg.length + nxt.thickness)
                outer_b = g.outer_point(seg, seg.length + nxt.thickness)
            quad = Polygon([_xy(inner_a), _xy(inner_b), _xy(outer_b), _xy(outer_a)])
            lo = a - (prev.thickness if first and convex(prev, seg) else 0.0)
            hi = b + (nxt.thickness if last and convex(seg, nxt) else 0.0)
            out_dir = seg.outward * seg.thickness
            body = Polygon(
                [
                    _xy(seg.point_at(lo)),
                    _xy(seg.point_at(hi)),
                    _xy(seg.point_at(hi) + out_dir),
                    _xy(seg.point_at(lo) + out_dir),
                ]
            )
            out.append(WallPiece(f"{g.room.id}.{seg.id}", seg.bearing, _snap(quad), _snap(body)))
    return out


def draw_walls(msp: Modelspace, geoms: Sequence[RoomGeometry]) -> None:
    """Стены всех помещений: штриховка по материалу и граница общего силуэта."""
    # Несущие первыми: на стыке с перегородкой место за несущей стеной
    pieces = sorted((p for g in geoms for p in wall_pieces(g)), key=lambda p: not p.bearing)
    total = shapely.unary_union([p.polygon for p in pieces])
    bearing = shapely.unary_union([p.body for p in pieces if p.bearing]).intersection(total)
    covered: BaseGeometry = Polygon()
    for p in pieces:
        # Тело стены, а не срезанный «на ус» кусок: стык со следующей стеной — под 90°
        body = p.body.intersection(total)
        area = body.intersection(bearing) if p.bearing else body.difference(bearing)
        own = area.difference(covered)
        covered = covered.union(area)
        base = HATCH_SCALE_BEARING if p.bearing else HATCH_SCALE_PARTITION
        scale = base * sheet_scale() / DEFAULT_SCALE
        with tagged(msp, "wall", p.tag):
            _hatch(msp, own, scale)
    # Граница силуэта и линия раздела «несущая | перегородка»; общие участки — один раз
    edges = shapely.unary_union([total.boundary, bearing.boundary])
    by_tag: dict[str, list[shapely.LineString]] = {}
    for line in shapely.get_parts(edges):
        for a, b in itertools.pairwise(line.coords):
            seg = shapely.LineString([a, b])
            owner = _owner(pieces, seg.interpolate(0.5, normalized=True))
            by_tag.setdefault(owner, []).append(seg)
    layer = {"layer": A_WALL.name}
    for tag, segs in by_tag.items():
        merged = shapely.line_merge(shapely.MultiLineString(segs))
        with tagged(msp, "wall", tag):
            for line in shapely.get_parts(merged):
                # Точки на прямой (стыки участков) убираются — линия от угла до угла
                pts = list(line.simplify(GRID / 2).coords)
                for a, b in itertools.pairwise(pts):
                    msp.add_line(a, b, dxfattribs=layer)


def _owner(pieces: Sequence[WallPiece], at: BaseGeometry) -> str:
    """Стена, на грани которой лежит точка; несущие проверяются первыми."""
    for p in pieces:
        if p.polygon.boundary.distance(at) <= GRID or p.body.boundary.distance(at) <= GRID:
            return p.tag
    return min(pieces, key=lambda p: p.polygon.distance(at)).tag


def _hatch(msp: Modelspace, area: BaseGeometry, scale: float) -> None:
    for part in shapely.get_parts(area):
        if not isinstance(part, Polygon) or part.area < MIN_AREA:
            continue
        hatch = msp.add_hatch(color=256, dxfattribs={"layer": A_WALL.name})
        hatch.set_pattern_fill(HATCH_PATTERN, scale=scale)
        hatch.paths.add_polyline_path(list(part.exterior.coords)[:-1], is_closed=True)
        for hole in part.interiors:
            hatch.paths.add_polyline_path(list(hole.coords)[:-1], is_closed=True, flags=0)


# --- Проёмы ------------------------------------------------------------------


def draw_openings(msp: Modelspace, g: RoomGeometry, language: Language = "ru") -> None:
    for op in g.room.openings:
        with tagged(msp, "opening", op.id):
            seg = g.contour.segment(op.wall)
            if op.type is OpeningType.DOOR:
                _draw_door(msp, g, seg, op)
            elif op.type is OpeningType.WINDOW:
                _draw_window(msp, g, seg, op, language)


def door_leaf(g: RoomGeometry, seg: WallSegment, op: Opening) -> tuple[Vec, Vec, Vec]:
    """Петля, край закрытого полотна и направление открывания двери."""
    hinge_off, free_off = (
        (op.offset, op.offset + op.width)
        if op.hinge == "start"
        else (op.offset + op.width, op.offset)
    )
    if op.swing == "in":
        return seg.point_at(hinge_off), seg.point_at(free_off), seg.inward
    return g.outer_point(seg, hinge_off), g.outer_point(seg, free_off), seg.outward


def _draw_door(msp: Modelspace, g: RoomGeometry, seg: WallSegment, op: Opening) -> None:
    layer = {"layer": A_DOOR.name}
    hinge, closed, normal = door_leaf(g, seg, op)
    leaf_end = hinge + normal * op.width
    msp.add_line(_xy(hinge), _xy(leaf_end), dxfattribs=layer)
    a_closed = math.degrees(math.atan2(closed.y - hinge.y, closed.x - hinge.x))
    a_open = math.degrees(math.atan2(leaf_end.y - hinge.y, leaf_end.x - hinge.x))
    # ARC строится против часовой стрелки от start_angle до end_angle
    if (closed - hinge).cross(leaf_end - hinge) > 0:
        start, end = a_closed, a_open
    else:
        start, end = a_open, a_closed
    msp.add_arc(_xy(hinge), op.width, start, end, dxfattribs=layer)


def _draw_window(
    msp: Modelspace, g: RoomGeometry, seg: WallSegment, op: Opening, language: Language
) -> None:
    layer = {"layer": A_WIND.name}
    a, b = op.offset, op.offset + op.width
    for frac in (0.0, 0.5, 1.0):
        shift = seg.outward * (seg.thickness * frac)
        msp.add_line(_xy(seg.point_at(a) + shift), _xy(seg.point_at(b) + shift), dxfattribs=layer)
    if op.sill is not None:
        mid = seg.point_at((a + b) / 2) + seg.inward * sheet(TEXT_SMALL_MM * 1.2)
        text = tr("sill", language, sill=f"{op.sill:g}")
        add_text(msp, text, mid, TEXT_SMALL_MM, A_WIND.name, seg.angle_deg)


# --- Размеры -----------------------------------------------------------------


def readable_angle(angle: float) -> float:
    """Угол текста, чтобы он не читался вверх ногами."""
    angle = (angle + 180.0) % 360.0 - 180.0
    if angle > 90.0 + 1e-6 or angle <= -90.0 + 1e-6:
        angle += 180.0
    return angle


def _reading(seg: WallSegment) -> tuple[Vec, Vec]:
    """Направление чтения подписи размера вдоль стены и сторона «над линией»."""
    d = seg.direction
    angle = math.degrees(math.atan2(d.y, d.x))
    if abs(readable_angle(angle) - angle) > 1e-6:
        d = d * -1.0
    return d, d.left()


def _dim_label(a: float, b: float) -> str:
    return f"{b - a:.0f}"


def _text_box(seg: WallSegment, a: float, b: float, offset: float, move: Vec) -> BaseGeometry:
    """Место подписи размера участка a…b: над размерной линией на offset (+ наружу),
    сдвинутой на move (мм модели)."""
    d, up = _reading(seg)
    hw = sheet(text_width(_dim_label(a, b), TEXT_DIM_MM) / 2 + DIM_TEXT_GAP_MM)
    hh = sheet(TEXT_DIM_MM * 0.6)
    c = seg.point_at((a + b) / 2) + seg.outward * offset + up * (sheet(DIM_GAP_MM) + hh) + move
    return Polygon([_xy(c + d * sx * hw + up * sy * hh) for sx, sy in CORNERS])


CORNERS = ((-1, -1), (1, -1), (1, 1), (-1, 1))


def _fits(a: float, b: float) -> bool:
    """Подпись помещается между выносными линиями участка."""
    return sheet(text_width(_dim_label(a, b), TEXT_DIM_MM) + 2 * DIM_TEXT_GAP_MM) <= b - a


def _moves(seg: WallSegment, a: float, b: float) -> list[Vec]:
    """Куда можно увести подпись узкого участка: вдоль линии за участок (ближе — раньше),
    затем строкой выше — по центру и вдоль линии."""
    d, up = _reading(seg)
    reach = (b - a) / 2 + sheet(text_width(_dim_label(a, b), TEXT_DIM_MM) / 2 + DIM_TEXT_GAP_MM)
    along = [reach + sheet(step) for step in DIM_STEPS_MM]
    lift = up * sheet(DIM_LIFT_MM)
    out = [d * (sign * x) for x in along for sign in (1.0, -1.0)]
    return out + [lift] + [lift + v for v in out]


def _line_band(seg: WallSegment, offset: float) -> BaseGeometry:
    """Размерная линия ряда: чужие подписи на неё не ложатся. Концы обрезаны — в углу
    комнаты линии соседних стен пересекаются всегда."""
    band = sheet(DIM_LINE_BAND_MM)
    trim = min(abs(offset) + sheet(DIM_GAP_MM), seg.length * 0.45)
    a, b, n = seg.point_at(trim), seg.point_at(seg.length - trim), seg.outward
    lo, hi = offset - band, offset + band
    return Polygon([_xy(a + n * lo), _xy(b + n * lo), _xy(b + n * hi), _xy(a + n * hi)])


def _hits(geom: BaseGeometry, taken: Sequence[BaseGeometry]) -> bool:
    return any(geom.intersection(t).area > 0 for t in taken)


def _place_rows(
    seg: WallSegment,
    rows: Sequence[Sequence[tuple[float, float]]],
    sign: float,
    base: float,
    taken: list[BaseGeometry],
) -> tuple[float, list[list[Vec | None]]]:
    """Ряды размеров стены (участки каждого ряда) на первом уровне, где их подписи не
    задевают уже поставленное (taken); узкие подписи — на свободное место рядом (_moves).
    Возвращает уровень первого ряда и сдвиги подписей; поставленное добавляет в taken."""
    step = sheet(DIM_LEVEL_STEP_MM)
    zero = Vec(0.0, 0.0)

    def offsets(start: float) -> list[float]:
        return [sign * (start + r * step) for r in range(len(rows))]

    level = base
    for k in range(DIM_MAX_SHIFTS + 1):
        start = base + k * step
        boxes = [
            _text_box(seg, a, b, off, zero)
            for parts, off in zip(rows, offsets(start), strict=True)
            for a, b in parts
            if _fits(a, b)
        ]
        lines = [_line_band(seg, off) for off in offsets(start)]
        if not any(_hits(g, taken) for g in boxes + lines):
            level = start
            break
    moves: list[list[Vec | None]] = []
    for parts, off in zip(rows, offsets(level), strict=True):
        row: list[Vec | None] = []
        for a, b in parts:
            default = _text_box(seg, a, b, off, zero)
            if _fits(a, b) and not _hits(default, taken):
                taken.append(default)
                row.append(None)
                continue
            # Узкая или легла на чужое — ближайшее свободное место рядом
            options = ([zero] if _fits(a, b) else []) + _moves(seg, a, b)
            move = next(
                (m for m in options if not _hits(_text_box(seg, a, b, off, m), taken)), options[0]
            )
            taken.append(_text_box(seg, a, b, off, move))
            row.append(None if move == zero else move)
        moves.append(row)
    taken.extend(_line_band(seg, off) for off in offsets(level))
    return level, moves


def _add_dim(
    msp: Modelspace, p1: Vec, p2: Vec, offset_outward: float, move: Vec | None = None
) -> None:
    """Размер между точками на грани стены, вынесенный по нормали наружу (+) или внутрь (−);
    move — сдвиг подписи от места по умолчанию, мм модели (узкий участок цепочки).

    У add_aligned_dim положительное distance — влево от p1→p2, а «влево» у стены — наружу.
    Если стена идёт влево или вниз, точки меняются местами, чтобы текст не был вверх ногами.
    """
    d = p2 - p1
    angle = math.degrees(math.atan2(d.y, d.x))
    if abs(readable_angle(angle) - angle) > 1e-6:
        p1, p2, offset_outward = p2, p1, -offset_outward
    dim = msp.add_aligned_dim(
        p1=_xy(p1),
        p2=_xy(p2),
        distance=offset_outward,
        dimstyle=DIM_STYLE,
        dxfattribs={"layer": A_DIMS.name},
    )
    if move is not None:
        dim.set_location(_xy(move), relative=True)
    dim.render()


def _outside_is_free(g: RoomGeometry, seg: WallSegment, others: Sequence[RoomGeometry]) -> bool:
    """Снаружи стены нет другого помещения (туда можно выносить размеры)."""
    mid = seg.point_at(seg.length / 2) + seg.outward * (seg.thickness + sheet(DIM_LEVEL_1_MM))
    return not any(point_in_polygon(mid, o.contour.vertices) for o in others if o is not g)


def _mirrored_wall(g: RoomGeometry, seg: WallSegment, other: RoomGeometry) -> WallSegment | None:
    """Стена другой комнаты, которая является обратной стороной этой же перегородки."""
    far_start = seg.start + seg.outward * seg.thickness
    far_end = seg.end + seg.outward * seg.thickness
    mine = [(seg.length - b, seg.length - a) for a, b in _gaps(g.room, seg.id)]
    for o in other.contour.segments:
        if (o.start - far_end).length() <= SHARED_WALL_TOLERANCE and (
            o.end - far_start
        ).length() <= SHARED_WALL_TOLERANCE:
            theirs = _gaps(other.room, o.id)
            same = len(mine) == len(theirs) and all(
                abs(a1 - a2) <= SHARED_WALL_TOLERANCE and abs(b1 - b2) <= SHARED_WALL_TOLERANCE
                for (a1, b1), (a2, b2) in zip(mine, theirs, strict=True)
            )
            return o if same else None
    return None


def draw_dimensions(
    msp: Modelspace,
    g: RoomGeometry,
    all_rooms: Sequence[RoomGeometry],
    done: Sequence[RoomGeometry] = (),
    taken: list[BaseGeometry] | None = None,
) -> None:
    """Размеры по внутренней грани стены.

    Снаружи свободно — выносим за габарит здания: 1-й ряд — цепочка проёмов,
    2-й — общая длина.
    Снаружи соседнее помещение — те же ряды внутрь своей комнаты, но только если
    эту перегородку ещё не образмерили со стороны соседа (`done`).
    taken — подписи и размерные линии уже поставленных рядов и подписи помещений, общие
    для всех комнат: ряд, чьи подписи на них ложатся, уходит на следующий уровень; узкая
    подпись (не входит между выносными) — на свободное место рядом.
    """
    taken = taken if taken is not None else []
    for seg in g.contour.segments:
        with tagged(msp, "dimension", f"{g.room.id}.{seg.id}"):
            gaps = _gaps(g.room, seg.id)
            if _outside_is_free(g, seg, all_rooms):
                # За габарит здания в сторону этой стены — размеры фасада на одной линии
                reach = max(c.dot(seg.outward) for r in all_rooms for c in r.corners)
                sign, base = 1.0, reach - seg.start.dot(seg.outward) + sheet(DIM_LEVEL_1_MM)
            else:
                if any(_mirrored_wall(g, seg, o) is not None for o in done):
                    continue
                sign, base = -1.0, sheet(DIM_LEVEL_1_MM)
            parts = [(0.0, seg.length)]
            if gaps:
                stops = sorted({0.0, seg.length, *(x for gap in gaps for x in gap)})
                parts = list(itertools.pairwise(stops))
            # Ряды: цепочка проёмов (если есть), затем общая длина
            rows = [parts, [(0.0, seg.length)]] if gaps else [parts]
            level, moves = _place_rows(seg, rows, sign, base, taken)
            step = sheet(DIM_LEVEL_STEP_MM)
            for r, (row, row_moves) in enumerate(zip(rows, moves, strict=True)):
                for (a, b), move in zip(row, row_moves, strict=True):
                    _add_dim(msp, seg.point_at(a), seg.point_at(b), sign * (level + r * step), move)


# --- Подписи -----------------------------------------------------------------


def add_text(
    msp: BaseLayout,
    text: str,
    at: Vec,
    height_mm: float,
    layer: str,
    angle: float = 0.0,
    align: TextEntityAlignment = TextEntityAlignment.MIDDLE_CENTER,
    color: int | None = None,
    scale: float | None = None,
) -> None:
    """Текст стилем проекта; color — true color (0xRRGGBB) вместо цвета слоя.

    height_mm — высота на листе; scale — сколько единиц чертежа в мм листа:
    None — в модели (текущий масштаб листа), 1 — на самом листе.
    """
    if scale is None:
        scale = sheet_scale()
    attribs: dict[str, object] = {"layer": layer, "style": TEXT_STYLE}
    if color is not None:
        attribs["true_color"] = color
    msp.add_text(
        text,
        height=height_mm * scale,
        rotation=readable_angle(angle),
        dxfattribs=attribs,
    ).set_placement(_xy(at), align=align)


def polygon_centroid(points: Sequence[Vec]) -> Vec:
    area = signed_area(points)
    if abs(area) < 1e-9:
        n = len(points)
        return Vec(sum(p.x for p in points) / n, sum(p.y for p in points) / n)
    cx = cy = 0.0
    for i, a in enumerate(points):
        b = points[(i + 1) % len(points)]
        k = a.cross(b)
        cx += (a.x + b.x) * k
        cy += (a.y + b.y) * k
    return Vec(cx / (6 * area), cy / (6 * area))


def label_point(contour: Contour) -> Vec:
    """Точка подписи: центр тяжести, а если он вне контура (Г-форма) — ближайший узел внутри."""
    pts = contour.vertices
    c = polygon_centroid(pts)
    if point_in_polygon(c, pts):
        return c
    xs, ys = [p.x for p in pts], [p.y for p in pts]
    best: Vec | None = None
    steps = 20
    for i in range(1, steps):
        for j in range(1, steps):
            p = Vec(
                min(xs) + (max(xs) - min(xs)) * i / steps,
                min(ys) + (max(ys) - min(ys)) * j / steps,
            )
            if point_in_polygon(p, pts) and (
                best is None or (p - c).length() < (best - c).length()
            ):
                best = p
    return best if best is not None else c


@dataclass(frozen=True)
class RoomArea:
    """Контур площади помещения в модели и его площадь сейчас — для полей AutoCAD."""

    contour: LWPolyline
    area_mm2: float


def draw_area_contour(msp: Modelspace, g: RoomGeometry) -> RoomArea:
    """Внутренний контур помещения отдельной полилинией: на неё ссылаются поля площади."""
    poly = msp.add_lwpolyline(
        [_xy(v) for v in g.contour.vertices], close=True, dxfattribs={"layer": A_AREA.name}
    )
    return RoomArea(poly, g.contour.area_mm2)


def _room_label_box(g: RoomGeometry) -> BaseGeometry:
    """Место названия и площади помещения (draw_room_label) — размеры на него не ложатся."""
    at = label_point(g.contour)
    w = max(text_width(g.room.name, TEXT_ROOM_MM), text_width("00,00 м²", TEXT_DIM_MM))
    hw, hh = sheet(w / 2 + 1.0), sheet(TEXT_ROOM_MM * 1.6)
    return Polygon(
        [
            (at.x - hw, at.y - hh),
            (at.x + hw, at.y - hh),
            (at.x + hw, at.y + hh),
            (at.x - hw, at.y + hh),
        ]
    )


def draw_room_label(msp: Modelspace, g: RoomGeometry, area: RoomArea) -> None:
    """Название и площадь помещения; площадь — поле AutoCAD от контура area."""
    doc = msp.doc
    assert doc is not None
    at = label_point(g.contour)
    gap = sheet(TEXT_ROOM_MM) * 0.8
    add_text(msp, g.room.name, at + Vec(0, gap), TEXT_ROOM_MM, A_TEXT.name)
    mtext = msp.add_mtext(
        "",
        dxfattribs={"layer": A_TEXT.name, "style": TEXT_STYLE, "char_height": sheet(TEXT_DIM_MM)},
    )
    mtext.set_location(_xy(at - Vec(0, gap)), attachment_point=MTextEntityAlignment.MIDDLE_CENTER)
    add_area_field(doc, mtext, area.contour, area.area_mm2, suffix=" м²")


# --- Сборка ------------------------------------------------------------------


def room_geometries(plan: Plan, contours: dict[str, Contour]) -> list[RoomGeometry]:
    return [
        RoomGeometry(room, contours[room.id], outer_corners(contours[room.id]))
        for room in plan.rooms
    ]


def draw_plan(msp: Modelspace, plan: Plan, contours: dict[str, Contour]) -> dict[str, RoomArea]:
    """План в модели 1:1: стены, проёмы, контуры площади, подписи, размеры.

    Возвращает контуры площади по id комнаты — на них ссылаются поля в экспликации.
    """
    geoms = room_geometries(plan, contours)
    areas: dict[str, RoomArea] = {}
    draw_walls(msp, geoms)
    for g in geoms:
        draw_openings(msp, g, plan.language)
        with tagged(msp, "room", g.room.id):
            areas[g.room.id] = draw_area_contour(msp, g)
            draw_room_label(msp, g, areas[g.room.id])
    # Общие перегородки образмериваем из более просторной комнаты
    done: list[RoomGeometry] = []
    # Подписи размеров не ложатся на названия помещений и стены. Открывание дверей не в
    # счёт: в коридоре с тремя дверями подписям иначе некуда встать рядом с участком
    taken = [_room_label_box(g) for g in geoms]
    taken += [p.polygon for g in geoms for p in wall_pieces(g)]
    for g in sorted(geoms, key=lambda r: r.contour.area_mm2, reverse=True):
        draw_dimensions(msp, g, geoms, done, taken)
        done.append(g)
    return areas


def plan_stamp(
    plan: Plan, image_key: str, sheet_no: int = 1, sheets: int = 1, today: date | None = None
) -> StampText:
    """Основная надпись листа; image_key — ключ наименования изображения в texts.TEXTS."""
    object_name = plan.sheet.object if plan.sheet.object is not None else plan.name
    image = tr(image_key, plan.language, scale=f"{sheet_scale():g}")
    return StampText(plan.sheet, object_name, image, sheet_no, sheets, today, plan.language)
