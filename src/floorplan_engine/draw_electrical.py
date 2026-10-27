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

from floorplan_engine.draw_plan import (
    RoomGeometry,
    add_text,
    room_geometries,
)
from floorplan_engine.geometry import Contour, Vec
from floorplan_engine.ids import tagged
from floorplan_engine.layers import (
    E_LED,
    E_TEXT,
    TEXT_DIM_MM,
    TEXT_SMALL_MM,
    sheet,
    sheet_scale,
    text_width,
)
from floorplan_engine.schema import (
    CEILING_TYPES,
    Board,
    Electrical,
    ElectricalPoint,
    LedStrip,
    Plan,
)
from floorplan_engine.symbols import (
    BOARD_DEPTH,
    LEGEND_ORDER,
    LIGHT_R,
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
LABEL_MAX_PUSH = 15  # сколько раз подпись можно отодвинуть от занятого места
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


def point_label(pt: ElectricalPoint) -> str:
    """Одна строка подписи: «2× h300 примечание». Группа пишется на трассе и в легенде."""
    parts: list[str] = []
    if pt.count > 1:
        parts.append(f"{pt.count}×")
    if pt.height is not None:
        parts.append(f"h{pt.height:g}")
    if pt.note:
        parts.append(pt.note)
    return " ".join(parts)


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


Box = tuple[float, float, float, float]  # x0, y0, x1, y1


def _text_box(text: str, at: Vec, align: TextEntityAlignment) -> Box:
    """Габарит строки по метрикам шрифта."""
    h = sheet(TEXT_SMALL_MM)
    w = text_width(text, h)
    x0 = {
        TextEntityAlignment.MIDDLE_LEFT: at.x,
        TextEntityAlignment.MIDDLE_RIGHT: at.x - w,
    }.get(align, at.x - w / 2)
    y0 = {
        TextEntityAlignment.BOTTOM_CENTER: at.y,
        TextEntityAlignment.TOP_CENTER: at.y - h,
    }.get(align, at.y - h / 2)
    return (x0, y0, x0 + w, y0 + h)


def _overlaps(a: Box, b: Box) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def place_label(
    msp: Modelspace, lines: Sequence[str], anchor: Anchor, taken: list[Box] | None = None
) -> None:
    """Горизонтальные подписи у символа, со стороны помещения.

    taken — уже занятые подписями места: если блок строк задевает их, он отодвигается
    дальше от стены (у потолочных — вниз), пока не найдётся свободное место.
    """
    lines = [s for s in lines if s]
    if not lines:
        return
    if anchor.inward is None:
        at = anchor.pos + Vec(sheet(LIGHT_R + LABEL_GAP_MM), 0)
        down = Vec(0, -sheet(LINE_STEP_MM))
        align, step, push = TextEntityAlignment.MIDDLE_LEFT, down, down
    else:
        n = anchor.inward
        at = anchor.pos + n * (anchor.depth + sheet(LABEL_GAP_MM))
        push = n * sheet(LINE_STEP_MM)
        if abs(n.x) >= abs(n.y):
            align = TextEntityAlignment.MIDDLE_LEFT if n.x > 0 else TextEntityAlignment.MIDDLE_RIGHT
            step = Vec(0, -sheet(LINE_STEP_MM))
        else:
            align = TextEntityAlignment.BOTTOM_CENTER if n.y > 0 else TextEntityAlignment.TOP_CENTER
            step = n * sheet(LINE_STEP_MM)
    boxes: list[Box] = []
    for _ in range(LABEL_MAX_PUSH):
        boxes = [_text_box(t, at + step * k, align) for k, t in enumerate(lines)]
        if taken is None or not any(_overlaps(b, t) for b in boxes for t in taken):
            break
        at += push
    if taken is not None:
        taken.extend(boxes)
    for k, text in enumerate(lines):
        add_text(msp, text, at + step * k, TEXT_SMALL_MM, E_TEXT.name, align=align)


def group_key(group: str) -> tuple[str, int]:
    """QF2 раньше QF10: сортировка по числу в имени группы."""
    m = re.match(r"^(\D*)(\d+)", group)
    return (m.group(1), int(m.group(2))) if m else (group, 0)


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
    taken: list[Box] = []
    for cluster in label_clusters(elec.points):
        # Строки без повторов, по порядку вдоль стены; подпись — по центру группы,
        # за самым далёким от стены символом
        lines = list(dict.fromkeys(point_label(elec.points[k]) for k in cluster))
        first, last = anchors[cluster[0]], anchors[cluster[-1]]
        deepest = max(
            (anchors[k] for k in cluster),
            key=lambda a: 0.0 if a.inward is None else (a.pos - first.pos).dot(a.inward) + a.depth,
        )
        center = first.pos + (last.pos - first.pos) * 0.5
        if deepest.inward is not None:
            center += deepest.inward * (deepest.pos - center).dot(deepest.inward)
        label_at = Anchor(center, deepest.inward, deepest.wall_dir, deepest.depth)
        with tagged(msp, "label", ",".join(elec.points[k].id for k in cluster)):
            place_label(msp, lines, label_at, taken)
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
            place_label(msp, [b.name, f"h{b.height:g}"], anchor, taken)
