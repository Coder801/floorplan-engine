"""Loads and panel groups: point power (`power`, or a typical value by kind and note, marked
"*" as an assumption), group load and current, group breaker (from the model or by kind:
lighting 10 A, sockets 16 A, heavy loads by current, no more than the cable can carry), an
overloaded group is split into lines on the panel (QF8 → QF8, QF8.2). Supply 230 V, single or
three phases (`panel.phases`); on three phases one appliance from THREE_PHASE_W (a cooktop, an
electric boiler) goes on all three, its current is per phase, its cable five cores; which phase
the other groups take is electrical/phases.py."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from floorplan_engine.electrical.groups import (
    LIGHT,
    LOW,
    composed_purpose,
    group_key,
    tell_apart,
)
from floorplan_engine.electrical.master import master_on
from floorplan_engine.electrical.panel_text import text
from floorplan_engine.model.schema import Electrical, ElectricalPoint, PanelScheme, Plan, PointType
from floorplan_engine.model.texts import Language, tr

VOLTAGE = 230.0
COS_PHI = 1.0  # power factor: a flat is mostly resistive load (assumption)
RATINGS = (6, 10, 16, 20, 25, 32, 40, 50, 63)  # breaker rating series, A
LIGHT_A = 10
SOCKETS_A = 16
HEAVY_W = 2000.0  # from this power a load is heavy and gets its own line
THREE_PHASE_W = 5000.0  # from this power one appliance goes on three phases, if the flat has them
SOCKET_POST_W = 100.0  # design power of a socket post without a note (assumption)
OUTLET_W = 1000.0  # appliance output without a note (assumption)
# Cross-section, mm² → (recommended, maximum) breaker, A: copper, concealed wiring
CABLE_LIMITS: dict[float, tuple[int, int]] = {
    1.5: (10, 16),
    2.5: (16, 25),
    4.0: (25, 32),
    6.0: (32, 40),
    10.0: (40, 50),
    16.0: (63, 63),
}
# Typical point power by kind, W (assumption)
TYPE_W: dict[PointType, float] = {
    PointType.LIGHT: 100.0,
    PointType.PENDANT: 100.0,
    PointType.SCONCE: 40.0,
    PointType.DOWNLIGHT: 10.0,
    PointType.LED_OUTPUT: 50.0,
}
# Typical power by point note, W (assumption); first match wins
NOTE_W: tuple[tuple[re.Pattern[str], float], ...] = tuple(
    (re.compile(p, re.IGNORECASE), w)
    for p, w in (
        (r"варильн|варочн|індукц|индукц|плит", 7200.0),
        (r"духов", 3500.0),
        (r"бойлер|водонагр", 2000.0),
        (r"електрокот|электрокот", 9000.0),  # before "котел": a gas boiler needs only 200 W
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
# What the backup bus carries by default: lighting, kitchen sockets and these loads (by note)
RESERVE_NOTE = re.compile(r"холодил|котел|котёл|котл|роутер|насос|ворот|домофон", re.IGNORECASE)
KITCHEN = re.compile(r"кух", re.IGNORECASE)
# What the master switch never cuts by default (by note): food, heating, water, gates, security
# and the network; a group with any of them stays on as a whole (panel.master_off)
KEEP_ON = re.compile(
    r"холодил|морозил|котел|котёл|котл|роутер|насос|ворот|домофон|сигнализ|охран|"
    r"видеонаб|відеоспост|сервер|акваріум|аквариум|рекуперат",
    re.IGNORECASE,
)
# Wet zone by name when room.yaml has no wet: true (assumption)
WET_NAME = re.compile(r"санв|сануз|ванн|душ|пральн|прачеч|постироч", re.IGNORECASE)
# Inrush current: such a group gets curve C even in premium
MOTOR = re.compile(r"кондиц|кондиціон|насос|ворот|компрес", re.IGNORECASE)


def demand_factor(installed_kw: float) -> float:
    """Flat demand factor by installed power (assumption)."""
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
    """Nearest rating in the series not below the current and not below floor."""
    return next((r for r in RATINGS if r >= max(amps, floor)), RATINGS[-1])


def cable_for(amps_: float, cores: int = 3) -> str | None:
    """Smallest cross-section whose recommended breaker carries the current: "3x6"; three phases
    are five cores, "5x2.5"."""
    s = next((s for s, (rec, _) in sorted(CABLE_LIMITS.items()) if rec >= amps_), None)
    return f"{cores}x{s:g}" if s is not None else None


def phases_of(elec: Electrical) -> int:
    """Phases of the supply: unset is one (an assumption, panel_questions asks)."""
    return elec.panel.phases or 1


_SECTION = re.compile(r"(\d+)\s*[xх×*]\s*(\d+(?:[.,]\d+)?)", re.IGNORECASE)


def cable_section(mark: str) -> float | None:
    """Conductor cross-section from a type like "3x2.5", "ВВГнг 3х2,5"; None if unreadable."""
    m = _SECTION.search(mark)
    return float(m.group(2).replace(",", ".")) if m else None


_BREAKER = re.compile(r"^\s*([BCD])?\s*(\d+)", re.IGNORECASE)


def parse_breaker(text: str) -> tuple[str, int] | None:
    """Parse a rating: "C16" → ("C", 16); "16 А" → ("C", 16); None if unreadable."""
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
    """Load: a model point with its power."""

    point: str  # point id
    room: str  # room name
    title: str
    count: int
    power: float  # W, for the whole point
    assumed: bool  # typical power, not from the source

    @property
    def heavy(self) -> bool:
        return self.power >= HEAVY_W

    @property
    def keep_on(self) -> bool:
        """The master switch leaves it on: fridge, boiler, router… (KEEP_ON, by the note)."""
        return bool(KEEP_ON.search(self.title))


@dataclass(frozen=True)
class Breaker:
    curve: str
    rating: int
    assumed: bool  # chosen by code, not from the model

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
    cable: str  # group cable types, comma-separated
    section: float | None  # smallest cross-section
    breaker: Breaker
    rcd: str | None  # "30 мА": RCBO or behind an RCD
    wet: bool
    reserved: bool
    split_of: str | None = None  # line of an overloaded group split on the panel
    phase: str | None = None  # L1, L2, L3 or 3P on a three-phase panel (phases.py); None on one
    master: bool = False  # cut by the master switch (behind its contactor)

    @property
    def three_phase(self) -> bool:
        return self.phase == "3P"

    @property
    def power(self) -> float:
        return sum(ld.power for ld in self.loads)

    @property
    def current(self) -> float:
        """Design current; on three phases per phase."""
        return current(self.power) / (3 if self.three_phase else 1)

    @property
    def assumed(self) -> bool:
        return any(ld.assumed for ld in self.loads)


def point_load(p: ElectricalPoint, rooms: dict[str, str], language: Language) -> Load | None:
    """Load for a point; None for a switch without a note and for low-voltage."""
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


def is_three_phase(elec: Electrical, group: str, loads: Sequence[Load]) -> bool:
    """A group on all three phases: only with a three-phase supply; the phase of the group in the
    model (3P), or one appliance of THREE_PHASE_W and more."""
    if phases_of(elec) != 3:
        return False
    info = elec.groups.get(group.split(".")[0])
    if info is not None and info.phase is not None:
        return info.phase == "3P"
    return len(loads) == 1 and loads[0].power >= THREE_PHASE_W


def heavy_cable(elec: Electrical, group: str, points: Sequence[ElectricalPoint]) -> str | None:
    """Cable for a group with a heavy load and no type in the model, to match the breaker the
    code picks for it (assumption): on three phases five cores and the current per phase; None
    without a heavy load."""
    loads = [ld for p in points if (ld := point_load(p, {}, "ru")) is not None]
    if not any(ld.heavy for ld in loads):
        return None
    amps_ = current(sum(ld.power for ld in loads))
    if is_three_phase(elec, group, loads):
        return cable_for(rating_for(amps_ / 3), cores=5)
    return cable_for(rating_for(amps_))


def _kind(points: Sequence[ElectricalPoint], loads: Sequence[Load], section: float | None) -> Kind:
    if any(ld.heavy for ld in loads) or (section is not None and section >= 4):
        return Kind.HEAVY
    powered = {p.id for p in points} & {ld.point for ld in loads}
    if powered and all(p.type in LIGHT for p in points if p.id in powered):
        return Kind.LIGHT
    return Kind.SOCKETS


def _breaker(kind: Kind, amps_: float, section: float | None, curve: str) -> Breaker:
    """Breaker by group kind, but no larger than recommended for the cable."""
    rating = {Kind.LIGHT: LIGHT_A, Kind.SOCKETS: SOCKETS_A}.get(kind) or rating_for(amps_)
    if section is not None and section in CABLE_LIMITS:
        rating = min(rating, CABLE_LIMITS[section][0])
    return Breaker(curve, rating, True)


def split_loads(loads: Sequence[Load], capacity: float) -> list[list[Load]]:
    """Loads split into lines of at most capacity W: largest first, each into the first line with
    room left (order inside a line follows the model)."""
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
    """Sockets or outputs in a wet room: the group needs an RCD."""
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
    master, master_off = master_on(elec), set(elec.panel.master_off)
    out: list[PanelGroup] = []
    for g in sorted(names, key=group_key):
        points = [p for p in elec.points if p.group == g]
        if points and all(p.type in LOW for p in points):
            continue  # low-voltage: not in the panel
        loads = [ld for p in points if (ld := point_load(p, rooms, lang)) is not None]
        marks = sorted({c.cable for c in elec.cables if c.group == g})
        sections = [s for m in marks if (s := cable_section(m)) is not None]
        section = min(sections) if sections else None
        kind = _kind(points, loads, section)
        three = is_three_phase(elec, g, loads)
        info = elec.groups.get(g)
        parsed = parse_breaker(info.breaker) if info is not None and info.breaker else None
        motor = any(p.note and MOTOR.search(p.note) for p in points)
        curve = "B" if scheme == "premium" and not motor else "C"
        breaker = (
            Breaker(parsed[0], parsed[1], False)
            if parsed is not None
            else _breaker(
                kind, current(sum(ld.power for ld in loads)) / (3 if three else 1), section, curve
            )
        )
        wet = _wet_group(points, wet_rooms)
        rcd = info.rcd if info is not None and info.rcd else None
        if rcd is None and (wet or scheme == "premium"):
            rcd = "30 мА"
        purpose = info.name if info is not None and info.name else None
        kitchen = kind is Kind.SOCKETS and any(
            KITCHEN.search(rooms.get(p.room, "")) for p in points
        )
        # A three-phase appliance is never on the backup bus: the backup source has one phase
        reserved = (
            backup
            and not three
            and (
                g in reserve
                if reserve
                else (
                    kind is Kind.LIGHT
                    or kitchen
                    or any(p.note and RESERVE_NOTE.search(p.note) for p in points)
                )
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
            phase="3P" if three else None,
            master=master
            and (
                g in master_off
                if master_off
                else not any(p.note and KEEP_ON.search(p.note) for p in points)
            ),
        )
        lines = split_loads(loads, breaker.rating * VOLTAGE * COS_PHI * (3 if three else 1))
        if base.current <= breaker.rating or len(lines) < 2:
            out.append(base)
            continue
        # Overload: lines on the panel, each with its own breaker of the same rating (a question)
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
    by_id = {p.id: p for p in elec.points}
    told = tell_apart(
        [(g.purpose, g.purpose_assumed, [by_id[ld.point] for ld in g.loads]) for g in out]
    )
    return [replace(g, purpose=t) for g, t in zip(out, told, strict=True)]
