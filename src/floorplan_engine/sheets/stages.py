"""Stages on sheets: the model of all stages at the current scale (draw_stages) and what goes
on each stage's sheet: schedules, legend, notes, wall elevations, panel front view.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

from ezdxf.document import Drawing
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.layout import Modelspace, Paperspace

from floorplan_engine.drawing.electrical import (
    LegendRow,
    draw_electrical,
    draw_legend,
    legend_rows,
    legend_size,
)
from floorplan_engine.drawing.elevations import elevation_panel
from floorplan_engine.drawing.layers import (
    A_DIMS,
    A_DOOR,
    A_TEXT,
    A_VPORT,
    A_WALL,
    A_WIND,
    ALL_LAYERS,
    E_BOARD,
    E_DATA,
    E_LED,
    E_LIGHT,
    E_SOCKET,
    E_SWITCH,
    ELECTRICAL_LAYERS,
    LIGHTING_LAYERS,
    PLUMBING_LAYERS,
    TEXT_SMALL_MM,
    WIRING_LAYERS,
    new_document,
    text_width,
)
from floorplan_engine.drawing.lighting import draw_lighting, lighting_model, switch_table
from floorplan_engine.drawing.panel import devices_table, draw_panel_front, fit_panel, panel_notes
from floorplan_engine.drawing.plan import RoomArea, add_text, draw_plan
from floorplan_engine.drawing.plumbing import (
    draw_plumbing,
    fixtures_table,
    legend_variants,
    pipes_table,
)
from floorplan_engine.drawing.schedules import (
    estimate_table,
    groups_table,
    points_table,
)
from floorplan_engine.drawing.symbols import define_blocks
from floorplan_engine.drawing.tables import Table, draw_table, room_schedule
from floorplan_engine.drawing.wiring import draw_wiring, wiring_notes
from floorplan_engine.electrical.elevations import WaterMap, wall_elevations
from floorplan_engine.electrical.estimate import build_estimate
from floorplan_engine.electrical.groups import group_colors
from floorplan_engine.electrical.panel import BoardPanel, build_panel
from floorplan_engine.electrical.pricing import Prices, price_notes
from floorplan_engine.electrical.wiring import box_wiring, estimate_wiring
from floorplan_engine.electrical.wiring_model import Wiring
from floorplan_engine.model.geometry import Contour, Vec
from floorplan_engine.model.plumbing import Plumbing
from floorplan_engine.model.scale import sheet_scale
from floorplan_engine.model.schema import LIGHT_TYPES, Electrical, Plan, WiringEdits
from floorplan_engine.model.texts import Language, tr
from floorplan_engine.plumbing.estimate import build_estimate as plumbing_estimate
from floorplan_engine.plumbing.estimate import text as plumbing_estimate_text
from floorplan_engine.plumbing.network_model import Network
from floorplan_engine.plumbing.rows import plumbing_notes, water_views
from floorplan_engine.sheets.layout import (
    Panel,
    SheetSpec,
    beside,
    in_row,
    stacked,
    table_panel,
)

ELEV_NOTES_W = 160.0  # width of the elevations explanation, sheet mm
# What each sheet's viewport shows
PLAN_SHEET_LAYERS = (A_WALL, A_DOOR, A_WIND, A_DIMS, A_TEXT)
ELECTRICAL_SHEET_LAYERS = (A_WALL, A_DOOR, A_WIND, *ELECTRICAL_LAYERS)
# Lighting: walls, lights and switches, links and their numbers; no sockets, panel or groups
LIGHTING_SHEET_LAYERS = (A_WALL, A_DOOR, A_WIND, E_SWITCH, E_LIGHT, E_LED, *LIGHTING_LAYERS)
# Wiring: walls, point symbols and panel, boxes and cables; no routes or electrical sheet labels
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
# Plumbing: walls, openings, pipes, fixtures, risers, obstacles; no electrical
PLUMBING_SHEET_LAYERS = (A_WALL, A_DOOR, A_WIND, *PLUMBING_LAYERS)
NOTE_STEP = TEXT_SMALL_MM * 1.8
MIDDLE_LEFT = TextEntityAlignment.MIDDLE_LEFT


def schedule_panel(plan: Plan, areas: dict[str, RoomArea]) -> Panel:
    table = room_schedule(plan, areas)
    return table_panel(table)


LEGEND_MIN_ROWS = 3  # rows per legend column, at least


def legend_columns(elec: Electrical, language: Language) -> tuple[Panel, ...]:
    """Bottom row variants: the legend split into columns of k rows. The smaller k, the wider and
    lower the row; the lowest one that fits is used. Only the icon and what it means: counts are
    in "Points", group colours in "Groups"."""
    title, body = (rows := legend_rows(elec, language))[0], rows[1:]
    blank = replace(title, text="", step=0.0)  # continuation: no heading, rows level

    def panel(rows: list[LegendRow]) -> Panel:
        width, height = legend_size(rows)
        return Panel(width, height, lambda psp, top_left: draw_legend(psp, rows, top_left))

    def columns(k: int) -> list[Panel]:
        chunks = [body[i : i + k] for i in range(0, len(body), k)] or [[]]
        return [panel([title if n == 0 else blank, *chunk]) for n, chunk in enumerate(chunks)]

    return tuple(
        in_row(columns(k)) for k in range(LEGEND_MIN_ROWS, max(len(body), LEGEND_MIN_ROWS) + 1)
    )


def groups_panel(
    plan: Plan,
    elec: Electrical,
    wiring: Wiring,
    board: BoardPanel | None,
    extra: Sequence[str] = (),
) -> Panel | None:
    """The "Groups" (breaker and power from the "Panel" sheet, cable and length from wiring) with
    notes: about built purposes and assumptions, then extra (wiring calculation)."""
    built = groups_table(plan, elec, wiring, board)
    if built is None:
        return None
    table, notes = built
    lines = [*notes, *extra]
    panel = table_panel(table)
    return stacked(panel, notes_panel(lines, width=table.width)) if lines else panel


def points_spec(plan: Plan, elec: Electrical) -> SheetSpec | None:
    """The "Points" sheet (decision 2026-10-28): numbers on the electrical plan → kind, height,
    count. The table takes the plan's place, in columns if it is too tall."""
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


