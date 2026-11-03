"""Wiring variants (docs/wiring-variants.md): mode (economy, standard, premium), route (ceiling,
floor) and distribution (through boxes; daisy chain through flush boxes later). Points come
from the project; a variant only changes how cable is run. All project variants are built
(project_variants: without routes the project will not have, see electrical.yaml routes):
the chosen one as sheets, the others as a summary for comparison (variant_summary), with no
drawings.

The "as in project" variant (default_variant) uses the mode and routes from electrical.yaml
as is; the others use one route for all cables.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import get_args

from floorplan_engine.electrical.estimate import PriceSource, build_estimate, conduit_mm
from floorplan_engine.electrical.lines import split_by_lines
from floorplan_engine.electrical.panel import build_panel
from floorplan_engine.electrical.wiring import estimate_wiring
from floorplan_engine.model.geometry import Contour
from floorplan_engine.model.schema import (
    Distribution,
    Electrical,
    ElectricalMode,
    Plan,
    Variant,
    WireRoute,
    WiringEdits,
)

MODES: tuple[ElectricalMode, ...] = get_args(ElectricalMode)
ROUTES: tuple[WireRoute, ...] = get_args(WireRoute)
DISTRIBUTIONS: tuple[Distribution, ...] = get_args(Distribution)


def all_variants() -> list[Variant]:
    return [
        Variant(mode=m, route=r, distribution=d)
        for m, r, d in product(MODES, ROUTES, DISTRIBUTIONS)
    ]


def project_routes(elec: Electrical) -> tuple[WireRoute, ...]:
    """Routes allowed in the project: electrical.yaml routes, or all if unset."""
    return ROUTES if elec.routes is None else tuple(r for r in ROUTES if r in elec.routes)


def project_variants(elec: Electrical) -> list[Variant]:
    """Project variants: all except routes the project will not have (routes)."""
    routes = project_routes(elec)
    return [v for v in all_variants() if v.route in routes]


def default_variant(elec: Electrical) -> Variant:
    """The "as in project" variant: mode from electrical.yaml; route is the shared one (route), and
    without it, floor if all cables run on the floor."""
    if elec.route is not None:
        return Variant(mode=elec.mode, route=elec.route)
    floor = bool(elec.cables) and all(c.route == "floor" for c in elec.cables)
    return Variant(mode=elec.mode, route="floor" if floor else "ceiling")


def apply_variant(elec: Electrical, variant: Variant) -> Electrical:
    """Variant electrical model: same points; the variant's mode; one route for all cables (the
    "as in project" variant leaves cable routes untouched)."""
    if variant == default_variant(elec):
        return elec
    cables = [c.model_copy(update={"route": variant.route}) for c in elec.cables]
    update = {"mode": variant.mode, "route": variant.route, "cables": cables}
    return elec.model_copy(update=update)


def variant_electrical(
    plan: Plan, contours: dict[str, Contour], source: Electrical, variant: Variant
) -> Electrical:
    """Variant electrical model for calculations: the variant is applied, and in premium and proper
    groups are split into lines from the panel (lines.split_by_lines), as on project load."""
    return split_by_lines(plan, contours, apply_variant(source, variant))


@dataclass(frozen=True)
class VariantSummary:
    """Variant summary for comparison: estimate, cable, panel devices, chases."""

    variant: Variant
    total: float  # estimate total, in the price list currency
    currency: str
    unpriced: int  # items without a price
    cable_m: float  # cable along routes, without margin
    devices: int  # devices in the panel
    chases_m: float
    conduit_m: float  # conduit along routes, without margin
    edited: bool  # has manual route edits

    def as_dict(self) -> dict[str, object]:
        v = self.variant
        return {
            "key": v.key, "mode": v.mode, "route": v.route, "distribution": v.distribution,
            "total": round(self.total, 2), "currency": self.currency, "unpriced": self.unpriced,
            "cable_m": round(self.cable_m, 1), "devices": self.devices,
            "chases_m": round(self.chases_m, 1), "conduit_m": round(self.conduit_m, 1),
            "edited": self.edited,
        }  # fmt: skip


def variant_summary(
    plan: Plan,
    contours: dict[str, Contour],
    source: Electrical,
    variant: Variant,
    edits: WiringEdits | None,
    prices: PriceSource,
) -> VariantSummary | None:
    """Summary of one variant without drawings: wiring, panel, estimate. None without a panel or
    groups.
    """
    elec = variant_electrical(plan, contours, source, variant)
    wiring = estimate_wiring(plan, contours, elec, edits)
    if wiring is None:
        return None
    panel = build_panel(plan, elec)
    est = build_estimate(wiring, elec, prices, plan.language, panel)
    return VariantSummary(
        variant=variant,
        total=est.total,
        currency=prices.currency,
        unpriced=est.unpriced,
        cable_m=sum(r.length_mm for r in wiring.runs) / 1000,
        devices=len(panel.devices) if panel is not None else 0,
        chases_m=(wiring.chase_length(wide=False) + wiring.chase_length(wide=True)) / 1000,
        conduit_m=sum(conduit_mm(r, elec.mode) for r in wiring.runs) / 1000,
        edited=edits is not None,
    )
