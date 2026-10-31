"""Проверка плана (room.yaml): уникальность id, замкнутость контура — при невязке ошибка с
её величиной и стенами, которые вероятно заданы неверно; проёмы — на своей стене и в её
длине. Ничего не подгоняется молча."""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Sequence

from floorplan_engine.model.geometry import (
    ANGLE_TOLERANCE_DEG,
    CLOSURE_TOLERANCE_MM,
    Contour,
    closure_suspects,
    expected_angle_sum,
    self_intersections,
    trace_contour,
)
from floorplan_engine.model.schema import (
    OpeningType,
    Plan,
    Room,
)
from floorplan_engine.validation.issues import (
    ROOM_FILE,
    Issue,
    Severity,
)


def _wall_list(ids: Sequence[str]) -> str:
    return ", ".join(ids)


def no_wall(room: Room, wall: str, path: str, file: str) -> Issue:
    known = _wall_list([w.id for w in room.walls])
    return Issue(file, path, f"стены «{wall}» нет в комнате «{room.name}» (есть: {known})")


def duplicates(
    ids: Iterable[tuple[str, str]], file: str, what: str, taken: dict[str, str] | None = None
) -> list[Issue]:
    """Повторы id: пары (путь к полю id, значение) в порядке появления.

    `taken` — уже занятые id (значение → где занят), сами они не проверяются.
    """
    seen: dict[str, str] = dict(taken or {})
    issues: list[Issue] = []
    for path, value in ids:
        if value in seen:
            issues.append(Issue(file, path, f"{what} «{value}» уже есть в {seen[value]}"))
        else:
            seen[value] = path.removesuffix(".id")
    return issues


def check_contour(room: Room, contour: Contour, path: str, file: str) -> list[Issue]:
    issues: list[Issue] = []
    n = len(room.walls)
    if abs(contour.angle_sum_error) > ANGLE_TOLERANCE_DEG:
        actual = sum(w.turn for w in room.walls)
        issues.append(
            Issue(
                file,
                f"{path}.walls[*].turn",
                f"углы не сходятся: для {n} стен сумма внутренних углов turn должна быть "
                f"{expected_angle_sum(n):g}°, сейчас {actual:g}°. "
                "Проверьте углы 270° (входящие) и 90° (обычные)",
            )
        )
    gap = contour.gap
    if contour.closure_error > CLOSURE_TOLERANCE_MM:
        msg = (
            f"контур «{room.name}» не замыкается: невязка ΔX = {gap.x:+.0f} мм, "
            f"ΔY = {gap.y:+.0f} мм (всего {contour.closure_error:.0f} мм, "
            f"допуск {CLOSURE_TOLERANCE_MM:g} мм)."
        )
        suspects = closure_suspects(contour)
        exact = [s for s in suspects if s.fixed_length is not None]
        if exact:
            options = "; ".join(
                f"стена {s.wall}: {s.current_length:g} → {s.fixed_length:g} мм" for s in exact
            )
            msg += f" Замкнётся, если исправить одну из стен — {options}."
        elif suspects:
            msg += f" Вероятно неверны стены: {_wall_list([s.wall for s in suspects])}."
        horiz = [s.id for s in contour.segments if abs(s.direction.x) > 0.5]
        vert = [s.id for s in contour.segments if abs(s.direction.y) > 0.5]
        if abs(gap.x) > CLOSURE_TOLERANCE_MM and horiz:
            msg += f" Невязку по X дают горизонтальные стены {_wall_list(horiz)}."
        if abs(gap.y) > CLOSURE_TOLERANCE_MM and vert:
            msg += f" Невязку по Y дают вертикальные стены {_wall_list(vert)}."
        msg += " Размеры не подгоняются автоматически — уточните, какой размер неверный."
        issues.append(Issue(file, f"{path}.walls", msg))
    elif contour.closure_error > 0.5:
        issues.append(
            Issue(
                file,
                f"{path}.walls",
                f"невязка контура {contour.closure_error:.1f} мм — в пределах допуска "
                f"{CLOSURE_TOLERANCE_MM:g} мм",
                Severity.WARNING,
            )
        )
    if not issues:
        for i, j in self_intersections(contour):
            issues.append(
                Issue(file, f"{path}.walls", f"стены {i} и {j} пересекаются — контур перекручен")
            )
    return issues


def check_openings(room: Room, path: str, file: str) -> list[Issue]:
    issues: list[Issue] = []
    by_wall: dict[str, list[tuple[int, float, float]]] = {}
    for k, op in enumerate(room.openings):
        p = f"{path}.openings[{k}]"
        index = room.wall_index(op.wall)
        if index is None:
            issues.append(no_wall(room, op.wall, f"{p}.wall", file))
            continue
        length = room.walls[index].length
        end = op.offset + op.width
        if end > length + 1e-6:
            issues.append(
                Issue(
                    file,
                    p,
                    f"{opening_name(op.type)} выходит за стену {op.wall}: offset {op.offset:g} + "
                    f"width {op.width:g} = {end:g} мм, а длина стены {length:g} мм "
                    f"(лишние {end - length:g} мм)",
                )
            )
        if op.type is OpeningType.WINDOW and op.sill is None:
            issues.append(
                Issue(file, f"{p}.sill", "не указана высота подоконника", Severity.WARNING)
            )
        by_wall.setdefault(op.wall, []).append((k, op.offset, end))
    for wall, spans in by_wall.items():
        spans.sort(key=lambda s: s[1])
        for (k1, _s1, e1), (k2, s2, _e2) in itertools.pairwise(spans):
            if s2 < e1 - 1e-6:
                issues.append(
                    Issue(
                        file,
                        f"{path}.openings[{k2}]",
                        f"проём перекрывается с openings[{k1}] на стене {wall} на {e1 - s2:g} мм",
                    )
                )
    return issues


def opening_name(kind: OpeningType) -> str:
    return {"door": "дверь", "window": "окно", "opening": "проём"}[kind.value]


def validate_plan(plan: Plan, file: str = ROOM_FILE) -> tuple[list[Issue], dict[str, Contour]]:
    issues: list[Issue] = []
    contours: dict[str, Contour] = {}
    seen: dict[str, int] = {}
    for r, room in enumerate(plan.rooms):
        path = f"rooms[{r}]"
        if room.id in seen:
            issues.append(
                Issue(file, f"{path}.id", f"id «{room.id}» уже есть в rooms[{seen[room.id]}]")
            )
        seen.setdefault(room.id, r)
        issues += duplicates(
            ((f"{path}.walls[{w}].id", wall.id) for w, wall in enumerate(room.walls)),
            file,
            "стена",
        )
        contour = trace_contour(room, plan.default_wall_thickness)
        contours[room.id] = contour
        issues += check_contour(room, contour, path, file)
        issues += check_openings(room, path, file)
    issues += duplicates(
        (
            (f"rooms[{r}].openings[{k}].id", op.id)
            for r, room in enumerate(plan.rooms)
            for k, op in enumerate(room.openings)
        ),
        file,
        "id",
    )
    return issues, contours