def wrap(text: str, width: float, height: float) -> list[str]:
    """A string split by words into lines no wider than width (sheet mm, by font metrics)."""
    out: list[str] = []
    for word in text.split():
        if out and text_width(f"{out[-1]} {word}", height) <= width:
            out[-1] = f"{out[-1]} {word}"
        else:
            out.append(word)
    return out or [""]


def notes_panel(lines: Sequence[str], width: float | None = None) -> Panel:
    """Note lines in small type; width wraps them by words to this width."""
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
    plan: Plan,
    wiring: Wiring,
    elec: Electrical,
    language: Language,
    prices: Prices | None = None,
    quantities: Wiring | None = None,
    board: BoardPanel | None = None,
) -> tuple[Panel, Panel]:
    """The "Groups" with wiring calculation notes, and under them the electrical estimate (prices
    from the list on top of the price service, pricing.Prices) or a bill of quantities (prices None,
    no prices): a stage's estimate sits on its sheet. Cable by type with margin comes first in
    the estimate; there is no separate cable type table here. quantities is the wiring for
    estimate quantities (wiring.estimate_wiring); None means the same as on the sheet; board is
    the panel set ("Panel" sheet): breakers and group power, the panel in the estimate."""
    cables = groups_panel(plan, elec, wiring, board, wiring_notes(wiring, language))
    assert cables is not None  # there is wiring, so there are groups
    priced = prices is not None and prices.priced
    est = build_estimate(quantities or wiring, elec, prices or Prices(), language, board)
    sheet = estimate_table(est, language, priced=priced)
    estimate = table_panel(sheet)
    if prices is not None and priced:
        lines = price_notes(est, prices, language)
        if lines:
            estimate = stacked(estimate, notes_panel(lines, width=sheet.width))
    return cables, estimate


