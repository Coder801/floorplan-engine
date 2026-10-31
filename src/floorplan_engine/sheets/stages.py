"""Этапы на листах: модель всех этапов в текущем масштабе (draw_stages) и что кладётся на
лист каждого из них — ведомости, легенда, примечания, развёртки стен, щит в лицо.
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
    split_legend,
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
    TEXT_SMALL_MM,
    WIRING_LAYERS,
    new_document,
    text_width,
)
from floorplan_engine.drawing.lighting import draw_lighting, is_lighting, switch_table
from floorplan_engine.drawing.panel import devices_table, draw_panel_front, fit_panel, panel_notes
from floorplan_engine.drawing.plan import RoomArea, add_text, draw_plan
from floorplan_engine.drawing.schedules import (
    estimate_table,
    groups_table,
    points_table,
)
from floorplan_engine.drawing.symbols import define_blocks
from floorplan_engine.drawing.tables import Table, draw_table, room_schedule
from floorplan_engine.drawing.wiring import draw_wiring, wiring_notes
from floorplan_engine.electrical.elevations import wall_elevations
from floorplan_engine.electrical.estimate import PRICES_FILE, PriceList, build_estimate
from floorplan_engine.electrical.estimate import text as estimate_text
from floorplan_engine.electrical.groups import group_colors
from floorplan_engine.electrical.panel import BoardPanel, build_panel
from floorplan_engine.electrical.wiring import box_wiring, estimate_wiring
from floorplan_engine.electrical.wiring_model import Wiring
from floorplan_engine.model.geometry import Contour, Vec
from floorplan_engine.model.scale import sheet_scale
from floorplan_engine.model.schema import LIGHT_TYPES, Electrical, Plan, WiringEdits
from floorplan_engine.model.texts import Language, tr
from floorplan_engine.sheets.layout import (
    Panel,
    SheetSpec,
    beside,
    in_row,
    stacked,
    table_panel,
)

ELEV_NOTES_W = 160.0  # ширина пояснения к развёрткам, мм листа
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
        variants.append(in_row(cols))
    return tuple(variants)


def groups_panel(
    plan: Plan,
    elec: Electrical,
    wiring: Wiring,
    board: BoardPanel | None,
    extra: Sequence[str] = (),
) -> Panel | None:
    """«Группы» (автомат и мощность — с листа «Щит», кабель и длина — из проводки) с
    примечаниями: о составленных назначениях и допущениях, затем extra (расчёт проводки)."""
    built = groups_table(plan, elec, wiring, board)
    if built is None:
        return None
    table, notes = built
    lines = [*notes, *extra]
    panel = table_panel(table)
    return stacked(panel, notes_panel(lines, width=table.width)) if lines else panel


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
    plan: Plan,
    wiring: Wiring,
    elec: Electrical,
    language: Language,
    prices: PriceList | None = None,
    quantities: Wiring | None = None,
    board: BoardPanel | None = None,
) -> tuple[Panel, Panel]:
    """«Группы» с примечаниями расчёта проводки, под ними — смета электрики (с прайсом) или
    ведомость объёмов (без прайса): смета этапа стоит на его листе. Кабель по маркам
    с запасом — первые строки сметы, отдельной таблицы марок здесь нет. quantities — проводка
    для объёмов сметы (wiring.estimate_wiring); None — та же, что на листе; board — состав
    щита (лист «Щит»): автоматы и мощность групп, щит в смете."""
    cables = groups_panel(plan, elec, wiring, board, wiring_notes(wiring, language))
    assert cables is not None  # проводка есть — есть и группы
    est = build_estimate(quantities or wiring, elec, prices or PriceList(), language, board)
    sheet = estimate_table(est, language, priced=prices is not None)
    estimate = table_panel(sheet)
    if prices is not None:
        date = f" ({prices.date})" if prices.date else ""
        lines = [estimate_text("sheet_prices", language, f=PRICES_FILE, date=date)]
        if est.unpriced:
            lines.append(estimate_text("unpriced", language, n=est.unpriced, f=PRICES_FILE))
        estimate = stacked(estimate, notes_panel(lines, width=sheet.width))
    return cables, estimate


def draw_stages(
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
