"""Debug trace of a project's wiring: every line with its last search, the SVG and the errors."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from shapely.geometry import Polygon, box

from floorplan_engine.electrical.routing import Grid, RouteTrace
from floorplan_engine.electrical.wiring_model import Run
from floorplan_engine.model.geometry import Vec
from floorplan_engine.pipeline.trace import (
    TracedLine,
    TraceError,
    line_note,
    trace_file,
    trace_svg,
    trace_wiring,
)
from tests.electrical.test_variants import _project


def test_every_line_has_its_last_search(tmp_path: Path) -> None:
    tr = trace_wiring(_project(tmp_path))
    assert tr.lines and len(tr.lines) == len(tr.wiring.runs)
    for t in tr.lines:
        assert t.routed >= 1 and t.search is not None
        assert t.search.path == t.run.path  # no manual routes: the search is what is drawn
        assert t.run.id in line_note(t)


def test_svg_shows_the_focus_line_with_its_grid(tmp_path: Path) -> None:
    tr = trace_wiring(_project(tmp_path))
    first = tr.lines[0]
    focus = [t for t in tr.lines if t.matches([first.run.id], [], [])]
    assert focus == [first]
    svg = trace_svg(tr, focus, cost=True)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert '<g id="grid">' in svg and "hsl(" in svg
    assert first.run.id in svg
    overview = trace_svg(tr, [])
    assert '<g id="grid">' not in overview


def test_matches_by_group_and_line_end(tmp_path: Path) -> None:
    tr = trace_wiring(_project(tmp_path))
    run = tr.lines[0].run
    assert tr.lines[0].matches([], [run.group], [])
    assert tr.lines[0].matches([], [], [run.target])
    assert not tr.lines[0].matches(["wire_999"], ["нет"], ["нет"])


def test_trace_file_names_the_selection(tmp_path: Path) -> None:
    assert trace_file(tmp_path, []).name == "trace.svg"
    assert trace_file(tmp_path, ["wire_3", "QF2"]) == tmp_path / "out/debug/trace-wire_3-QF2.svg"


def test_no_electrical_is_an_error(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "electrical.yaml").unlink()
    with pytest.raises(TraceError, match="Электрику"):
        trace_wiring(project)


def test_no_plan_is_an_error(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "room.yaml").write_text(yaml.safe_dump({"name": "x"}), "utf-8")
    with pytest.raises(TraceError, match="План"):
        trace_wiring(project)


def test_line_note_tells_wall_from_opening_and_ready_hole() -> None:
    """The summary says how the line crossed into the next room: through a drillable wall, above
    an opening (a band on the ceiling, decision 2026-11-23) or into a hole a line before it made."""
    area = box(0, 0, 3000, 1000)
    grid = Grid.of(area)
    cells = tuple(grid.center(grid.nearest_free(Vec(x, 500))) for x in range(250, 2800, 100))
    wall, opening = box(1000, 0, 1100, 1000), box(2000, 0, 2100, 1000)
    run = Run("wire_1", "QF1", "3x2.5", False, "board", "s1", cells, 2500.0, 0.0, 0.0, 0.0)

    def note(
        walls: tuple[Polygon, ...], passes: tuple[Polygon, ...], opened: frozenset[int]
    ) -> str:
        g = Grid(grid.x0, grid.y0, grid.nx, grid.ny, grid.free, grid.inner, opened=opened)
        search = RouteTrace(
            area, walls, g, 0, 1, {}, cells[0], cells[-1], cells, cells, 2500.0, False, passes
        )
        return line_note(TracedLine(run, search, 1, False))

    plain = note((), (), frozenset())
    assert "сквозь стену" not in plain and "через проём" not in plain and "отверстию" not in plain
    assert "сквозь стену" in note((wall,), (), frozenset())
    assert "через проём" in note((), (opening,), frozenset())
    both = note((wall,), (opening,), frozenset({grid.index(cells[8])}))
    assert "сквозь стену" in both and "через проём" in both and "по готовому отверстию" in both
