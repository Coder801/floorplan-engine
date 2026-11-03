"""Project pipeline without screen output: assessment, report, DXF build, artifact and PNG.

Shared by the CLI and the service: the CLI prints the result, the service stores it in the
project state.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from ezdxf.document import Drawing
from ezdxf.filemanagement import readfile

from floorplan_engine.drawing.titleblock import FORMATS
from floorplan_engine.drawing.wiring import write_chases, write_journal
from floorplan_engine.electrical.chases import CHASE_CABLES, CHASE_SHARE, HOLE_CABLES
from floorplan_engine.electrical.elevations import elevation_data
from floorplan_engine.electrical.estimate import (
    ESTIMATE_CSV,
    ESTIMATE_MD,
    ESTIMATE_XLSX,
    FIXING_STEP,
    HINTS,
    LINES,
    PRICES_FILE,
    Estimate,
    PriceList,
    PriceSource,
    build_estimate,
    edit_price_items,
    unknown_keys,
    write_csv,
    write_markdown,
    write_xlsx,
)
from floorplan_engine.electrical.estimate import text as estimate_text
from floorplan_engine.electrical.groups import group_colors, group_key
from floorplan_engine.electrical.market import (
    MARKET_FILE,
    MarketSample,
    item_spread,
    period,
    used_sources,
)
from floorplan_engine.electrical.panel import BoardPanel, build_panel, write_loads
from floorplan_engine.electrical.pricing import MockPriceService, Prices, mock_price, price_notes
from floorplan_engine.electrical.variants import project_variants, variant_summary
from floorplan_engine.electrical.wiring import END_ALLOWANCE, RESERVE, box_wiring, estimate_wiring
from floorplan_engine.electrical.wiring_model import CHASE_NARROW, Wiring
from floorplan_engine.epd.artifact import export_artifact
from floorplan_engine.epd.objects import (
    describe_objects,
    line_chains,
    line_groups,
    wire_titles,
    wiring_handles,
)
from floorplan_engine.epd.overview import overview_data
from floorplan_engine.epd.panel_data import panel_data
from floorplan_engine.epd.plumbing import plumbing_objects, plumbing_scene, plumbing_tables
from floorplan_engine.epd.scene3d import build_scene
from floorplan_engine.epd.side import side_legends, side_tables
from floorplan_engine.epd.thumbnail import PREVIEW_FILE, plan_thumbnail
from floorplan_engine.model.intake import Stage
from floorplan_engine.model.panel_catalog import DeviceKind
from floorplan_engine.model.plumbing import PLUMBING_FILE, Plumbing
from floorplan_engine.model.scale import drawing_scale
from floorplan_engine.model.schema import Electrical, SheetFormat, Variant, WiringEdits, WiringFile
from floorplan_engine.plumbing.estimate import LINES as PLUMBING_LINES
from floorplan_engine.plumbing.estimate import MOCK_PRICES as PLUMBING_MOCK_PRICES
from floorplan_engine.plumbing.estimate import RESERVE as PLUMBING_RESERVE
from floorplan_engine.plumbing.estimate import build_estimate as build_plumbing_estimate
from floorplan_engine.plumbing.estimate import text as plumbing_estimate_text
from floorplan_engine.plumbing.network import Network, build_network, routes_json
from floorplan_engine.plumbing.rows import water_views
from floorplan_engine.sheets.document import build_project_document, document_scale, sheet_png_name
from floorplan_engine.sheets.preview import paper_size, render_png, sheet_layouts
from floorplan_engine.sheets.printing import SheetCheck, check_sheets, write_album
from floorplan_engine.validation.answers import load_optional
from floorplan_engine.validation.assess import STAGE_FILES, StageResult, assess
from floorplan_engine.validation.issues import (
    ELECTRICAL_FILE,
    VARIANT_FILE,
    WIRING_FILE,
    Issue,
    Severity,
    load_yaml,
    parse_model,
)
from floorplan_engine.validation.report import REPORT_JSON, REPORT_MD, render_markdown, to_json
from floorplan_engine.validation.validate import Report, validate_project

OUT_DIR = "out"
PROJECT_FILE = "project.dxf"
ARTIFACT_FILE = "project.epd"
ALBUM_FILE = "album.pdf"  # PDF album of the sheets (print command)
WIRING_JOURNAL_FILE = "wiring-boxes.csv"  # cable log of wiring through boxes
CHASES_FILE = "wiring-chases.csv"  # wall chase schedule
LOADS_FILE = "panel-loads.csv"  # load list by panel group
SHEETS_DIR = "sheets"


class AuditError(RuntimeError):
    """The written DXF failed the ezdxf audit."""


@dataclass
class Assessment:
    report: Report
    stages: list[StageResult]

    @property
    def name(self) -> str:
        return self.report.plan.name if self.report.plan else ""

    def status(self, stage: Stage) -> StageResult | None:
        return next((r for r in self.stages if r.stage is stage), None)

    @property
    def global_errors(self) -> list[Issue]:
        """Errors outside stage files (intake.yaml, answers.yaml) stop everything."""
        stage_files = set(STAGE_FILES.values())
        return [i for i in self.report.errors if i.file not in stage_files]

    @property
    def plan_builds(self) -> bool:
        plan = self.status(Stage.PLAN)
        return (
            not self.global_errors
            and self.report.plan is not None
            and plan is not None
            and plan.status.builds
        )

    @property
    def open_questions(self) -> int:
        return sum(len(r.open_questions) for r in self.stages)


@dataclass
class BuildResult:
    assessment: Assessment
    report_files: list[Path] = field(default_factory=list)
    dxf: Path | None = None
    artifact: Path | None = None
    journal: Path | None = None  # cable log of wiring through boxes (CSV)
    chases: Path | None = None  # chase schedule (CSV)
    loads: Path | None = None  # panel load list (CSV)
    estimate: list[Path] = field(default_factory=list)  # estimate: md, csv, xlsx, as on the sheet
    plumbing_estimate: list[Path] = field(default_factory=list)  # plumbing estimate
    sewer_routes: Path | None = None  # sewer routes (JSON, routing spec format)
    price_issues: list[Issue] = field(default_factory=list)  # prices.yaml could not be read
    sheets: list[Path] = field(default_factory=list)

    @property
    def built(self) -> bool:
        return self.dxf is not None


def assess_project(project: Path) -> Assessment:
    report = validate_project(project)
    return Assessment(report, assess(report))


def _sheet_inputs(
    project: Path, assessment: Assessment, service: PriceSource | None
) -> tuple[Electrical | None, Prices | None, list[Issue]]:
    """What goes on the sheets besides the plan: electrical (if the stage builds) and estimate
    prices, the project or studio price list (if present and readable) on top of the price
    service; prices are needed even without electrical if plumbing builds."""
    report = assessment.report
    elec_status = assessment.status(Stage.ELECTRICAL)
    elec = report.electrical if elec_status is not None and elec_status.status.builds else None
    if elec is None and plumbing_of(assessment) is None:
        return None, None, []
    price_path = find_prices(project)
    own, issues = load_prices(price_path) if price_path is not None else (None, [])
    return elec, Prices(own, service), issues


def plumbing_of(assessment: Assessment) -> Plumbing | None:
    """Plumbing, if its stage builds (plumbing.yaml without errors, questions do not block it)."""
    status = assessment.status(Stage.PLUMBING)
    if status is None or not status.status.builds:
        return None
    return assessment.report.plumbing


def price_service(given: PriceSource | None) -> PriceSource:
    """Price service for estimates: the given client (service/, later) or the mock, which also knows
    plumbing items (plumbing/estimate.MOCK_PRICES)."""
    return given if given is not None else MockPriceService(extra=PLUMBING_MOCK_PRICES)


def write_report(out: Path, assessment: Assessment, fallback_name: str) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    name = assessment.name or fallback_name
    md, js = out / REPORT_MD, out / REPORT_JSON
    md.write_text(render_markdown(name, assessment.report, assessment.stages), encoding="utf-8")
    js.write_text(to_json(name, assessment.report, assessment.stages), encoding="utf-8")
    return [md, js]


def save_checked(doc: Drawing, path: Path) -> Drawing:
    """Save the DXF, read it back and check it with the ezdxf audit; return the re-read document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path, encoding="utf-8")
    reread = readfile(path)
    auditor = reread.audit()
    if auditor.has_errors:
        messages = "; ".join(err.message for err in auditor.errors)
        raise AuditError(f"аудит {path.name}: {messages}")
    return reread


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
    elec, prices, result.price_issues = _sheet_inputs(
        project, assessment, price_service(prices_from)
    )
    edits = report.wiring_edits
    plumbing = plumbing_of(assessment)
    doc = build_project_document(
        report.plan, report.contours, elec, prices=prices, edits=edits, plumbing=plumbing
    )
    saved = save_checked(doc, out / PROJECT_FILE)
    result.dxf = out / PROJECT_FILE
    # Preview for the project card in the viewer
    (out / PREVIEW_FILE).write_text(plan_thumbnail(report.plan, report.contours), "utf-8")
    wiring: Wiring | None = None
    edit: dict[str, Any] | None = None
    scene: dict[str, Any] | None = None
    if elec is not None:
        # At sheet scale: connection nodes, routes and bundle lanes exactly as on the drawing
        with drawing_scale(document_scale(saved)):
            wiring = box_wiring(report.plan, report.contours, elec, edits)
            if wiring is not None:
                edit = wiring_handles(report.plan, report.contours, wiring)
                scene = build_scene(report.plan, report.contours, elec, wiring)
    journal, chases = out / WIRING_JOURNAL_FILE, out / CHASES_FILE
    if wiring is not None:
        assert elec is not None
        titles = wire_titles(report.plan, elec, wiring)
        result.journal = write_journal(wiring, journal, titles)
        result.chases = write_chases(wiring, chases)
        if wiring.edit_notes:
            report.issues += [
                Issue(WIRING_FILE, path, msg, Severity.WARNING) for path, msg in wiring.edit_notes
            ]
            result.report_files = write_report(out, assessment, project.name)
    else:
        journal.unlink(missing_ok=True)
        chases.unlink(missing_ok=True)
    panel = build_panel(report.plan, elec) if elec is not None else None
    loads = out / LOADS_FILE
    if panel is not None:
        result.loads = write_loads(panel, loads)
        if panel.warnings:
            report.issues += [
                Issue(
                    ELECTRICAL_FILE,
                    f"groups.{w.group}" if w.group else "panel",
                    w.text["ru"],
                    Severity.WARNING,
                )
                for w in panel.warnings
            ]
            result.report_files = write_report(out, assessment, project.name)
    else:
        loads.unlink(missing_ok=True)
    net = build_network(report.plan, report.contours, plumbing) if plumbing is not None else None
    if net is not None and net.weak:
        report.issues += [
            Issue(
                PLUMBING_FILE, w.target and f"fixtures.{w.target}", w.text["ru"], Severity.WARNING
            )
            for w in net.weak
        ]
        result.report_files = write_report(out, assessment, project.name)
    routes = out / SEWER_ROUTES_FILE
    if net is not None and plumbing is not None:
        result.plumbing_estimate = write_plumbing_estimate(
            project, assessment, net, plumbing, prices or Prices(), find_prices(project)
        )
        routes.write_text(
            json.dumps(routes_json(net), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        result.sewer_routes = routes
    else:
        for name in PLUMBING_ESTIMATE_FILES:
            (out / name).unlink(missing_ok=True)
        routes.unlink(missing_ok=True)
    panel_view = None
    if panel is not None:
        assert elec is not None
        board = elec.board.name if elec.board is not None else "ЩР"
        panel_view = panel_data(panel, group_colors(elec), board, report.plan.language)
    # The artifact comes from the written file: exactly what AutoCAD will open
    water = water_views(plumbing, net) if plumbing is not None and net is not None else None
    objects = describe_objects(report.plan, report.contours, elec, wiring, water)
    if net is not None and plumbing is not None:
        objects |= plumbing_objects(report.plan, plumbing, net)
    quantities = None
    if wiring is not None and elec is not None:
        quantities = estimate_wiring(report.plan, report.contours, elec, edits)
    tables = side_tables(report.plan, report.contours, elec, wiring, prices, quantities)
    if net is not None and plumbing is not None:
        tables |= plumbing_tables(report.plan, plumbing, net, prices)
        if scene is not None:
            ceiling = wiring.ceiling_height if wiring is not None else report.plan.ceiling_height
            scene |= plumbing_scene(net, ceiling)
    if quantities is not None and elec is not None and not result.price_issues:
        # Estimate files are the same as on the sheet, so the Excel in the viewer matches the
        # sheets;
        # if the price list has errors, no estimate is written (errors go to price_issues) and the
        # old one is removed
        _, result.estimate = write_estimate(
            project,
            assessment,
            quantities,
            elec,
            prices or Prices(),
            find_prices(project),
            panel,
        )
    else:
        for name in (ESTIMATE_MD, ESTIMATE_CSV, ESTIMATE_XLSX):
            (out / name).unlink(missing_ok=True)
    chains = line_chains(wiring) if wiring is not None else None
    groups = line_groups(wiring) if wiring is not None else None
    result.artifact = export_artifact(
        saved,
        report.plan,
        out / ARTIFACT_FILE,
        objects,
        tables,
        chains,
        groups,
        edit,
        scene,
        panel_view,
        elevation_data(
            report.plan,
            report.contours,
            elec,
            wiring,
            group_colors(elec),
            water,
        )
        if elec is not None
        else None,
        side_legends(elec, report.plan.language) if elec is not None else None,
        variant_block(report, prices) if elec is not None and prices is not None else None,
        overview_data(
            report.plan,
            report.contours,
            elec,
            panel,
            plumbing,
            net,
            build_plumbing_estimate(net, plumbing, prices or Prices(), report.plan.language)
            if net is not None and plumbing is not None
            else None,
        ),
    )
    if previews:
        result.sheets = render_sheets(out)
    else:
        for old in (out / SHEETS_DIR).glob("*.png"):
            old.unlink()
    return result


def variant_block(report: Report, prices: Prices) -> dict[str, Any] | None:
    """Wiring variants for the viewer (.epd manifest, key variants): the chosen one, "as in project"
    and a summary of each (estimate, cable, devices, chases), without drawings."""
    source, chosen, default = report.source_electrical, report.variant, report.default_variant
    if report.plan is None or source is None or chosen is None or default is None:
        return None
    wiring_file = report.wiring_file or WiringFile()
    items = []
    for variant in project_variants(source):  # without routes the project does not have (routes)
        edits = wiring_file.edits_for(variant.key, default.key)
        summary = variant_summary(report.plan, report.contours, source, variant, edits, prices)
        if summary is not None:
            items.append(summary.as_dict())
    return {"active": chosen.key, "default": default.key, "items": items}


def save_variant(project: Path, data: dict[str, Any]) -> list[Issue]:
    """Save the wiring variant from the viewer to variant.yaml: {mode, route, distribution,
    ceiling_height?}. Without ceiling_height the previous height stays. Errors come with a field
    path, and the file is left unchanged."""
    path = project / VARIANT_FILE
    if "ceiling_height" not in data:  # changing the variant does not reset the ceiling height
        old, _ = load_optional(path, Variant)
        if old is not None and old.ceiling_height is not None:
            data = {**data, "ceiling_height": old.ceiling_height}
    variant, issues = parse_model(Variant, data, VARIANT_FILE)
    if variant is None:
        return issues
    path.write_text(
        "# Вариант проводки и высота потолка, выбранные в просмотре (docs/wiring-variants.md).\n"
        + yaml.safe_dump(
            variant.model_dump(exclude_none=True), allow_unicode=True, sort_keys=False
        ),
        encoding="utf-8",
    )
    return []


def save_wiring_edits(project: Path, changes: dict[str, Any]) -> list[Issue]:
    """Save wiring edits from the viewer to the project's wiring.yaml, under the chosen variant
    (variants.<key>): changes = {"wires": {id: edit or None}, "boxes": {...}}; None removes
    the edit (the line becomes an auto route again). Pre-variant edits (top-level wires and
    boxes) move into the "as in project" section when that variant is edited. No edits means
    no file. Errors come with a field path, and the file is left unchanged."""
    path = project / WIRING_FILE
    report = validate_project(project)
    # Electrical cannot be read, so there is no variant: edits go the old way, outside variant
    # sections
    key = report.variant.key if report.variant is not None else None
    default_key = report.default_variant.key if report.default_variant is not None else None
    current = WiringFile()
    if path.exists():
        raw, issues = load_yaml(path)
        if issues and raw is None and path.stat().st_size:
            return issues
        if isinstance(raw, dict):
            parsed, issues = parse_model(WiringFile, raw, WIRING_FILE)
            if parsed is None:
                return issues
            current = parsed
    if key is None or default_key is None:
        edits = WiringEdits(wires=current.wires, boxes=current.boxes)
    else:
        edits = current.edits_for(key, default_key) or WiringEdits()
    data: dict[str, Any] = {
        "wires": {k: v.model_dump(by_alias=True) for k, v in edits.wires.items()},
        "boxes": {k: v.model_dump() for k, v in edits.boxes.items()},
    }
    for kind in ("wires", "boxes"):
        for name, value in (changes.get(kind) or {}).items():
            if value is None:
                data[kind].pop(name, None)
            else:
                data[kind][name] = value
    new, issues = parse_model(WiringEdits, data, WIRING_FILE)
    if new is None:
        return issues
    variants = dict(current.variants)
    if key is None:
        result = WiringFile(wires=new.wires, boxes=new.boxes, variants=variants)
    else:
        variants[key] = new
        keep_legacy = key != default_key  # pre-variant edits belong to the "as in project" variant
        result = WiringFile(
            wires=current.wires if keep_legacy else {},
            boxes=current.boxes if keep_legacy else {},
            variants={k: v for k, v in variants.items() if v.wires or v.boxes},
        )
    if not (result.wires or result.boxes or result.variants):
        path.unlink(missing_ok=True)
        return []
    path.write_text(dump_wiring_file(result), encoding="utf-8")
    return []


def dump_wiring_file(data: WiringFile) -> str:
    """wiring.yaml with variants: pre-variant edits (if any are left), then variants."""
    head = [
        "# Ручные правки проводки из просмотра (floorplan-engine view), мм модели, по вариантам",
        "# проводки (variants.<режим-трасса-разводка>). Удалить запись — вернуть автотрассу.",
    ]
    body: list[str] = []
    legacy = WiringEdits(wires=data.wires, boxes=data.boxes)
    if legacy.wires or legacy.boxes:
        body += _edit_lines(legacy, "")
    if data.variants:
        body.append("variants:")
        for key in sorted(data.variants):
            body.append(f"  {json.dumps(key)}:")
            body += _edit_lines(data.variants[key], "    ")
    return "\n".join(head + body) + "\n"


def dump_wiring_edits(edits: WiringEdits) -> str:
    """Edits of one variant (pre-variant wiring.yaml): one line per box and per line."""
    head = [
        "# Ручные правки проводки из просмотра (floorplan-engine view), мм модели.",
        "# Остальное строится автоматически; удалить запись — вернуть автотрассу.",
    ]
    return "\n".join(head + _edit_lines(edits, "")) + "\n"


def _edit_lines(edits: WiringEdits, indent: str) -> list[str]:
    """Indented edit lines: one line per box and per line, route points on one line."""

    def xy(p: tuple[float, float]) -> str:
        return f"[{p[0]:g}, {p[1]:g}]"

    def q(text: str) -> str:  # a JSON string is also a YAML string, with any characters
        return json.dumps(text, ensure_ascii=False)

    lines = []
    if edits.boxes:
        lines.append(f"{indent}boxes:")
        for bid, b in sorted(edits.boxes.items()):
            lines.append(
                f"{indent}  {q(bid)}: {{ room: {q(b.room)}, group: {q(b.group)}, at: {xy(b.at)} }}"
            )
    if edits.wires:
        lines.append(f"{indent}wires:")
        for wid, w in sorted(edits.wires.items(), key=lambda kv: _natural(kv[0])):
            path = ", ".join(xy(p) for p in w.path)
            lines.append(
                f"{indent}  {q(wid)}: {{ from: {q(w.from_)}, to: {q(w.to)}, path: [{path}] }}"
            )
    return lines


def _natural(key: str) -> tuple[str, int]:
    """wire_2 before wire_10."""
    head, _, tail = key.rpartition("_")
    return (head, int(tail)) if tail.isdigit() else (key, 0)


@dataclass
class EstimateResult:
    assessment: Assessment
    issues: list[Issue] = field(default_factory=list)  # price list errors, reasons for no estimate
    estimate: Estimate | None = None
    prices: Path | None = None  # price list used for the calculation (None means no prices)
    files: list[Path] = field(default_factory=list)


@dataclass
class PrintResult:
    assessment: Assessment
    issues: list[Issue] = field(default_factory=list)  # why there is no album
    pdf: Path | None = None
    dxf: Path | None = None  # DXF for the requested paper size (own size is out/project.dxf)
    paper: str = ""  # «A3»
    scale: float = 0.0  # 50 means 1:50
    checks: list[SheetCheck] = field(default_factory=list)

    @property
    def warnings(self) -> list[str]:
        return [w for c in self.checks for w in c.warnings()]


def print_project(
    project: Path, paper: SheetFormat = "auto", prices_from: PriceSource | None = None
) -> PrintResult:
    """PDF album of the sheets at full size (printing.py). paper="auto" keeps the set as built
    (out/project.dxf → out/album.pdf; an error if there is no build); a given paper size lays
    the sheets out again for it: out/print-A3.dxf and out/album-A3.pdf."""
    assessment = assess_project(project)
    result = PrintResult(assessment)
    out = project / OUT_DIR
    plan = assessment.report.plan
    if paper == "auto":
        dxf = out / PROJECT_FILE
        if not dxf.exists():
            result.issues.append(Issue(PROJECT_FILE, "", "нет сборки — сначала build"))
            return result
        doc, pdf = readfile(dxf), out / ALBUM_FILE
    else:
        if not assessment.plan_builds or plan is None:
            result.issues.append(Issue("room.yaml", "", "план не строится — см. check"))
            return result
        elec, prices, result.issues = _sheet_inputs(project, assessment, price_service(prices_from))
        sheet = plan.sheet.model_copy(update={"format": paper})
        doc = build_project_document(
            plan.model_copy(update={"sheet": sheet}),
            assessment.report.contours,
            elec,
            prices=prices,
            edits=assessment.report.wiring_edits,
            plumbing=plumbing_of(assessment),
        )
        result.dxf = out / f"print-{paper}.dxf"
        doc = save_checked(doc, result.dxf)
        pdf = out / f"album-{paper}.pdf"
    layouts = sheet_layouts(doc)
    if layouts:
        size = sorted(paper_size(layouts[0]))
        result.paper = next((n for n, f in FORMATS.items() if list(f) == size), "")
    result.scale = document_scale(doc)
    result.checks = check_sheets(doc)
    title = plan.name if plan is not None else project.name
    result.pdf = write_album(doc, pdf, title)
    return result


SEWER_ROUTES_FILE = "sewer-routes.json"  # sewer routes: pieces, zones, heights, errors
PLUMBING_ESTIMATE_FILES = (
    "plumbing-estimate.md",
    "plumbing-estimate.csv",
    "plumbing-estimate.xlsx",
)


def write_plumbing_estimate(
    project: Path,
    assessment: Assessment,
    net: Network,
    plumbing: Plumbing,
    prices: Prices,
    source: Path | None,
) -> list[Path]:
    """Plumbing estimate in out/: plumbing-estimate.md, .csv and .xlsx, the same as on the
    "Plumbing" sheet. Written by build."""
    plan = assessment.report.plan
    assert plan is not None
    lang = plan.language
    est = build_plumbing_estimate(net, plumbing, prices, lang)
    if prices.priced:
        notes = price_notes(est, prices, lang, f=source.name if source else PRICES_FILE, note=True)
    else:
        notes = [estimate_text("note_no_prices", lang, f=PRICES_FILE)]
    notes += [
        plumbing_estimate_text("note_pipes", lang, pct=round(PLUMBING_RESERVE * 100)),
        plumbing_estimate_text("note_input", lang),
        plumbing_estimate_text("note_excluded", lang),
    ]
    status = assessment.status(Stage.PLUMBING)
    if status is not None and status.open_questions:
        ids = ", ".join(q.id for q in status.open_questions)
        notes.append(plumbing_estimate_text("note_questions", lang, ids=ids))
    title = plumbing_estimate_text("title", lang, name=plan.name)
    out = project / OUT_DIR
    md, csv_, xlsx = (out / name for name in PLUMBING_ESTIMATE_FILES)
    return [
        write_markdown(est, md, title, notes, lang),
        write_csv(est, csv_),
        write_xlsx(est, xlsx, title, notes, lang),
    ]


def find_prices(project: Path) -> Path | None:
    """Estimate price list: the project's own (prices.yaml in its folder), otherwise the shared
    studio list (prices.yaml in the folder above the projects, next to studio.yaml); None if
    neither exists."""
    for path in (project / PRICES_FILE, project.parent / PRICES_FILE):
        if path.is_file():
            return path
    return None


def load_prices(path: Path) -> tuple[PriceList | None, list[Issue]]:
    """Project price list; errors come with a field path, an unknown item key is also an error."""
    data, issues = load_yaml(path)
    if data is None:
        return None, issues
    prices, issues = parse_model(PriceList, data, path.name)
    if prices is None:
        return None, issues
    keys = [k for k in unknown_keys(prices) if k not in PLUMBING_LINES]
    bad = [Issue(path.name, f"items.{k}", "нет такой позиции сметы") for k in keys]
    return (None, bad) if bad else (prices, [])


WORK_PREFIX = "work."  # the studio price page shows works (services); materials stay in prices.yaml
NEW_PRICES = (
    "# Общий прайс студии для сметы: берётся, если у проекта нет своего prices.yaml.\n"
    "# Цены — за единицу позиции; ключи — LINES в electrical/estimate.py.\n"
    "currency: грн\n"
    "items:\n"
)


def load_market(path: Path) -> tuple[MarketSample | None, list[Issue]]:
    """Market sample (market.yaml); no file — None without errors."""
    if not path.is_file():
        return None, []
    data, issues = load_yaml(path)
    if data is None:
        return None, issues
    return parse_model(MarketSample, data, path.name)


def price_page(root: Path, market_root: Path | None = None) -> dict[str, Any]:
    """Studio price page (viewer, GET /api/prices): electrical works in estimate order — the
    studio price from root/prices.yaml next to the market spread from market.yaml (in
    market_root, by default in root: the sample is shared by all studios), the period of the
    market prices and its sources. Errors of either file — in issues."""
    prices_path = root / PRICES_FILE
    own, issues = load_prices(prices_path) if prices_path.is_file() else (None, [])
    market, market_issues = load_market((market_root or root) / MARKET_FILE)
    issues = [*issues, *market_issues]
    rows = []
    for key, (section, unit, ru, uk) in LINES.items():
        if not key.startswith(WORK_PREFIX):
            continue
        price = own.price(key) if own is not None else None
        item = market.items.get(key) if market is not None else None
        spread = item_spread(market, key) if market is not None else None
        rows.append(
            {
                "key": key,
                "section": section,
                "unit": unit,
                "name": {"ru": ru, "uk": uk},
                "hint": HINTS.get(key),
                "price": price.price if price is not None else None,
                # no studio price — the estimate takes the price service's (a mock for now)
                "service": mock_price(key) if price is None else None,
                "market": None
                if item is None or spread is None
                else {
                    **spread.as_dict(),
                    "basis": item.basis,
                    "quotes": [
                        {"source": src, "price": q.price, "text": q.text}
                        for src, q in sorted(item.quotes.items(), key=lambda kv: kv[1].price)
                    ],
                },
            }
        )
    used = used_sources(market) if market is not None else set()
    return {
        "file": PRICES_FILE,
        "exists": prices_path.is_file(),
        "currency": own.currency if own is not None else "грн",
        "date": own.date if own is not None else "",
        "note": own.note if own is not None else "",
        "rows": rows,
        "market": None
        if market is None
        else {
            "region": market.region,
            "collected": market.collected,
            "currency": market.currency,
            "period": period(market, used).as_dict(),
            "sources": [
                {"id": k, **s.model_dump()} for k, s in market.sources.items() if k in used
            ],
        },
        "issues": [f"{i.file}: {i.path}: {i.message}" for i in issues],
    }


def save_prices(root: Path, changes: dict[str, Any]) -> list[Issue]:
    """Studio price page edits → root/prices.yaml: {"items": {key: price | None}, "date"?};
    only works (work.*), None removes the price. Comments and other keys of the file stay
    (estimate.edit_price_items). Errors come with a field path; the file then is unchanged."""
    path = root / PRICES_FILE
    items = changes.get("items", {})
    if not isinstance(items, dict):
        return [Issue(PRICES_FILE, "items", "ожидается словарь «ключ: цена»")]
    bad = []
    for key, value in items.items():
        if not key.startswith(WORK_PREFIX) or key not in LINES:
            bad.append(Issue(PRICES_FILE, f"items.{key}", "нет такой работы в смете"))
        elif value is not None and (
            isinstance(value, bool) or not isinstance(value, int | float) or value < 0
        ):
            bad.append(Issue(PRICES_FILE, f"items.{key}", "цена — число не меньше 0"))
    date = changes.get("date")
    if date is not None and not isinstance(date, str):
        bad.append(Issue(PRICES_FILE, "date", "ожидается строка"))
    if bad:
        return bad
    text = edit_price_items(path.read_text("utf-8") if path.is_file() else NEW_PRICES, items)
    if date is not None:
        line = f'date: "{date}"' if date else 'date: ""'
        text, n = re.subn(r"^date:.*$", line, text, count=1, flags=re.M)
        if not n:
            text = re.sub(r"^items:", f"{line}\nitems:", text, count=1, flags=re.M)
    data = yaml.safe_load(text)
    parsed, issues = parse_model(PriceList, data, PRICES_FILE)
    if parsed is None:
        return issues
    root.mkdir(parents=True, exist_ok=True)  # a new studio has no folder yet
    path.write_text(text, encoding="utf-8")
    return []


def estimate_project(
    project: Path, prices_path: Path | None = None, prices_from: PriceSource | None = None
) -> EstimateResult:
    """Electrical estimate: quantities from the model, prices from the project prices.yaml,
    otherwise from the shared studio list (find_prices) or from prices_path, on top of the price
    service (prices_from; None means the mock). Writes out/estimate.md, estimate.csv and
    estimate.xlsx."""
    assessment = assess_project(project)
    result = EstimateResult(assessment)
    report = assessment.report
    elec_status = assessment.status(Stage.ELECTRICAL)
    if not assessment.plan_builds or elec_status is None or not elec_status.status.builds:
        result.issues.append(Issue("electrical.yaml", "", "этап электрики не строится — см. check"))
        return result
    assert report.plan is not None and report.electrical is not None
    wiring = estimate_wiring(report.plan, report.contours, report.electrical, report.wiring_edits)
    if wiring is None:
        result.issues.append(Issue("electrical.yaml", "board", "нет щита или точек с группами"))
        return result
    path = prices_path or find_prices(project)
    own: PriceList | None = None
    if path is not None and path.exists():
        own, issues = load_prices(path)
        if own is None:
            result.issues += issues
            return result
        result.prices = path
    prices = Prices(own, price_service(prices_from))
    panel = build_panel(report.plan, report.electrical)
    result.estimate, result.files = write_estimate(
        project, assessment, wiring, report.electrical, prices, result.prices, panel
    )
    return result


def write_estimate(
    project: Path,
    assessment: Assessment,
    wiring: Wiring,
    elec: Electrical,
    prices: Prices,
    source: Path | None,
    panel: BoardPanel | None,
) -> tuple[Estimate, list[Path]]:
    """Estimate in out/: estimate.md, .csv and .xlsx (formulas), from the same quantities as the
    wiring sheet; the panel follows the "Panel" sheet set (panel). Written by both estimate
    and build."""
    assert assessment.report.plan is not None
    plan = assessment.report.plan
    est = build_estimate(wiring, elec, prices, plan.language, panel)
    notes = _estimate_notes(assessment, est, wiring, elec, prices, source)
    title = estimate_text("title", plan.language, name=plan.name)
    out = project / OUT_DIR
    files = [
        write_markdown(est, out / ESTIMATE_MD, title, notes, plan.language),
        write_csv(est, out / ESTIMATE_CSV),
        write_xlsx(est, out / ESTIMATE_XLSX, title, notes, plan.language),
    ]
    return est, files


def _estimate_notes(
    assessment: Assessment,
    est: Estimate,
    wiring: Wiring,
    elec: Electrical,
    prices: Prices,
    source: Path | None,
) -> list[str]:
    """Where prices come from, what assumptions the quantities include and what the estimate
    leaves out.
    """
    assert assessment.report.plan is not None
    lang = assessment.report.plan.language
    if prices.priced:
        notes = price_notes(est, prices, lang, f=source.name if source else PRICES_FILE, note=True)
    else:
        notes = [estimate_text("note_no_prices", lang, f=PRICES_FILE)]
    notes += [
        estimate_text("note_cable", lang, pct=round(RESERVE * 100)),
        estimate_text("note_chases", lang, d=f"{CHASE_SHARE:g}", k=CHASE_CABLES, n=CHASE_NARROW),
        estimate_text("note_holes", lang, k=HOLE_CABLES),
        estimate_text("note_fixing", lang, step=f"{FIXING_STEP:g}"),
        estimate_text("note_crimp", lang),
    ]
    if any(ln.key.startswith("conduit.") for ln in est.lines):
        notes.append(estimate_text("note_conduit", lang))
    if elec.board is not None:
        notes.append(estimate_text("note_panel", lang))
        notes.append(
            estimate_text(
                "note_board_tail", lang, h=f"{elec.board.height:g}", e=f"{END_ALLOWANCE:g}"
            )
        )
    if prices.own is not None and prices.own.board_kit and source is not None:
        keys = ", ".join(k.value for k in DeviceKind)
        notes.append(estimate_text("note_board_kit", lang, f=source.name, keys=keys))
    with_boxes = {b.group for b in wiring.boxes}
    direct = sorted({r.group for r in wiring.runs} - with_boxes, key=group_key)
    if direct:
        notes.append(estimate_text("note_direct", lang, groups=", ".join(direct)))
    wet = sum(1 for b in wiring.boxes if b.wet)
    if wet:
        notes.append(estimate_text("note_wet", lang, n=wet))
    notes.append(estimate_text("note_excluded", lang))
    if wiring.height_assumed:
        notes.append(estimate_text("note_height", lang))
    status = assessment.status(Stage.ELECTRICAL)
    if status is not None and status.open_questions:
        ids = ", ".join(q.id for q in status.open_questions)
        notes.append(estimate_text("note_questions", lang, ids=ids))
    return notes
