"""Источник → примитивы страниц: адаптер выбирается сам, по файлу и по каждой странице.

- картинка (JPEG, PNG, TIFF…) — растр;
- PDF — постранично: есть векторный текст (MIN_VECTOR_CHARS символов и больше) — вектор,
  нет (скан, лист, вставленный картинкой, текст в кривых) — страница рендерится и идёт
  в растр.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber

from shtroba.service.facts.primitives import Sheet
from shtroba.service.facts.raster import IMAGE_TYPES, RENDER_DPI, read_image, render_page
from shtroba.service.facts.vector import page_sheet

MIN_VECTOR_CHARS = 20


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_TYPES


def read_source(path: Path, name: str | None = None) -> list[Sheet]:
    """Страницы источника как примитивы; у каждой source — vector или raster."""
    name = name or path.name
    if is_image(path):
        return read_image(path, name)
    out: list[Sheet] = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            if len(page.chars) >= MIN_VECTOR_CHARS:
                out.append(page_sheet(page, name, i))
            else:
                out.append(render_page(path, i, name, RENDER_DPI))
    return out
