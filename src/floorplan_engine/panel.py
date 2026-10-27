"""Щит в лицо: потребители по группам, нагрузка, автоматы, состав щита и слабые места.

Только расчёт по модели, без рисования (рисует draw_panel.py). Однофазный ввод 230 В.

- Потребители — точки electrical.yaml с мощностью: `power` точки из источника, иначе типовая
  по виду точки и пометке («духовка» — 3,5 кВт); типовая — допущение («*»).
- Автомат группы — из `groups` модели; нет — по виду группы: свет 10 А, розетки 16 А,
  тяжёлые потребители — по току, но не больше, чем держит кабель группы.
- Состав щита — по схеме (`panel.scheme`, решение 2026-10-27): economy — ввод и группы,
  мокрые зоны под одним УЗО, резерв — ручным переключателем; standard — плюс реле напряжения,
  мокрые зоны дифавтоматами, резерв через АВР; premium — плюс УЗИП, все группы
  дифавтоматами, характеристика B (кроме моторной нагрузки — C).
- Резерв (`panel.backup`) — от схемы отдельно: не задан — гибридный инвертор допущением
  и вопрос. Резервная шина — свет, холодильник, роутер, котёл, насос, ворота, розетки кухни.
- Перегруженная группа делится на щите на линии (QF8 → QF8, QF8.2) — и вопрос: перенести
  второй кабель в electrical.yaml. Один прибор больше автомата — вопрос о кабеле.
- Слабые места — автомат больше, чем держит кабель, тяжёлый потребитель в общей группе,
  расчётный ток выше вводного, нет селективности, резерв меньше нагрузки.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from floorplan_engine.draw_electrical import group_key
from floorplan_engine.groups import LIGHT, LOW, composed_purpose
from floorplan_engine.intake import QSeverity, Question, Stage
from floorplan_engine.panel_catalog import CatalogModel, DeviceKind, model_for
from floorplan_engine.schema import Electrical, ElectricalPoint, PanelScheme, Plan, PointType
from floorplan_engine.texts import Language, tr

VOLTAGE = 230.0
COS_PHI = 1.0  # коэффициент мощности: в квартире преобладает активная нагрузка (допущение)
RATINGS = (6, 10, 16, 20, 25, 32, 40, 50, 63)  # ряд номиналов автоматов, А
LIGHT_A = 10
SOCKETS_A = 16
HEAVY_W = 2000.0  # от этой мощности потребитель — тяжёлый: своя линия
SOCKET_POST_W = 100.0  # расчётная мощность поста розетки без пометки (допущение)
OUTLET_W = 1000.0  # вывод к технике без пометки (допущение)
INPUT_A = 63  # вводной автомат, если в модели его нет (допущение, решение 2026-10-27)
RCD_A = 40  # УЗО на мокрые зоны в economy
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


TEXT: dict[str, dict[str, str]] = {
    "socket_generic": {"ru": "Розетка", "uk": "Розетка"},
    "outlet_generic": {"ru": "Вывод к технике", "uk": "Вивід до техніки"},
    "input": {"ru": "Вводной автомат", "uk": "Вступний автомат"},
    "relay": {"ru": "Реле напряжения", "uk": "Реле напруги"},
    "spd": {"ru": "УЗИП (защита от перенапряжения)", "uk": "ПЗІП (захист від перенапруги)"},
    "rcd": {"ru": "УЗО", "uk": "ПЗВ"},
    "rcd_wet": {"ru": "УЗО мокрых зон", "uk": "ПЗВ мокрих зон"},
    "changeover": {
        "ru": "Перекидной рубильник I-0-II",
        "uk": "Перекидний рубильник I-0-II",
    },
    "bypass": {
        "ru": "Обходной переключатель: сеть / инвертор",
        "uk": "Обвідний перемикач: мережа / інвертор",
    },
    "ats": {"ru": "АВР (автоматический ввод резерва)", "uk": "АВР (автоматичне введення резерву)"},
    "inverter_feed": {"ru": "Питание инвертора (AC IN)", "uk": "Живлення інвертора (AC IN)"},
    "inverter": {"ru": "Инвертор с АКБ", "uk": "Інвертор з АКБ"},
    "plug": {"ru": "Силовая вилка генератора", "uk": "Силова вилка генератора"},
    "title": {
        "ru": "Щит {name}: 1 фаза, 230 В — {scheme}",
        "uk": "Щит {name}: 1 фаза, 230 В — {scheme}",
    },
    "economy": {"ru": "эконом", "uk": "економ"},
    "standard": {"ru": "обычный", "uk": "звичайний"},
    "premium": {"ru": "премиум", "uk": "преміум"},
    "with_inverter": {"ru": "резерв: инвертор", "uk": "резерв: інвертор"},
    "with_plug": {"ru": "резерв: генератор", "uk": "резерв: генератор"},
    "grid": {"ru": "Ввод от сети 230 В", "uk": "Введення від мережі 230 В"},
    "reserve_bus": {"ru": "Резервная шина", "uk": "Резервна шина"},
    "main_bus": {"ru": "Сеть", "uk": "Мережа"},
    # Слабые места
    "w_overload": {
        "ru": "{g}: расчётный ток {i} А больше автомата {r} А — разделите группу",
        "uk": "{g}: розрахунковий струм {i} А більший за автомат {r} А — розділіть групу",
    },
    "w_single": {
        "ru": "{g}: {what} — ток {i} А больше автомата {r} А: нужен кабель сечением больше "
        "и автомат {need} А (или мощность прибора ниже)",
        "uk": "{g}: {what} — струм {i} А більший за автомат {r} А: потрібен кабель більшого "
        "перерізу і автомат {need} А (або потужність приладу нижча)",
    },
    "w_split": {
        "ru": "{g}: перегруз — на щите разделена на {n} линии; второй кабель — в вопросе",
        "uk": "{g}: перевантаження — на щиті розділена на {n} лінії; другий кабель — у питанні",
    },
    "w_cable": {
        "ru": "{g}: автомат {r} А не защищает кабель {c} (не больше {m} А)",
        "uk": "{g}: автомат {r} А не захищає кабель {c} (не більше {m} А)",
    },
    "w_cable_soft": {
        "ru": "{g}: для кабеля {c} обычно автомат {m} А, стоит {r} А",
        "uk": "{g}: для кабелю {c} зазвичай автомат {m} А, стоїть {r} А",
    },
    "w_heavy_shared": {
        "ru": "{g}: {what} ({p} кВт) в общей группе — нужна своя линия",
        "uk": "{g}: {what} ({p} кВт) у спільній групі — потрібна окрема лінія",
    },
    "w_no_cable": {
        "ru": "{g}: нет марки кабеля — автомат подобран без проверки по сечению",
        "uk": "{g}: немає марки кабелю — автомат підібрано без перевірки за перерізом",
    },
    "w_wet": {
        "ru": "{g}: мокрая зона без УЗО 30 мА в модели — на схеме поставлено УЗО",
        "uk": "{g}: мокра зона без ПЗВ 30 мА в моделі — на схемі поставлено ПЗВ",
    },
    "w_total": {
        "ru": "Расчётный ток квартиры {i} А больше вводного автомата {r} А",
        "uk": "Розрахунковий струм квартири {i} А більший за вступний автомат {r} А",
    },
    "w_power": {
        "ru": "Расчётная мощность {p} кВт больше выделенной {lim} кВт",
        "uk": "Розрахункова потужність {p} кВт більша за виділену {lim} кВт",
    },
    "w_select": {
        "ru": "{g}: автомат {r} А не меньше вводного {i} А — нет селективности",
        "uk": "{g}: автомат {r} А не менший за вступний {i} А — немає селективності",
    },
    "w_no_relay": {
        "ru": "Нет реле напряжения: скачок в сети повредит технику",
        "uk": "Немає реле напруги: стрибок у мережі пошкодить техніку",
    },
    "w_backup": {
        "ru": "Резервная шина {p} кВт больше мощности резерва {lim} кВт",
        "uk": "Резервна шина {p} кВт більша за потужність резерву {lim} кВт",
    },
    "w_backup_unknown": {
        "ru": "Мощность инвертора или генератора не задана (panel.backup_power) — "
        "резервная шина {p} кВт не проверена",
        "uk": "Потужність інвертора або генератора не задана (panel.backup_power) — "
        "резервна шина {p} кВт не перевірена",
    },
    "w_plug": {
        "ru": "Генератор — только через силовую вилку-ввод и перекидной рубильник; кабель "
        "«вилка-вилка» в розетку запрещён: на штырях напряжение",
        "uk": "Генератор — лише через силову вилку-введення і перекидний рубильник; кабель "
        "«вилка-вилка» у розетку заборонений: на штирях напруга",
    },
    "w_input_assumed": {
        "ru": "Вводной автомат {r} А — допущение: уточните по техусловиям (panel.input)",
        "uk": "Вступний автомат {r} А — припущення: уточніть за техумовами (panel.input)",
    },
}


def text(key: str, language: Language, **kw: object) -> str:
    return TEXT[key][language].format(**kw)


def kw(watts: float) -> str:
    """Вт → «1,25» кВт."""
    return f"{watts / 1000:.2f}".replace(".", ",")


def amps(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


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


@dataclass(frozen=True)
class Device:
    """Аппарат на DIN-рейке."""

    id: str  # QS1, KV1, FV1, QD1, SA1, KM1, QF4
    kind: DeviceKind
    label: str  # что написано на аппарате: «C16», «40 А 30 мА»
    title: str  # что это
    group: str | None = None  # группа щита у автомата и дифавтомата
    feeds: tuple[str, ...] = ()  # группы под УЗО
    assumed: bool = False
    reserve: bool = False  # на резервной шине
    brand: str = "generic"  # бренд щита: модель — из каталога (panel_catalog)

    @property
    def model(self) -> CatalogModel:
        return model_for(self.kind, self.brand)

    @property
    def modules(self) -> int:
        return self.model.modules

    @property
    def key(self) -> str:
        """Объект чертежа: группа — «device:QF4», остальное — «device:QS1»."""
        return f"device:{self.group or self.id}"


@dataclass(frozen=True)
class Warning:
    severity: str  # major | minor
    text: dict[str, str]  # по языкам: ru для отчёта, язык проекта — для листа
    group: str | None = None


@dataclass(frozen=True)
class BoardPanel:
    """Щит целиком: группы, аппараты по порядку, итоги и слабые места."""

    scheme: PanelScheme
    backup: str | None  # inverter | plug; None — без резерва
    backup_assumed: bool  # резерв не задан — инвертор допущением
    groups: tuple[PanelGroup, ...]
    devices: tuple[Device, ...]
    input: Breaker
    installed: float  # Вт
    demand: float  # коэффициент спроса
    warnings: tuple[Warning, ...]
    power_limit: float | None  # выделенная мощность, кВт
    backup_power: float | None

    @property
    def calculated(self) -> float:
        return self.installed * self.demand

    @property
    def modules(self) -> int:
        return sum(d.modules for d in self.devices)

    @property
    def reserve_power(self) -> float:
        return sum(g.power for g in self.groups if g.reserved)


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


MODE_SCHEME: dict[str, PanelScheme] = {
    "economy": "economy",
    "standard": "standard",
    "proper": "premium",
}


def scheme_of(elec: Electrical) -> PanelScheme:
    if elec.panel.scheme is not None:
        return elec.panel.scheme
    return MODE_SCHEME[elec.mode]


def backup_of(elec: Electrical) -> tuple[str | None, bool]:
    """Резерв и допущение ли он: не задан — гибридный инвертор (решение 2026-10-27)."""
    b = elec.panel.backup
    if b is None:
        return "inverter", True
    return (None if b == "none" else b), False


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


def _group_devices(
    groups: Sequence[PanelGroup], scheme: PanelScheme, reserve: bool, lang: Language, rcds: int
) -> list[Device]:
    """Аппараты групп одной шины: в economy мокрые — под общим УЗО в конце, в proper
    свет — автоматами, остальное — дифавтоматами."""
    out: list[Device] = []
    under_rcd: list[PanelGroup] = []
    for g in groups:
        if scheme == "economy" and g.rcd is not None:
            under_rcd.append(g)
            continue
        kind = DeviceKind.DIFF if g.rcd is not None else DeviceKind.BREAKER
        label = g.breaker.label + (f" {g.rcd}" if g.rcd else "")
        out.append(Device(g.group, kind, label, g.purpose, g.group, (), g.breaker.assumed, reserve))
    if under_rcd:
        name = f"QD{rcds + 1}"
        rating = max(RCD_A, max(g.breaker.rating for g in under_rcd))
        rcd_label = f"{rating_for(rating, RCD_A)} А 30 мА"
        title = text("rcd_wet", lang)
        feeds = tuple(g.group for g in under_rcd)
        out.append(Device(name, DeviceKind.RCD, rcd_label, title, None, feeds, True, reserve))
        for g in under_rcd:
            out.append(
                Device(
                    g.group,
                    DeviceKind.BREAKER,
                    g.breaker.label,
                    g.purpose,
                    g.group,
                    (),
                    g.breaker.assumed,
                    reserve,
                )
            )
    return out


def build_panel(plan: Plan, elec: Electrical) -> BoardPanel | None:
    """Щит по модели; групп нет — None."""
    lang = plan.language
    setup = elec.panel
    scheme = scheme_of(elec)
    backup, backup_assumed = backup_of(elec)
    groups = panel_groups(plan, elec, scheme, backup is not None)
    if not groups:
        return None
    installed = sum(g.power for g in groups)
    demand = demand_factor(installed / 1000)
    inp = Breaker("C", setup.input or INPUT_A, setup.input is None)
    relay = setup.voltage_relay if setup.voltage_relay is not None else scheme != "economy"
    spd = setup.spd if setup.spd is not None else scheme == "premium"
    ats = setup.ats if setup.ats is not None else scheme != "economy"

    devices = [Device("QS1", DeviceKind.INPUT, f"{inp.label} 2P", text("input", lang))]
    if relay:
        label = f"{inp.rating} А"
        devices.append(Device("KV1", DeviceKind.RELAY, label, text("relay", lang)))
    if spd:
        devices.append(Device("FV1", DeviceKind.SPD, "T2 20 кА", text("spd", lang)))
    main = [g for g in groups if not g.reserved]
    reserved = [g for g in groups if g.reserved]
    devices += _group_devices(main, scheme, False, lang, 0)
    if backup is not None:
        if backup == "inverter":
            devices.append(
                Device("QS2", DeviceKind.FEED, f"C{SOCKETS_A * 2} 2P", text("inverter_feed", lang))
            )
        if ats:
            devices.append(Device("KM1", DeviceKind.ATS, "АВР", text("ats", lang), reserve=True))
        else:
            key = "bypass" if backup == "inverter" else "changeover"
            devices.append(
                Device("SA1", DeviceKind.CHANGEOVER, "I-0-II", text(key, lang), reserve=True)
            )
        rcds = sum(1 for d in devices if d.kind is DeviceKind.RCD)
        devices += _group_devices(reserved, scheme, True, lang, rcds)

    devices = [replace(d, brand=setup.brand) for d in devices]
    panel = BoardPanel(
        scheme,
        backup,
        backup_assumed,
        tuple(groups),
        tuple(devices),
        inp,
        installed,
        demand,
        (),
        setup.power,
        setup.backup_power,
    )
    return replace(panel, warnings=tuple(weak_spots(panel, relay)))


def _both(key: str, **kw_: object) -> dict[str, str]:
    return {lang: text(key, lang, **kw_) for lang in ("ru", "uk")}


def weak_spots(panel: BoardPanel, relay: bool) -> list[Warning]:
    """Слабые места щита: сначала по группам, потом по вводу и резерву."""
    out: list[Warning] = []
    for g in panel.groups:
        b = g.breaker
        if g.split_of is not None and g.group == g.split_of:
            msg = _both(
                "w_split", g=g.group, n=sum(1 for x in panel.groups if x.split_of == g.group)
            )
            out.append(Warning("major", msg, g.group))
        if g.current > b.rating and len(g.loads) == 1:
            ld, i = g.loads[0], amps(g.current)
            need = rating_for(g.current)
            msg = _both("w_single", g=g.group, what=ld.title, i=i, r=b.rating, need=need)
            out.append(Warning("major", msg, g.group))
        elif g.current > b.rating:
            msg = _both("w_overload", g=g.group, i=amps(g.current), r=b.rating)
            out.append(Warning("major", msg, g.group))
        if g.section is None:
            out.append(Warning("minor", _both("w_no_cable", g=g.group), g.group))
        elif g.section in CABLE_LIMITS:
            rec, top = CABLE_LIMITS[g.section]
            c = g.cable
            if b.rating > top:
                out.append(
                    Warning("major", _both("w_cable", g=g.group, r=b.rating, c=c, m=top), g.group)
                )
            elif b.rating > rec:
                out.append(
                    Warning(
                        "minor", _both("w_cable_soft", g=g.group, r=b.rating, c=c, m=rec), g.group
                    )
                )
        heavy = [ld for ld in g.loads if ld.heavy]
        if heavy and len(g.loads) > 1:
            for ld in heavy:
                out.append(
                    Warning(
                        "major",
                        _both("w_heavy_shared", g=g.group, what=ld.title, p=kw(ld.power)),
                        g.group,
                    )
                )
        if b.rating >= panel.input.rating:
            out.append(
                Warning(
                    "major", _both("w_select", g=g.group, r=b.rating, i=panel.input.rating), g.group
                )
            )
    calc_a = current(panel.calculated)
    if calc_a > panel.input.rating:
        out.append(Warning("major", _both("w_total", i=amps(calc_a), r=panel.input.rating)))
    if panel.power_limit is not None and panel.calculated / 1000 > panel.power_limit:
        out.append(
            Warning("major", _both("w_power", p=kw(panel.calculated), lim=f"{panel.power_limit:g}"))
        )
    if panel.input.assumed:
        out.append(Warning("minor", _both("w_input_assumed", r=panel.input.rating)))
    if not relay:
        out.append(Warning("minor", _both("w_no_relay")))
    if panel.backup is not None:
        res = panel.reserve_power
        if panel.backup_power is None:
            out.append(Warning("minor", _both("w_backup_unknown", p=kw(res))))
        elif res / 1000 > panel.backup_power:
            out.append(
                Warning("major", _both("w_backup", p=kw(res), lim=f"{panel.backup_power:g}"))
            )
        if panel.backup == "plug":
            out.append(Warning("minor", _both("w_plug")))
    return out


def ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def row_modules(devices: Sequence[Device]) -> int:
    """Модулей в рейке: 12, если хватает четырёх реек, иначе 18 или 24."""
    total = sum(d.modules for d in devices)
    return next((n for n in (12, 18, 24) if ceil_div(total, n) <= 4), 24)


def din_rows(devices: Sequence[Device], per_row: int | None = None) -> list[list[Device]]:
    """Аппараты по DIN-рейкам по порядку; аппарат не делится между рейками, резервная
    шина начинается с новой рейки."""
    if per_row is None:
        per_row = row_modules(devices)
    rows: list[list[Device]] = [[]]
    used = 0
    reserve = False
    for d in devices:
        fresh = d.reserve and not reserve  # резервная шина — со своей рейки
        reserve = reserve or d.reserve
        if (used + d.modules > per_row or fresh) and rows[-1]:
            rows.append([])
            used = 0
        rows[-1].append(d)
        used += d.modules
    return rows


def write_loads(panel: BoardPanel, path: Path) -> Path:
    """Роспись потребителей в CSV: группа, аппарат, точка, помещение, потребитель, мощность
    и откуда она (source — из модели, typical — типовая, допущение)."""
    devices = {d.group: d for d in panel.devices if d.group}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "group",
                "device",
                "cable",
                "point",
                "room",
                "consumer",
                "count",
                "watts",
                "power_from",
            ]
        )
        for g in panel.groups:
            label = devices[g.group].label if g.group in devices else g.breaker.label
            for ld in g.loads:
                w.writerow(
                    [
                        g.group,
                        label,
                        g.cable,
                        ld.point,
                        ld.room,
                        ld.title,
                        ld.count,
                        f"{ld.power:g}",
                        "typical" if ld.assumed else "source",
                    ]
                )
    return path


EXTERNAL = {"inverter": "U1", "plug": "XP1"}  # аппарат резерва вне щита


def panel_data(
    panel: BoardPanel, colors: dict[str, int], name: str, language: Language
) -> dict[str, object]:
    """Щит для просмотра (ключ `panel` страницы .epd): аппараты по порядку с моделью
    из каталога, группы с нагрузкой, итоги и слабые места — на языке проекта. Раскладку
    по рейкам и рисунок делает просмотр."""
    groups = {}
    for g in panel.groups:
        groups[g.group] = {
            "purpose": g.purpose,
            "purpose_assumed": g.purpose_assumed,
            "cable": g.cable,
            "power": round(g.power),
            "current": round(g.current, 1),
            "assumed": g.assumed,
            "loads": len(g.loads),
            "color": f"#{c:06x}" if (c := color_of(g.group, colors)) is not None else None,
            "split_of": g.split_of,
        }
    devices = []
    for d in panel.devices:
        item: dict[str, object] = {
            "id": d.id,
            "key": d.key,
            "kind": d.kind.value,
            "label": d.label,
            "title": d.title,
            "model": d.model.as_dict(),
        }
        if d.group is not None:
            item["group"] = d.group
        if d.feeds:
            item["feeds"] = list(d.feeds)
        if d.assumed:
            item["assumed"] = True
        if d.reserve:
            item["reserve"] = True
        devices.append(item)
    calc = panel.calculated
    out: dict[str, object] = {
        "name": name,
        "phases": 1,
        "scheme": panel.scheme,
        "input": {"label": panel.input.label, "assumed": panel.input.assumed},
        "devices": devices,
        "groups": groups,
        "totals": {
            "installed": round(panel.installed),
            "demand": panel.demand,
            "calculated": round(calc),
            "current": round(current(calc), 1),
            "modules": panel.modules,
        },
        "warnings": [
            {
                "severity": w.severity,
                "text": w.text[language],
                **({"group": w.group} if w.group else {}),
            }
            for w in panel.warnings
        ],
        "texts": {
            "title": text("title", language, name=name, scheme=scheme_title(panel, language)),
            "grid": text("grid", language),
            "reserve": text("reserve_bus", language),
        },
    }
    if panel.backup is not None:
        out["external"] = {
            "id": EXTERNAL[panel.backup],
            "kind": panel.backup,
            "title": text(panel.backup, language),
            "to": "KM1" if any(d.id == "KM1" for d in panel.devices) else "SA1",
            "feed": "QS2" if panel.backup == "inverter" else None,
        }
    return out


def scheme_title(panel: BoardPanel, language: Language) -> str:
    """«преміум, резерв: інвертор*»: схема и резерв, допущение — «*»."""
    out = text(panel.scheme, language)
    if panel.backup is not None:
        out += ", " + text(f"with_{panel.backup}", language) + ("*" if panel.backup_assumed else "")
    return out


def color_of(group: str | None, colors: dict[str, int]) -> int | None:
    """Цвет группы; линия разделённой группы (QF8.2) — цветом группы (QF8)."""
    if group is None:
        return None
    return colors.get(group, colors.get(group.split(".")[0]))


# --- Вопросы по щиту -----------------------------------------------------------

AUTO_PREFIX = "panel_"  # id вопросов, которые составляет код; в intake.yaml такие не пишутся
BACKUP_OPTIONS = ["none", "inverter", "plug"]


def cable_for(amps_: float) -> str | None:
    """Наименьшее сечение, для которого рекомендуемый автомат держит ток: «3x6»."""
    s = next((s for s, (rec, _) in sorted(CABLE_LIMITS.items()) if rec >= amps_), None)
    return f"3x{s:g}" if s is not None else None


def panel_questions(elec: Electrical, panel: BoardPanel) -> list[Question]:
    """Вопросы щита по расчёту: резерв и ввод, если не заданы; разделённые группы;
    прибор больше автомата своей группы; состав резервной шины по умолчанию."""
    out: list[Question] = []
    setup = elec.panel
    if setup.backup is None:
        out.append(
            Question(
                id=f"{AUTO_PREFIX}backup",
                stage=Stage.PANEL,
                target="panel.backup",
                answer="choice",
                options=BACKUP_OPTIONS,
                assumption="inverter",
                text="Нужен ли резерв питания? Сейчас — гибридный инвертор с АКБ (допущение): "
                "none — без резерва, inverter — инвертор, plug — генератор через силовую вилку",
            )
        )
    if setup.input is None:
        out.append(
            Question(
                id=f"{AUTO_PREFIX}input",
                stage=Stage.PANEL,
                target="panel.input",
                answer="value",
                unit="А",
                assumption=float(panel.input.rating),
                text=f"Вводной автомат по техусловиям? Сейчас {panel.input.rating} А "
                f"(допущение); расчётный ток квартиры {amps(current(panel.calculated))} А",
            )
        )
    if panel.backup is not None and not setup.reserve:
        names = ", ".join(g.group for g in panel.groups if g.reserved) or "—"
        out.append(
            Question(
                id=f"{AUTO_PREFIX}reserve",
                stage=Stage.PANEL,
                severity=QSeverity.MINOR,
                text=f"Что держать на резерве? Сейчас: {names} — свет, холодильник, роутер, "
                "котёл, насос, ворота, розетки кухни (допущение). Список групп — panel.reserve",
            )
        )
    for g in panel.groups:
        if g.split_of == g.group:
            lines = [x for x in panel.groups if x.split_of == g.group]
            parts = "; ".join(
                f"{x.group} — {', '.join(ld.title for ld in x.loads)} ({kw(x.power)} кВт)"
                for x in lines
            )
            total = current(sum(x.power for x in lines))
            protect = " Мокрая зона — каждая линия через дифавтомат 30 мА." if g.wet else ""
            out.append(
                Question(
                    id=f"{AUTO_PREFIX}split_{g.group}",
                    stage=Stage.PANEL,
                    severity=QSeverity.MAJOR,
                    text=f"{g.group}: {amps(total)} А на автомате {g.breaker.rating} А — на щите "
                    f"разделена на {len(lines)} линии: {parts}.{protect} Подтвердите — "
                    "второй кабель от щита перенесём в electrical.yaml",
                )
            )
        if g.current > g.breaker.rating and len(g.loads) == 1:
            ld = g.loads[0]
            need = rating_for(g.current)
            cable = cable_for(g.current) or "больше"
            out.append(
                Question(
                    id=f"{AUTO_PREFIX}cable_{g.group}",
                    stage=Stage.PANEL,
                    severity=QSeverity.MAJOR,
                    text=f"{g.group}: {ld.title} {kw(ld.power)} кВт — {amps(g.current)} А, "
                    f"а кабель {g.cable or '—'} и автомат {g.breaker.rating} А. Нужен кабель "
                    f"{cable} и автомат {need} А — или укажите мощность прибора (power у точки)",
                )
            )
    return out
