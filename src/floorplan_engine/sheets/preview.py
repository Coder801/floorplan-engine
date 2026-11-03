"""PNG previews of DXF sheets via ezdxf.addons.drawing + matplotlib: light background, 150 dpi.

The whole sheet is drawn: frame, title block, panels and viewports with the model (ezdxf, like
AutoCAD, does not show layers frozen in a viewport).
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

# ACI colours that are hard to see on white → darker shades (preview only)
_DARKEN = {
    "#ffff00": "#a07800",  # 2 yellow
    "#00ff00": "#008a00",  # 3 green
    "#00ffff": "#00838f",  # 4 cyan
    "#ff00ff": "#9c27b0",  # 6 magenta
}


def _darken_colors(entity: Any, properties: Any) -> None:
    color = str(properties.color).lower()[:7]
    if color in _DARKEN:
        properties.color = _DARKEN[color]


def frozen_in_viewports(layout: Paperspace) -> set[str]:
    """Layers frozen in the sheet viewports (names in upper case)."""
    return {name.upper() for vp in layout.viewports() for name in vp.frozen_layers}


def _hide_layers(layout: Paperspace, names: set[str]) -> Callable[[Any, Any], None]:
    """ezdxf does not apply viewport freezing to primitives inside blocks (layer 0 inherits the
    insert layer), so symbol blocks are hidden by hand by their effective layer.
    What is drawn directly on the sheet is left alone."""
    sheet_owner = layout.layout_key

    def hide(entity: Any, properties: Any) -> None:
        if entity.dxf.owner != sheet_owner and properties.layer.upper() in names:
            properties.is_visible = False

    return hide


def sheet_layouts(doc: Drawing) -> list[Paperspace]:
    """Document sheets in tab order."""
    return [doc.paperspace(name) for name in doc.layout_names_in_taborder() if name != "Model"]


def draw_sheet_layout(
    doc: Drawing, layout: Paperspace, backend: BackendInterface, config: Configuration
) -> None:
    """Draw a sheet with the ezdxf engine into any backend, the same for PNG and for the artifact:
    white background, dark variants of light colours, viewport layer freezing also inside blocks."""
    register_fonts()
    frontend = Frontend(RenderContext(doc), backend, config=config)
    frontend.push_property_override_function(_darken_colors)
    frontend.push_property_override_function(_hide_layers(layout, frozen_in_viewports(layout)))
    props = LayoutProperties.from_layout(layout)
    props.set_colors(BACKGROUND)
    # ezdxf shifts hatching by random fractions of a millimetre (so lines do not pass through
    # vertices). Fix the randomness for the sheet: the same document gives the same bytes
    state = random.getstate()
    random.seed(0)
    try:
        # the matplotlib backend's finalize rebuilds the figure, so save_axes sets the frame
        frontend.draw_layout(layout, finalize=False, layout_properties=props)
    finally:
        random.setstate(state)


def paper_size(layout: Paperspace) -> tuple[float, float]:
    """Sheet width and height, mm."""
    return layout.dxf_layout.dxf.paper_width, layout.dxf_layout.dxf.paper_height


def render_png(doc: Drawing, layout: Paperspace, png_path: Path, dpi: int = PREVIEW_DPI) -> Path:
    """Draw the sheet to a PNG at paper size."""
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
    """Frame: the whole sheet with a small margin, white background."""
    pad = max(width, height) * EDGE_PAD
    ax.set_aspect("equal", "datalim")
    ax.set_xlim(-pad, width + pad)
    ax.set_ylim(-pad, height + pad)
    ax.axis("off")
    ax.set_facecolor(BACKGROUND)
    fig.patch.set_facecolor(BACKGROUND)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=dpi, facecolor=BACKGROUND)
