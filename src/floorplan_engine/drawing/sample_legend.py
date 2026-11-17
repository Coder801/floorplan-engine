"""Legend of sample rows next to the title block: a heading, then rows of a drawn sample and its
caption, split into columns; the plumbing and plan legends are built this way."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import partial

from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.layout import Paperspace

from floorplan_engine.drawing.layers import A_TEXT, TEXT_ROOM_MM, TEXT_SMALL_MM, text_width
from floorplan_engine.drawing.plan import add_text
from floorplan_engine.model.geometry import Vec

LEGEND_ROW_MM = 6.0
LEGEND_SAMPLE_MM = 10.0
LEGEND_GAP_MM = 6.0
CAPTION_GAP_MM = 3.0  # caption after the sample
TITLE_GAP_MM = 2.0  # rows below the heading
MIN_ROWS = 3  # rows per column, at least

LegendDraw = Callable[[Paperspace, Vec], None]  # row sample; the point is the middle on the left
LegendRow = tuple[str, LegendDraw]  # caption and its sample


def _draw_legend(
    psp: Paperspace,
    tl: Vec,
    *,
    title: str,
    chunks: list[list[LegendRow]],
    widths: list[float],
    sample: float,
) -> None:
    left = TextEntityAlignment.MIDDLE_LEFT
    at = Vec(tl.x, tl.y - TEXT_ROOM_MM / 2)
    add_text(psp, title, at, TEXT_ROOM_MM, A_TEXT.name, align=left, scale=1.0)
    x = tl.x
    for chunk, w in zip(chunks, widths, strict=True):
        y = tl.y - TEXT_ROOM_MM - TITLE_GAP_MM
        for label, draw in chunk:
            mid = Vec(x, y - LEGEND_ROW_MM / 2)
            draw(psp, mid)
            caption = Vec(x + sample + CAPTION_GAP_MM, mid.y)
            add_text(psp, label, caption, TEXT_SMALL_MM, A_TEXT.name, align=left, scale=1.0)
            y -= LEGEND_ROW_MM
        x += w + LEGEND_GAP_MM


def legend_variants(
    title: str, rows: Sequence[LegendRow], sample: float = LEGEND_SAMPLE_MM
) -> list[tuple[float, float, LegendDraw]]:
    """Legend variants: (width, height, drawing from the top-left corner), k rows per column
    from MIN_ROWS (fewer rows — one column); the layout takes the lowest one that fits
    (layout.fit_legend). sample is the sample width, sheet mm."""
    out: list[tuple[float, float, LegendDraw]] = []
    for k in range(min(MIN_ROWS, len(rows)), len(rows) + 1):
        chunks = [list(rows[i : i + k]) for i in range(0, len(rows), k)]
        widths = [
            sample + CAPTION_GAP_MM + max(text_width(t, TEXT_SMALL_MM) for t, _ in chunk)
            for chunk in chunks
        ]
        width = max(
            sum(widths) + LEGEND_GAP_MM * (len(chunks) - 1), text_width(title, TEXT_ROOM_MM)
        )
        height = TEXT_ROOM_MM + TITLE_GAP_MM + k * LEGEND_ROW_MM
        draw = partial(_draw_legend, title=title, chunks=chunks, widths=widths, sample=sample)
        out.append((width, height, draw))
    return out
