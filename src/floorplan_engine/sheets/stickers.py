"""Panel stickers on paper: layout of one sticker in mm and a PDF sheet for printing.

A sticker stands upright, 10 × 25 mm: number, name, icon from top to bottom. The name wraps
by real font width, `lay_out` gives ready lines with their baselines. Text is curves in the PDF
and in the viewer alike (key `panel.stickers`, docs/epd-format.md): the condensed font has no
web version with Cyrillic, and the screen shows exactly what prints.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from math import floor
from pathlib import Path
from typing import Any

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.patches import FancyBboxPatch, PathPatch
from matplotlib.path import Path as MplPath
from matplotlib.textpath import TextPath
from matplotlib.transforms import Affine2D

from floorplan_engine import BRAND
from floorplan_engine.drawing.layers import FONT_DIR
from floorplan_engine.electrical.panel import BoardPanel
from floorplan_engine.electrical.panel_text import text
from floorplan_engine.electrical.stickers import Sticker, build_stickers
from floorplan_engine.model.texts import Language
from floorplan_engine.sheets.printing import MM_PER_INCH, PT_PER_MM

WIDTH, HEIGHT = 10.0, 25.0  # mm: upright, ratio 2.5
PAD = 0.7  # mm: number and rule from the edge
NAME_PAD = 0.45  # mm: the name may go wider, words are long and the sticker is narrow
NUMBER_EM = 3.6  # mm, shrinks to fit the width
NUMBER_BASELINE = 3.7
RULE_Y = 4.7
ICON_SIZE = 6.4
ICON_Y = HEIGHT - PAD - ICON_SIZE
ICON_STROKE = 1.6  # in icon units, 24 per icon
NAME_TOP, NAME_BOTTOM = RULE_Y + 0.6, ICON_Y - 0.5
NAME_EMS = (2.3, 2.1, 1.9, 1.7)  # mm, the largest that fits
LEADING = 1.12  # line step, in em
VOWELS = "аеёиоуыэюяіїє"

PAGE_W, PAGE_H = 210.0, 297.0  # A4
MARGIN = 10.0
GAP = 2.0
HEADER, FOOTER = 8.0, 12.0
HAIRLINE = 0.1  # mm, cut outline
CORNER = 0.8

ASSETS = Path(__file__).resolve().parent / "stickers_assets"
NAME_FONT = FontProperties(fname=FONT_DIR / "IBMPlexSansCondensed-Medium.ttf")
NUMBER_FONT = FontProperties(fname=FONT_DIR / "IBMPlexSansCondensed-SemiBold.ttf")


@lru_cache
def icons() -> dict[str, list[str]]:
    """Icon paths, absolute M/L/C/Z in a 24-unit box (scripts/sticker_icons.py)."""
    loaded: dict[str, list[str]] = json.loads((ASSETS / "icons.json").read_text("utf-8"))
    return loaded


def _width(line: str, em: float, font: FontProperties) -> float:
    return float(TextPath((0, 0), line, size=em, prop=font).get_extents().width) if line else 0.0


def _tokens(block: str) -> list[str]:
    """Pieces a line may break between: words, and after a hyphen ("Кухня-", "вітальня")."""
    return [p for word in block.split() for p in re.findall(r"[^-]+-?|-", word)]


def _can_cut(word: str, at: int) -> bool:
    """A hyphen may stand here: after a vowel or between consonants, ь and й stay on the left,
    and no piece of one or two letters: "Кондиціо-нер", "Холодиль-ник"."""
    left, right = word[at - 1].lower(), word[at].lower()
    if at < 3 or len(word) - at < 3 or right in "ьъй":
        return False
    return left in VOWELS or (right not in VOWELS and left not in "ьъ") or left in "ьй"


def _split_word(word: str, em: float, room: float) -> list[str]:
    """A word wider than the sticker: hyphen at the last syllable break that fits."""
    pieces = []
    while _width(word, em, NAME_FONT) > room:
        fits = [
            n for n in range(len(word) - 1, 0, -1) if _width(f"{word[:n]}-", em, NAME_FONT) <= room
        ]
        cut = next((n for n in fits if _can_cut(word, n)), fits[0])
        pieces.append(f"{word[:cut]}-")
        word = word[cut:]
    return [*pieces, word]


def _wrap(blocks: tuple[str, ...], em: float, room: float, split: bool) -> list[str] | None:
    """Lines at this size; None if a word does not fit and may not be split."""
    lines: list[str] = []
    for block in blocks:
        line = ""
        for token in _tokens(block):
            glue = "" if line.endswith("-") or not line else " "
            if _width(f"{line}{glue}{token}", em, NAME_FONT) <= room:
                line = f"{line}{glue}{token}"
                continue
            if line:
                lines.append(line)
            pieces = [token]
            if _width(token, em, NAME_FONT) > room:
                if not split:
                    return None
                pieces = _split_word(token, em, room)
            lines.extend(pieces[:-1])
            line = pieces[-1]
        lines.append(line)
    return lines


def _fit_name(blocks: tuple[str, ...]) -> tuple[list[str], float]:
    """The largest size at which the name fits; at the smallest, extra lines end with "…"."""
    room = WIDTH - 2 * NAME_PAD
    height = NAME_BOTTOM - NAME_TOP
    for em in NAME_EMS:
        lines = _wrap(blocks, em, room, split=False)
        if lines is not None and len(lines) * em * LEADING <= height:
            return lines, em
    em = NAME_EMS[-1]
    lines = _wrap(blocks, em, room, split=True) or []
    limit = int(height / (em * LEADING))
    if len(lines) > limit:
        lines = lines[:limit]
        last = lines[-1].rstrip("-")
        while last and _width(f"{last}…", em, NAME_FONT) > room:
            last = last[:-1]
        lines[-1] = f"{last}…"
    return lines, em


@dataclass(frozen=True)
class Layout:
    """A sticker ready to draw, mm from its top left corner: text is centred on the width."""

    sticker: Sticker
    number_em: float
    lines: tuple[tuple[str, float], ...]  # line and its baseline
    name_em: float


def lay_out(sticker: Sticker) -> Layout:
    room = WIDTH - 2 * PAD
    width = _width(sticker.id, NUMBER_EM, NUMBER_FONT)
    number_em = NUMBER_EM * min(1.0, room / width) if width else NUMBER_EM
    lines, em = _fit_name(sticker.lines)
    step = em * LEADING
    top = NAME_TOP + (NAME_BOTTOM - NAME_TOP - step * len(lines)) / 2
    placed = tuple((ln, round(top + step * n + em * 0.86, 2)) for n, ln in enumerate(lines))
    return Layout(sticker, floor(number_em * 100) / 100, placed, em)


def _line_path(
    line: str, x: float, y: float, em: float, font: FontProperties, centred: bool = True
) -> MplPath:
    """A line of curves from x or centred on it, baseline y, in mm with y going down."""
    path = TextPath((0, 0), line, size=em, prop=font)
    box = path.get_extents()
    shift = -(box.x0 + box.x1) / 2 if centred else -box.x0
    return Affine2D().translate(shift, 0).scale(1, -1).translate(x, y).transform_path(path)


def _sticker_lines(laid: Layout) -> list[MplPath]:
    """Number and name in sticker mm."""
    mid = WIDTH / 2
    paths = [_line_path(laid.sticker.id, mid, NUMBER_BASELINE, laid.number_em, NUMBER_FONT)]
    paths += [_line_path(ln, mid, y, laid.name_em, NAME_FONT) for ln, y in laid.lines if ln]
    return paths


def _svg_path(laid: Layout) -> str:
    """Text of a sticker as one SVG path, to 0.001 mm: the glyphs are under 2 mm high."""
    letters = {MplPath.MOVETO: "M", MplPath.LINETO: "L", MplPath.CURVE3: "Q", MplPath.CURVE4: "C"}
    out: list[str] = []
    for path in _sticker_lines(laid):
        for points, code in path.iter_segments(simplify=False, curves=True):
            if code == MplPath.CLOSEPOLY:
                out.append("Z")
            else:
                out.append(
                    letters[code] + " ".join(f"{v:.3f}".rstrip("0").rstrip(".") for v in points)
                )
    return "".join(out)


def stickers_data(panel: BoardPanel) -> dict[str, object]:
    """Stickers for the viewer (key `stickers` of `panel`): sizes, geometry of each, used icons."""
    laid = [lay_out(s) for s in build_stickers(panel)]
    used = sorted({x.sticker.icon for x in laid})
    return {
        "width": WIDTH,
        "height": HEIGHT,
        "rule_y": RULE_Y,
        "pad": PAD,
        "icon": {
            "x": (WIDTH - ICON_SIZE) / 2,
            "y": ICON_Y,
            "size": ICON_SIZE,
            "stroke": ICON_STROKE,
        },
        "items": [
            {
                "id": x.sticker.id,
                "row": x.sticker.row,
                "title": x.sticker.title,
                "icon": x.sticker.icon,
                "text": _svg_path(x),
            }
            for x in laid
        ],
        "icons": {key: icons()[key] for key in used},
    }


def _icon_path(d: str) -> MplPath:
    """SVG path of M/L/C/Z as a matplotlib path."""
    verts: list[tuple[float, float]] = []
    codes: list[Any] = []
    for op, args in re.findall(r"([MLCZ])([^MLCZ]*)", d):
        n = [float(v) for v in args.split()]
        points = list(zip(n[::2], n[1::2], strict=True))
        if op == "Z":
            verts.append(verts[-1])
            codes.append(MplPath.CLOSEPOLY)
        elif op == "C":
            verts.extend(points)
            codes.extend([MplPath.CURVE4] * 3)
        else:
            verts.extend(points)
            codes.append(MplPath.MOVETO if op == "M" else MplPath.LINETO)
    return MplPath(verts, codes)


def _draw(fig: Figure, laid: Layout, x: float, y: float) -> None:
    ax = fig.axes[0]
    ax.add_patch(
        FancyBboxPatch(
            (x + CORNER, y + CORNER),
            WIDTH - 2 * CORNER,
            HEIGHT - 2 * CORNER,
            boxstyle=f"round,pad={CORNER},rounding_size={CORNER}",
            fc="none",
            ec="#b0b0b0",
            lw=HAIRLINE * PT_PER_MM,
        )
    )
    mid = x + WIDTH / 2
    for path in _sticker_lines(laid):
        place = Affine2D().translate(x, y)
        ax.add_patch(PathPatch(place.transform_path(path), fc="black", lw=0))
    ax.plot(
        [x + PAD, x + WIDTH - PAD],
        [y + RULE_Y, y + RULE_Y],
        color="black",
        lw=0.15 * PT_PER_MM,
        solid_capstyle="butt",
    )
    scale = ICON_SIZE / 24
    place = Affine2D().scale(scale).translate(mid - ICON_SIZE / 2, y + ICON_Y)
    for d in icons()[laid.sticker.icon]:
        ax.add_patch(
            PathPatch(
                place.transform_path(_icon_path(d)),
                fc="none",
                ec="black",
                lw=ICON_STROKE * scale * PT_PER_MM,
                capstyle="round",
                joinstyle="round",
            )
        )


def _page() -> Figure:
    fig = Figure(figsize=(PAGE_W / MM_PER_INCH, PAGE_H / MM_PER_INCH))
    ax = fig.add_axes((0.0, 0.0, 1.0, 1.0))
    ax.set_xlim(0, PAGE_W)
    ax.set_ylim(PAGE_H, 0)
    ax.axis("off")
    return fig


def _pages(laid: list[Layout]) -> list[list[tuple[Layout, float, float]]]:
    """Stickers on A4 pages: each rail starts a new line, as it does in the panel."""
    columns = int((PAGE_W - 2 * MARGIN + GAP) // (WIDTH + GAP))
    bottom = PAGE_H - MARGIN - FOOTER
    pages: list[list[tuple[Layout, float, float]]] = [[]]
    column, y, row = 0, MARGIN + HEADER, laid[0].sticker.row if laid else 0
    for item in laid:
        if column == columns or item.sticker.row != row:
            column, y = 0, y + HEIGHT + GAP
            row = item.sticker.row
        if y + HEIGHT > bottom:
            pages.append([])
            column, y = 0, MARGIN + HEADER
        pages[-1].append((item, MARGIN + column * (WIDTH + GAP), y))
        column += 1
    return pages


def write_stickers(panel: BoardPanel, name: str, language: Language, path: Path) -> Path:
    """A4 PDF of the panel stickers at actual size, to print at 100 %."""
    laid = [lay_out(s) for s in build_stickers(panel)]
    title = text("stickers_title", language, name=name)
    size = f"{WIDTH:g} × {HEIGHT:g}"
    note = text("stickers_note", language, size=size)
    metadata = {"Title": title, "Creator": f"{BRAND} (floorplan-engine)", "CreationDate": None}
    with PdfPages(path, metadata=metadata) as pdf:
        for placed in _pages(laid):
            fig = _page()
            ax = fig.axes[0]
            for item, x, y in placed:
                _draw(fig, item, x, y)
            head = _line_path(title, MARGIN, MARGIN + 3, 3.6, NUMBER_FONT, centred=False)
            ax.add_patch(PathPatch(head, fc="black", lw=0))
            y = PAGE_H - MARGIN
            foot = _line_path(note, MARGIN, y, 2.6, NAME_FONT, centred=False)
            ax.add_patch(PathPatch(foot, fc="#555555", lw=0))
            # 50 mm ruler: measure it on paper to check the printer did not scale the page
            ruler = [PAGE_W - MARGIN - 50, PAGE_W - MARGIN]
            ax.plot(ruler, [y, y], color="black", lw=0.25 * PT_PER_MM, solid_capstyle="butt")
            for x in ruler:
                ax.plot([x, x], [y - 1.2, y], color="black", lw=0.25 * PT_PER_MM)
            mark = _line_path("50 mm", PAGE_W - MARGIN - 25, y - 1.2, 2.4, NAME_FONT)
            ax.add_patch(PathPatch(mark, fc="black", lw=0))
            pdf.savefig(fig)
    return path
