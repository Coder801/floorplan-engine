"""Адаптер растра: скан, PDF-картинка, JPEG/PNG → надписи и отрезки (как у вектора).

Без LLM, локально:

- надписи — OCR (RapidOCR, Apache-2.0) по плиткам с перекрытием: так большой лист не
  сжимается перед распознаванием. Второй проход — по изображению, повёрнутому на 90°:
  подписи, написанные снизу вверх, читаются как обычные. Уверенность надписи — оценка OCR;
- отрезки — OpenCV (Apache-2.0): бинаризация, текст маскируется, отрезки по Хафу; почти
  горизонтальные и вертикальные выпрямляются (на растре линия «дрожит» на пиксель).

Координаты переводятся в pt листа (1 pt = 1/72 дюйма) от левого нижнего угла, Y вверх —
так разбор (analysis.py) работает с растром теми же правилами, что с вектором; его допуски
растягиваются на RASTER_TOLERANCE: конец отрезка на растре точен до пары пикселей.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import numpy.typing as npt

from shtroba.service.facts.primitives import Label, Segment, Sheet

RENDER_DPI = 200  # PDF-картинка рендерится в таком разрешении
DEFAULT_LONG_MM = 420.0  # у картинки без dpi длинная сторона считается A3
TILE = 1280  # px: сторона плитки OCR
TILE_OVERLAP = 192  # px: перекрытие плиток — подпись на стыке целиком в одной из них
MIN_OCR_SCORE = 0.5
SNAP_DEG = 2.0  # отрезок ближе этого угла к оси выпрямляется
MIN_SEGMENT_PX = 8
MERGE_GAP_PX = 3.0  # соосные куски одной линии ближе этого — один отрезок
MERGE_AXIS_PX = 1.5  # куски на одной линии: расхождение поперёк не больше этого
# Маска текста — середина строки: снизу у подписи проходит размерная линия, её не трогаем
MASK_TOP, MASK_BOTTOM = 0.1, 0.3
RASTER_TOLERANCE = 3.0  # во сколько раз допуски разбора шире, чем у вектора
IMAGE_TYPES = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"})

Image = npt.NDArray[np.uint8]


@dataclass(frozen=True)
class Word:
    """Распознанная строка: прямоугольник в px изображения (Y вниз) и направление."""

    text: str
    score: float
    x0: float
    y0: float
    x1: float
    y1: float
    vertical: bool  # читается снизу вверх


@cache
def _engine() -> Any:
    from rapidocr_onnxruntime import RapidOCR  # тяжёлый импорт — только когда нужен

    return RapidOCR()


def read_image(path: Path, name: str | None = None) -> list[Sheet]:
    """Картинка — одна страница. dpi — из файла, иначе длинная сторона = A3."""
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"{path.name}: не картинка или файл повреждён")
    gray: Image = np.asarray(img, dtype=np.uint8)
    dpi = _dpi(path) or max(gray.shape) / (DEFAULT_LONG_MM / 25.4)
    return [image_sheet(gray, name or path.name, 1, dpi)]


def read_raster_pdf(path: Path, name: str | None = None, dpi: int = RENDER_DPI) -> list[Sheet]:
    """PDF как картинки: каждая страница рендерится и разбирается растром."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        count = len(pdf)
    finally:
        pdf.close()
    return [render_page(path, i, name or path.name, dpi) for i in range(1, count + 1)]


