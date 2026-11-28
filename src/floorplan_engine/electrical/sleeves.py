"""Cable passes through walls (decision 2026-11-28): the cables go through a wall in a smooth
rigid light PVC sleeve, and the gaps are sealed with fire-rated mounting foam (class B1). One
cable pass is one sleeve; there is no large core-drilled hole: the cables one Ø40 does not hold
go through the next pass beside it.

PUE clause 2.1.58: wiring through a wall goes in a pipe, the gaps are sealed with an easily
removable non-combustible mass that lets the wiring be replaced.

- the sleeve size follows the cables of the pass, like a shared conduit (mounting.conduits):
  they fill at most SLEEVE_FILL of its inner cross-section (SLEEVE_INNER); the thickest cable
  first, each into the first sleeve it fits; more than one Ø40 holds — the next pass. Power and
  low-voltage are in different holes already (chases.wall_holes) and never share a sleeve;
- a power cable takes its flat size (mounting.cable_area). One with a cross-section the studio
  sizes do not have (mounting.FLAT_CABLE: 3×10, 5×16 — loads.cable_for goes up to 16 mm²) goes
  alone, in the sleeve of its conduit (mounting.conduit_diameter; no such sleeve — the largest),
  marked Sleeve.by_section for the estimate note; one without a cross-section — a Ø20 alone;
- low-voltage cables of a crossing (internet, TV) share sleeves too (decision 2026-11-28), by the
  circle of their typical outer Ø (LOW_CABLE_OD), with the same fill;
- a sleeve sticks out SLEEVE_OUT_MM on each side of the wall (studio rule): its length is the
  wall thickness at the pass (Hole.wall_mm) plus 2 × SLEEVE_OUT_MM;
- the foam fills each sleeve around its cables inside the wall: (π/4·d² − the cables) × the
  wall thickness, one can per FOAM_YIELD_L litres (foam_cans).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace

from floorplan_engine.electrical.mounting import (
    CONDUIT_FILL,
    cable_area,
    cable_section,
    conduit_diameter,
)
from floorplan_engine.electrical.wiring_model import Hole, Run, Sleeve, Wiring

# Smooth rigid light PVC pipe, outer Ø → inner Ø, mm: DKC light series (shop cards of DKC,
# checked 2026-11-28). Ø32 and Ø50 are not here: no confirmed inner Ø yet (docs/mounting.md)
SLEEVE_INNER: dict[int, float] = {20: 17.6, 25: 22.7, 40: 36.7}
SLEEVE_FILL = CONDUIT_FILL  # cables fill at most 40 % of the inner cross-section, as in a conduit
SLEEVE_ALONE = min(SLEEVE_INNER)  # a power cable without a cross-section: a Ø20 of its own
# Low-voltage cables by mark → outer Ø, mm: typical nominal sizes (UTP cat.5e/6 ≈ 6 mm, RG-6 coax
# ≈ 7 mm), not manufacturer data — the cable of the job may be a little thicker or thinner. A
# mark not here takes LOW_CABLE_OD_OTHER, the larger one (decision 2026-11-28)
LOW_CABLE_OD: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"utp|ftp|stp|cat", re.I), 6.0),
    (re.compile(r"rg-?6|коакс|coax", re.I), 7.0),
)
LOW_CABLE_OD_OTHER = 7.0
SLEEVE_OUT_MM = 10.0  # the sleeve sticks out this much on each side of the wall (studio rule)
# Fire-rated mounting foam class B1, a 750 ml can (decision 2026-11-28, was a 325 ml firestop
# sealant at 2.1 l): the lowest yield the makers state — Tytan Professional B1 42 l, Penosil Fire
# Rated up to 45 l, Lacrysil B1 up to 50 l. A free-expansion figure: in a tight sleeve it gives less
FOAM_CAN_ML = 750
FOAM_YIELD_L = 42.0
SLEEVE_KEY = "sleeve"  # estimate key, sleeve.<Ø>
FOAM_KEY = "firestop_foam"  # estimate key of a foam can


def capacity(diameter: int) -> float:
    """Cross-section cables may take in a sleeve, mm² (SLEEVE_FILL of the inner one)."""
    return SLEEVE_FILL * math.pi / 4 * SLEEVE_INNER[diameter] ** 2


def sleeve_size(area: float) -> int:
    """The smallest sleeve the cables of this cross-section fit, mm; the largest if none."""
    return next((d for d in sorted(SLEEVE_INNER) if area <= capacity(d) + 1e-9), max(SLEEVE_INNER))


def low_cable_od(mark: str) -> float:
    """Typical outer Ø of a low-voltage cable, mm (LOW_CABLE_OD; another mark — the larger)."""
    return next((d for pattern, d in LOW_CABLE_OD if pattern.search(mark)), LOW_CABLE_OD_OTHER)


def low_cable_area(mark: str) -> float:
    """Cross-section a low-voltage cable takes in a sleeve, mm²: the circle of its outer Ø."""
    return math.pi / 4 * low_cable_od(mark) ** 2


def section_sleeve(mark: str) -> int:
    """Sleeve of a power cable with a cross-section but no known size: the smallest not below
    its conduit (mounting.conduit_diameter), the largest if none is (Ø32 conduit → Ø40)."""
    d = conduit_diameter(mark)
    return next((s for s in sorted(SLEEVE_INNER) if s >= d), max(SLEEVE_INNER))


def _pack(runs: Sequence[Run], areas: Mapping[int, float]) -> list[Sleeve]:
    """Cables of these indices into sleeves: the thickest first, each into the first sleeve whose
    cables with it still fit the largest size (first fit), then each sleeve by its cables
    (sleeve_size). Ties go by the order of runs."""
    bins: list[list[int]] = []
    top = capacity(max(SLEEVE_INNER))
    for k in sorted(areas, key=lambda k: (-areas[k], k)):
        for inside in bins:
            if sum(areas[j] for j in inside) + areas[k] <= top + 1e-9:
                inside.append(k)
                break
        else:
            bins.append([k])
    out: list[Sleeve] = []
    for inside in bins:
        total = sum(areas[j] for j in inside)
        out.append(Sleeve(sleeve_size(total), total, tuple(runs[j].id for j in sorted(inside))))
    return out


def fit_sleeves(runs: Sequence[Run]) -> tuple[Sleeve, ...]:
    """Sleeves of the cables of one pass: power cables with sizes packed (_pack, by
    mounting.cable_area), low-voltage ones packed apart (by low_cable_area), then each power
    cable without a size alone — by its conduit if it has a cross-section (section_sleeve,
    by_section), a Ø20 if not. Deterministic: ties go by the order of runs."""
    power: dict[int, float] = {}
    low: dict[int, float] = {}
    alone: list[Sleeve] = []
    for k, r in enumerate(runs):
        if r.lay == "low":
            low[k] = low_cable_area(r.mark)
        elif (area := cable_area(r.mark)) is not None:
            power[k] = area
        elif cable_section(r.mark) is not None:
            alone.append(Sleeve(section_sleeve(r.mark), 0.0, (r.id,), by_section=True))
        else:
            alone.append(Sleeve(SLEEVE_ALONE, 0.0, (r.id,)))
    return (*_pack(runs, power), *_pack(runs, low), *alone)


def with_sleeves(holes: Sequence[Hole], runs: Sequence[Run]) -> tuple[Hole, ...]:
    """Holes with the sleeves of their cables (fit_sleeves)."""
    by_id: Mapping[str, Run] = {r.id: r for r in runs}
    return tuple(
        replace(h, sleeves=fit_sleeves([by_id[i] for i in h.runs if i in by_id])) for h in holes
    )


def cable_passes(holes: Sequence[Hole]) -> int:
    """Cable passes: one per sleeve."""
    return sum(len(h.sleeves) for h in holes)


def sleeve_counts(holes: Sequence[Hole]) -> dict[int, int]:
    """Sleeves (cable passes) by outer Ø, from the smallest."""
    counts = Counter(s.diameter for h in holes for s in h.sleeves)
    return dict(sorted(counts.items()))


def sleeve_lengths(holes: Sequence[Hole]) -> dict[int, float]:
    """Sleeve length by outer Ø, mm: each the wall thickness plus SLEEVE_OUT_MM on each side."""
    out: dict[int, float] = {}
    for h in holes:
        for s in h.sleeves:
            out[s.diameter] = out.get(s.diameter, 0.0) + h.wall_mm + 2 * SLEEVE_OUT_MM
    return dict(sorted(out.items()))


def foam_litres(holes: Sequence[Hole]) -> float:
    """Firestop foam for all sleeves, l: the free inner cross-section of each sleeve (around its
    cables) times the wall thickness (the foam is inside the wall, not in the ends that stick
    out)."""
    mm3 = sum(
        max(math.pi / 4 * SLEEVE_INNER[s.diameter] ** 2 - s.cables_mm2, 0.0) * h.wall_mm
        for h in holes
        for s in h.sleeves
    )
    return mm3 / 1e6


def foam_cans(wiring: Wiring) -> int:
    """Foam cans for the passes: by the volume at FOAM_YIELD_L each, at least one if there is a
    sleeve."""
    if not any(h.sleeves for h in wiring.holes):
        return 0
    return max(math.ceil(foam_litres(wiring.holes) / FOAM_YIELD_L - 1e-9), 1)
