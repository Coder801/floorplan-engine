"""Растровый адаптер: чистые функции без OCR (плитки, выпрямление, склейка, надписи)."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from shtroba.service.facts.analysis import page_facts
from shtroba.service.facts.primitives import Label, Segment, Sheet
from shtroba.service.facts.raster import Word, _label, dedupe, merge, snap, tiles


def test_tiles_cover_image_with_overlap() -> None:
    assert tiles(800, 600, size=1000, overlap=100) == [(0, 0)]  # меньше плитки — одна
    starts = tiles(2500, 1000, size=1000, overlap=200)
    xs = sorted({x for x, _ in starts})
    assert xs[0] == 0 and xs[-1] == 1500  # последняя плитка — вплотную к краю
    assert all(b - a <= 800 for a, b in itertools.pairwise(xs))  # шаг с перекрытием


def test_snap_straightens_near_axis_lines() -> None:
    assert snap(0, 10, 100, 11) == (0, 10.5, 100, 10.5)
    assert snap(5, 0, 6, 200) == (5.5, 0, 5.5, 200)
    assert snap(0, 0, 10, 10) == (0, 0, 10, 10)  # засечка 45° — как есть


def test_merge_joins_collinear_pieces_only() -> None:
    pieces = [(0, 10, 40, 10), (42, 10.5, 90, 10.5), (0, 30, 40, 30), (5, 5, 9, 9)]
    out = merge(pieces)
    flat = sorted((a, b) for a, y, b, y2 in out if y == y2 and abs(y - 10) < 1)
    assert flat == [(0, 90)]  # зазор 2 px — один отрезок
    assert (0, 30, 40, 30) in out and (5, 5, 9, 9) in out


def test_dedupe_keeps_confident_word() -> None:
    a = Word("3842", 0.99, 0, 0, 40, 10, False)
    b = Word("3842", 0.7, 2, 0, 41, 10, False)  # та же строка из соседней плитки
    c = Word("120", 0.9, 100, 0, 130, 10, False)
    assert dedupe([b, a, c]) == [a, c]


def test_word_to_label_in_points_y_up() -> None:
    # Картинка 1000 px высотой, 144 dpi: 1 px = 0,5 pt
    h = Word("3842", 0.9, 100, 200, 180, 220, False)
    lab = _label(h, 1000, 0.5)
    assert (lab.direction, lab.a0, lab.a1) == ("h", 50, 90)
    assert lab.base == pytest.approx((1000 - 220) * 0.5)  # низ строки, Y вверх
    assert lab.confidence == 0.9
    v = Word("1300", 0.8, 300, 400, 320, 480, True)
    lv = _label(v, 1000, 0.5)
    assert lv.direction == "v" and lv.base == 160 and (lv.a0, lv.a1) == (260, 300)


def test_merged_chain_line_split_by_ticks_on_raster() -> None:
    """Растр: звенья цепочки слиты в одну линию; размер ищется между засечками у подписи."""
    line = Segment(0, 100, 300, 100)
    ticks = [Segment(x - 1, 98.5, x + 1, 101.5) for x in (0, 100, 300)]

    def label(text: str, mid: float) -> Label:
        return Label(text, "h", mid - 10, mid + 10, 101, 104, 6, confidence=0.9)

    labels = [label("1000", 50), label("2000", 200)]
    raster = Sheet("scan.png", 1, 400, 200, labels, [line, *ticks], source="raster", tolerance=3)
    facts = page_facts(raster)
    assert sorted((d.value, d.start, d.end) for d in facts.dimensions) == [
        (1000, 0, 100),
        (2000, 100, 300),
    ]
    assert all(d.confidence == 0.9 for d in facts.dimensions)
    vector = Sheet("plan.pdf", 1, 400, 200, labels, [line, *ticks])  # вектор так не делает
    assert page_facts(vector).dimensions == []


def test_gate_page_problems() -> None:
    from shtroba.service.facts.analysis import Dimension, PageFacts
    from shtroba.service.facts.gate import MIN_DIMS, page_problem

    def facts(n: int, scale: float | None, conf: float = 1.0) -> PageFacts:
        dims = [Dimension(1000, "h", 0, 0, 100, confidence=conf) for _ in range(n)]
        return PageFacts("x.pdf", 1, 100, 100, scale=scale, dimensions=dims)

    assert page_problem(facts(MIN_DIMS, None)) == "масштаб не найден"
    assert page_problem(facts(MIN_DIMS - 1, 10.0)) is not None
    assert page_problem(facts(MIN_DIMS, 10.0, conf=0.5)) is not None
    assert page_problem(facts(MIN_DIMS, 10.0)) is None


def test_gate_text_source_always_passes(tmp_path: Path) -> None:
    from shtroba.service.facts.gate import check_sources

    src = tmp_path
    (src / "plan.pdf").write_bytes(b"%PDF")
    gate = check_sources(src)
    assert not gate.ok and gate.reasons[0].startswith("plan.pdf")
    (src / "notes.md").write_text("Кухня 3×4 м", "utf-8")
    assert check_sources(src).ok
