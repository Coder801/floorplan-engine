"""Отрисовка электрики: розетки, выключатели, светильники, щит, легенда.

Трассы кабелей здесь не рисуются — только на листе проводки (draw_wiring.py), чтобы
на чертеже был один способ разводки. Кабели модели дают группам марку кабеля.

Все точки привязаны к стенам плана (room + wall + offset) или к потолку комнаты
(ceiling — от origin комнаты). Символы — вставки блоков из symbols.py.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.base import BaseLayout
from ezdxf.layouts.layout import Modelspace
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from floorplan_engine.draw_plan import (
    RoomGeometry,
    add_text,
    door_leaf,
    room_geometries,
    wall_pieces,
)
from floorplan_engine.geometry import Contour, Vec
from floorplan_engine.ids import tagged
from floorplan_engine.labels import Align, LabelPlacer, Metrics, door_swing
from floorplan_engine.layers import (
    E_LED,
    E_TEXT,
    TEXT_DIM_MM,
    TEXT_SMALL_MM,
    sheet,
    sheet_scale,
    text_width,
)
from floorplan_engine.point_numbers import number_points, ranges
from floorplan_engine.schema import (
    CEILING_TYPES,
    Board,
    Electrical,
    ElectricalPoint,
    LedStrip,
    OpeningType,
    Plan,
)
from floorplan_engine.symbols import (
    BOARD_DEPTH,
    LEGEND_ORDER,
    SYMBOLS,
    SymbolSpec,
    symbol_key,
)
from floorplan_engine.tables import TEXT_GAP
from floorplan_engine.texts import Language, tr

LABEL_GAP_MM = 1.0
LINE_STEP_MM = TEXT_SMALL_MM * 1.5
STACK_GAP_MM = 1.0  # между символами, стоящими в одной точке стены
STACK_TOLERANCE = 30.0  # мм: точки ближе этого по стене рисуются стопкой
LABEL_CLUSTER_GAP = 250.0  # мм: соседние точки на стене ближе этого подписываются вместе
LABEL_PROBE_MM = 1.0  # шаг перебора мест подписи, мм листа
LABEL_REACH = 12  # сколько шагов подпись может уйти от символа (вдоль стены и от неё)
LABEL_FAR = 40  # рядом места нет — ищется до стольких шагов, с выноской
LABEL_BAND_MM = 6.0  # насколько подпись может выйти за габарит плана, мм листа
LEADER_MIN_MM = 3.0  # дальше этого от символа — подпись с выноской
LW_LEADER = 13  # толщина выноски, сотые мм
# Цвета групп — мягкие, RGB (true color в DXF), различимые между собой и читаемые тонкой
# линией на белом (решение 2026-10-25); серых нет: просмотр в тёмной теме перекрашивает серое
GROUP_PALETTE = (
    "#4e79a7",  # синий
    "#f28e2b",  # оранжевый
    "#59a14f",  # зелёный
    "#e15759",  # красный
    "#76b7b2",  # бирюзовый
    "#d4a72c",  # охра
    "#b07aa1",  # сиреневый
    "#e67f8a",  # розовый
    "#9c755f",  # коричневый
    "#5f9ed1",  # голубой
    "#8cbf5f",  # салатовый
    "#c9845c",  # терракота
    "#7f7fc9",  # лавандовый
    "#4fb0a0",  # морская волна
)
GROUP_SWATCH_MM = 6.0  # отрезок цвета группы в легенде
LW_SWATCH = 50
LED_INSET_MM = 1.0  # лента — чуть внутри помещения от грани стены
LW_LED = 35


@dataclass(frozen=True)
class Anchor:
    """Положение символа: точка вставки и направление в помещение (None — потолок)."""

    pos: Vec
    inward: Vec | None
    wall_dir: Vec | None
    depth: float

    @property
    def node(self) -> Vec:
        """Точка подключения трассы — «макушка» символа."""
        return self.pos if self.inward is None else self.pos + self.inward * self.depth

    @property
    def rotation(self) -> float:
        if self.inward is None:
            return 0.0
        return math.degrees(math.atan2(self.inward.y, self.inward.x)) - 90.0

    @property
    def wall_is_vertical(self) -> bool:
        return self.wall_dir is not None and abs(self.wall_dir.y) > abs(self.wall_dir.x)


def _geom(geoms: dict[str, RoomGeometry], room_id: str) -> RoomGeometry:
    return geoms[room_id]


def wall_anchor(
    geoms: dict[str, RoomGeometry], room_id: str, wall: str, offset: float, depth: float
) -> Anchor:
    seg = _geom(geoms, room_id).contour.segment(wall)
    return Anchor(seg.point_at(offset), seg.inward, seg.direction, depth)


def point_anchor(pt: ElectricalPoint, geoms: dict[str, RoomGeometry], shift: float = 0.0) -> Anchor:
    """Положение символа; shift — сдвиг от стены в помещение (для стопки в одной точке)."""
    spec = SYMBOLS[symbol_key(pt)]
    if pt.ceiling is not None:
        origin = Vec(*_geom(geoms, pt.room).room.origin)
        return Anchor(origin + Vec(*pt.ceiling), None, None, sheet(spec.depth))
    assert pt.wall is not None and pt.offset is not None
    a = wall_anchor(geoms, pt.room, pt.wall, pt.offset, sheet(spec.depth))
    if shift == 0.0 or a.inward is None:
        return a
    return Anchor(a.pos + a.inward * shift, a.inward, a.wall_dir, a.depth)


def stacks(points: Sequence[ElectricalPoint]) -> list[list[int]]:
    """Точки на одной стене в одном месте (в пределах STACK_TOLERANCE от первой) — розетка
    под выключателем и т. п., по порядку из YAML; потолочные точки — каждая сама по себе."""
    out: list[list[int]] = []
    for k, pt in enumerate(points):
        if pt.wall is None or pt.offset is None:
            out.append([k])
            continue
        group = next(
            (
                g
                for g in out
                if (first := points[g[0]]).room == pt.room
                and first.wall == pt.wall
                and first.offset is not None
                and abs(first.offset - pt.offset) <= STACK_TOLERANCE
            ),
            None,
        )
        if group is None:
            out.append([k])
        else:
            group.append(k)
    return out


def stack_shifts(points: Sequence[ElectricalPoint]) -> list[float]:
    """Сдвиг каждой точки от стены: следующая в стопке ставится за предыдущей."""
    shifts = [0.0] * len(points)
    for group in stacks(points):
        acc = 0.0
        for k in group:
            shifts[k] = acc
            acc += sheet(SYMBOLS[symbol_key(points[k])].depth + STACK_GAP_MM)
    return shifts


def board_anchor(board: Board, geoms: dict[str, RoomGeometry]) -> Anchor:
    return wall_anchor(geoms, board.room, board.wall, board.offset, sheet(BOARD_DEPTH))


def insert_symbol(
    msp: BaseLayout,
    spec: SymbolSpec,
    anchor: Anchor,
    xscale: float = 1.0,
    yscale: float = 1.0,
    attribs: dict[str, str] | None = None,
) -> None:
    """Вставка блока УГО; attribs — значения невидимых атрибутов ID, H, GROUP (в модели)."""
    ref = msp.add_blockref(
        spec.block,
        anchor.pos.as_tuple(),
        dxfattribs={
            "layer": spec.layer,
            "rotation": anchor.rotation,
            "xscale": xscale,
            "yscale": yscale,
        },
    )
    if attribs is not None:
        ref.add_auto_attribs(attribs)
        # Щит растянут под свою ширину: атрибуты с ним растянулись бы на десятки метров
        # и раздули габарит вида. Атрибуты невидимы — им нужен обычный размер в точке вставки
        for attrib in ref.attribs:
            attrib.dxf.height = sheet(TEXT_SMALL_MM)
            attrib.dxf.width = 1.0
            attrib.dxf.insert = anchor.pos.as_tuple()


def point_attribs(pt: ElectricalPoint) -> dict[str, str]:
    height = "" if pt.height is None else f"{pt.height:g}"
    return {"ID": pt.id, "H": height, "GROUP": pt.group or ""}


# --- Подписи -----------------------------------------------------------------


def label_clusters(points: Sequence[ElectricalPoint]) -> list[list[int]]:
    """Точки одной стены, идущие подряд с шагом не больше LABEL_CLUSTER_GAP, — одна подпись.
    Потолочные точки подписываются каждая отдельно."""
    by_wall: dict[tuple[str, str], list[int]] = {}
    out: list[list[int]] = []
    for k, pt in enumerate(points):
        if pt.wall is None or pt.offset is None:
            out.append([k])
        else:
            by_wall.setdefault((pt.room, pt.wall), []).append(k)
    for idx in by_wall.values():
        idx.sort(key=lambda k: points[k].offset or 0.0)
        cluster = [idx[0]]
        for k in idx[1:]:
            prev = points[cluster[-1]].offset or 0.0
            if (points[k].offset or 0.0) - prev <= LABEL_CLUSTER_GAP:
                cluster.append(k)
            else:
                out.append(cluster)
                cluster = [k]
        out.append(cluster)
    return out


def _symbol_area(a: Anchor, half: float | None = None) -> BaseGeometry:
    """Габарит символа для размещения подписей: у стены — от стены на depth, шириной в
    две глубины (или 2 × half); на потолке — квадрат по радиусу."""
    if a.inward is None:
        r = a.depth
        return box(a.pos.x - r, a.pos.y - r, a.pos.x + r, a.pos.y + r)
    half = half if half is not None else max(a.depth, sheet(1.5))
    u = a.inward.left() * half
    tip = a.pos + a.inward * a.depth
    corners = [a.pos + u, a.pos - u, tip - u, tip + u]
    return Polygon([c.as_tuple() for c in corners]).envelope


def _strip_area(strip: LedStrip, geoms: dict[str, RoomGeometry]) -> BaseGeometry:
    """LED-лента — линия вдоль стены: подписи на неё не ложатся."""
    seg = _geom(geoms, strip.room).contour.segment(strip.wall)
    a = seg.point_at(strip.start) + seg.inward * sheet(LED_INSET_MM)
    b = seg.point_at(strip.end) + seg.inward * sheet(LED_INSET_MM)
    return LineString([a.as_tuple(), b.as_tuple()]).buffer(sheet(0.5))


def _opening_areas(geoms: Sequence[RoomGeometry]) -> list[BaseGeometry]:
    """Зоны проёмов: открывание дверей и окна (остекление в толще стены)."""
    out: list[BaseGeometry] = []
    for g in geoms:
        for op in g.room.openings:
            seg = g.contour.segment(op.wall)
            if op.type is OpeningType.DOOR:
                hinge, closed, normal = door_leaf(g, seg, op)
                out.append(door_swing(hinge, closed, normal, op.width))
            elif op.type is OpeningType.WINDOW:
                a, b = op.offset, op.offset + op.width
                corners = [
                    seg.point_at(a),
                    seg.point_at(b),
                    g.outer_point(seg, b),
                    g.outer_point(seg, a),
                ]
                out.append(Polygon([c.as_tuple() for c in corners]))
    return out


def label_placer(
    geoms: Sequence[RoomGeometry],
    symbols: Sequence[BaseGeometry],
    strips: Sequence[BaseGeometry] = (),
) -> LabelPlacer:
    """Размещение подписей листа: символы — препятствия для подписи и выноски, проёмы и
    LED-ленты — только для подписи."""
    metrics = Metrics(
        line_h=sheet(TEXT_SMALL_MM),
        step=sheet(LINE_STEP_MM),
        gap=sheet(LABEL_GAP_MM),
        probe=sheet(LABEL_PROBE_MM),
        reach=LABEL_REACH,
        far=LABEL_FAR,
        leader_min=sheet(LEADER_MIN_MM),
    )
    walls = unary_union([p.polygon for g in geoms for p in wall_pieces(g)])
    zones = [*_opening_areas(geoms), *strips]
    # За контур квартиры — только в полосе LABEL_BAND_MM у плана: иначе вид листа растёт
    frame = box(*unary_union([walls, *zones]).bounds).buffer(
        sheet(LABEL_BAND_MM), join_style="mitre"
    )
    rooms = {g.room.id: Polygon([v.as_tuple() for v in g.contour.vertices]) for g in geoms}
    return LabelPlacer(walls, symbols, zones, metrics, frame, rooms)


ALIGN = {
    Align.LEFT: TextEntityAlignment.MIDDLE_LEFT,
    Align.RIGHT: TextEntityAlignment.MIDDLE_RIGHT,
    Align.CENTER: TextEntityAlignment.MIDDLE_CENTER,
}


def place_label(
    msp: Modelspace,
    placer: LabelPlacer,
    lines: Sequence[str],
    anchor: Anchor,
    own: BaseGeometry | None = None,
    room: str | None = None,
    layer: str = E_TEXT.name,
) -> None:
    """Горизонтальная подпись у символа в свободном месте (labels.py); далеко — с выноской.
    layer — слой подписи (лист освещения — свой)."""
    lines = [s for s in lines if s]
    if not lines:
        return
    h = sheet(TEXT_SMALL_MM)
    widths = [text_width(t, h) for t in lines]
    placed = placer.place(lines, widths, anchor.pos, anchor.inward, anchor.depth, own, room)
    for text, at in placed.lines:
        add_text(msp, text, at, TEXT_SMALL_MM, layer, align=ALIGN[placed.align])
    if placed.leader is not None:
        a, b = placed.leader
        attribs = {"layer": layer, "lineweight": LW_LEADER}
        msp.add_line(a.as_tuple(), b.as_tuple(), dxfattribs=attribs)


def group_key(group: str) -> tuple[str, int, int]:
    """QF2 раньше QF10, линия QF1.2 — сразу после QF1: сортировка по числам в имени группы."""
    m = re.match(r"^(\D*)(\d+)(?:\.(\d+))?", group)
    return (m.group(1), int(m.group(2)), int(m.group(3) or 1)) if m else (group, 0, 0)


def rgb(hex_color: str) -> int:
    """«#4e79a7» → число true color DXF (0xRRGGBB)."""
    return int(hex_color.lstrip("#"), 16)


