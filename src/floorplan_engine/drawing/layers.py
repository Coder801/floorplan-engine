"""Document styling: layers, colours, line types, text and dimension styles.

The model is 1:1 in mm. Text heights and symbol sizes are given "on sheet" and multiplied
by the sheet scale: at 1:50, 2.5 mm on the sheet is 125 mm in the model. The scale is a
build parameter (drawing_scale); the whole set is drawn at one scale.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

from ezdxf.document import Drawing
from ezdxf.filemanagement import new as new_dxf
from ezdxf.fonts import fonts

from floorplan_engine.drawing.ids import register_app
from floorplan_engine.model.scale import sheet, sheet_scale

DXF_VERSION = "R2018"
INSUNITS_MM = 4

TEXT_STYLE = "PLEX_LIGHT"
# IBM Plex Sans Light (OFL) ships inside the package: the preview takes it from there, while
# CAD needs the font installed, otherwise the program substitutes another one
TEXT_FONT = "IBMPlexSans-Light.ttf"
TEXT_FONT_FAMILY = "IBM Plex Sans Light"
FONT_DIR = Path(__file__).resolve().parent / "fonts"
DIM_STYLE = "PLAN"


@cache
def register_fonts() -> None:
    """Register the package fonts (IBM Plex Sans) with the ezdxf font manager, once per process."""
    fonts.font_manager.scan_folder(FONT_DIR)


def text_width(text: str, height: float = 1.0) -> float:
    """Width of one line of text in TEXT_STYLE, mm: from font metrics, not an estimate."""
    register_fonts()
    return float(fonts.make_font(TEXT_FONT, height).text_width(text))


CABLE_LINETYPE = "E_CABLE_DASH"
LED_LINETYPE = "E_LED_DASH"
FLOOR_LINETYPE = "W_FLOOR_DASHDOT"
SURFACE_LINETYPE = "P_SURFACE_DASH"  # sewer along the wall above the floor (in a box)

TEXT_DIM_MM = 2.5  # dimensions
TEXT_SMALL_MM = 2.0  # electrical labels, areas
TEXT_ROOM_MM = 3.5  # room names, total area
MIN_TEXT_MM = 1.8  # GOST 2.304: smaller text does not print on the sheet (checked in printing.py)


@dataclass(frozen=True)
class LayerSpec:
    name: str
    color: int
    description: str
    linetype: str = "Continuous"
    plot: bool = True


A_WALL = LayerSpec("A-WALL", 7, "Стены; штриховка — несущие")
A_DOOR = LayerSpec("A-DOOR", 3, "Двери с дугой открывания")
A_WIND = LayerSpec("A-WIND", 4, "Окна")
A_DIMS = LayerSpec("A-DIMS", 2, "Размеры")
A_TEXT = LayerSpec("A-TEXT", 7, "Названия и площади помещений, подоконники")
# Room outline for area fields: not printed and not visible on sheets; delete it and the
# area fields show "####"
A_AREA = LayerSpec("A-AREA", 8, "Контуры площади помещений (не печатается)", plot=False)
E_SOCKET = LayerSpec("E-SOCKET", 1, "Розетки")
E_SWITCH = LayerSpec("E-SWITCH", 5, "Выключатели")
E_LIGHT = LayerSpec("E-LIGHT", 6, "Светильники")
E_BOARD = LayerSpec("E-BOARD", 1, "Электрощит")
# Labels are dark (7); only symbols and groups are coloured on sheets (feedback 2026-10-28:
# red labels blended into red sockets)
E_TEXT = LayerSpec("E-TEXT", 7, "Группы, высоты, сечения")
E_DATA = LayerSpec("E-DATA", 140, "Интернет и TV")
E_LED = LayerSpec("E-LED", 221, "LED-подсветка и выводы под неё", LED_LINETYPE)
W_BOX = LayerSpec("W-BOX", 1, "Распаечные коробки (проводка через коробки)")
# Cables: a layer per line purpose, protection (-RCD: RCBO or RCD) and route (-FLOOR: in the screed)
CABLE_PURPOSES = {"light": "свет", "socket": "розетки", "device": "приборы", "low": "слаботочка"}


def _cable_spec(purpose: str, rcd: bool, floor: bool) -> LayerSpec:
    name = f"W-CABLE-{purpose.upper()}{'-RCD' if rcd else ''}{'-FLOOR' if floor else ''}"
    note = f"Кабели: {CABLE_PURPOSES[purpose]}{', с дифом/УЗО' if rcd else ''}"
    note += ", по полу (в стяжке)" if floor else ""
    return LayerSpec(name, 1, note, FLOOR_LINETYPE if floor else CABLE_LINETYPE)


W_CABLES = {
    (purpose, rcd, floor): _cable_spec(purpose, rcd, floor)
    for purpose in CABLE_PURPOSES
    for rcd in (False, True)
    for floor in (False, True)
    if not (purpose == "low" and rcd)  # low-voltage lines are not in the panel
}
W_TEXT = LayerSpec("W-TEXT", 7, "Подписи коробок")
E_PANEL = LayerSpec("E-PANEL", 7, "Щит в лицо: корпус, рейки, аппараты, подписи")
E_PANEL_WIRE = LayerSpec("E-PANEL-WIRE", 1, "Щит в лицо: провода групп к автоматам")
A_SHEET = LayerSpec("A-SHEET", 7, "Рамка листа и основная надпись")
A_VPORT = LayerSpec("A-VPORT", 8, "Рамки видовых экранов на листах (не печатается)", plot=False)

PLAN_LAYERS = (A_WALL, A_DOOR, A_WIND, A_DIMS, A_TEXT, A_AREA, A_SHEET)
ELECTRICAL_LAYERS = (
    E_SOCKET,
    E_SWITCH,
    E_LIGHT,
    E_DATA,
    E_LED,
    E_BOARD,
    E_TEXT,
    A_SHEET,
)
WIRING_LAYERS = (W_BOX, *W_CABLES.values(), W_TEXT, A_SHEET)
PANEL_LAYERS = (E_PANEL, E_PANEL_WIRE, A_SHEET)
E_LINK = LayerSpec("E-LINK", 5, "Освещение: что чем включает выключатель", CABLE_LINETYPE)
L_TEXT = LayerSpec("L-TEXT", 7, "Освещение: номера светильников и выключателей")
LW_LINK = 18  # switch link line weight, 1/100 mm
LIGHTING_LAYERS = (E_LINK, L_TEXT)
E_ELEV = LayerSpec("E-ELEV", 7, "Развёртки стен: стена, проёмы, точки, коробки, штробы, размеры")
P_COLD = LayerSpec("P-COLD", 5, "Холодная вода (В1)")
P_HOT = LayerSpec("P-HOT", 1, "Горячая вода (Т3)")
P_SEWER = LayerSpec("P-SEWER", 34, "Канализация (К1)")
P_FIXT = LayerSpec("P-FIXT", 7, "Сантехприборы: номера и водорозетки")
P_RISER = LayerSpec("P-RISER", 7, "Стояки, узел ввода, коллекторы")
P_OBST = LayerSpec("P-OBST", 8, "Препятствия: инсталляция, ванна, поддон, короб")
P_SYMB = LayerSpec("P-SYMB", 8, "Сантехприборы контуром: ванна, душ, унитаз… (типовой размер)")
P_TEXT = LayerSpec("P-TEXT", 7, "Подписи сантехники: диаметры, уклоны")
PLUMBING_LAYERS = (P_COLD, P_HOT, P_SEWER, P_FIXT, P_RISER, P_OBST, P_SYMB, P_TEXT, A_SHEET)
ALL_LAYERS = tuple(
    dict.fromkeys(
        PLAN_LAYERS
        + ELECTRICAL_LAYERS
        + LIGHTING_LAYERS
        + WIRING_LAYERS
        + PANEL_LAYERS
        + (E_ELEV,)
        + PLUMBING_LAYERS
    )
)


def new_document(layers: tuple[LayerSpec, ...] = ALL_LAYERS) -> Drawing:
    """New DXF R2018 in mm with the project styles and layers."""
    doc = new_dxf(DXF_VERSION, setup=False, units=INSUNITS_MM)
    doc.header["$INSUNITS"] = INSUNITS_MM
    doc.header["$MEASUREMENT"] = 1  # metric
    doc.header["$LUNITS"] = 2  # decimal
    doc.header["$LTSCALE"] = 1.0
    register_app(doc)
    _add_linetypes(doc)
    _add_text_style(doc)
    _add_dim_style(doc)
    for spec in layers:
        layer = doc.layers.add(spec.name, color=spec.color, linetype=spec.linetype)
        layer.description = spec.description
        if not spec.plot:
            layer.dxf.plot = 0
    return doc


def _add_linetypes(doc: Drawing) -> None:
    if CABLE_LINETYPE not in doc.linetypes:
        dash, gap = sheet(6.0), sheet(3.0)
        doc.linetypes.add(
            CABLE_LINETYPE,
            pattern=[dash + gap, dash, -gap],
            description="Трасса __ __ __",
        )
    if LED_LINETYPE not in doc.linetypes:
        dash, gap = sheet(2.0), sheet(1.0)
        doc.linetypes.add(
            LED_LINETYPE,
            pattern=[dash + gap, dash, -gap],
            description="LED - - - -",
        )
    if SURFACE_LINETYPE not in doc.linetypes:
        dash, gap = sheet(3.0), sheet(1.2)
        doc.linetypes.add(
            SURFACE_LINETYPE,
            pattern=[dash + gap, dash, -gap],
            description="Над полом у стены — — —",
        )
    if FLOOR_LINETYPE not in doc.linetypes:
        dash, dot, gap = sheet(6.0), sheet(0.5), sheet(1.5)
        doc.linetypes.add(
            FLOOR_LINETYPE,
            pattern=[dash + dot + 2 * gap, dash, -gap, dot, -gap],
            description="По полу __ . __ . __",
        )


def _add_text_style(doc: Drawing) -> None:
    if TEXT_STYLE not in doc.styles:
        style = doc.styles.add(TEXT_STYLE, font=TEXT_FONT)
        # Font family in XDATA: this is how AutoCAD/BricsCAD find the TTF by name
        style.set_extended_font_data(family=TEXT_FONT_FAMILY, italic=False, bold=False)


def _add_dim_style(doc: Drawing) -> None:
    if DIM_STYLE in doc.dimstyles:
        return
    doc.dimstyles.add(
        DIM_STYLE,
        dxfattribs={
            "dimscale": sheet_scale(),
            "dimtxsty": TEXT_STYLE,
            "dimtxt": TEXT_DIM_MM,
            "dimasz": 2.5,
            "dimtsz": 1.25,  # ticks instead of arrows
            "dimexo": 1.5,  # extension line offset from the object
            "dimexe": 1.25,  # extension line overshoot past the dimension line
            "dimdle": 1.25,  # dimension line overshoot past the extension lines
            "dimgap": 0.8,
            "dimtad": 1,  # text above the dimension line
            "dimtih": 0,  # text parallel to the dimension line
            "dimtoh": 0,
            "dimdec": 0,
            "dimlunit": 2,
            "dimzin": 8,
            # Explicit colour for layer A-DIMS: ezdxf puts dimension block lines on layer 0,
            # and the ezdxf.addons.drawing preview does not understand BYBLOCK
            "dimclrd": A_DIMS.color,
            "dimclre": A_DIMS.color,
            "dimclrt": A_DIMS.color,
        },
    )
