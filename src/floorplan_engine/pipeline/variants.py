"""Wiring variants: the block for the .epd manifest and the choice saved in variant.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from floorplan_engine.electrical.pricing import Prices
from floorplan_engine.electrical.variants import project_variants, variant_summary
from floorplan_engine.model.schema import Variant, WiringFile
from floorplan_engine.validation.answers import load_optional
from floorplan_engine.validation.issues import (
    VARIANT_FILE,
    Issue,
    parse_model,
)
from floorplan_engine.validation.validate import Report

KEPT = {"ceiling_height", "plaster", "rough_light"}  # not part of the wiring variant


def variant_block(report: Report, prices: Prices) -> dict[str, Any] | None:
    """Wiring variants for the viewer (.epd manifest, key variants): the chosen one, "as in project"
    and a summary of each preset and of the chosen one (estimate, cable, devices, chases), without
    drawings. conduit is the choice itself: null — "don't know", as the mode gives."""
    source, chosen, default = report.source_electrical, report.variant, report.default_variant
    if report.plan is None or source is None or chosen is None or default is None:
        return None
    wiring_file = report.wiring_file or WiringFile()
    items = []
    variants = project_variants(source)  # without routes the project does not have (routes)
    if chosen.key not in {v.key for v in variants}:
        variants.append(chosen)  # a set from the setup wizard
    job = {"plaster": chosen.plaster, "rough_light": chosen.rough_light}  # alike in every variant
    for variant in variants:
        edits = wiring_file.edits_for(variant.key, default.key)
        same_job = variant.model_copy(update=job)
        summary = variant_summary(report.plan, report.contours, source, same_job, edits, prices)
        if summary is not None:
            items.append(summary.as_dict())
    return {
        "active": chosen.key,
        "default": default.key,
        "conduit": chosen.conduit,
        "items": items,
    }


def save_variant(project: Path, data: dict[str, Any]) -> list[Issue]:
    """Save the wiring variant from the viewer to variant.yaml: {mode, route, distribution, path?,
    conduit?, plaster?, rough_light?, ceiling_height?}. What is not in data of KEPT stays as it
    was. Errors come with a field path, and the file is left unchanged."""
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
