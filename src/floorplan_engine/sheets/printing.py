"""Printing the set: a full-size PDF album of the sheets and a pre-print sheet check (decision
2026-10-28).

A PDF page is exactly the sheet size (A2 is 594 × 420 mm), lines keep their width (mm), text
is converted to curves: printing "actual size" gives the drawing at sheet scale. The paper
size of the set can be given (`print --paper A3`): the sheets are laid out again for that
size, and the scale is picked by the same function as in the build
(`sheets.choose_paper_and_scale`).

Check: the smallest text on each sheet (on paper, mm) is not below MIN_TEXT_MM; nothing
sticks out of the sheet frame (the plan did not fit the paper even at the smallest scale).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from ezdxf import bbox
from ezdxf.addons.drawing.config import Configuration, LineweightPolicy
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf.document import Drawing
from ezdxf.entities.attrib import Attrib
from ezdxf.entities.dxfgfx import DXFGraphic
from ezdxf.entities.insert import Insert
from ezdxf.entities.mtext import MText
from ezdxf.entities.text import Text
from ezdxf.layouts.layout import Paperspace
from matplotlib.backends.backend_pdf import PdfPages

from floorplan_engine import BRAND
from floorplan_engine.drawing.layers import A_SHEET, MIN_TEXT_MM
from floorplan_engine.drawing.titleblock import frame_region
from floorplan_engine.sheets.preview import (
    BACKGROUND,
    draw_sheet_layout,
    frozen_in_viewports,
    paper_size,
    sheet_layouts,
)

MM_PER_INCH = 25.4
PT_PER_MM = 72.0 / MM_PER_INCH  # matplotlib line width is in points
MIN_LINE_MM = 0.1  # nothing prints thinner than this

FRAME_TOL_MM = 0.5  # tolerance for sticking out of the frame (line width)


@dataclass(frozen=True)
class SheetCheck:
    """Sheet before printing: tab name, the smallest text on paper (mm; None if there is no text)
    and how far anything sticks out of the frame (mm, 0 if everything is inside)."""

    tab: str
    min_text: float | None
    overflow: float
    empty: bool = False  # only frame and title block: content did not fit

    def warnings(self) -> list[str]:
        out: list[str] = []
        if self.min_text is not None and self.min_text < MIN_TEXT_MM - 1e-6:
            out.append(
                f"лист «{self.tab}»: текст {self.min_text:.1f} мм — мельче {MIN_TEXT_MM:g} мм, "
                "на печати не прочитать"
            )
        if self.empty:
            out.append(f"лист «{self.tab}» пустой — содержимое не поместилось в формат")
        if self.overflow > FRAME_TOL_MM:
            out.append(
                f"лист «{self.tab}»: чертёж выходит за рамку на {self.overflow:.0f} мм — "
                "не помещается в формат, нужен формат крупнее"
            )
        return out


def write_album(doc: Drawing, path: Path, title: str) -> Path:
    """All document sheets as pages of one PDF, each at its own sheet size."""
    path.parent.mkdir(parents=True, exist_ok=True)
    config = Configuration(
        lineweight_policy=LineweightPolicy.ABSOLUTE,
        lineweight_scaling=PT_PER_MM,
        min_lineweight=MIN_LINE_MM * PT_PER_MM,
    )
    metadata = {"Title": title, "Creator": f"{BRAND} (floorplan-engine)"}
    with PdfPages(path, metadata=metadata) as pdf:
        for layout in sheet_layouts(doc):
            width, height = paper_size(layout)
            fig = plt.figure(figsize=(width / MM_PER_INCH, height / MM_PER_INCH))
            try:
                ax = fig.add_axes((0.0, 0.0, 1.0, 1.0))
                draw_sheet_layout(doc, layout, MatplotlibBackend(ax, adjust_figure=False), config)
                ax.set_xlim(0, width)
                ax.set_ylim(0, height)
                ax.set_aspect("auto")
                ax.axis("off")
                fig.patch.set_facecolor(BACKGROUND)
                pdf.savefig(fig, facecolor=BACKGROUND)
            finally:
                plt.close(fig)
    return path


def check_sheets(doc: Drawing) -> list[SheetCheck]:
    """Smallest text and frame overflow on each sheet."""
    return [_check(doc, layout) for layout in sheet_layouts(doc)]


def _check(doc: Drawing, layout: Paperspace) -> SheetCheck:
    sizes = list(_text_heights(layout))
    frame = frame_region(*paper_size(layout))
    overflow = 0.0
    viewports = [v for v in layout.viewports() if v.dxf.id != 1]
    for vp in viewports:
        c, w, h = vp.dxf.center, vp.dxf.width, vp.dxf.height
        rect = (c.x - w / 2, c.y - h / 2, c.x + w / 2, c.y + h / 2)
        overflow = max(overflow, _beyond(rect, frame))
    # Frame and title block (A-SHEET) are on the frame edge and beyond it by nature (trim line)
    others = [e for e in layout if e.dxftype() != "VIEWPORT" and e.dxf.layer != A_SHEET.name]
    box = bbox.extents(others)
    if box.has_data:
        rect = (box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y)
        overflow = max(overflow, _beyond(rect, frame))
    # Model text goes through a viewport: height on paper = model height / scale
    frozen = {n.upper() for n in frozen_in_viewports(layout)}
    for vp in viewports:
        if vp.dxf.height <= 0:
            continue
        scale = vp.dxf.view_height / vp.dxf.height
        sizes += [h / scale for h in _text_heights(doc.modelspace(), frozen)]
    empty = not viewports and not others
    return SheetCheck(layout.name, min(sizes) if sizes else None, overflow, empty)


def _beyond(
    rect: tuple[float, float, float, float], frame: tuple[float, float, float, float]
) -> float:
    """How many mm the rectangle sticks out of the frame (0 if inside)."""
    x0, y0, x1, y1 = rect
    f0, g0, f1, g1 = frame
    return max(0.0, f0 - x0, g0 - y0, x1 - f1, y1 - g1)


def _text_heights(
    entities: Iterable[DXFGraphic], frozen: set[str] | None = None
) -> Iterator[float]:
    """Heights of non-empty texts, including texts inside blocks (at the insert scale)."""
    for e in _flat(entities):
        if frozen and e.dxf.layer.upper() in frozen:
            continue
        if isinstance(e, MText):
            if str(e.plain_text()).strip():
                yield float(e.dxf.char_height)
        elif isinstance(e, Text) and e.dxf.text.strip():
            # An invisible attribute (ID, group on a symbol) is not printed
            if isinstance(e, Attrib) and e.is_invisible:
                continue
            yield float(e.dxf.height)


def _flat(entities: Iterable[DXFGraphic], depth: int = 0) -> Iterator[DXFGraphic]:
    """Primitives with block contents (up to 4 nesting levels) and insert attributes."""
    for e in entities:
        if isinstance(e, Insert) and depth < 4:
            yield from e.attribs
            yield from _flat(e.virtual_entities(), depth + 1)
        else:
            yield e
