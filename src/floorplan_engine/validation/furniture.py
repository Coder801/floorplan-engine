"""Furniture check (furniture.yaml, decision 2026-11-15): the room is in room.yaml, the rectangle
lies on its floor (within INSIDE_TOLERANCE of the outline), ids are not repeated."""

from __future__ import annotations

from shapely.geometry import Polygon, box

from floorplan_engine.model.furniture import FURNITURE_FILE, Furniture
from floorplan_engine.model.geometry import Contour
from floorplan_engine.model.schema import Plan
from floorplan_engine.validation.issues import Issue
from floorplan_engine.validation.plan import duplicates

INSIDE_TOLERANCE = 20.0  # mm: a piece drawn by the plan may touch the walls a little


def validate_furniture(
    furniture: Furniture, plan: Plan, contours: dict[str, Contour], file: str = FURNITURE_FILE
) -> list[Issue]:
    issues = duplicates(
        ((f"items[{k}].id", item.id) for k, item in enumerate(furniture.items)), file, "id"
    )
    rooms = {r.id: r for r in plan.rooms}
    for k, item in enumerate(furniture.items):
        path = f"items[{k}]"
        room = rooms.get(item.room)
        if room is None:
            known = ", ".join(rooms)
            issues.append(
                Issue(
                    file, f"{path}.room", f"комнаты «{item.room}» нет в room.yaml (есть: {known})"
                )
            )
            continue
        contour = contours.get(room.id)
        if contour is None or not contour.is_closed() or len(contour.vertices) < 3:
            continue
        floor = Polygon([v.as_tuple() for v in contour.vertices]).buffer(INSIDE_TOLERANCE)
        x, y = room.origin[0] + item.at[0], room.origin[1] + item.at[1]
        if not floor.contains(box(x, y, x + item.size[0], y + item.size[1])):
            issues.append(
                Issue(
                    file,
                    f"{path}.at",
                    f"«{item.id}»: прямоугольник at {list(item.at)}, size {list(item.size)} "
                    f"выходит за пол помещения «{room.name}» больше чем на "
                    f"{INSIDE_TOLERANCE:g} мм: координаты — мм от origin помещения, size — по "
                    "осям X и Y",
                )
            )
    return issues
