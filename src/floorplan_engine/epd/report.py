"""Estimate report as one HTML page, from a built .epd: the source of the estimate PDF.

The PDF service (pdf-generator-service, Playwright) opens this page and prints it to A4
(`format: "a4"`, `orientation` as here; viewport as wide as the sheet at 96 dpi — 794 px
portrait, 1123 px landscape — so the scale is 1). The page is laid out for A4 in mm: page size
and margins come from `@page`, table headers repeat on every page, a row does not break across
pages, the page number and the brand are in the bottom page margin (`@page` margin boxes,
Chromium 131+). No scripts and no external files: the font is IBM Plex Sans, as in the viewer,
cut down and embedded (epd/fonts, scripts/report_fonts.py), so the PDF does not depend on the
fonts of the PDF service; the page is ready as soon as it loads, and the same .epd and parts
always give the same HTML.

The look follows anvilco/html-pdf-invoice-template (MIT, Anvil Foundry Inc.): a header with the
project large on the left and the document on the right, quiet grey upper-case column headings,
rows without heavy rules, and a closing block with the grand total large and in colour.

Parts (`PARTS`), chosen in the download dialog:
  plan             electrical plan: the wiring sheet (`stage` wiring) cut to its drawing area
                   (`view`), black and white: light fills stay white, everything else is black;
                   always lying horizontally: a drawing taller than wide is turned a quarter;
                   lighting lines dashed, the rest solid; under it a short legend in a grid: the
                   two kinds of line, the junction box and the point symbols of the electrical
                   sheet legend (key `legend` of the electrical page)
  material_rough   rough materials: the estimate section of the wiring page (key `estimate`)
  material_finish  finish materials
  work_rough       rough work; what each item includes and its result (work scope) go to an
                   appendix after the closing block, the work table says so under its heading
  work_finish      finishing work
  panel            single-line diagram of the panel (epd/single_line.py), top down, in tiers
                   as wide as the page, from the panel page (`stage` panel, key `panel`);
                   always last, on a new page (on screen set off by a rule)
An estimate that is not split into rough and finish materials (section `material`) is shown
with either materials part. Every priced estimate ends with a closing block: section
totals and their sum. The estimate notes (where the prices come from, items without a price,
how the panel is counted) are for the studio and stay out of the report; the mark of a
provisional materials total stays.
"""

from __future__ import annotations

import base64
import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal, cast, get_args

from floorplan_engine import BRAND
from floorplan_engine.electrical.estimate import (
    MATERIAL_SECTIONS,
    SECTIONS,
    Section,
    format_number,
    parse_number,
    section_title,
)
from floorplan_engine.electrical.estimate import text as estimate_text
from floorplan_engine.electrical.panel_text import DEVICE_LEGEND
from floorplan_engine.epd.single_line import assumed_any, single_line_svgs
from floorplan_engine.model.texts import Language

Orientation = Literal["portrait", "landscape"]
ORIENTATIONS: tuple[Orientation, ...] = get_args(Orientation)
Part = Literal["plan", "material_rough", "material_finish", "work_rough", "work_finish", "panel"]
PARTS: tuple[Part, ...] = get_args(Part)
ESTIMATE_PARTS: dict[Part, tuple[Section, ...]] = {
    "material_rough": ("material_rough", "material"),
    "material_finish": ("material_finish", "material"),
    "work_rough": ("rough",),
    "work_finish": ("finish",),
}
WORK_SECTIONS: tuple[Section, ...] = ("rough", "finish")

# Plan on the page: the box it fits in (A4 minus margins, the report title and the plan heading),
# the thinnest printed line and the lightness above which a colour prints white
PLAN_BOX_MM: dict[Orientation, tuple[float, float]] = {
    "portrait": (186.0, 196.0),
    "landscape": (273.0, 104.0),
}
# Brand as in the viewer (web/src/ui/Logo, pages/Gate): the "St" mark in a frame with two corners
# and the "Shtroba" wordmark, letters in Chakra Petch 600 turned into paths by
# scripts/brand_paths.py (the report loads no fonts)
# Single-line diagram on its page: the box it fits in (A4 minus margins and its heading)
PANEL_BOX_MM: dict[Orientation, tuple[float, float]] = {
    "portrait": (186.0, 245.0),
    "landscape": (273.0, 158.0),
}
LOGO_MARK = (
    "M0.82 -1.54V-2.86H2.53V-2.07L3.1 -1.5H6.38L6.97 -2.1V-4.04L6.39 -4.62H2.4L0.85 "
    "-6.15V-8.96L2.4 -10.5H7.02L8.56 -8.96V-7.62H6.85V-8.43L6.27 -9H3.15L2.56 -8.43V-6.69L3.15 "
    "-6.12H7.14L8.69 -4.58V-1.57L7.11 0H2.37ZM10.79 "
    "-1.48V-6.03H9.44V-7.47H10.81V-9.9H12.48V-7.47H14.77V-6.03H12.48V-2.02L13.06 "
    "-1.44H14.77V0H12.27Z"
)
LOGO_MARK_X = 8.39  # the letters centred in the -2 0 36 32 box, baseline 21.5
LOGO_WORD = (
    "M0.99 -1.85V-3.44H3.04V-2.48L3.73 -1.8H7.65L8.37 -2.52V-4.84L7.67 -5.54H2.88L1.03 "
    "-7.38V-10.75L2.88 -12.6H8.42L10.28 -10.75V-9.14H8.23V-10.12L7.52 -10.8H3.78L3.08 "
    "-10.12V-8.03L3.78 -7.34H8.57L10.42 -5.49V-1.89L8.53 0H2.84ZM12.85 -12.85H14.89V-7.42L16.43 "
    "-8.96H19.26L21.15 -7.07V0H19.12V-6.52L18.41 -7.22H16.76L14.89 -5.33V0H12.85ZM24.57 "
    "-1.78V-7.24H22.95V-8.96H24.61V-11.88H26.6V-8.96H29.36V-7.24H26.6V-2.43L27.31 "
    "-1.73H29.36V0H26.35ZM31.43 -8.96H33.32V-7.43L34.81 -8.96H37.3V-7.22H35.26L33.46 "
    "-5.38V0H31.43ZM38.83 -1.8V-7.16L40.61 -8.96H45.58L47.38 -7.16V-1.8L45.58 0H40.61ZM44.62 "
    "-1.71 45.34 -2.43V-6.53L44.62 -7.25H41.58L40.86 -6.53V-2.43L41.58 -1.71ZM49.9 "
    "-1.85V-12.85H51.93V-7.56L53.39 -8.96H56.61L58.41 -7.16V-1.8L56.61 0H51.73ZM55.62 -1.75 "
    "56.38 -2.5V-6.46L55.62 -7.22H53.71L51.93 -5.44V-2.5L52.69 -1.75ZM60.66 -1.6V-3.73L62.26 "
    "-5.31H66.89V-6.64L66.22 -7.31H63.4L62.73 -6.64V-6.07H60.73V-7.11L62.57 -8.96H67.05L68.89 "
    "-7.11V0H67.03V-1.39L65.59 0H62.26ZM65.39 -1.6 66.89 -3.04V-3.8H63.23L62.66 "
    "-3.24V-2.14L63.2 -1.6Z"
)
LOGO_WORD_WIDTH = 69.97

