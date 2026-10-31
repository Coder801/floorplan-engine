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

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from floorplan_engine.electrical.anchors import Anchor, board_anchor, point_anchor, stack_shifts
from floorplan_engine.electrical.boxes import (
    BOX_BRANCHES,
    BOX_SIZE_MM,
    FAN_ANGLE,
    anchor_end,
    box_size,
    branch_reach,
    fan_angle,
    moved_anchor,
    place_box,
    place_ceiling_box,
    split_points,
)
from floorplan_engine.electrical.chases import (
    passages,
    wall_chases,
    wall_holes,
)
from floorplan_engine.electrical.groups import group_key
from floorplan_engine.electrical.routing import (
    Router,
    fit_path,
    free_area,
    length,
    room_area,
)
from floorplan_engine.electrical.wiring_model import (
    Circuit,
    JunctionBox,
    Route,
    Run,
    Wiring,
)
from floorplan_engine.model.geometry import Contour, RoomGeometry, Vec, room_geometries
from floorplan_engine.model.scale import DEFAULT_SCALE, drawing_scale, sheet
from floorplan_engine.model.schema import (
    Board,
    Cable,
    Electrical,
    ElectricalPoint,
    Plan,
    PointType,
    WireEdit,
    WiringEdits,
)

END_ALLOWANCE = 200.0  # мм: выпуск кабеля на каждое подключение, кроме щита
RESERVE = 0.15  # запас на итог по марке
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


def estimate_wiring(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical,
    edits: WiringEdits | None = None,
) -> Wiring | None:
    """Проводка для объёмов сметы — всегда в масштабе 1:50. Полосы пучков задаются в мм листа,
    и длины трасс чуть зависят от масштаба листа; смета от формата не зависит: одна и та же
    на листе A2, A3 и в out/estimate.*."""
    with drawing_scale(DEFAULT_SCALE):
        return box_wiring(plan, contours, elec, edits)


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
        Router(free, anchor_end(board_anchor(elec.board, geoms))),
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
        cost = Router(ctx.free, anchor_end(b.anchor)).cost(target.node)
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
    spot = place_box(g, ctx.from_board, reach, taken)
    if spot is not None and route == "ceiling" and fan_angle(spot, fan) >= FAN_ANGLE:
        depth = sheet(BOX_SIZE_MM)
        spot = place_ceiling_box(g, ctx.from_board, reach, taken, depth) or spot
    return spot


def _route_runs(ctx: _Context, links: Sequence[_Link], boxes: Sequence[JunctionBox]) -> list[Run]:
    """Трассы линий: от щита — по всей квартире, от коробки — только внутри её помещения."""
    routers = {b.id: Router(room_area(ctx.geoms[b.room]), anchor_end(b.anchor)) for b in boxes}
    # Ветка к выключателю за дверью — по всей квартире через проём
    wide = {
        b.id: Router(ctx.free, anchor_end(b.anchor))
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
        path = tuple(router.route(anchor_end(ln.target_anchor)))
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
