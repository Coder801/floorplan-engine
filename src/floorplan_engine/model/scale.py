"""Масштаб листа: знаменатель, под который рисуется модель (50 — это 1:50). Размеры «на листе»
(высота текста, глубина символа, отступ трассы от стены) умножаются на него — поэтому от
масштаба зависят и расчёты в мм модели: якоря точек, трассы, коробки. Масштаб — параметр
сборки (drawing_scale); весь комплект рисуется в одном масштабе.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

DEFAULT_SCALE = 50.0
# Масштабы от крупного к мелкому — из них подбирается масштаб листов: ряд ГОСТ 2.302
# и 1:30, принятый в интерьерных проектах
SCALES = (20.0, 25.0, 30.0, 40.0, 50.0, 75.0, 100.0)
_SCALE: ContextVar[float] = ContextVar("sheet_scale", default=DEFAULT_SCALE)


def sheet_scale() -> float:
    """Знаменатель масштаба листа, по которому сейчас рисуется модель (50 — это 1:50)."""
    return _SCALE.get()


@contextmanager
def drawing_scale(scale: float) -> Iterator[None]:
    """Рисовать модель под масштаб листа 1:scale."""
    token = _SCALE.set(scale)
    try:
        yield
    finally:
        _SCALE.reset(token)


def sheet(mm: float) -> float:
    """Размер «на листе» → размер в модели при текущем масштабе."""
    return mm * _SCALE.get()
