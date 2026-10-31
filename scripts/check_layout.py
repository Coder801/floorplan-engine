"""Раскладка листов собранных проектов — кодом, без картинок: формат, масштаб, переполнение
и таблицы поверх плана.

    uv run python scripts/check_layout.py nahirna-16 vavilovykh-11

Код выхода 1 — есть переполненный лист или таблица на плане.
"""

from __future__ import annotations

import sys
from pathlib import Path

from floorplan_engine.model.scale import drawing_scale
from floorplan_engine.pipeline import assess_project, find_prices, load_prices
from floorplan_engine.sheets.document import choose_paper_and_scale
from floorplan_engine.sheets.layout import place, view_size
from floorplan_engine.sheets.stages import draw_stages


def check(project: Path) -> bool:
    report = assess_project(project).report
    assert report.plan is not None, f"{project}: план не строится"
    prices_path = find_prices(project)
    prices = load_prices(prices_path)[0] if prices_path is not None else None
    paper, scale = choose_paper_and_scale(report.plan, report.contours, report.electrical, prices)
    ok = True
    with drawing_scale(scale):
        doc, specs = draw_stages(report.plan, report.contours, report.electrical, prices)
        for spec in specs:
            view = view_size(doc, spec)
            p = place(view, spec, paper)
            vx0, vy1 = p.view_at.x, p.view_at.y
            vx1, vy0 = vx0 + view[0], vy1 - view[1]
            on_plan = [
                panel
                for panel, at in p.panels
                if not (
                    at.x >= vx1
                    or at.x + panel.width <= vx0
                    or at.y <= vy0
                    or at.y - panel.height >= vy1
                )
            ]
            fine = p.layout.fits and not on_plan
            ok = ok and fine
            state = "ok" if fine else ("переполнен" if not p.layout.fits else "таблица на плане")
            print(f"{project.name}: {spec.tab_key} — {paper[0]} 1:{scale:g} — {state}")
    return ok


if __name__ == "__main__":
    results = [check(Path("projects") / name) for name in sys.argv[1:]]
    sys.exit(0 if all(results) else 1)
