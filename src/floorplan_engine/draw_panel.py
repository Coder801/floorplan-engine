"""Лист «Щит»: щит в лицо — DIN-рейки, аппараты, провода групп снизу к своим автоматам,
таблица аппаратов с нагрузкой и слабые места. Рисуется прямо на листе (мм листа), без
видового экрана: щит — схема, а не план в масштабе.

Ряд рейки сверху вниз: полоса обозначений (QF4) и шина, аппарат, полоса проводов — провод
группы цветом её линий идёт вниз от автомата, рядом вертикальные подписи: назначение, кабель
и мощность. Все размеры — в долях модуля DIN (`m`, мм листа): щит подгоняется под место.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ezdxf.colors import RGB
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.base import BaseLayout

from floorplan_engine.draw_plan import add_text
from floorplan_engine.geometry import Vec
from floorplan_engine.ids import tagged
from floorplan_engine.layers import E_PANEL, E_PANEL_WIRE, MIN_TEXT_MM, text_width
from floorplan_engine.panel import (
    BoardPanel,
    Device,
    PanelGroup,
    amps,
    color_of,
    current,
    din_rows,
    kw,
    scheme_title,
)
from floorplan_engine.panel import text as panel_text
from floorplan_engine.panel_catalog import DeviceKind
from floorplan_engine.tables import Column, Mark, Table, name_width
from floorplan_engine.texts import Language

# Высоты в модулях
HEAD = 1.2  # полоса обозначений и шина
BODY = 5.0  # аппарат
GUTTER = 6.5  # провода и подписи под рейкой
PAD = 1.2  # от стенки щита до рейки
LEAD = 2.0  # ввод над щитом
ROW = HEAD + BODY + GUTTER
SIDE = 7.0  # внешний аппарат (инвертор, вилка) справа от щита, с зазором
M_MAX = 9.0  # модуль на листе, мм: больше — щит слишком крупный
TEXT_MAX = 2.0
GUTTER_TEXT = 0.28  # подписи под рейкой — доля модуля, самые мелкие на листе
M_MIN = MIN_TEXT_MM / GUTTER_TEXT  # меньше — подписи мельче MIN_TEXT_MM
DARK = 0x3A3A3A
GREY = 0x8C8C8C
BUS = 0x5A5A5A
INPUT_WIRE = 0x8B4513  # коричневый — фаза ввода
RESERVE = 0x2E8B57
LW_BOX = 50
LW_DEV = 25
LW_WIRE = 35
LW_THIN = 13
LEFT = TextEntityAlignment.MIDDLE_LEFT
CENTER = TextEntityAlignment.MIDDLE_CENTER

TEXT: dict[str, dict[str, str]] = {
    "grid": {"ru": "Ввод 230 В", "uk": "Введення 230 В"},
    "reserve": {"ru": "резервная шина", "uk": "резервна шина"},
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
        "ru": "* — допущение: мощность типовая по виду точки, автомат подобран по группе; "
        "уточните (power у точки, groups в electrical.yaml)",
        "uk": "* — припущення: потужність типова за видом точки, автомат підібрано за групою; "
        "уточніть (power у точки, groups в electrical.yaml)",
    },
    "weak": {"ru": "Слабые места:", "uk": "Слабкі місця:"},
    "none": {"ru": "Слабых мест не найдено", "uk": "Слабких місць не знайдено"},
}
KIND_NAME: dict[DeviceKind, dict[str, str]] = {
    DeviceKind.BREAKER: {"ru": "Автомат 1P", "uk": "Автомат 1P"},
    DeviceKind.DIFF: {"ru": "Дифавтомат 1P+N", "uk": "Дифавтомат 1P+N"},
}
ASSUMED = "*"


def text(key: str, language: Language, **kw_: object) -> str:
    return TEXT[key][language].format(**kw_)


@dataclass(frozen=True)
class PanelDrawing:
    """Щит, подогнанный под место: модуль m и рейки."""

    m: float
    rows: tuple[tuple[Device, ...], ...]
    per_row: int
    external: bool  # инвертор или вилка справа от щита

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
    """Ширина рейки (12, 18 или 24 модуля), при которой модуль крупнее всего; не влезает
    даже с M_MIN — None."""
    external = panel.backup is not None
    best: PanelDrawing | None = None
    for per_row in (12, 18, 24):
        rows = din_rows(panel.devices, per_row)
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
    """Строка, обрезанная с «…» под ширину width, мм листа."""
    if text_width(s, h) <= width:
        return s
    while s and text_width(s + "…", h) > width:
        s = s[:-1]
    return s.rstrip() + "…"


def draw_device(layout: BaseLayout, d: Device, x: float, top: float, m: float, color: int) -> None:
    """Аппарат от левого верхнего угла корпуса: корпус, рычаги, надпись номинала."""
    w, h = d.modules * m, BODY * m
    x1, bottom = x + w, top - h
    _fill(layout, x, bottom, x1, top, 0xFFFFFF)
    _rect(layout, x, bottom, x1, top, lineweight=LW_DEV, true_color=DARK)
    # Полоска цвета группы — как у её линий на листах электрики и проводки
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
    ):
        poles = 1 if d.kind is DeviceKind.DIFF else d.modules
        for k in range(poles):
            cx = x + (k + 0.5) * m
            _fill(layout, cx - 0.22 * m, mid - 0.6 * m, cx + 0.22 * m, mid + 0.6 * m, DARK)
        if d.kind in (DeviceKind.DIFF, DeviceKind.RCD):  # кнопка «Тест»
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
        _text(layout, "I    0    II", Vec(cx, mid + 1.35 * m), th * 0.8)
    else:  # АВР
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
    """Провод группы вниз от автомата и вертикальные подписи по бокам."""
    bottom = top - (GUTTER - 0.4) * m
    _line(layout, [Vec(x, top), Vec(x, bottom)], color, LW_WIRE, E_PANEL_WIRE.name)
    layout.add_circle(
        (x, bottom), 0.15 * m, dxfattribs={"layer": E_PANEL_WIRE.name, "true_color": color}
    )
    th = min(TEXT_MAX * 0.9, GUTTER_TEXT * m)
    room = (GUTTER - 1.0) * m
    star = ASSUMED if g.assumed else ""
    left = clip(g.purpose, room, th)
    right = clip(f"{g.cable or '—'} · {kw(g.power)} кВт{star}", room, th)
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
    """Щит в лицо от левого верхнего угла места на листе."""
    m = fit.m
    groups = {g.group: g for g in panel.groups}
    x0 = top_left.x
    box_top = top_left.y - LEAD * m
    box_bottom = top_left.y - fit.height
    x1 = x0 + fit.box_w
    th = min(TEXT_MAX, 0.35 * m)
    title = panel_text("title", language, name=name, scheme=scheme_title(panel, language))
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
    places: dict[str, tuple[float, float]] = {}  # id аппарата → (x середины, верх)
    for r, row in enumerate(fit.rows):
        top = box_top - (PAD + r * ROW) * m
        dev_top = top - HEAD * m
        rail_y = dev_top - BODY * m / 2
        # DIN-рейка за аппаратами
        _fill(
            layout,
            x0 + PAD * m * 0.6,
            rail_y - 0.35 * m,
            x1 - PAD * m * 0.6,
            rail_y + 0.35 * m,
            0xC8C8C8,
        )
        x = x0 + PAD * m
        segments: list[tuple[float, float, bool]] = []
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
            segments.append((x, x + w, d.reserve))
            x += w
        # Шина над аппаратами: основная и резервная — отдельными кусками
        bus_y = dev_top + 0.25 * m
        for reserve in (False, True):
            xs = [(a, b) for a, b, rv in segments if rv is reserve]
            if not xs:
                continue
            a, b = xs[0][0] + 0.3 * m, xs[-1][1] - 0.3 * m
            _line(layout, [Vec(a, bus_y), Vec(b, bus_y)], RESERVE if reserve else BUS, LW_DEV)
            if reserve:
                y0 = dev_top - BODY * m - 0.3 * m
                layout.add_lwpolyline(
                    [
                        (a - 0.5 * m, y0),
                        (b + 0.5 * m, y0),
                        (b + 0.5 * m, top + 0.1 * m),
                        (a - 0.5 * m, top + 0.1 * m),
                    ],
                    close=True,
                    dxfattribs={"layer": E_PANEL.name, "true_color": RESERVE},
                )
                _text(
                    layout,
                    text("reserve", language),
                    Vec(b, y0 - 0.5 * m),
                    th * 0.9,
                    color=RESERVE,
                    align=TextEntityAlignment.MIDDLE_RIGHT,
                )
    # Ввод сверху в вводной автомат
    if "QS1" in places:
        cx, top = places["QS1"]
        with tagged(layout, "device", "QS1"):
            _line(
                layout, [Vec(cx, top_left.y), Vec(cx, top)], INPUT_WIRE, LW_WIRE, E_PANEL_WIRE.name
            )
            _text(
                layout,
                text("grid", language),
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
    """Инвертор или силовая вилка справа от щита и провод к переключателю резерва."""
    key = "inverter" if panel.backup == "inverter" else "plug"
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


# --- Таблица аппаратов и примечания ------------------------------------------


def device_rows(panel: BoardPanel, language: Language) -> list[tuple[Device, tuple[str, ...]]]:
    """Строки таблицы: аппарат → (поз., назначение, аппарат, кабель, P, I)."""
    groups = {g.group: g for g in panel.groups}
    out: list[tuple[Device, tuple[str, ...]]] = []
    for d in panel.devices:
        g = groups.get(d.group or "")
        star = ASSUMED if d.assumed else ""
        if g is not None:
            kind = KIND_NAME.get(d.kind, KIND_NAME[DeviceKind.BREAKER])[language]
            purpose = g.purpose + (ASSUMED if g.purpose_assumed else "")
            p = kw(g.power) + (ASSUMED if g.assumed else "")
            out.append((d, (d.id, purpose, f"{kind} {d.label}{star}", g.cable, p, amps(g.current))))
        else:
            out.append((d, (d.id, d.title, d.label + star, "", "", "")))
    return out


PURPOSE_MAX = 80.0  # мм листа: длинное назначение обрезается


def devices_table(panel: BoardPanel, language: Language, colors: dict[str, int]) -> Table:
    rows = device_rows(panel, language)
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
    """Расчётная нагрузка, допущения и слабые места — строки под таблицей."""
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
        text("assumed", language),
    ]
    if panel.warnings:
        lines.append(text("weak", language))
        lines += [f"! {w.text[language]}" for w in panel.warnings]
    else:
        lines.append(text("none", language))
    return lines