MIN_STROKE_MM = 0.12
WHITE_ABOVE = 0.85

TEXT: dict[str, dict[Language, str]] = {
    "estimate": {"ru": "Смета электрики", "uk": "Кошторис електрики"},
    "plan": {"ru": "План электрики", "uk": "План електрики"},
    "plan_note": {
        "ru": "Трассы кабелей, коробки, точки и щит — как на листе проводки",
        "uk": "Траси кабелів, коробки, точки і щит — як на аркуші проводки",
    },
    "legend_power": {
        "ru": "Линии розеток, техники и слабого тока",
        "uk": "Лінії розеток, техніки і слабкого струму",
    },
    "legend_light": {"ru": "Линии освещения", "uk": "Лінії освітлення"},
    "legend_box": {"ru": "Распаечная коробка", "uk": "Розподільча коробка"},
    "no_plan": {
        "ru": "В сборке нет листа проводки",
        "uk": "У збірці немає аркуша проводки",
    },
    "no_estimate": {
        "ru": "В сборке нет сметы электрики",
        "uk": "У збірці немає кошторису електрики",
    },
    "no_section": {
        "ru": "В смете нет этого раздела",
        "uk": "У кошторисі немає цього розділу",
    },
    "panel": {"ru": "Однолинейная схема щита", "uk": "Однолінійна схема щита"},
    "panel_note": {
        "ru": "Аппараты щита и линии групп; мощность — установленная",
        "uk": "Апарати щита і лінії груп; потужність — встановлена",
    },
    "no_panel": {"ru": "В сборке нет щита", "uk": "У збірці немає щита"},
    "panel_warnings": {"ru": "Замечания расчёта", "uk": "Зауваження розрахунку"},
    "assumed_note": {
        "ru": "* — допущение: уточняется по техусловиям или у заказчика",
        "uk": "* — припущення: уточнюється за техумовами або у замовника",
    },
    "col_group": {"ru": "Группа", "uk": "Група"},
    "col_device": {"ru": "Аппарат", "uk": "Апарат"},
    "col_cable": {"ru": "Кабель", "uk": "Кабель"},
    "col_power": {"ru": "Мощность, Вт", "uk": "Потужність, Вт"},
    "col_current": {"ru": "Ток, А", "uk": "Струм, А"},
    "col_purpose": {"ru": "Назначение", "uk": "Призначення"},
    "summary": {"ru": "Разделы", "uk": "Розділи"},
    "page": {"ru": "Страница", "uk": "Сторінка"},
    "of": {"ru": "из", "uk": "з"},
    "includes": {"ru": "Входит", "uk": "Входить"},
    "appendix": {"ru": "Приложение. Что входит в работы", "uk": "Додаток. Що входить у роботи"},
    "appendix_lead": {
        "ru": "По каждой работе сметы: что входит в её цену и какой результат принимается "
        "при сдаче. Номера — как в таблицах работ.",
        "uk": "Для кожної роботи кошторису: що входить у її ціну і який результат приймається при "
        "здачі. Номери — як у таблицях робіт.",
    },
    "appendix_ref": {
        "ru": "Что входит в каждую работу и результат при сдаче — "
        "в приложении «Что входит в работы»",
        "uk": "Що входить у кожну роботу і результат при здачі — у додатку «Що входить у роботи»",
    },
    "result": {"ru": "Результат", "uk": "Результат"},
    "guess": {
        "ru": "≈ — цены материалов ориентировочные: типовые, не рыночные",
        "uk": "≈ — ціни матеріалів орієнтовні: типові, не ринкові",
    },
    "approximate": {"ru": "цены ориентировочные", "uk": "ціни орієнтовні"},
}


