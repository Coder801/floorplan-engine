"""Документ проекта: модель 1:1 и листы с видовыми экранами 1:50.

Модель — вся геометрия всех этапов, каждый этап на своих слоях. Лист (layout) — рамка
и основная надпись в мм листа, видовой экран 1:50 на модель, в котором заморожены
слои чужих этапов, таблицы и легенда.

Раскладка листа одна для всех — четыре секции, крест которых проходит через левый
верхний угол штампа:

    план    | таблицы
    легенда | штамп

План — по центру своей секции и занимает около VIEW_FILL её; таблицы — прижаты к правому
краю своей секции, одна под другой; не влезли — колонками справа налево, и колонки за линией
штампа забирают место у секции плана (arrange); легенда — в секции слева от штампа. Формат,
ориентация и масштаб — общие для комплекта.

Таблицы, что не входят ни на один формат (печать на заданном формате, `print --paper A3`),
уходят на лист-продолжение «… (продолжение)» во всю ширину над штампом; таблица выше листа
делится по строкам на колонки (`fit_specs`).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date

from ezdxf import bbox
from ezdxf.document import Drawing
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.layout import Modelspace, Paperspace
from ezdxf.math import BoundingBox

from floorplan_engine.draw_electrical import (
    LegendRow,
    draw_electrical,
    draw_legend,
    group_colors,
    legend_rows,
    legend_size,
    split_legend,
)
from floorplan_engine.draw_elevations import elevation_panel
from floorplan_engine.draw_panel import devices_table, draw_panel_front, fit_panel, panel_notes
from floorplan_engine.draw_plan import RoomArea, add_text, draw_plan, plan_stamp
from floorplan_engine.draw_wiring import draw_wiring, wiring_notes, wiring_table
from floorplan_engine.elevations import wall_elevations
from floorplan_engine.estimate import PRICES_FILE, PriceList, build_estimate, estimate_table
from floorplan_engine.estimate import text as estimate_text
from floorplan_engine.fields import finalize_fields
from floorplan_engine.geometry import Contour, Vec
from floorplan_engine.groups import groups_table
from floorplan_engine.layers import (
    A_DIMS,
    A_DOOR,
    A_SHEET,
    A_TEXT,
    A_VPORT,
    A_WALL,
    A_WIND,
    ALL_LAYERS,
    DEFAULT_SCALE,
    E_BOARD,
    E_DATA,
    E_LED,
    E_LIGHT,
    E_SOCKET,
    E_SWITCH,
    E_TEXT,
    ELECTRICAL_LAYERS,
    LIGHTING_LAYERS,
    SCALES,
    TEXT_SMALL_MM,
    WIRING_LAYERS,
    LayerSpec,
    drawing_scale,
    new_document,
    sheet_scale,
    text_width,
)
from floorplan_engine.lighting import draw_lighting, is_lighting, switch_table
from floorplan_engine.panel import build_panel
from floorplan_engine.point_numbers import points_table
from floorplan_engine.schema import LIGHT_TYPES, Electrical, Plan, WiringEdits
from floorplan_engine.specification import specification_table
from floorplan_engine.symbols import define_blocks
from floorplan_engine.tables import Table, draw_table, room_schedule
from floorplan_engine.texts import TEXTS, Language, tr
from floorplan_engine.titleblock import (
    PADDING,
    STAMP_H,
    STAMP_W,
    Region,
    SheetLayout,
    StampText,
    draw_sheet,
    format_candidates,
    frame_region,
)
from floorplan_engine.wiring import Wiring, box_wiring, estimate_wiring

VIEW_MARGIN = 3.0  # поле вокруг чертежа внутри видового экрана, мм листа
PANEL_GAP = 10.0  # между таблицами и колонками легенды, мм листа
ELEV_NOTES_W = 160.0  # ширина пояснения к развёрткам, мм листа
MIN_LEAD_ROWS = 5  # меньше строк в остатке колонки — таблица начинается в следующей
VIEW_FILL = 0.94  # какую долю секции плана занимает чертёж — цель (решение 2026-10-21)
VIEW_FILL_MAX = 1.0  # больше — чертёж вылезает из секции
LEGEND_PAD = 5.0  # отступ легенды сверху и снизу: секция низкая, по высоте штампа
# Бумага: (формат, ширина, высота) в мм — с ориентацией
Paper = tuple[str, float, float]
VIEWPORT_LOCKED = 16384  # флаг VIEWPORT «Display locked»: колесо мыши не сбивает масштаб
# Слой 0 несёт содержимое блоков, слои листа модели не касаются
NEVER_FROZEN = frozenset({"0", "DEFPOINTS", A_SHEET.name, A_VPORT.name})

# Что видно в видовом экране каждого листа
PLAN_SHEET_LAYERS = (A_WALL, A_DOOR, A_WIND, A_DIMS, A_TEXT)
ELECTRICAL_SHEET_LAYERS = (A_WALL, A_DOOR, A_WIND, *ELECTRICAL_LAYERS)
# Освещение: стены, свет и выключатели, связи и свои номера; без розеток, щита и групп
LIGHTING_SHEET_LAYERS = (A_WALL, A_DOOR, A_WIND, E_SWITCH, E_LIGHT, E_LED, *LIGHTING_LAYERS)
# Проводка: стены, символы точек и щит, коробки и кабели; без трасс и подписей листа электрики
WIRING_SHEET_LAYERS = (
    A_WALL,
    A_DOOR,
    A_WIND,
    E_SOCKET,
    E_SWITCH,
    E_LIGHT,
    E_DATA,
    E_LED,
    E_BOARD,
    *WIRING_LAYERS,
)
NOTE_STEP = TEXT_SMALL_MM * 1.8
MIDDLE_LEFT = TextEntityAlignment.MIDDLE_LEFT


@dataclass(frozen=True)
class Panel:
    """Блок на листе (таблица, легенда); draw рисует его от левого верхнего угла, мм листа."""

    width: float
    height: float
    draw: Callable[[Paperspace, Vec], None]
    # Части: первая не выше first (остаток колонки), остальные не выше rest (таблица — по
    # строкам); None — блок не делится
    split: Callable[[float, float], list[Panel] | None] | None = None


def table_panel(table: Table) -> Panel:
    """Таблица блоком на листе; выше места — делится по строкам (split_table)."""

    def split(first: float, rest: float) -> list[Panel] | None:
        parts = split_table(table, first, rest)
        return None if parts is None else [table_panel(t) for t in parts]

    return Panel(table.width, table.height, lambda psp, tl: draw_table(psp, table, tl), split)


def split_table(table: Table, first: float, rest: float) -> list[Table] | None:
    """Таблица частями: первая не выше first, остальные — не выше rest; заголовок колонок —
    в каждой, название — в первой, итог — в последней. В first не входят MIN_LEAD_ROWS
    строк — обрывок не ставится, таблица начинается с rest; None — в rest не входят две."""
    head = replace(table, rows=(), total=None).height
    per = int((rest - head) // table.row_h)
    if per < 2:
        return None
    rows = table.rows
    lead = max(0, int((first - head) // table.row_h))
    lead = lead if lead >= MIN_LEAD_ROWS else 0
    chunks = [rows[:lead]] if lead else []
    chunks += [rows[i : i + per] for i in range(lead, len(rows), per)]
    chunks = chunks or [()]
    room = lead if lead and len(chunks) == 1 else per
    if table.total is not None and len(chunks[-1]) >= room:
        chunks[-1], extra = chunks[-1][:-1], chunks[-1][-1:]
        chunks.append(extra)
    last = len(chunks) - 1
    return [
        replace(
            table,
            rows=chunk,
            title=table.title if k == 0 else "",
            total=table.total if k == last else None,
        )
        for k, chunk in enumerate(chunks)
    ]


# Имя PNG листа по его вкладке: «02 Електрика» → 02-electrical.png (латиница — для путей и API)
SHEET_SLUGS = {
    "tab_plan": "plan",
    "tab_electrical": "electrical",
    "tab_lighting": "lighting",
    "tab_wiring": "wiring",
    "tab_panel": "panel",
    "tab_points": "points",
    "tab_elevations": "elevations",
}


def sheet_slug(tab: str) -> str | None:
    """Тема листа (plan / electrical / wiring) по имени вкладки «NN Название» на любом языке."""
    title = tab.partition(" ")[2]
    for suffix in TEXTS["sheet_continued"].values():
        title = title.removesuffix(f" {suffix}")
    return next((slug for key, slug in SHEET_SLUGS.items() if title in TEXTS[key].values()), None)


def sheet_png_name(tab: str) -> str:
    """Имя файла превью листа по имени вкладки «NN Название» на любом языке проекта."""
    return f"{tab.partition(' ')[0]}-{sheet_slug(tab) or 'sheet'}.png"


@dataclass(frozen=True)
class SheetSpec:
    tab_key: str  # имя вкладки листа — ключ texts.TEXTS
    image_key: str  # графа 4 основной надписи
    layers: tuple[LayerSpec, ...]  # видимые в видовом экране слои модели
    tables: tuple[Panel, ...] = ()  # справа от вида, по порядку
    legends: tuple[Panel, ...] = ()  # варианты ряда легенды у штампа (разное число колонок)
    # Схема вместо видового экрана (щит): по месту (ширина, высота) — панель или None,
    # если не помещается
    body: Callable[[float, float], Panel | None] | None = None
    wide: bool = False  # схема во всю ширину над штампом (секции плана и таблиц вместе)
    # Схема не влезла (печать на малом формате) — эти таблицы по страницам вместо неё
    spill: tuple[Panel, ...] = ()
    # Блоки spill всегда по страницам (развёртки стен): сколько листов — столько и будет
    paged: bool = False
    continued: bool = False  # лист-продолжение таблиц предыдущего листа


@dataclass(frozen=True)
class Placement:
    layout: SheetLayout
    view_at: Vec  # левый верхний угол видового экрана
    panels: tuple[tuple[Panel, Vec], ...]  # панель и её левый верхний угол


def visible_extents(doc: Drawing, layers: tuple[LayerSpec, ...]) -> BoundingBox:
    names = {spec.name for spec in layers}
    return bbox.extents((e for e in doc.modelspace() if e.dxf.layer in names), fast=True)


def view_size(
    doc: Drawing, spec: SheetSpec, layers: tuple[LayerSpec, ...] | None = None
) -> tuple[float, float]:
    """Ширина и высота видового экрана 1:50 под слои листа (или layers), мм листа; у схемы — 0."""
    if spec.body is not None:
        return 0.0, 0.0
    box = visible_extents(doc, layers or spec.layers)
    k = sheet_scale()
    return box.size.x / k + 2 * VIEW_MARGIN, box.size.y / k + 2 * VIEW_MARGIN


def view_parts(doc: Drawing, spec: SheetSpec) -> tuple[tuple[float, float], tuple[float, float]]:
    """Вид без подписей электрики и их вынос за него, мм листа. Подписи стоят в мм листа и
    с масштабом не растут — при выборе масштаба вынос не пересчитывается (labels.py)."""
    full = view_size(doc, spec)
    core_layers = tuple(spec_ for spec_ in spec.layers if spec_.name != E_TEXT.name)
    if spec.body is not None or len(core_layers) == len(spec.layers):
        return full, (0.0, 0.0)
    core = view_size(doc, spec, core_layers)
    return core, (max(full[0] - core[0], 0.0), max(full[1] - core[1], 0.0))


@dataclass(frozen=True)
class Grid:
    """Секции листа, (x0, y0, x1, y1) в мм листа."""

    plan: Region
    tables: Region
    legend: Region


def grid(w: float, h: float) -> Grid:
    """Секции по кресту в левом верхнем углу штампа."""
    x0, y0, x1, y1 = frame_region(w, h)
    xs, ys = x1 - STAMP_W, y0 + STAMP_H
    return Grid((x0, ys, xs, y1), (xs, ys, x1, y1), (x0, y0, xs, ys))


def _size(r: Region) -> tuple[float, float]:
    return r[2] - r[0], r[3] - r[1]


def stack_right(tables: Sequence[Panel], sec: Region) -> list[tuple[Panel, Vec]] | None:
    """Таблицы одна под другой, прижаты к правому краю секции; None — не помещаются."""
    x0, y0, x1, y1 = sec
    out: list[tuple[Panel, Vec]] = []
    y = y1 - PADDING
    for t in tables:
        if t.width > x1 - x0 - 2 * PADDING:
            return None
        out.append((t, Vec(x1 - PADDING - t.width, y)))
        y -= t.height + PANEL_GAP
    if tables and y + PANEL_GAP < y0 + PADDING:
        return None
    return out


@dataclass(frozen=True)
class Arrangement:
    """Таблицы на листе и что осталось плану."""

    tables: tuple[tuple[Panel, Vec], ...]
    plan: Region


def columns(tables: Sequence[Panel], sec: Region) -> list[list[Panel]] | None:
    """Таблицы по колонкам высотой с секцию, по порядку; None — таблица выше секции."""
    height = sec[3] - sec[1] - 2 * PADDING
    out: list[list[Panel]] = []
    used = height + 1.0  # первая таблица открывает колонку
    for t in tables:
        if t.height > height:
            return None
        if used + PANEL_GAP + t.height > height:
            out.append([])
            used = -PANEL_GAP
        out[-1].append(t)
        used += PANEL_GAP + t.height
    return out


def arrange(tables: Sequence[Panel], g: Grid) -> Arrangement | None:
    """Таблицы над штампом одной колонкой; не влезли — колонками справа налево, и лишние
    колонки забирают место у секции плана. None — таблица выше секции или плану не осталось
    места."""
    one = stack_right(tables, g.tables)
    if one is not None:
        return Arrangement(tuple(one), g.plan)
    cols = columns(tables, g.tables)
    if cols is None:
        return None
    out: list[tuple[Panel, Vec]] = []
    right = g.tables[2] - PADDING
    for col in cols:
        width = max(t.width for t in col)
        y = g.tables[3] - PADDING
        for t in col:
            out.append((t, Vec(right - t.width, y)))
            y -= t.height + PANEL_GAP
        right -= width + PANEL_GAP
    # Секция плана — до левого края таблиц, если они зашли за линию штампа
    left = right + PANEL_GAP - PADDING
    px0, py0, px1, py1 = g.plan
    if left < px1:
        px1 = left
    if px1 - px0 <= 2 * PADDING:
        return None
    return Arrangement(tuple(out), (px0, py0, px1, py1))


def fit_legend(legends: Sequence[Panel], sec: Region) -> tuple[Panel, Vec] | None:
    """Самый низкий вариант легенды, что помещается в секцию; по высоте — по центру."""
    w, h = _size(sec)
    for leg in sorted(legends, key=lambda p: p.height):
        # По горизонтали — обычный отступ, по вертикали меньше: секция высотой со штамп
        if leg.width <= w - 2 * PADDING and leg.height <= h - 2 * LEGEND_PAD:
            return leg, Vec(sec[0] + PADDING, sec[3] - (h - leg.height) / 2)
    return None


def panels_fit(spec: SheetSpec, paper: Paper) -> bool:
    if spec.paged:  # по страницам: лишь бы каждый блок влез на свою
        x0, y0, x1, y1 = plan_region(replace(spec, wide=True), paper)
        return paginate(spec.spill, x1 - x0 - 2 * PADDING, y1 - y0 - 2 * PADDING) is not None
    g = grid(paper[1], paper[2])
    legend_ok = not spec.legends or fit_legend(spec.legends, g.legend) is not None
    return legend_ok and arrange(spec.tables, g) is not None and fit_body(spec, paper) is not False


def fit_body(spec: SheetSpec, paper: Paper) -> Panel | bool:
    """Схема листа под секцию плана без отступов; схемы нет — True, не влезла — False."""
    if spec.body is None:
        return True
    x0, y0, x1, y1 = plan_region(spec, paper)
    body = spec.body(x1 - x0 - 2 * PADDING, y1 - y0 - 2 * PADDING)
    return body if body is not None else False


def plan_region(spec: SheetSpec, paper: Paper) -> Region:
    """Секция плана на этом листе: без колонок таблиц, зашедших в неё; у листа-продолжения —
    секции плана и таблиц вместе."""
    g = grid(paper[1], paper[2])
    if spec.wide:
        return g.plan[0], g.plan[1], g.tables[2], g.tables[3]
    a = arrange(spec.tables, g)
    return a.plan if a is not None else g.plan


def place(view: tuple[float, float], spec: SheetSpec, paper: Paper) -> Placement:
    """Раскладка на бумаге paper = (формат, ширина, высота). Что не поместилось, всё равно
    ставится на своё место; fits=False отмечает, что лист переполнен."""
    name, w, h = paper
    g = grid(w, h)
    arranged = arrange(spec.tables, g)
    legend = fit_legend(spec.legends, g.legend) if spec.legends else None
    plan = arranged.plan if arranged is not None else g.plan
    if spec.wide:
        plan = plan_region(spec, paper)
    fits = (
        arranged is not None
        and (not spec.legends or legend is not None)
        and fill(view, plan) <= 1.0
    )
    if arranged is None:  # переполнение: одна под другой от правого верхнего угла секции
        tables, y = [], g.tables[3] - PADDING
        for t in spec.tables:
            tables.append((t, Vec(g.tables[2] - PADDING - t.width, y)))
            y -= t.height + PANEL_GAP
    else:
        tables = list(arranged.tables)
    panels = list(tables)
    if legend is not None:
        panels.append(legend)
    elif spec.legends:
        panels.append((spec.legends[0], Vec(g.legend[0] + PADDING, g.legend[3] - LEGEND_PAD)))
    px0, py0, px1, py1 = plan
    view_at = Vec((px0 + px1 - view[0]) / 2, (py0 + py1 + view[1]) / 2)
    layout = SheetLayout(name, w, h, frame_region(w, h), fits=fits)
    return Placement(layout, view_at, tuple(panels))


def add_sheet(
    doc: Drawing, spec: SheetSpec, tab: str, stamp: StampText, paper: Paper
) -> Paperspace:
    """Лист на бумаге paper: рамка, штамп, видовой экран (или схема), таблицы и легенда."""
    if spec.body is not None:
        return _add_body_sheet(doc, spec, tab, stamp, paper)
    box = visible_extents(doc, spec.layers)
    vw, vh = view_size(doc, spec)
    p = place((vw, vh), spec, paper)
    layout = p.layout

    psp = _new_layout(doc, tab, layout)
    draw_sheet(psp, layout, stamp)
    vp = psp.add_viewport(
        center=(p.view_at.x + vw / 2, p.view_at.y - vh / 2),
        size=(vw, vh),
        view_center_point=(box.center.x, box.center.y),
        view_height=vh * sheet_scale(),
        dxfattribs={"layer": A_VPORT.name},
    )
    vp.dxf.flags = vp.dxf.flags | VIEWPORT_LOCKED
    shown = {s.name.upper() for s in spec.layers} | NEVER_FROZEN
    vp.frozen_layers = [lay.dxf.name for lay in doc.layers if lay.dxf.name.upper() not in shown]
    for panel, at in p.panels:
        panel.draw(psp, at)
    return psp


def _new_layout(doc: Drawing, tab: str, layout: SheetLayout) -> Paperspace:
    psp = doc.layouts.new(tab)
    psp.page_setup(
        size=(layout.width, layout.height),
        margins=(0, 0, 0, 0),
        units="mm",
        scale=(1, 1),
        name=layout.paper_prefix,
    )
    return psp


def _add_body_sheet(
    doc: Drawing, spec: SheetSpec, tab: str, stamp: StampText, paper: Paper
) -> Paperspace:
    """Лист со схемой вместо видового экрана: схема — по центру секции плана."""
    p = place((0.0, 0.0), spec, paper)
    body = fit_body(spec, paper)
    layout = p.layout if isinstance(body, Panel) else replace(p.layout, fits=False)
    psp = _new_layout(doc, tab, layout)
    draw_sheet(psp, layout, stamp)
    if isinstance(body, Panel):
        x0, y0, x1, y1 = plan_region(spec, paper)
        body.draw(psp, Vec((x0 + x1 - body.width) / 2, (y0 + y1 + body.height) / 2))
    for panel, at in p.panels:
        panel.draw(psp, at)
    return psp


def document_scale(doc: Drawing) -> float:
    """Масштаб, в котором нарисована модель документа (50 — это 1:50): по видовому экрану
    листа; листов нет — DEFAULT_SCALE."""
    for layout in doc.layouts:
        for vp in layout.query("VIEWPORT"):
            if vp.dxf.layer == A_VPORT.name and vp.dxf.height > 0:
                return round(float(vp.dxf.view_height) / float(vp.dxf.height), 6)
    return DEFAULT_SCALE


def schedule_panel(plan: Plan, areas: dict[str, RoomArea]) -> Panel:
    table = room_schedule(plan, areas)
    return table_panel(table)


LEGEND_MIN_ROWS = 3  # строк в колонке легенды — не меньше


def legend_columns(
    elec: Electrical, language: Language, with_groups: bool = True
) -> tuple[Panel, ...]:
    """Варианты нижнего ряда: условные обозначения и группы, разбитые на колонки по k
    строк. Чем меньше k, тем ряд шире и ниже; берётся самый низкий, что поместится.
    with_groups=False — без цветов групп (лист освещения: линии там не по группам)."""
    symbols, groups = split_legend(legend_rows(elec, language))
    if not with_groups:
        groups = []
    head = symbols[0]
    blank = replace(head, text="")  # продолжение колонки — без заголовка, строки вровень

    def panel(rows: list[LegendRow]) -> Panel:
        width, height = legend_size(rows)
        return Panel(width, height, lambda psp, top_left: draw_legend(psp, rows, top_left))

    def columns(rows: list[LegendRow], k: int) -> list[Panel]:
        title, body = rows[0], rows[1:]
        chunks = [body[i : i + k] for i in range(0, len(body), k)] or [[]]
        out = []
        for n, chunk in enumerate(chunks):
            first = title if n == 0 else replace(blank, step=0.0)
            out.append(panel([first, *chunk]))
        return out

    longest = max(len(symbols), len(groups)) - 1  # без заголовков
    variants = []
    for k in range(LEGEND_MIN_ROWS, max(longest, LEGEND_MIN_ROWS) + 1):
        cols = columns(symbols, k) + (columns(groups, k) if groups else [])
        variants.append(_row(cols))
    return tuple(variants)


def groups_panel(plan: Plan, elec: Electrical) -> Panel | None:
    """Группы щита с примечанием о составленных назначениях."""
    built = groups_table(plan, elec)
    if built is None:
        return None
    table, notes = built
    panel = table_panel(table)
    return stacked(panel, notes_panel(notes, width=table.width)) if notes else panel


def points_spec(plan: Plan, elec: Electrical) -> SheetSpec | None:
    """Лист «Точки» (решение 2026-10-28): номера на плане электрики → вид, высота,
    количество. Таблица — на месте плана, колонками, если не входит по высоте."""
    table = points_table(plan, elec)
    if table is None:
        return None

    def body(width: float, height: float) -> Panel | None:
        for k in range(1, len(table.rows) + 1):
            per = -(-len(table.rows) // k)
            parts = [
                replace(table, rows=table.rows[i : i + per], title=table.title if i == 0 else "")
                for i in range(0, len(table.rows), per)
            ]
            if max(t.height for t in parts) > height:
                continue
            panels = [Panel(t.width, t.height, _table_draw(t)) for t in parts]
            out = panels[0]
            for p in panels[1:]:
                out = beside(out, p)
            return out if out.width <= width else None
        return None

    spill = (table_panel(table),)
    return SheetSpec("tab_points", "points_image", (), (), body=body, wide=True, spill=spill)


def _table_draw(table: Table) -> Callable[[Paperspace, Vec], None]:
    return lambda psp, tl: draw_table(psp, table, tl)


def specification_panel(elec: Electrical, language: Language) -> Panel | None:
    table = specification_table(elec, language)
    if table is None:
        return None
    return table_panel(table)


def _row(panels: Sequence[Panel]) -> Panel:
    out = panels[0]
    for p in panels[1:]:
        out = beside(out, p)
    return out


def wrap(text: str, width: float, height: float) -> list[str]:
    """Строка, разбитая по словам на строки не шире width (мм листа, по метрикам шрифта)."""
    out: list[str] = []
    for word in text.split():
        if out and text_width(f"{out[-1]} {word}", height) <= width:
            out[-1] = f"{out[-1]} {word}"
        else:
            out.append(word)
    return out or [""]


def notes_panel(lines: Sequence[str], width: float | None = None) -> Panel:
    """Строки примечаний мелким шрифтом; width — переносить по словам под эту ширину."""
    if width is not None:
        lines = [part for line in lines for part in wrap(line, width, TEXT_SMALL_MM)]
    notes_w = max(text_width(t, TEXT_SMALL_MM) for t in lines)
    notes_h = len(lines) * NOTE_STEP

    def draw_notes(psp: Paperspace, top_left: Vec) -> None:
        for k, text in enumerate(lines):
            at = Vec(top_left.x, top_left.y - (k + 0.5) * NOTE_STEP)
            add_text(psp, text, at, TEXT_SMALL_MM, A_TEXT.name, align=MIDDLE_LEFT, scale=1.0)

    return Panel(notes_w, notes_h, draw_notes)


def wiring_panels(
    wiring: Wiring,
    elec: Electrical,
    language: Language,
    prices: PriceList | None = None,
    quantities: Wiring | None = None,
) -> tuple[Panel, Panel]:
    """Таблица кабелей по группам и примечания, под ними — смета электрики (с прайсом) или
    ведомость объёмов (без прайса): смета этапа стоит на его листе. Кабель по маркам
    с запасом — первые строки сметы, отдельной таблицы марок здесь нет. quantities — проводка
    для объёмов сметы (wiring.estimate_wiring); None — та же, что на листе."""
    table = wiring_table(wiring, language, group_colors(elec))
    cables = stacked(
        table_panel(table),
        notes_panel(wiring_notes(wiring, language), width=table.width),
    )
    est = build_estimate(quantities or wiring, elec, prices or PriceList(), language)
    sheet = estimate_table(est, language, priced=prices is not None)
    estimate = table_panel(sheet)
    if prices is not None:
        date = f" ({prices.date})" if prices.date else ""
        lines = [estimate_text("sheet_prices", language, f=PRICES_FILE, date=date)]
        if est.unpriced:
            lines.append(estimate_text("unpriced", language, n=est.unpriced, f=PRICES_FILE))
        estimate = stacked(estimate, notes_panel(lines, width=sheet.width))
    return cables, estimate


def beside(left: Panel, right: Panel) -> Panel:
    """Две панели рядом, по верхнему краю."""

    def draw(psp: Paperspace, top_left: Vec) -> None:
        left.draw(psp, top_left)
        right.draw(psp, Vec(top_left.x + left.width + PANEL_GAP, top_left.y))

    return Panel(left.width + PANEL_GAP + right.width, max(left.height, right.height), draw)


def stacked(top: Panel, bottom: Panel) -> Panel:
    """Две панели одна под другой."""

    def draw(psp: Paperspace, top_left: Vec) -> None:
        top.draw(psp, top_left)
        bottom.draw(psp, Vec(top_left.x, top_left.y - top.height - PANEL_GAP))

    def split(first: float, rest: float) -> list[Panel] | None:
        # Делится верхний блок; нижний (примечания) — под последней частью или отдельно
        parts = top.split(first, rest) if top.split is not None else None
        if parts is None or bottom.height > rest:
            return None
        room = first if len(parts) == 1 else rest
        if parts[-1].height + PANEL_GAP + bottom.height <= room:
            return [*parts[:-1], stacked(parts[-1], bottom)]
        return [*parts, bottom]

    width = max(top.width, bottom.width)
    return Panel(width, top.height + PANEL_GAP + bottom.height, draw, split)


def _draw(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical | None,
    prices: PriceList | None = None,
    edits: WiringEdits | None = None,
) -> tuple[Drawing, list[SheetSpec]]:
    """Модель всех этапов в текущем масштабе и описания листов (без самих листов)."""
    doc = new_document((*ALL_LAYERS, A_VPORT))
    define_blocks(doc)
    msp = doc.modelspace()
    areas = draw_plan(msp, plan, contours)
    specs = [SheetSpec("tab_plan", "plan_image", PLAN_SHEET_LAYERS, (schedule_panel(plan, areas),))]
    if elec is not None:
        draw_electrical(msp, plan, contours, elec)
        specs.append(
            SheetSpec(
                "tab_electrical",
                "electrical_image",
                ELECTRICAL_SHEET_LAYERS,
                tables=tuple(
                    p
                    for p in [groups_panel(plan, elec), specification_panel(elec, plan.language)]
                    if p
                ),
                legends=legend_columns(elec, plan.language),
            )
        )
        lighting = lighting_spec(msp, plan, contours, elec)
        if lighting is not None:
            specs.append(lighting)
        wiring = box_wiring(plan, contours, elec, edits)
        if wiring is not None:
            draw_wiring(msp, wiring, elec)
            specs.append(
                SheetSpec(
                    "tab_wiring",
                    "wiring_image",
                    WIRING_SHEET_LAYERS,
                    wiring_panels(
                        wiring,
                        elec,
                        plan.language,
                        prices,
                        estimate_wiring(plan, contours, elec, edits),
                    ),
                )
            )
        board = panel_spec(plan, elec)
        if board is not None:
            specs.append(board)
        # Ведомость точек — приложением в конце: номера листов этапов не меняются
        points = points_spec(plan, elec)
        if points is not None:
            specs.append(points)
        # Развёртки стен — тоже в конце, сколько листов понадобится
        elevations = elevations_spec(plan, contours, elec, wiring)
        if elevations is not None:
            specs.append(elevations)
    return doc, specs


def lighting_spec(
    msp: Modelspace, plan: Plan, contours: dict[str, Contour], elec: Electrical
) -> SheetSpec | None:
    """Лист «Освещение» — сразу за электрикой: связи выключателей и таблица «Выключатели»,
    легенда — только света. Света нет — листа нет."""
    if not any(p.type in LIGHT_TYPES for p in elec.points):
        return None
    draw_lighting(msp, plan, contours, elec)
    lang = plan.language
    tables: list[Panel] = []
    built = switch_table(plan, elec)
    if built is not None:
        table, notes = built
        panel = table_panel(table)
        tables.append(stacked(panel, notes_panel(notes, width=table.width)) if notes else panel)
    light = elec.model_copy(
        update={"points": [p for p in elec.points if is_lighting(p)], "board": None}
    )
    return SheetSpec(
        "tab_lighting",
        "lighting_image",
        LIGHTING_SHEET_LAYERS,
        tables=tuple(tables),
        legends=legend_columns(light, lang, with_groups=False),
    )


def elevations_spec(
    plan: Plan, contours: dict[str, Contour], elec: Electrical, wiring: Wiring | None
) -> SheetSpec | None:
    """Листы «Развёртки»: стена за стеной в масштабе комплекта, по страницам; первым —
    как читать размеры. Стен с электрикой нет — листов нет."""
    walls = wall_elevations(plan, contours, elec, wiring)
    if not walls:
        return None
    lang = plan.language
    blocks = [elevation_panel(e, sheet_scale(), lang) for e in walls]
    notes = notes_panel([tr("elev_notes", lang)], width=ELEV_NOTES_W)
    panels = (notes, *(Panel(b.width, b.height, b.draw) for b in blocks))
    nothing: Callable[[float, float], Panel | None] = lambda w, h: None  # noqa: E731
    return SheetSpec(
        "tab_elevations", "elevations_image", (), body=nothing, wide=True, spill=panels, paged=True
    )


def panel_spec(plan: Plan, elec: Electrical) -> SheetSpec | None:
    """Лист «Щит»: щит в лицо по центру секции плана, справа — аппараты с нагрузкой
    и слабые места. Групп нет — листа нет."""
    panel = build_panel(plan, elec)
    if panel is None:
        return None
    lang = plan.language
    colors = group_colors(elec)
    name = elec.board.name if elec.board is not None else "ЩР"

    def body(width: float, height: float) -> Panel | None:
        fit = fit_panel(panel, width, height)
        if fit is None:
            return None
        return Panel(
            fit.width,
            fit.height,
            lambda psp, tl: draw_panel_front(psp, panel, fit, tl, colors, name, lang),
        )

    table = devices_table(panel, lang, colors)
    tables = stacked(
        table_panel(table),
        notes_panel(panel_notes(panel, lang), width=table.width),
    )
    return SheetSpec("tab_panel", "panel_image", (), (tables,), body=body)


def paginate(tables: Sequence[Panel], width: float, height: float) -> list[Panel] | None:
    """Таблицы по страницам width × height: колонками слева направо, колонка не шире
    страницы; таблица, что не входит в остаток колонки, делится по строкам (Panel.split) и
    продолжается в следующей колонке или на следующей странице. None — таблица не входит
    даже частями."""
    pages: list[list[list[Panel]]] = [[[]]]
    used = -PANEL_GAP  # высота занятой части колонки

    def page_width(cols: list[list[Panel]]) -> float:
        return sum(max(p.width for p in c) for c in cols if c) + PANEL_GAP * (len(cols) - 1)

    def put(part: Panel) -> bool:
        nonlocal used
        if part.width > width or part.height > height:
            return False
        cols = pages[-1]
        if cols[-1] and used + PANEL_GAP + part.height > height:
            cols.append([])
            used = -PANEL_GAP
        cols[-1].append(part)
        if page_width(cols) > width:  # колонка не входит — на новую страницу
            cols[-1].pop()
            if not cols[-1]:
                cols.pop()
            pages.append([[part]])
        used = part.height if len(pages[-1][-1]) == 1 else used + PANEL_GAP + part.height
        return True

    for t in tables:
        left = height - used - PANEL_GAP
        if t.height <= left or (t.split is None and t.height <= height):
            parts = [t]
        else:
            split = t.split(left, height) if t.split is not None else None
            if split is None:
                return None
            parts = split
        if not all(put(part) for part in parts):
            return None
    return [_row([_column(c) for c in cols if c]) for cols in pages if any(cols)]


def _column(panels: Sequence[Panel]) -> Panel:
    out = panels[0]
    for p in panels[1:]:
        out = stacked(out, p)
    return out


def fit_specs(specs: Sequence[SheetSpec], paper: Paper) -> list[SheetSpec]:
    """Листы на бумаге paper: у листа, таблицы которого не помещаются, остаются первые, что
    влезли, остальные — на лист-продолжение сразу за ним; не влезла легенда — она тоже
    (самым узким вариантом, первой)."""
    out: list[SheetSpec] = []
    for spec in specs:
        if spec.paged:  # развёртки: первая страница — сам лист, дальше — продолжения
            first, *rest = _continued(spec, spec.spill, paper)
            out += [replace(first, continued=False), *rest]
            continue
        if panels_fit(spec, paper):
            out.append(spec)
            continue
        if spec.body is not None:
            # Схема (щит) — во всю ширину, её таблицы — на продолжение
            wide = replace(spec, tables=(), wide=True)
            if spec.tables and panels_fit(wide, paper):
                out += [wide, *_continued(spec, spec.tables, paper)]
            elif spec.spill:  # схема-таблица (точки) — по страницам
                first, *rest = _continued(spec, spec.spill, paper)
                out += [replace(first, continued=False), *rest]
            else:
                out.append(spec)  # не влезает и так — проверка печати скажет
            continue
        moved: list[Panel] = []
        main = spec
        if spec.legends and fit_legend(spec.legends, grid(paper[1], paper[2]).legend) is None:
            moved.append(min(spec.legends, key=lambda p: p.width))
            main = replace(spec, legends=())
        # Остаются таблицы, что встают одной колонкой над штампом: план не уступает им место
        sec = grid(paper[1], paper[2]).tables
        k = next(
            k
            for k in range(len(main.tables), -1, -1)
            if stack_right(main.tables[:k], sec) is not None
        )
        moved += main.tables[k:]
        # Таблиц на листе не осталось — плану вся ширина над штампом
        main = replace(main, tables=main.tables[:k], wide=k == 0)
        out += [main, *_continued(spec, moved, paper)]
    return out


def _continued(spec: SheetSpec, tables: Sequence[Panel], paper: Paper) -> list[SheetSpec]:
    """Листы-продолжения таблиц листа spec во всю ширину над штампом, по страницам. Не
    входят даже частями — один лист с исходной схемой: его проверит печать (пустой лист)."""
    x0, y0, x1, y1 = plan_region(replace(spec, wide=True), paper)
    pages = paginate(tables, x1 - x0 - 2 * PADDING, y1 - y0 - 2 * PADDING)

    def sheet(page: Panel | None) -> SheetSpec:
        body = (lambda w, h: page) if page is not None else (lambda w, h: None)
        return SheetSpec(
            spec.tab_key,
            spec.image_key,
            (),
            body=body,
            wide=True,
            continued=True,
            paged=spec.paged,
        )

    return [sheet(p) for p in pages] if pages else [sheet(None)]


def _at(view: tuple[float, float], scale: float) -> tuple[float, float]:
    """Размер вида в масштабе 1:scale по черновику 1:50 — с запасом: подписи и размерные
    линии в крупном масштабе занимают в модели меньше, чем в черновике."""
    k = DEFAULT_SCALE / scale
    return (
        (view[0] - 2 * VIEW_MARGIN) * k + 2 * VIEW_MARGIN,
        (view[1] - 2 * VIEW_MARGIN) * k + 2 * VIEW_MARGIN,
    )


def fill(view: tuple[float, float], sec: Region) -> float:
    """Какую долю секции занимает вид — по более тесной стороне. На A4 штамп во всю
    ширину и секции плана нет — бесконечность."""
    w, h = _size(sec)
    if w <= 0 or h <= 0:
        return math.inf
    return max(view[0] / w, view[1] / h)


def choose_paper_and_scale(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical | None,
    prices: PriceList | None = None,
    edits: WiringEdits | None = None,
) -> tuple[Paper, float]:
    """Бумага комплекта — наименьшая, на которой у всех листов помещаются таблицы и легенда,
    а план в 1:50 или крупнее занимает не больше VIEW_FILL_MAX своей секции (формат из
    room.yaml — только он). Масштаб — тот, при котором самый тесный план ближе всего
    к VIEW_FILL, не больше VIEW_FILL_MAX."""
    with drawing_scale(DEFAULT_SCALE):
        draft, all_specs = _draw(plan, contours, elec, prices, edits)
        views = {s.tab_key: view_parts(draft, s) for s in all_specs if s.body is None}
    papers = format_candidates(plan.sheet.format)
    specs = all_specs

    def worst(paper: Paper, scale: float) -> float:
        # Схема (щит) масштаба не имеет: её место проверяет panels_fit
        def at(core: tuple[float, float], extra: tuple[float, float]) -> tuple[float, float]:
            w, h = _at(core, scale)
            return w + extra[0], h + extra[1]

        return max(
            fill(at(*views[s.tab_key]), plan_region(s, paper)) for s in specs if s.body is None
        )

    def ok(paper: Paper, scale: float) -> bool:
        panels = all(panels_fit(s, paper) for s in specs)
        return panels and worst(paper, scale) <= VIEW_FILL_MAX

    base = [s for s in SCALES if s <= DEFAULT_SCALE]
    found = next((p for p in papers if any(ok(p, s) for s in base)), None)
    if found is None:
        # Ни на один формат таблицы не входят — самый крупный, таблицы на продолжение
        # Масштаб — по виду: схемам (щит, таблицы) он не поможет, их проверит печать
        paper = max(papers, key=lambda p: (p[1] * p[2], p[1]))
        specs = fit_specs(all_specs, paper)
        fitting = [s for s in SCALES if worst(paper, s) <= VIEW_FILL_MAX]
        # Оценка по черновику 1:50 занижает полосу размеров в мелком масштабе — выбранный
        # масштаб проверяется отрисовкой, не влез — следующий мельче
        best = min(fitting, key=lambda s: abs(worst(paper, s) - VIEW_FILL), default=SCALES[-1])
        for scale in [s for s in SCALES if s >= best]:
            with drawing_scale(scale):
                real, real_specs = _draw(plan, contours, elec, prices, edits)
                shown = [s for s in fit_specs(real_specs, paper) if s.body is None]
                if all(fill(view_size(real, s), plan_region(s, paper)) <= 1.0 for s in shown):
                    return paper, scale
        return paper, SCALES[-1]
    else:
        paper = found
        fitting = [s for s in SCALES if ok(paper, s)]
    if not fitting:
        return paper, SCALES[-1]
    return paper, min(fitting, key=lambda s: abs(worst(paper, s) - VIEW_FILL))


def build_project_document(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical | None = None,
    today: date | None = None,
    prices: PriceList | None = None,
    edits: WiringEdits | None = None,
) -> Drawing:
    """Один DXF: модель со всеми этапами и лист на каждый этап; формат и масштаб — общие.
    prices — прайс проекта для сметы на листе проводки; None — ведомость объёмов без цен.
    edits — ручные правки проводки (wiring.yaml)."""
    paper, scale = choose_paper_and_scale(plan, contours, elec, prices, edits)
    with drawing_scale(scale):
        doc, specs = _draw(plan, contours, elec, prices, edits)
        specs = fit_specs(specs, paper)
        main_no = 1  # лист, чьи таблицы продолжаются
        for no, spec in enumerate(specs, 1):
            main_no = main_no if spec.continued else no
            tab = f"{no:02d} {tr(spec.tab_key, plan.language)}"
            stamp = plan_stamp(plan, spec.image_key, no, len(specs), today)
            if spec.continued:
                tab += f" {tr('sheet_continued', plan.language)}"
                if spec.paged:  # продолжение развёрток — то же название
                    image = f"{stamp.image} {tr('sheet_continued', plan.language)}"
                else:
                    image = tr("sheet_tables", plan.language, no=main_no)
                stamp = replace(stamp, image=image)
            add_sheet(doc, spec, tab, stamp, paper)
    # Пустой лист по умолчанию из ezdxf не нужен
    doc.layouts.delete("Layout1")
    finalize_fields(doc)
    return doc
