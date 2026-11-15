from __future__ import annotations

from floorplan_engine.model.scale import DEFAULT_SCALE, SCALES
from floorplan_engine.model.schema import Plan
from floorplan_engine.sheets.document import choose_paper_and_scale
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan


def _rect(w: float, h: float, fmt: str = "auto") -> Plan:
    plan = make_plan([{"length": w}, {"length": h}, {"length": w}, {"length": h}])
    return plan.model_copy(update={"sheet": plan.sheet.model_copy(update={"format": fmt})})


def test_a_small_room_is_drawn_at_the_set_scale_on_small_paper() -> None:
    # Before 2026-11-15 the scale was picked to fill the sheet; now one scale (1:25) always
    plan = _rect(3000, 4000)
    issues, contours = validate_plan(plan)
    assert not issues
    paper, scale = choose_paper_and_scale(plan, contours, None)
    assert scale == DEFAULT_SCALE
    assert paper[0] in ("A4", "A3", "A2")


def test_a_plan_that_does_not_fit_the_paper_goes_to_a_smaller_scale() -> None:
    # A4 portrait: 12 m is 480 mm at 1:25 and 240 mm at 1:50, wider than the sheet; 120 mm at 1:100
    plan = _rect(12000, 8000, "A4")
    issues, contours = validate_plan(plan)
    assert not issues
    paper, scale = choose_paper_and_scale(plan, contours, None)
    assert (paper[0], scale) == ("A4", SCALES[-1])
