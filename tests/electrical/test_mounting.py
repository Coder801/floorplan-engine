"""Cable mounting: fixing spots along routes, counts for the estimate, installer notes."""

from __future__ import annotations

import itertools
import math
from collections import Counter
from dataclasses import replace
from typing import Any

import pytest

from floorplan_engine.electrical.estimate import (
    CONDUIT_JOINT_EVERY,
    conduit_lengths,
    quantities,
)
from floorplan_engine.electrical.mounting import (
    PAD,
    PRACTICE,
    BendSize,
    Fixing,
    MountingNorms,
    Surface,
    bend_rows,
    bend_size,
    bundle_radii,
    cable_area,
    conduit_diameter,
    conduits,
    fixing_counts,
    fixing_rows,
    fixing_spans,
    fixings,
    mounting_notes,
    pair_diameter,
    plan_conduits,
    plan_fixings,
    run_fixings,
    shared_diameter,
    shared_pairs,
    source_conduits,
    spots,
)
from floorplan_engine.electrical.wiring_model import Run, Wiring
from floorplan_engine.model.geometry import Vec
from tests.conftest import make_plan
from tests.electrical.test_estimate import _wiring
from tests.electrical.test_wiring import RECT, _sockets
from tests.electrical.test_wiring import _wiring as _plan_wiring


def _run(path: list[Vec], rise_start: float = 0.0, rise_end: float = 0.0, **kw: Any) -> Run:
    plan = sum((b - a).length() for a, b in itertools.pairwise(path))
    return Run(
        id="r1",
        group="QF1",
        mark="3x2.5",
        mark_assumed=False,
        source="board",
        target="p1",
        path=tuple(path),
        plan_mm=plan,
        rise_start_mm=rise_start,
        rise_end_mm=rise_end,
        ends_mm=300.0,
        **kw,
    )


def test_spots_offset_from_ends_and_no_wider_than_step() -> None:
    got = spots(1000.0, 300.0, 50.0)
    assert got[0] == pytest.approx(50.0) and got[-1] == pytest.approx(950.0)
    gaps = [b - a for a, b in itertools.pairwise(got)]
    assert max(gaps) <= 300.0 + 1e-6 and len(got) == 4  # 900 mm inside: 3 gaps of 300
    assert spots(400.0, 300.0, 50.0) == pytest.approx([50.0, 350.0])  # exactly one step


def test_spots_short_pieces() -> None:
    assert spots(80.0, 300.0, 50.0) == [40.0]  # up to 2·offset: one in the middle
    assert spots(30.0, 300.0, 50.0) == []  # shorter than offset: held by the neighbours
    assert spots(0.0, 300.0, 50.0) == []


def test_run_fixings_per_piece_and_rise() -> None:
    """Each piece of the route counts from its own bends; the rises go along the walls with the
    wall step."""
    path = [Vec(0, 0), Vec(1000, 0), Vec(1000, 400)]
    run = _run(path, rise_start=1000.0, rise_end=2000.0)
    got = run_fixings(run, "none")
    first = [f for f in got if f.piece == 0]
    second = [f for f in got if f.piece == 1]
    assert len(first) == len(spots(1000, 300, 50)) and len(second) == 2
    assert all(f.surface == "ceiling" and not f.in_conduit for f in first + second)
    walls = [f for f in got if f.piece is None]
    assert len(walls) == len(spots(1000, 500, 50)) + len(spots(2000, 500, 50))
    assert all(f.surface == "wall" for f in walls)


def test_floor_route_is_in_conduit_with_floor_step() -> None:
    run = _run([Vec(0, 0), Vec(2000, 0)], rise_end=300.0, route="floor")
    got = run_fixings(run, "none")
    assert all(f.in_conduit for f in got)
    assert {f.surface for f in got if f.piece is not None} == {"floor"}


def test_norms_profile_changes_the_spots() -> None:
    dense = MountingNorms(
        "test",
        {"ceiling": 100.0, "wall": 100.0, "floor": 100.0},
        {"ceiling": 100.0, "wall": 100.0, "floor": 100.0},
        50.0,
        10.0,
        2,
        0.0,
        PRACTICE.source,
    )
    run = _run([Vec(0, 0), Vec(1000, 0)])
    assert len(run_fixings(run, "none", dense)) > len(run_fixings(run, "none"))
    assert run_fixings(run, "none")[0] == Fixing("ceiling", False, 0, 50.0)


