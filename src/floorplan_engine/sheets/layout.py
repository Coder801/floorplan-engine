"""Sheet layout: sections (plan | tables / legend | title block), table and legend panels,
columns from right to left, fitting to paper, continuation sheets for tables that did not fit.

One layout for all sheets: four sections whose cross goes through the top-left corner of the
title block:

    plan   | tables
    legend | title block

The plan is centred in its section and takes about VIEW_FILL of it; tables are pressed to
the right edge of their section, one under another; if they do not fit, they go in columns
from right to left, and columns past the title block line take space from the plan section
(arrange); the legend sits in the section left of the title block.
Tables that fit no paper size (printing at a given size, `print --paper A3`) go to a
continuation sheet across the full width above the title block; a table taller than the
sheet is split by rows into columns (`fit_specs`).
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

VIEW_MARGIN = 3.0  # margin around the drawing inside the viewport, sheet mm
PANEL_GAP = 10.0  # between tables and legend columns, sheet mm
MIN_LEAD_ROWS = 5  # fewer rows left in a column than this: the table starts in the next one
LEGEND_PAD = 5.0  # legend top and bottom margin: the section is low, as tall as the title block


# Paper: (size, width, height) in mm, orientation applied
Paper = tuple[str, float, float]


@dataclass(frozen=True)
class Panel:
    """Block on the sheet (table, legend); draw draws it from the top-left corner, sheet mm."""

    width: float
    height: float
    draw: Callable[[Paperspace, Vec], None]
    # Parts: the first no taller than first (rest of a column), the others no taller than rest
    # (a table splits by rows); None means the block does not split
    split: Callable[[float, float], list[Panel] | None] | None = None


def table_panel(table: Table) -> Panel:
    """Table as a sheet block; taller than the space, it splits by rows (split_table)."""

    def split(first: float, rest: float) -> list[Panel] | None:
        parts = split_table(table, first, rest)
        return None if parts is None else [table_panel(t) for t in parts]

    return Panel(table.width, table.height, lambda psp, tl: draw_table(psp, table, tl), split)


def split_table(table: Table, first: float, rest: float) -> list[Table] | None:
    """Table in parts: the first no taller than first, the others no taller than rest; the column
    header is in each, the title in the first, the total in the last. If first cannot hold
    MIN_LEAD_ROWS rows, no stub is placed and the table starts in rest; None if rest cannot
    hold two."""
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
    tab_key: str  # sheet tab name: a texts.TEXTS key
    image_key: str  # title block box 4
    layers: tuple[LayerSpec, ...]  # model layers visible in the viewport
    tables: tuple[Panel, ...] = ()  # right of the view, in order
    legends: tuple[Panel, ...] = ()  # legend row variants by the title block
    # Diagram instead of a viewport (panel): for the space (width, height) a panel, or None
    # if it does not fit
    body: Callable[[float, float], Panel | None] | None = None
    wide: bool = False  # diagram full width above the title block
    # The diagram did not fit (printing on small paper): these tables go page by page instead
    spill: tuple[Panel, ...] = ()
    # spill blocks always go page by page (wall elevations): as many sheets as it takes
    paged: bool = False
    continued: bool = False  # continuation sheet for the previous sheet's tables


@dataclass(frozen=True)
class Placement:
    layout: SheetLayout
    view_at: Vec  # top-left corner of the viewport
    panels: tuple[tuple[Panel, Vec], ...]  # panel and its top-left corner


def visible_extents(doc: Drawing, layers: tuple[LayerSpec, ...]) -> BoundingBox:
    names = {spec.name for spec in layers}
    return bbox.extents((e for e in doc.modelspace() if e.dxf.layer in names), fast=True)


def view_size(
    doc: Drawing, spec: SheetSpec, layers: tuple[LayerSpec, ...] | None = None
) -> tuple[float, float]:
    """Width and height of the 1:50 viewport for the sheet layers (or layers), sheet mm; 0 for a
    diagram.
    """
    if spec.body is not None:
        return 0.0, 0.0
    box = visible_extents(doc, layers or spec.layers)
    k = sheet_scale()
    return box.size.x / k + 2 * VIEW_MARGIN, box.size.y / k + 2 * VIEW_MARGIN


def view_parts(doc: Drawing, spec: SheetSpec) -> tuple[tuple[float, float], tuple[float, float]]:
    """View without electrical labels and how far they stick out, sheet mm. Labels are set in sheet
    mm and do not grow with the scale, so the overhang is not recomputed when the scale is chosen
    (labels.py)."""
    full = view_size(doc, spec)
    core_layers = tuple(spec_ for spec_ in spec.layers if spec_.name != E_TEXT.name)
    if spec.body is not None or len(core_layers) == len(spec.layers):
        return full, (0.0, 0.0)
    core = view_size(doc, spec, core_layers)
    return core, (max(full[0] - core[0], 0.0), max(full[1] - core[1], 0.0))


@dataclass(frozen=True)
class Grid:
    """Sheet sections, (x0, y0, x1, y1) in sheet mm."""

    plan: Region
    tables: Region
    legend: Region


def grid(w: float, h: float) -> Grid:
    """Sections by the cross at the top-left corner of the title block."""
    x0, y0, x1, y1 = frame_region(w, h)
    xs, ys = x1 - STAMP_W, y0 + STAMP_H
    return Grid((x0, ys, xs, y1), (xs, ys, x1, y1), (x0, y0, xs, ys))


def _size(r: Region) -> tuple[float, float]:
    return r[2] - r[0], r[3] - r[1]


def stack_right(tables: Sequence[Panel], sec: Region) -> list[tuple[Panel, Vec]] | None:
    """Tables one under another, pressed to the right edge of the section; None if they do not
    fit.
    """
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
    """Tables on the sheet and what is left for the plan."""

    tables: tuple[tuple[Panel, Vec], ...]
    plan: Region


def columns(tables: Sequence[Panel], sec: Region) -> list[list[Panel]] | None:
    """Tables in columns as tall as the section, in order; None if a table is taller than the
    section.
    """
    height = sec[3] - sec[1] - 2 * PADDING
    out: list[list[Panel]] = []
    used = height + 1.0  # the first table opens a column
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
    """Tables above the title block in one column; if they do not fit, in columns from right to
    left, and the extra columns take space from the plan section. None if a table is taller than
    the section or there is no room left for the plan."""
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
    # The plan section ends at the left edge of the tables if they went past the title block line
    left = right + PANEL_GAP - PADDING
    px0, py0, px1, py1 = g.plan
    if left < px1:
        px1 = left
    if px1 - px0 <= 2 * PADDING:
        return None
    return Arrangement(tuple(out), (px0, py0, px1, py1))


def fit_legend(legends: Sequence[Panel], sec: Region) -> tuple[Panel, Vec] | None:
    """The lowest legend variant that fits the section; vertically centred."""
    w, h = _size(sec)
    for leg in sorted(legends, key=lambda p: p.height):
        # Normal margin horizontally, less vertically: the section is as tall as the title block
        if leg.width <= w - 2 * PADDING and leg.height <= h - 2 * LEGEND_PAD:
            return leg, Vec(sec[0] + PADDING, sec[3] - (h - leg.height) / 2)
    return None


def panels_fit(spec: SheetSpec, paper: Paper) -> bool:
    if spec.paged:  # page by page: each block only needs to fit its own page
        x0, y0, x1, y1 = plan_region(replace(spec, wide=True), paper)
        return paginate(spec.spill, x1 - x0 - 2 * PADDING, y1 - y0 - 2 * PADDING) is not None
    g = grid(paper[1], paper[2])
    legend_ok = not spec.legends or fit_legend(spec.legends, g.legend) is not None
    return legend_ok and arrange(spec.tables, g) is not None and fit_body(spec, paper) is not False


def fit_body(spec: SheetSpec, paper: Paper) -> Panel | bool:
    """Sheet diagram for the plan section without margins; True if there is no diagram, False if
    it does not fit.
    """
    if spec.body is None:
        return True
    x0, y0, x1, y1 = plan_region(spec, paper)
    body = spec.body(x1 - x0 - 2 * PADDING, y1 - y0 - 2 * PADDING)
    return body if body is not None else False


def plan_region(spec: SheetSpec, paper: Paper) -> Region:
    """Plan section on this sheet: without the table columns that went into it; a continuation
    sheet gets the plan and table sections together."""
    g = grid(paper[1], paper[2])
    if spec.wide:
        return g.plan[0], g.plan[1], g.tables[2], g.tables[3]
    a = arrange(spec.tables, g)
    return a.plan if a is not None else g.plan


def place(view: tuple[float, float], spec: SheetSpec, paper: Paper) -> Placement:
    """Layout on paper = (size, width, height). What does not fit is still placed in its spot;
    fits=False marks the sheet as overflowing."""
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
    if arranged is None:  # overflow: one under another from the top-right corner of the section
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
    """Two panels side by side, aligned at the top."""

    def draw(psp: Paperspace, top_left: Vec) -> None:
        left.draw(psp, top_left)
        right.draw(psp, Vec(top_left.x + left.width + PANEL_GAP, top_left.y))

    return Panel(left.width + PANEL_GAP + right.width, max(left.height, right.height), draw)


def stacked(top: Panel, bottom: Panel) -> Panel:
    """Two panels one under another."""

    def draw(psp: Paperspace, top_left: Vec) -> None:
        top.draw(psp, top_left)
        bottom.draw(psp, Vec(top_left.x, top_left.y - top.height - PANEL_GAP))

    def split(first: float, rest: float) -> list[Panel] | None:
        # The top block splits; the bottom one (notes) goes under the last part or on its own
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
    """Tables on width × height pages: in columns from left to right, a column no wider than the
    page; a table that does not fit the rest of a column is split by rows (Panel.split) and
    continues in the next column or on the next page. None if a table does not fit even in parts."""
    pages: list[list[list[Panel]]] = [[[]]]
    used = -PANEL_GAP  # height of the used part of the column

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
        if page_width(cols) > width:  # the column does not fit: new page
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
    """Sheets on paper: a sheet whose tables do not fit keeps the first ones that fit, the rest go
    to a continuation sheet right after it; a legend that does not fit goes there too (in its
    narrowest variant, first)."""
    out: list[SheetSpec] = []
    for spec in specs:
        if spec.paged:  # elevations: the first page is the sheet itself, the rest are continuations
            first, *rest = _continued(spec, spec.spill, paper)
            out += [replace(first, continued=False), *rest]
            continue
        if panels_fit(spec, paper):
            out.append(spec)
            continue
        if spec.body is not None:
            # Diagram (panel) across the full width, its tables go to a continuation
            wide = replace(spec, tables=(), wide=True)
            if spec.tables and panels_fit(wide, paper):
                out += [wide, *_continued(spec, spec.tables, paper)]
            elif spec.spill:  # a table diagram (points) goes page by page
                first, *rest = _continued(spec, spec.spill, paper)
                out += [replace(first, continued=False), *rest]
            else:
                out.append(spec)  # does not fit even so: the print check will report it
            continue
        moved: list[Panel] = []
        main = spec
        if spec.legends and fit_legend(spec.legends, grid(paper[1], paper[2]).legend) is None:
            moved.append(min(spec.legends, key=lambda p: p.width))
            main = replace(spec, legends=())
        # Tables that fit in one column above the title block stay: the plan does not give way to
        # them
        sec = grid(paper[1], paper[2]).tables
        k = next(
            k
            for k in range(len(main.tables), -1, -1)
            if stack_right(main.tables[:k], sec) is not None
        )
        moved += main.tables[k:]
        # No tables left on the sheet: the plan gets the full width above the title block
        main = replace(main, tables=main.tables[:k], wide=k == 0)
        out += [main, *_continued(spec, moved, paper)]
    return out


def _continued(spec: SheetSpec, tables: Sequence[Panel], paper: Paper) -> list[SheetSpec]:
    """Continuation sheets for the tables of sheet spec, full width above the title block, page by
    page. If they do not fit even in parts, one sheet with the original diagram: the print check
    will catch it (an empty sheet)."""
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
    """Share of the section the view takes, by the tighter side. On A4 the title block spans the
    full width and there is no plan section: infinity."""
    w, h = _size(sec)
    if w <= 0 or h <= 0:
        return math.inf
    return max(view[0] / w, view[1] / h)
