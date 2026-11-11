"""Wall names for people (decision 2026-11-11): ids w1…wN are unique only inside a room and say
nothing, so every wall gets a code unique in the flat and a description.

Code: the floor number from the room schedule and a letter by the walk (clockwise from the
room's first wall): "2.В". A zone that splits the floor is a floor of its own, with its own
number, as in the schedule. Letters are Cyrillic without the ones easily confused with digits or
with each other; past the last letter they repeat with a number ("А2").

Description: `name` of the wall in room.yaml, if given; otherwise built from geometry — what is
behind the wall (neighbouring rooms, or "наружная" when no room of the flat is there) and what is
in it (windows, doors, openings): "Кухня за стеной, дверь", "наружная, окно ×2".

The ids in YAML stay as they are: openings, points, wiring.yaml and answers refer to them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from floorplan_engine.model.geometry import (
    Contour,
    RoomGeometry,
    WallSegment,
    point_in_polygon,
    room_geometries,
)
from floorplan_engine.model.schema import OpeningType, Plan, Room
from floorplan_engine.model.texts import Language
from floorplan_engine.model.zones import plan_floors

# Same in ru and uk; no З (3), О (0), Ч (4), Ё/Й/Ъ/Ь/Ы and no letters of one language only
LETTERS = "АБВГДЕЖИКЛМНПРСТУФХЦШ"
BEHIND_PROBE_MM = 50.0  # how far past the outer wall face to look for a neighbouring room
FACE_TOLERANCE_MM = 30.0  # neighbour face no farther than this from this wall's outer face
BEHIND_STEP_MM = 500.0  # probe step along the wall (neighbour behind part of a wall)

WORDS: dict[str, dict[Language, str]] = {
    "behind": {"ru": "{rooms} за стеной", "uk": "{rooms} за стіною"},
    "outside": {"ru": "наружная", "uk": "зовнішня"},
    OpeningType.WINDOW: {"ru": "окно", "uk": "вікно"},
    OpeningType.DOOR: {"ru": "дверь", "uk": "двері"},
    OpeningType.OPENING: {"ru": "проём", "uk": "проріз"},
}
OPENING_ORDER = (OpeningType.WINDOW, OpeningType.DOOR, OpeningType.OPENING)


@dataclass(frozen=True)
class WallName:
    code: str  # "2.В": unique in the flat
    text: str  # "Кухня за стеной, дверь" or the wall's name from room.yaml

    @property
    def full(self) -> str:
        return f"{self.code} · {self.text}"


@dataclass(frozen=True)
class Behind:
    """A room of the flat behind a wall, and its wall on the far side (None: no wall faces)."""

    room: str  # room id
    name: str  # room name
    wall: str | None  # its wall id


def letter(k: int) -> str:
    """Letter of the k-th wall of a floor (from 0)."""
    n, i = divmod(k, len(LETTERS))
    return LETTERS[i] + (str(n + 1) if n else "")


def wall_codes(plan: Plan, contours: dict[str, Contour]) -> dict[tuple[str, str], str]:
    """(room id, wall id) → code. Walls of a floor in walk order; a wall of no floor (a zone that
    does not take every wall leaves the room one floor, so there is none) does not happen."""
    out: dict[tuple[str, str], str] = {}
    for n, floor in enumerate(plan_floors(plan, contours), 1):
        walls = set(floor.walls)
        ordered = [w.id for w in floor.room.walls if w.id in walls]
        for k, wall in enumerate(ordered):
            out[(floor.room.id, wall)] = f"{n}.{letter(k)}"
    return out


def wall_names(plan: Plan, contours: dict[str, Contour]) -> dict[tuple[str, str], WallName]:
    """(room id, wall id) → code and description, for every wall of the flat."""
    codes = wall_codes(plan, contours)
    geoms = room_geometries(plan, contours)
    out: dict[tuple[str, str], WallName] = {}
    for g in geoms:
        for seg, wall in zip(g.contour.segments, g.room.walls, strict=True):
            key = (g.room.id, wall.id)
            text = wall.name or describe(g.room, seg, behind(g, seg, geoms), plan.language)
            out[key] = WallName(codes[key], text)
    return out


def describe(room: Room, seg: WallSegment, near: Sequence[Behind], language: Language) -> str:
    """What is behind the wall and what is in it, in words."""
    rooms = ", ".join(b.name for b in near)
    parts = [WORDS["behind"][language].format(rooms=rooms) if near else WORDS["outside"][language]]
    for kind in OPENING_ORDER:
        n = sum(1 for op in room.openings if op.wall == seg.id and op.type is kind)
        if n:
            parts.append(WORDS[kind][language] + (f" ×{n}" if n > 1 else ""))
    return ", ".join(parts)


def behind(g: RoomGeometry, seg: WallSegment, geoms: Sequence[RoomGeometry]) -> tuple[Behind, ...]:
    """What is behind wall seg of room g: neighbouring rooms (probed beyond the outer face along the
    whole wall: a partition may be shared only in part, a long wall may have several rooms behind
    it) and the neighbour's wall on the same face; empty means no room of the flat behind."""
    out: list[Behind] = []
    n = max(3, round(seg.length / BEHIND_STEP_MM))
    for k in range(n):
        at = seg.length * (k + 0.5) / n
        p = seg.point_at(at) + seg.outward * (seg.thickness + BEHIND_PROBE_MM)
        for o in geoms:
            if o is g or not point_in_polygon(p, o.contour.vertices):
                continue
            facing = facing_segments(seg, o)
            item = Behind(o.room.id, o.room.name, facing[0].id if facing else None)
            if item not in out:
                out.append(item)
    return tuple(out)


def facing_segments(seg: WallSegment, other: RoomGeometry) -> list[WallSegment]:
    """Neighbour walls on the far side of seg: they run the opposite way along seg's outer face and
    overlap it along the wall."""
    far = seg.start + seg.outward * seg.thickness
    out: list[WallSegment] = []
    for o in other.contour.segments:
        if o.direction.dot(seg.direction) > -0.99:
            continue
        if abs((o.start - far).dot(seg.outward)) > FACE_TOLERANCE_MM:
            continue
        a = (o.end - seg.start).dot(seg.direction)
        b = (o.start - seg.start).dot(seg.direction)
        if min(b, seg.length) - max(a, 0.0) > FACE_TOLERANCE_MM:
            out.append(o)
    return out