@pytest.mark.parametrize("conduit", ["none", "ceiling", "walls"])
def test_estimate_counts_the_drawn_spots(conduit: str) -> None:
    """The estimate takes the same spots as the sheet, plus the reserve (decision 2026-11-11):
    conduit gets clips by diameter, bare cable gets pads."""
    wiring, elec = _wiring()
    elec = elec.model_copy(update={"conduit": conduit})
    counts = fixing_counts(wiring, elec.conduit_level)
    total: dict[str, int] = {}
    for (key, _), n in counts.items():
        total[key] = total.get(key, 0) + n
    got = fixings(wiring, elec.conduit_level)
    assert got == {k: math.ceil(v * (1 + PRACTICE.reserve)) for k, v in total.items()}
    q = quantities(wiring, elec)
    assert {k: v for k, v in q.items() if k in got} == got
    if elec.conduit_level == "none":
        assert set(got) == {PAD}
    elif elec.conduit_level == "walls":
        assert PAD not in got and all(k.startswith("conduit_clip.") for k in got)
    else:  # ceiling in conduit, drops along the walls without it
        assert PAD in got and any(k.startswith("conduit_clip.") for k in got)


def test_fixing_spans_by_surface() -> None:
    """Plan part on the ceiling (or the floor for a floor route), rises on the walls; the ends in
    boxes are not fixed."""
    wiring, _ = _wiring()
    r = wiring.runs[0]
    spans = fixing_spans(r, "ceiling")
    assert spans[0] == (True, "ceiling", r.plan_mm)
    assert [s[:2] for s in spans[1:]] == [(False, "wall"), (False, "wall")]
    assert sum(s[2] for s in spans) == pytest.approx(r.length_mm - r.ends_mm)
    floor = replace(r, route="floor")
    assert all(s[0] for s in fixing_spans(floor, "none"))
    assert fixing_spans(floor, "none")[0][1] == "floor"


def test_conduit_diameter_by_section() -> None:
    marks = ("3x1.5", "3x2.5", "3x4", "5x10", "UTP")
    # a flat 3×1.5 is up to 11.5 mm wide: it takes a Ø20, not a Ø16 (studio data 2026-11-11)
    assert [conduit_diameter(m) for m in marks] == [20, 20, 25, 32, 20]


def test_summary_rows_clips_then_pads_with_totals() -> None:
    counts: dict[tuple[str, Surface], int] = {
        ("cable_pad", "wall"): 4,
        ("conduit_clip.20", "ceiling"): 7,
        ("conduit_clip.16", "floor"): 2,
    }
    rows = fixing_rows(counts, "ru")
    assert [name for name, _ in rows] == [
        "Клипса, гофра 16 мм",
        "Клипса, гофра 20 мм",
        "Площадка, кабель",
    ]
    assert rows[1][1] == [7, 0, 0, 7] and rows[2][1] == [0, 4, 0, 4]


@pytest.mark.parametrize("lang", ["ru", "uk"])
def test_notes_follow_norms_and_conduit(lang: Any) -> None:
    _, elec = _wiring()
    notes = mounting_notes(elec.model_copy(update={"conduit": "walls"}), lang)
    joined = " ".join(notes)
    assert "300" in joined and "500" in joined and " 50 " in joined and "10" in joined
    assert PRACTICE.source[lang] in joined
    other = mounting_notes(elec.model_copy(update={"conduit": "none"}), lang)
    assert other != notes  # the conduit line follows the variant


def test_bend_size_flat_cable_by_width_and_conduit_by_larger_radius() -> None:
    """Flat cable bent lying flat: its width, 10 widths (studio practice); conduit: its
    diameter, the larger of the conduit's and the cable's radius (studio data 2026-11-11)."""
    assert bend_size("3x2.5", False) == BendSize(13.0, 130.0)
    assert bend_size("3x1.5", True) == BendSize(20.0, 80.0)
    assert bend_size("3x2.5", True) == BendSize(20.0, 90.0)  # the cable needs more than Ø20
    assert bend_size("3x6", True) == BendSize(25.0, 100.0)
    assert bend_size("UTP", False) is None  # no sizes: the manufacturer's radius


