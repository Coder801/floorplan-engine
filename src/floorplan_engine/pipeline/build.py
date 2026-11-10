"""Project build: DXF, .epd artifact, estimates and journals in out/."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ezdxf.document import Drawing
from ezdxf.filemanagement import readfile

from floorplan_engine.drawing.wiring import write_chases, write_journal
from floorplan_engine.electrical.elevations import elevation_data
from floorplan_engine.electrical.estimate import (
    ESTIMATE_CSV,
    ESTIMATE_MD,
    ESTIMATE_XLSX,
    PriceSource,
)
from floorplan_engine.electrical.groups import group_colors
from floorplan_engine.electrical.panel import BoardPanel, build_panel, write_loads
from floorplan_engine.electrical.pricing import Prices
from floorplan_engine.electrical.wiring import box_wiring, estimate_wiring
from floorplan_engine.electrical.wiring_model import Wiring
from floorplan_engine.electrical.work_scope import WORK_SCOPE_MD
from floorplan_engine.epd.artifact import export_artifact
from floorplan_engine.epd.objects import (
    describe_objects,
    line_chains,
    line_groups,
    plan_areas,
    plan_chains,
    wire_titles,
    wiring_handles,
)
from floorplan_engine.epd.overview import overview_data
from floorplan_engine.epd.panel_data import panel_data
from floorplan_engine.epd.plumbing import plumbing_objects, plumbing_scene, plumbing_tables
from floorplan_engine.epd.scene3d import build_scene
from floorplan_engine.epd.side import side_legends, side_tables
from floorplan_engine.epd.thumbnail import PREVIEW_FILE, plan_thumbnail
from floorplan_engine.model.plumbing import PLUMBING_FILE, Plumbing
from floorplan_engine.model.scale import drawing_scale
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.pipeline.assessment import (
    Assessment,
    assess_project,
    plumbing_of,
    price_service,
    save_checked,
    write_report,
)
from floorplan_engine.pipeline.estimates import write_estimate, write_plumbing_estimate
from floorplan_engine.pipeline.files import (
    ARTIFACT_FILE,
    CHASES_FILE,
    LOADS_FILE,
    OUT_DIR,
    PLUMBING_ESTIMATE_FILES,
    PROJECT_FILE,
    SEWER_ROUTES_FILE,
    SHEETS_DIR,
    STICKERS_COLOR_FILE,
    STICKERS_COLOR_SHORT_FILE,
    STICKERS_FILE,
    STICKERS_FILES,
    STICKERS_SHORT_FILE,
    WIRING_JOURNAL_FILE,
)
from floorplan_engine.pipeline.prices import find_prices, sheet_inputs
from floorplan_engine.pipeline.variants import variant_block
from floorplan_engine.plumbing.estimate import build_estimate as build_plumbing_estimate
from floorplan_engine.plumbing.network import Network, build_network, routes_json
from floorplan_engine.plumbing.rows import water_views
from floorplan_engine.sheets.document import build_project_document, document_scale, sheet_png_name
from floorplan_engine.sheets.preview import render_png, sheet_layouts
from floorplan_engine.sheets.stickers import write_stickers
from floorplan_engine.validation.issues import (
    ELECTRICAL_FILE,
    WIRING_FILE,
    Issue,
    Severity,
)
from floorplan_engine.validation.validate import Report


@dataclass
class BuildResult:
    assessment: Assessment
    report_files: list[Path] = field(default_factory=list)
    dxf: Path | None = None
    artifact: Path | None = None
    journal: Path | None = None  # cable log of wiring through boxes (CSV)
    chases: Path | None = None  # chase schedule (CSV)
    loads: Path | None = None  # panel load list (CSV)
    stickers: Path | None = None  # panel stickers (PDF)
    estimate: list[Path] = field(default_factory=list)  # estimate: md, csv, xlsx, as on the sheet
    plumbing_estimate: list[Path] = field(default_factory=list)  # plumbing estimate
    sewer_routes: Path | None = None  # sewer routes (JSON, routing spec format)
    price_issues: list[Issue] = field(default_factory=list)  # prices.yaml could not be read
    sheets: list[Path] = field(default_factory=list)

    @property
    def built(self) -> bool:
        return self.dxf is not None


def render_sheets(out: Path) -> list[Path]:
    """PNG of each project.dxf sheet in out/sheets/NN-<sheet>.png, for example 02-electrical.png
    (old previews are deleted)."""
    dxf = out / PROJECT_FILE
    if not dxf.exists():
        return []
    sheets = out / SHEETS_DIR
    for old in sheets.glob("*.png"):
        old.unlink()
    doc = readfile(dxf)
    return [
        render_png(doc, layout, sheets / sheet_png_name(layout.name))
        for layout in sheet_layouts(doc)
    ]


@dataclass
class _Build:
    """One running build: what its steps share. Each step writes its files in out/ or, when its
    stage is not there, removes what an earlier build left."""

    project: Path
    assessment: Assessment
    result: BuildResult
    plan: Plan
    elec: Electrical | None
    prices: Prices | None
    plumbing: Plumbing | None

    @property
    def out(self) -> Path:
        return self.project / OUT_DIR

    @property
    def report(self) -> Report:
        return self.assessment.report

    def warn(self, issues: list[Issue]) -> None:
        """Warnings found while building go to the report, so it is written again."""
        self.report.issues += issues
        self.result.report_files = write_report(self.out, self.assessment, self.project.name)


@dataclass
class _Wiring:
    """Wiring through boxes at sheet scale; the sheet handles and the 3D scene come with it."""

    wiring: Wiring | None = None
    edit: dict[str, Any] | None = None
    scene: dict[str, Any] | None = None


def _wiring_step(run: _Build, saved: Drawing) -> _Wiring:
    """Wiring as on the drawing, its cable log and chase schedule."""
    report, result = run.report, run.result
    found = _Wiring()
    if run.elec is not None:
        # At sheet scale: connection nodes, routes and bundle lanes exactly as on the drawing
        with drawing_scale(document_scale(saved)):
            found.wiring = box_wiring(run.plan, report.contours, run.elec, report.wiring_edits)
            if found.wiring is not None:
                found.edit = wiring_handles(run.plan, report.contours, found.wiring)
                found.scene = build_scene(run.plan, report.contours, run.elec, found.wiring)
    journal, chases = run.out / WIRING_JOURNAL_FILE, run.out / CHASES_FILE
    wiring = found.wiring
    if wiring is None:
        journal.unlink(missing_ok=True)
        chases.unlink(missing_ok=True)
        return found
    assert run.elec is not None
    titles = wire_titles(run.plan, run.elec, wiring)
    result.journal = write_journal(wiring, journal, titles)
    result.chases = write_chases(wiring, chases)
    if wiring.edit_notes:
        run.warn([Issue(WIRING_FILE, p, m, Severity.WARNING) for p, m in wiring.edit_notes])
    return found


def _panel_step(run: _Build) -> BoardPanel | None:
    """The panel, its load list and stickers."""
    panel = build_panel(run.plan, run.elec) if run.elec is not None else None
    loads = run.out / LOADS_FILE
    if panel is None:
        loads.unlink(missing_ok=True)
        for file in STICKERS_FILES:
            (run.out / file).unlink(missing_ok=True)
        return None
    run.result.loads = write_loads(panel, loads)
    assert run.elec is not None
    board = run.elec.board.name if run.elec.board is not None else "ЩР"
    lang, colors = run.plan.language, group_colors(run.elec)
    run.result.stickers = write_stickers(panel, board, lang, run.out / STICKERS_FILE)
    write_stickers(panel, board, lang, run.out / STICKERS_COLOR_FILE, colors)
    write_stickers(panel, board, lang, run.out / STICKERS_SHORT_FILE, short=True)
    write_stickers(panel, board, lang, run.out / STICKERS_COLOR_SHORT_FILE, colors, short=True)
    if panel.warnings:
        run.warn(
            [
                Issue(
                    ELECTRICAL_FILE,
                    f"groups.{w.group}" if w.group else "panel",
                    w.text["ru"],
                    Severity.WARNING,
                )
                for w in panel.warnings
            ]
        )
    return panel


def _plumbing_step(run: _Build) -> Network | None:
    """The plumbing network, its estimate and sewer routes."""
    report, plumbing = run.report, run.plumbing
    net = build_network(run.plan, report.contours, plumbing) if plumbing is not None else None
    routes = run.out / SEWER_ROUTES_FILE
    if net is None or plumbing is None:
        for name in PLUMBING_ESTIMATE_FILES:
            (run.out / name).unlink(missing_ok=True)
        routes.unlink(missing_ok=True)
        return None
    if net.weak:
        run.warn(
            [
                Issue(
                    PLUMBING_FILE,
                    w.target and f"fixtures.{w.target}",
                    w.text["ru"],
                    Severity.WARNING,
                )
                for w in net.weak
            ]
        )
    run.result.plumbing_estimate = write_plumbing_estimate(
        run.project,
        run.assessment,
        net,
        plumbing,
        run.prices or Prices(),
        find_prices(run.project),
    )
    routes.write_text(
        json.dumps(routes_json(net), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    run.result.sewer_routes = routes
    return net


def _estimate_step(run: _Build, quantities: Wiring | None, panel: BoardPanel | None) -> None:
    """Estimate files are the same as on the sheet, so the Excel in the viewer matches the sheets;
    if the price list has errors, no estimate is written (errors go to price_issues) and the old
    one is removed."""
    if quantities is None or run.elec is None or run.result.price_issues:
        for name in (ESTIMATE_MD, ESTIMATE_CSV, ESTIMATE_XLSX, WORK_SCOPE_MD):
            (run.out / name).unlink(missing_ok=True)
        return
    _, run.result.estimate = write_estimate(
        run.project,
        run.assessment,
        quantities,
        run.elec,
        run.prices or Prices(),
        find_prices(run.project),
        panel,
    )


def _export(
    run: _Build,
    saved: Drawing,
    found: _Wiring,
    panel: BoardPanel | None,
    net: Network | None,
) -> Path:
    """The .epd artifact, made from the written file: exactly what AutoCAD will open."""
    plan, contours, elec, plumbing = run.plan, run.report.contours, run.elec, run.plumbing
    prices, wiring, scene = run.prices, found.wiring, found.scene
    pipes = (plumbing, net) if plumbing is not None and net is not None else None
    panel_view = None
    if panel is not None:
        assert elec is not None
        board = elec.board.name if elec.board is not None else "ЩР"
        panel_view = panel_data(panel, group_colors(elec), board, plan.language)
    water = water_views(*pipes) if pipes is not None else None
    objects = describe_objects(plan, contours, elec, wiring, water)
    if pipes is not None:
        objects |= plumbing_objects(plan, *pipes)
    quantities = None
    if wiring is not None and elec is not None:
        quantities = estimate_wiring(plan, contours, elec, run.report.wiring_edits)
    tables = side_tables(plan, contours, elec, wiring, prices, quantities)
    if pipes is not None:
        tables |= plumbing_tables(plan, *pipes, prices)
        if scene is not None:
            ceiling = wiring.ceiling_height if wiring is not None else plan.ceiling_height
            scene |= plumbing_scene(pipes[1], ceiling)
    _estimate_step(run, quantities, panel)
    return export_artifact(
        saved,
        plan,
        run.out / ARTIFACT_FILE,
        objects,
        tables,
        line_chains(wiring) if wiring is not None else None,
        line_groups(wiring) if wiring is not None else None,
        found.edit,
        scene,
        panel_view,
        elevation_data(plan, contours, elec, wiring, group_colors(elec), water)
        if elec is not None
        else None,
        side_legends(elec, plan.language) if elec is not None else None,
        variant_block(run.report, prices) if elec is not None and prices is not None else None,
        overview_data(
            plan,
            contours,
            elec,
            panel,
            plumbing,
            net,
            build_plumbing_estimate(pipes[1], pipes[0], prices or Prices(), plan.language)
            if pipes is not None
            else None,
            run.report.source_electrical,
        ),
        plan_chains=plan_chains(plan, contours),
        plan_areas=plan_areas(plan, contours),
    )


def build_project(
    project: Path, previews: bool = False, prices_from: PriceSource | None = None
) -> BuildResult:
    """Assess the project, write the report and, if the plan can be built, build the DXF and the
    .epd artifact from the stages that can be built. Sheets are shown from the .epd (canvas);
    PNGs from the DXF only with previews=True, otherwise old out/sheets/*.png are deleted.
    prices_from is the price service for the estimate; None means the mock
    (pricing.MockPriceService)."""
    assessment = assess_project(project)
    out = project / OUT_DIR
    result = BuildResult(assessment, write_report(out, assessment, project.name))
    if not assessment.plan_builds:
        return result
    report = assessment.report
    assert report.plan is not None
    elec, prices, result.price_issues = sheet_inputs(
        project, assessment, price_service(prices_from)
    )
    plumbing = plumbing_of(assessment)
    doc = build_project_document(
        report.plan,
        report.contours,
        elec,
        prices=prices,
        edits=report.wiring_edits,
        plumbing=plumbing,
    )
    saved = save_checked(doc, out / PROJECT_FILE)
    result.dxf = out / PROJECT_FILE
    # Preview for the project card in the viewer
    (out / PREVIEW_FILE).write_text(plan_thumbnail(report.plan, report.contours), "utf-8")
    run = _Build(project, assessment, result, report.plan, elec, prices, plumbing)
    found = _wiring_step(run, saved)
    panel = _panel_step(run)
    net = _plumbing_step(run)
    result.artifact = _export(run, saved, found, panel, net)
    if previews:
        result.sheets = render_sheets(out)
    else:
        for old in (out / SHEETS_DIR).glob("*.png"):
            old.unlink()
    return result
