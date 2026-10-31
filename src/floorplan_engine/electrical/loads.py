"""Потребители и группы щита: мощность точки (`power` или типовая по виду и пометке —
допущение «*»), нагрузка группы и ток, автомат группы (из модели или по виду: свет 10 А,
розетки 16 А, тяжёлые — по току, не больше, чем держит кабель), перегруженная группа —
линиями на щите (QF8 → QF8, QF8.2). Однофазный ввод 230 В."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from floorplan_engine.electrical.groups import LIGHT, LOW, composed_purpose, group_key
from floorplan_engine.electrical.panel_text import text
from floorplan_engine.model.schema import Electrical, ElectricalPoint, PanelScheme, Plan, PointType
from floorplan_engine.model.texts import Language, tr

VOLTAGE = 230.0
COS_PHI = 1.0  # коэффициент мощности: в квартире преобладает активная нагрузка (допущение)
RATINGS = (6, 10, 16, 20, 25, 32, 40, 50, 63)  # ряд номиналов автоматов, А
LIGHT_A = 10
SOCKETS_A = 16
HEAVY_W = 2000.0  # от этой мощности потребитель — тяжёлый: своя линия
SOCKET_POST_W = 100.0  # расчётная мощность поста розетки без пометки (допущение)
OUTLET_W = 1000.0  # вывод к технике без пометки (допущение)
# Сечение, мм² → (рекомендуемый, наибольший) автомат, А: медь, скрытая проводка
CABLE_LIMITS: dict[float, tuple[int, int]] = {
    1.5: (10, 16),
    2.5: (16, 25),
    4.0: (25, 32),
    6.0: (32, 40),
    10.0: (40, 50),
    16.0: (63, 63),
}
# Типовая мощность точек по виду, Вт (допущение)
TYPE_W: dict[PointType, float] = {
    PointType.LIGHT: 100.0,
    PointType.PENDANT: 100.0,
    PointType.SCONCE: 40.0,
    PointType.DOWNLIGHT: 10.0,
    PointType.LED_OUTPUT: 50.0,
}
# Типовая мощность по пометке точки, Вт (допущение); первое совпадение
NOTE_W: tuple[tuple[re.Pattern[str], float], ...] = tuple(
    (re.compile(p, re.IGNORECASE), w)
    for p, w in (
        (r"варильн|варочн|індукц|индукц|плит", 7200.0),
        (r"духов", 3500.0),
        (r"бойлер|водонагр", 2000.0),
        (r"пральн|стирал", 2200.0),
        (r"сушил|сушиль", 2500.0),
        (r"посудом", 2200.0),
        (r"чайник", 2200.0),
        (r"кондиц|кондиціон", 1500.0),
        (r"\bтп\b|тепл\w* підлог|тепл\w* пол", 1500.0),
        (r"мікрохвил|микроволн|\bсвч\b", 1200.0),
        (r"рушникосуш|полотенцесуш", 300.0),
        (r"холодил", 300.0),
        (r"витяж|вытяж", 200.0),
        (r"\btv\b|телевіз|телевиз", 300.0),
        (r"котел|котёл|котл", 200.0),
        (r"насос", 500.0),
        (r"домофон|роутер|відеоспост|видеонаб", 20.0),
    )
)
# Что по умолчанию держит резервная шина: свет, розетки кухни и эти потребители (по пометке)
RESERVE_NOTE = re.compile(r"холодил|котел|котёл|котл|роутер|насос|ворот|домофон", re.IGNORECASE)
KITCHEN = re.compile(r"кух", re.IGNORECASE)
# Мокрая зона по названию, если в room.yaml нет wet: true (допущение)
WET_NAME = re.compile(r"санв|сануз|ванн|душ|пральн|прачеч|постироч", re.IGNORECASE)
# Пусковой ток: такой группе характеристика C и в premium
MOTOR = re.compile(r"кондиц|кондиціон|насос|ворот|компрес", re.IGNORECASE)


def demand_factor(installed_kw: float) -> float:
    """Коэффициент спроса квартиры по установленной мощности (допущение)."""
    if installed_kw <= 10:
        return 0.8
    if installed_kw <= 15:
        return 0.7
    if installed_kw <= 25:
        return 0.6
    return 0.5


def current(watts: float) -> float:
    return watts / VOLTAGE / COS_PHI


def rating_for(amps: float, floor: int = SOCKETS_A) -> int:
    """Ближайший номинал ряда не меньше тока и не меньше floor."""
    return next((r for r in RATINGS if r >= max(amps, floor)), RATINGS[-1])


_SECTION = re.compile(r"(\d+)\s*[xх×*]\s*(\d+(?:[.,]\d+)?)", re.IGNORECASE)


def cable_section(mark: str) -> float | None:
    """Сечение жилы из марки «3x2.5», «ВВГнг 3х2,5»; не разобрать — None."""
    m = _SECTION.search(mark)
    return float(m.group(2).replace(",", ".")) if m else None


_BREAKER = re.compile(r"^\s*([BCD])?\s*(\d+)", re.IGNORECASE)


def parse_breaker(text: str) -> tuple[str, int] | None:
    """«C16» → ("C", 16); «16 А» → ("C", 16); не разобрать — None."""
    m = _BREAKER.match(text)
    if m is None:
        return None
    return (m.group(1) or "C").upper(), int(m.group(2))


class Kind(StrEnum):
    LIGHT = "light"
    SOCKETS = "sockets"
    HEAVY = "heavy"


@dataclass(frozen=True)
class Load:
    """Потребитель: точка модели с мощностью."""

    point: str  # id точки
    room: str  # название помещения
    title: str
    count: int
    power: float  # Вт, на точку целиком
    assumed: bool  # мощность типовая, не из источника

    @property
    def heavy(self) -> bool:
        return self.power >= HEAVY_W


@dataclass(frozen=True)
class Breaker:
    curve: str
    rating: int
    assumed: bool  # подобран кодом, а не из модели

    @property
    def label(self) -> str:
        return f"{self.curve}{self.rating}"


@dataclass(frozen=True)
class PanelGroup:
    group: str
    kind: Kind
    purpose: str
    purpose_assumed: bool
    loads: tuple[Load, ...]
    cable: str  # марки кабелей группы через запятую
    section: float | None  # наименьшее сечение
    breaker: Breaker
    rcd: str | None  # «30 мА» — дифавтомат или под УЗО
    wet: bool
    reserved: bool
    split_of: str | None = None  # линия перегруженной группы, разделённой на щите

    @property
    def power(self) -> float:
        return sum(ld.power for ld in self.loads)

    @property
    def current(self) -> float:
        return current(self.power)

    @property
    def assumed(self) -> bool:
        return any(ld.assumed for ld in self.loads)


def point_load(p: ElectricalPoint, rooms: dict[str, str], language: Language) -> Load | None:
    """Потребитель по точке; выключатель без пометки и слаботочка — None."""
    room = rooms.get(p.room, p.room)
    note_w = next((w for rx, w in NOTE_W if p.note and rx.search(p.note)), None)
    title = p.note[0].upper() + p.note[1:] if p.note else tr(f"symbol_{p.type.value}", language)
    if p.power is not None:
        return Load(p.id, room, title, p.count, p.power, False)
    if note_w is not None:
        return Load(p.id, room, title, p.count, note_w, True)
    if p.type in TYPE_W:
        return Load(p.id, room, title, p.count, TYPE_W[p.type] * p.count, True)
    if p.type is PointType.SOCKET:
        title = text("socket_generic", language) if not p.note else title
        return Load(p.id, room, title, p.count, SOCKET_POST_W * p.count, True)
    if p.type is PointType.OUTLET:
        title = text("outlet_generic", language) if not p.note else title
        return Load(p.id, room, title, p.count, OUTLET_W, True)
    return None


def _kind(points: Sequence[ElectricalPoint], loads: Sequence[Load], section: float | None) -> Kind:
    if any(ld.heavy for ld in loads) or (section is not None and section >= 4):
        return Kind.HEAVY
    powered = {p.id for p in points} & {ld.point for ld in loads}
    if powered and all(p.type in LIGHT for p in points if p.id in powered):
        return Kind.LIGHT
    return Kind.SOCKETS


def _breaker(kind: Kind, amps_: float, section: float | None, curve: str) -> Breaker:
    """Автомат по виду группы, но не больше рекомендуемого для кабеля."""
    rating = {Kind.LIGHT: LIGHT_A, Kind.SOCKETS: SOCKETS_A}.get(kind) or rating_for(amps_)
    if section is not None and section in CABLE_LIMITS:
        rating = min(rating, CABLE_LIMITS[section][0])
    return Breaker(curve, rating, True)


def split_loads(loads: Sequence[Load], capacity: float) -> list[list[Load]]:
    """Нагрузки по линиям не больше capacity, Вт: крупные — первыми, каждая — в первую
    линию, где хватает места (порядок внутри линии — как в модели)."""
    lines: list[list[Load]] = []
    for ld in sorted(loads, key=lambda x: -x.power):
        line = next((ln for ln in lines if sum(x.power for x in ln) + ld.power <= capacity), None)
        if line is None:
            lines.append([ld])
        else:
            line.append(ld)
    order = {ld.point: k for k, ld in enumerate(loads)}
    return [sorted(ln, key=lambda x: order[x.point]) for ln in lines]


def _wet_group(points: Sequence[ElectricalPoint], wet_rooms: set[str]) -> bool:
    """Розетки или выводы в мокром помещении — группе нужно УЗО."""
    return any(
        p.room in wet_rooms and p.type in (PointType.SOCKET, PointType.OUTLET) for p in points
    )


def panel_groups(
    plan: Plan, elec: Electrical, scheme: PanelScheme, backup: bool
) -> list[PanelGroup]:
    lang = plan.language
    rooms = {r.id: r.name for r in plan.rooms}
    wet_rooms = {r.id for r in plan.rooms if r.wet or WET_NAME.search(r.name)}
    names = {p.group for p in elec.points if p.group} | {c.group for c in elec.cables if c.group}
    reserve = set(elec.panel.reserve)
    out: list[PanelGroup] = []
    for g in sorted(names, key=group_key):
        points = [p for p in elec.points if p.group == g]
        if points and all(p.type in LOW for p in points):
            continue  # слаботочка — не в щите
        loads = [ld for p in points if (ld := point_load(p, rooms, lang)) is not None]
        marks = sorted({c.cable for c in elec.cables if c.group == g})
        sections = [s for m in marks if (s := cable_section(m)) is not None]
        section = min(sections) if sections else None
        kind = _kind(points, loads, section)
        info = elec.groups.get(g)
        parsed = parse_breaker(info.breaker) if info is not None and info.breaker else None
        motor = any(p.note and MOTOR.search(p.note) for p in points)
        curve = "B" if scheme == "premium" and not motor else "C"
        breaker = (
            Breaker(parsed[0], parsed[1], False)
            if parsed is not None
            else _breaker(kind, current(sum(ld.power for ld in loads)), section, curve)
        )
        wet = _wet_group(points, wet_rooms)
        rcd = info.rcd if info is not None and info.rcd else None
        if rcd is None and (wet or scheme == "premium"):
            rcd = "30 мА"
        purpose = info.name if info is not None and info.name else None
        kitchen = kind is Kind.SOCKETS and any(
            KITCHEN.search(rooms.get(p.room, "")) for p in points
        )
        reserved = backup and (
            g in reserve
            if reserve
            else (
                kind is Kind.LIGHT
                or kitchen
                or any(p.note and RESERVE_NOTE.search(p.note) for p in points)
            )
        )
        base = PanelGroup(
            g,
            kind,
            purpose or composed_purpose(points, rooms, lang),
            purpose is None,
            tuple(loads),
            ", ".join(marks),
            section,
            breaker,
            rcd,
            wet,
            reserved,
        )
        lines = split_loads(loads, breaker.rating * VOLTAGE * COS_PHI)
        if base.current <= breaker.rating or len(lines) < 2:
            out.append(base)
            continue
        # Перегруз: линии на щите, у каждой — свой автомат того же номинала (вопрос)
        by_id = {p.id: p for p in points}
        for k, line in enumerate(lines, 1):
            pts = [by_id[ld.point] for ld in line]
            out.append(
                replace(
                    base,
                    group=g if k == 1 else f"{g}.{k}",
                    kind=_kind(pts, line, section),
                    purpose=composed_purpose(pts, rooms, lang)
                    if k > 1 or purpose is None
                    else base.purpose,
                    purpose_assumed=k > 1 or purpose is None,
                    loads=tuple(line),
                    split_of=g,
                    breaker=replace(breaker, assumed=breaker.assumed or k > 1),
                )
            )
    return out
