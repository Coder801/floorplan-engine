"""Разбор примитивов страницы: размеры, масштаб, цепочки, надписи — и выжимка для модели.

Не зависит от формата источника: на входе Sheet (primitives.py) из любого адаптера.

- размер — подпись-число над размерной линией: отрезок параллелен подписи, проходит под
  её серединой, на обоих концах засечки (непараллельные линии через конец отрезка);
- масштаб листа — медиана «подпись / длина отрезка» по согласным размерам. Размер, у
  которого длина на чертеже расходится с подписью, помечается: это вопрос, а не ошибка
  разбора;
- цепочки — размерные отрезки на одной линии, которые стыкуются концами;
- строки одной заметки — в одну надпись.

Стены, символы и выноски не распознаются — это остаётся модели. Координаты в выжимке —
мм в масштабе чертежа от левого нижнего угла листа (X вправо, Y вверх).
"""

from __future__ import annotations

import itertools
import re
import statistics
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from typing import Any

from shtroba.service.facts.primitives import Direction, Label, Segment, Sheet

LINE_DIST = 0.8  # размерная линия не дальше этой доли высоты от базовой линии подписи
TICK_TOL = 0.6  # pt: засечка проходит через конец отрезка с этим допуском
SCALE_BAND = 0.015  # согласные размеры — в пределах 1,5 % от моды масштаба
MIN_SCALE_DIMS = 3
JOIN_TOL = 0.6  # pt: стык отрезков цепочки и общая линия
OVERALL_DIST = 40.0  # pt: общий размер — на соседней размерной линии, не у другой стены
# Версия разбора: меняется вместе с правилами — по ней в базе отличают старые выжимки
ALGO_VERSION = "facts-1"
# Множитель допусков TICK_TOL и JOIN_TOL для текущей страницы (Sheet.tolerance)
_TOLERANCE: ContextVar[float] = ContextVar("facts_tolerance", default=1.0)


def _tol(value: float) -> float:
    return value * _TOLERANCE.get()


HEIGHT = re.compile(r"[НH]\s*=\s*(\d+)")


@dataclass
class Dimension:
    value: int
    direction: Direction
    line: float  # pt: Y горизонтальной размерной линии или X вертикальной
    start: float  # pt вдоль линии
    end: float
    chain: int | None = None
    drawn: float | None = None  # мм по масштабу; None — масштаба нет
    confidence: float = 1.0  # уверенность в подписи: у вектора 1, у OCR — его оценка

    @property
    def length(self) -> float:
        return self.end - self.start


@dataclass
class PageFacts:
    file: str
    page: int
    width: float
    height: float
    unit: str = "pt"
    source: str = "vector"  # адаптер: vector | raster
    tolerance: float = 1.0  # множитель допусков разбора (Sheet.tolerance)
    scale: float | None = None  # мм на единицу источника (pt, px)
    scale_dims: int = 0
    scale_spread: float = 0.0  # %, разброс согласных размеров
    dimensions: list[Dimension] = field(default_factory=list)
    loose_numbers: list[Label] = field(default_factory=list)  # числа без размерной линии
    texts: list[Label] = field(default_factory=list)


def _blocks(labels: list[Label]) -> list[Label]:
    """Строки одной заметки — в одну надпись: друг под другом, с перекрытием по ширине.

    Координата блока — его первая (верхняя) строка.
    """
    out: list[tuple[Label, Label]] = []  # (блок, его последняя строка)
    for label in sorted(labels, key=lambda t: (t.direction, -t.perp, t.a0)):
        for i in range(len(out) - 1, -1, -1):
            block, last = out[i]
            step = last.perp - label.perp
            overlap = min(last.a1, label.a1) - max(last.a0, label.a0)
            if (
                last.direction == label.direction == "h"
                and 0 < step <= 1.4 * max(last.height, label.height)
                and overlap >= 0.5 * min(last.a1 - last.a0, label.a1 - label.a0)
            ):
                block.text += " " + label.text
                block.a0, block.a1 = min(block.a0, label.a0), max(block.a1, label.a1)
                out[i] = (block, label)
                break
        else:
            out.append((Label(**vars(label)), label))
    return [block for block, _ in out]


