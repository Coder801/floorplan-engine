"""Work stages of plumbing (plumbing/stages.py): every estimate item in one stage, own acceptance
criteria, the pressure test after the water pipes."""

from __future__ import annotations

from floorplan_engine.electrical.estimate import Estimate, Line
from floorplan_engine.electrical.stages import stage_by_key, unstaged
from floorplan_engine.plumbing.estimate import LINES, unit_text
from floorplan_engine.plumbing.stages import load_stages, plumbing_draft


def _estimate(*rows: tuple[str, float, float | None]) -> Estimate:
    lines = []
    for key, qty, price in rows:
        section, unit, ru, _ = LINES[key]
        lines.append(Line(section, key, ru, unit_text(unit, "ru"), qty, price))
    return Estimate(tuple(lines), "грн")


def test_template_covers_every_estimate_item_once() -> None:
    catalog = load_stages()
    assert unstaged(catalog, LINES) == []
    staged = stage_by_key(catalog, LINES)
    assert set(staged) == set(LINES)
    assert staged["water.tee20_16"] == "water" and staged["sewer.revision"] == "sewer"
    assert all(s.result for s in catalog.stages)  # no work scope: every stage has its own


def test_draft_tasks_and_dependencies() -> None:
    est = _estimate(
        ("water.pipe16", 20.0, 75.0),
        ("work.water_pipe", 18.0, 120.0),
        ("work.pressure_test", 1.0, None),
    )
    water, pressure = plumbing_draft(est, "uk")
    assert (water.key, water.order, water.after) == ("plumbing.water", 3, ())
    assert water.photo == "required" and water.title == "Водопровід"
    assert (water.work_total, water.material_total) == (2160.0, 1500.0)
    assert pressure.after == ("plumbing.water",) and pressure.unpriced == 1
    assert pressure.result and "манометр" in pressure.result[0]
