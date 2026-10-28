"""Печать комплекта: PDF-альбом листов в натуральную величину и проверка листа перед
печатью (решение 2026-10-28).

Страница PDF — ровно формат листа (A2 — 594 × 420 мм), линии — в своей толщине (мм),
текст — кривыми: печать «в размер» даёт чертёж в масштабе листа. Формат комплекта можно
задать (`print --paper A3`) — листы раскладываются заново под этот формат, масштаб
подбирается тот же функцией, что при сборке (`sheets.choose_paper_and_scale`).

Проверка: самый мелкий текст на каждом листе (на бумаге, мм) — не мельче MIN_TEXT_MM;
ничего не выходит за рамку листа (план не влез в формат даже в самом мелком масштабе).
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

from floorplan_engine.layers import A_SHEET, MIN_TEXT_MM
from floorplan_engine.preview import (
    BACKGROUND,
    draw_sheet_layout,
    frozen_in_viewports,
    paper_size,
    sheet_layouts,
)
from floorplan_engine.titleblock import frame_region

MM_PER_INCH = 25.4
PT_PER_MM = 72.0 / MM_PER_INCH  # толщина линии в matplotlib — в пунктах
MIN_LINE_MM = 0.1  # тоньше на печати не бывает

FRAME_TOL_MM = 0.5  # допуск выхода за рамку (толщина линий)


@dataclass(frozen=True)
class SheetCheck:
    """Лист перед печатью: имя вкладки, самый мелкий текст на бумаге (мм; текста нет — None)
    и насколько что-то вылезает за рамку (мм, 0 — всё внутри)."""

    tab: str
    min_text: float | None
    overflow: float
    empty: bool = False  # на листе только рамка и штамп: схема или таблицы не поместились

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
    """Все листы документа — страницами одного PDF, каждая в размер своего листа."""
    path.parent.mkdir(parents=True, exist_ok=True)
    config = Configuration(
        lineweight_policy=LineweightPolicy.ABSOLUTE,
        lineweight_scaling=PT_PER_MM,
        min_lineweight=MIN_LINE_MM * PT_PER_MM,
    )
    metadata = {"Title": title, "Creator": "Штроба (floorplan-engine)"}
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
    """Самый мелкий текст и выход за рамку на каждом листе."""
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
    # Рамка и штамп (A-SHEET) — сами по себе на краю рамки и за ней (линия обреза)
    others = [e for e in layout if e.dxftype() != "VIEWPORT" and e.dxf.layer != A_SHEET.name]
    box = bbox.extents(others)
    if box.has_data:
        rect = (box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y)
        overflow = max(overflow, _beyond(rect, frame))
    # Текст модели — через видовой экран: высота на бумаге = высота в модели / масштаб
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
    """На сколько мм прямоугольник выходит за рамку (0 — внутри)."""
    x0, y0, x1, y1 = rect
    f0, g0, f1, g1 = frame
    return max(0.0, f0 - x0, g0 - y0, x1 - f1, y1 - g1)


def _text_heights(
    entities: Iterable[DXFGraphic], frozen: set[str] | None = None
) -> Iterator[float]:
    """Высоты непустых текстов, с текстами внутри блоков (в масштабе вставки)."""
    for e in _flat(entities):
        if frozen and e.dxf.layer.upper() in frozen:
            continue
        if isinstance(e, MText):
            if str(e.plain_text()).strip():
                yield float(e.dxf.char_height)
        elif isinstance(e, Text) and e.dxf.text.strip():
            # Невидимый атрибут (ID, группа у символа) не печатается
            if isinstance(e, Attrib) and e.is_invisible:
                continue
            yield float(e.dxf.height)


def _flat(entities: Iterable[DXFGraphic], depth: int = 0) -> Iterator[DXFGraphic]:
    """Примитивы с содержимым блоков (до 4 уровней вложенности) и атрибутами вставок."""
    for e in entities:
        if isinstance(e, Insert) and depth < 4:
            yield from e.attribs
            yield from _flat(e.virtual_entities(), depth + 1)
        else:
            yield e
