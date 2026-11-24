"""Fonts of the estimate report (epd/report.py): IBM Plex Sans, as in the viewer, cut down to
what the report prints and embedded in the page, so the PDF looks the same whatever fonts the
PDF service has.

From the variable IBM Plex Sans of Google Fonts (ofl/ibmplexsans, SIL Open Font License 1.1) it
takes weights 400 and 600 at normal width, keeps Latin, Cyrillic (with Ukrainian), digits,
punctuation and the signs the estimate uses (№, ×, Ø, ², —, …), and writes woff2 to
src/floorplan_engine/epd/fonts/. "Plex" is a Reserved Font Name: a cut-down file is a Modified
Version, so the family is renamed "Shtroba Report Sans" (OFL, condition 3).

    uv run --with brotli python scripts/report_fonts.py 'IBMPlexSans[wdth,wght].ttf'
"""

from __future__ import annotations

import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

OUT = Path(__file__).resolve().parent.parent / "src/floorplan_engine/epd/fonts"
FAMILY = "Shtroba Report Sans"
WEIGHTS = {"Regular": 400, "SemiBold": 600}
UNICODES = [
    *range(0x20, 0x7F),  # Basic Latin
    *range(0xA0, 0x100),  # Latin-1: nbsp, ², ×, «», °…
    *range(0x400, 0x460),  # Cyrillic, with і ї є ґ
    0x490, 0x491,  # Ґ ґ
    0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x201E,
    0x2022, 0x2026, 0x2032, 0x2033, 0x2116, 0x2212, 0x2248, 0x2264, 0x2265, 0x2300,
]  # fmt: skip


def build(source: Path, style: str, weight: int) -> Path:
    font = instancer.instantiateVariableFont(TTFont(source), {"wght": weight, "wdth": 100})
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["kern", "liga", "tnum", "lnum"]
    options.name_IDs = []  # names are written below
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=UNICODES)
    subsetter.subset(font)
    name = font["name"]
    name.names = []
    for nid, value in {
        1: FAMILY,
        2: "Regular" if weight == 400 else "Bold",
        4: f"{FAMILY} {style}",
        6: f"ShtrobaReportSans-{style}",
        16: FAMILY,
        17: style,
    }.items():
        name.setName(value, nid, 3, 1, 0x409)
    out = OUT / f"ShtrobaReportSans-{style}.woff2"
    font.flavor = "woff2"
    font.save(out)
    return out


def main(source: str) -> None:
    OUT.mkdir(exist_ok=True)
    for style, weight in WEIGHTS.items():
        path = build(Path(source), style, weight)
        print(path.name, path.stat().st_size)


if __name__ == "__main__":
    main(sys.argv[1])
