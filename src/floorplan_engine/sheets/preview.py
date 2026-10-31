"""PNG-превью листов DXF через ezdxf.addons.drawing + matplotlib: светлый фон, 150 dpi.

Рисуется лист целиком: рамка, штамп, панели и видовые экраны с моделью (заморожённые
в видовом экране слои ezdxf не показывает, как и AutoCAD).
"""

from __future__ import annotations

import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from ezdxf.addons.drawing.backend import BackendInterface
from ezdxf.addons.drawing.config import Configuration, LineweightPolicy
from ezdxf.addons.drawing.frontend import Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf.addons.drawing.properties import LayoutProperties, RenderContext
from ezdxf.document import Drawing
from ezdxf.layouts.layout import Paperspace
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from floorplan_engine.drawing.layers import register_fonts

PREVIEW_DPI = 150
BACKGROUND = "#ffffff"
LONG_SIDE_INCHES = 14.0
MARGIN = 0.03
EDGE_PAD = 0.005

# Цвета ACI, плохо видимые на белом фоне, → более тёмные оттенки (только в превью)
_DARKEN = {
    "#ffff00": "#a07800",  # 2 жёлтый
    "#00ff00": "#008a00",  # 3 зелёный
    "#00ffff": "#00838f",  # 4 голубой
    "#ff00ff": "#9c27b0",  # 6 пурпурный
}


def _darken_colors(entity: Any, properties: Any) -> None:
    color = str(properties.color).lower()[:7]
    if color in _DARKEN:
        properties.color = _DARKEN[color]


def frozen_in_viewports(layout: Paperspace) -> set[str]:
    """Слои, замороженные в видовых экранах листа (имена в верхнем регистре)."""
    return {name.upper() for vp in layout.viewports() for name in vp.frozen_layers}


def _hide_layers(layout: Paperspace, names: set[str]) -> Callable[[Any, Any], None]:
    """ezdxf не применяет заморозку видового экрана к примитивам внутри блоков (слой 0
    наследует слой вставки), поэтому символы УГО прячем сами по итоговому слою.
    То, что нарисовано прямо на листе, не трогаем."""
    sheet_owner = layout.layout_key

    def hide(entity: Any, properties: Any) -> None:
        if entity.dxf.owner != sheet_owner and properties.layer.upper() in names:
            properties.is_visible = False

    return hide


def sheet_layouts(doc: Drawing) -> list[Paperspace]:
    """Листы документа в порядке вкладок."""
    return [doc.paperspace(name) for name in doc.layout_names_in_taborder() if name != "Model"]


def draw_sheet_layout(
    doc: Drawing, layout: Paperspace, backend: BackendInterface, config: Configuration
) -> None:
    """Отрисовать лист движком ezdxf в любой бэкенд — так же для PNG и для артефакта:
    белый фон, тёмные варианты светлых цветов, заморозка слоёв видовых экранов и в блоках."""
    register_fonts()
    frontend = Frontend(RenderContext(doc), backend, config=config)
    frontend.push_property_override_function(_darken_colors)
    frontend.push_property_override_function(_hide_layers(layout, frozen_in_viewports(layout)))
    props = LayoutProperties.from_layout(layout)
    props.set_colors(BACKGROUND)
    # Штриховку ezdxf сдвигает на случайные доли миллиметра (чтобы линии не шли через
    # вершины). Фиксируем случайность на время листа: одинаковый документ — одинаковые байты
    state = random.getstate()
    random.seed(0)
    try:
        # finalize бэкенда matplotlib перестраивает фигуру — кадр задаёт save_axes
        frontend.draw_layout(layout, finalize=False, layout_properties=props)
    finally:
        random.setstate(state)


def paper_size(layout: Paperspace) -> tuple[float, float]:
    """Ширина и высота листа, мм."""
    return layout.dxf_layout.dxf.paper_width, layout.dxf_layout.dxf.paper_height


def render_png(doc: Drawing, layout: Paperspace, png_path: Path, dpi: int = PREVIEW_DPI) -> Path:
    """Отрисовать лист в PNG по размеру бумаги."""
    width, height = paper_size(layout)
    scale = LONG_SIDE_INCHES / max(width, height)
    fig = plt.figure(figsize=(width * scale, height * scale), dpi=dpi)
    try:
        ax = fig.add_axes((MARGIN, MARGIN, 1 - 2 * MARGIN, 1 - 2 * MARGIN))
        config = Configuration(lineweight_policy=LineweightPolicy.RELATIVE)
        draw_sheet_layout(doc, layout, MatplotlibBackend(ax), config)
        save_axes(fig, ax, width, height, png_path, dpi)
    finally:
        plt.close(fig)
    return png_path


def save_axes(fig: Figure, ax: Axes, width: float, height: float, png_path: Path, dpi: int) -> None:
    """Кадр — лист целиком с небольшим полем, белый фон."""
    pad = max(width, height) * EDGE_PAD
    ax.set_aspect("equal", "datalim")
    ax.set_xlim(-pad, width + pad)
    ax.set_ylim(-pad, height + pad)
    ax.axis("off")
    ax.set_facecolor(BACKGROUND)
    fig.patch.set_facecolor(BACKGROUND)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=dpi, facecolor=BACKGROUND)