def group_colors(elec: Electrical) -> dict[str, int]:
    """Свой цвет (true color, 0xRRGGBB) для каждой группы — по порядку номеров."""
    groups = sorted(
        {p.group for p in elec.points if p.group} | {c.group for c in elec.cables if c.group},
        key=group_key,
    )
    return {g: rgb(GROUP_PALETTE[k % len(GROUP_PALETTE)]) for k, g in enumerate(groups)}


def draw_led_strip(msp: Modelspace, strip: LedStrip, geoms: dict[str, RoomGeometry]) -> None:
    seg = _geom(geoms, strip.room).contour.segment(strip.wall)
    a = seg.point_at(strip.start) + seg.inward * sheet(LED_INSET_MM)
    b = seg.point_at(strip.end) + seg.inward * sheet(LED_INSET_MM)
    msp.add_line(a.as_tuple(), b.as_tuple(), dxfattribs={"layer": E_LED.name, "lineweight": LW_LED})
    if strip.note:
        mid = a + (b - a) * 0.5 + seg.inward * sheet(TEXT_SMALL_MM)
        add_text(msp, strip.note, mid, TEXT_SMALL_MM, E_TEXT.name, seg.angle_deg)


# --- Легенда -----------------------------------------------------------------


LEGEND_ROW = 9.0  # мм листа
LEGEND_TEXT_X = 9.0  # от левого края легенды до подписи
LEGEND_SYMBOL_X = 3.0