def test_bundle_radii_reference_reserve_and_lanes() -> None:
    """Inner line is the reference: its radius plus 2 free lanes of its width, then each line
    goes out by its lane; a thick outer line keeps its own radius."""
    thin, thick = BendSize(11.5, 115.0), BendSize(16.5, 165.0)
    assert bundle_radii([thin, thin, thin]) == pytest.approx([138.0, 149.5, 161.0])
    radii = bundle_radii([thin, thick])
    assert radii[0] == pytest.approx(138.0)
    assert radii[1] == pytest.approx(165.0)  # 138 + 14 = 152 is less than its own 165
    assert bundle_radii([]) == []


def test_bend_rows_by_type_without_unknown() -> None:
    rows = bend_rows(["3x2.5", "3x1.5", "UTP", "3x1.5"])
    assert rows == [("3x1.5", "115", "20", "80"), ("3x2.5", "130", "20", "90")]


def _chain(loop: str, route: str = "floor", conduit: str = "none") -> Any:
    """Four sockets in a daisy chain on one wall."""
    elec = _sockets(distribution="loop", route=route, conduit=conduit, loop_conduit=loop)
    return _plan_wiring(make_plan(walls=RECT), elec)


def test_pair_diameter_by_larger_section() -> None:
    assert pair_diameter("3x1.5", "3x1.5") == 25
    assert pair_diameter("3x1.5", "3x2.5") == 32
    assert pair_diameter("UTP", "3x1.5") == 32  # unreadable: as 2.5 mm²


def test_shared_chain_drop_is_one_conduit_with_one_row_of_clips() -> None:
    """loop_conduit shared (decision 2026-11-11): at a chain point the cable going out rises in
    the conduit of the cable coming in; that conduit takes both, so it is larger."""
    two, one = _chain("separate"), _chain("shared")
    assert not two.shared_rises and len(one.shared_rises) == 3  # all but the head of the chain
    pairs = shared_pairs(one)
    assert len(pairs) == 3 and {r.id for r in pairs.values()} == one.shared_rises
    out = next(iter(pairs.values()))
    wall = PRACTICE.steps["wall"]
    full, inner = run_fixings(out, "none"), run_fixings(out, "none", inside=True)
    assert [f for f in full if f.piece is not None] == [f for f in inner if f.piece is not None]
    assert sum(f.piece is None for f in inner) == len(spots(out.rise_end_mm, wall, PRACTICE.offset))
    paired = [f for f in run_fixings(out, "none", pair=True) if f.pair]  # on the rise to the point
    assert len(paired) == len(spots(out.rise_end_mm, wall, PRACTICE.offset))
    sep, shared = fixing_counts(two, "none"), fixing_counts(one, "none")
    per_rise = len(spots(out.rise_start_mm, PRACTICE.steps["wall"], PRACTICE.offset))

    def walls(c: Counter[tuple[str, Surface]]) -> int:
        return sum(n for (_, surface), n in c.items() if surface == "wall")

    assert walls(sep) - walls(shared) == 3 * per_rise
    d = pair_diameter(out.mark, out.mark)
    assert shared[(f"conduit_clip.{d}", "wall")] == 3 * per_rise
    lengths = conduit_lengths(one, "none")
    # besides the pair drops, the stretches lines share on the floor may take the same diameter
    along = sum(p.length for p in plan_conduits(one, "none") if p.diameter == d)
    drops = sum(r.rise_end_mm for r in one.runs if r.id in pairs)
    assert lengths[d] == pytest.approx(drops + along)
    saved = sum(r.rise_start_mm for r in one.runs if r.id in one.shared_rises)
    assert sum(lengths.values()) == pytest.approx(
        sum(conduit_lengths(two, "none").values()) - saved
    )


def test_shared_needs_conduit_on_the_drops() -> None:
    """Bare drops (ceiling route, conduit only on the ceiling): nothing to share."""
    assert not _chain("shared", route="ceiling", conduit="ceiling").shared_rises
    assert _chain("shared", route="ceiling", conduit="walls").shared_rises