def _span(seg: Segment, direction: Direction) -> tuple[float, float, float]:
    """(линия, начало, конец) отрезка в осях размера."""
    if direction == "h":
        return seg.y0, min(seg.x0, seg.x1), max(seg.x0, seg.x1)
    return seg.x0, min(seg.y0, seg.y1), max(seg.y0, seg.y1)


def _has_tick(segments: list[Segment], seg: Segment, x: float, y: float) -> bool:
    return any(
        s is not seg and s.direction != seg.direction and s.passes_near(x, y, _tol(TICK_TOL))
        for s in segments
    )


def _dimension_lines(label: Label, segments: list[Segment]) -> list[Segment]:
    """Размерные отрезки у базовой линии подписи: параллельны ей, с засечками на концах."""
    out = []
    for seg in segments:
        if seg.direction != label.direction:
            continue
        line, start, end = _span(seg, label.direction)
        if abs(line - label.base) > LINE_DIST * label.height:
            continue
        ends = (
            [(start, line), (end, line)] if label.direction == "h" else [(line, start), (line, end)]
        )
        if all(_has_tick(segments, seg, x, y) for x, y in ends):
            out.append(seg)
    return out


def _centered(label: Label, segments: list[Segment]) -> Dimension | None:
    """Подпись стоит по середине своего отрезка — обычное положение размера."""
    value = label.number
    if value is None or value < 10:
        return None
    tol = 0.25 * (label.a1 - label.a0) + _tol(JOIN_TOL)
    for seg in _dimension_lines(label, segments):
        line, start, end = _span(seg, label.direction)
        if abs((start + end) / 2 - label.mid) <= tol and end - start >= label.a1 - label.a0:
            return Dimension(value, label.direction, line, start, end, confidence=label.confidence)
    return None


def _crossings(seg: Segment, segments: list[Segment]) -> list[float]:
    """Где линию seg пересекают непараллельные отрезки (засечки, выносные), вдоль неё."""
    direction = seg.direction or "h"
    line, start, end = _span(seg, direction)
    tol = _tol(TICK_TOL)
    out = []
    for s in segments:
        if s is seg or s.direction == seg.direction:
            continue
        # В осях линии: u — вдоль, w — поперёк
        (u0, w0, u1, w1) = (
            (s.x0, s.y0, s.x1, s.y1) if direction == "h" else (s.y0, s.x0, s.y1, s.x1)
        )
        if w0 == w1 or not min(w0, w1) - tol <= line <= max(w0, w1) + tol:
            continue
        t = u0 + (u1 - u0) * (line - w0) / (w1 - w0)
        if start - tol <= t <= end + tol:
            out.append(t)
    return sorted(out)


def _centered_span(label: Label, segments: list[Segment]) -> Dimension | None:
    """Неточные примитивы (растр): размерная линия под подписью может быть слита с соседними
    звеньями цепочки. Звено — ближайшая к подписи пара пересечений линии, середина которой
    совпадает с серединой подписи."""
    value = label.number
    if value is None or value < 10:
        return None
    width = label.a1 - label.a0
    tol = 0.25 * width + _tol(JOIN_TOL)
    best: tuple[float, Dimension] | None = None
    for seg in segments:
        if seg.direction != label.direction:
            continue
        line, start, end = _span(seg, label.direction)
        if abs(line - label.base) > LINE_DIST * label.height or not start < label.mid < end:
            continue
        cuts = _crossings(seg, segments)
        left = [t for t in cuts if t < label.mid]
        right = [t for t in cuts if t > label.mid]
        for a in reversed(left):
            for b in right:
                if b - a < width or abs((a + b) / 2 - label.mid) > tol:
                    continue
                if best is None or b - a < best[0]:
                    dim = Dimension(value, label.direction, line, a, b, confidence=label.confidence)
                    best = (b - a, dim)
                break
    return best[1] if best else None


def _moved_out(label: Label, segments: list[Segment], scale: float) -> Dimension | None:
    """Подпись вынесена за короткий отрезок: ближайший отрезок рядом той же длины по масштабу."""
    value = label.number
    if value is None or value < 10:
        return None
    best: tuple[float, Dimension] | None = None
    for seg in _dimension_lines(label, segments):
        line, start, end = _span(seg, label.direction)
        if abs((end - start) * scale - value) > max(10.0, 0.01 * value):
            continue
        gap = max(start - label.a1, label.a0 - end, 0.0)
        if gap <= 3 * label.height and (best is None or gap < best[0]):
            dim = Dimension(value, label.direction, line, start, end, confidence=label.confidence)
            best = (gap, dim)
    return best[1] if best else None