@dataclass(frozen=True)
class LegendRow:
    """Строка легенды: символ блока (key), линия LED или заголовок/группа (только текст)."""

    text: str
    height: float  # мм листа
    step: float  # шаг от предыдущей строки, мм листа
    key: str | None = None
    led: bool = False
    color: int | None = None  # группа: true color отрезка перед именем


def legend_rows(elec: Electrical, language: Language = "ru") -> list[LegendRow]:
    rows = [LegendRow(tr("legend", language), TEXT_DIM_MM, 0.0)]
    present = {symbol_key(p) for p in elec.points}
    if elec.board is not None:
        present.add("board")
    for key in (k for k in LEGEND_ORDER if k in present):
        rows.append(LegendRow(tr(f"symbol_{key}", language), TEXT_SMALL_MM, LEGEND_ROW, key=key))
    if elec.led_strips:
        rows.append(
            LegendRow(tr("legend_led_strip", language), TEXT_SMALL_MM, LEGEND_ROW, led=True)
        )
    colors = group_colors(elec)
    if colors:
        rows.append(LegendRow(tr("groups", language), TEXT_DIM_MM, LEGEND_ROW * 1.5))
    for group, color in colors.items():
        # Только имя и цвет линии: назначение, кабель и точки — в таблице «Группы щита»
        rows.append(LegendRow(group, TEXT_SMALL_MM, LEGEND_ROW * 0.7, color=color))
    return rows


