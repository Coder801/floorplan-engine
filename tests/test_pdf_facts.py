"""Выжимка из векторного PDF: масштаб, размеры, цепочки, надписи."""

from __future__ import annotations

from pathlib import Path

import pytest

from shtroba.service.pdf_facts import describe, extract

# Цифра Helvetica 10 pt — 5,56 pt шириной
DIGIT = 5.56


def _pdf(content: str) -> bytes:
    """Одностраничный PDF 600×400 pt со шрифтом Helvetica."""
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 400] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    trailer = f"<< /Size {len(objects) + 1} /Root 1 0 R >>"
    out += f"trailer\n{trailer}\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def _line(x0: float, y0: float, x1: float, y1: float) -> str:
    return f"{x0} {y0} m {x1} {y1} l S"


def _dim_h(x0: float, x1: float, y: float) -> list[str]:
    """Горизонтальная размерная линия с засечками на концах."""
    return [_line(x0, y, x1, y), *(_line(x - 1, y - 1.5, x + 1, y + 1.5) for x in (x0, x1))]


def _dim_v(x: float, y0: float, y1: float) -> list[str]:
    return [_line(x, y0, x, y1), *(_line(x - 1.5, y - 1, x + 1.5, y + 1) for y in (y0, y1))]


def _text(text: str, x: float, y: float, vertical: bool = False) -> str:
    matrix = "0 1 -1 0" if vertical else "1 0 0 1"
    return f"BT /F1 10 Tf {matrix} {x} {y} Tm ({text}) Tj ET"


def _centered(text: str, mid: float, base: float, vertical: bool = False) -> str:
    start = mid - len(text) * DIGIT / 2
    return _text(text, base, start, True) if vertical else _text(text, start, base)


@pytest.fixture
def sheet(tmp_path: Path) -> Path:
    """Масштаб 1 pt = 10 мм: цепочка 1000 + 2000 + 150 и общий размер 3150 под ней."""
    ops = [
        *_dim_h(100, 200, 100),
        *_dim_h(200, 400, 100),
        *_dim_h(400, 415, 100),
        _centered("1000", 150, 101),
        _centered("2000", 300, 101),
        _text("150", 418, 101),  # не помещается в отрезок 15 pt — вынесена вправо
        *_dim_h(100, 415, 70),
        _centered("3150", 257.5, 71),
        # Вертикальный размер: подпись 2200, нарисовано 230 pt = 2300 мм
        *_dim_v(500, 100, 330),
        _centered("2200", 215, 499, vertical=True),
        _text("H=1100", 200, 200),
        _text("socket for", 300, 250),
        _text("fridge", 305, 238),
        _text("2", 50, 300),
    ]
    path = tmp_path / "sheet.pdf"
    path.write_bytes(_pdf("\n".join(ops)))
    return path


def test_scale_dimensions_and_chain(sheet: Path) -> None:
    (page,) = extract(sheet)
    assert page.scale == pytest.approx(10.0, rel=0.005)
    assert page.scale_dims == 3  # 1000, 2000, 3150; 2200 расходится с чертежом
    values = sorted(d.value for d in page.dimensions)
    assert values == [150, 1000, 2000, 2200, 3150]
    chain = sorted((d for d in page.dimensions if d.chain), key=lambda d: d.start)
    assert [d.value for d in chain] == [1000, 2000, 150]
    vertical = next(d for d in page.dimensions if d.direction == "v")
    assert vertical.drawn == pytest.approx(2300, abs=5)


def test_render(sheet: Path) -> None:
    text = describe(sheet, "source/sheet.pdf")
    assert "### source/sheet.pdf, страница 1" in text
    assert "1 pt = 10.000 мм" in text
    assert "1000 + 2000 + 150 = 3150" in text
    assert "общий размер 3150 (Y=700) — совпадает" in text
    assert "| 2200 | ≠ 2300 | X=5000 | Y=1000 | Y=3300 |" in text
    assert "«socket for fridge»" in text  # строки заметки — одна надпись
    assert "«H=1100» — высота 1100" in text
    assert "Числа без размерной линии" in text and "2 (" in text


def test_no_scale_without_dimensions(tmp_path: Path) -> None:
    path = tmp_path / "text.pdf"
    path.write_bytes(_pdf(_text("plan", 100, 100)))
    (page,) = extract(path)
    assert page.scale is None and not page.dimensions
    assert "Масштаб не найден" in describe(path)


def test_broken_pdf_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4")
    assert "PDF не разобран" in describe(path)


def test_analysis_needs_only_primitives() -> None:
    """Разбор не знает формата: страница из надписей и отрезков, собранная руками (как из
    растрового адаптера), даёт те же размеры и масштаб."""
    from shtroba.service.facts.analysis import page_facts, render
    from shtroba.service.facts.primitives import Label, Segment, Sheet

    def dim(x0: float, x1: float, y: float, value: int) -> tuple[Label, list[Segment]]:
        ticks = [Segment(x - 1, y - 1.5, x + 1, y + 1.5) for x in (x0, x1)]
        mid, w = (x0 + x1) / 2, 4 * DIGIT
        label = Label(str(value), "h", mid - w / 2, mid + w / 2, y, y + 4, 7, confidence=0.9)
        return label, [Segment(x0, y, x1, y), *ticks]

    labels, segments = [], []
    for x0, x1, value in ((50, 150, 1000), (150, 350, 2000), (350, 450, 1000)):
        label, segs = dim(x0, x1, 300, value)
        labels.append(label)
        segments += segs
    sheet = Sheet("scan.png", 1, 600, 400, labels, segments, unit="px", source="raster")
    facts = page_facts(sheet)
    assert facts.scale == pytest.approx(10.0)  # 1000 мм на 100 px
    assert [d.value for d in facts.dimensions] == [1000, 2000, 1000]
    assert len({d.chain for d in facts.dimensions}) == 1  # одна цепочка
    assert "1 px = 10.000 мм" in render([facts])


def test_facts_json_round_trip(sheet: Path) -> None:
    """JSON выжимки (для базы) читается обратно в тот же объект — и тот же Markdown."""
    import json

    from shtroba.service.facts.analysis import ALGO_VERSION, from_dict, render, to_dict

    pages = extract(sheet)
    data = json.loads(json.dumps([to_dict(f) for f in pages]))
    assert data[0]["algo_version"] == ALGO_VERSION and data[0]["source"] == "vector"
    assert all(d["confidence"] == 1.0 for d in data[0]["dimensions"])
    back = [from_dict(d) for d in data]
    assert back == pages and render(back) == render(pages)
