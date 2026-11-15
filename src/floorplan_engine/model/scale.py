"""Sheet scale: the denominator the model is drawn for (50 means 1:50). "On sheet" sizes (text
height, symbol depth, route clearance from a wall) are multiplied by it, so calculations in
model mm depend on the scale too: point anchors, routes, boxes. The scale is a build
parameter (drawing_scale); the whole set is drawn at one scale.

Every project is drawn at 1:25 (decision 2026-11-15): labels and lines keep the same size
against the plan in every project, on screen and on paper, and the tables never change the
model. 1:50, then 1:100 only for a plan that does not fit the largest paper (a large house).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

DEFAULT_SCALE = 25.0
# Scales the set may be drawn at, the preferred one first; the next one only if the plan does
# not fit the largest paper (sheets.choose_paper_and_scale)
SCALES = (DEFAULT_SCALE, 50.0, 100.0)
_SCALE: ContextVar[float] = ContextVar("sheet_scale", default=DEFAULT_SCALE)


def sheet_scale() -> float:
    """Denominator of the sheet scale the model is drawn for now (50 means 1:50)."""
    return _SCALE.get()


@contextmanager
def drawing_scale(scale: float) -> Iterator[None]:
    """Draw the model for sheet scale 1:scale."""
    token = _SCALE.set(scale)
    try:
        yield
    finally:
        _SCALE.reset(token)


def sheet(mm: float) -> float:
    """Convert an "on sheet" size → model size at the current scale."""
    return mm * _SCALE.get()
