"""Electrical check (electrical.yaml): references to rooms and walls, anchoring points to walls
and heights (a point above the ceiling is a warning), the panel, switch `controls`, groups
spanning several rooms in standard and proper modes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from shapely.geometry import Polygon

from floorplan_engine.electrical.floor_heating import (
    AREA_TOLERANCE,
    floor_outline,
    heating_power,
    heating_zones,
)
from floorplan_engine.electrical.heating_auto import HEATING_ROOMS, NONE, Place, parse_place
from floorplan_engine.model.geometry import (
    Contour,
    Vec,
    point_in_polygon,
)
from floorplan_engine.model.schema import (
    LIGHT_TYPES,
    Board,
    Electrical,
    ElectricalPoint,
    Plan,
    PointType,
)
from floorplan_engine.validation.issues import (
    ELECTRICAL_FILE,
    ROOM_FILE,
    Issue,
    Severity,
)
from floorplan_engine.validation.plan import (
    duplicates,
    no_wall,
    opening_name,
)

HEIGHT_MIN_MM = 0.0
HEIGHT_MAX_MM = 3000.0


def _check_height(value: float | None, path: str, file: str) -> list[Issue]:
    if value is None or HEIGHT_MIN_MM <= value <= HEIGHT_MAX_MM:
        return []
    return [
        Issue(
            file,
            path,
            f"высота {value:g} мм вне разумных пределов {HEIGHT_MIN_MM:g}–{HEIGHT_MAX_MM:g} мм",
        )
    ]


def _check_controls(elec: Electrical, file: str) -> list[Issue]:
    """A switch's controls refers to a light, an LED output or a strip of the project."""
    lights = {p.id for p in elec.points if p.type in LIGHT_TYPES}
    lights |= {s.id for s in elec.led_strips}
    return [
        Issue(
            file,
            f"points[{k}].controls[{j}]",
            f"«{ref}» — не светильник, не вывод LED и не лента проекта",
        )
        for k, pt in enumerate(elec.points)
        for j, ref in enumerate(pt.controls)
        if ref not in lights
    ]


def _above_ceiling(elec: Electrical, plan: Plan, file: str) -> list[Issue]:
    """Wall point above the ceiling: either the point height or the ceiling height is wrong (a
    warning: on the wall elevation such a point shows above the ceiling line)."""
    ceiling = plan.ceiling_height
    default = "ceiling_height" not in plan.model_fields_set
    note = " (не задана в room.yaml — по умолчанию)" if default else ""
    return [
        Issue(
            file,
            f"points[{k}].height",
            f"точка {pt.id} на высоте {pt.height:g} мм — выше потолка {ceiling:g} мм{note}: "
            "уточните высоту точки или потолка",
            Severity.WARNING,
        )
        for k, pt in enumerate(elec.points)
        if pt.wall is not None and pt.height is not None and pt.height > ceiling
    ]


def check_wall_anchor(
    plan: Plan, room_id: str, wall: str, offset: float, path: str, file: str
) -> list[Issue]:
    room = next((r for r in plan.rooms if r.id == room_id), None)
    if room is None:
        known = ", ".join(r.id for r in plan.rooms)
        return [Issue(file, f"{path}.room", f"комнаты «{room_id}» нет в room.yaml (есть: {known})")]
    index = room.wall_index(wall)
    if index is None:
        return [no_wall(room, wall, f"{path}.wall", file)]
    length = room.walls[index].length
    if offset > length:
        return [
            Issue(
                file,
                f"{path}.offset",
                f"offset {offset:g} мм за пределами стены {wall} длиной {length:g} мм",
            )
        ]
    issues: list[Issue] = []
    for op in room.openings:
        if op.wall == wall and op.offset < offset < op.offset + op.width:
            issues.append(
                Issue(
                    file,
                    f"{path}.offset",
                    f"точка попадает в {opening_name(op.type)} "
                    f"({op.offset:g}–{op.offset + op.width:g} мм на стене {wall})",
                    Severity.WARNING,
                )
            )
    return issues


