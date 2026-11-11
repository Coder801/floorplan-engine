"""Source → page primitives: the adapter is picked automatically, per file and per page.

- an image (JPEG, PNG, TIFF…) goes to raster;
- a PDF goes page by page: with vector text (MIN_VECTOR_CHARS characters or more) it is
  vector; without it (a scan, a sheet pasted as an image, text as curves) the page is
  rendered and goes to raster.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber

from floorplan_engine.service.facts.primitives import Sheet
from floorplan_engine.service.facts.raster import IMAGE_TYPES, RENDER_DPI, read_image, render_page
from floorplan_engine.service.facts.vector import page_sheet

MIN_VECTOR_CHARS = 20

# CAD drawings: reading DWG and DXF is in development (decision 2026-11-11). Until then such a
# file is named and the client is asked for a PDF of it; the drawing is not parsed
CAD_TYPES = frozenset({".dwg", ".dxf"})
CAD_PENDING = (
    "чтение DWG и DXF в разработке, пока не разбирается: сохраните чертёж в PDF "
    "(в AutoCAD — печать в PDF) и пришлите его"
)


def is_cad(path: Path) -> bool:
    return path.suffix.lower() in CAD_TYPES


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_TYPES


def read_source(path: Path, name: str | None = None) -> list[Sheet]:
    """Source pages as primitives; each has source set to vector or raster."""
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
