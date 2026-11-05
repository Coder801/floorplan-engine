"""Project pipeline without screen output: assessment, report, DXF build, artifact and PNG.

Shared by the CLI and the service: the CLI prints the result, the service stores it in the
project state.
"""

from __future__ import annotations

from floorplan_engine.pipeline.answers import MAX_ANSWER_TEXT, AnswerSaved, save_answer
from floorplan_engine.pipeline.assessment import (
    Assessment,
    AuditError,
    assess_project,
    plumbing_of,
    price_service,
    save_checked,
    write_report,
)
from floorplan_engine.pipeline.build import BuildResult, build_project, render_sheets
from floorplan_engine.pipeline.estimates import (
    EstimateResult,
    estimate_project,
    write_estimate,
    write_plumbing_estimate,
)
from floorplan_engine.pipeline.files import (
    ALBUM_FILE,
    ARTIFACT_FILE,
    CHASES_FILE,
    LOADS_FILE,
    OUT_DIR,
    PLUMBING_ESTIMATE_FILES,
    PROJECT_FILE,
    SEWER_ROUTES_FILE,
    SHEETS_DIR,
    STICKERS_FILE,
    WIRING_JOURNAL_FILE,
)
from floorplan_engine.pipeline.prices import (
    NEW_PRICES,
    WORK_PREFIX,
    find_prices,
    load_market,
    load_prices,
    price_page,
    save_prices,
)
from floorplan_engine.pipeline.printing import PrintResult, print_project
from floorplan_engine.pipeline.variants import save_variant, variant_block
from floorplan_engine.pipeline.wiring_edits import (
    dump_wiring_edits,
    dump_wiring_file,
    save_wiring_edits,
)

__all__ = [
    "ALBUM_FILE",
    "ARTIFACT_FILE",
    "CHASES_FILE",
    "LOADS_FILE",
    "MAX_ANSWER_TEXT",
    "NEW_PRICES",
    "OUT_DIR",
    "PLUMBING_ESTIMATE_FILES",
    "PROJECT_FILE",
    "SEWER_ROUTES_FILE",
    "SHEETS_DIR",
    "STICKERS_FILE",
    "WIRING_JOURNAL_FILE",
    "WORK_PREFIX",
    "AnswerSaved",
    "Assessment",
    "AuditError",
    "BuildResult",
    "EstimateResult",
    "PrintResult",
    "assess_project",
    "build_project",
    "dump_wiring_edits",
    "dump_wiring_file",
    "estimate_project",
    "find_prices",
    "load_market",
    "load_prices",
    "plumbing_of",
    "price_page",
    "price_service",
    "print_project",
    "render_sheets",
    "save_answer",
    "save_checked",
    "save_prices",
    "save_variant",
    "save_wiring_edits",
    "variant_block",
    "write_estimate",
    "write_plumbing_estimate",
    "write_report",
]