def _check_point(
    plan: Plan, contours: dict[str, Contour], pt: ElectricalPoint, path: str, file: str
) -> list[Issue]:
    issues = _check_height(pt.height, f"{path}.height", file)
    if pt.wall is not None and pt.offset is not None:
        return issues + check_wall_anchor(plan, pt.room, pt.wall, pt.offset, path, file)
    room = next((r for r in plan.rooms if r.id == pt.room), None)
    if room is None:
        known = ", ".join(r.id for r in plan.rooms)
        return [
            *issues,
            Issue(file, f"{path}.room", f"комнаты «{pt.room}» нет в room.yaml (есть: {known})"),
        ]
    contour = contours.get(room.id)
    if pt.ceiling is not None and contour is not None and contour.is_closed():
        pos = Vec(*room.origin) + Vec(*pt.ceiling)
        if not point_in_polygon(pos, contour.vertices):
            issues.append(
                Issue(
                    file,
                    f"{path}.ceiling",
                    f"точка [{pt.ceiling[0]:g}, {pt.ceiling[1]:g}] (от origin комнаты) "
                    f"вне контура «{room.name}»",
                )
            )
    return issues


def _check_board_width(plan: Plan, board: Board, file: str, path: str = "board") -> list[Issue]:
    """The panel or the low-voltage cabinet (offset is its centre) fits entirely on the wall."""
    room = next((r for r in plan.rooms if r.id == board.room), None)
    index = room.wall_index(board.wall) if room is not None else None
    if room is None or index is None:
        return []
    length = room.walls[index].length
    lo, hi = board.offset - board.width / 2, board.offset + board.width / 2
    if lo < 0 or hi > length:
        return [
            Issue(
                file,
                path,
                f"щит шириной {board.width:g} мм с серединой на offset {board.offset:g} "
                f"занимает {lo:g}…{hi:g} мм и не помещается на стене {board.wall} "
                f"длиной {length:g} мм",
            )
        ]
    return []


def resolve_ref(ref: str, points: Sequence[ElectricalPoint]) -> int | None:
    """Point index by its id; None if not found."""
    return next((k for k, pt in enumerate(points) if pt.id == ref), None)


