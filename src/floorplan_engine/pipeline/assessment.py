"""Project assessment: validation, stage statuses, the report and a checked DXF save."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ezdxf.document import Drawing
from ezdxf.filemanagement import readfile

from floorplan_engine.electrical.estimate import (
    PriceSource,
)
from floorplan_engine.electrical.pricing import MockPriceService
from floorplan_engine.model.intake import (
    Stage,
)
from floorplan_engine.model.plumbing import Plumbing
from floorplan_engine.plumbing.estimate import MOCK_PRICES as PLUMBING_MOCK_PRICES
from floorplan_engine.validation.assess import STAGE_FILES, StageResult, assess
from floorplan_engine.validation.issues import (
    Issue,
)
from floorplan_engine.validation.report import REPORT_JSON, REPORT_MD, render_markdown, to_json
from floorplan_engine.validation.validate import Report, validate_project


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


def assess_project(project: Path) -> Assessment:
    report = validate_project(project)
    return Assessment(report, assess(report))


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
