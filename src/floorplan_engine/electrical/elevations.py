"""Развёртки стен (решение 2026-10-28, P1): что монтажник делает на каждой стене.

Стена — вид изнутри помещения: слева — начало стены по обходу, справа — конец (обход по
часовой стрелке по внутреннему контуру, поэтому изнутри отступ всегда растёт слева
направо); снизу — пол, сверху — потолок. На стене: проёмы, точки (номер — как на листе
электрики), щит, распаечные коробки, штробы (спуски от потолка или подъёмы от пола).
Только стены, на которых есть точки, щит, коробки или штробы.

Общая перегородка двух помещений — две развёртки, по одной с каждой стороны (каждая изнутри
своего помещения). Чтобы их не путать, у развёртки — что за стеной (behind): соседнее
помещение и номер его стены — обратной стороны этой, или «вне квартиры». Выводы соседа на
обратной стороне (back) — на своём месте, как видно с этой стороны: сверлить насквозь
или ставить спина к спине.

Новых расчётов нет: точки и щит — из модели, коробки и штробы — из wiring.py, высоты
проёмов без данных — те же допущения, что в 3D (scene3d).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from floorplan_engine.electrical.boxes import box_wall
from floorplan_engine.electrical.point_numbers import number_points, point_name
from floorplan_engine.electrical.wiring_model import Wiring
from floorplan_engine.model.geometry import (
    DOOR_TOP_MM,
    WINDOW_HEIGHT_MM,
    WINDOW_SILL_MM,
    Contour,
    RoomGeometry,
    WallSegment,
    point_in_polygon,
    room_geometries,
)
from floorplan_engine.model.schema import (
    Electrical,
    ElectricalPoint,
    OpeningType,
    Plan,
    PointType,
    Room,
)
from floorplan_engine.model.texts import Language, tr

BOARD_HEIGHT_MM = 400.0  # высота щита на развёртке: в модели её нет — допущение
POST_PITCH_MM = 71.0  # шаг постов в рамке
BOX_DEFAULT_MM = 100.0
BEHIND_PROBE_MM = 50.0  # насколько за внешней гранью стены искать соседнее помещение
FACE_TOLERANCE_MM = 30.0  # грань соседа — не дальше от внешней грани этой стены
BEHIND_STEP_MM = 500.0  # шаг пробных точек вдоль стены: сосед за частью длинной стены — тоже


@dataclass(frozen=True)
class OpeningView:
    kind: str  # door | window | opening
    x0: float
    x1: float
    y0: float  # низ: 0 у двери, подоконник у окна
    y1: float  # верх
    assumed: bool  # высоты нет в room.yaml — типовая


@dataclass(frozen=True)
class PointView:
    """Точка на стене: середина символа (x — от начала стены, y — от пола), мм."""

    id: str
    number: int
    type: PointType
    x: float
    y: float
    posts: int


@dataclass(frozen=True)
class BoxView:
    id: str
    label: str  # «К3»
    x: float
    y: float
    size: float  # сторона, мм


@dataclass(frozen=True)
class ChaseView:
    """Штроба: вертикаль x, от y0 до y1 (y0 < y1), мм; wide — больше двух кабелей."""

    x: float
    y0: float
    y1: float
    cables: int
    wide: bool
    low: bool  # слаботочная (интернет, TV)


@dataclass(frozen=True)
class BoardView:
    name: str
    x: float  # середина
    y: float  # середина
    width: float
    height: float


@dataclass(frozen=True)
class WallElevation:
    room: str
    room_name: str
    wall: str
    index: int  # номер стены в обходе, с 1
    length: float
    height: float  # высота потолка
    height_assumed: bool
    openings: tuple[OpeningView, ...] = ()
    points: tuple[PointView, ...] = ()
    boxes: tuple[BoxView, ...] = ()
    chases: tuple[ChaseView, ...] = ()
    board: BoardView | None = None
    behind: tuple[tuple[str, int | None], ...] = ()  # за стеной: (помещение, номер его стены)
    back: tuple[PointView, ...] = ()  # выводы на обратной стороне стены (x — с этой стороны)

    @property
    def key(self) -> str:
        return f"{self.room}.{self.wall}"

    @property
    def top(self) -> float:
        """Верх чертежа: потолок или, если что-то стоит выше потолка (ошибка данных или
        потолок не тот), — это место с запасом."""
        tops = [p.y + 100.0 for p in self.points] + [b.y + b.size / 2 for b in self.boxes]
        if self.board is not None:
            tops.append(self.board.y + self.board.height / 2)
        return max([self.height, *tops])

    def above_ceiling(self) -> list[str]:
        """Точки выше потолка — id."""
        return [p.id for p in self.points if p.y > self.height]

    def heights(self) -> list[float]:
        """Отметки от пола для размеров: точки, щит, коробки (без повторов, по возрастанию)."""
        ys = {round(p.y) for p in self.points} | {round(b.y) for b in self.boxes}
        if self.board is not None:
            ys.add(round(self.board.y))
        return sorted(float(y) for y in ys)

    def offsets(self) -> list[float]:
        """Отступы от начала стены: точки, щит, коробки (без повторов, по возрастанию)."""
        xs = {round(p.x) for p in self.points} | {round(b.x) for b in self.boxes}
        if self.board is not None:
            xs.add(round(self.board.x))
        return sorted(float(x) for x in xs)


@dataclass
class _Wall:
    points: list[PointView] = field(default_factory=list)
    boxes: list[BoxView] = field(default_factory=list)
    chases: list[ChaseView] = field(default_factory=list)
    board: BoardView | None = None


def wall_elevations(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical,
    wiring: Wiring | None,
    ceiling_default: float = 2700.0,
) -> list[WallElevation]:
    """Развёртки стен с электрикой — по помещениям и обходу стен."""
    ceiling = wiring.ceiling_height if wiring is not None else ceiling_default
    assumed = wiring.height_assumed if wiring is not None else True
    numbers = number_points(plan, elec)
    geoms = {g.room.id: g for g in room_geometries(plan, contours)}
    walls: dict[tuple[str, str], _Wall] = defaultdict(_Wall)

    for p in elec.points:
        if p.wall is None or p.offset is None or p.height is None:
            continue
        walls[(p.room, p.wall)].points.append(
            PointView(p.id, numbers[p.id], p.type, p.offset, p.height, _posts(p))
        )
    if elec.board is not None:
        b = elec.board
        walls[(b.room, b.wall)].board = BoardView(
            b.name, b.offset, b.height, b.width, BOARD_HEIGHT_MM
        )

    if wiring is not None:
        for box in wiring.boxes:
            g = geoms.get(box.room)
            seg = box_wall(g, box.anchor) if g is not None else None
            if g is None or seg is None:
                continue  # на потолке — не на стене
            x = (box.anchor.pos - seg.start).dot(seg.direction)
            y = box.rise_mm if box.route == "floor" else ceiling - box.rise_mm
            side = _box_side(box.size)
            walls[(box.room, seg.id)].boxes.append(BoxView(box.id, box.label, x, y, side))
            # Штроба от коробки до плоскости трассы
            y0, y1 = (0.0, y) if box.route == "floor" else (y, ceiling)
            walls[(box.room, seg.id)].chases.append(ChaseView(x, y0, y1, 1, False, False))
        for c in wiring.chases:
            if not c.wall:
                continue  # у коробки — нарисована выше
            y0, y1 = (0.0, c.length_mm) if c.route == "floor" else (ceiling - c.length_mm, ceiling)
            walls[(c.room, c.wall)].chases.append(
                ChaseView(c.offset, y0, y1, c.cables, c.wide, c.circuit != "power")
            )

    out: list[WallElevation] = []
    for room in plan.rooms:
        for k, wall in enumerate(room.walls, 1):
            w = walls.get((room.id, wall.id))
            if w is None:
                continue
            seg = geoms[room.id].contour.segments[k - 1]
            openings = _openings(room, wall.id, ceiling)
            out.append(
                WallElevation(
                    room.id,
                    room.name,
                    wall.id,
                    k,
                    wall.length,
                    ceiling,
                    assumed,
                    openings,
                    tuple(sorted(w.points, key=lambda p: (p.x, p.y))),
                    tuple(sorted(w.boxes, key=lambda b: b.x)),
                    tuple(sorted(w.chases, key=lambda c: (c.x, c.y0))),
                    w.board,
                    behind(geoms[room.id], seg, list(geoms.values())),
                    _back_points(seg, room.id, geoms, elec, numbers),
                )
            )
    return out


def elevation_data(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical,
    wiring: Wiring | None,
    colors: dict[str, int],
) -> list[dict[str, Any]]:
    """Развёртки данными для своего показа в просмотре (ключ elevations страницы, как щит):
    стена, проёмы, штробы, щит, коробки и точки — с номером листа электрики, названием,
    группой и коробкой, от которой к точке идёт линия проводки (связь с листом проводки).
    Ключи объектов — как на листах (point:<id>, box:<id>, board:board). Ещё — внутренняя
    грань на плане (face: где стоять, чтобы видеть стену, — мини-схема) и соседние стены в
    углах (left, right: внутренний угол turn и что на соседней стене — для изометрии)."""
    lang = plan.language
    points = {p.id: p for p in elec.points}
    boxes = {b.id: b for b in wiring.boxes} if wiring is not None else {}
    board = elec.board.name if elec.board is not None else "board"
    feeds = {r.target: r.source for r in wiring.runs} if wiring is not None else {}

    def fed(target: str) -> str | None:
        src = feeds.get(target)
        if src is None:
            return None
        return board if src == "board" else boxes[src].label if src in boxes else src

    def color(group: str | None) -> str | None:
        c = colors.get(group or "")
        return f"#{c:06x}" if c is not None else None

    def r(v: float) -> float:
        return round(v, 1)

    def content(e: WallElevation) -> dict[str, Any]:
        pts = []
        for pv in e.points:
            p = points[pv.id]
            pts.append(
                {
                    "id": pv.id,
                    "key": f"point:{pv.id}",
                    "n": pv.number,
                    "type": pv.type.value,
                    "name": point_name(p, lang),
                    "x": r(pv.x),
                    "y": r(pv.y),
                    "posts": pv.posts,
                    "group": p.group,
                    "color": color(p.group),
                    "from": fed(pv.id),
                }
            )
        data: dict[str, Any] = {
            "key": f"elevation:{e.key}",
            "length": r(e.length),
            "openings": [
                {
                    "kind": o.kind,
                    "x0": r(o.x0),
                    "x1": r(o.x1),
                    "y0": r(o.y0),
                    "y1": r(o.y1),
                    "assumed": o.assumed,
                }
                for o in e.openings
            ],
            "chases": [
                {"x": r(c.x), "y0": r(c.y0), "y1": r(c.y1), "wide": c.wide, "low": c.low}
                for c in e.chases
            ],
            "boxes": [
                {
                    "id": b.id,
                    "key": f"box:{b.id}",
                    "label": b.label,
                    "x": r(b.x),
                    "y": r(b.y),
                    "size": r(b.size),
                    "group": boxes[b.id].group if b.id in boxes else None,
                    "color": color(boxes[b.id].group if b.id in boxes else None),
                    "from": fed(b.id),
                }
                for b in e.boxes
            ],
            "points": pts,
            "back": [
                {
                    "id": p.id,
                    "n": p.number,
                    "type": p.type.value,
                    "x": r(p.x),
                    "y": r(p.y),
                    "posts": p.posts,
                }
                for p in e.back
            ],
        }
        if e.board is not None:
            b = e.board
            data["board"] = {
                "key": "board:board",
                "name": b.name,
                "x": r(b.x),
                "y": r(b.y),
                "width": r(b.width),
                "height": r(b.height),
            }
        return data

    elevations = wall_elevations(plan, contours, elec, wiring)
    ceiling = elevations[0].height if elevations else 2700.0
    done = {(e.room, e.wall): content(e) for e in elevations}
    geoms = {g.room.id: g for g in room_geometries(plan, contours)}

    def neighbour(room: Room, k: int, turn: float) -> dict[str, Any]:
        """Соседняя стена в углу (k — её индекс в обходе, с 0): угол и что на ней. Стена
        без электрики — только проёмы."""
        wall = room.walls[k % len(room.walls)]
        side = done.get((room.id, wall.id))
        if side is None:
            side = content(
                WallElevation(
                    room.id,
                    room.name,
                    wall.id,
                    0,
                    wall.length,
                    ceiling,
                    True,
                    _openings(room, wall.id, ceiling),
                )
            )
        side = {key: v for key, v in side.items() if key != "back"}
        return {"turn": turn, **side}

    out: list[dict[str, Any]] = []
    for e in elevations:
        room = next(x for x in plan.rooms if x.id == e.room)
        seg = geoms[e.room].contour.segments[e.index - 1]
        k = e.index - 1
        data = {
            **done[(e.room, e.wall)],
            "title": tr("elev_card", lang, room=e.room_name, n=e.index),
            "behind": behind_text(e, lang),
            "height": r(e.height),
            "height_assumed": e.height_assumed,
            "top": r(e.top),
            # Внутренняя грань на плане (мм модели, как сцена 3D): начало — левый угол
            "face": [[r(seg.start.x), r(seg.start.y)], [r(seg.end.x), r(seg.end.y)]],
            # Углы к соседним стенам: слева — к предыдущей по обходу, справа — к следующей
            "left": neighbour(room, k - 1, room.walls[k - 1].turn),
            "right": neighbour(room, k + 1, room.walls[k].turn),
        }
        out.append(data)
    return out


def behind_text(e: WallElevation, language: Language) -> str:
    """Что за стеной — словами: «Спальня (стена 2); Балкон» или «вне квартиры»."""
    names = [
        tr("elev_behind_wall", language, room=room, n=n) if n is not None else room
        for room, n in e.behind
    ]
    return "; ".join(names) if names else tr("elev_outside", language)  # в именах бывают запятые


def _back_points(
    seg: WallSegment,
    room: str,
    geoms: dict[str, RoomGeometry],
    elec: Electrical,
    numbers: dict[str, int],
) -> tuple[PointView, ...]:
    """Выводы соседних помещений на обратной стороне стены seg: точка на стене соседа по
    той же грани — в координатах этой стены (отступ от её левого угла, вид изнутри)."""
    out: list[PointView] = []
    for g in geoms.values():
        if g.room.id == room:
            continue
        for other in _facing_segments(seg, g):
            for p in elec.points:
                if (
                    p.room != g.room.id
                    or p.wall != other.id
                    or p.offset is None
                    or p.height is None
                ):
                    continue
                x = (other.point_at(p.offset) - seg.start).dot(seg.direction)
                if -FACE_TOLERANCE_MM <= x <= seg.length + FACE_TOLERANCE_MM:
                    out.append(PointView(p.id, numbers[p.id], p.type, x, p.height, _posts(p)))
    return tuple(sorted(out, key=lambda p: (p.x, p.y)))


def _posts(p: ElectricalPoint) -> int:
    """Постов в рамке: у розеток и слаботочки — count, у остального — один."""
    return p.count if p.type in (PointType.SOCKET, PointType.DATA, PointType.TV) else 1


def behind(
    g: RoomGeometry, seg: WallSegment, geoms: Sequence[RoomGeometry]
) -> tuple[tuple[str, int | None], ...]:
    """Что за стеной seg помещения g: соседние помещения (по точкам за внешней гранью вдоль
    всей стены — перегородка бывает общей не целиком, за длинной стеной — несколько
    помещений) и номер стены соседа по той же грани; пусто — за стеной не помещение квартиры."""
    out: list[tuple[str, int | None]] = []
    n = max(3, round(seg.length / BEHIND_STEP_MM))
    for k in range(n):
        at = seg.length * (k + 0.5) / n
        p = seg.point_at(at) + seg.outward * (seg.thickness + BEHIND_PROBE_MM)
        for o in geoms:
            if o is g or not point_in_polygon(p, o.contour.vertices):
                continue
            item = (o.room.name, _facing(seg, o))
            if item not in out:
                out.append(item)
    return tuple(out)


def _facing_segments(seg: WallSegment, other: RoomGeometry) -> list[WallSegment]:
    """Стены соседа — обратная сторона seg: идут навстречу по внешней грани seg и
    перекрываются с ней вдоль стены."""
    far = seg.start + seg.outward * seg.thickness
    out: list[WallSegment] = []
    for o in other.contour.segments:
        if o.direction.dot(seg.direction) > -0.99:
            continue
        if abs((o.start - far).dot(seg.outward)) > FACE_TOLERANCE_MM:
            continue
        a = (o.end - seg.start).dot(seg.direction)
        b = (o.start - seg.start).dot(seg.direction)
        if min(b, seg.length) - max(a, 0.0) > FACE_TOLERANCE_MM:
            out.append(o)
    return out


def _facing(seg: WallSegment, other: RoomGeometry) -> int | None:
    """Номер (с 1) первой стены соседа — обратной стороны seg."""
    found = _facing_segments(seg, other)
    return found[0].index + 1 if found else None


def _openings(room: Room, wall: str, ceiling: float) -> tuple[OpeningView, ...]:
    return tuple(
        _opening(o.type, o.offset, o.width, o.sill, o.height, ceiling)
        for o in room.openings
        if o.wall == wall
    )


def _box_side(size: str) -> float:
    """Сторона коробки на развёртке по типоразмеру: «100x100» → 100, «80» (круглая) → 80."""
    try:
        return float(size.split("x")[0])
    except ValueError:
        return BOX_DEFAULT_MM


def _opening(
    kind: OpeningType,
    offset: float,
    width: float,
    sill: float | None,
    height: float | None,
    ceiling: float,
) -> OpeningView:
    if kind is OpeningType.WINDOW:
        s = sill if sill is not None else WINDOW_SILL_MM
        top = s + (height if height is not None else WINDOW_HEIGHT_MM)
        return OpeningView(
            "window", offset, offset + width, s, min(top, ceiling), sill is None or height is None
        )
    top = height if height is not None else DOOR_TOP_MM
    return OpeningView(kind.value, offset, offset + width, 0.0, min(top, ceiling), height is None)
