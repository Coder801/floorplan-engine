"""File names in a project's out/ folder."""

from __future__ import annotations

OUT_DIR = "out"
PROJECT_FILE = "project.dxf"
ARTIFACT_FILE = "project.epd"
ALBUM_FILE = "album.pdf"  # PDF album of the sheets (print command)
WIRING_JOURNAL_FILE = "wiring-boxes.csv"  # cable log of wiring through boxes
CHASES_FILE = "wiring-chases.csv"  # wall chase schedule
LOADS_FILE = "panel-loads.csv"  # load list by panel group
STICKERS_FILE = "panel-stickers.pdf"  # panel stickers for printing
STICKERS_COLOR_FILE = "panel-stickers-color.pdf"  # the same in group colours
STICKERS_SHORT_FILE = "panel-stickers-short.pdf"  # line number without letters: 12, not QF12
STICKERS_COLOR_SHORT_FILE = "panel-stickers-color-short.pdf"
STICKERS_FILES = (
    STICKERS_FILE,
    STICKERS_COLOR_FILE,
    STICKERS_SHORT_FILE,
    STICKERS_COLOR_SHORT_FILE,
)
SHEETS_DIR = "sheets"


SEWER_ROUTES_FILE = "sewer-routes.json"  # sewer routes: pieces, zones, heights, errors
PLUMBING_ESTIMATE_FILES = (
    "plumbing-estimate.md",
    "plumbing-estimate.csv",
    "plumbing-estimate.xlsx",
)