def legend_size(rows: Sequence[LegendRow]) -> tuple[float, float]:
    """Ширина и высота легенды на листе, мм (ширина — по метрикам шрифта)."""
    width = max(
        (LEGEND_TEXT_X if r.key or r.led or r.color is not None else 0.0)
        + text_width(r.text, r.height)
        + TEXT_GAP
        for r in rows
    )
    height = sum(r.step for r in rows) + rows[0].height + LEGEND_ROW / 2
    return width, height


def split_legend(rows: Sequence[LegendRow]) -> tuple[list[LegendRow], list[LegendRow]]:
    """Символы и группы — две отдельные колонки; заголовок групп становится первой строкой."""
    k = next((i for i, r in enumerate(rows) if i and r.key is None and not r.led), len(rows))
    groups = list(rows[k:])
    if groups:
        groups[0] = replace(groups[0], step=0.0)
    return list(rows[:k]), groups


def draw_legend(psp: BaseLayout, rows: Sequence[LegendRow], top_left: Vec) -> None:
    """Легенда на листе (мм листа) от левого верхнего угла: символы — те же блоки УГО,
    уменьшенные в масштаб листа."""
    x0 = top_left.x
    y = top_left.y - rows[0].height
    left = TextEntityAlignment.MIDDLE_LEFT
    for row in rows:
        y -= row.step
        if row.key is not None:
            spec = SYMBOLS[row.key]
            on_ceiling = row.key in {str(t) for t in CEILING_TYPES}
            depth = spec.depth
            sym_at = Vec(x0 + LEGEND_SYMBOL_X, y if on_ceiling else y - depth / 2)
            anchor = Anchor(sym_at, None if on_ceiling else Vec(0, 1), Vec(1, 0), depth)
            if row.key == "board":
                insert_symbol(psp, spec, anchor, xscale=6.0, yscale=BOARD_DEPTH)
            else:
                insert_symbol(psp, spec, anchor)
        if row.led:
            psp.add_line(
                (x0, y), (x0 + 6.0, y), dxfattribs={"layer": E_LED.name, "lineweight": LW_LED}
            )
        if row.color is not None:  # группа: отрезок её цвета, как линии на листе
            psp.add_line(
                (x0 + LEGEND_SYMBOL_X - GROUP_SWATCH_MM / 2, y),
                (x0 + LEGEND_SYMBOL_X + GROUP_SWATCH_MM / 2, y),
                dxfattribs={"layer": E_TEXT.name, "true_color": row.color, "lineweight": LW_SWATCH},
            )
        x = x0 + (LEGEND_TEXT_X if row.key or row.led or row.color is not None else 0.0)
        add_text(psp, row.text, Vec(x, y), row.height, E_TEXT.name, align=left, scale=1.0)


