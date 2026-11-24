"""Brand mark and wordmark as SVG paths, for pages that load no fonts (the estimate report,
epd/report.py: `LOGO_MARK`, `LOGO_WORD`).

The viewer draws the mark with text in the brand font (web/src/ui/Logo: "St", Chakra Petch 600,
15 px, letter spacing -0.02 em, centred at x 16, baseline 21.5 in the -2 0 36 32 box) and the
wordmark next to it (pages/Gate: "Shtroba", 18 px, letter spacing 0.02 em). This script lays the
same letters out from the font file and prints the paths to paste into report.py. Chakra Petch is
under the SIL Open Font License; the file is the SemiBold woff2 with Latin from Google Fonts.

    uv run --with brotli python scripts/brand_paths.py ChakraPetch-SemiBold.woff2
"""

from __future__ import annotations

import sys

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont


def layout(font: TTFont, text: str, size: float, spacing_em: float) -> tuple[str, float]:
    """Path of text from x 0 on baseline 0 (y down) and its advance width."""
    scale = size / font["head"].unitsPerEm
    cmap, glyphs, hmtx = font.getBestCmap(), font.getGlyphSet(), font["hmtx"]
    pen = SVGPathPen(glyphs, ntos=lambda v: f"{v:.2f}".rstrip("0").rstrip("."))
    x = 0.0
    for i, ch in enumerate(text):
        name = cmap[ord(ch)]
        glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, x, 0)))
        x += hmtx[name][0] * scale + (spacing_em * size if i < len(text) - 1 else 0)
    return pen.getCommands(), x


def main(path: str) -> None:
    font = TTFont(path)
    mark, width = layout(font, "St", 15, -0.02)
    print(f"MARK x0 {16 - width / 2:.2f} y 21.5\n{mark}\n")
    word, width = layout(font, "Shtroba", 18, 0.02)
    print(f"WORD width {width:.2f}\n{word}")


if __name__ == "__main__":
    main(sys.argv[1])
