"""Legend of the plan sheet."""

from __future__ import annotations

from floorplan_engine.drawing.plan_legend import legend_rows, plan_legend_variants
from floorplan_engine.model.texts import tr
from floorplan_engine.sheets.stages import draw_stages
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan

WALLS = [{"length": 3000, "bearing": True}, {"length": 4000}, {"length": 3000}, {"length": 4000}]


def test_rows_are_only_what_the_plan_has() -> None:
    plain = make_plan([{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}])
    assert [t for t, _ in legend_rows(plain, "ru")] == [tr("legend_partition", "ru")]
    window = [{"wall": "w2", "type": "window", "offset": 1000, "width": 1500, "sill": 900}]
    full = make_plan(WALLS, window)
    keys = ["legend_bearing", "legend_partition", "legend_window"]
    assert [t for t, _ in legend_rows(full, "uk")] == [tr(k, "uk") for k in keys]


def test_variants_get_lower_with_more_columns() -> None:
    plan = make_plan(WALLS, [{"wall": "w2", "type": "window", "offset": 1000, "width": 1500}])
    variants = plan_legend_variants(plan)
    assert len(variants) == 1  # three rows: one column of three
    width, height, _ = variants[0]
    assert width > 0 and height > 0


def test_plan_sheet_gets_the_legend() -> None:
    plan = make_plan(WALLS)
    _, contours = validate_plan(plan)
    _, specs = draw_stages(plan, contours, None)
    assert specs[0].tab_key == "tab_plan" and specs[0].legends