def _scale(dims: list[Dimension]) -> tuple[float | None, int, float]:
    ratios = [d.value / d.length for d in dims if d.length > 0]
    if len(ratios) < MIN_SCALE_DIMS:
        return None, 0, 0.0
    mode = max(ratios, key=lambda r: sum(abs(t / r - 1) <= SCALE_BAND for t in ratios))
    agreed = [t for t in ratios if abs(t / mode - 1) <= SCALE_BAND]
    if len(agreed) < MIN_SCALE_DIMS:
        return None, 0, 0.0
    scale = statistics.median(agreed)
    spread = max(abs(t / scale - 1) for t in agreed) * 100
    return scale, len(agreed), spread


def _chains(dims: list[Dimension]) -> None:
    """Номер цепочки — у отрезков на одной линии, которые стыкуются концами."""
    ordered = sorted(dims, key=lambda d: (d.direction, round(d.line, 0), d.start))
    chain_no = 0
    for prev, cur in itertools.pairwise(ordered):
        joined = (
            prev.direction == cur.direction
            and abs(prev.line - cur.line) <= _tol(JOIN_TOL)
            and abs(prev.end - cur.start) <= _tol(JOIN_TOL)
        )
        if not joined:
            continue
        if prev.chain is None:
            chain_no += 1
            prev.chain = chain_no
        cur.chain = prev.chain


def page_facts(sheet: Sheet) -> PageFacts:
    token = _TOLERANCE.set(sheet.tolerance)
    try:
        return _page_facts(sheet)
    finally:
        _TOLERANCE.reset(token)


def _page_facts(sheet: Sheet) -> PageFacts:
    labels, segments = sheet.labels, sheet.segments
    facts = PageFacts(
        sheet.file, sheet.page, sheet.width, sheet.height, sheet.unit, sheet.source, sheet.tolerance
    )
    numbers: list[Label] = []
    loose = sheet.tolerance > 1.0  # неточные примитивы: звено ищется и внутри длинной линии
    for label in labels:
        dim = _centered(label, segments) or (_centered_span(label, segments) if loose else None)
        if dim is not None:
            facts.dimensions.append(dim)
        elif label.number is not None:
            numbers.append(label)
        else:
            facts.texts.append(label)
    facts.scale, facts.scale_dims, facts.scale_spread = _scale(facts.dimensions)
    for label in numbers:
        dim = _moved_out(label, segments, facts.scale) if facts.scale else None
        if dim is not None:
            facts.dimensions.append(dim)
        else:
            facts.loose_numbers.append(label)
    facts.texts = _blocks(facts.texts)
    if facts.scale:
        for d in facts.dimensions:
            d.drawn = d.length * facts.scale
    _chains(facts.dimensions)
    return facts


# --- Текст для модели --------------------------------------------------------------


def _mismatch(d: Dimension) -> bool:
    return d.drawn is not None and abs(d.drawn - d.value) > max(10.0, 0.01 * d.value)


def _overall(dims: list[Dimension], chain: list[Dimension]) -> list[Dimension]:
    """Размеры вне цепочки от её начала до конца: общий размер над или под цепочкой."""
    start, end = chain[0].start, chain[-1].end
    return [
        d
        for d in dims
        if d.chain != chain[0].chain
        and d.direction == chain[0].direction
        and abs(d.line - chain[0].line) <= OVERALL_DIST
        and abs(d.start - start) <= _tol(JOIN_TOL)
        and abs(d.end - end) <= _tol(JOIN_TOL)
    ]


def render(pages: list[PageFacts]) -> str:
    out: list[str] = []
    for f in pages:
        token = _TOLERANCE.set(f.tolerance)
        try:
            out += _render_page(f)
        finally:
            _TOLERANCE.reset(token)
    return "\n".join(out)