# --- Сборка ------------------------------------------------------------------


def draw_electrical(
    msp: Modelspace, plan: Plan, contours: dict[str, Contour], elec: Electrical
) -> None:
    geoms_list = room_geometries(plan, contours)
    geoms = {g.room.id: g for g in geoms_list}
    for strip in elec.led_strips:
        with tagged(msp, "led_strip", strip.id):
            draw_led_strip(msp, strip, geoms)
    shifts = stack_shifts(elec.points)
    anchors = [point_anchor(pt, geoms, shifts[k]) for k, pt in enumerate(elec.points)]
    for k, pt in enumerate(elec.points):
        with tagged(msp, "point", pt.id):
            k_ins = sheet_scale()
            insert_symbol(
                msp,
                SYMBOLS[symbol_key(pt)],
                anchors[k],
                xscale=k_ins,
                yscale=k_ins,
                attribs=point_attribs(pt),
            )
    board_area = None
    if elec.board is not None:
        board = board_anchor(elec.board, geoms)
        board_area = _symbol_area(board, elec.board.width / 2)
    symbols = [_symbol_area(a) for a in anchors] + ([board_area] if board_area else [])
    strips = [_strip_area(strip, geoms) for strip in elec.led_strips]
    placer = label_placer(geoms_list, symbols, strips)
    numbers = number_points(plan, elec)
    for cluster in label_clusters(elec.points):
        # У символа — только номера (вид и высота — в таблице «Точки»); подпись — по центру
        # группы, за самым далёким от стены символом
        lines = [ranges([numbers[elec.points[k].id] for k in cluster])]
        first, last = anchors[cluster[0]], anchors[cluster[-1]]
        deepest = max(
            (anchors[k] for k in cluster),
            key=lambda a: 0.0 if a.inward is None else (a.pos - first.pos).dot(a.inward) + a.depth,
        )
        center = first.pos + (last.pos - first.pos) * 0.5
        if deepest.inward is not None:
            center += deepest.inward * (deepest.pos - center).dot(deepest.inward)
        label_at = Anchor(center, deepest.inward, deepest.wall_dir, deepest.depth)
        own = unary_union([_symbol_area(anchors[k]) for k in cluster])
        with tagged(msp, "label", ",".join(elec.points[k].id for k in cluster)):
            place_label(msp, placer, lines, label_at, own, elec.points[cluster[0]].room)
    if elec.board is not None:
        b = elec.board
        anchor = board_anchor(b, geoms)
        with tagged(msp, "board", "board"):
            attribs = {"ID": "board", "H": f"{b.height:g}", "GROUP": ""}
            insert_symbol(
                msp,
                SYMBOLS["board"],
                anchor,
                xscale=b.width,
                yscale=sheet(BOARD_DEPTH),
                attribs=attribs,
            )
            place_label(msp, placer, [b.name, f"h{b.height:g}"], anchor, board_area, b.room)