def text(key: str, language: Language) -> str:
    return TEXT[key][language]


def parts_of(values: Sequence[str]) -> tuple[Part, ...]:
    """Parts by name in report order, without repeats; an unknown name is a ValueError."""
    unknown = [v for v in values if v not in PARTS]
    if unknown:
        raise ValueError(f"неизвестные части: {', '.join(unknown)}; есть: {', '.join(PARTS)}")
    return tuple(p for p in PARTS if p in values)


@dataclass(frozen=True)
class _Block:
    """One estimate section of the page table: its heading, rows and total row."""

    section: Section
    title: str
    rows: tuple[dict[str, Any], ...]
    subtotal: dict[str, Any] | None
    approximate: bool = False  # materials priced by the placeholder service: the prices are rough


def report_title(parts: Sequence[Part], language: Language) -> str:
    """The document the report is: the estimate when it holds an estimate part (or nothing),
    otherwise the plan or the single-line diagram; the PDF file is named after it too."""
    if any(p in ESTIMATE_PARTS for p in parts) or not parts:
        return text("estimate", language)
    return text("plan" if "plan" in parts else "panel", language)


def report_filename(manifest: dict[str, Any], parts: Sequence[Part]) -> str:
    """The PDF file name: "<project> — <document>.pdf"; characters a file system refuses
    (/ \\ : * ? " < > |) become spaces."""
    project = str((manifest.get("project") or {}).get("name") or "").strip()
    title = report_title(parts, _language(manifest))
    name = f"{project} — {title}" if project else title
    safe = "".join(" " if c in '/\\:*?"<>|' or ord(c) < 32 else c for c in name)
    return " ".join(safe.split()) + ".pdf"


def report_html(
    manifest: dict[str, Any],
    wiring: dict[str, Any] | None,
    parts: Sequence[Part],
    orientation: Orientation = "portrait",
    panel: dict[str, Any] | None = None,
    legend: Sequence[dict[str, Any]] = (),
) -> str:
    """The report page: manifest of the .epd, its wiring page (None: none in the build), the
    chosen parts, the A4 orientation, the `panel` key of its panel page (None: no panel) and the
    `legend` of the electrical page (point symbols for the plan legend).
    Without parts it is the title only.

    Sections are independent in style: each is a <section> with its own root class (`r-head`,
    `r-plan`, `r-lines`, `r-closing`), its CSS sits next to its function and selects only inside
    that class, and the page takes the CSS of the sections it holds. Nothing is shared but the
    page box (`@page`, the body margin)."""
    language = _language(manifest)
    project = str((manifest.get("project") or {}).get("name") or "")
    estimate = (wiring or {}).get("estimate")
    chosen = [p for p in parts if p in ESTIMATE_PARTS]
    title = report_title(parts, language)
    body = [_header(project, title)]
    styles = [_page_css(project, orientation, language), HEAD_CSS]
    if "plan" in parts:
        body.append(_plan(wiring, language, PLAN_BOX_MM[orientation], legend))
        styles.append(PLAN_CSS)
    if chosen:
        body.append(_estimate(estimate, chosen, language))
        styles += [LINES_CSS, CLOSING_CSS, APPENDIX_CSS]
    if "panel" in parts:
        body.append(_panel(panel, wiring, language, PANEL_BOX_MM[orientation]))
        styles.append(PANEL_CSS)
    return "".join(
        [
            "<!doctype html>",
            f'<html lang="{language}"><head><meta charset="utf-8">',
            f"<title>{_e(project or title)} · {_e(title)}</title>",
            f"<style>{''.join(styles)}</style>",
            "</head><body>",
            *body,
            "</body></html>",
        ]
    )


FONT = '"Shtroba Report Sans", "IBM Plex Sans", Arial, Helvetica, sans-serif'
FONTS_DIR = Path(__file__).parent / "fonts"


@cache
def _font_faces() -> str:
    """IBM Plex Sans 400 and 600 (cut down and renamed, scripts/report_fonts.py) as data URIs."""
    faces = []
    for style, weight in (("Regular", 400), ("SemiBold", 600)):
        data = (FONTS_DIR / f"ShtrobaReportSans-{style}.woff2").read_bytes()
        faces.append(
            '@font-face { font-family: "Shtroba Report Sans"; font-style: normal;'
            f" font-weight: {weight}; src: url(data:font/woff2;base64,"
            f'{base64.b64encode(data).decode("ascii")}) format("woff2"); }}'
        )
    return "".join(faces)


def _page_css(project: str, orientation: Orientation, language: Language) -> str:
    """The page box: A4, margins, the brand and the page number in the bottom margin."""
    footer = _css_string(f"{BRAND} · {project}" if project else BRAND)
    number = f'"{text("page", language)} " counter(page) " {text("of", language)} " counter(pages)'
    margin = f"font: 7.5pt {FONT}; color: #777;"
    return _font_faces() + (
        f"@page {{ size: A4 {orientation}; margin: 12mm 12mm 16mm;"
        f" @bottom-left {{ content: {footer}; {margin} }}"
        f" @bottom-right {{ content: {number}; {margin} }} }}"
        "html, body { margin: 0; padding: 0; background: #fff; }"
        # On screen (the page opened from the viewer) the report is a column, not the full window
        "@media screen { body { max-width: 1024px; margin: 0 auto; padding: 24px 16px; } }"
    )


