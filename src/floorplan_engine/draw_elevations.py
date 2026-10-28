"""Развёртка стены на листе (elevations.py → блок листа): рисуется прямо на листе, в масштабе
комплекта, как щит в лицо. Снизу — отступы от левого угла стены, справа — высоты от пола
(ординатные размеры: близкие значения разводятся, к месту ведёт излом выноски).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ezdxf.colors import RGB
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.layout import Paperspace

from floorplan_engine.draw_plan import add_text
from floorplan_engine.elevations import POST_PITCH_MM, WallElevation, behind_text
from floorplan_engine.geometry import Vec
from floorplan_engine.ids import tagged
from floorplan_engine.layers import E_ELEV, MIN_TEXT_MM, TEXT_DIM_MM, TEXT_SMALL_MM, text_width
from floorplan_engine.point_numbers import ranges
from floorplan_engine.schema import PointType
from floorplan_engine.texts import Language, tr

DARK = 0x29251F
GREY = 0x9A9288
LIGHT = 0xD9D3C8
CHASE = 0xE4DED3
CHASE_LOW = 0xCFE3F3
BACK = 0xB0A99D  # выводы с обратной стороны стены — бледно
LOW = 0x1F6FB2  # слаботочка
BOX = 0xB3261E

LW_FLOOR = 50
LW_WALL = 25
LW_THIN = 13

TITLE_H = TEXT_DIM_MM
SIDE_H = TEXT_SMALL_MM  # строка под заголовком: вид изнутри, что за стеной
SIDE_GAP = 1.0
TITLE_GAP = 3.0
HEAD = TITLE_H + SIDE_GAP + SIDE_H + TITLE_GAP  # заголовок над стеной
ORD_TEXT = TEXT_SMALL_MM  # подписи размеров
ORD_GAP = 0.8  # между соседними подписями
TICK = 1.2  # выноска до излома
JOG = 2.0  # излом
MIN_SYMBOL = 1.0  # радиус символа на листе — не меньше, мм
DASH, DASH_GAP = 0.8, 0.6  # пунктир выносок от вывода к шкалам, мм листа

SWITCHES = frozenset({PointType.SWITCH, PointType.PASS_SWITCH})
LOW_TYPES = frozenset({PointType.DATA, PointType.TV})

Box = tuple[float, float, float, float]  # x0, y0, x1, y1 — мм листа


def spread(wanted: Sequence[float], gap: float, lo: float, hi: float) -> list[float]:
    """Места подписей вдоль оси: как можно ближе к wanted (по возрастанию), не ближе gap друг
    к другу, в пределах lo…hi, если влезают."""
    out: list[float] = []
    for w in wanted:
        out.append(max(w, lo, out[-1] + gap) if out else max(w, lo))
    if out and out[-1] > hi:
        out[-1] = hi
        for k in range(len(out) - 2, -1, -1):
            out[k] = min(out[k], out[k + 1] - gap)
    return out


@dataclass(frozen=True)
class ElevationPanel:
    width: float
    height: float
    draw: Callable[[Paperspace, Vec], None]


def elevation_panel(e: WallElevation, scale: float, language: Language) -> ElevationPanel:
    """Развёртка стены e на листе в масштабе 1:scale; draw — от левого верхнего угла блока."""
    w, h = e.length / scale, e.top / scale
    right = _ord_width([*e.heights(), e.height])
    bottom = _ord_width([*e.offsets(), 0.0, e.length])
    width = max(
        w + right + JOG,
        text_width(_title(e, language), TITLE_H),
        text_width(_side(e, language), SIDE_H),
    )
    height = HEAD + h + bottom + JOG

    def draw(psp: Paperspace, top_left: Vec) -> None:
        with tagged(psp, "elevation", e.key):
            _draw(psp, e, scale, language, top_left, w, h)

    return ElevationPanel(width, height, draw)


def _title(e: WallElevation, language: Language) -> str:
    return tr("elev_title", language, room=e.room_name, n=e.index, length=f"{e.length:.0f}")


def _side(e: WallElevation, language: Language) -> str:
    """Вторая строка: с какой стороны вид и что за стеной — у общей перегородки две
    развёртки, и каждая называет другую."""
    return tr("elev_side", language, behind=behind_text(e, language))


def _ord_width(values: Sequence[float]) -> float:
    """Место под ординатные размеры: выноска, излом и самая длинная подпись."""
    longest = max((text_width(f"{v:.0f}*", ORD_TEXT) for v in values), default=0.0)
    return TICK + JOG + 0.5 + longest


def _draw(
    psp: Paperspace,
    e: WallElevation,
    scale: float,
    language: Language,
    top_left: Vec,
    w: float,
    h: float,
) -> None:
    x0 = top_left.x
    floor = top_left.y - HEAD - h
    top = floor + h
    ceil = floor + e.height / scale  # потолок; выше — только если точка выше потолка

    def at(x: float, y: float) -> Vec:
        return Vec(x0 + x / scale, floor + y / scale)

    def line(a: Vec, b: Vec, lw: int = LW_THIN, color: int = DARK) -> None:
        psp.add_line(
            a.as_tuple(),
            b.as_tuple(),
            dxfattribs={"layer": E_ELEV.name, "lineweight": lw, "true_color": color},
        )

    def rect(b: Box, lw: int = LW_THIN, color: int = DARK, fill: int | None = None) -> None:
        bx0, by0, bx1, by1 = b
        if fill is not None:
            hatch = psp.add_hatch(dxfattribs={"layer": E_ELEV.name})
            hatch.set_solid_fill(rgb=RGB.from_hex(f"#{fill:06x}"))
            hatch.paths.add_polyline_path(
                [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)], is_closed=True
            )
        pts = [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)]
        psp.add_lwpolyline(
            pts,
            close=True,
            dxfattribs={"layer": E_ELEV.name, "lineweight": lw, "true_color": color},
        )

    def dashed(a: Vec, b: Vec, color: int = GREY) -> None:
        """Пунктир штрихами-отрезками: так он один и тот же в DXF, PNG и просмотре."""
        length = (b - a).length()
        if length < 1e-6:
            return
        step = (b - a) * (1 / length)
        t = 0.0
        while t < length:
            line(a + step * t, a + step * min(t + DASH, length), LW_THIN, color)
            t += DASH + DASH_GAP

    def text(
        s: str,
        p: Vec,
        hgt: float = ORD_TEXT,
        angle: float = 0.0,
        align: TextEntityAlignment = TextEntityAlignment.MIDDLE_LEFT,
        color: int = DARK,
    ) -> None:
        size = max(hgt, MIN_TEXT_MM)
        add_text(psp, s, p, size, E_ELEV.name, angle, align, color=color, scale=1.0)

    text(
        _title(e, language),
        Vec(x0, top_left.y - TITLE_H / 2),
        TITLE_H,
        align=TextEntityAlignment.MIDDLE_LEFT,
    )
    text(
        _side(e, language),
        Vec(x0, top_left.y - TITLE_H - SIDE_GAP - SIDE_H / 2),
        SIDE_H,
        align=TextEntityAlignment.MIDDLE_LEFT,
    )

    # Штробы — под всем остальным
    for ch in e.chases:
        half = max((50.0 if ch.wide else 30.0) / 2 / scale, 0.3)
        a, b = at(ch.x, ch.y0), at(ch.x, ch.y1)
        rect((a.x - half, a.y, a.x + half, b.y), LW_THIN, GREY, CHASE_LOW if ch.low else CHASE)

    # Стена: пол и потолок толще, торцы — углы помещения
    line(Vec(x0, floor), Vec(x0 + w, floor), LW_FLOOR)
    line(Vec(x0, ceil), Vec(x0 + w, ceil), LW_FLOOR)
    line(Vec(x0, floor), Vec(x0, top), LW_WALL)
    line(Vec(x0 + w, floor), Vec(x0 + w, top), LW_WALL)

    for o in e.openings:
        a, b = at(o.x0, o.y0), at(o.x1, o.y1)
        color = GREY if o.assumed else DARK
        rect((a.x, a.y, b.x, b.y), LW_WALL, color, 0xFFFFFF)
        if o.kind == "window":  # переплёт
            mid = (a.x + b.x) / 2
            line(Vec(mid, a.y), Vec(mid, b.y), LW_THIN, color)
        elif o.kind == "door":  # открывание — треугольник к петлям
            line(Vec(a.x, a.y), Vec((a.x + b.x) / 2, b.y), LW_THIN, LIGHT)
            line(Vec(b.x, a.y), Vec((a.x + b.x) / 2, b.y), LW_THIN, LIGHT)
        if o.assumed:
            text("*", Vec(b.x - 0.4, b.y - ORD_TEXT), align=TextEntityAlignment.MIDDLE_RIGHT)

    # Зоны шкал размеров: справа от стены и под полом — подписи точек туда не ставятся
    taken: list[Box] = [
        (x0 + w, floor - 1.0, x0 + w + TICK + JOG + 12.0, top + 1.0),
        (x0 - 1.0, floor - TICK - JOG - 12.0, x0 + w + 1.0, floor),
    ]
    if e.board is not None:
        bd = e.board
        a = at(bd.x - bd.width / 2, bd.y - bd.height / 2)
        b = at(bd.x + bd.width / 2, bd.y + bd.height / 2)
        rect((a.x, a.y, b.x, b.y), LW_WALL, DARK, 0xFFFFFF)
        centre = Vec((a.x + b.x) / 2, (a.y + b.y) / 2)
        text(bd.name, centre, align=TextEntityAlignment.MIDDLE_CENTER)
        taken.append((a.x, a.y, b.x, b.y))

    for bx in e.boxes:
        c = at(bx.x, bx.y)
        half = max(bx.size / 2 / scale, 0.8)
        rect((c.x - half, c.y - half, c.x + half, c.y + half), LW_WALL, BOX, 0xFFFFFF)
        taken.append((c.x - half, c.y - half, c.x + half, c.y + half))
        _label(bx.label, c, half, taken, text, BOX)

    # Выводы с обратной стороны стены — бледно, под своими, без размеров (они — на развёртке
    # той стороны)
    r = max(34.0 / scale, MIN_SYMBOL)  # подрозетник Ø68
    pitch = max(POST_PITCH_MM / scale, 2 * r)
    for p in e.back:
        c = at(p.x, p.y)
        first = c.x - pitch * (p.posts - 1) / 2
        for k in range(p.posts):
            cx = first + k * pitch
            if p.type in SWITCHES:
                rect((cx - r, c.y - r, cx + r, c.y + r), LW_THIN, BACK)
            else:
                psp.add_circle(
                    (cx, c.y),
                    r,
                    dxfattribs={"layer": E_ELEV.name, "lineweight": LW_THIN, "true_color": BACK},
                )

    # Точки: пунктир вниз к шкале отступов и вправо к шкале высот, символ (пост блока —
    # свой кружок), номер
    labels: dict[tuple[float, float], tuple[list[int], float]] = {}
    for p in e.points:
        c = at(p.x, p.y)
        half_block = r + pitch * (p.posts - 1) / 2
        dashed(Vec(c.x, c.y - r), Vec(c.x, floor))
        dashed(Vec(c.x + half_block, c.y), Vec(x0 + w, c.y))
        color = LOW if p.type in LOW_TYPES else DARK
        first = c.x - pitch * (p.posts - 1) / 2
        for k in range(p.posts):
            cx = first + k * pitch
            if p.type in SWITCHES:
                rect((cx - r, c.y - r, cx + r, c.y + r), LW_WALL, color, 0xFFFFFF)
            else:
                psp.add_circle(
                    (cx, c.y),
                    r,
                    dxfattribs={"layer": E_ELEV.name, "lineweight": LW_WALL, "true_color": color},
                )
            taken.append((cx - r, c.y - r, cx + r, c.y + r))
        key = (round(c.x, 1), round(c.y, 1))
        nums, half = labels.get(key, ([], 0.0))
        labels[key] = ([*nums, p.number], max(half, r + pitch * (p.posts - 1) / 2))
    for (cx, cy), (nums, half) in labels.items():
        _label(ranges(nums), Vec(cx, cy), half, taken, text, DARK)
    # Номера выводов той стороны — после своих: место у символа — сначала своим
    for p in e.back:
        c = at(p.x, p.y)
        _label(str(p.number), c, r + pitch * (p.posts - 1) / 2, taken, text, BACK)

    _ordinates_x(e, scale, x0, floor, w, line, text)
    _ordinates_y(e, scale, x0 + w, floor, top, line, text)


def _label(
    s: str,
    c: Vec,
    half: float,
    taken: list[Box],
    text: Callable[..., None],
    color: int,
) -> None:
    """Подпись у символа: справа, слева, сверху или снизу — где не занято."""
    tw, th = text_width(s, ORD_TEXT), max(ORD_TEXT, MIN_TEXT_MM)
    gap = 0.6
    options = [
        ((c.x + half + gap, c.y - th / 2, c.x + half + gap + tw, c.y + th / 2), "left"),
        ((c.x - half - gap - tw, c.y - th / 2, c.x - half - gap, c.y + th / 2), "left"),
        ((c.x - tw / 2, c.y + half + gap, c.x + tw / 2, c.y + half + gap + th), "left"),
        ((c.x - tw / 2, c.y - half - gap - th, c.x + tw / 2, c.y - half - gap), "left"),
    ]
    choice = next((b for b, _ in options if not any(_hit(b, t) for t in taken)), options[0][0])
    taken.append(choice)
    text(s, Vec(choice[0], (choice[1] + choice[3]) / 2), color=color)


def _hit(a: Box, b: Box) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _ordinates_x(
    e: WallElevation,
    scale: float,
    x0: float,
    floor: float,
    w: float,
    line: Callable[..., None],
    text: Callable[..., None],
) -> None:
    """Отступы от левого угла — под полом: подписи вертикально, разведены по ширине."""
    values = sorted({0.0, *e.offsets(), e.length})
    wanted = [x0 + v / scale for v in values]
    th = max(ORD_TEXT, MIN_TEXT_MM)
    places = spread(wanted, th + ORD_GAP, x0 - th, x0 + w + th)
    for v, want, place in zip(values, wanted, places, strict=True):
        line(Vec(want, floor), Vec(want, floor - TICK))
        line(Vec(want, floor - TICK), Vec(place, floor - TICK - JOG))
        text(
            f"{v:.0f}",
            Vec(place, floor - TICK - JOG - 0.5),
            angle=90.0,
            align=TextEntityAlignment.MIDDLE_RIGHT,
        )


def _ordinates_y(
    e: WallElevation,
    scale: float,
    right: float,
    floor: float,
    ceil: float,
    line: Callable[..., None],
    text: Callable[..., None],
) -> None:
    """Высоты от пола — справа от стены; высота потолка — со «*», если допущение."""
    values = sorted({*e.heights(), e.height})
    wanted = [floor + v / scale for v in values]
    th = max(ORD_TEXT, MIN_TEXT_MM)
    places = spread(wanted, th + ORD_GAP, floor, ceil + th)
    for v, want, place in zip(values, wanted, places, strict=True):
        line(Vec(right, want), Vec(right + TICK, want))
        line(Vec(right + TICK, want), Vec(right + TICK + JOG, place))
        mark = "*" if v == e.height and e.height_assumed else ""
        text(f"{v:.0f}{mark}", Vec(right + TICK + JOG + 0.5, place))