def draw_stages(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical | None,
    prices: Prices | None = None,
    edits: WiringEdits | None = None,
    plumbing: tuple[Plumbing, Network] | None = None,
) -> tuple[Drawing, list[SheetSpec]]:
    """Model of all stages at the current scale and sheet descriptions (without the sheets
    themselves). plumbing is plumbing and its network (plumbing/network.build_network): the
    "Plumbing" sheet comes right after the electrical sheets, before the point schedule and the
    elevations."""
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
                        plan,
                        wiring,
                        elec,
                        plan.language,
                        prices,
                        estimate_wiring(plan, contours, elec, edits),
                        build_panel(plan, elec),
                    ),
                )
            )
        board = panel_spec(plan, elec)
        if board is not None:
            specs.append(board)
    if plumbing is not None:
        specs.append(plumbing_spec(msp, plan, *plumbing, prices))
    if elec is not None:
        # The point schedule is an appendix at the end: stage sheet numbers do not change
        points = points_spec(plan, elec)
        if points is not None:
            specs.append(points)
        # Wall elevations also at the end, as many sheets as needed
        water = water_views(*plumbing) if plumbing is not None else None
        elevations = elevations_spec(plan, contours, elec, wiring, water)
        if elevations is not None:
            specs.append(elevations)
    return doc, specs


def plumbing_spec(
    msp: Modelspace, plan: Plan, plumbing: Plumbing, net: Network, prices: Prices | None
) -> SheetSpec:
    """The "Plumbing" sheet: pipes, fixtures, risers, obstacles; on the right "Fixtures" with notes
    (assumptions, weak spots), "Pipes" and the plumbing estimate; the legend by the title block."""
    draw_plumbing(msp, plan, plumbing, net)
    lang = plan.language
    tables: list[Panel] = []
    fixtures = fixtures_table(plan, plumbing, net)
    notes = plumbing_notes(plan, plumbing, net)
    if fixtures is not None:
        panel = table_panel(fixtures)
        tables.append(stacked(panel, notes_panel(notes, width=fixtures.width)))
    elif notes:
        tables.append(notes_panel(notes, width=ELEV_NOTES_W))
    pipes = pipes_table(plan, net)
    if pipes is not None:
        tables.append(table_panel(pipes))
    priced = prices is not None and prices.priced
    est = plumbing_estimate(net, plumbing, prices or Prices(), lang)
    if est.lines:
        title = plumbing_estimate_text("sheet_title" if priced else "sheet_volumes", lang)
        sheet = estimate_table(est, lang, priced=priced, title=title)
        estimate = table_panel(sheet)
        if prices is not None and priced:
            lines = price_notes(est, prices, lang)
            if lines:
                estimate = stacked(estimate, notes_panel(lines, width=sheet.width))
        tables.append(estimate)
    legends = tuple(Panel(w, h, draw) for w, h, draw in legend_variants(lang))
    return SheetSpec(
        "tab_plumbing", "plumbing_image", PLUMBING_SHEET_LAYERS, tuple(tables), legends=legends
    )


def lighting_spec(
    msp: Modelspace, plan: Plan, contours: dict[str, Contour], elec: Electrical
) -> SheetSpec | None:
    """The "Lighting" sheet, right after electrical: switch links and the "Switches" table, a
    legend of lights only. No lights, no sheet."""
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
    return SheetSpec(
        "tab_lighting",
        "lighting_image",
        LIGHTING_SHEET_LAYERS,
        tables=tuple(tables),
        legends=legend_columns(lighting_model(elec), lang),
    )


def elevations_spec(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical,
    wiring: Wiring | None,
    water: WaterMap | None = None,
) -> SheetSpec | None:
    """The "Elevations" sheets: wall after wall at the set's scale, page by page; first an
    explanation of how to read the dimensions. No walls with electrical items, no sheets."""
    walls = wall_elevations(plan, contours, elec, wiring, water=water)
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
    """The "Panel" sheet: the panel front view centred in the plan section, devices with load and
    weak spots on the right. No groups, no sheet."""
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