def _header(project: str, title: str) -> str:
    """One line: the brand, the project, the document on the right; a rule under it."""
    return "".join(
        [
            f'<section class="r-head">{_brand()}',
            f'<div class="r-head__project">{_e(project)}</div>',
            f'<div class="r-head__title">{_e(title)}</div></section>',
        ]
    )


def _brand() -> str:
    """Mark and wordmark, as on the viewer login page; the name stays readable as text."""
    return "".join(
        [
            f'<div class="r-head__brand" role="img" aria-label="{BRAND}">',
            '<svg class="r-head__mark" viewBox="-2 0 36 32">',
            '<path d="M-.5 11V1.5H9M32.5 21v9.5H23" fill="none" stroke="currentColor"',
            ' stroke-width="3" stroke-linecap="square"/>',
            f'<path d="{LOGO_MARK}" transform="translate({LOGO_MARK_X} 21.5)"',
            ' fill="currentColor"/>',
            "</svg>",
            f'<svg class="r-head__word" viewBox="0 -18.5 {LOGO_WORD_WIDTH} 24">',
            f'<path d="{LOGO_WORD}" fill="currentColor"/></svg>',
            "</div>",
        ]
    )


HEAD_CSS = f"""
.r-head {{ font: 10pt/1.3 {FONT}; color: #1d2330; display: flex; align-items: center;
  gap: 6mm; padding-bottom: 3mm; border-bottom: 0.4mm solid #1d2330; }}
.r-head__brand {{ display: flex; align-items: center; gap: 1.6mm; flex: none; }}
.r-head__mark {{ height: 6.5mm; width: 7.3mm; overflow: visible; }}
.r-head__word {{ height: 4.9mm; width: auto; }}
.r-head__project {{ flex: 1 1 auto; min-width: 0; font-size: 12pt; font-weight: 600;
  padding-left: 6mm; border-left: 0.3mm solid #ccc; }}
.r-head__title {{ flex: none; font-size: 10pt; color: #555; }}
"""


def _css_string(value: str) -> str:
    """A CSS string literal for `content`, safe inside <style>: quotes, backslashes and "<" are
    CSS escapes (a project named "</style>" does not end the style sheet)."""
    out = value.replace("\\", "\\5C ").replace('"', "\\22 ").replace("<", "\\3C ")
    return '"' + out.replace("\n", " ") + '"'


def _language(manifest: dict[str, Any]) -> Language:
    value = (manifest.get("project") or {}).get("language")
    return cast(Language, value) if value in get_args(Language) else "ru"


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


# --- Plan ----------------------------------------------------------------------


def _plan(
    page: dict[str, Any] | None,
    language: Language,
    box: tuple[float, float],
    legend: Sequence[dict[str, Any]] = (),
) -> str:
    title = f'<h2 class="r-plan__title">{_e(text("plan", language))}</h2>'
    note = f'<p class="r-plan__note">{_e(text("plan_note", language))}</p>'
    if page is None:
        return (
            f'<section class="r-plan">{title}{note}<p class="r-plan__empty">'
            + _e(text("no_plan", language))
            + "</p></section>"
        )
    drawing = f'<div class="r-plan__drawing">{plan_svg(page, box)}</div>'
    keys = plan_legend(page, legend, language)
    return f'<section class="r-plan">{title}{note}{drawing}{keys}</section>'


# Lighting lines on the plan: dash and gap in printed mm (scaled with the drawing on screen)
LIGHT_LAYER = "W-CABLE-LIGHT"
DASH_MM = (1.6, 1.0)
KEY_LINE_MM = (9.0, 0.35)  # legend line: length and width


def plan_legend(page: dict[str, Any], legend: Sequence[dict[str, Any]], language: Language) -> str:
    """Short legend under the plan, a grid of many rows and columns: solid and dashed lines,
    the junction box (from the plan itself) and the point symbols of the electrical sheet
    legend, all black and white."""
    keys = [
        (_key_line(dashed=False), text("legend_power", language)),
        (_key_line(dashed=True), text("legend_light", language)),
    ]
    box = _first_object(page.get("items", []), "W-BOX", "box:")
    if box:
        keys.append((_key_icon(box), text("legend_box", language)))
    keys += [(_key_icon(e["items"]), str(e["text"])) for e in legend if e.get("items")]
    cells = "".join(
        f'<div class="r-plan__key"><span class="r-plan__icon">{icon}</span>'
        f"<span>{_e(caption)}</span></div>"
        for icon, caption in keys
    )
    return f'<div class="r-plan__legend">{cells}</div>'


def _first_object(items: Sequence[dict[str, Any]], layer: str, kind: str) -> list[dict[str, Any]]:
    """Primitives of the first object of a kind on a layer (one junction box)."""
    first = next(
        (i.get("o") for i in items if i.get("l") == layer and str(i.get("o", "")).startswith(kind)),
        None,
    )
    return [i for i in items if first is not None and i.get("o") == first]


def _key_line(dashed: bool) -> str:
    length, width = KEY_LINE_MM
    dash = f' stroke-dasharray="{_n(DASH_MM[0])} {_n(DASH_MM[1])}"' if dashed else ""
    return (
        f'<svg viewBox="0 0 {_n(length)} 2" width="{_n(length)}mm" height="2mm">'
        f'<path d="M0 1H{_n(length)}" stroke="#000000" stroke-width="{_n(width)}"{dash}/></svg>'
    )


