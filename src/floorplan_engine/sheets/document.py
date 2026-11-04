"""Project document: the 1:1 model and sheets with 1:50 viewports.

The model holds all geometry of all stages, each stage on its own layers (sheets.stages). A
sheet (layout) has the frame and title block in sheet mm, a 1:50 viewport onto the model with
the layers of other stages frozen, tables and the legend; the layout logic is sheets.layout.

Paper size, orientation and scale are shared by the whole set (choose_paper_and_scale).
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
from floorplan_engine.electrical.pricing import Prices
from floorplan_engine.model.geometry import Contour, Vec
from floorplan_engine.model.plumbing import Plumbing
from floorplan_engine.model.scale import DEFAULT_SCALE, SCALES, drawing_scale, sheet_scale
from floorplan_engine.model.schema import Electrical, Plan, WiringEdits
from floorplan_engine.model.texts import TEXTS, tr
from floorplan_engine.plumbing.network import build_network
from floorplan_engine.plumbing.network_model import Network
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

VIEW_FILL = 0.94  # target share of the plan section taken by the drawing (decision 2026-10-21)
VIEW_FILL_MAX = 1.0  # more than this and the drawing sticks out of the section
VIEWPORT_LOCKED = 16384  # VIEWPORT flag "Display locked": the mouse wheel does not change the scale
# Layer 0 carries block contents; sheet layers do not touch the model
NEVER_FROZEN = frozenset({"0", "DEFPOINTS", A_SHEET.name, A_VPORT.name})


# Sheet PNG name by its tab: "02 Електрика" → 02-electrical.png (Latin, for paths and the API)
SHEET_SLUGS = {
    "tab_plan": "plan",
    "tab_electrical": "electrical",
    "tab_lighting": "lighting",
    "tab_wiring": "wiring",
    "tab_panel": "panel",
    "tab_plumbing": "plumbing",
    "tab_points": "points",
    "tab_elevations": "elevations",
}


def sheet_slug(tab: str) -> str | None:
    """Sheet topic (plan / electrical / wiring) by the tab name "NN Name" in any language."""
    title = tab.partition(" ")[2]
    for suffix in TEXTS["sheet_continued"].values():
        title = title.removesuffix(f" {suffix}")
    return next((slug for key, slug in SHEET_SLUGS.items() if title in TEXTS[key].values()), None)


def sheet_png_name(tab: str) -> str:
    """Sheet preview file name by the tab name "NN Name" in any project language."""
    return f"{tab.partition(' ')[0]}-{sheet_slug(tab) or 'sheet'}.png"


def add_sheet(
    doc: Drawing, spec: SheetSpec, tab: str, stamp: StampText, paper: Paper
) -> Paperspace:
    """Sheet on paper: frame, title block, viewport (or diagram), tables and legend."""
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
    """Sheet with a diagram instead of a viewport: the diagram is centred in the plan section."""
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
    """Scale the document model is drawn at (50 means 1:50), from the sheet viewport;
    DEFAULT_SCALE if there are no sheets."""
    for layout in doc.layouts:
        for vp in layout.query("VIEWPORT"):
            if vp.dxf.layer == A_VPORT.name and vp.dxf.height > 0:
                return round(float(vp.dxf.view_height) / float(vp.dxf.height), 6)
    return DEFAULT_SCALE


def _at(view: tuple[float, float], scale: float) -> tuple[float, float]:
    """View size at 1:scale from the 1:50 draft, with a margin: labels and dimension lines at a
    large scale take less model space than in the draft."""
    k = DEFAULT_SCALE / scale
    return (
        (view[0] - 2 * VIEW_MARGIN) * k + 2 * VIEW_MARGIN,
        (view[1] - 2 * VIEW_MARGIN) * k + 2 * VIEW_MARGIN,
    )


def choose_paper_and_scale(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical | None,
    prices: Prices | None = None,
    edits: WiringEdits | None = None,
    plumbing: tuple[Plumbing, Network] | None = None,
) -> tuple[Paper, float]:
    """Paper for the set: the smallest on which every sheet fits its tables and legend and the plan
    at 1:50 or larger takes at most VIEW_FILL_MAX of its section (a size from room.yaml is used
    alone). The scale is the one that brings the tightest plan closest to VIEW_FILL, no more than
    VIEW_FILL_MAX."""
    with drawing_scale(DEFAULT_SCALE):
        draft, all_specs = draw_stages(plan, contours, elec, prices, edits, plumbing)
        views = {s.tab_key: view_parts(draft, s) for s in all_specs if s.body is None}
    papers = format_candidates(plan.sheet.format)
    specs = all_specs

    def worst(paper: Paper, scale: float) -> float:
        # A diagram (panel) has no scale: panels_fit checks its space
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
        # Tables fit no paper size: take the largest, tables go to a continuation sheet
        # Scale follows the view: it will not help diagrams (panel, tables), printing checks those
        paper = max(papers, key=lambda p: (p[1] * p[2], p[1]))
        specs = fit_specs(all_specs, paper)
        fitting = [s for s in SCALES if worst(paper, s) <= VIEW_FILL_MAX]
        # The 1:50 draft estimate understates the dimension band at a small scale, so the chosen
        # scale is checked by drawing; if it does not fit, the next smaller one
        best = min(fitting, key=lambda s: abs(worst(paper, s) - VIEW_FILL), default=SCALES[-1])
        for scale in [s for s in SCALES if s >= best]:
            with drawing_scale(scale):
                real, real_specs = draw_stages(plan, contours, elec, prices, edits, plumbing)
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
    prices: Prices | None = None,
    edits: WiringEdits | None = None,
    plumbing: Plumbing | None = None,
) -> Drawing:
    """One DXF: the model with all stages and one sheet per stage; paper and scale are shared.
    prices are the estimate prices on the wiring sheet (price list on top of the price service);
    None gives a bill of quantities without prices.
    edits are manual wiring edits (wiring.yaml); plumbing is plumbing (the "Plumbing" sheet)."""
    water = (plumbing, build_network(plan, contours, plumbing)) if plumbing is not None else None
    paper, scale = choose_paper_and_scale(plan, contours, elec, prices, edits, water)
    with drawing_scale(scale):
        doc, specs = draw_stages(plan, contours, elec, prices, edits, water)
        specs = fit_specs(specs, paper)
        main_no = 1  # sheet whose tables continue
        for no, spec in enumerate(specs, 1):
            main_no = main_no if spec.continued else no
            tab = f"{no:02d} {tr(spec.tab_key, plan.language)}"
            stamp = plan_stamp(plan, spec.image_key, no, len(specs), today)
            if spec.continued:
                tab += f" {tr('sheet_continued', plan.language)}"
                if spec.paged:  # elevation continuation keeps the same name
                    image = f"{stamp.image} {tr('sheet_continued', plan.language)}"
                else:
                    image = tr("sheet_tables", plan.language, no=main_no)
                stamp = replace(stamp, image=image)
            add_sheet(doc, spec, tab, stamp, paper)
    # The default empty sheet from ezdxf is not needed
    doc.layouts.delete("Layout1")
    finalize_fields(doc)
    return doc
