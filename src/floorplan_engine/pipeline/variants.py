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


def variant_block(report: Report, prices: Prices) -> dict[str, Any] | None:
    """Wiring variants for the viewer (.epd manifest, key variants): the chosen one, "as in project"
    and a summary of each (estimate, cable, devices, chases), without drawings."""
    source, chosen, default = report.source_electrical, report.variant, report.default_variant
    if report.plan is None or source is None or chosen is None or default is None:
        return None
    wiring_file = report.wiring_file or WiringFile()
    items = []
    for variant in project_variants(source):  # without routes the project does not have (routes)
        edits = wiring_file.edits_for(variant.key, default.key)
        summary = variant_summary(report.plan, report.contours, source, variant, edits, prices)
        if summary is not None:
            items.append(summary.as_dict())
    return {"active": chosen.key, "default": default.key, "items": items}


def save_variant(project: Path, data: dict[str, Any]) -> list[Issue]:
    """Save the wiring variant from the viewer to variant.yaml: {mode, route, distribution,
    ceiling_height?}. Without ceiling_height the previous height stays. Errors come with a field
    path, and the file is left unchanged."""
    path = project / VARIANT_FILE
    if "ceiling_height" not in data:  # changing the variant does not reset the ceiling height
        old, _ = load_optional(path, Variant)
        if old is not None and old.ceiling_height is not None:
            data = {**data, "ceiling_height": old.ceiling_height}
    variant, issues = parse_model(Variant, data, VARIANT_FILE)
    if variant is None:
        return issues
    path.write_text(
        "# Вариант проводки и высота потолка, выбранные в просмотре (docs/wiring-variants.md).\n"
        + yaml.safe_dump(
            variant.model_dump(exclude_none=True), allow_unicode=True, sort_keys=False
        ),
        encoding="utf-8",
    )
    return []