def _render_page(f: PageFacts) -> list[str]:
    k = f.scale or 1.0

    def c(v: float) -> int:  # координата для модели: мм по масштабу или единицы источника
        return round(v * k)

    out = [f"### {f.file}, страница {f.page}", _scale_line(f)]
    if f.dimensions:
        out += _dimensions_table(f, c)
        out += _chain_lines(f, c)
    unit = "мм" if f.scale else f.unit
    if f.loose_numbers:
        out.append(f"\nЧисла без размерной линии (центр, {unit}):")
        out.append(
            "; ".join(
                f"{n.text} ({c(n.point()[0])}, {c(n.point()[1])})"
                + (" верт." if n.direction == "v" else "")
                for n in f.loose_numbers
            )
        )
    if f.texts:
        out.append(f"\nНадписи (центр, {unit}):")
        for t in sorted(f.texts, key=lambda t: (-round(t.point()[1]), t.point()[0])):
            x, y = t.point()
            heights = [m.group(1) for m in HEIGHT.finditer(t.text)]
            note = f" — высота {', '.join(heights)}" if heights else ""
            vert = " (верт.)" if t.direction == "v" else ""
            out.append(f"- ({c(x)}, {c(y)}) «{t.text}»{vert}{note}")
    out.append("")
    return out


def _scale_line(f: PageFacts) -> str:
    if f.scale:
        return (
            f"Масштаб листа: 1 {f.unit} = {f.scale:.3f} мм — по {f.scale_dims} размерам из "
            f"{len(f.dimensions)}, разброс ±{f.scale_spread:.1f} %. Координаты — мм в "
            "масштабе чертежа от левого нижнего угла листа: X вправо, Y вверх."
        )
    return (
        f"Масштаб не найден (меньше трёх согласных размеров). Координаты — {f.unit} от "
        "левого нижнего угла листа: X вправо, Y вверх."
    )


def _dimensions_table(f: PageFacts, c: Callable[[float], int]) -> list[str]:
    """Таблица размеров: подпись, длина по чертежу (≠ — расходится), линия и концы."""
    out = [
        "\nРазмеры (подпись над размерной линией с засечками). «По чертежу» — длина "
        "линии по масштабу; ≠ — подпись расходится с чертежом.",
        "| Подпись | По чертежу | Линия | От | До | Цепочка |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for d in sorted(f.dimensions, key=lambda d: (d.direction, -d.line, d.start)):
        axis, along = ("Y", "X") if d.direction == "h" else ("X", "Y")
        drawn = "—" if d.drawn is None else f"{d.drawn:.0f}"
        if _mismatch(d):
            drawn = f"≠ {drawn}"
        chain = f"c{d.chain}" if d.chain else ""
        out.append(
            f"| {d.value} | {drawn} | {axis}={c(d.line)} | {along}={c(d.start)} | "
            f"{along}={c(d.end)} | {chain} |"
        )
    return out


def _chain_lines(f: PageFacts, c: Callable[[float], int]) -> list[str]:
    """Цепочки: сумма подписей, концы и сверка с общим размером рядом."""
    chains: dict[int, list[Dimension]] = {}
    for d in f.dimensions:
        if d.chain:
            chains.setdefault(d.chain, []).append(d)
    if not chains:
        return []
    out = ["\nЦепочки (сумма подписей; от–до — концы на чертеже):"]
    for no, ds in sorted(chains.items()):
        ds.sort(key=lambda d: d.start)
        axis, along = ("Y", "X") if ds[0].direction == "h" else ("X", "Y")
        total = sum(d.value for d in ds)
        line = (
            f"- c{no} ({axis}={c(ds[0].line)}): "
            f"{' + '.join(str(d.value) for d in ds)} = {total}; "
            f"{along} от {c(ds[0].start)} до {c(ds[-1].end)}"
        )
        for o in _overall(f.dimensions, ds):
            verdict = "совпадает" if o.value == total else "≠ сумме"
            line += f"; общий размер {o.value} ({axis}={c(o.line)}) — {verdict}"
        out.append(line)
    return out


def to_dict(f: PageFacts) -> dict[str, Any]:
    """Выжимка страницы для JSON и базы (колонка facts); обратно — from_dict."""
    return {"algo_version": ALGO_VERSION, **asdict(f)}


def from_dict(data: dict[str, Any]) -> PageFacts:
    fields = {k: v for k, v in data.items() if k != "algo_version"}
    fields["dimensions"] = [Dimension(**d) for d in data.get("dimensions", [])]
    fields["loose_numbers"] = [Label(**t) for t in data.get("loose_numbers", [])]
    fields["texts"] = [Label(**t) for t in data.get("texts", [])]
    return PageFacts(**fields)
