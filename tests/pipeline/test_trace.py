"""Debug trace of a project's wiring: every line with its last search, the SVG and the errors."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from floorplan_engine.pipeline.trace import (
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