def test_conduit_joints_by_metres_of_each_diameter() -> None:
    """A joint coupling per CONDUIT_JOINT_EVERY of conduit of a diameter, rounded up."""
    wiring = _chain("separate")
    elec = _sockets(distribution="loop", route="floor")
    q = quantities(wiring, elec)
    for d, mm in conduit_lengths(wiring, "none").items():
        assert q[f"conduit_joint.{d}"] == math.ceil(mm / CONDUIT_JOINT_EVERY)


def test_no_conduit_entries_in_the_estimate() -> None:
    """Conduit goes into flush boxes, junction boxes and the panel through knock-outs: the
    estimate has no separate entry fittings."""
    wiring = _plan_wiring(make_plan(walls=RECT), _sockets(route="floor"))
    assert wiring.boxes
    q = quantities(wiring, _sockets(route="floor"))
    assert not any(k.startswith("conduit_entry") for k in q)


def test_bundle_is_fixed_in_one_line_with_a_fixing_per_cable() -> None:
    """Three cables along one line: every spot holds all three in one line (the clips snap
    together, decision 2026-11-12), the spots go by the bundle piece; where one turns away the
    bundle piece ends and the rest are fixed on their own spots."""
    long = [Vec(0, 0), Vec(3000, 0)]
    short = [Vec(0, 0), Vec(1500, 0), Vec(1500, 1000)]
    runs = tuple(replace(_run(p), id=rid) for rid, p in (("a", long), ("b", long), ("c", short)))
    wiring = Wiring(2700.0, False, (), runs)
    spots_ = plan_fixings(wiring, "none")
    three = [f for f in spots_ if len(f.runs) == 3]
    two = [f for f in spots_ if set(f.runs) == {"a", "b"}]
    assert three and two
    assert all(f.axis == "h" and f.at.y == 0 and 0 < f.at.x < 1500 for f in three)
    assert all(1500 < f.at.x < 3000 for f in two)
    # The estimate: one fixing per cable at each spot, plus the vertical piece of "c"
    counts = fixing_counts(wiring, "none")
    plan = sum(n for (_, surface), n in counts.items() if surface == "ceiling")
    assert plan == sum(len(f.runs) for f in spots_)
    assert any(f.runs == ("c",) and f.axis == "v" for f in spots_)


def test_slanted_piece_is_fixed_on_its_own() -> None:
    wiring = Wiring(2700.0, False, (), (_run([Vec(0, 0), Vec(1000, 1000)]),))
    (*spots_,) = plan_fixings(wiring, "none")
    assert spots_ and all(f.axis is None and f.runs == ("r1",) for f in spots_)


def test_conduit_is_fixed_wider_apart_than_bare_cable() -> None:
    """Studio norms (2026-11-12): conduit every 450 mm overhead and 550 mm on a wall, bare cable
    every 300 and 500."""
    assert PRACTICE.step("ceiling", True) == 450 and PRACTICE.step("wall", True) == 550
    assert PRACTICE.step("ceiling", False) == 300 and PRACTICE.step("wall", False) == 500
    run = _run([Vec(0, 0), Vec(3000, 0)], rise_end=2000.0)
    bare = run_fixings(run, "none")
    piped = run_fixings(run, "walls")
    assert len(piped) < len(bare)
    wiring = Wiring(2700.0, False, (), (run,))
    assert len(plan_fixings(wiring, "ceiling")) < len(plan_fixings(wiring, "none"))


def test_shared_diameter_by_fill_matches_the_size_tables() -> None:
    """40 % of the inner cross-section (decision 2026-11-13) gives the sizes the studio named
    for one cable and for a chain pair, and at most three cables in a Ø32."""
    assert cable_area("3x1.5") == pytest.approx(math.pi / 4 * 5.5 * 11.5)
    assert cable_area("5x2.5") == pytest.approx(math.pi / 4 * 6.0 * 13.0 * 5 / 3)
    assert cable_area("UTP") is None and cable_area("3x10") is None
    for mark in ("3x1.5", "3x2.5", "3x4", "3x6"):
        assert shared_diameter([mark]) == conduit_diameter(mark)
    for a, b in (("3x1.5", "3x1.5"), ("3x1.5", "3x2.5"), ("3x2.5", "3x2.5"), ("3x4", "3x6")):
        assert shared_diameter([a, b]) == pair_diameter(a, b)
    assert shared_diameter(["3x1.5"] * 3) == 32 and shared_diameter(["3x2.5"] * 3) == 32
    assert shared_diameter(["3x1.5"] * 4) is None  # more than a Ø32 takes
    assert shared_diameter(["3x1.5", "UTP"]) is None and shared_diameter([]) is None