def _key_icon(items: Sequence[dict[str, Any]]) -> str:
    """Symbol primitives (sheet mm) as a small SVG at sheet size, black and white."""
    numbers = [float(n) for i in items for n in _NUMBER.findall(str(i["d"]))]
    xs, ys = numbers[0::2], numbers[1::2]
    pad = 0.4
    x0, y0 = min(xs) - pad, min(ys) - pad
    w, h = max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad
    paths = "".join(_path(i, 1.0) for i in items)
    return (
        f'<svg viewBox="{_n(x0)} {_n(y0)} {_n(w)} {_n(h)}" width="{_n(w)}mm" height="{_n(h)}mm"'
        f' stroke-linecap="round" stroke-linejoin="round">{paths}</svg>'
    )


PLAN_CSS = f"""
.r-plan {{ font: 9.5pt/1.45 {FONT}; color: #1d2330;
  break-after: page; }}
.r-plan__title {{ font-size: 11pt; font-weight: 600; margin: 5mm 0 0.5mm; }}
.r-plan__note {{ color: #555; font-size: 8.5pt; margin: 0; }}
.r-plan__empty {{ color: #999; font-style: italic; }}
.r-plan__drawing svg {{ display: block; width: 100%; height: auto; margin: 3mm 0 0; }}
.r-plan__legend {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(44mm, 1fr));
  gap: 1.5mm 5mm; margin-top: 4mm; padding-top: 3mm; border-top: 0.2mm solid #ddd;
  font-size: 8pt; line-height: 1.25; color: #333; }}
.r-plan__key {{ display: flex; align-items: center; gap: 2mm; break-inside: avoid; }}
.r-plan__icon {{ flex: 0 0 10mm; display: flex; justify-content: center; align-items: center;
  height: 7mm; }}
.r-plan__icon svg {{ max-width: 10mm; max-height: 7mm; overflow: visible; }}
@media print {{ .r-plan__drawing svg {{ max-height: var(--plan-max-h); }} }}
"""


def plan_svg(page: dict[str, Any], box: tuple[float, float] = PLAN_BOX_MM["portrait"]) -> str:
    """The page drawing area as black-and-white SVG, lying horizontally: a drawing taller than
    wide is turned a quarter counter-clockwise. On the page it is as wide as the text column
    (PLAN_CSS); in print no taller than box[1] mm, so it stays on the first sheet. The mm size in
    the attributes (fit to box) is for the SVG on its own and sets the thinnest printed line."""
    width, height = page["size"]
    x0, y0, x1, y1 = page.get("view") or (0.0, 0.0, width, height)
    w, h = x1 - x0, y1 - y0
    turned = h > w
    vw, vh = (h, w) if turned else (w, h)
    scale = min(box[0] / vw, box[1] / vh)
    move = f"translate(0 {_n(w)}) rotate(-90) " if turned else ""
    paths = [_path(item, scale) for item in page.get("items", [])]
    return "".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_n(vw)} {_n(vh)}"',
            f' width="{_n(vw * scale)}mm" height="{_n(vh * scale)}mm"',
            f' style="--plan-max-h: {_n(box[1])}mm">',
            # Clipped to the drawing area: a print page narrower than the column (height cap)
            # leaves room at the sides, where the rest of the sheet would show
            f'<defs><clipPath id="r-plan-clip"><rect width="{_n(vw)}" height="{_n(vh)}"/>',
            "</clipPath></defs>",
            f'<g clip-path="url(#r-plan-clip)"><rect width="{_n(vw)}" height="{_n(vh)}"',
            ' fill="#ffffff"/>',
            f'<g transform="{move}translate({_n(-x0)} {_n(-y0)})"',
            ' stroke-linecap="round" stroke-linejoin="round">',
            *paths,
            "</g></g></svg>",
        ]
    )


def _path(item: dict[str, Any], scale: float) -> str:
    """One primitive, black and white; a lighting line is dashed, its pieces joined so the dash
    runs on instead of starting again at every piece of an arc."""
    colour = mono(str(item["c"]))
    if item["k"] == "f":
        return f'<path d="{item["d"]}" fill="{colour}"/>'
    stroke = max(float(item.get("w", 0.0)), MIN_STROKE_MM / scale)
    d, dash = str(item["d"]), ""
    if item.get("l") == LIGHT_LAYER and str(item.get("o", "")).startswith("wire:"):
        d = joined(d)
        dash = f' stroke-dasharray="{_n(DASH_MM[0] / scale)} {_n(DASH_MM[1] / scale)}"'
    return f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{_n(stroke)}"{dash}/>'


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_COMMAND = re.compile(r"[MLQCZ]|-?\d+(?:\.\d+)?")


def joined(d: str) -> str:
    """Path without a move to the point where the pen already is: pieces drawn end to end
    (`M a L b M b L c`) become one line (`M a L b L c`)."""
    tokens = _COMMAND.findall(d)
    out: list[str] = []
    at: tuple[str, str] | None = None
    start: tuple[str, str] | None = None
    k = 0
    sizes = {"M": 2, "L": 2, "Q": 4, "C": 6, "Z": 0}
    while k < len(tokens):
        cmd = tokens[k]
        args = tokens[k + 1 : k + 1 + sizes[cmd]]
        k += 1 + sizes[cmd]
        if cmd == "M" and at == (args[0], args[1]):
            continue
        out.append(cmd + " ".join(args))
        if cmd == "M":
            start = (args[0], args[1])
        at = start if cmd == "Z" else (args[-2], args[-1])
    return "".join(out)


def mono(colour: str) -> str:
    """#rrggbb or #rrggbbaa → white for a light colour (label backings, light wall fills),
    black for the rest."""
    r, g, b = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
    light = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    return "#ffffff" if light > WHITE_ABOVE else "#000000"


