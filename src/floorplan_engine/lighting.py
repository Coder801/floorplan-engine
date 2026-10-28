"""План освещения (решение 2026-10-28, P2): светильники, выключатели и что чем включается.

Связь «выключатель → свет» — из `controls` выключателя (только из источника); нет её —
по группе и помещению: выключатель стоит в группе света, которым управляет (правило
CLAUDE.md), и включает свет своей группы в своём помещении. Такая связь — допущение «*»:
у двухклавишного выключателя код не знает, какая клавиша что включает.

На листе — стены и проёмы, символы света и выключателей (слои E-SWITCH, E-LIGHT, E-LED),
связи (E-LINK, пунктир дугами: выключатель → ближайший светильник → следующий…; дуга —
чтобы связь не путалась с кабелем, тот идёт по прямым под 90°), номера точек —
как на листе электрики, только у света и выключателей (L-TEXT), таблица «Выключатели».
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ezdxf.layouts.layout import Modelspace
from shapely.ops import unary_union

from floorplan_engine.draw_electrical import (
    Anchor,
    _strip_area,
    _symbol_area,
    label_clusters,
    label_placer,
    place_label,
    point_anchor,
    stack_shifts,
)
from floorplan_engine.draw_plan import room_geometries
from floorplan_engine.geometry import Contour, Vec
from floorplan_engine.ids import tagged
from floorplan_engine.layers import E_LINK, L_TEXT, LW_LINK
from floorplan_engine.point_numbers import number_points, point_name, ranges
from floorplan_engine.schema import (
    LIGHT_TYPES,
    SWITCH_TYPES,
    Electrical,
    ElectricalPoint,
    Plan,
    PointType,
)
from floorplan_engine.tables import Column, Table, name_width
from floorplan_engine.texts import Language

TEXT: dict[str, dict[str, str]] = {
    "title": {"ru": "Выключатели", "uk": "Вимикачі"},
    "number": {"ru": "№", "uk": "№"},
    "switch": {"ru": "Выключатель", "uk": "Вимикач"},
    "controls": {"ru": "Включает", "uk": "Вмикає"},
    "group": {"ru": "Группа", "uk": "Група"},
    "strip": {"ru": "лента {name}", "uk": "стрічка {name}"},
    "assumed": {
        "ru": "* — связь по группе и помещению, не из проекта: уточните (controls в "
        "electrical.yaml); у двухклавишного — какая клавиша что включает",
        "uk": "* — зв'язок за групою і приміщенням, не з проєкту: уточніть (controls в "
        "electrical.yaml); у двоклавішного — яка клавіша що вмикає",
    },
}


def text(key: str, language: Language, **kw: object) -> str:
    return TEXT[key][language].format(**kw)


@dataclass(frozen=True)
class SwitchLink:
    switch: str
    targets: tuple[str, ...]  # id светильников, выводов LED и лент
    assumed: bool  # из группы и помещения, не из controls


def is_lighting(p: ElectricalPoint) -> bool:
    return p.type in LIGHT_TYPES or p.type in SWITCH_TYPES


# Слова подписи выключателя → какой свет он включает (основы слов, ru и uk)
KEYWORDS: tuple[tuple[tuple[str, ...], frozenset[PointType]], ...] = (
    (("бра",), frozenset({PointType.SCONCE})),
    (("підвіс", "подвес"), frozenset({PointType.PENDANT})),
    (("підсвіт", "подсвет", "led", "стрічк", "лент"), frozenset({PointType.LED_OUTPUT})),
    (
        ("стел", "потол", "точков", "основн"),
        frozenset({PointType.DOWNLIGHT, PointType.LIGHT}),
    ),
)


def _words(note: str | None) -> set[str]:
    return {w for w in (note or "").lower().replace(",", " ").split() if len(w) >= 4}


def _by_note(s: ElectricalPoint, candidates: Sequence[ElectricalPoint]) -> list[str]:
    """Свет, который выключатель включает по своей подписи: по виду («бра» → бра) или по
    общему слову с подписью светильника («підсвітка кухні»). Подсказки нет — []."""
    note = (s.note or "").lower()
    kinds: set[PointType] = set()
    for stems, types in KEYWORDS:
        if any(stem in note for stem in stems):
            kinds |= types
    words = _words(s.note)
    return [c.id for c in candidates if c.type in kinds or (words and words & _words(c.note))]


def switch_links(elec: Electrical) -> list[SwitchLink]:
    """Что включает каждый выключатель. Из controls — как есть. Иначе — допущение: свет
    его группы в его помещении; если подпись выключателя подсказывает вид или общее слово
    («бра», «стеля», «підсвітка кухні») — только такой свет; выключатели без подсказки
    берут то, что не разобрали подсказанные (а если всё разобрано — весь свет группы).
    Без controls и без группы — ничего: связь не выдумывается."""
    out: list[SwitchLink] = []
    pending: list[tuple[ElectricalPoint, list[ElectricalPoint]]] = []
    claimed: dict[tuple[str, str], set[str]] = {}
    for s in elec.points:
        if s.type not in SWITCH_TYPES:
            continue
        if s.controls:
            out.append(SwitchLink(s.id, tuple(s.controls), False))
            continue
        if s.group is None:
            continue
        candidates = [
            p
            for p in elec.points
            if p.type in LIGHT_TYPES and p.group == s.group and p.room == s.room
        ]
        hinted = _by_note(s, candidates)
        if hinted:
            out.append(SwitchLink(s.id, tuple(hinted), True))
            claimed.setdefault((s.group, s.room), set()).update(hinted)
        elif candidates:
            pending.append((s, candidates))
    for s, candidates in pending:
        taken = claimed.get((s.group or "", s.room), set())
        rest = [c.id for c in candidates if c.id not in taken] or [c.id for c in candidates]
        out.append(SwitchLink(s.id, tuple(rest), True))
    order = {p.id: k for k, p in enumerate(elec.points)}
    return sorted(out, key=lambda lk: order[lk.switch])


# Изгиб связи: дуга на столько градусов (у всех связей — в одну сторону)
LINK_SWEEP_DEG = 40.0
LINK_BULGE = math.tan(math.radians(LINK_SWEEP_DEG) / 4)  # выпуклость вершины LWPOLYLINE


def arc_link(msp: Modelspace, points: Sequence[Vec], attribs: dict[str, object]) -> None:
    """Связь через точки — дугами между соседними (выпуклость у каждой вершины, кроме последней)."""
    msp.add_lwpolyline(
        [(v.x, v.y, LINK_BULGE if k < len(points) - 1 else 0.0) for k, v in enumerate(points)],
        format="xyb",
        dxfattribs=attribs,
    )


def chain(start: Vec, targets: Sequence[tuple[str, Vec]]) -> list[tuple[str, Vec]]:
    """Обход целей от start: каждый раз — к ближайшей ещё не пройденной."""
    left = list(targets)
    out: list[tuple[str, Vec]] = []
    at = start
    while left:
        k = min(range(len(left)), key=lambda i: ((left[i][1] - at).length(), left[i][0]))
        item = left.pop(k)
        out.append(item)
        at = item[1]
    return out


def draw_lighting(
    msp: Modelspace, plan: Plan, contours: dict[str, Contour], elec: Electrical
) -> None:
    """Связи выключателей и номера света на своих слоях (символы — с листа электрики)."""
    geoms_list = room_geometries(plan, contours)
    geoms = {g.room.id: g for g in geoms_list}
    shifts = stack_shifts(elec.points)
    anchors: dict[str, Anchor] = {
        p.id: point_anchor(p, geoms, shifts[k]) for k, p in enumerate(elec.points)
    }
    spots = {pid: _spot(a) for pid, a in anchors.items()}
    for strip in elec.led_strips:
        c = _strip_area(strip, geoms).centroid
        spots[strip.id] = Vec(c.x, c.y)

    # Как на плане освещения: свет одного набора — одной цепочкой дуг, от выключателя — одна
    # дуга к ближайшему светильнику набора
    links = switch_links(elec)
    attribs = {"layer": E_LINK.name, "lineweight": LW_LINK}
    drawn: set[frozenset[str]] = set()
    for link in links:
        targets = [(t, spots[t]) for t in link.targets if t in spots]
        if not targets:
            continue
        start = spots[link.switch]
        key = frozenset(t for t, _ in targets)
        if key not in drawn and len(targets) > 1:
            drawn.add(key)
            head = min(targets, key=lambda tv: ((tv[1] - start).length(), tv[0]))
            path = chain(head[1], [tv for tv in targets if tv[0] != head[0]])
            with tagged(msp, "light_set", ",".join(sorted(key))):
                arc_link(msp, [head[1], *(v for _, v in path)], attribs)
        nearest = min(targets, key=lambda tv: ((tv[1] - start).length(), tv[0]))
        with tagged(msp, "switch_link", link.switch):
            arc_link(msp, [start, nearest[1]], attribs)

    lights = [p for p in elec.points if is_lighting(p)]
    symbols = [_symbol_area(anchors[p.id]) for p in lights]
    strips = [_strip_area(s, geoms) for s in elec.led_strips]
    placer = label_placer(geoms_list, symbols, strips)
    numbers = number_points(plan, elec)
    for cluster in label_clusters(lights):
        ids = [lights[k].id for k in cluster]
        first, last = anchors[ids[0]], anchors[ids[-1]]
        center = first.pos + (last.pos - first.pos) * 0.5
        label_at = Anchor(center, first.inward, first.wall_dir, first.depth)
        own = unary_union([_symbol_area(anchors[i]) for i in ids])
        with tagged(msp, "label", ",".join(ids)):
            place_label(
                msp,
                placer,
                [ranges([numbers[i] for i in ids])],
                label_at,
                own,
                lights[cluster[0]].room,
                layer=L_TEXT.name,
            )


def _spot(a: Anchor) -> Vec:
    """Куда ведёт связь: середина символа (у точки на стене — отступ от стены)."""
    if a.inward is None:
        return a.pos
    return a.pos + a.inward * (a.depth / 2)


@dataclass(frozen=True)
class SwitchRow:
    numbers: str
    name: str
    controls: str
    group: str
    point_ids: tuple[str, ...]


def switch_rows(plan: Plan, elec: Electrical) -> list[SwitchRow]:
    """Строки таблицы «Выключатели» по номерам выключателей."""
    lang = plan.language
    numbers = number_points(plan, elec)
    by_id = {p.id: p for p in elec.points}
    strips = {s.id: s for s in elec.led_strips}
    rows: list[SwitchRow] = []
    for link in sorted(switch_links(elec), key=lambda lk: numbers[lk.switch]):
        s = by_id[link.switch]
        nums = [numbers[t] for t in link.targets if t in numbers]
        named = [text("strip", lang, name=strips[t].note or t) for t in link.targets if t in strips]
        what = ", ".join(x for x in [ranges(nums), *named] if x)
        rows.append(
            SwitchRow(
                str(numbers[s.id]),
                point_name(s, lang),
                f"{what}*" if link.assumed else what,
                s.group or "",
                (s.id, *link.targets),
            )
        )
    return rows


def switch_table(plan: Plan, elec: Electrical) -> tuple[Table, list[str]] | None:
    """Таблица «Выключатели» и примечание о допущениях; выключателей со связями нет — None."""
    rows = switch_rows(plan, elec)
    if not rows:
        return None
    lang = plan.language
    columns = (
        Column(text("number", lang), 10.0),
        Column(text("switch", lang), name_width([r.name for r in rows]), "left"),
        Column(text("controls", lang), name_width([r.controls for r in rows]), "left"),
        Column(text("group", lang), 16.0),
    )
    cells = tuple((r.numbers, r.name, r.controls, r.group) for r in rows)
    notes = [text("assumed", lang)] if any(r.controls.endswith("*") for r in rows) else []
    return Table(text("title", lang), columns, cells), notes
