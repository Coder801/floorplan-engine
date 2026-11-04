"""Printing: a PDF album of the sheets, at the paper size the project chose or at a given one."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ezdxf.filemanagement import readfile

from floorplan_engine.drawing.titleblock import FORMATS
from floorplan_engine.electrical.estimate import (
    PriceSource,
)
from floorplan_engine.model.schema import SheetFormat
from floorplan_engine.pipeline.assessment import (
    Assessment,
    assess_project,
    plumbing_of,
    price_service,
    save_checked,
)
from floorplan_engine.pipeline.files import ALBUM_FILE, OUT_DIR, PROJECT_FILE
from floorplan_engine.pipeline.prices import sheet_inputs
from floorplan_engine.sheets.document import build_project_document, document_scale
from floorplan_engine.sheets.preview import paper_size, sheet_layouts
from floorplan_engine.sheets.printing import SheetCheck, check_sheets, write_album
from floorplan_engine.validation.issues import (
    Issue,
)


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
        elec, prices, result.issues = sheet_inputs(project, assessment, price_service(prices_from))
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
