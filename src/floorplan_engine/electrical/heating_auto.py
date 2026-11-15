"""Floor heating zones built by code from the controllers (decision 2026-11-15, the priority of
floor heating: the design's zones → zones by the controllers → a question).

A `thermostat` point that no `floor_heating` entry names gets a zone of its own (`auto: true`, an
assumption on the sheet and in the report):

1. `heating_rooms.<id>` is set (the answer to the question `heating_<id>`, or by hand) — there:
   a room id, «room:zone» or `none` (no floor heating for it).
2. The point's `note` names a room or a zone (`Room.name`, `Zone.name`): words of three letters
   and more, without the general ones (STOP_WORDS); a note word fits a name word when they share
   a prefix of PREFIX letters (or the shorter word whole: «кухня» — «кухні» — «кухне»). The
   candidates with the most fitting words win; a zone beats its own room. One candidate — there.
3. Nothing in the note — the room the controller hangs in.
4. Not built, but a question built by code (`heating_<id>`, the studio's, choice of rooms and
   zones and `none`): several candidates fit the note equally; the room has zones and the note
   names none of them — whether the note names that room (its name wins over the zones', «ТП
   кухня-гостиная» in a room «Кухня-гостиная» with zones «Кухня» and «Гостиная») or names
   nothing and the controller hangs there; the floor is already heated by another zone (a
   written one or an auto one before it in electrical.yaml order; the options are then the
   places no zone heats yet).

An area in the note («зона 6,35 м²») becomes the zone's `area` (the source): the check
compares it with the layout. Everything here is deterministic: the same model gives the same
zones and questions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from floorplan_engine.model.intake import Question, Stage
from floorplan_engine.model.schema import (
    Electrical,
    ElectricalPoint,
    FloorHeating,
    Plan,
    PointType,
)
from floorplan_engine.model.texts import tr

HEATING_PREFIX = "heating_"  # ids of the questions built here; never written in intake.yaml
HEATING_ROOMS = "heating_rooms"  # the Electrical field the answers go to
NONE = "none"
AUTO_ID = "auto_"  # zone id: auto_<controller id>
PREFIX = 4  # letters a note word and a name word must share
STOP_WORDS = frozenset(
    {
        "тп",
        "теплый",
        "тёплый",
        "теплий",
        "тепла",
        "теплая",
        "тёплая",
        "теплого",
        "тёплого",
        "теплої",
        "пол",
        "пола",
        "полу",
        "підлога",
        "підлоги",
        "підлозі",
        "регулятор",
        "терморегулятор",
        "термостат",
        "датчик",
        "зона",
        "зони",
        "зоны",
        "зоне",
        "зоні",
        "площа",
        "площадь",
        "кабель",
        "мат",
        "для",
        "над",
        "під",
        "под",
        "біля",
        "возле",
    }
)
AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:м²|м2|кв\.?\s*м)")


@dataclass(frozen=True)
class Place:
    """Where a zone lies: a room, or a zone of it."""

    room: str
    zone: str | None = None

    @property
    def key(self) -> str:
        return self.room if self.zone is None else f"{self.room}:{self.zone}"

    def overlaps(self, other: Place) -> bool:
        """The two places share floor: the same room, and one of them is the whole room or both
        are the same zone."""
        return self.room == other.room and (
            self.zone is None or other.zone is None or self.zone == other.zone
        )


def parse_place(plan: Plan, value: str) -> Place | None:
    """A `heating_rooms` value → its place; None for a room or zone the plan does not have."""
    room_id, _, zone = value.partition(":")
    room = next((r for r in plan.rooms if r.id == room_id), None)
    if room is None or (zone and zone not in {z.name for z in room.zones}):
        return None
    return Place(room_id, zone or None)


def _words(text: str) -> list[str]:
    plain = text.lower().replace("ё", "е").replace("'", "").replace("’", "").replace("ʼ", "")
    return [w for w in re.split(r"[^a-zа-яіїєґ]+", plain) if len(w) >= 3 and w not in STOP_WORDS]


def _fits(a: str, b: str) -> bool:
    n = min(PREFIX, len(a), len(b))
    return a[:n] == b[:n]


def note_places(plan: Plan, note: str) -> list[Place]:
    """Rooms and zones the note names, best first by the rule of the module docstring (all of
    the best equally); [] when it names none."""
    words = _words(note)
    if not words:
        return []
    scored: list[tuple[int, Place]] = []
    for room in plan.rooms:
        named = [
            (Place(room.id), room.name),
            *((Place(room.id, z.name), z.name) for z in room.zones),
        ]
        for place, name in named:
            score = sum(1 for w in _words(name) if any(_fits(w, n) for n in words))
            if score:
                scored.append((score, place))
    if not scored:
        return []
    best = max(s for s, _ in scored)
    top = [p for s, p in scored if s == best]
    zoned = {p.room for p in top if p.zone is not None}
    return [p for p in top if p.zone is not None or p.room not in zoned]


def note_area(note: str) -> float | None:
    """Area in the note («зона 6,35 м²»), m²; None without one."""
    found = AREA_RE.search(note)
    if found is None:
        return None
    value = float(found.group(1).replace(",", "."))
    return value if 0 < value <= 500 else None


@dataclass(frozen=True)
class AutoHeating:
    zones: tuple[FloorHeating, ...]  # auto zones, in point order
    questions: tuple[Question, ...]  # where code cannot tell: heating_<controller id>


def _label(plan: Plan, place: Place) -> str:
    room = next(r for r in plan.rooms if r.id == place.room)
    return room.name if place.zone is None else f"{room.name} — {place.zone}"


def _all_places(plan: Plan) -> list[Place]:
    return [p for r in plan.rooms for p in (Place(r.id), *(Place(r.id, z.name) for z in r.zones))]


def _question(
    plan: Plan, pt: ElectricalPoint, kind: str, places: list[Place], **values: str
) -> Question:
    lang = plan.language
    options = [p.key for p in places] + [NONE]
    labels = {p.key: _label(plan, p) for p in places} | {NONE: tr("fh_q_none", lang)}
    return Question(
        id=f"{HEATING_PREFIX}{pt.id}",
        stage=Stage.ELECTRICAL,
        target=f"{HEATING_ROOMS}.{pt.id}",
        answer="choice",
        options=options,
        option_labels=labels,
        assumption=NONE,
        text=tr(f"fh_q_{kind}", lang, reg=pt.id, note=pt.note or "", **values),
    )


def auto_heating(plan: Plan, elec: Electrical) -> AutoHeating:
    """Auto zones and questions for the controllers no floor_heating entry names."""
    named = {fh.thermostat for fh in elec.floor_heating}
    taken = [
        (Place(fh.room, fh.zone), fh.id)
        for fh in elec.floor_heating
        if any(r.id == fh.room for r in plan.rooms)
    ]
    ids = {fh.id for fh in elec.floor_heating} | {p.id for p in elec.points}
    rooms = {r.id: r for r in plan.rooms}
    zones: list[FloorHeating] = []
    questions: list[Question] = []
    for pt in elec.points:
        if pt.type is not PointType.THERMOSTAT or pt.id in named:
            continue
        chosen = elec.heating_rooms.get(pt.id)
        place: Place | None
        if chosen is not None:
            place = None if chosen == NONE else parse_place(plan, chosen)
            if place is None:
                continue  # none, or a wrong value: the check reports it
        else:
            found = note_places(plan, pt.note or "")
            room = rooms.get(pt.room)
            if len(found) > 1:
                questions.append(_question(plan, pt, "many", found))
                continue
            if found and found[0].zone is None and rooms[found[0].room].zones:
                # The note names a room that has zones, but none of them: which one is heated
                whole = rooms[found[0].room]
                places = [Place(whole.id, z.name) for z in whole.zones]
                questions.append(_question(plan, pt, "named", places, room=whole.name))
                continue
            if found:
                place = found[0]
            elif room is None:
                continue  # the check reports the point's room
            elif room.zones:
                places = [Place(room.id, z.name) for z in room.zones]
                questions.append(_question(plan, pt, "zones", places, room=room.name))
                continue
            else:
                place = Place(room.id)
            other = next((zid for p, zid in taken if p.overlaps(place)), None)
            if other is not None:
                free = [p for p in _all_places(plan) if not any(t.overlaps(p) for t, _ in taken)]
                questions.append(
                    _question(plan, pt, "taken", free, place=_label(plan, place), other=other)
                )
                continue
        zid = f"{AUTO_ID}{pt.id}"
        while zid in ids:
            zid += "_"
        ids.add(zid)
        fh = FloorHeating(
            id=zid,
            room=place.room,
            zone=place.zone,
            thermostat=pt.id,
            area=note_area(pt.note or ""),
            auto=True,
        )
        zones.append(fh)
        taken.append((place, zid))
    return AutoHeating(tuple(zones), tuple(questions))
