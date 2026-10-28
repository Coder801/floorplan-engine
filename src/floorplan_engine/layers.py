"""Оформление документа: слои, цвета, типы линий, текстовый и размерный стили.

Модель — 1:1 в мм. Высоты текста и размеры символов задаются «на листе» и умножаются
на масштаб листа: при 1:50 2,5 мм на листе = 125 мм в модели. Масштаб — параметр сборки
(drawing_scale); весь комплект рисуется в одном масштабе.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from ezdxf.document import Drawing
from ezdxf.filemanagement import new as new_dxf
from ezdxf.fonts import fonts

from floorplan_engine.ids import register_app

DXF_VERSION = "R2018"
INSUNITS_MM = 4
DEFAULT_SCALE = 50.0
# Масштабы от крупного к мелкому — из них подбирается масштаб листов: ряд ГОСТ 2.302
# и 1:30, принятый в интерьерных проектах
SCALES = (20.0, 25.0, 30.0, 40.0, 50.0, 75.0, 100.0)
_SCALE: ContextVar[float] = ContextVar("sheet_scale", default=DEFAULT_SCALE)

TEXT_STYLE = "PLEX_LIGHT"
# IBM Plex Sans Light (OFL) лежит в пакете: превью берёт его оттуда, а в CAD шрифт
# нужно установить, иначе программа подставит замену
TEXT_FONT = "IBMPlexSans-Light.ttf"
TEXT_FONT_FAMILY = "IBM Plex Sans Light"
FONT_DIR = Path(__file__).resolve().parent / "fonts"
DIM_STYLE = "PLAN"


@cache
def register_fonts() -> None:
    """Шрифты из пакета (IBM Plex Sans) — в менеджер шрифтов ezdxf, один раз за процесс."""
    fonts.font_manager.scan_folder(FONT_DIR)


def text_width(text: str, height: float = 1.0) -> float:
    """Ширина однострочного текста стилем TEXT_STYLE, мм: по метрикам шрифта, не по оценке."""
    register_fonts()
    return float(fonts.make_font(TEXT_FONT, height).text_width(text))


CABLE_LINETYPE = "E_CABLE_DASH"
LED_LINETYPE = "E_LED_DASH"
FLOOR_LINETYPE = "W_FLOOR_DASHDOT"

TEXT_DIM_MM = 2.5  # размеры
TEXT_SMALL_MM = 2.0  # подписи электрики, площади
TEXT_ROOM_MM = 3.5  # названия помещений, общая площадь
MIN_TEXT_MM = 1.8  # ГОСТ 2.304: мельче на листе не печатается (проверка — printing.py)


def sheet_scale() -> float:
    """Знаменатель масштаба листа, по которому сейчас рисуется модель (50 — это 1:50)."""
    return _SCALE.get()


@contextmanager
def drawing_scale(scale: float) -> Iterator[None]:
    """Рисовать модель под масштаб листа 1:scale."""
    token = _SCALE.set(scale)
    try:
        yield
    finally:
        _SCALE.reset(token)


def sheet(mm: float) -> float:
    """Размер «на листе» → размер в модели при текущем масштабе."""
    return mm * _SCALE.get()


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
A_TEXT = LayerSpec("A-TEXT", 7, "Названия и площади помещений")
# Контур помещения для полей площади: не печатается и не виден на листах; удалишь —
# поля площади покажут «####»
A_AREA = LayerSpec("A-AREA", 8, "Контуры площади помещений (не печатается)", plot=False)
E_SOCKET = LayerSpec("E-SOCKET", 1, "Розетки")
E_SWITCH = LayerSpec("E-SWITCH", 5, "Выключатели")
E_LIGHT = LayerSpec("E-LIGHT", 6, "Светильники")
E_BOARD = LayerSpec("E-BOARD", 1, "Электрощит")
# Подписи — тёмные (7), цвет на листах — только у символов и у группы (отзыв 2026-10-28:
# красные подписи сливались с красными розетками)
E_TEXT = LayerSpec("E-TEXT", 7, "Группы, высоты, сечения")
E_DATA = LayerSpec("E-DATA", 140, "Интернет и TV")
E_LED = LayerSpec("E-LED", 221, "LED-подсветка и выводы под неё", LED_LINETYPE)
W_BOX = LayerSpec("W-BOX", 1, "Распаечные коробки (проводка через коробки)")
W_CABLE = LayerSpec("W-CABLE", 1, "Кабели проводки через коробки", CABLE_LINETYPE)
W_CABLE_FLOOR = LayerSpec("W-CABLE-FLOOR", 1, "Кабели по полу (в стяжке)", FLOOR_LINETYPE)
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
WIRING_LAYERS = (W_BOX, W_CABLE, W_CABLE_FLOOR, W_TEXT, A_SHEET)
PANEL_LAYERS = (E_PANEL, E_PANEL_WIRE, A_SHEET)
E_LINK = LayerSpec("E-LINK", 5, "Освещение: что чем включает выключатель", CABLE_LINETYPE)
L_TEXT = LayerSpec("L-TEXT", 7, "Освещение: номера светильников и выключателей")
LW_LINK = 18  # толщина связи выключателя, сотые мм
LIGHTING_LAYERS = (E_LINK, L_TEXT)
E_ELEV = LayerSpec("E-ELEV", 7, "Развёртки стен: стена, проёмы, точки, коробки, штробы, размеры")
ALL_LAYERS = tuple(
    dict.fromkeys(
        PLAN_LAYERS + ELECTRICAL_LAYERS + LIGHTING_LAYERS + WIRING_LAYERS + PANEL_LAYERS + (E_ELEV,)
    )
)


def new_document(layers: tuple[LayerSpec, ...] = ALL_LAYERS) -> Drawing:
    """Новый DXF R2018 в мм со стилями проекта и заданными слоями."""
    doc = new_dxf(DXF_VERSION, setup=False, units=INSUNITS_MM)
    doc.header["$INSUNITS"] = INSUNITS_MM
    doc.header["$MEASUREMENT"] = 1  # метрическая система
    doc.header["$LUNITS"] = 2  # десятичные
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
        # Семейство шрифта в XDATA — так AutoCAD/BricsCAD находят TTF по имени
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
            "dimtsz": 1.25,  # засечки вместо стрелок
            "dimexo": 1.5,  # отступ выносной линии от объекта
            "dimexe": 1.25,  # выход выносной линии за размерную
            "dimdle": 1.25,  # выход размерной линии за выносные
            "dimgap": 0.8,
            "dimtad": 1,  # текст над размерной линией
            "dimtih": 0,  # текст параллельно размерной линии
            "dimtoh": 0,
            "dimdec": 0,
            "dimlunit": 2,
            "dimzin": 8,
            # Явный цвет слоя A-DIMS: линии блока размера ezdxf кладёт на слой 0,
            # а BYBLOCK не понимает превью ezdxf.addons.drawing
            "dimclrd": A_DIMS.color,
            "dimclre": A_DIMS.color,
            "dimclrt": A_DIMS.color,
        },
    )