def validate_electrical(
    elec: Electrical, plan: Plan, contours: dict[str, Contour], file: str = ELECTRICAL_FILE
) -> list[Issue]:
    issues: list[Issue] = []
    # Object ids are unique across the whole project, plan openings included
    taken = {
        op.id: f"{ROOM_FILE}: rooms[{r}].openings[{k}]"
        for r, room in enumerate(plan.rooms)
        for k, op in enumerate(room.openings)
    }
    taken["board"] = "board (зарезервировано для щита)"
    taken["media"] = "media (зарезервировано для слаботочного щита)"
    issues += duplicates(
        [
            *((f"points[{k}].id", pt.id) for k, pt in enumerate(elec.points)),
            *((f"cables[{k}].id", c.id) for k, c in enumerate(elec.cables)),
            *((f"led_strips[{k}].id", st.id) for k, st in enumerate(elec.led_strips)),
            *((f"cable_channels[{k}].id", ch.id) for k, ch in enumerate(elec.cable_channels)),
            *((f"floor_heating[{k}].id", fh.id) for k, fh in enumerate(elec.floor_heating)),
        ],
        file,
        "id",
        taken,
    )
    for k, pt in enumerate(elec.points):
        issues += _check_point(plan, contours, pt, f"points[{k}]", file)
    issues += _above_ceiling(elec, plan, file)
    issues += _check_controls(elec, file)
    if elec.board is not None:
        b = elec.board
        issues += _check_height(b.height, "board.height", file)
        issues += check_wall_anchor(plan, b.room, b.wall, b.offset, "board", file)
        issues += _check_board_width(plan, b, file)
    if elec.media is not None:
        m = elec.media
        issues += _check_height(m.height, "media.height", file)
        issues += check_wall_anchor(plan, m.room, m.wall, m.offset, "media", file)
        issues += _check_board_width(plan, m, file, "media")
    for s, strip in enumerate(elec.led_strips):
        # The strip end must lie on the wall; landing in an opening is not an error here
        issues += [
            replace(i, path=i.path.replace(".offset", ".end"))
            for i in check_wall_anchor(
                plan, strip.room, strip.wall, strip.end, f"led_strips[{s}]", file
            )
            if i.severity is Severity.ERROR
        ]
    for k, ch in enumerate(elec.cable_channels):
        path = f"cable_channels[{k}]"
        issues += check_wall_anchor(plan, ch.room, ch.wall, ch.offset, path, file)
        issues += _check_height(ch.entry, f"{path}.entry", file)
        issues += _check_height(ch.exit, f"{path}.exit", file)
    issues += _check_room_groups(elec, plan, file)
    issues += _check_floor_heating(elec, plan, contours, file)
    used = {p.group for p in elec.points if p.group} | {c.group for c in elec.cables if c.group}
    for name in elec.groups:
        if name not in used:
            issues.append(
                Issue(
                    file,
                    f"groups.{name}",
                    f"группы «{name}» нет ни у одной точки и кабеля",
                    Severity.WARNING,
                )
            )
    for c, cable in enumerate(elec.cables):
        path = f"cables[{c}]"
        refs = [("from", cable.from_), *((f"to[{t}]", r) for t, r in enumerate(cable.to))]
        for key, ref in refs:
            if ref == "board":
                if elec.board is None:
                    issues.append(Issue(file, f"{path}.{key}", "ссылка на board, но щит не задан"))
                continue
            if resolve_ref(ref, elec.points) is None:
                issues.append(
                    Issue(
                        file,
                        f"{path}.{key}",
                        f"не найдена точка «{ref}»: ожидается board или id точки",
                    )
                )
    return issues


# Lighting and socket groups are per room (except in economy mode); dedicated appliance lines
# and floor heating controllers do not count
_ROOM_GROUP_TYPES = frozenset(
    {
        PointType.LIGHT,
        PointType.DOWNLIGHT,
        PointType.PENDANT,
        PointType.SCONCE,
        PointType.LED_OUTPUT,
        PointType.SOCKET,
    }
)


def _check_room_groups(elec: Electrical, plan: Plan, file: str) -> list[Issue]:
    """In standard and proper modes a lighting or socket group stays within one room."""
    if elec.mode == "economy":
        return []
    names = {r.id: r.name for r in plan.rooms}
    rooms: dict[str, set[str]] = {}
    for p in elec.points:
        if p.group and p.type in _ROOM_GROUP_TYPES:
            rooms.setdefault(p.group, set()).add(p.room)
    return [
        Issue(
            file,
            f"groups.{g}",
            f"режим {elec.mode}: группа {g} охватывает несколько помещений "
            f"({', '.join(sorted(names.get(r, r) for r in rs))}) — каждое помещение "
            "своей группой (или mode: economy)",
            Severity.WARNING,
        )
        for g, rs in sorted(rooms.items())
        if len(rs) > 1
    ]


EXCLUDE_TOLERANCE = 1.0  # mm: an exclusion may touch the floor outline


