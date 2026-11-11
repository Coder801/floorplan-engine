"""Zones of an open-plan room (decision 2026-11-11): a kitchen-living room with a hall is one
room in room.yaml — no wall between them — yet group purposes and point captions should say
"Кухня-вітальня" or "Передпокій", not the name of the whole space.

A zone is a set of the room's walls. A wall point belongs to the zone of its wall. A ceiling
point belongs to the zone whose outline holds it: the zone's walls in walk order, closed by a
straight line where the zone meets the next one (the boundary that has no wall); outside every
outline — the zone of the nearest wall. A point on a wall of no zone, or in a room without
zones, takes the room name.

On the plan (decision 2026-11-11) each zone is its own floor: its outline, name and area, a row
of the room schedule and a hover highlight in the viewer (`room_floors`). Zones split the floor
only if they take every wall of the room; otherwise the room stays one floor.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from floorplan_engine.model.geometry import (
    Contour,
    Vec,
    WallSegment,
    point_in_polygon,
    signed_area,
    trace_contour,
)
from floorplan_engine.model.schema import ElectricalPoint, Plan, Room, Zone


def _distance(p: Vec, s: WallSegment) -> float:
    """From a point to the inner face of a wall, mm."""
    t = max(0.0, min(s.length, (p - s.start).dot(s.direction)))
    return (p - s.point_at(t)).length()


def _outline(contour: Contour, zone: Zone) -> list[Vec]:
    """The zone's walls in walk order, start and end of each; the polygon closes itself."""
    walls = [seg for seg in contour.segments if seg.id in zone.walls]
    return [v for seg in walls for v in (seg.start, seg.end)]


def _ceiling_zone(room: Room, plan: Plan, at: tuple[float, float]) -> str:
    contour = trace_contour(room, plan.default_wall_thickness)
    p = Vec(*room.origin) + Vec(*at)
    inside = next((z.name for z in room.zones if point_in_polygon(p, _outline(contour, z))), None)
    if inside is not None:
        return inside
    wall = min(contour.segments, key=lambda s: _distance(p, s)).id
    return next((z.name for z in room.zones if wall in z.walls), room.name)


def place_of(plan: Plan, point: ElectricalPoint) -> str:
    """Zone name of the point, or its room name; an unknown room gives its id."""
    room = next((r for r in plan.rooms if r.id == point.room), None)
    if room is None:
        return point.room
    if not room.zones:
        return room.name
    if point.wall is None and point.ceiling is not None:
        return _ceiling_zone(room, plan, point.ceiling)
    return next((z.name for z in room.zones if point.wall in z.walls), room.name)


def point_places(plan: Plan, points: Iterable[ElectricalPoint]) -> dict[str, str]:
    """Point id → zone or room name."""
    return {p.id: place_of(plan, p) for p in points}


@dataclass(frozen=True)
class Floor:
    """A floor on the plan: a whole room, or a zone of it. key is the object key on the sheet
    ("room:hall", or "zone:hall.1" for the first zone)."""

    key: str
    room: Room
    name: str
    vertices: tuple[Vec, ...]  # inner outline, as the room contour
    walls: tuple[str, ...]  # its walls: the zone's, or all walls of the room

    @property
    def area_mm2(self) -> float:
        return abs(signed_area(self.vertices))

    @property
    def area_m2(self) -> float:
        return self.area_mm2 / 1e6


def splits_floor(room: Room) -> bool:
    """Zones split the floor when together they take every wall of the room."""
    taken = {w for z in room.zones for w in z.walls}
    return bool(room.zones) and taken == {w.id for w in room.walls}


def _distinct(points: list[Vec]) -> tuple[Vec, ...]:
    """Outline without repeated neighbours: the end of a wall is the start of the next one."""
    out: list[Vec] = []
    for p in points:
        if not out or (p - out[-1]).length() > 1e-6:
            out.append(p)
    if len(out) > 1 and (out[0] - out[-1]).length() <= 1e-6:
        out.pop()
    return tuple(out)


def room_floors(room: Room, contour: Contour) -> list[Floor]:
    """The room's floors: one per zone when the zones split it, else the whole room."""
    if not splits_floor(room):
        walls = tuple(w.id for w in room.walls)
        return [Floor(f"room:{room.id}", room, room.name, tuple(contour.vertices), walls)]
    return [
        Floor(f"zone:{room.id}.{k}", room, z.name, _distinct(_outline(contour, z)), tuple(z.walls))
        for k, z in enumerate(room.zones, 1)
    ]


def plan_floors(plan: Plan, contours: dict[str, Contour]) -> list[Floor]:
    """Floors of all rooms in plan order (the room schedule order)."""
    return [f for r in plan.rooms if r.id in contours for f in room_floors(r, contours[r.id])]
