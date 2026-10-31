"""Раскладка листа: секции (план | таблицы / легенда | штамп), панели таблиц и легенды,
колонки справа налево, подбор под формат, листы-продолжения для таблиц, что не влезли.

Раскладка одна для всех листов — четыре секции, крест которых проходит через левый верхний
угол штампа:

    план    | таблицы
    легенда | штамп

План — по центру своей секции и занимает около VIEW_FILL её; таблицы — прижаты к правому
краю своей секции, одна под другой; не влезли — колонками справа налево, и колонки за линией
штампа забирают место у секции плана (arrange); легенда — в секции слева от штампа.
Таблицы, что не входят ни на один формат (печать на заданном формате, `print --paper A3`),
уходят на лист-продолжение во всю ширину над штампом; таблица выше листа делится по строкам
на колонки (`fit_specs`).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from ezdxf import bbox
from ezdxf.document import Drawing
from ezdxf.layouts.layout import Paperspace
from ezdxf.math import BoundingBox

from floorplan_engine.drawing.layers import (
    E_TEXT,
    LayerSpec,
)
from floorplan_engine.drawing.tables import Table, draw_table
from floorplan_engine.drawing.titleblock import (
    PADDING,
    STAMP_H,
    STAMP_W,
    Region,
    SheetLayout,
    frame_region,
)
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.scale import sheet_scale

VIEW_MARGIN = 3.0  # поле вокруг чертежа внутри видового экрана, мм листа
PANEL_GAP = 10.0  # между таблицами и колонками легенды, мм листа
MIN_LEAD_ROWS = 5  # меньше строк в остатке колонки — таблица начинается в следующей
LEGEND_PAD = 5.0  # отступ легенды сверху и снизу: секция низкая, по высоте штампа


# Бумага: (формат, ширина, высота) в мм — с ориентацией
Paper = tuple[str, float, float]


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


def in_row(panels: Sequence[Panel]) -> Panel:
    out = panels[0]
    for p in panels[1:]:
        out = beside(out, p)
    return out


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
    return [in_row([_column(c) for c in cols if c]) for cols in pages if any(cols)]


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


def fill(view: tuple[float, float], sec: Region) -> float:
    """Какую долю секции занимает вид — по более тесной стороне. На A4 штамп во всю
    ширину и секции плана нет — бесконечность."""
    w, h = _size(sec)
    if w <= 0 or h <= 0:
        return math.inf
    return max(view[0] / w, view[1] / h)
