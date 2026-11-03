"""Sheet frame and title block per DSTU B A.2.4-4:2009.

The frame follows annex E: a 20 mm binding margin on the left, 5 mm on the other sides.
The title block is form 3 (annex D), 185 × 55 mm, in the bottom-right corner of the frame;
extra boxes 20–22 go on the binding margin, 26 "Копіював" and 27 "Формат" below the frame.
Paper sizes follow GOST 2.301, which DSTU refers to (box 27).
Frame and title block are drawn on the sheet (paperspace) in sheet mm, 1:1. The paper size is
chosen so that the sheet content (model view and the panels to its right) fits above the
title block or to its left.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ezdxf.document import Drawing
from ezdxf.entities.insert import Insert
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.base import BaseLayout
from ezdxf.layouts.layout import Paperspace

from floorplan_engine.drawing.layers import A_SHEET, TEXT_STYLE, text_width
from floorplan_engine.model.schema import SheetFormat, SheetInfo
from floorplan_engine.model.texts import Language, tr

# Short × long side, mm
FORMATS: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "A2": (420.0, 594.0),
    "A1": (594.0, 841.0),
    "A0": (841.0, 1189.0),
}
FRAME_LEFT = 20.0  # binding margin
FRAME_MARGIN = 5.0
STAMP_W = 185.0
STAMP_H = 55.0
PADDING = 20.0  # from the frame and title block to the drawing, tables and legend
LW_THICK = 50  # 0.5 mm: thick line
LW_THIN = 18  # 0.18 mm: thin line
# Text heights from the GOST 2.304 series (2.5; 3.5; 5); never below 2.5, compress instead
TEXT_LABEL_MM = 2.5
TEXT_FIELD_MM = 3.5
TEXT_CODE_MM = 5.0
TEXT_MIN_MM = 2.5
CELL_PAD = 1.0  # from the box lines to the text on each side, mm
LINE_PITCH = 1.6  # line step in text heights (two lines in a 15 mm box)
# Boxes 20–22 from bottom to top: "Інв. № ор.", "Підпис і дата", "Зам. інв. №"; height, mm
INV_ROWS = (("inv_original", 25.0), ("inv_signature", 35.0), ("inv_replaced", 25.0))
INV_LABEL_W = 5.0
INV_VALUE_W = 7.0

Region = tuple[float, float, float, float]  # x0, y0, x1, y1 in sheet mm


@dataclass(frozen=True)
class SheetLayout:
    format: str
    width: float  # sheet mm, orientation applied
    height: float
    region: Region  # area inside the frame
    fits: bool  # the content fits

    @property
    def paper_prefix(self) -> str:
        """Start of the paper name "DWG To PDF.pc3": ezdxf appends "_(420.00_x_297.00_MM)"."""
        return f"ISO_full_bleed_{self.format}"


@dataclass(frozen=True)
class StampText:
    """What goes into the title block of a particular sheet."""

    info: SheetInfo
    object_name: str  # box 2
    image: str  # box 4
    sheet_no: int = 1  # box 7
    sheets: int = 1  # box 8
    today: date | None = None  # default signature date
    language: Language = "ru"


def format_candidates(fmt: SheetFormat) -> list[tuple[str, float, float]]:
    """Paper sizes in ascending order: (name, width, height); landscape before portrait.
    A4 is portrait only. A given size is used alone, in both orientations."""
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
    """Area inside the sheet frame (the title block sits in its bottom-right corner)."""
    return FRAME_LEFT, FRAME_MARGIN, width - FRAME_MARGIN, height - FRAME_MARGIN


# --- Drawing -----------------------------------------------------------------


class _Pen:
    """Drawing in sheet mm shifted by (dx, dy), the box origin.

    layer is the primitive layer: A-SHEET on the sheet, "0" inside the title block (inherits the
    insert layer).
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
        """width is how many mm the text has along the line: if it does not fit, shrink and
        compress.
        """
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
    """Height and width factor that make one line of text fit into width mm (by font metrics):
    first reduce the height down to TEXT_MIN_MM, then compress the width."""
    natural = text_width(text)  # width at 1 mm height
    if natural == 0:
        return preferred, 1.0
    height = max(min(TEXT_MIN_MM, preferred), min(preferred, width / natural))
    factor = min(1.0, width / (natural * height))
    return height, factor


