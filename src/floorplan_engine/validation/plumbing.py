"""Plumbing check (plumbing.yaml): references to rooms and walls, anchoring of fixtures, the
supply unit and obstacles to walls, risers inside a room (or in its wall), project-wide ids,
fixtures outside wet rooms, a missing sewer riser when fixtures have drains."""

from __future__ import annotations

from shapely.geometry import Point, Polygon

from floorplan_engine.model.geometry import Contour
from floorplan_engine.model.plumbing import (
    DRY_ROOM_FIXTURES,
    PLUMBING_FILE,
    Plumbing,
)
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.validation.electrical import check_wall_anchor
from floorplan_engine.validation.issues import ROOM_FILE, Issue, Severity
from floorplan_engine.validation.plan import duplicates

RISER_SLACK_MM = 100.0  # riser in a wall: at most wall thickness + this from the room


def _room(plan: Plan, room_id: str, path: str, file: str) -> Issue | None:
    if any(r.id == room_id for r in plan.rooms):
        return None
    known = ", ".join(r.id for r in plan.rooms)
    return Issue(file, f"{path}.room", f"комнаты «{room_id}» нет в room.yaml (есть: {known})")


def validate_plumbing(
    plumbing: Plumbing,
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical | None = None,
    file: str = PLUMBING_FILE,
) -> list[Issue]:
    issues: list[Issue] = []
    taken = {
        op.id: f"{ROOM_FILE}: rooms[{r}].openings[{k}]"
        for r, room in enumerate(plan.rooms)
        for k, op in enumerate(room.openings)
    }
    if elec is not None:
        taken |= {p.id: f"electrical.yaml: points[{k}]" for k, p in enumerate(elec.points)}
    issues += duplicates(
        [
            *((f"risers[{k}].id", r.id) for k, r in enumerate(plumbing.risers)),
            *((f"fixtures[{k}].id", f.id) for k, f in enumerate(plumbing.fixtures)),
            *((f"obstacles[{k}].id", o.id) for k, o in enumerate(plumbing.obstacles)),
        ],
        file,
        "id",
        taken,
    )
    rooms = {r.id: r for r in plan.rooms}
    for k, fx in enumerate(plumbing.fixtures):
        path = f"fixtures[{k}]"
        issues += check_wall_anchor(plan, fx.room, fx.wall, fx.offset, path, file)
        room = rooms.get(fx.room)
        if room is not None and not room.wet and fx.type not in DRY_ROOM_FIXTURES:
            issues.append(
                Issue(
                    file,
                    f"{path}.room",
                    f"прибор {fx.type.value} в помещении «{room.name}» без wet: true — "
                    "мокрая зона: коробки IP44, УЗО",
                    Severity.WARNING,
                )
            )
    if plumbing.input is not None:
        inp = plumbing.input
        issues += check_wall_anchor(plan, inp.room, inp.wall, inp.offset, "input", file)
    for k, ob in enumerate(plumbing.obstacles):
        path = f"obstacles[{k}]"
        if ob.wall is not None and ob.offset is not None and ob.width is not None:
            issues += [
                i
                for i in check_wall_anchor(plan, ob.room, ob.wall, ob.offset + ob.width, path, file)
                if i.severity is Severity.ERROR
            ]
        elif (bad := _room(plan, ob.room, path, file)) is not None:
            issues.append(bad)
    for k, r in enumerate(plumbing.risers):
        path = f"risers[{k}]"
        bad = _room(plan, r.room, path, file)
        if bad is not None:
            issues.append(bad)
            continue
        contour = contours.get(r.room)
        if contour is None or not contour.is_closed():
            continue
        room = rooms[r.room]
        poly = Polygon([v.as_tuple() for v in contour.vertices])
        at = Point(room.origin[0] + r.at[0], room.origin[1] + r.at[1])
        reach = max(s.thickness for s in contour.segments) + RISER_SLACK_MM
        if poly.distance(at) > reach:
            issues.append(
                Issue(
                    file,
                    f"{path}.at",
                    f"стояк [{r.at[0]:g}, {r.at[1]:g}] (от origin комнаты) дальше "
                    f"{reach:g} мм от «{room.name}» — не в помещении и не в его стене",
                )
            )
    drains = [f for f in plumbing.fixtures if f.spec.sewer is not None]
    if drains and not any(r.sewer for r in plumbing.risers):
        issues.append(
            Issue(file, "risers", "есть приборы с выпуском, но нет стояка канализации (sewer)")
        )
    return issues
