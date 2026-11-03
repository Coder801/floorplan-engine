"""Electrical symbol blocks (simplified, following project legends: sockets, switches, lights,
low-voltage).

Block local system: the insert point is on the inner wall face, the wall runs along X, the
room is towards +Y. Ceiling symbols are centred on the insert point. Block unit is 1 sheet mm:
in the model the block is inserted with the sheet scale factor (50 at 1:50), in the legend
on the sheet with 1.
Geometry is on layer 0 with colour BYBLOCK, so a symbol takes the colour of its insert's
layer (E-SOCKET, E-SWITCH, ...). The same blocks are exported to the symbols/ folder by
`floorplan-engine symbols`.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ezdxf.document import Drawing
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.blocklayout import BlockLayout

from floorplan_engine.drawing.layers import (
    ALL_LAYERS,
    E_BOARD,
    E_DATA,
    E_LED,
    E_LIGHT,
    E_SOCKET,
    E_SWITCH,
    TEXT_SMALL_MM,
    TEXT_STYLE,
    new_document,
)
from floorplan_engine.electrical.anchors import (
    BOARD_DEPTH,
    DATA_LEN,
    DATA_TRI,
    DOWNLIGHT_R,
    LED_OUTPUT_R,
    LIGHT_R,
    OUTLET_DEPTH,
    OUTLET_R,
    PENDANT_R,
    SCONCE_R,
    SOCKET_R,
    SWITCH_ARM,
    SWITCH_R,
    SYMBOL_DEPTH,
    WALL_GAP,
)
from floorplan_engine.model.scale import sheet_scale
from floorplan_engine.model.schema import PointType

BLOCK_SOCKET = "E_SOCKET"
BLOCK_SWITCH = "E_SWITCH"
BLOCK_SWITCH2 = "E_SWITCH2"
BLOCK_PASS_SWITCH = "E_PASS_SWITCH"
BLOCK_LIGHT = "E_LIGHT"
BLOCK_DOWNLIGHT = "E_DOWNLIGHT"
BLOCK_PENDANT = "E_PENDANT"
BLOCK_SCONCE = "E_SCONCE"
BLOCK_DATA = "E_DATA"
BLOCK_TV = "E_TV"
BLOCK_LED_OUTPUT = "E_LED_OUTPUT"
BLOCK_OUTLET = "E_OUTLET"
BLOCK_BOARD = "E_BOARD"

_BYBLOCK = {"layer": "0", "color": 0}

TICK = 1.0


@dataclass(frozen=True)
class SymbolSpec:
    block: str
    layer: str
    depth: float  # sheet mm: how far the symbol sticks out from the wall (radius for ceiling ones)


# Symbol block and layer by key (electrical.anchors.symbol_key); depth is SYMBOL_DEPTH
SYMBOLS: dict[str, SymbolSpec] = {
    key: SymbolSpec(block, layer.name, SYMBOL_DEPTH[key])
    for key, block, layer in (
        (PointType.SOCKET, BLOCK_SOCKET, E_SOCKET),
        (PointType.SWITCH, BLOCK_SWITCH, E_SWITCH),
        ("switch2", BLOCK_SWITCH2, E_SWITCH),
        (PointType.PASS_SWITCH, BLOCK_PASS_SWITCH, E_SWITCH),
        (PointType.LIGHT, BLOCK_LIGHT, E_LIGHT),
        (PointType.DOWNLIGHT, BLOCK_DOWNLIGHT, E_LIGHT),
        (PointType.PENDANT, BLOCK_PENDANT, E_LIGHT),
        (PointType.SCONCE, BLOCK_SCONCE, E_LIGHT),
        (PointType.DATA, BLOCK_DATA, E_DATA),
        (PointType.TV, BLOCK_TV, E_DATA),
        (PointType.LED_OUTPUT, BLOCK_LED_OUTPUT, E_LED),
        (PointType.OUTLET, BLOCK_OUTLET, E_SOCKET),
        ("board", BLOCK_BOARD, E_BOARD),
    )
}

# Legend row order
LEGEND_ORDER: tuple[str, ...] = (
    PointType.SOCKET,
    PointType.SWITCH,
    "switch2",
    PointType.PASS_SWITCH,
    PointType.LIGHT,
    PointType.DOWNLIGHT,
    PointType.PENDANT,
    PointType.SCONCE,
    PointType.LED_OUTPUT,
    PointType.OUTLET,
    PointType.DATA,
    PointType.TV,
    "board",
)


def _socket(blk: BlockLayout) -> None:
    c = (0.0, WALL_GAP)
    blk.add_arc(c, SOCKET_R, 0, 180, dxfattribs=_BYBLOCK)
    blk.add_line((-SOCKET_R, WALL_GAP), (SOCKET_R, WALL_GAP), dxfattribs=_BYBLOCK)
    top = WALL_GAP + SOCKET_R
    # Tangent line: earth contact
    blk.add_line((-SOCKET_R * 0.8, top), (SOCKET_R * 0.8, top), dxfattribs=_BYBLOCK)


def _arm(blk: BlockLayout, angle_deg: float, ticks: int) -> None:
    """Switch lever from the circle at angle_deg with ticks at the end."""
    cy = WALL_GAP + SWITCH_R
    d = math.radians(angle_deg)
    start = (SWITCH_R * math.cos(d), cy + SWITCH_R * math.sin(d))
    end = (start[0] + SWITCH_ARM * math.cos(d), start[1] + SWITCH_ARM * math.sin(d))
    blk.add_line(start, end, dxfattribs=_BYBLOCK)
    perp = d - math.pi / 2 if angle_deg < 90 else d + math.pi / 2
    for k in range(ticks):
        back = k * 0.6
        base = (end[0] - back * math.cos(d), end[1] - back * math.sin(d))
        tip = (base[0] + TICK * math.cos(perp), base[1] + TICK * math.sin(perp))
        blk.add_line(base, tip, dxfattribs=_BYBLOCK)


def _switch_body(blk: BlockLayout) -> None:
    blk.add_circle((0.0, WALL_GAP + SWITCH_R), SWITCH_R, dxfattribs=_BYBLOCK)


def _switch(blk: BlockLayout) -> None:
    _switch_body(blk)
    _arm(blk, 45, ticks=1)


def _switch2(blk: BlockLayout) -> None:
    _switch_body(blk)
    _arm(blk, 45, ticks=1)
    _arm(blk, 135, ticks=1)


def _pass_switch(blk: BlockLayout) -> None:
    _switch_body(blk)
    _arm(blk, 45, ticks=2)


def _light(blk: BlockLayout) -> None:
    blk.add_circle((0.0, 0.0), LIGHT_R, dxfattribs=_BYBLOCK)
    k = LIGHT_R * math.cos(math.radians(45))
    blk.add_line((-k, -k), (k, k), dxfattribs=_BYBLOCK)
    blk.add_line((-k, k), (k, -k), dxfattribs=_BYBLOCK)


def _solid_circle(blk: BlockLayout, center: tuple[float, float], r: float) -> None:
    hatch = blk.add_hatch(color=0, dxfattribs={"layer": "0"})
    hatch.set_solid_fill(color=0)
    path = hatch.paths.add_edge_path()
    path.add_arc(center, r, 0, 360)


def _downlight(blk: BlockLayout) -> None:
    """Spot light: filled circle with a cross sticking out of the outline."""
    blk.add_circle((0.0, 0.0), DOWNLIGHT_R, dxfattribs=_BYBLOCK)
    _solid_circle(blk, (0.0, 0.0), DOWNLIGHT_R * 0.6)
    k = DOWNLIGHT_R * 1.8
    blk.add_line((-k, 0), (k, 0), dxfattribs=_BYBLOCK)
    blk.add_line((0, -k), (0, k), dxfattribs=_BYBLOCK)


def _pendant(blk: BlockLayout) -> None:
    """Pendant: two concentric circles with a filled centre."""
    blk.add_circle((0.0, 0.0), PENDANT_R, dxfattribs=_BYBLOCK)
    blk.add_circle((0.0, 0.0), PENDANT_R * 0.55, dxfattribs=_BYBLOCK)
    _solid_circle(blk, (0.0, 0.0), PENDANT_R * 0.3)


def _sconce(blk: BlockLayout) -> None:
    """Wall lamp: half circle at the wall with an inner half circle and an axis."""
    c = (0.0, WALL_GAP)
    blk.add_arc(c, SCONCE_R, 0, 180, dxfattribs=_BYBLOCK)
    blk.add_arc(c, SCONCE_R * 0.45, 0, 180, dxfattribs=_BYBLOCK)
    blk.add_line((-SCONCE_R, WALL_GAP), (SCONCE_R, WALL_GAP), dxfattribs=_BYBLOCK)
    blk.add_line((0, WALL_GAP), (0, WALL_GAP + SCONCE_R), dxfattribs=_BYBLOCK)


def _outlet_with_letter(letter: str) -> Callable[[BlockLayout], None]:
    """Low-voltage socket: a stub from the wall and a filled triangle, with a letter next to it."""

    def build(blk: BlockLayout) -> None:
        tip = WALL_GAP + DATA_LEN
        blk.add_line((0, WALL_GAP), (0, tip - DATA_TRI), dxfattribs=_BYBLOCK)
        tri = [(-DATA_TRI, tip - DATA_TRI), (DATA_TRI, tip - DATA_TRI), (0.0, tip)]
        blk.add_lwpolyline(tri, close=True, dxfattribs=_BYBLOCK)
        hatch = blk.add_hatch(color=0, dxfattribs={"layer": "0"})
        hatch.set_solid_fill(color=0)
        hatch.paths.add_polyline_path(tri, is_closed=True)
        blk.add_text(
            letter,
            height=1.8,
            dxfattribs={**_BYBLOCK, "style": TEXT_STYLE},
        ).set_placement((DATA_TRI * 1.4, tip - DATA_TRI), align=TextEntityAlignment.MIDDLE_LEFT)

    return build


def _led_output(blk: BlockLayout) -> None:
    """Lighting output: a dot at the wall and a wave."""
    _solid_circle(blk, (0.0, WALL_GAP + LED_OUTPUT_R), LED_OUTPUT_R)
    w = 0.9
    y0 = WALL_GAP + LED_OUTPUT_R * 2
    blk.add_arc((0.0, y0 + w / 2), w / 2, 270, 90, dxfattribs=_BYBLOCK)
    blk.add_arc((0.0, y0 + w * 1.5), w / 2, 90, 270, dxfattribs=_BYBLOCK)


def _outlet(blk: BlockLayout) -> None:
    """Power cable output: a stub from the wall and a hollow circle at the end."""
    top = OUTLET_DEPTH - 2 * OUTLET_R
    blk.add_line((0.0, WALL_GAP), (0.0, top), dxfattribs=_BYBLOCK)
    blk.add_circle((0.0, top + OUTLET_R), OUTLET_R, dxfattribs=_BYBLOCK)


def _board(blk: BlockLayout) -> None:
    """Unit 1×1 rectangle (scaled by the insert), the half towards the room is filled."""
    blk.add_lwpolyline([(-0.5, 0), (0.5, 0), (0.5, 1), (-0.5, 1)], close=True, dxfattribs=_BYBLOCK)
    hatch = blk.add_hatch(color=0, dxfattribs={"layer": "0"})
    hatch.set_solid_fill(color=0)
    hatch.paths.add_polyline_path([(-0.5, 0.5), (0.5, 0.5), (0.5, 1), (-0.5, 1)], is_closed=True)


_BUILDERS: dict[str, Callable[[BlockLayout], None]] = {
    BLOCK_SOCKET: _socket,
    BLOCK_SWITCH: _switch,
    BLOCK_SWITCH2: _switch2,
    BLOCK_PASS_SWITCH: _pass_switch,
    BLOCK_LIGHT: _light,
    BLOCK_DOWNLIGHT: _downlight,
    BLOCK_PENDANT: _pendant,
    BLOCK_SCONCE: _sconce,
    BLOCK_DATA: _outlet_with_letter("i"),
    BLOCK_TV: _outlet_with_letter("TV"),
    BLOCK_LED_OUTPUT: _led_output,
    BLOCK_OUTLET: _outlet,
    BLOCK_BOARD: _board,
}


# Invisible attributes of a point insert: edited in AutoCAD (EATTEDIT), read by update
SYMBOL_ATTRIBS = (("ID", "id точки"), ("H", "Высота от пола, мм"), ("GROUP", "Группа"))
ATTDEF_INVISIBLE = 1


def define_blocks(doc: Drawing) -> None:
    """Add all symbol block definitions to the document (if not there yet)."""
    for name, build in _BUILDERS.items():
        if name not in doc.blocks:
            block = doc.blocks.new(name, base_point=(0, 0))
            build(block)
            for tag, prompt in SYMBOL_ATTRIBS:
                block.add_attdef(
                    tag,
                    insert=(0, 0),
                    height=TEXT_SMALL_MM,
                    dxfattribs={
                        "layer": "0",
                        "style": TEXT_STYLE,
                        "prompt": prompt,
                        "flags": ATTDEF_INVISIBLE,
                    },
                )


def export_symbols(folder: Path) -> list[Path]:
    """Export each block to its own DXF (definition + one insert) for a CAD library."""
    folder.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for spec in SYMBOLS.values():
        doc = new_document(ALL_LAYERS)
        define_blocks(doc)
        k = sheet_scale()
        scale = (300.0, BOARD_DEPTH * k) if spec.block == BLOCK_BOARD else (k, k)
        doc.modelspace().add_blockref(
            spec.block,
            (0, 0),
            dxfattribs={"layer": spec.layer, "xscale": scale[0], "yscale": scale[1]},
        )
        for name in list(_BUILDERS):
            if name != spec.block:
                doc.blocks.delete_block(name, safe=False)
        path = folder / f"{spec.block.lower()}.dxf"
        doc.saveas(path, encoding="utf-8")
        paths.append(path)
    return paths
