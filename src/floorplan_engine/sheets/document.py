"""Документ проекта: модель 1:1 и листы с видовыми экранами 1:50.

Модель — вся геометрия всех этапов, каждый этап на своих слоях (sheets.stages). Лист
(layout) — рамка и основная надпись в мм листа, видовой экран 1:50 на модель, в котором
заморожены слои чужих этапов, таблицы и легенда; раскладка — sheets.layout.

Формат, ориентация и масштаб — общие для комплекта (choose_paper_and_scale).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from ezdxf.document import Drawing
from ezdxf.layouts.layout import Paperspace

from floorplan_engine.drawing.fields import finalize_fields
from floorplan_engine.drawing.layers import (
    A_SHEET,
    A_VPORT,
)
from floorplan_engine.drawing.plan import plan_stamp
from floorplan_engine.drawing.titleblock import (
    SheetLayout,
    StampText,
    draw_sheet,
    format_candidates,
)
from floorplan_engine.electrical.estimate import PriceList
from floorplan_engine.model.geometry import Contour, Vec
from floorplan_engine.model.scale import DEFAULT_SCALE, SCALES, drawing_scale, sheet_scale
from floorplan_engine.model.schema import Electrical, Plan, WiringEdits
from floorplan_engine.model.texts import TEXTS, tr
from floorplan_engine.sheets.layout import (
    VIEW_MARGIN,
    Panel,
    Paper,
    SheetSpec,
    fill,
    fit_body,
    fit_specs,
    panels_fit,
    place,
    plan_region,
    view_parts,
    view_size,
    visible_extents,
)
from floorplan_engine.sheets.stages import draw_stages

VIEW_FILL = 0.94  # какую долю секции плана занимает чертёж — цель (решение 2026-10-21)
VIEW_FILL_MAX = 1.0  # больше — чертёж вылезает из секции
VIEWPORT_LOCKED = 16384  # флаг VIEWPORT «Display locked»: колесо мыши не сбивает масштаб
# Слой 0 несёт содержимое блоков, слои листа модели не касаются
NEVER_FROZEN = frozenset({"0", "DEFPOINTS", A_SHEET.name, A_VPORT.name})


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


def _at(view: tuple[float, float], scale: float) -> tuple[float, float]:
    """Размер вида в масштабе 1:scale по черновику 1:50 — с запасом: подписи и размерные
    линии в крупном масштабе занимают в модели меньше, чем в черновике."""
    k = DEFAULT_SCALE / scale
    return (
        (view[0] - 2 * VIEW_MARGIN) * k + 2 * VIEW_MARGIN,
        (view[1] - 2 * VIEW_MARGIN) * k + 2 * VIEW_MARGIN,
    )


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
        draft, all_specs = draw_stages(plan, contours, elec, prices, edits)
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
                real, real_specs = draw_stages(plan, contours, elec, prices, edits)
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
        doc, specs = draw_stages(plan, contours, elec, prices, edits)
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
