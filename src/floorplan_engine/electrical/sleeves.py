"""Cable passes through walls (decision 2026-11-28): the cables go through a wall in a smooth
rigid light PVC sleeve, and the gaps are sealed with firestop foam. One cable pass is one
sleeve; there is no large core-drilled hole: the cables one Ø40 does not hold go through the
next pass beside it.

PUE clause 2.1.58: wiring through a wall goes in a pipe, the gaps are sealed with an easily
removable non-combustible mass that lets the wiring be replaced.

- the sleeve size follows the cables of the pass, like a shared conduit (mounting.conduits):
  they fill at most SLEEVE_FILL of its inner cross-section (SLEEVE_INNER); the thickest cable
  first, each into the first sleeve it fits; more than one Ø40 holds — the next pass. A cable
  without sizes (internet, TV) takes a Ø20 sleeve of its own, as in a conduit
  (mounting.conduit_diameter). Power and low-voltage are in different holes already
  (chases.wall_holes);
- a sleeve sticks out SLEEVE_OUT_MM on each side of the wall (studio rule): its length is the
  wall thickness at the pass (Hole.wall_mm) plus 2 × SLEEVE_OUT_MM;
- the foam fills each sleeve around its cables inside the wall: (π/4·d² − the cables) × the
  wall thickness, one can per FOAM_YIELD_L litres (foam_cans).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace

from floorplan_engine.electrical.mounting import CONDUIT_FILL, cable_area
from floorplan_engine.electrical.wiring_model import Hole, Run, Sleeve, Wiring

# Smooth rigid light PVC pipe, outer Ø → inner Ø, mm: DKC light series (shop cards of DKC,
# checked 2026-11-28). Ø32 and Ø50 are not here: no confirmed inner Ø yet (docs/mounting.md)
SLEEVE_INNER: dict[int, float] = {20: 17.6, 25: 22.7, 40: 36.7}
SLEEVE_FILL = CONDUIT_FILL  # cables fill at most 40 % of the inner cross-section, as in a conduit
SLEEVE_ALONE = min(SLEEVE_INNER)  # a cable without sizes: a Ø20 of its own
SLEEVE_OUT_MM = 10.0  # the sleeve sticks out this much on each side of the wall (studio rule)
# Hilti CFS-F FX firestop foam, a 325 ml can: up to 2.1 l of foam when it expands freely (Hilti
# data sheet, ETA-10/0109). "Up to": in a tight sleeve it gives less
FOAM_CAN_ML = 325
FOAM_YIELD_L = 2.1
SLEEVE_KEY = "sleeve"  # estimate key, sleeve.<Ø>
FOAM_KEY = "firestop_foam"  # estimate key of a foam can


def capacity(diameter: int) -> float:
    """Cross-section cables may take in a sleeve, mm² (SLEEVE_FILL of the inner one)."""
    return SLEEVE_FILL * math.pi / 4 * SLEEVE_INNER[diameter] ** 2


def sleeve_size(area: float) -> int:
    """The smallest sleeve the cables of this cross-section fit, mm; the largest if none."""
    return next((d for d in sorted(SLEEVE_INNER) if area <= capacity(d) + 1e-9), max(SLEEVE_INNER))


def fit_sleeves(runs: Sequence[Run]) -> tuple[Sleeve, ...]:
    """Sleeves of the cables of one pass: the thickest first, each into the first sleeve whose
    cables with it still fit the largest size (first fit), then each sleeve by its cables
    (sleeve_size); a cable without sizes alone in a Ø20. Deterministic: ties go by the order of
    runs."""
    areas = [cable_area(r.mark) for r in runs]
    bins: list[list[int]] = []
    alone: list[int] = []
    order = sorted(range(len(runs)), key=lambda k: (-(areas[k] or 0.0), k))
    top = capacity(max(SLEEVE_INNER))
    for k in order:
        area = areas[k]
        if area is None:
            alone.append(k)
            continue
        for inside in bins:
            if sum(areas[j] or 0.0 for j in inside) + area <= top + 1e-9:
                inside.append(k)
                break
        else:
            bins.append([k])
    out: list[Sleeve] = []
    for inside in bins:
        total = sum(areas[j] or 0.0 for j in inside)
        out.append(Sleeve(sleeve_size(total), total, tuple(runs[j].id for j in sorted(inside))))
    out += [Sleeve(SLEEVE_ALONE, 0.0, (runs[k].id,)) for k in sorted(alone)]
    return tuple(out)


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
