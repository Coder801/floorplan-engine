"""Wiring variants: the block for the .epd manifest and the choice saved in variant.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from floorplan_engine.electrical.pricing import Prices
from floorplan_engine.electrical.variants import (
    chosen_job,
    has_led,
    neighbour_variants,
    variant_summary,
)
from floorplan_engine.model.schema import Variant, WiringFile
from floorplan_engine.validation.answers import load_optional
from floorplan_engine.validation.issues import (
    VARIANT_FILE,
    Issue,
    parse_model,
)
from floorplan_engine.validation.validate import Report

# Not part of the wiring variant: changing the variant keeps them
KEPT = {
    "ceiling_height",
    "plaster",
    "rough_light",
    "panel_labels",
    "insulation_test",
    "protection_test",
    "loop_conduit",
}


def variant_block(report: Report, prices: Prices) -> dict[str, Any] | None:
    """Wiring variants for the viewer (.epd manifest, key variants): the chosen one, "as in project"
    and a summary (estimate, cable, devices, chases), without drawings, of the chosen set first and
    then of its neighbours: the set with one option changed (variants.neighbour_variants), for the
    comparison and the prices on the wizard cards. conduit is the choice itself: null — "don't
    know", as the mode gives. led: the project has LED outputs, so the LED supply is asked."""
    source, chosen, default = report.source_electrical, report.variant, report.default_variant
    if report.plan is None or source is None or chosen is None or default is None:
        return None
    wiring_file = report.wiring_file or WiringFile()
    items = []
    for variant in [chosen_job(source, chosen), *neighbour_variants(source, chosen)]:
        edits = wiring_file.edits_for(variant.key, default.key)
        summary = variant_summary(report.plan, report.contours, source, variant, edits, prices)
        if summary is not None:
            items.append(summary.as_dict())
    return {
        "active": chosen.key,
        "default": default.key,
        "conduit": chosen.conduit,
        "led": has_led(source),
        "items": items,
    }


def save_variant(project: Path, data: dict[str, Any]) -> list[Issue]:
    """Save the wiring variant from the viewer to variant.yaml: {mode, route, distribution, path?,
    conduit?, led_supply?, plaster?, rough_light?, panel_labels?, insulation_test?,
    protection_test?, loop_conduit?, ceiling_height?}. What is not in
    data of KEPT stays as it was. Errors come with a field path, and the file is left unchanged."""
    path = project / VARIANT_FILE
    old, _ = load_optional(path, Variant)
    if old is not None:  # changing the variant does not reset these
        data = {**old.model_dump(include=KEPT, exclude_none=True), **data}
    variant, issues = parse_model(Variant, data, VARIANT_FILE)
    if variant is None:
        return issues
    path.write_text(
        "# Вариант проводки и настройки монтажа из просмотра (docs/wiring-variants.md).\n"
        + yaml.safe_dump(
            variant.model_dump(exclude_none=True), allow_unicode=True, sort_keys=False
        ),
        encoding="utf-8",
    )
    return []
