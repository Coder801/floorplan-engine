"""Блоки УГО электрики (упрощённо, по легенде проектов: розетки, выключатели, свет, слаботочка).

Локальная система блока: точка вставки — на внутренней грани стены, стена вдоль оси X,
помещение — в сторону +Y. Потолочные символы — с центром в точке вставки. Единица блока —
1 мм листа: в модели блок вставляется с коэффициентом масштаба листа (50 при 1:50), в
легенде на листе — 1.
Геометрия на слое 0 с цветом BYBLOCK, поэтому символ принимает цвет слоя своей вставки
(E-SOCKET, E-SWITCH, ...). Эти же блоки выгружаются в папку symbols/ командой
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

from floorplan_engine.layers import (
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
    sheet_scale,
)
from floorplan_engine.schema import ElectricalPoint, PointType

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

WALL_GAP = 0.4  # зазор символа от грани стены
SOCKET_R = 2.0
SOCKET_DEPTH = WALL_GAP + SOCKET_R  # до касательной (линия заземления)
SWITCH_R = 1.0
SWITCH_ARM = 3.0
SWITCH_DEPTH = WALL_GAP + 2 * SWITCH_R + SWITCH_ARM * math.sin(math.radians(45))
LIGHT_R = 2.5
DOWNLIGHT_R = 1.0
PENDANT_R = 2.0
SCONCE_R = 2.0
DATA_LEN = 3.5
DATA_TRI = 1.2
LED_OUTPUT_R = 0.6
LED_OUTPUT_DEPTH = WALL_GAP + 2.5
OUTLET_R = 0.8
OUTLET_DEPTH = WALL_GAP + 2.5
BOARD_DEPTH = 3.0
TICK = 1.0


@dataclass(frozen=True)
class SymbolSpec:
    block: str
    layer: str
    depth: float  # мм листа: насколько символ выступает от стены (у потолочных — радиус)


# Ключ символа: тип точки, а для двухклавишного выключателя — "switch2"; щит — "board"
SYMBOLS: dict[str, SymbolSpec] = {
    PointType.SOCKET: SymbolSpec(BLOCK_SOCKET, E_SOCKET.name, SOCKET_DEPTH),
    PointType.SWITCH: SymbolSpec(BLOCK_SWITCH, E_SWITCH.name, SWITCH_DEPTH),
    "switch2": SymbolSpec(BLOCK_SWITCH2, E_SWITCH.name, SWITCH_DEPTH),
    PointType.PASS_SWITCH: SymbolSpec(BLOCK_PASS_SWITCH, E_SWITCH.name, SWITCH_DEPTH),
    PointType.LIGHT: SymbolSpec(BLOCK_LIGHT, E_LIGHT.name, LIGHT_R),
    PointType.DOWNLIGHT: SymbolSpec(BLOCK_DOWNLIGHT, E_LIGHT.name, DOWNLIGHT_R * 1.8),
    PointType.PENDANT: SymbolSpec(BLOCK_PENDANT, E_LIGHT.name, PENDANT_R),
    PointType.SCONCE: SymbolSpec(BLOCK_SCONCE, E_LIGHT.name, WALL_GAP + SCONCE_R),
    PointType.DATA: SymbolSpec(BLOCK_DATA, E_DATA.name, WALL_GAP + DATA_LEN),
    PointType.TV: SymbolSpec(BLOCK_TV, E_DATA.name, WALL_GAP + DATA_LEN),
    PointType.LED_OUTPUT: SymbolSpec(BLOCK_LED_OUTPUT, E_LED.name, LED_OUTPUT_DEPTH),
    PointType.OUTLET: SymbolSpec(BLOCK_OUTLET, E_SOCKET.name, OUTLET_DEPTH),
    "board": SymbolSpec(BLOCK_BOARD, E_BOARD.name, BOARD_DEPTH),
}

# Порядок строк легенды
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


def symbol_key(pt: ElectricalPoint) -> str:
    if pt.type is PointType.SWITCH and pt.keys == 2:
        return "switch2"
    return str(pt.type)


def _socket(blk: BlockLayout) -> None:
    c = (0.0, WALL_GAP)
    blk.add_arc(c, SOCKET_R, 0, 180, dxfattribs=_BYBLOCK)
    blk.add_line((-SOCKET_R, WALL_GAP), (SOCKET_R, WALL_GAP), dxfattribs=_BYBLOCK)
    top = WALL_GAP + SOCKET_R
    # Касательная — защитный контакт
    blk.add_line((-SOCKET_R * 0.8, top), (SOCKET_R * 0.8, top), dxfattribs=_BYBLOCK)


def _arm(blk: BlockLayout, angle_deg: float, ticks: int) -> None:
    """Рычаг выключателя из окружности под углом angle_deg с ticks засечками на конце."""
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
    """Точечный: залитый кружок с перекрестием, выходящим за контур."""
    blk.add_circle((0.0, 0.0), DOWNLIGHT_R, dxfattribs=_BYBLOCK)
    _solid_circle(blk, (0.0, 0.0), DOWNLIGHT_R * 0.6)
    k = DOWNLIGHT_R * 1.8
    blk.add_line((-k, 0), (k, 0), dxfattribs=_BYBLOCK)
    blk.add_line((0, -k), (0, k), dxfattribs=_BYBLOCK)


def _pendant(blk: BlockLayout) -> None:
    """Подвесной: две концентрические окружности с залитым центром."""
    blk.add_circle((0.0, 0.0), PENDANT_R, dxfattribs=_BYBLOCK)
    blk.add_circle((0.0, 0.0), PENDANT_R * 0.55, dxfattribs=_BYBLOCK)
    _solid_circle(blk, (0.0, 0.0), PENDANT_R * 0.3)


def _sconce(blk: BlockLayout) -> None:
    """Бра: полукруг у стены с внутренним полукругом и осью."""
    c = (0.0, WALL_GAP)
    blk.add_arc(c, SCONCE_R, 0, 180, dxfattribs=_BYBLOCK)
    blk.add_arc(c, SCONCE_R * 0.45, 0, 180, dxfattribs=_BYBLOCK)
    blk.add_line((-SCONCE_R, WALL_GAP), (SCONCE_R, WALL_GAP), dxfattribs=_BYBLOCK)
    blk.add_line((0, WALL_GAP), (0, WALL_GAP + SCONCE_R), dxfattribs=_BYBLOCK)


def _outlet_with_letter(letter: str) -> Callable[[BlockLayout], None]:
    """Слаботочная розетка: отвод от стены и залитый треугольник, рядом буква."""

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
    """Вывод под подсветку: точка у стены и волна."""
    _solid_circle(blk, (0.0, WALL_GAP + LED_OUTPUT_R), LED_OUTPUT_R)
    w = 0.9
    y0 = WALL_GAP + LED_OUTPUT_R * 2
    blk.add_arc((0.0, y0 + w / 2), w / 2, 270, 90, dxfattribs=_BYBLOCK)
    blk.add_arc((0.0, y0 + w * 1.5), w / 2, 90, 270, dxfattribs=_BYBLOCK)


def _outlet(blk: BlockLayout) -> None:
    """Силовой вывод кабеля: отвод от стены и полый кружок на конце."""
    top = OUTLET_DEPTH - 2 * OUTLET_R
    blk.add_line((0.0, WALL_GAP), (0.0, top), dxfattribs=_BYBLOCK)
    blk.add_circle((0.0, top + OUTLET_R), OUTLET_R, dxfattribs=_BYBLOCK)


def _board(blk: BlockLayout) -> None:
    """Единичный прямоугольник 1×1 (масштабируется вставкой), половина к помещению залита."""
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


# Невидимые атрибуты вставки точки: правятся в AutoCAD (EATTEDIT), читаются update
SYMBOL_ATTRIBS = (("ID", "id точки"), ("H", "Высота от пола, мм"), ("GROUP", "Группа"))
ATTDEF_INVISIBLE = 1


def define_blocks(doc: Drawing) -> None:
    """Добавить в документ определения всех блоков УГО (если их ещё нет)."""
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
    """Выгрузить каждый блок в отдельный DXF (определение + одна вставка) для библиотеки CAD."""
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
