"""Варианты проводки (docs/wiring-variants.md): режим (эконом, стандарт, премиум), трасса
(потолок, пол) и разводка (через коробки; шлейф через подрозетники — позже). Точки — из
проекта, вариант меняет только то, как тянуть. Строятся все варианты проекта
(project_variants: без трасс, которых в проекте не будет — electrical.yaml routes):
выбранный — листами, остальные — сводкой для сравнения (variant_summary), без чертежей.

Вариант «как в проекте» (default_variant) — режим и трассы из electrical.yaml как есть;
у остальных трасса одна на все кабели.
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
    """Трассы, допустимые в проекте: electrical.yaml routes, нет — все."""
    return ROUTES if elec.routes is None else tuple(r for r in ROUTES if r in elec.routes)


def project_variants(elec: Electrical) -> list[Variant]:
    """Варианты проекта: все, кроме трасс, которых в проекте не будет (routes)."""
    routes = project_routes(elec)
    return [v for v in all_variants() if v.route in routes]


def default_variant(elec: Electrical) -> Variant:
    """Вариант «как в проекте»: режим из electrical.yaml; трасса — общая (route), а без неё
    по полу, если все кабели по полу."""
    if elec.route is not None:
        return Variant(mode=elec.mode, route=elec.route)
    floor = bool(elec.cables) and all(c.route == "floor" for c in elec.cables)
    return Variant(mode=elec.mode, route="floor" if floor else "ceiling")


def apply_variant(elec: Electrical, variant: Variant) -> Electrical:
    """Электрика варианта: точки те же; режим — варианта; трасса — одна на все кабели (у
    варианта «как в проекте» трассы кабелей не трогаются)."""
    if variant == default_variant(elec):
        return elec
    cables = [c.model_copy(update={"route": variant.route}) for c in elec.cables]
    update = {"mode": variant.mode, "route": variant.route, "cables": cables}
    return elec.model_copy(update=update)


def variant_electrical(
    plan: Plan, contours: dict[str, Contour], source: Electrical, variant: Variant
) -> Electrical:
    """Электрика варианта для расчётов: вариант применён, в premium и proper группы
    поделены на линии от щита (lines.split_by_lines), как при загрузке проекта."""
    return split_by_lines(plan, contours, apply_variant(source, variant))


@dataclass(frozen=True)
class VariantSummary:
    """Сводка варианта для сравнения: смета, кабель, аппараты щита, штробы."""

    variant: Variant
    total: float  # всего по смете, валюта прайса
    currency: str
    unpriced: int  # позиций без цены
    cable_m: float  # кабель по трассам, без запаса
    devices: int  # аппаратов в щите
    chases_m: float
    conduit_m: float  # гофра по трассам, без запаса
    edited: bool  # есть ручные правки трасс

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
    """Сводка одного варианта без чертежей: проводка, щит, смета. Нет щита или групп — None."""
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