def _n(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


# --- Single-line diagram ---------------------------------------------------------


def _panel(
    panel: dict[str, Any] | None,
    wiring: dict[str, Any] | None,
    language: Language,
    box: tuple[float, float],
) -> str:
    """The single-line diagram: tiers as wide as the page column (box[0]), each kept whole;
    cable lengths from the groups table of the wiring page; under it the abbreviations, the
    assumption mark and the warnings of the panel calculation (major ones first)."""
    title = f'<h2 class="r-panel__title">{_e(text("panel", language))}</h2>'
    note = f'<p class="r-panel__note">{_e(text("panel_note", language))}</p>'
    if not panel:
        drawing = f'<p class="r-panel__empty">{_e(text("no_panel", language))}</p>'
    else:
        grid = str((panel.get("texts") or {}).get("grid") or "")
        keys = ("group", "device", "cable", "power", "current", "purpose")
        headings = {k: text(f"col_{k}", language) for k in keys}
        lengths = group_lengths(wiring)
        tiers = single_line_svgs(panel, grid, headings, box[0], language, lengths)
        drawing = "".join(f'<div class="r-panel__tier">{svg}</div>' for svg in tiers)
        notes = [DEVICE_LEGEND[language]]
        if assumed_any(panel):
            notes.append(text("assumed_note", language))
        drawing += "".join(f'<p class="r-panel__legend">{_e(n)}</p>' for n in notes)
        drawing += _panel_warnings(panel, language)
    return f'<section class="r-panel">{title}{note}{drawing}</section>'


def group_lengths(wiring: dict[str, Any] | None) -> dict[str, str]:
    """Cable length per group, m, as the groups table of the wiring page writes it: the row's
    `group` and the cell of the column headed "…, м"; no wiring or no such table — empty."""
    out: dict[str, str] = {}
    for table in (wiring or {}).get("tables") or []:
        columns = [str(c) for c in table.get("columns") or []]
        index = next((i for i, c in enumerate(columns) if c.endswith(", м")), None)
        if index is None:
            continue
        for row in table.get("rows") or []:
            cells = row.get("cells") or []
            if row.get("group") and len(cells) > index and cells[index]:
                out[str(row["group"])] = str(cells[index])
    return out


def _panel_warnings(panel: dict[str, Any], language: Language) -> str:
    """Weak spots of the calculation under the diagram, major ones first, each with its group."""
    warnings = [w for w in panel.get("warnings") or [] if w.get("text")]
    if not warnings:
        return ""
    warnings.sort(key=lambda w: w.get("severity") != "major")
    items = "".join(
        f'<li class="r-panel__warning r-panel__warning--{_e(w.get("severity") or "minor")}">'
        f"{_e(w['text'])}</li>"
        for w in warnings
    )
    return (
        f'<h3 class="r-panel__subtitle">{_e(text("panel_warnings", language))}</h3>'
        f'<ul class="r-panel__warnings">{items}</ul>'
    )


# On screen the diagram is set off from the estimate above by a rule; in print it starts a page
PANEL_CSS = f"""
.r-panel {{ font: 9.5pt/1.45 {FONT}; color: #1d2330; break-before: page; }}
@media screen {{ .r-panel {{ margin-top: 16mm; padding-top: 6mm;
  border-top: 0.5mm solid #1d2330; }} }}
.r-panel__title {{ font-size: 13pt; font-weight: 600; margin: 0 0 1mm; }}
.r-panel__note {{ color: #555; font-size: 8.5pt; margin: 0; }}
.r-panel__empty {{ color: #999; font-style: italic; }}
.r-panel__tier {{ break-inside: avoid; margin-top: 6mm; }}
.r-panel__tier svg {{ display: block; max-width: 100%; height: auto; margin: 0 auto; }}
.r-panel__legend {{ color: #555; font-size: 8pt; margin: 3mm 0 0; }}
.r-panel__subtitle {{ font-size: 9.5pt; font-weight: 600; margin: 6mm 0 1mm; break-after: avoid; }}
.r-panel__warnings {{ margin: 0; padding-left: 5mm; font-size: 8.5pt; line-height: 1.5; }}
.r-panel__warning--major {{ color: #c62828; }}
.r-panel__warning--minor {{ color: #555; }}
"""


# --- Estimate ------------------------------------------------------------------


def _estimate(estimate: dict[str, Any] | None, parts: Sequence[Part], language: Language) -> str:
    """Each estimate section its own `r-lines` section, then the closing block."""
    if not estimate:
        return _missing(text("estimate", language), text("no_estimate", language))
    blocks = {b.section: b for b in estimate_blocks(estimate, language)}
    columns = [str(c) for c in estimate["columns"]]
    align = [str(a) for a in estimate["align"]]
    out: list[str] = []
    shown: list[_Block] = []
    for part in parts:
        found = [blocks[s] for s in ESTIMATE_PARTS[part] if s in blocks]
        if not found:
            title = section_title(ESTIMATE_PARTS[part][0], language)
            out.append(_missing(title, text("no_section", language)))
        for block in found:
            if block not in shown:  # an estimate not split: one materials section for both
                out.append(_block(block, columns, align, language))
                shown.append(block)
    out.append(_summary(shown, columns, language))
    out.append(_appendix(shown, language))
    return "".join(out)


def _missing(title: str, message: str) -> str:
    return "".join(
        [
            f'<section class="r-lines"><h2 class="r-lines__title">{_e(title)}</h2>',
            f'<p class="r-lines__empty">{_e(message)}</p></section>',
        ]
    )


def estimate_blocks(estimate: dict[str, Any], language: Language) -> list[_Block]:
    """Sections of the estimate table (side.estimate_side_table) by their heading; builds before
    2026-11-23 wrote a note after a dash into the heading ("… — цены пока имитация"). A heading
    that is not a known section is skipped. A materials section is approximate when its total is
    provisional (`guess`) or, in those older builds, its heading carried that note."""
    titles = {section_title(s, language): s for s in SECTIONS}
    blocks: list[_Block] = []
    section: Section | None = None
    title = ""
    noted = False
    rows: list[dict[str, Any]] = []

    def close(subtotal: dict[str, Any] | None) -> None:
        if section is not None:
            rough = noted or bool(subtotal and subtotal.get("guess"))
            approximate = rough and section in MATERIAL_SECTIONS
            blocks.append(_Block(section, title, tuple(rows), subtotal, approximate))

    for row in estimate["rows"]:
        cells = [str(c) for c in row["cells"]]
        if row.get("section"):
            close(None)
            title, dash, _ = cells[1].partition(" — ")
            section, rows, noted = titles.get(title), [], bool(dash)
        elif _is_subtotal(cells):
            close(row)
            section, rows = None, []
        else:
            rows.append(row)
    close(None)
    return blocks


def _is_subtotal(cells: Sequence[str]) -> bool:
    """A section total, as the viewer reads it (web/src/shared/estimate.ts, rowKind): no number,
    a caption and the sum in the last cell."""
    return not cells[0] and sum(1 for c in cells if c) == 2 and bool(cells[-1])


def _block(block: _Block, columns: list[str], align: list[str], language: Language) -> str:
    cls = ["r-lines__num" if a != "left" else "" for a in align]
    approx = text("approximate", language)
    tag = f' <span class="r-lines__tag">{_e(approx)}</span>' if block.approximate else ""
    head = "".join(f'<th class="{c}">{_e(t)}</th>' for c, t in zip(cls, columns, strict=True))
    # One row group per item (a row does not break across pages); the work scope is in the
    # appendix, the work table points to it under its heading
    body = [
        f'<tbody class="r-lines__item">{_tr([str(c) for c in row["cells"]], cls)}</tbody>'
        for row in block.rows
    ]
    ref = ""
    if _scoped(block):
        ref = f'<p class="r-lines__ref">{_e(text("appendix_ref", language))}</p>'  # fmt: skip
    if block.subtotal is not None:
        cells = [str(c) for c in block.subtotal["cells"]]
        if block.approximate:
            cells[-1] = f"≈ {cells[-1]}"
        body.append(f'<tbody class="r-lines__subtotal">{_tr(cells, cls)}</tbody>')
    return "".join(
        [
            f'<section class="r-lines"><h2 class="r-lines__title">{_e(block.title)}{tag}</h2>',
            ref,
            f'<table class="r-lines__table"><thead><tr>{head}</tr></thead>',
            f"{''.join(body)}</table></section>",
        ]
    )


def _tr(cells: Sequence[str], cls: Sequence[str]) -> str:
    tds = "".join(f'<td class="{c}">{_e(t)}</td>' for c, t in zip(cls, cells, strict=True))
    return f"<tr>{tds}</tr>"


def _scoped(block: _Block) -> bool:
    """A work section with a scope on any of its items."""
    return block.section in WORK_SECTIONS and any(r.get("scope") for r in block.rows)


def _appendix(blocks: Sequence[_Block], language: Language) -> str:
    """What each work includes and its result, by work section, numbers as in the tables; on a
    page of its own after the closing block. None of the shown sections has a scope: nothing."""
    groups = [b for b in blocks if _scoped(b)]
    if not groups:
        return ""
    out = [
        '<section class="r-appendix">',
        f'<h2 class="r-appendix__title">{_e(text("appendix", language))}</h2>',
        f'<p class="r-appendix__lead">{_e(text("appendix_lead", language))}</p>',
    ]
    for block in groups:
        out.append(f'<h3 class="r-appendix__group">{_e(block.title)}</h3>')
        for row in block.rows:
            scope = row.get("scope")
            if not scope:
                continue
            no, name = str(row["cells"][0]), str(row["cells"][1])
            includes = "; ".join(str(i) for i in scope.get("includes") or [])
            result = str(scope.get("result") or "")
            out.append('<div class="r-appendix__item">')
            number = f'<span class="r-appendix__no">{_e(no)}</span>'
            out.append(f'<div class="r-appendix__name">{number}{_e(name)}</div>')
            if includes:
                out.append(f"<p><b>{_e(text('includes', language))}:</b> {_e(includes)}.</p>")
            if result:
                out.append(f"<p><b>{_e(text('result', language))}:</b> {_e(result)}</p>")
            out.append("</div>")
    out.append("</section>")
    return "".join(out)


APPENDIX_CSS = f"""
.r-appendix {{ font: 9.5pt/1.45 {FONT}; color: #1d2330; break-before: page; }}
.r-appendix__title {{ font-size: 12pt; font-weight: 600; margin: 5mm 0 1mm; }}
.r-appendix__lead {{ color: #555; font-size: 8.5pt; margin: 0 0 4mm; }}
.r-appendix__group {{ font-size: 10.5pt; font-weight: 600; margin: 6mm 0 1mm;
  padding-bottom: 1.5mm; border-bottom: 0.5mm solid #ddd; break-after: avoid; }}
.r-appendix__item {{ padding: 2.5mm 0; border-bottom: 0.2mm solid #eee; break-inside: avoid; }}
.r-appendix__name {{ font-weight: 600; }}
.r-appendix__no {{ display: inline-block; min-width: 7mm; color: #777; font-weight: 400; }}
.r-appendix__item p {{ margin: 0.8mm 0 0 7mm; color: #444; font-size: 8.5pt; }}
.r-appendix__item b {{ font-weight: 600; color: #1d2330; }}
"""


LINES_CSS = f"""
.r-lines {{ font: 9.5pt/1.45 {FONT}; color: #1d2330; }}
.r-lines__title {{ font-size: 11pt; font-weight: 600; margin: 10mm 0 1mm; break-after: avoid; }}
.r-lines__tag {{ font-size: 8pt; font-weight: 400; color: #8a5a00; background: #fff4d6;
  padding: 0.3mm 1.6mm; margin-left: 2mm; vertical-align: 1px; white-space: nowrap; }}
.r-lines__empty {{ color: #999; font-style: italic; }}
.r-lines__table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
.r-lines__table thead {{ display: table-header-group; }}
.r-lines__table th {{ text-align: left; color: #666; font-weight: 600; font-size: 7.5pt;
  letter-spacing: 0.04em; text-transform: uppercase; border-bottom: 0.5mm solid #ddd;
  padding: 3mm 1.5mm 2.5mm; }}
.r-lines__table th:nth-child(1) {{ width: 9mm; }}
.r-lines__table th:nth-child(3) {{ width: 14mm; }}
.r-lines__table th:nth-child(4) {{ width: 18mm; }}
.r-lines__table th:nth-child(5) {{ width: 22mm; }}
.r-lines__table th:nth-child(6) {{ width: 26mm; }}
.r-lines__table td {{ text-align: left; vertical-align: top; padding: 2.2mm 1.5mm;
  border-bottom: 0.2mm solid #eee; }}
.r-lines__table th:first-child, .r-lines__table td:first-child {{ padding-left: 0; }}
.r-lines__table th:last-child, .r-lines__table td:last-child {{ padding-right: 0; }}
.r-lines__table .r-lines__num {{ text-align: right; white-space: nowrap; }}
.r-lines__table th:first-child, .r-lines__table td:first-child {{ text-align: left; }}
.r-lines__item {{ break-inside: avoid; }}
.r-lines__item:first-of-type td {{ padding-top: 3.5mm; }}
.r-lines__item td:first-child {{ color: #777; }}
.r-lines__item td:last-child {{ font-weight: 600; }}
.r-lines__ref {{ color: #555; font-size: 8.5pt; margin: 0; }}
.r-lines__subtotal td {{ font-weight: 600; border-top: 0.5mm solid #ddd; border-bottom: none;
  padding-top: 3mm; }}
"""


def _summary(blocks: Sequence[_Block], columns: list[str], language: Language) -> str:
    """Closing block: section totals on the left, their sum large on the right, and what "!"
    means; only when every shown section has a priced total (a bill of quantities has none)."""
    totals = [b.subtotal for b in blocks]
    if not blocks or any(t is None for t in totals):
        return ""
    cells = [
        (b.title, str(t["cells"][-1]), b.approximate)
        for b, t in zip(blocks, totals, strict=True)
        if t
    ]
    sums = [parse_number(value) for _, value, _ in cells]
    if any(v is None for v in sums):
        return ""
    rows = "".join(
        f'<div class="r-closing__part"><span>{_e(title)}</span>'
        f'<span class="r-closing__sum">{"≈ " if guess else ""}{_e(value)}</span></div>'
        for title, value, guess in cells
    )
    total = format_number(sum(v for v in sums if v is not None))
    heading = f"{estimate_text('total', language)}, {columns[-1].rpartition(', ')[2]}"
    guess = any(g for _, _, g in cells)
    note = f'<p class="r-closing__note">{_e(text("guess", language))}</p>' if guess else ""
    return "".join(
        [
            '<section class="r-closing"><div class="r-closing__head">',
            f"<span>{_e(text('summary', language))}</span><span>{_e(heading)}</span></div>",
            f'<div class="r-closing__body"><div class="r-closing__parts">{rows}</div>',
            f'<div class="r-closing__grand">{_e(total)}</div></div>',
            f"{note}</section>",
        ]
    )


# Closing block colour after the template's total
CLOSING_CSS = f"""
.r-closing {{ font: 9pt/1.7 {FONT}; color: #1d2330;
  margin-top: 14mm; break-inside: avoid; }}
.r-closing__head {{ display: flex; justify-content: space-between; color: #666; font-weight: 600;
  font-size: 7.5pt; letter-spacing: 0.04em; text-transform: uppercase;
  border-bottom: 0.5mm solid #ddd; padding: 3mm 0 2.5mm; }}
.r-closing__body {{ display: flex; align-items: center; justify-content: space-between;
  gap: 10mm; border-bottom: 0.5mm solid #ddd; padding: 4mm 0 5mm; }}
.r-closing__parts {{ flex: 0 0 60%; }}
.r-closing__part {{ display: flex; justify-content: space-between; gap: 6mm; }}
.r-closing__sum {{ white-space: nowrap; }}
.r-closing__grand {{ font-size: 20pt; font-weight: 600; color: #fb7578; white-space: nowrap; }}
.r-closing__note {{ color: #555; font-size: 8.5pt; margin: 2mm 0 0; }}
"""