def _check_floor_heating(
    elec: Electrical, plan: Plan, contours: dict[str, Contour], file: str
) -> list[Issue]:
    """Floor heating zones: the room and its zone, the controller is a `thermostat` point, the
    exclusions lie on the floor; the layout remarks (pitch out of range, part not covered)."""
    issues: list[Issue] = []
    rooms = {r.id: r for r in plan.rooms}
    points = {p.id: p for p in elec.points}
    for k, fh in enumerate(elec.floor_heating):
        path = f"floor_heating[{k}]"
        room = rooms.get(fh.room)
        if room is None:
            issues.append(Issue(file, f"{path}.room", f"нет помещения «{fh.room}» в {ROOM_FILE}"))
            continue
        if fh.zone is not None and fh.zone not in {z.name for z in room.zones}:
            names = ", ".join(f"«{z.name}»" for z in room.zones) or "зон нет"
            issues.append(
                Issue(file, f"{path}.zone", f"в помещении {fh.room} нет зоны «{fh.zone}»: {names}")
            )
        reg = points.get(fh.thermostat)
        if reg is None:
            issues.append(
                Issue(file, f"{path}.thermostat", f"нет точки «{fh.thermostat}» — регулятора зоны")
            )
        elif reg.type is not PointType.THERMOSTAT:
            issues.append(
                Issue(
                    file,
                    f"{path}.thermostat",
                    f"точка «{fh.thermostat}» — {reg.type.value}, а регулятор тёплого пола — "
                    "type: thermostat",
                )
            )
        outline = floor_outline(plan, contours, fh) if fh.room in contours else None
        if outline is None or len(outline) < 3:
            continue
        floor = Polygon([v.as_tuple() for v in outline]).buffer(EXCLUDE_TOLERANCE)
        ox, oy = room.origin
        for j, ex in enumerate(fh.exclude):
            x, y = ox + ex.at[0], oy + ex.at[1]
            rect = Polygon(
                [(x, y), (x + ex.size[0], y), (x + ex.size[0], y + ex.size[1]), (x, y + ex.size[1])]
            )
            if not floor.contains(rect):
                where = f"зоны «{fh.zone}»" if fh.zone else f"помещения {fh.room}"
                issues.append(
                    Issue(
                        file,
                        f"{path}.exclude[{j}]",
                        f"прямоугольник at {list(ex.at)}, size {list(ex.size)} выходит за пол "
                        f"{where}: координаты — мм от origin помещения",
                    )
                )
    issues += _check_heating_overlaps(elec, plan, file)
    if any(i.severity is Severity.ERROR for i in issues):
        return issues
    regs = {p.id: k for k, p in enumerate(elec.points)}
    for z in heating_zones(plan, contours, elec):
        # An auto zone has no entry in electrical.yaml: its remarks point to the controller
        path = (
            f"points[{regs[z.spec.thermostat]}]"
            if z.spec.auto and z.spec.thermostat in regs
            else f"floor_heating[{z.index}]"
        )
        what = f"тёплый пол «{z.spec.id}»" + (" (зона по регулятору)" if z.spec.auto else "")
        if z.spec.auto:
            issues.append(
                Issue(
                    file,
                    path,
                    f"{what}: в floor_heating зоны нет — построена кодом: {z.name}* "
                    "(допущение: помещение по подписи или месту регулятора); уточните по дизайну "
                    "или задайте heating_rooms",
                    Severity.WARNING,
                )
            )
        issues += [Issue(file, path, f"{what}: {r}", Severity.WARNING) for r in z.remarks]
        if z.area_off:
            assert z.spec.area is not None
            source = "по подписи регулятора" if z.spec.auto else "по проекту"
            issues.append(
                Issue(
                    file,
                    f"{path}.note" if z.spec.auto else f"{path}.area",
                    f"{what}: {source} {_m2(z.spec.area)} м², по раскладке {_m2(z.area_m2)} м² — "
                    f"расхождение больше {AREA_TOLERANCE:.0%}: уточните вырезы (exclude) или "
                    "мебель (furniture.yaml)",
                    Severity.WARNING,
                )
            )
    return issues


