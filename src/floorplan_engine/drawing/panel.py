"""The "Panel" sheet: the panel front view with DIN rails, devices, group wires going down to their
breakers, a device table with loads, and weak spots. Drawn directly on the sheet (sheet mm),
with no viewport: the panel is a diagram, not a scaled plan.

A rail row from top to bottom: a strip of designations (QF4) and the busbar, the device, a
strip of wires: each group's wire goes down from its breaker in the colour of its lines, with
vertical labels next to it: purpose, cable and power. All sizes are fractions of a DIN module
(`m`, sheet mm), so the panel fits its space.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ezdxf.colors import RGB
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.base import BaseLayout

from floorplan_engine.drawing.ids import tagged
from floorplan_engine.drawing.layers import E_PANEL, E_PANEL_WIRE, MIN_TEXT_MM, text_width
from floorplan_engine.drawing.plan import add_text
from floorplan_engine.drawing.tables import Column, Mark, Table, name_width
from floorplan_engine.electrical.led_supply import LedLine
from floorplan_engine.electrical.loads import PanelGroup, current
from floorplan_engine.electrical.panel import (
    BoardPanel,
    Device,
    color_of,
    device_name,
    din_rows,
    panel_title,
)
from floorplan_engine.electrical.panel_text import DEVICE_LEGEND, amps, kw
from floorplan_engine.electrical.panel_text import text as panel_text
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.panel_catalog import DeviceKind
from floorplan_engine.model.texts import Language

# Heights in modules
HEAD = 1.2  # designation strip and busbar
BODY = 5.0  # device
GUTTER = 6.5  # wires and labels under the rail
PAD = 1.2  # from the enclosure wall to the rail
LEAD = 2.0  # supply above the panel
ROW = HEAD + BODY + GUTTER
SIDE = 7.0  # external device (inverter, plug) right of the panel, with a gap
M_MAX = 9.0  # module on the sheet, mm: larger makes the panel too big
TEXT_MAX = 2.0
GUTTER_TEXT = 0.28  # labels under the rail, fraction of a module; the smallest on the sheet
M_MIN = MIN_TEXT_MM / GUTTER_TEXT  # smaller makes labels smaller than MIN_TEXT_MM
DARK = 0x3A3A3A
GREY = 0x8C8C8C
BUS = 0x5A5A5A
INPUT_WIRE = 0x8B4513  # brown: supply phase
RESERVE = 0x2E8B57
MASTER = 0xC77700  # busbar behind the master switch contactor
LW_BOX = 50
LW_DEV = 25
LW_WIRE = 35
LW_THIN = 13
LEFT = TextEntityAlignment.MIDDLE_LEFT
CENTER = TextEntityAlignment.MIDDLE_CENTER

TEXT: dict[str, dict[str, str]] = {
    "grid": {"ru": "Ввод {v} В", "uk": "Введення {v} В"},
    "reserve": {"ru": "резервная шина", "uk": "резервна шина"},
    "master": {"ru": "мастер-выключатель", "uk": "майстер-вимикач"},
    "pe": {"ru": "PE", "uk": "PE"},
    "table": {"ru": "Аппараты щита", "uk": "Апарати щита"},
    "id": {"ru": "Поз.", "uk": "Поз."},
    "purpose": {"ru": "Назначение", "uk": "Призначення"},
    "device": {"ru": "Аппарат", "uk": "Апарат"},
    "cable": {"ru": "Кабель", "uk": "Кабель"},
    "p": {"ru": "P, кВт", "uk": "P, кВт"},
    "i": {"ru": "I, А", "uk": "I, А"},
    "installed": {"ru": "Установленная", "uk": "Встановлена"},
    "calc": {
        "ru": "Расчётная: Кс {k} → {p} кВт, {i} А; ввод {inp}",
        "uk": "Розрахункова: Кп {k} → {p} кВт, {i} А; введення {inp}",
    },
    "assumed": {
        "ru": "* — допущение: мощность типовая по виду точки, автомат подобран по группе, "
        "кабель — по виду точек; уточните (power у точки, groups и cables в electrical.yaml)",
        "uk": "* — припущення: потужність типова за видом точки, автомат підібрано за групою, "
        "кабель — за видом точок; уточніть (power у точки, groups і cables в electrical.yaml)",
    },
    "weak": {"ru": "Слабые места:", "uk": "Слабкі місця:"},
    "none": {"ru": "Слабых мест не найдено", "uk": "Слабких місць не знайдено"},
}
ASSUMED = "*"


def text(key: str, language: Language, **kw_: object) -> str:
    return TEXT[key][language].format(**kw_)


@dataclass(frozen=True)
class PanelDrawing:
    """Panel fitted to its space: module m and rails."""

    m: float
    rows: tuple[tuple[Device, ...], ...]
    per_row: int
    external: bool  # inverter or plug right of the panel

    @property
    def box_w(self) -> float:
        return (self.per_row + 2 * PAD) * self.m

    @property
    def width(self) -> float:
        return self.box_w + (SIDE * self.m if self.external else 0.0)

    @property
    def height(self) -> float:
        return (LEAD + 2 * PAD + len(self.rows) * ROW) * self.m


def fit_panel(panel: BoardPanel, width: float, height: float) -> PanelDrawing | None:
    """Panel at the largest module that fits; None if it does not fit even with M_MIN. With an
    enclosure chosen (choose_enclosure) the sheet shows its rails as they are: its rail width and
    the devices by its rails (panel.rows), as the viewer and the estimate do. Without one the
    rail width (12, 18 or 24 modules) is the one that gives the largest module."""
    external = panel.backup is not None
    if panel.enclosure is not None and panel.rows:
        options = [(panel.enclosure.per_row, [list(r) for r in panel.rows])]
    else:
        options = [(n, din_rows(panel.devices, n)) for n in (12, 18, 24)]
    best: PanelDrawing | None = None
    for per_row, rows in options:
        a = per_row + 2 * PAD + (SIDE if external else 0.0)
        b = LEAD + 2 * PAD + len(rows) * ROW
        m = min(M_MAX, width / a, height / b)
        if m >= M_MIN and (best is None or m > best.m):
            best = PanelDrawing(m, tuple(tuple(r) for r in rows), per_row, external)
    return best


def _rect(
    layout: BaseLayout, x0: float, y0: float, x1: float, y1: float, **attribs: object
) -> None:
    points = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    layout.add_lwpolyline(points, close=True, dxfattribs={"layer": E_PANEL.name, **attribs})


def _fill(layout: BaseLayout, x0: float, y0: float, x1: float, y1: float, color: int) -> None:
    hatch = layout.add_hatch(dxfattribs={"layer": E_PANEL.name})
    hatch.set_solid_fill(rgb=RGB.from_hex(f"#{color:06x}"))
    hatch.paths.add_polyline_path([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], is_closed=True)


def _line(
    layout: BaseLayout, pts: Sequence[Vec], color: int, lw: int, layer: str = E_PANEL.name
) -> None:
    layout.add_lwpolyline(
        [(p.x, p.y) for p in pts],
        dxfattribs={"layer": layer, "true_color": color, "lineweight": lw},
    )


def _text(
    layout: BaseLayout,
    s: str,
    at: Vec,
    h: float,
    color: int = DARK,
    angle: float = 0.0,
    align: TextEntityAlignment = CENTER,
) -> None:
    add_text(layout, s, at, h, E_PANEL.name, angle, align, color=color, scale=1.0)


def clip(s: str, width: float, h: float) -> str:
    """String cut with "…" to fit width, sheet mm."""
    if text_width(s, h) <= width:
        return s
    while s and text_width(s + "…", h) > width:
        s = s[:-1]
    return s.rstrip() + "…"


def draw_device(layout: BaseLayout, d: Device, x: float, top: float, m: float, color: int) -> None:
    """Device from the top-left corner of its body: body, levers, rating text."""
    w, h = d.modules * m, BODY * m
    x1, bottom = x + w, top - h
    _fill(layout, x, bottom, x1, top, 0xFFFFFF)
    _rect(layout, x, bottom, x1, top, lineweight=LW_DEV, true_color=DARK)
    # Group colour stripe, same as its lines on the electrical and wiring sheets
    if d.group is not None:
        _fill(layout, x + 0.1 * m, top - 0.45 * m, x1 - 0.1 * m, top - 0.15 * m, color)
    th = min(TEXT_MAX, 0.32 * m)
    mid = top - h * 0.45
    if d.kind in (
        DeviceKind.BREAKER,
        DeviceKind.DIFF,
        DeviceKind.INPUT,
        DeviceKind.RCD,
        DeviceKind.FEED,
        DeviceKind.OUTPUT,
    ):
        poles = 1 if d.kind is DeviceKind.DIFF else d.modules
        for k in range(poles):
            cx = x + (k + 0.5) * m
            _fill(layout, cx - 0.22 * m, mid - 0.6 * m, cx + 0.22 * m, mid + 0.6 * m, DARK)
        if d.kind in (DeviceKind.DIFF, DeviceKind.RCD):  # "Test" button
            cx = x1 - 0.5 * m
            layout.add_circle((cx, mid), 0.22 * m, dxfattribs={"layer": E_PANEL.name})
            _text(layout, "T", Vec(cx, mid - 0.55 * m), th)
    elif d.kind is DeviceKind.RELAY:
        _fill(layout, x + 0.3 * m, mid - 0.4 * m, x1 - 0.3 * m, mid + 0.6 * m, 0x1F3D2B)
        _text(layout, "230V", Vec((x + x1) / 2, mid + 0.1 * m), th, color=0x7CFC9A)
    elif d.kind is DeviceKind.SPD:
        _rect(layout, x + 0.25 * m, mid - 0.7 * m, x1 - 0.25 * m, mid + 0.7 * m, true_color=GREY)
        _text(layout, "SPD", Vec((x + x1) / 2, mid), th)
    elif d.kind is DeviceKind.CHANGEOVER:
        cx = (x + x1) / 2
        layout.add_circle(
            (cx, mid), 0.9 * m, dxfattribs={"layer": E_PANEL.name, "lineweight": LW_DEV}
        )
        _line(layout, [Vec(cx, mid), Vec(cx, mid + 0.8 * m)], DARK, LW_WIRE)
        _text(layout, "I    0    II", Vec(cx, mid + 1.35 * m), th)
    elif d.kind is DeviceKind.CONTACTOR:  # coil A1–A2 and the contacts
        _rect(layout, x + 0.3 * m, mid - 0.6 * m, x1 - 0.3 * m, mid + 0.6 * m, true_color=GREY)
        _text(layout, "KM", Vec((x + x1) / 2, mid), th)
    else:  # ATS
        _rect(layout, x + 0.3 * m, mid - 0.6 * m, x1 - 0.3 * m, mid + 0.6 * m, true_color=GREY)
        _text(layout, "ATS", Vec((x + x1) / 2, mid), th)
    lines = d.label.split(" ", 1) if d.modules > 1 or len(d.label) > 4 else [d.label]
    for k, line in enumerate(lines):
        at = Vec((x + x1) / 2, bottom + (len(lines) - k) * th * 1.3)
        _text(layout, clip(line, w - 0.2 * m, th), at, th)
    if d.assumed:
        _text(layout, ASSUMED, Vec(x1 - 0.2 * m, top - 0.75 * m), th)


def _gutter_labels(
    layout: BaseLayout, g: PanelGroup, x: float, top: float, m: float, color: int
) -> None:
    """Group wire down from the breaker with vertical labels on both sides."""
    bottom = top - (GUTTER - 0.4) * m
    _line(layout, [Vec(x, top), Vec(x, bottom)], color, LW_WIRE, E_PANEL_WIRE.name)
    layout.add_circle(
        (x, bottom), 0.15 * m, dxfattribs={"layer": E_PANEL_WIRE.name, "true_color": color}
    )
    th = min(TEXT_MAX * 0.9, GUTTER_TEXT * m)
    room = (GUTTER - 1.0) * m
    star = ASSUMED if g.assumed else ""
    left = clip(g.purpose, room, th)
    cable = g.cable + (ASSUMED if g.cable_assumed else "")
    right = clip(f"{cable} · {kw(g.power)} кВт{star}", room, th)
    _text(layout, left, Vec(x - 0.28 * m, bottom + 0.3 * m), th, angle=90, align=LEFT)
    _text(layout, right, Vec(x + 0.28 * m, bottom + 0.3 * m), th, color=color, angle=90, align=LEFT)


def draw_panel_front(
    layout: BaseLayout,
    panel: BoardPanel,
    fit: PanelDrawing,
    top_left: Vec,
    colors: dict[str, int],
    name: str,
    language: Language,
) -> None:
    """Panel front view from the top-left corner of its space on the sheet."""
    m = fit.m
    groups = {g.group: g for g in panel.groups}
    x0 = top_left.x
    box_top = top_left.y - LEAD * m
    box_bottom = top_left.y - fit.height
    x1 = x0 + fit.box_w
    th = min(TEXT_MAX, 0.35 * m)
    title = panel_title(panel, name, language)
    _text(layout, title, Vec(x0, top_left.y + 0.9 * m), th * 1.2, align=LEFT)
    with tagged(layout, "board", "board"):
        _rect(layout, x0, box_bottom, x1, box_top, lineweight=LW_BOX, true_color=DARK)
        _rect(
            layout,
            x0 + 0.4 * m,
            box_bottom + 0.4 * m,
            x1 - 0.4 * m,
            box_top - 0.4 * m,
            lineweight=LW_THIN,
            true_color=GREY,
        )
    places: dict[str, tuple[float, float]] = {}  # device id → (centre x, top)
    for r, row in enumerate(fit.rows):
        top = box_top - (PAD + r * ROW) * m
        dev_top = top - HEAD * m
        rail_y = dev_top - BODY * m / 2
        # DIN rail behind the devices
        _fill(
            layout,
            x0 + PAD * m * 0.6,
            rail_y - 0.35 * m,
            x1 - PAD * m * 0.6,
            rail_y + 0.35 * m,
            0xC8C8C8,
        )
        x = x0 + PAD * m
        segments: list[tuple[float, float, bool, bool]] = []
        for d in row:
            w = d.modules * m
            with tagged(layout, "device", d.key.partition(":")[2]):
                color = color_of(d.group, colors) or DARK
                draw_device(layout, d, x, dev_top, m, color)
                _text(layout, d.id, Vec(x + w / 2, top - 0.4 * m), th)
                g = groups.get(d.group or "")
                if g is not None:
                    _gutter_labels(layout, g, x + w / 2, dev_top - BODY * m, m, color)
                elif d.kind is DeviceKind.SPD:
                    pe = dev_top - BODY * m - 1.2 * m
                    _line(
                        layout,
                        [Vec(x + w / 2, dev_top - BODY * m), Vec(x + w / 2, pe)],
                        0x2E8B2E,
                        LW_WIRE,
                    )
                    _text(layout, text("pe", language), Vec(x + w / 2, pe - 0.5 * m), th)
            places[d.id] = (x + w / 2, dev_top)
            # A contactor itself hangs on its bus; the groups behind it on a busbar of their own
            segments.append((x, x + w, d.reserve, d.master and d.kind is not DeviceKind.CONTACTOR))
            x += w
        # Busbar above the devices: main and backup as separate pieces, each split again by the
        # master switch contactor
        bus_y = dev_top + 0.25 * m
        for reserve, master in ((False, False), (False, True), (True, False), (True, True)):
            xs = [(a, b) for a, b, rv, ms in segments if rv is reserve and ms is master]
            if not xs:
                continue
            a, b = xs[0][0] + 0.3 * m, xs[-1][1] - 0.3 * m
            color = MASTER if master else RESERVE if reserve else BUS
            _line(layout, [Vec(a, bus_y), Vec(b, bus_y)], color, LW_DEV)
            if not (reserve or master):
                continue
            y0 = dev_top - BODY * m - 0.3 * m
            pad = 0.25 * m if master and reserve else 0.5 * m  # inside the backup frame
            layout.add_lwpolyline(
                [
                    (a - pad, y0),
                    (b + pad, y0),
                    (b + pad, top + 0.1 * m),
                    (a - pad, top + 0.1 * m),
                ],
                close=True,
                dxfattribs={"layer": E_PANEL.name, "true_color": color},
            )
            label = text("master" if master else "reserve", language)
            align = TextEntityAlignment.MIDDLE_LEFT if master else TextEntityAlignment.MIDDLE_RIGHT
            _text(
                layout,
                label,
                Vec(a if master else b, y0 - 0.5 * m),
                th * 0.9,
                color=color,
                align=align,
            )
    # Supply from above into the main breaker
    if "QS1" in places:
        cx, top = places["QS1"]
        with tagged(layout, "device", "QS1"):
            _line(
                layout, [Vec(cx, top_left.y), Vec(cx, top)], INPUT_WIRE, LW_WIRE, E_PANEL_WIRE.name
            )
            _text(
                layout,
                text("grid", language, v=400 if panel.phases == 3 else 230),
                Vec(cx + 0.5 * m, top_left.y - 0.6 * m),
                th,
                align=LEFT,
            )
    if fit.external:
        _draw_external(layout, panel, places, x1, box_top, m, th, language)


def _draw_external(
    layout: BaseLayout,
    panel: BoardPanel,
    places: dict[str, tuple[float, float]],
    box_right: float,
    box_top: float,
    m: float,
    th: float,
    language: Language,
) -> None:
    """Inverter or power plug right of the panel, and the wire to the backup switch."""
    key = panel.backup or "plug"
    ext_id = "U1" if key == "inverter" else "XP1"
    bx0, bx1 = box_right + 1.5 * m, box_right + (SIDE - 0.3) * m
    by1 = box_top - PAD * m
    by0 = by1 - 4.0 * m
    with tagged(layout, "device", ext_id):
        _fill(layout, bx0, by0, bx1, by1, 0xF4F4F4)
        _rect(layout, bx0, by0, bx1, by1, lineweight=LW_DEV, true_color=DARK)
        _text(layout, ext_id, Vec((bx0 + bx1) / 2, by1 - 0.8 * m), th)
        name = panel_text(key, language)
        words = name.split(" ")
        half = (len(words) + 1) // 2
        for k, line in enumerate((" ".join(words[:half]), " ".join(words[half:]))):
            at = Vec((bx0 + bx1) / 2, by1 - (2.0 + k * 0.9) * m)
            _text(layout, clip(line, bx1 - bx0 - 0.3 * m, th * 0.9), at, th * 0.9)
        target = places.get("KM1") or places.get("SA1")
        if target is not None:
            cx, top = target
            y = box_top - 0.2 * m
            _line(
                layout,
                [
                    Vec(bx0, by1 - 3.2 * m),
                    Vec(bx0 - 0.7 * m, by1 - 3.2 * m),
                    Vec(bx0 - 0.7 * m, y),
                    Vec(cx, y),
                    Vec(cx, top),
                ],
                RESERVE,
                LW_WIRE,
                E_PANEL_WIRE.name,
            )
        feed = places.get("QS2")
        if feed is not None:
            cx, top = feed
            y = box_top - 0.6 * m
            _line(
                layout,
                [
                    Vec(cx, top),
                    Vec(cx, y),
                    Vec(bx0 - 1.0 * m, y),
                    Vec(bx0 - 1.0 * m, by1 - 1.0 * m),
                    Vec(bx0, by1 - 1.0 * m),
                ],
                INPUT_WIRE,
                LW_WIRE,
                E_PANEL_WIRE.name,
            )


# --- Device table and notes ---------------------------------------------------


def device_rows(
    panel: BoardPanel, language: Language, led_lines: Mapping[str, LedLine] | None = None
) -> list[tuple[Device, tuple[str, ...]]]:
    """Table rows: device → (pos., purpose, device, cable, P, I). An LED supply: its output and
    strip, the 12 V line (led_lines, from the wiring; without it no cable), the strip current."""
    groups = {g.group: g for g in panel.groups}
    out: list[tuple[Device, tuple[str, ...]]] = []
    dc = panel.dc
    leds = {ld.point: ld for ld in panel.led.loads} if panel.led is not None else {}
    for d in panel.all_devices:
        g = groups.get(d.group or "")
        star = ASSUMED if d.assumed else ""
        if g is not None:
            purpose = g.purpose + (ASSUMED if g.purpose_assumed else "")
            p = kw(g.power) + (ASSUMED if g.assumed else "")
            name = device_name(d, language, short=True) + star  # "АВ 3P C16", legend under it
            cable = g.cable + (ASSUMED if g.cable_assumed else "")
            out.append((d, (d.id, purpose, name, cable, p, amps(g.current))))
        elif dc is not None and d.kind is DeviceKind.DC_BATTERY:  # battery cable and current
            v = f"{dc.voltage} В" + (ASSUMED if dc.voltage_assumed else "")
            cable = f"2×{dc.cable:g} мм²"
            out.append((d, (d.id, f"{d.title}, {v}", d.label + star, cable, "", amps(dc.current))))
        elif d.point is not None and d.point in leds:
            ld = leds[d.point]
            m = f"{ld.metres:g}".replace(".", ",") + (ASSUMED if ld.metres_assumed else "")
            purpose = f"{d.title}, {panel_text('led_strip_m', language, m=m)}"
            line = (led_lines or {}).get(d.point)
            cable = line.mark.replace("x", "×") if line is not None else ""
            name = device_name(d, language, short=True) + star
            p = kw(ld.power) + (ASSUMED if ld.power_assumed else "")
            out.append((d, (d.id, purpose, name, cable, p, amps(ld.current))))
        else:
            out.append((d, (d.id, d.title, d.label + star, "", "", "")))
    return out


PURPOSE_MAX = 80.0  # sheet mm: a long purpose is cut


def devices_table(
    panel: BoardPanel,
    language: Language,
    colors: dict[str, int],
    led_lines: Mapping[str, LedLine] | None = None,
) -> Table:
    rows = device_rows(panel, language, led_lines)
    purposes = [clip(r[1], PURPOSE_MAX, 2.5) for _, r in rows]
    devices = [r[2] for _, r in rows]
    columns = (
        Column(text("id", language), 16.0),
        Column(text("purpose", language), min(name_width(purposes), PURPOSE_MAX + 6), "left"),
        Column(text("device", language), name_width(devices), "left"),
        Column(text("cable", language), 16.0),
        Column(text("p", language), 15.0),
        Column(text("i", language), 12.0),
    )
    cells = []
    for (d, r), purpose in zip(rows, purposes, strict=True):
        color = color_of(d.group, colors)
        first: str | Mark = Mark(r[0], color) if color is not None else r[0]
        cells.append((first, purpose, *r[2:]))
    total = (
        "",
        text("installed", language),
        "",
        "",
        kw(panel.installed),
        amps(current(panel.installed)),
    )
    return Table(text("table", language), columns, tuple(cells), total, row_h=6.0, header_h=8.0)


def panel_notes(panel: BoardPanel, language: Language) -> list[str]:
    """Design load, assumptions and weak spots: rows under the table."""
    inp = panel.input.label + (ASSUMED if panel.input.assumed else "")
    calc = panel.calculated
    lines = [
        text(
            "calc",
            language,
            k=f"{panel.demand:g}".replace(".", ","),
            p=kw(calc),
            i=amps(current(calc)),
            inp=inp,
        ),
        DEVICE_LEGEND[language],
        text("assumed", language),
    ]
    if panel.warnings:
        lines.append(text("weak", language))
        lines += [f"! {w.text[language]}" for w in panel.warnings]
    else:
        lines.append(text("none", language))
    return lines
