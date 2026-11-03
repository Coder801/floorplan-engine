"""Raster adapter: scan, image PDF, JPEG/PNG → labels and segments (as for vector).

No LLM, local only:

- labels: OCR (RapidOCR, Apache-2.0) in overlapping tiles, so a large sheet is not shrunk
  before recognition. A second pass runs on the image rotated by 90°, so labels written
  bottom to top read as normal. Label confidence is the OCR estimate;
- segments: OpenCV (Apache-2.0): binarisation, text masked out, Hough segments; nearly
  horizontal and vertical ones are straightened (on a raster a line "wobbles" by a pixel).

Coordinates are converted to sheet pt (1 pt = 1/72 inch) from the bottom-left corner, Y up,
so the analysis (analysis.py) treats raster with the same rules as vector; its tolerances are
widened by RASTER_TOLERANCE: a segment end on a raster is accurate to a couple of pixels.
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

from floorplan_engine.service.facts.primitives import Label, Segment, Sheet

RENDER_DPI = 200  # an image PDF is rendered at this resolution
DEFAULT_LONG_MM = 420.0  # for an image without dpi the long side is taken as A3
TILE = 1280  # px: OCR tile side
TILE_OVERLAP = 192  # px: tile overlap, so a label at a seam is whole in one of them
MIN_OCR_SCORE = 0.5
SNAP_DEG = 2.0  # a segment closer than this angle to an axis is straightened
MIN_SEGMENT_PX = 8
MERGE_GAP_PX = 3.0  # collinear pieces of one line closer than this become one segment
MERGE_AXIS_PX = 1.5  # pieces on one line: cross offset no more than this
# Text mask covers the middle of the line: the dimension line runs under the label, leave it alone
MASK_TOP, MASK_BOTTOM = 0.1, 0.3
RASTER_TOLERANCE = 3.0  # how much wider the parser tolerances are than for vector
IMAGE_TYPES = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"})

Image = npt.NDArray[np.uint8]


@dataclass(frozen=True)
class Word:
    """Recognised line: a rectangle in image px (Y down) and a direction."""

    text: str
    score: float
    x0: float
    y0: float
    x1: float
    y1: float
    vertical: bool  # reads bottom to top


@cache
def _engine() -> Any:
    from rapidocr_onnxruntime import RapidOCR  # heavy import, only when needed

    return RapidOCR()


def read_image(path: Path, name: str | None = None) -> list[Sheet]:
    """An image is one page. dpi comes from the file, otherwise the long side = A3."""
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"{path.name}: не картинка или файл повреждён")
    gray: Image = np.asarray(img, dtype=np.uint8)
    dpi = _dpi(path) or max(gray.shape) / (DEFAULT_LONG_MM / 25.4)
    return [image_sheet(gray, name or path.name, 1, dpi)]


def read_raster_pdf(path: Path, name: str | None = None, dpi: int = RENDER_DPI) -> list[Sheet]:
    """PDF as images: each page is rendered and parsed as raster."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        count = len(pdf)
    finally:
        pdf.close()
    return [render_page(path, i, name or path.name, dpi) for i in range(1, count + 1)]


def render_page(path: Path, page_no: int, name: str, dpi: int = RENDER_DPI) -> Sheet:
    """A PDF page (from 1) is rendered in greyscale and parsed as raster."""
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
    """Image page (greyscale) → primitives in pt, Y up."""
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
    """Top-left corners of overlapping tiles covering a w × h image."""
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
    """Text lines by tile: horizontal ones as is, vertical ones by a pass over the image rotated
    90° clockwise (bottom-to-top becomes left-to-right)."""
    h, w = gray.shape
    words: list[Word] = []
    for x, y in tiles(w, h):
        tile = gray[y : y + TILE, x : x + TILE]
        for box, text, score in _ocr(tile):
            xs, ys = [p[0] + x for p in box], [p[1] + y for p in box]
            if max(xs) - min(xs) >= max(ys) - min(ys):  # horizontal line
                words.append(Word(text, score, min(xs), min(ys), max(xs), max(ys), False))
    # point (x, y) → (h - 1 - y, x)
    turned: Image = np.asarray(cv2.rotate(gray, cv2.ROTATE_90_CLOCKWISE), dtype=np.uint8)
    th, tw = turned.shape
    for x, y in tiles(tw, th):
        tile = turned[y : y + TILE, x : x + TILE]
        for box, text, score in _ocr(tile):
            xs, ys = [p[0] + x for p in box], [p[1] + y for p in box]
            if max(xs) - min(xs) < max(ys) - min(ys):
                continue
            # Back to the original: x = y', y = h - 1 - x'
            words.append(
                Word(text, score, min(ys), h - 1 - max(xs), max(ys), h - 1 - min(xs), True)
            )
    return dedupe([wd for wd in words if wd.score >= MIN_OCR_SCORE and wd.text.strip()])


def dedupe(words: Sequence[Word]) -> list[Word]:
    """The same line from two tiles becomes one: if they overlap by more than half of the smaller,
    the more confident one stays."""
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
    """OCR line → parser label: the baseline is the bottom edge of the line (the right one for
    vertical).
    """
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


# --- Lines ----------------------------------------------------------------------


def line_segments(
    gray: Image, words: Sequence[Word] = ()
) -> list[tuple[float, float, float, float]]:
    """Drawing segments in px (Y down): text is painted over so letters do not produce segments."""
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
    # OpenCV versions return different shapes: (N, 1, 4) or (N, 4)
    return merge([snap(*map(float, row)) for row in np.asarray(lines).reshape(-1, 4)])


def _mask_box(wd: Word) -> tuple[float, float, float, float]:
    """Part of the line under the mask: without the edge on the baseline side (the dimension line
    is there).
    """
    if wd.vertical:  # baseline on the right
        w = wd.x1 - wd.x0
        return wd.x0 + MASK_TOP * w, wd.y0, wd.x1 - MASK_BOTTOM * w, wd.y1
    h = wd.y1 - wd.y0
    return wd.x0, wd.y0 + MASK_TOP * h, wd.x1, wd.y1 - MASK_BOTTOM * h


Px = tuple[float, float, float, float]


def merge(segments: Sequence[Px]) -> list[Px]:
    """Collinear pieces of horizontals and verticals with a gap up to MERGE_GAP_PX become one
    segment; slanted ones stay as they are."""
    flat: list[tuple[float, float, float]] = []  # (across, from, to) for horizontals
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
    """(across, from, to): pieces of one line that overlap or have a small gap go together."""
    out: list[list[float]] = []
    for c, a, b in sorted(items, key=lambda t: (round(t[0] / MERGE_AXIS_PX), t[1])):
        last = out[-1] if out else None
        if last and abs(last[0] - c) <= MERGE_AXIS_PX and a <= last[2] + MERGE_GAP_PX:
            last[2] = max(last[2], b)
        else:
            out.append([c, a, b])
    return [(c, a, b) for c, a, b in out]


def snap(x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float, float]:
    """A nearly horizontal or vertical segment snapped exactly to the axis."""
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
