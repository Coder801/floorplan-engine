"""Рамка листа и основная надпись (штамп) по ДСТУ Б А.2.4-4:2009.

Рамка — додаток Е: поле для підшивки 20 мм слева, 5 мм с остальных сторон.
Основная надпись — форма 3 (додаток Д), 185 × 55 мм, в правом нижнем углу рамки;
дополнительные графы 20–22 — на поле для підшивки, 26 «Копіював» и 27 «Формат» — под рамкой.
Форматы листов — ГОСТ 2.301, на который ссылается ДСТУ (графа 27).
Рамка и штамп рисуются на листе (paperspace) в мм листа, 1:1. Формат подбирается так,
чтобы содержимое листа (вид модели и панели справа от него) поместилось над основной
надписью или слева от неё.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ezdxf.document import Drawing
from ezdxf.entities.insert import Insert
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.base import BaseLayout
from ezdxf.layouts.layout import Paperspace

from shtroba.layers import A_SHEET, TEXT_STYLE, text_width
from shtroba.schema import SheetFormat, SheetInfo
from shtroba.texts import Language, tr

# Короткая × длинная сторона, мм
FORMATS: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "A2": (420.0, 594.0),
    "A1": (594.0, 841.0),
    "A0": (841.0, 1189.0),
}
FRAME_LEFT = 20.0  # поле для подшивки
FRAME_MARGIN = 5.0
STAMP_W = 185.0
STAMP_H = 55.0
PADDING = 20.0  # от рамки и штампа до чертежа, таблиц и легенды
LW_THICK = 50  # 0,5 мм — основная линия
LW_THIN = 18  # 0,18 мм — тонкая
# Высоты текста — ряд ГОСТ 2.304 (2,5; 3,5; 5); меньше 2,5 не уменьшаем, дальше — сжатие
TEXT_LABEL_MM = 2.5
TEXT_FIELD_MM = 3.5
TEXT_CODE_MM = 5.0
TEXT_MIN_MM = 2.5
CELL_PAD = 1.0  # от линий графы до текста с каждой стороны, мм
LINE_PITCH = 1.6  # шаг строк в высотах текста (две строки в графе 15 мм)
# Графы 20–22 снизу вверх: «Інв. № ор.», «Підпис і дата», «Зам. інв. №» — высота, мм
INV_ROWS = (("inv_original", 25.0), ("inv_signature", 35.0), ("inv_replaced", 25.0))
INV_LABEL_W = 5.0
INV_VALUE_W = 7.0

Region = tuple[float, float, float, float]  # x0, y0, x1, y1 в мм листа


@dataclass(frozen=True)
class SheetLayout:
    format: str
    width: float  # мм листа, с учётом ориентации
    height: float
    region: Region  # поле внутри рамки
    fits: bool  # содержимое поместилось

    @property
    def paper_prefix(self) -> str:
        """Начало имени бумаги «DWG To PDF.pc3»: ezdxf допишет «_(420.00_x_297.00_MM)»."""
        return f"ISO_full_bleed_{self.format}"


@dataclass(frozen=True)
class StampText:
    """Что пишется в основной надписи конкретного листа."""

    info: SheetInfo
    object_name: str  # графа 2
    image: str  # графа 4
    sheet_no: int = 1  # графа 7
    sheets: int = 1  # графа 8
    today: date | None = None  # дата подписей по умолчанию
    language: Language = "ru"


def format_candidates(fmt: SheetFormat) -> list[tuple[str, float, float]]:
    """Форматы по возрастанию: (имя, ширина, высота); горизонтальный раньше вертикального.
    A4 — только вертикальный. Заданный формат — только он, в двух ориентациях."""
    names = list(FORMATS) if fmt == "auto" else [fmt]
    out: list[tuple[str, float, float]] = []
    for name in names:
        short, long = FORMATS[name]
        if name == "A4":
            out.append((name, short, long))
        else:
            out += [(name, long, short), (name, short, long)]
    return out


def frame_region(width: float, height: float) -> Region:
    """Поле внутри рамки листа (штамп — в его правом нижнем углу)."""
    return FRAME_LEFT, FRAME_MARGIN, width - FRAME_MARGIN, height - FRAME_MARGIN


# --- Отрисовка ---------------------------------------------------------------


class _Pen:
    """Рисование в мм листа со сдвигом (dx, dy) — началом графы.

    layer — слой примитивов: A-SHEET на листе, «0» внутри блока штампа (наследует слой
    вставки).
    """

    def __init__(self, target: BaseLayout, dx: float = 0, dy: float = 0, layer: str = ""):
        self.target, self.dx, self.dy = target, dx, dy
        self.layer = layer or A_SHEET.name

    def _p(self, x: float, y: float) -> tuple[float, float]:
        return (self.dx + x, self.dy + y)

    def line(self, x0: float, y0: float, x1: float, y1: float, thick: bool = True) -> None:
        self.target.add_line(
            self._p(x0, y0),
            self._p(x1, y1),
            dxfattribs={"layer": self.layer, "lineweight": LW_THICK if thick else LW_THIN},
        )

    def rect(self, x0: float, y0: float, x1: float, y1: float, thick: bool = True) -> None:
        self.line(x0, y0, x1, y0, thick)
        self.line(x1, y0, x1, y1, thick)
        self.line(x1, y1, x0, y1, thick)
        self.line(x0, y1, x0, y0, thick)

    def text(
        self,
        text: str,
        x: float,
        y: float,
        height: float = TEXT_LABEL_MM,
        align: TextEntityAlignment = TextEntityAlignment.MIDDLE_CENTER,
        rotation: float = 0.0,
        width: float | None = None,
    ) -> None:
        """width — сколько мм есть у текста вдоль строки: не влезает — уменьшаем и сжимаем."""
        if not text:
            return
        factor = 1.0
        if width is not None:
            height, factor = fit_line(text, width, height)
        self.target.add_text(
            text,
            height=height,
            rotation=rotation,
            dxfattribs={"layer": self.layer, "style": TEXT_STYLE, "width": factor},
        ).set_placement(self._p(x, y), align=align)


def fit_line(text: str, width: float, preferred: float) -> tuple[float, float]:
    """Высота и коэффициент ширины, при которых текст в одну строку помещается в width мм
    (по метрикам шрифта): сначала уменьшаем высоту до TEXT_MIN_MM, потом сжимаем по ширине."""
    natural = text_width(text)  # ширина при высоте 1 мм
    if natural == 0:
        return preferred, 1.0
    height = max(min(TEXT_MIN_MM, preferred), min(preferred, width / natural))
    factor = min(1.0, width / (natural * height))
    return height, factor


@dataclass(frozen=True)
class Line:
    """Строка значения в графе: текст, высота, коэффициент ширины, сдвиг от центра по Y."""

    text: str
    height: float
    factor: float
    dy: float = 0.0


def fit_cell(text: str, width: float, preferred: float, lines: int = 1) -> list[Line]:
    """Разложить значение по графе шириной width мм: одна строка, а если она не влезает
    без уменьшения и графа позволяет (lines = 2) — две строки по границе слова."""
    height, factor = fit_line(text, width, preferred)
    single = [Line(text, height, factor)]
    words = text.split()
    if lines < 2 or len(words) < 2 or (height, factor) == (preferred, 1.0):
        return single
    splits = [(" ".join(words[:i]), " ".join(words[i:])) for i in range(1, len(words))]
    top, bottom = min(splits, key=lambda s: max(text_width(s[0]), text_width(s[1])))
    longest = max(text_width(top), text_width(bottom))
    h2 = max(min(TEXT_MIN_MM, preferred), min(preferred, width / longest))
    if h2 * min(1.0, width / (longest * h2)) <= height * factor:
        return single  # на две строки не крупнее
    dy = h2 * LINE_PITCH / 2
    return [
        Line(s, h2, min(1.0, width / (text_width(s) * h2)), d)
        for s, d in ((top, dy), (bottom, -dy))
    ]


def draw_frame(psp: Paperspace, layout: SheetLayout, language: Language = "ru") -> None:
    """Граница формата (тонкая), рамка (основная), графы 26–27 под ней и 20–22 слева."""
    pen = _Pen(psp)
    w, h = layout.width, layout.height
    pen.rect(0, 0, w, h, thick=False)
    pen.rect(FRAME_LEFT, FRAME_MARGIN, w - FRAME_MARGIN, h - FRAME_MARGIN)
    under = FRAME_MARGIN / 2
    stamp_x0 = w - FRAME_MARGIN - STAMP_W
    pen.text(tr("copied", language), stamp_x0 + 85, under)  # графа 26 — под графой 4
    pen.text(
        tr("format", language, name=layout.format),
        w - FRAME_MARGIN,
        under,
        align=TextEntityAlignment.MIDDLE_RIGHT,
    )
    draw_binding_columns(pen, language)


def draw_binding_columns(pen: _Pen, language: Language) -> None:
    """Дополнительные графы 20–22 на поле для підшивки: подпись 5 мм + значение 7 мм."""
    x1 = FRAME_LEFT
    x0, xm = x1 - INV_LABEL_W - INV_VALUE_W, x1 - INV_VALUE_W
    y = FRAME_MARGIN
    for key, height in INV_ROWS:
        pen.rect(x0, y, x1, y + height)
        pen.line(xm, y, xm, y + height)
        label = tr(key, language)
        pen.text(label, (x0 + xm) / 2, y + height / 2, rotation=90.0, width=height - 2 * CELL_PAD)
        y += height


# --- Основная надпись: блок с атрибутами --------------------------------------


@dataclass(frozen=True)
class StampField:
    """Атрибут штампа: тег, границы графы по X (x0, x1), центр графы по Y, высота графы,
    высота текста. Графа в две строки (lines = 2) — два атрибута: TAG и TAG_2."""

    tag: str
    x0: float
    x1: float
    y: float
    cell_h: float
    height: float
    prompt: str
    align: TextEntityAlignment = TextEntityAlignment.MIDDLE_CENTER
    lines: int = 1

    @property
    def width(self) -> float:
        """Сколько мм есть у текста: графа без отступов от линий."""
        return self.x1 - self.x0 - 2 * CELL_PAD

    @property
    def anchor_x(self) -> float:
        left = self.align is TextEntityAlignment.MIDDLE_LEFT
        return self.x0 + CELL_PAD if left else (self.x0 + self.x1) / 2

    @property
    def tags(self) -> tuple[str, ...]:
        return (self.tag,) if self.lines == 1 else (self.tag, f"{self.tag}_2")


SIGNATURE_ROWS = 8
_LEFT = TextEntityAlignment.MIDDLE_LEFT

STAMP_FIELDS: tuple[StampField, ...] = (
    StampField("CODE", 65, 185, 50, 10, TEXT_CODE_MM, "Графа 1: позначення документа"),
    StampField("OBJECT", 65, 185, 37.5, 15, TEXT_FIELD_MM, "Графа 2: об'єкт", lines=2),
    StampField("BUILDING", 65, 135, 22.5, 15, TEXT_FIELD_MM, "Графа 3: будинок", lines=2),
    StampField("IMAGE", 65, 135, 7.5, 15, TEXT_FIELD_MM, "Графа 4: зображення", lines=2),
    StampField("STAGE", 135, 150, 20, 10, TEXT_FIELD_MM, "Графа 6: стадія"),
    StampField("SHEET", 150, 165, 20, 10, TEXT_FIELD_MM, "Графа 7: аркуш"),
    StampField("SHEETS", 165, 185, 20, 10, TEXT_FIELD_MM, "Графа 8: аркушів"),
    StampField("ORG", 135, 185, 7.5, 15, TEXT_LABEL_MM, "Графа 9: організація", lines=2),
    *(
        f
        for i in range(SIGNATURE_ROWS)
        for f in (
            StampField(f"ROLE{i + 1}", 0, 20, 37.5 - 5 * i, 5, TEXT_LABEL_MM, "Посада", _LEFT),
            StampField(f"NAME{i + 1}", 20, 40, 37.5 - 5 * i, 5, TEXT_LABEL_MM, "Прізвище", _LEFT),
            StampField(f"DATE{i + 1}", 55, 65, 37.5 - 5 * i, 5, TEXT_LABEL_MM, "Дата"),
        )
    ),
)
STAMP_BLOCK = "STAMP_F3"


def define_stamp_block(doc: Drawing, language: Language) -> None:
    """Неизменная часть основной надписи формы 3 (линии и подписи граф) + атрибуты граф.

    Левая часть 65 мм — изменения и подписи, правая 120 мм сверху вниз: графа 1 — 10 мм,
    графа 2 — 15, графа 3 со «Стадія / Аркуш / Аркушів» (15 / 15 / 20) — 15,
    графы 4 и 9 (70 / 50) — 15.
    """
    if STAMP_BLOCK in doc.blocks:
        return
    block = doc.blocks.new(STAMP_BLOCK)
    pen = _Pen(block, layer="0")
    pen.rect(0, 0, STAMP_W, STAMP_H)
    pen.line(65, 0, 65, STAMP_H)
    # Левая часть: 2 строки изменений, шапка, 8 строк подписей — по 5 мм
    for i in range(1, 11):
        y = 5.0 * i
        pen.line(0, y, 65, y, thick=y in (40.0, 45.0))
    for x in (10, 20, 30, 40, 55):
        pen.line(x, 40, x, STAMP_H)
    for x in (20, 40, 55):
        pen.line(x, 0, x, 40)
    header = (
        ("stamp_change", 0, 10),
        ("stamp_count", 10, 20),
        ("stamp_sheet_short", 20, 30),
        ("stamp_doc", 30, 40),
        ("stamp_sign", 40, 55),
        ("stamp_date", 55, 65),
    )
    for key, x0, x1 in header:
        pen.text(tr(key, language), (x0 + x1) / 2, 42.5, width=x1 - x0 - 2 * CELL_PAD)
    # Правая часть: графы 1, 2, 3 + стадия/лист/листов, 4 + 9
    for y in (15, 30, 45):
        pen.line(65, y, STAMP_W, y)
    pen.line(135, 0, 135, 30)
    pen.line(150, 15, 150, 30)
    pen.line(165, 15, 165, 30)
    pen.line(135, 25, STAMP_W, 25, thick=False)
    for key, x0, x1 in (
        ("stamp_stage", 135, 150),
        ("stamp_sheet", 150, 165),
        ("stamp_sheets", 165, 185),
    ):
        pen.text(tr(key, language), (x0 + x1) / 2, 27.5, width=x1 - x0 - 2 * CELL_PAD)
    for f in STAMP_FIELDS:
        for k, tag in enumerate(f.tags):
            y = f.y - k * f.height * LINE_PITCH  # вторая строка — под первой
            block.add_attdef(
                tag,
                insert=(f.anchor_x, y),
                height=f.height,
                dxfattribs={"layer": "0", "style": TEXT_STYLE, "prompt": f.prompt},
            ).set_placement((f.anchor_x, y), align=f.align)


def stamp_values(stamp: StampText) -> dict[str, str]:
    info = stamp.info
    values = {
        "CODE": info.code,
        "OBJECT": stamp.object_name,
        "BUILDING": info.building,
        "IMAGE": stamp.image,
        "STAGE": info.stage,
        # Графа 7 — если листов больше одного, графа 8 — только на первом листе
        "SHEET": str(stamp.sheet_no) if stamp.sheets > 1 else "",
        "SHEETS": str(stamp.sheets) if stamp.sheet_no == 1 else "",
        "ORG": info.organization,
    }
    default_date = (stamp.today or date.today()).strftime("%m.%y")
    for i in range(SIGNATURE_ROWS):
        sig = info.signatures[i] if i < len(info.signatures) else None
        values[f"ROLE{i + 1}"] = sig.role if sig else ""
        values[f"NAME{i + 1}"] = sig.name if sig else ""
        values[f"DATE{i + 1}"] = (sig.date or default_date) if sig else ""
    return values


def draw_stamp(psp: Paperspace, layout: SheetLayout, stamp: StampText) -> Insert:
    """Вставка блока штампа в правый нижний угол рамки. Значение раскладывается по графе
    (fit_cell): уменьшается, сжимается или переносится на вторую строку — за линии не выходит."""
    doc = psp.doc
    assert doc is not None
    define_stamp_block(doc, stamp.language)
    x0, y0 = layout.width - FRAME_MARGIN - STAMP_W, FRAME_MARGIN
    ref = psp.add_blockref(STAMP_BLOCK, (x0, y0), dxfattribs={"layer": A_SHEET.name})
    values = stamp_values(stamp)
    ref.add_auto_attribs({tag: "" for f in STAMP_FIELDS for tag in f.tags})
    attribs = {a.dxf.tag: a for a in ref.attribs}
    for f in STAMP_FIELDS:
        lines = fit_cell(values[f.tag], f.width, f.height, f.lines) if values[f.tag] else []
        for k, tag in enumerate(f.tags):
            attrib = attribs[tag]
            if k >= len(lines):
                attrib.dxf.text = ""
                continue
            line = lines[k]
            attrib.dxf.text = line.text
            attrib.dxf.height = line.height
            attrib.dxf.width = line.factor
            attrib.set_placement((x0 + f.anchor_x, y0 + f.y + line.dy), align=f.align)
    return ref


def draw_sheet(psp: Paperspace, layout: SheetLayout, stamp: StampText) -> None:
    """Рамка и основная надпись на листе."""
    draw_frame(psp, layout, stamp.language)
    draw_stamp(psp, layout, stamp)