def _check_heating_overlaps(elec: Electrical, plan: Plan, file: str) -> list[Issue]:
    """Two zones on one floor (the whole room and a zone of it, or the same place twice) would
    lay two serpentines and count the power twice: an error on the later one. An auto zone is
    set by its controller's heating_rooms entry (from the note it never takes a heated floor)."""
    issues: list[Issue] = []
    seen: list[tuple[Place, str]] = []
    for k, fh in enumerate(elec.floor_heating):
        place = parse_place(plan, Place(fh.room, fh.zone).key)
        if place is None:
            continue  # no such room or zone: reported above
        other = next((zid for p, zid in seen if p.overlaps(place)), None)
        seen.append((place, fh.id))
        if other is None:
            continue
        if fh.auto:
            path = f"{HEATING_ROOMS}.{fh.thermostat}"
        else:
            path = f"floor_heating[{k}].{'zone' if fh.zone is not None else 'room'}"
        what = f"зона «{fh.zone}» помещения {fh.room}" if fh.zone else f"помещение {fh.room}"
        issues.append(
            Issue(
                file,
                path,
                f"тёплый пол «{fh.id}»: {what} уже греет зона «{other}» — две змейки на одном "
                "полу и двойная мощность; оставьте одну запись или разделите пол по зонам",
            )
        )
    return issues


def _m2(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _check_heating_rooms(elec: Electrical, plan: Plan, file: str) -> list[Issue]:
    """`heating_rooms`: a key is a controller without a floor_heating entry, a value is a room,
    «room:zone» or none."""
    issues: list[Issue] = []
    points = {p.id: p for p in elec.points}
    named = {fh.thermostat for fh in elec.floor_heating}
    for reg, value in elec.heating_rooms.items():
        path = f"{HEATING_ROOMS}.{reg}"
        pt = points.get(reg)
        if pt is None or pt.type is not PointType.THERMOSTAT:
            issues.append(Issue(file, path, f"«{reg}» — не точка type: thermostat"))
        elif reg in named:
            issues.append(
                Issue(
                    file,
                    path,
                    f"у регулятора {reg} уже есть зона в floor_heating — запись не нужна",
                    Severity.WARNING,
                )
            )
        elif value != NONE and parse_place(plan, value) is None:
            issues.append(
                Issue(
                    file,
                    path,
                    f"«{value}»: ожидается id помещения, «помещение:зона» из {ROOM_FILE} или "
                    f"{NONE}",
                )
            )
    return issues


def floor_heating_source(
    elec: Electrical, plan: Plan, contours: dict[str, Contour], file: str = ELECTRICAL_FILE
) -> list[Issue]:
    """Checks of electrical.yaml as written, before the code adds to it: `fixtures`, `furniture`
    and `auto` are set by the code; `heating_rooms` names controllers and places."""
    code_set = {
        "fixtures": "fixtures ставит код по plumbing.yaml — уберите поле; своё пятно — в exclude",
        "furniture": "furniture ставит код по furniture.yaml — уберите поле; мебель — в "
        "furniture.yaml, своё пятно — в exclude",
        "auto": "auto ставит код у зоны по регулятору — уберите поле",
    }
    issues = [
        Issue(file, f"floor_heating[{k}].{name}", message)
        for k, fh in enumerate(elec.floor_heating)
        for name, message in code_set.items()
        if getattr(fh, name)
    ]
    issues += _check_heating_rooms(elec, plan, file)
    return issues


def heating_power_issues(
    elec: Electrical, plan: Plan, contours: dict[str, Contour], file: str = ELECTRICAL_FILE
) -> list[Issue]:
    """A controller's own `power` that differs from its cable sections is a warning. elec is the
    model after with_heating: the zones as the sheet, the panel and the estimate see them (with
    the plumbing spots, the solid furniture and the auto zones)."""
    issues: list[Issue] = []
    power = heating_power(heating_zones(plan, contours, elec))
    for k, p in enumerate(elec.points):
        if p.power is not None and p.id in power and abs(p.power - power[p.id]) > 0.1 * p.power:
            issues.append(
                Issue(
                    file,
                    f"points[{k}].power",
                    f"у регулятора {p.id} мощность {p.power:g} Вт, а у его секций тёплого пола "
                    f"{power[p.id]:g} Вт: щит считается по {p.power:g} Вт — уточните",
                    Severity.WARNING,
                )
            )
    return issues
