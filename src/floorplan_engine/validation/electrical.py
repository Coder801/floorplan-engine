"""Проверка электрики (electrical.yaml): ссылки на помещения и стены, привязка точек
к стене и высоты (точка выше потолка — предупреждение), щит, `controls` выключателей,
группы, охватывающие несколько помещений в режимах standard и proper."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

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
    """controls выключателя ссылается на светильник, вывод LED или ленту проекта."""
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
    """Точка на стене выше потолка: неверна высота точки или высота потолка (предупреждение —
    на развёртке стены такая точка видна над линией потолка)."""
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


def _check_wall_anchor(
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
        return issues + _check_wall_anchor(plan, pt.room, pt.wall, pt.offset, path, file)
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


def _check_board_width(plan: Plan, board: Board, file: str) -> list[Issue]:
    """Щит (offset — его середина) целиком помещается на стене."""
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
                "board",
                f"щит шириной {board.width:g} мм с серединой на offset {board.offset:g} "
                f"занимает {lo:g}…{hi:g} мм и не помещается на стене {board.wall} "
                f"длиной {length:g} мм",
            )
        ]
    return []


def resolve_ref(ref: str, points: Sequence[ElectricalPoint]) -> int | None:
    """Индекс точки по её id; None — не найдено."""
    return next((k for k, pt in enumerate(points) if pt.id == ref), None)


def validate_electrical(
    elec: Electrical, plan: Plan, contours: dict[str, Contour], file: str = ELECTRICAL_FILE
) -> list[Issue]:
    issues: list[Issue] = []
    # id объектов уникальны во всём проекте: проёмы плана — тоже
    taken = {
        op.id: f"{ROOM_FILE}: rooms[{r}].openings[{k}]"
        for r, room in enumerate(plan.rooms)
        for k, op in enumerate(room.openings)
    }
    taken["board"] = "board (зарезервировано для щита)"
    issues += duplicates(
        [
            *((f"points[{k}].id", pt.id) for k, pt in enumerate(elec.points)),
            *((f"cables[{k}].id", c.id) for k, c in enumerate(elec.cables)),
            *((f"led_strips[{k}].id", st.id) for k, st in enumerate(elec.led_strips)),
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
        issues += _check_wall_anchor(plan, b.room, b.wall, b.offset, "board", file)
        issues += _check_board_width(plan, b, file)
    for s, strip in enumerate(elec.led_strips):
        # Конец ленты должен лежать на стене; попадание в проём здесь не ошибка
        issues += [
            replace(i, path=i.path.replace(".offset", ".end"))
            for i in _check_wall_anchor(
                plan, strip.room, strip.wall, strip.end, f"led_strips[{s}]", file
            )
            if i.severity is Severity.ERROR
        ]
    issues += _check_room_groups(elec, plan, file)
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


# Группы света и розеток — по помещениям (кроме режима economy); отдельные линии к технике
# и регуляторы (switch с note) — не в счёт
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
    """В режиме standard и proper группа света или розеток — в одном помещении."""
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
