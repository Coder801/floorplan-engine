"""Wiring variants (docs/wiring-variants.md): mode (economy, standard, premium), route (ceiling,
floor), distribution (through boxes or a daisy chain through flush boxes), path and ceiling
conduit, and for every variant alike when the cable goes in (plaster), rough light and the
extra options (panel labels, insulation test, protection test: the estimate only). Points
come from the project; a variant only changes how cable is run. The modes are presets of the
options; the person chooses each option in the setup wizard. The chosen set is built as sheets,
and it and its neighbours (neighbour_variants: the set with one option changed, without routes
the project will not have, see electrical.yaml routes) as a summary for comparison and for the
prices on the wizard cards (variant_summary), with no drawings: all 64 sets would take minutes on
every build.

The "as in project" variant (default_variant) uses the mode and routes from electrical.yaml
as is; the others use one route for all cables.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import get_args

from floorplan_engine.electrical.estimate import PriceSource, build_estimate, conduit_lengths
from floorplan_engine.electrical.lines import split_by_lines
from floorplan_engine.electrical.master import with_master_switch
from floorplan_engine.electrical.panel import build_panel
from floorplan_engine.electrical.wiring import estimate_wiring
from floorplan_engine.model.geometry import Contour
from floorplan_engine.model.schema import (
    Conduit,
    Distribution,
    Electrical,
    ElectricalMode,
    LedSupply,
    LightWiring,
    LoopConduit,
    Plan,
    Plaster,
    PointType,
    Variant,
    WirePath,
    WireRoute,
    WiringEdits,
)

MODES: tuple[ElectricalMode, ...] = get_args(ElectricalMode)
ROUTES: tuple[WireRoute, ...] = get_args(WireRoute)


def project_routes(elec: Electrical) -> tuple[WireRoute, ...]:
    """Routes allowed in the project: electrical.yaml routes, or all if unset."""
    return ROUTES if elec.routes is None else tuple(r for r in ROUTES if r in elec.routes)


def has_led(elec: Electrical) -> bool:
    """The project has LED outputs: only then the LED supply is a choice."""
    return any(p.type is PointType.LED_OUTPUT for p in elec.points)


def has_loop_drops(variant: Variant) -> bool:
    """Daisy chain drops go in conduit: only then loop_conduit is a choice (chases.with_conduit:
    floor routes always, ceiling routes with conduit in the walls)."""
    return variant.distribution == "loop" and (
        variant.route == "floor" or variant.conduit_level == "walls"
    )


def _job(elec: Electrical, variant: Variant) -> dict[str, object]:
    """Plaster, rough light, the extra options and the chain drop conduit of the variant; None:
    as in electrical.yaml."""
    return {
        "plaster": variant.plaster or elec.plaster,
        "rough_light": elec.rough_light if variant.rough_light is None else variant.rough_light,
        "panel_labels": elec.panel_labels if variant.panel_labels is None else variant.panel_labels,
        "insulation_test": (
            elec.insulation_test if variant.insulation_test is None else variant.insulation_test
        ),
        "protection_test": (
            elec.protection_test if variant.protection_test is None else variant.protection_test
        ),
        "loop_conduit": variant.loop_conduit or elec.loop_conduit,
    }


def chosen_job(elec: Electrical, variant: Variant) -> Variant:
    """The variant with plaster and rough light spelt out (None: as in electrical.yaml) and the
    path spelt out (None: as the mode gives), as the setup wizard sends it."""
    return variant.model_copy(update={"path": variant.wire_path, **_job(elec, variant)})


def neighbour_variants(elec: Electrical, chosen: Variant) -> list[Variant]:
    """The chosen set with one option changed, each other value of each wizard step: route (only
    those the project has), distribution, path, conduit, light wiring, LED supplies (only with
    LED outputs), breakers (the mode), plaster, rough light and the chain drop conduit (only with
    chain drops in conduit, has_loop_drops). The extra options (panel labels, insulation test,
    protection test) have no neighbours: each would be one more variant to calculate, and they
    only add an estimate line; their cards are priced after the recalculation. conduit "don't
    know" (None) stays with another mode, as in the wizard: then the conduit of that mode comes
    with it."""
    base = chosen_job(elec, chosen)
    others: list[tuple[str, tuple[object, ...], object]] = [
        ("route", project_routes(elec), base.route),
        ("distribution", get_args(Distribution), base.distribution),
        ("path", get_args(WirePath), base.path),
        ("conduit", get_args(Conduit), base.conduit_level),
        ("light_wiring", get_args(LightWiring), base.light_wiring),
        ("led_supply", get_args(LedSupply) if has_led(elec) else (), base.led_supply),
        ("mode", MODES, base.mode),
        ("plaster", get_args(Plaster), base.plaster),
        ("rough_light", (False, True), base.rough_light),
        (
            "loop_conduit",
            get_args(LoopConduit) if has_loop_drops(base) else (),
            base.loop_conduit,
        ),
    ]
    changes = [{f: v} for f, values, now in others for v in values if v != now]
    return [base.model_copy(update=change) for change in changes]


def default_variant(elec: Electrical) -> Variant:
    """The "as in project" variant: options from electrical.yaml; route is the shared one (route),
    and without it, floor if all cables run on the floor."""
    route = elec.route
    if route is None:
        floor = bool(elec.cables) and all(c.route == "floor" for c in elec.cables)
        route = "floor" if floor else "ceiling"
    return Variant(
        mode=elec.mode,
        route=route,
        distribution=elec.distribution,
        path=elec.path,
        conduit=elec.conduit,
        light_wiring=elec.light_wiring,
        led_supply=elec.led_supply,
        plaster=elec.plaster,
        rough_light=elec.rough_light,
        panel_labels=elec.panel_labels,
        insulation_test=elec.insulation_test,
        protection_test=elec.protection_test,
        loop_conduit=elec.loop_conduit,
    )


def apply_variant(elec: Electrical, variant: Variant) -> Electrical:
    """Variant electrical model: same points; the variant's options; one route for all cables (the
    "as in project" variant leaves cable routes untouched). plaster, rough_light, the extra
    options and loop_conduit are not in the key: they apply to any variant."""
    job = _job(elec, variant)
    if variant.key == default_variant(elec).key:
        same = job == {k: getattr(elec, k) for k in job}
        return elec if same else elec.model_copy(update=job)
    cables = [c.model_copy(update={"route": variant.route}) for c in elec.cables]
    update = {
        "mode": variant.mode,
        "route": variant.route,
        "distribution": variant.distribution,
        "path": variant.path,
        "conduit": variant.conduit,
        "light_wiring": variant.light_wiring,
        "led_supply": variant.led_supply,
        "cables": cables,
        **job,
    }
    return elec.model_copy(update=update)


def variant_electrical(
    plan: Plan, contours: dict[str, Contour], source: Electrical, variant: Variant
) -> Electrical:
    """Variant electrical model for calculations: the variant is applied, and in premium and proper
    groups are split into lines from the panel (lines.split_by_lines) and the master switch point
    is put in (master.with_master_switch), as on project load."""
    return split_by_lines(plan, contours, with_master_switch(plan, apply_variant(source, variant)))


@dataclass(frozen=True)
class VariantSummary:
    """Variant summary for comparison: estimate, cable, panel devices, chases."""

    variant: Variant
    total: float  # estimate total, in the price list currency
    material: float  # materials section of the estimate
    work: float  # rough and finish work sections
    currency: str
    unpriced: int  # items without a price
    cable_m: float  # cable along routes, without margin
    devices: int  # devices in the panel
    chases_m: float
    conduit_m: float  # conduit along routes, without margin
    edited: bool  # has manual route edits
    plaster: Plaster = "after"
    rough_light: bool = False
    panel_labels: bool = True
    insulation_test: bool = True
    protection_test: bool = False
    loop_conduit: LoopConduit = "separate"

    def as_dict(self) -> dict[str, object]:
        v = self.variant
        return {
            "key": v.key, "mode": v.mode, "route": v.route, "distribution": v.distribution,
            "path": v.wire_path, "conduit": v.conduit_level,
            "light_wiring": v.light_wiring, "led_supply": v.led_supply,
            "plaster": self.plaster, "rough_light": self.rough_light,
            "panel_labels": self.panel_labels, "insulation_test": self.insulation_test,
            "protection_test": self.protection_test,
            "loop_conduit": self.loop_conduit,
            "total": round(self.total, 2), "material": round(self.material, 2),
            "work": round(self.work, 2), "currency": self.currency, "unpriced": self.unpriced,
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
        material=est.materials,
        work=est.work,
        currency=prices.currency,
        unpriced=est.unpriced,
        cable_m=sum(r.length_mm for r in wiring.runs) / 1000,
        devices=len(panel.devices) if panel is not None else 0,
        chases_m=(wiring.chase_length(wide=False) + wiring.chase_length(wide=True)) / 1000,
        conduit_m=sum(conduit_lengths(wiring, elec.conduit_level).values()) / 1000,
        edited=edits is not None,
        plaster=elec.plaster,
        rough_light=elec.rough_light,
        panel_labels=elec.panel_labels,
        insulation_test=elec.insulation_test,
        protection_test=elec.protection_test,
        loop_conduit=elec.loop_conduit,
    )
