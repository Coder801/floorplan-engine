"""Tests of electrical/sleeves.py: cable passes through walls, one PVC sleeve each, and their
firestop foam (decisions 2026-11-28)."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from floorplan_engine.drawing.wiring import wiring_notes
from floorplan_engine.electrical.estimate import build_estimate
from floorplan_engine.electrical.estimate.quantities import quantities
from floorplan_engine.electrical.mounting import cable_area
from floorplan_engine.electrical.price_list import PriceList
from floorplan_engine.electrical.sleeves import (
    FOAM_CAN_ML,
    FOAM_YIELD_L,
    LOW_CABLE_OD_OTHER,
    SLEEVE_INNER,
    SLEEVE_OUT_MM,
    cable_passes,
    capacity,
    fit_sleeves,
    foam_cans,
    foam_litres,
    low_cable_area,
    low_cable_od,
    section_sleeve,
    sleeve_counts,
    sleeve_lengths,
    sleeve_size,
    with_sleeves,
)
from floorplan_engine.electrical.wiring import RESERVE
from floorplan_engine.electrical.wiring_model import Hole, Run, Sleeve, Wiring
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.model.texts import CABLE_PASS_WORDS, plural
from floorplan_engine.pipeline.estimates import _low_sizes, _pass_notes
from tests.electrical.conftest import two_rooms_with_door, wiring_of


def _run(rid: str, mark: str = "3x2.5", circuit: str = "power") -> Run:
    return Run(
        id=rid,
        group="QF1",
        mark=mark,
        mark_assumed=False,
        source="board",
        target=f"p_{rid}",
        path=(Vec(0, 0), Vec(1000, 0)),
        plan_mm=1000.0,
        rise_start_mm=0.0,
        rise_end_mm=0.0,
        ends_mm=0.0,
        circuit="low" if circuit == "low" else "power",
    )


def _area(mark: str) -> float:
    area = cable_area(mark)
    assert area is not None
    return area


def test_sleeve_size_by_fill_of_the_inner_section() -> None:
    """Cables take at most 40 % of the inner cross-section: 17.6 mm in a Ø20, 22.7 in a Ø25,
    36.7 in a Ø40 (DKC light smooth pipe)."""
    assert SLEEVE_INNER == {20: 17.6, 25: 22.7, 40: 36.7}
    assert capacity(20) == pytest.approx(0.4 * math.pi / 4 * 17.6**2)
    assert sleeve_size(capacity(20)) == 20
    assert sleeve_size(capacity(20) + 1) == 25
    assert sleeve_size(capacity(25) + 1) == 40
    assert sleeve_size(capacity(40) * 2) == 40  # too much for one: the largest


def test_one_cable_in_a_small_sleeve_two_in_a_larger() -> None:
    (one,) = fit_sleeves([_run("a", "3x1.5")])
    assert (one.diameter, one.runs) == (20, ("a",))
    assert one.cables_mm2 == pytest.approx(_area("3x1.5"))
    (two,) = fit_sleeves([_run("a", "3x1.5"), _run("b", "3x1.5")])
    assert two.diameter == 25 and two.runs == ("a", "b")  # 2 × 49.7 mm² > 97 mm² of a Ø20


def test_more_than_one_largest_sleeve_holds_goes_to_the_next_pass() -> None:
    """Nine 3×2.5: six fit one Ø40 (423 mm²), the other three go through the next pass beside it
    (no core-drilled hole), which by their 184 mm² is a Ø40 too; first fit, every run once."""
    runs = [_run(f"r{k}") for k in range(9)]
    sleeves = fit_sleeves(runs)
    assert [s.diameter for s in sleeves] == [40, 40]
    assert [len(s.runs) for s in sleeves] == [6, 3]
    assert sorted(i for s in sleeves for i in s.runs) == sorted(r.id for r in runs)
    assert all(s.cables_mm2 <= capacity(s.diameter) for s in sleeves)
    assert fit_sleeves(runs) == sleeves  # deterministic


def test_thickest_cable_first() -> None:
    """A 3×6 goes in first: with 3×1.5 and 3×2.5 it is the one that sets the first sleeve."""
    runs = [_run("thin", "3x1.5"), _run("thick", "3x6"), _run("mid", "3x2.5")]
    (sleeve,) = fit_sleeves(runs)
    assert sleeve.diameter == 40  # 49.7 + 90.7 + 61.3 = 201.7 mm² > Ø25
    assert sleeve.runs == ("thin", "thick", "mid")


def test_low_voltage_cables_share_a_sleeve_by_their_outer_diameter() -> None:
    """Decision 2026-11-28: internet and TV of one crossing go together, by the circle of their
    typical outer Ø (UTP ≈ 6 mm, RG-6 ≈ 7 mm), with the same 40 % fill: 28.3 + 38.5 mm² in one
    Ø20."""
    assert (low_cable_od("UTP cat.6"), low_cable_od("FTP cat.5e"), low_cable_od("RG-6")) == (
        6.0,
        6.0,
        7.0,
    )
    assert low_cable_od("КСПВ 4x0.5") == LOW_CABLE_OD_OTHER == 7.0  # another mark: the larger
    runs = [_run("utp", "UTP cat.6", "low"), _run("tv", "RG-6", "low")]
    (sleeve,) = fit_sleeves(runs)
    assert (sleeve.diameter, sleeve.runs, sleeve.by_section) == (20, ("utp", "tv"), False)
    assert sleeve.cables_mm2 == pytest.approx(math.pi / 4 * (6.0**2 + 7.0**2))


def test_low_voltage_overflow_goes_to_the_next_sleeve() -> None:
    """Sixteen UTP: fourteen fill one Ø40 (14 × 28.3 = 396 of 423 mm²), two go in a Ø20 beside
    it."""
    runs = [_run(f"u{k}", "UTP cat.6", "low") for k in range(16)]
    sleeves = fit_sleeves(runs)
    assert [(s.diameter, len(s.runs)) for s in sleeves] == [(40, 14), (20, 2)]
    assert all(s.cables_mm2 <= capacity(s.diameter) for s in sleeves)
    assert 15 * low_cable_area("UTP cat.6") > capacity(40)


def test_power_and_low_voltage_never_share_a_sleeve() -> None:
    """A 12 V LED line from the panel lies with the power cables (Run.lay)."""
    led = replace(_run("led", "3x1.5", "low"), led=True)
    runs = [_run("p", "3x1.5"), _run("utp", "UTP cat.6", "low"), led]
    sleeves = fit_sleeves(runs)
    assert [s.runs for s in sleeves] == [("p", "led"), ("utp",)]


def test_thick_cable_without_sizes_takes_the_sleeve_of_its_conduit() -> None:
    """A 3×10 (loads.cable_for goes up to 16 mm²) has a cross-section but no studio size
    (mounting.FLAT_CABLE): not a Ø20 like a cable with no section, but alone in the sleeve of its
    conduit — Ø32, no such sleeve, so a Ø40 — marked for the estimate note."""
    assert cable_area("3x10") is None
    assert section_sleeve("3x10") == section_sleeve("5x16") == 40
    assert section_sleeve("3x0.75") == 20  # a thin one: its Ø20 conduit
    runs = [_run("thin", "3x2.5"), _run("thick", "3x10"), _run("odd", "ВВГнг")]
    assert fit_sleeves(runs) == (
        Sleeve(20, _area("3x2.5"), ("thin",)),
        Sleeve(40, 0.0, ("thick",), by_section=True),
        Sleeve(20, 0.0, ("odd",)),  # no cross-section at all: a Ø20 alone, as before
    )


def test_pass_notes_name_the_guessed_sleeves_and_assumed_walls() -> None:
    w, _ = _door_wiring()
    assert _pass_notes(w, 200.0, "ru") == []  # sized cables, a written partition
    (hole,) = w.holes
    big = replace(w.runs[0], id="big", mark="3x10")
    guessed = Hole(
        "x", 1, runs=("big",), wall_mm=200.0, wall_assumed=True, sleeves=fit_sleeves([big])
    )
    w = Wiring(w.ceiling_height, False, w.boxes, (*w.runs, big), holes=(hole, guessed))
    section, wall = _pass_notes(w, 200.0, "ru")
    assert section.startswith("Кабель 3×10 — Ø40: наружного размера нет в справочнике студии")
    assert wall.startswith("Толщина стены в местах кабельных проходок (1 шт) в room.yaml не")
    assert "200 мм (допущение)" in wall
    assert _pass_notes(w, 200.0, "uk")[1].endswith("200 мм (припущення)")
    assert _low_sizes() == "UTP ≈ 6 мм, RG-6 ≈ 7 мм"  # the passes note names the typical sizes


def test_pass_through_a_wall_without_thickness_is_an_assumption() -> None:
    """The partition has no thickness of its own: the default one, marked assumed (the length
    of the sleeves and the foam come from it)."""
    plan = two_rooms_with_door()
    rooms = [
        r.model_copy(update={"walls": [w.model_copy(update={"thickness": None}) for w in r.walls]})
        for r in plan.rooms
    ]
    plan = Plan.model_validate(
        {**plan.model_dump(exclude_unset=True), "default_wall_thickness": 100}
        | {"rooms": [r.model_dump(exclude_unset=True) for r in rooms]}
    )
    _, elec = _door_wiring()
    (hole,) = wiring_of(plan, elec).holes
    assert (hole.wall_mm, hole.wall_assumed) == (100.0, True)
    written, _ = _door_wiring()
    assert not written.holes[0].wall_assumed


def test_foam_by_free_section_times_the_wall_not_the_sleeve() -> None:
    sleeve = Sleeve(20, _area("3x1.5"), ("a",))
    hole = Hole("door", 1, runs=("a",), wall_mm=100.0, sleeves=(sleeve,))
    free = math.pi / 4 * 17.6**2 - _area("3x1.5")
    assert foam_litres([hole]) == pytest.approx(free * 100 / 1e6)  # not the 120 mm sleeve
    wiring = Wiring(2700.0, False, (), (), holes=(hole,))
    assert foam_cans(wiring) == 1  # at least one can with a sleeve
    assert foam_cans(Wiring(2700.0, False, (), ())) == 0
    # Decision 2026-11-28: fire-rated mounting foam B1, a 750 ml can at 42 l — the lowest yield
    # the makers state (Tytan B1 42 l, Penosil up to 45, Lacrysil up to 50)
    assert (FOAM_CAN_ML, FOAM_YIELD_L) == (750, 42.0)
    # Fifty empty Ø40 through a metre of wall: 52.9 l, more than one can
    big = Hole("w", 50, runs=(), wall_mm=1000.0, sleeves=(Sleeve(40, 0.0),) * 50)
    litres = foam_litres([big])
    many = foam_cans(Wiring(2700.0, False, (), (), holes=(big,)))
    assert many == math.ceil(litres / FOAM_YIELD_L) == 2


def test_lengths_and_counts_by_diameter() -> None:
    holes = [
        Hole("a", 1, wall_mm=100.0, sleeves=(Sleeve(20, 0.0),)),
        Hole("b", 2, wall_mm=120.0, sleeves=(Sleeve(25, 0.0), Sleeve(20, 0.0))),
    ]
    # The wall plus 10 mm on each side (studio rule)
    assert SLEEVE_OUT_MM == 10.0
    assert sleeve_lengths(holes) == {20: 260.0, 25: 140.0}
    assert sleeve_counts(holes) == {20: 2, 25: 1}
    assert cable_passes(holes) == 3  # one per sleeve


def test_with_sleeves_keeps_the_hole() -> None:
    hole = Hole("door", 2, runs=("a", "b"), wall_mm=100.0)
    (done,) = with_sleeves([hole], [_run("a", "3x1.5"), _run("b", "3x1.5"), _run("c")])
    assert (done.passage, done.cables, done.wall_mm) == ("door", 2, 100.0)
    assert [s.runs for s in done.sleeves] == [("a", "b")]


def _door_wiring() -> tuple[Wiring, Electrical]:
    """Panel in a facing the door, two sockets in b: two cables over the door through the
    100 mm partition."""
    pts = [
        {
            "id": f"s{k}",
            "room": "b",
            "type": "socket",
            "wall": "w3",
            "offset": 300 + 500 * k,
            "height": 300,
            "group": f"QF{k + 1}",
        }
        for k in range(2)
    ]
    board = {"room": "a", "wall": "w1", "offset": 1500, "height": 1700}
    elec = Electrical.model_validate({"points": pts, "board": board})
    wiring: Wiring = wiring_of(two_rooms_with_door(), elec)
    return wiring, elec


def test_pass_over_a_door_has_sleeves_as_long_as_the_wall() -> None:
    w, _ = _door_wiring()
    (hole,) = w.holes
    assert hole.passage == "a_door_1" and hole.wall_mm == 100.0
    assert hole.sleeves and sum(len(s.runs) for s in hole.sleeves) == hole.cables


def test_estimate_counts_passes_sleeves_and_foam() -> None:
    w, elec = _door_wiring()
    q = quantities(w, elec)
    for d, mm in sleeve_lengths(w.holes).items():
        assert q[f"sleeve.{d}"] == pytest.approx(math.ceil(mm / 1000 * (1 + RESERVE) * 10) / 10)
    assert q["firestop_foam"] == 1
    assert q["work.cable_pass"] == cable_passes(w.holes)
    assert not {"work.wall_hole", "work.wall_hole_large"} & set(q)
    est = build_estimate(w, elec, PriceList(), "ru")
    by_key = {ln.key: ln for ln in est.lines}
    (sleeve_key,) = [k for k in by_key if k.startswith("sleeve.")]
    size = sleeve_key.split(".")[1]
    assert by_key[sleeve_key].name == f"Гильза ПВХ Ø{size} для прохода через стену"
    assert by_key["work.cable_pass"].name == "Кабельная проходка"
    assert by_key[sleeve_key].section == "material_rough" and by_key[sleeve_key].unit == "м"
    assert by_key["firestop_foam"].name == "Пена монтажная огнестойкая B1, баллон 750 мл"
    # No price in the list: like any other item without one, marked and left out of the total
    for key in (sleeve_key, "firestop_foam", "work.cable_pass"):
        assert by_key[key].price is None and "Цена уточняется" in (by_key[key].hint or "")
    priced = PriceList.model_validate({"items": {"work.cable_pass": 150, "sleeve": 40}})
    by_key = {ln.key: ln for ln in build_estimate(w, elec, priced, "ru").lines}
    assert by_key["work.cable_pass"].price == 150 and by_key[sleeve_key].price == 40


def test_wiring_sheet_note_counts_the_passes() -> None:
    holes = (
        Hole("a", 1, wall_mm=100.0, sleeves=(Sleeve(20, 0.0), Sleeve(40, 0.0))),
        Hole("b", 1, wall_mm=100.0, sleeves=(Sleeve(20, 0.0),)),
    )
    w = Wiring(2700.0, False, (), (), holes=holes)
    note = (
        "3 кабельные проходки в ПВХ-гильзах (Ø20 ×2, Ø40 ×1), заделка огнестойкой монтажной "
        "пеной B1"
    )
    assert note in wiring_notes(w, "ru")
    uk = (
        "3 кабельні проходи у ПВХ-гільзах (Ø20 ×2, Ø40 ×1), закладення вогнестійкою монтажною "
        "піною B1"
    )
    assert uk in wiring_notes(w, "uk")
    assert not any("гильз" in n for n in wiring_notes(Wiring(2700.0, False, (), ()), "ru"))


@pytest.mark.parametrize(
    ("n", "word"),
    [
        (1, "кабельная проходка"),
        (3, "кабельные проходки"),
        (5, "кабельных проходок"),
        (11, "кабельных проходок"),
        (21, "кабельная проходка"),
        (24, "кабельные проходки"),
    ],
)
def test_pass_word_by_number(n: int, word: str) -> None:
    assert plural(n, CABLE_PASS_WORDS["ru"]) == word
