"""Estimate files of the electrical and plumbing stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from floorplan_engine.electrical.chases import CHASE_CABLES, CHASE_SHARE, HOLE_CABLES
from floorplan_engine.electrical.estimate import (
    ESTIMATE_CSV,
    ESTIMATE_MD,
    ESTIMATE_XLSX,
    FIXING_STEP,
    PRICES_FILE,
    Estimate,
    PriceList,
    PriceSource,
    build_estimate,
    write_csv,
    write_markdown,
    write_xlsx,
)
from floorplan_engine.electrical.estimate import text as estimate_text
from floorplan_engine.electrical.groups import group_key
from floorplan_engine.electrical.panel import BoardPanel, build_panel
from floorplan_engine.electrical.pricing import Prices, price_notes
from floorplan_engine.electrical.wiring import END_ALLOWANCE, RESERVE, estimate_wiring
from floorplan_engine.electrical.wiring_model import CHASE_NARROW, Wiring
from floorplan_engine.electrical.work_scope import (
    WORK_SCOPE_MD,
    scope_entries,
    scope_sheet,
    write_scope_markdown,
)
from floorplan_engine.electrical.work_scope import text as scope_text
from floorplan_engine.model.intake import (
    Stage,
)
from floorplan_engine.model.panel_catalog import DeviceKind
from floorplan_engine.model.plumbing import Plumbing
from floorplan_engine.model.schema import Electrical
from floorplan_engine.pipeline.assessment import Assessment, assess_project, price_service
from floorplan_engine.pipeline.files import OUT_DIR, PLUMBING_ESTIMATE_FILES
from floorplan_engine.pipeline.prices import find_prices, load_prices
from floorplan_engine.plumbing.estimate import RESERVE as PLUMBING_RESERVE
from floorplan_engine.plumbing.estimate import build_estimate as build_plumbing_estimate
from floorplan_engine.plumbing.estimate import text as plumbing_estimate_text
from floorplan_engine.plumbing.network import Network
from floorplan_engine.validation.issues import (
    Issue,
)


@dataclass
class EstimateResult:
    assessment: Assessment
    issues: list[Issue] = field(default_factory=list)  # price list errors, reasons for no estimate
    estimate: Estimate | None = None
    prices: Path | None = None  # price list used for the calculation (None means no prices)
    files: list[Path] = field(default_factory=list)


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
    wiring sheet; the panel follows the "Panel" sheet set (panel). Next to it the work scope of
    the estimate's work items (electrical/work_scope.py): work-scope.md and a sheet in the
    workbook. Written by both estimate and build."""
    assert assessment.report.plan is not None
    plan = assessment.report.plan
    lang = plan.language
    est = build_estimate(wiring, elec, prices, lang, panel)
    notes = _estimate_notes(assessment, est, wiring, elec, prices, source)
    title = estimate_text("title", lang, name=plan.name)
    scope = scope_entries(est, lang)
    left_out = [estimate_text("note_excluded", lang)]
    out = project / OUT_DIR
    files = [
        write_markdown(est, out / ESTIMATE_MD, title, notes, lang),
        write_csv(est, out / ESTIMATE_CSV),
        write_xlsx(
            est, out / ESTIMATE_XLSX, title, notes, lang, scope_sheet(scope, left_out, lang)
        ),
        write_scope_markdown(
            scope, out / WORK_SCOPE_MD, scope_text("title", lang, name=plan.name), left_out, lang
        ),
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
        estimate_text("note_holes", lang, k=HOLE_CABLES),
        estimate_text("note_fixing", lang, step=f"{FIXING_STEP:g}"),
        estimate_text("note_crimp", lang),
    ]
    if any(ln.key.startswith("work.chase") for ln in est.lines):
        notes.append(
            estimate_text("note_chases", lang, d=f"{CHASE_SHARE:g}", k=CHASE_CABLES, n=CHASE_NARROW)
        )
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
    notes.append(scope_text("note_scope", lang, f=WORK_SCOPE_MD, s=scope_text("sheet", lang)))
    if wiring.height_assumed:
        notes.append(estimate_text("note_height", lang))
    status = assessment.status(Stage.ELECTRICAL)
    if status is not None and status.open_questions:
        ids = ", ".join(q.id for q in status.open_questions)
        notes.append(estimate_text("note_questions", lang, ids=ids))
    return notes
