"""Проводка без плана: сечение из марки, ширина штробы, длины линий и итоги по маркам."""

from __future__ import annotations

import pytest

from floorplan_engine.geometry import Vec
from floorplan_engine.wiring import CHASE_NARROW, Chase, Run, Wiring, section


@pytest.mark.parametrize(
    ("mark", "value"),
    [
        ("3x1.5", 1.5),
        ("3x2,5", 2.5),
        ("3х6", 6.0),  # кириллическая «х»
        ("5×10", 10.0),
        ("3 x 4", 4.0),
        ("ВВГнг-LS 3x2.5", 2.5),
        ("UTP", 0.0),
        ("", 0.0),
        ("3x", 0.0),
    ],
)
def test_section_from_mark(mark: str, value: float) -> None:
    assert section(mark) == value


def _chase(cables: int, length: float = 1000.0) -> Chase:
    return Chase("point", "r", "w1", 500.0, length, cables)


@pytest.mark.parametrize(
    ("cables", "wide"), [(1, False), (CHASE_NARROW, False), (CHASE_NARROW + 1, True)]
)
def test_chase_wide_above_narrow_limit(cables: int, wide: bool) -> None:
    assert _chase(cables).wide is wide


def _run(mark: str, plan: float, start: float, end: float, ends: float) -> Run:
    return Run(
        id="r1",
        group="1",
        mark=mark,
        mark_assumed=False,
        source="board",
        target="p1",
        path=(Vec(0, 0), Vec(1000, 0)),
        plan_mm=plan,
        rise_start_mm=start,
        rise_end_mm=end,
        ends_mm=ends,
    )


def test_run_vertical_and_total_length() -> None:
    r = _run("3x2.5", plan=4000, start=150, end=2400, ends=300)
    assert r.vertical_mm == 2550
    assert r.length_mm == 6850


def test_run_ceiling_point_has_no_drop() -> None:
    r = _run("3x1.5", plan=1000, start=150, end=0, ends=0)
    assert r.vertical_mm == 150 and r.length_mm == 1150


def _wiring(runs: tuple[Run, ...] = (), chases: tuple[Chase, ...] = ()) -> Wiring:
    return Wiring(2700.0, False, (), runs, chases=chases)


def test_chase_lengths_split_by_width() -> None:
    w = _wiring(chases=(_chase(1, 1000), _chase(2, 500), _chase(3, 700), _chase(4, 300)))
    assert w.chase_length(wide=False) == 1500
    assert w.chase_length(wide=True) == 1000
    assert w.chase_mm == 2500


def test_by_mark_sums_meters_sorted_by_mark() -> None:
    w = _wiring(
        runs=(
            _run("3x2.5", 1000, 0, 0, 0),
            _run("3x1.5", 2000, 500, 0, 0),
            _run("3x2.5", 1500, 0, 0, 0),
        )
    )
    assert list(w.by_mark()) == ["3x1.5", "3x2.5"]
    assert w.by_mark() == pytest.approx({"3x1.5": 2.5, "3x2.5": 2.5})


def test_empty_wiring_totals_are_zero() -> None:
    w = _wiring()
    assert w.chase_mm == 0 and w.chase_length(wide=True) == 0 and w.by_mark() == {}