def render_page(path: Path, page_no: int, name: str, dpi: int = RENDER_DPI) -> Sheet:
    """Страница PDF (с 1) рендерится в оттенки серого и разбирается растром."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        rgb = pdf[page_no - 1].render(scale=dpi / 72).to_numpy()
    finally:
        pdf.close()
    gray: Image = np.asarray(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), dtype=np.uint8)
    return image_sheet(gray, name, page_no, dpi)


def _dpi(path: Path) -> float | None:
    try:
        from PIL import Image as PilImage
    except ImportError:
        return None
    with PilImage.open(path) as im:
        info = im.info.get("dpi")
    return float(info[0]) if info and info[0] > 1 else None


def image_sheet(gray: Image, file: str, page: int, dpi: float) -> Sheet:
    """Страница-картинка (оттенки серого) → примитивы в pt, Y вверх."""
    h, w = gray.shape
    k = 72.0 / dpi
    words = ocr_words(gray)
    labels = [_label(wd, h, k) for wd in words]
    segments = [_to_pt(s, h, k) for s in line_segments(gray, words)]
    return Sheet(
        file,
        page,
        w * k,
        h * k,
        labels,
        segments,
        unit="pt",
        source="raster",
        tolerance=RASTER_TOLERANCE,
    )


# --- OCR ------------------------------------------------------------------------


def tiles(w: int, h: int, size: int = TILE, overlap: int = TILE_OVERLAP) -> list[tuple[int, int]]:
    """Левые верхние углы плиток, покрывающих изображение w × h с перекрытием."""
    step = size - overlap

    def starts(n: int) -> list[int]:
        if n <= size:
            return [0]
        out = list(range(0, n - size, step))
        return [*out, n - size]

    return [(x, y) for y in starts(h) for x in starts(w)]


def _ocr(img: Image) -> list[tuple[list[list[float]], str, float]]:
    result, _ = _engine()(img)
    return [(box, text, float(score)) for box, text, score in (result or [])]


def ocr_words(gray: Image) -> list[Word]:
    """Строки текста по плиткам: горизонтальные — как есть, вертикальные — проходом по
    изображению, повёрнутому на 90° по часовой (снизу-вверх становится слева-направо)."""
    h, w = gray.shape
    words: list[Word] = []
    for x, y in tiles(w, h):
        tile = gray[y : y + TILE, x : x + TILE]
        for box, text, score in _ocr(tile):
            xs, ys = [p[0] + x for p in box], [p[1] + y for p in box]
            if max(xs) - min(xs) >= max(ys) - min(ys):  # горизонтальная строка
                words.append(Word(text, score, min(xs), min(ys), max(xs), max(ys), False))
    # точка (x, y) → (h - 1 - y, x)
    turned: Image = np.asarray(cv2.rotate(gray, cv2.ROTATE_90_CLOCKWISE), dtype=np.uint8)
    th, tw = turned.shape
    for x, y in tiles(tw, th):
        tile = turned[y : y + TILE, x : x + TILE]
        for box, text, score in _ocr(tile):
            xs, ys = [p[0] + x for p in box], [p[1] + y for p in box]
            if max(xs) - min(xs) < max(ys) - min(ys):
                continue
            # Обратно в исходное: x = y', y = h - 1 - x'
            words.append(
                Word(text, score, min(ys), h - 1 - max(xs), max(ys), h - 1 - min(xs), True)
            )
    return dedupe([wd for wd in words if wd.score >= MIN_OCR_SCORE and wd.text.strip()])


def dedupe(words: Sequence[Word]) -> list[Word]:
    """Одна строка из двух плиток — одна: при пересечении больше половины меньшей
    остаётся более уверенная."""
    out: list[Word] = []
    for wd in sorted(words, key=lambda t: -t.score):
        if all(_overlap(wd, o) <= 0.5 for o in out):
            out.append(wd)
    return out


def _overlap(a: Word, b: Word) -> float:
    ix = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    iy = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    small = min((a.x1 - a.x0) * (a.y1 - a.y0), (b.x1 - b.x0) * (b.y1 - b.y0))
    return ix * iy / small if small > 0 else 0.0


def _label(wd: Word, h: int, k: float) -> Label:
    """Строка OCR → надпись разбора: база — нижний край строки (у вертикальной — правый)."""
    if wd.vertical:
        return Label(
            text=wd.text,
            direction="v",
            a0=(h - wd.y1) * k,
            a1=(h - wd.y0) * k,
            base=wd.x1 * k,
            perp=(wd.x0 + wd.x1) / 2 * k,
            height=(wd.x1 - wd.x0) * k,
            confidence=wd.score,
        )
    return Label(
        text=wd.text,
        direction="h",
        a0=wd.x0 * k,
        a1=wd.x1 * k,
        base=(h - wd.y1) * k,
        perp=(h - (wd.y0 + wd.y1) / 2) * k,
        height=(wd.y1 - wd.y0) * k,
        confidence=wd.score,
    )


# --- Линии ----------------------------------------------------------------------


def line_segments(
    gray: Image, words: Sequence[Word] = ()
) -> list[tuple[float, float, float, float]]:
    """Отрезки чертежа в px (Y вниз): текст закрашен, чтобы буквы не дали отрезков."""
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    for wd in words:
        x0, y0, x1, y1 = _mask_box(wd)
        cv2.rectangle(ink, (int(x0), int(y0)), (int(x1) + 1, int(y1) + 1), 0, -1)
    lines = cv2.HoughLinesP(
        ink,
        rho=1,
        theta=math.pi / 360,
        threshold=12,
        minLineLength=MIN_SEGMENT_PX,
        maxLineGap=2,
    )
    if lines is None:
        return []
    # Форма результата у версий OpenCV разная: (N, 1, 4) или (N, 4)
    return merge([snap(*map(float, row)) for row in np.asarray(lines).reshape(-1, 4)])


def _mask_box(wd: Word) -> tuple[float, float, float, float]:
    """Часть строки под маской: без края со стороны базовой линии (там размерная линия)."""
    if wd.vertical:  # база — справа
        w = wd.x1 - wd.x0
        return wd.x0 + MASK_TOP * w, wd.y0, wd.x1 - MASK_BOTTOM * w, wd.y1
    h = wd.y1 - wd.y0
    return wd.x0, wd.y0 + MASK_TOP * h, wd.x1, wd.y1 - MASK_BOTTOM * h


Px = tuple[float, float, float, float]


def merge(segments: Sequence[Px]) -> list[Px]:
    """Соосные куски горизонталей и вертикалей с зазором до MERGE_GAP_PX — в один отрезок;
    наклонные — как есть."""
    flat: list[tuple[float, float, float]] = []  # (поперёк, от, до) для горизонталей
    tall: list[tuple[float, float, float]] = []
    out: list[Px] = []
    for x0, y0, x1, y1 in segments:
        if y0 == y1:
            flat.append((y0, min(x0, x1), max(x0, x1)))
        elif x0 == x1:
            tall.append((x0, min(y0, y1), max(y0, y1)))
        else:
            out.append((x0, y0, x1, y1))
    out += [(a, c, b, c) for c, a, b in _join(flat)]
    out += [(c, a, c, b) for c, a, b in _join(tall)]
    return out


def _join(items: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    """(поперёк, от, до): куски одной линии, перекрытые или с малым зазором, — вместе."""
    out: list[list[float]] = []
    for c, a, b in sorted(items, key=lambda t: (round(t[0] / MERGE_AXIS_PX), t[1])):
        last = out[-1] if out else None
        if last and abs(last[0] - c) <= MERGE_AXIS_PX and a <= last[2] + MERGE_GAP_PX:
            last[2] = max(last[2], b)
        else:
            out.append([c, a, b])
    return [(c, a, b) for c, a, b in out]


def snap(x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float, float]:
    """Почти горизонтальный или вертикальный отрезок — ровно по оси."""
    angle = abs(math.degrees(math.atan2(y1 - y0, x1 - x0))) % 180
    if min(angle, 180 - angle) <= SNAP_DEG:
        y = (y0 + y1) / 2
        return x0, y, x1, y
    if abs(angle - 90) <= SNAP_DEG:
        x = (x0 + x1) / 2
        return x, y0, x, y1
    return x0, y0, x1, y1


def _to_pt(s: tuple[float, float, float, float], h: int, k: float) -> Segment:
    x0, y0, x1, y1 = s
    return Segment(x0 * k, (h - y0) * k, x1 * k, (h - y1) * k)
