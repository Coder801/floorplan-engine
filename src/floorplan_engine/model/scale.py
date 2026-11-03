"""Sheet scale: the denominator the model is drawn for (50 means 1:50). "On sheet" sizes (text
height, symbol depth, route clearance from a wall) are multiplied by it, so calculations in
model mm depend on the scale too: point anchors, routes, boxes. The scale is a build
parameter (drawing_scale); the whole set is drawn at one scale.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

DEFAULT_SCALE = 50.0
# Scales from large to small, used to pick the sheet scale: the GOST 2.302 series plus
# 1:30, common in interior projects
SCALES = (20.0, 25.0, 30.0, 40.0, 50.0, 75.0, 100.0)
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