def test_conduits_pack_power_together_and_internet_alone() -> None:
    way = [Vec(0, 0), Vec(1000, 0)]
    power = [replace(_run(way), id=f"p{k}", mark="3x2.5") for k in range(4)]
    light = replace(_run(way), id="l1", mark="3x1.5")
    lan = replace(_run(way), id="lan", mark="UTP", circuit="low")
    led = [replace(_run(way), id=f"d{k}", mark="2x1.5", circuit="low", led=True) for k in range(2)]
    assert conduits([power[0]]) == [(20, ("p0",))]
    assert conduits(power[:3]) == [(32, ("p0", "p1", "p2"))]
    # the fourth 3x2.5 does not fit: a conduit of its own, where the thinner 3x1.5 joins it
    assert conduits([*power, light]) == [(32, ("p0", "p1", "p2")), (32, ("p3", "l1"))]
    # internet never shares; 12 V LED lines from the panel lie with the power cables
    # (decision 2026-11-13)
    assert conduits([power[0], lan, *led]) == [(32, ("p0", "d0", "d1")), (20, ("lan",))]
    assert led[0].lay == "power" and lan.lay == "low"


def test_plan_conduits_share_on_the_common_stretch_only() -> None:
    """Two lines together for 2 m, then one goes on alone: a Ø32 for the common stretch, a Ø20
    for the rest; without conduit on the ceiling there is none; the clips follow the conduits."""
    a = replace(_run([Vec(0, 0), Vec(2000, 0)]), id="a")
    b = replace(_run([Vec(0, 0), Vec(3000, 0), Vec(3000, 1000)]), id="b")
    w = Wiring(2700.0, False, (), (a, b))
    assert plan_conduits(w, "none") == []
    pieces = sorted(plan_conduits(w, "ceiling"), key=lambda p: (-p.length, p.diameter))
    assert [(p.diameter, p.length, p.runs) for p in pieces] == [
        (32, 2000.0, ("a", "b")),
        (20, 1000.0, ("b",)),
        (20, 1000.0, ("b",)),
    ]
    assert conduit_lengths(w, "ceiling") == {32: 2000.0, 20: 2000.0}
    counts = fixing_counts(w, "ceiling")
    step, offset = PRACTICE.step("ceiling", True), PRACTICE.offset
    assert counts[("conduit_clip.32", "ceiling")] == len(spots(2000.0, step, offset))
    assert counts[("conduit_clip.20", "ceiling")] == 2 * len(spots(1000.0, step, offset))
    first = next(f for f in plan_fixings(w, "ceiling") if set(f.runs) == {"a", "b"})
    assert first.keys == ("conduit_clip.32",)  # one clip holds both lines
    bare = next(f for f in plan_fixings(w, "none") if set(f.runs) == {"a", "b"})
    assert bare.keys == (PAD, PAD)


def test_rise_from_the_panel_shares_conduit_with_conduit_in_the_walls() -> None:
    way = [Vec(0, 0), Vec(1000, 0)]
    runs = tuple(replace(_run(way, rise_start=1000.0), id=f"r{k}") for k in range(3))
    w = Wiring(2700.0, False, (), runs)
    assert source_conduits(w, "ceiling") == []  # the rise is bare
    (piece,) = source_conduits(w, "walls")
    assert (piece.diameter, piece.length, piece.surface) == (32, 1000.0, "wall")
    step, offset = PRACTICE.step("wall", True), PRACTICE.offset
    assert fixing_counts(w, "walls")[("conduit_clip.32", "wall")] == len(
        spots(1000.0, step, offset)
    )
    lengths = conduit_lengths(w, "walls")
    # one Ø32 up the wall and along the ceiling; each cable's end in its own Ø20, as before
    assert lengths[32] == pytest.approx(2000.0)
    assert lengths[20] == pytest.approx(sum(r.ends_mm for r in runs))
