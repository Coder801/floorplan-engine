"""Legend of the "Plumbing" sheet."""

from __future__ import annotations

from floorplan_engine.drawing.plumbing_legend import legend_variants


def test_legend_variants_get_lower_with_more_columns() -> None:
    heights = [h for _, h, _ in legend_variants("uk")]
    assert heights == sorted(heights) and len(heights) >= 2