@dataclass(frozen=True)
class Line:
    """Value line in a box: text, height, width factor, Y offset from the centre."""

    text: str
    height: float
    factor: float
    dy: float = 0.0


def fit_cell(text: str, width: float, preferred: float, lines: int = 1) -> list[Line]:
    """Lay a value out in a box width mm wide: one line, or, if it does not fit without shrinking
    and the box allows it (lines = 2), two lines split at a word boundary."""
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
        return single  # two lines no larger than
    dy = h2 * LINE_PITCH / 2
    return [
        Line(s, h2, min(1.0, width / (text_width(s) * h2)), d)
        for s, d in ((top, dy), (bottom, -dy))
    ]


def draw_frame(psp: Paperspace, layout: SheetLayout, language: Language = "ru") -> None:
    """Paper border (thin), frame (thick), boxes 26–27 below it and 20–22 on the left."""
    pen = _Pen(psp)
    w, h = layout.width, layout.height
    pen.rect(0, 0, w, h, thick=False)
    pen.rect(FRAME_LEFT, FRAME_MARGIN, w - FRAME_MARGIN, h - FRAME_MARGIN)
    under = FRAME_MARGIN / 2
    stamp_x0 = w - FRAME_MARGIN - STAMP_W
    pen.text(tr("copied", language), stamp_x0 + 85, under)  # box 26 sits under box 4
    pen.text(
        tr("format", language, name=layout.format),
        w - FRAME_MARGIN,
        under,
        align=TextEntityAlignment.MIDDLE_RIGHT,
    )
    draw_binding_columns(pen, language)


def draw_binding_columns(pen: _Pen, language: Language) -> None:
    """Extra boxes 20–22 on the binding margin: a 5 mm caption + a 7 mm value."""
    x1 = FRAME_LEFT
    x0, xm = x1 - INV_LABEL_W - INV_VALUE_W, x1 - INV_VALUE_W
    y = FRAME_MARGIN
    for key, height in INV_ROWS:
        pen.rect(x0, y, x1, y + height)
        pen.line(xm, y, xm, y + height)
        label = tr(key, language)
        pen.text(label, (x0 + xm) / 2, y + height / 2, rotation=90.0, width=height - 2 * CELL_PAD)
        y += height


# --- Title block: block with attributes ---------------------------------------


@dataclass(frozen=True)
class StampField:
    """Title block attribute: tag, box X bounds (x0, x1), box Y centre, box height, text height.
    A two-line box (lines = 2) has two attributes: TAG and TAG_2."""

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
        """How many mm the text has: the box minus padding from the lines."""
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
    """Fixed part of the form 3 title block (lines and box captions) + box attributes.

    The left part (65 mm) holds revisions and signatures; the right part (120 mm) from top to
    bottom: box 1 is 10 mm, box 2 is 15, box 3 with "Стадія / Аркуш / Аркушів" (15 / 15 / 20)
    is 15, boxes 4 and 9 (70 / 50) are 15.
    """
    if STAMP_BLOCK in doc.blocks:
        return
    block = doc.blocks.new(STAMP_BLOCK)
    pen = _Pen(block, layer="0")
    pen.rect(0, 0, STAMP_W, STAMP_H)
    pen.line(65, 0, 65, STAMP_H)
    # Left part: 2 revision rows, header, 8 signature rows, 5 mm each
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
    # Right part: boxes 1, 2, 3 + stage/sheet/sheets, 4 + 9
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
            y = f.y - k * f.height * LINE_PITCH  # second line under the first
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
        # Box 7 only when there is more than one sheet, box 8 only on the first sheet
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
    """Insert the title block into the bottom-right corner of the frame. Each value is fitted to its
    box (fit_cell): shrunk, compressed or wrapped to a second line; it never crosses the lines."""
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
    """Frame and title block on the sheet."""
    draw_frame(psp, layout, stamp.language)
    draw_stamp(psp, layout, stamp)
