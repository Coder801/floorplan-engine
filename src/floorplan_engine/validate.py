"""Валидация проекта до отрисовки. Сообщения — по-русски, с путём к полю в YAML.

Ничего не подгоняется молча: при невязке контура выдаётся ошибка с её величиной
и списком стен, которые вероятно заданы неверно.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from floorplan_engine.geometry import (
    ANGLE_TOLERANCE_DEG,
    CLOSURE_TOLERANCE_MM,
    Contour,
    Vec,
    closure_suspects,
    expected_angle_sum,
    point_in_polygon,
    self_intersections,
    trace_contour,
)
from floorplan_engine.intake import (
    ANSWERS_FILE,
    INTAKE_FILE,
    Accept,
    Answers,
    Intake,
    Question,
    Stage,
    TargetError,
    TextAnswer,
    get_target,
    index_path,
    set_target,
)
from floorplan_engine.lines import split_by_lines
from floorplan_engine.panel import AUTO_PREFIX, build_panel, panel_questions
from floorplan_engine.schema import (
    Board,
    Electrical,
    ElectricalPoint,
    OpeningType,
    Plan,
    PointType,
    Room,
    Studio,
    WiringEdits,
)

ROOM_FILE = "room.yaml"
ELECTRICAL_FILE = "electrical.yaml"
WIRING_FILE = "wiring.yaml"  # ручные правки проводки из просмотра (линии, коробки)
STUDIO_FILE = "studio.yaml"  # профиль студии — в папке над проектами
HEIGHT_MIN_MM = 0.0
HEIGHT_MAX_MM = 3000.0

M = TypeVar("M", bound=BaseModel)


class Severity(StrEnum):
    ERROR = "ошибка"
    WARNING = "предупреждение"


@dataclass(frozen=True)
class Issue:
    file: str
    path: str
    message: str
    severity: Severity = Severity.ERROR

    def __str__(self) -> str:
        where = f"{self.file}: {self.path}" if self.path else self.file
        return f"[{self.severity.value}] {where}: {self.message}"


QuestionState = Literal["open", "answered", "accepted", "text"]


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    plan: Plan | None = None
    electrical: Electrical | None = None
    contours: dict[str, Contour] = field(default_factory=dict)
    intake: Intake | None = None
    # open — нет ответа; answered — значение подставлено; accepted — оставлено допущение;
    # text — текстовый ответ ждёт анализатора
    question_states: dict[str, QuestionState] = field(default_factory=dict)
    wiring_edits: WiringEdits | None = None  # wiring.yaml; сверка с проводкой — при сборке
    # Вопросы щита, составленные кодом по расчёту (panel.panel_questions), id «panel_…»
    auto_questions: list[Question] = field(default_factory=list)

    @property
    def questions(self) -> list[Question]:
        """Все вопросы проекта: из intake.yaml и составленные кодом."""
        return [*(self.intake.questions if self.intake else []), *self.auto_questions]

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors


# --- Загрузка YAML и перевод ошибок pydantic ---------------------------------


def format_loc(loc: Iterable[int | str]) -> str:
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else part
    return out


def _fmt_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return ""
    return f" (указано: {value!r})"


def _translate(err: Any) -> str:
    kind: str = err["type"]
    ctx: dict[str, Any] = err.get("ctx") or {}
    given = _fmt_value(err.get("input"))
    match kind:
        case "missing":
            return "обязательное поле не заполнено"
        case "extra_forbidden":
            return "неизвестное поле — опечатка или лишний ключ"
        case "greater_than":
            return f"должно быть больше {ctx['gt']}{given}"
        case "greater_than_equal":
            return f"должно быть не меньше {ctx['ge']}{given}"
        case "less_than":
            return f"должно быть меньше {ctx['lt']}{given}"
        case "less_than_equal":
            return f"должно быть не больше {ctx['le']}{given}"
        case "float_parsing" | "float_type" | "int_parsing" | "int_type":
            return f"ожидается число{given}"
        case "int_from_float":
            return f"ожидается целое число{given}"
        case "string_type":
            return f"ожидается строка{given}"
        case "bool_parsing" | "bool_type":
            return f"ожидается true или false{given}"
        case "literal_error" | "enum":
            return f"допустимые значения: {ctx.get('expected', '?')}{given}"
        case "string_pattern_mismatch":
            return f"допустимы только латиница, цифры, _ и -{given}"
        case "string_too_short":
            return "не может быть пустым"
        case "too_short":
            return f"нужно минимум {ctx.get('min_length')} элемента(ов)"
        case "too_long":
            return f"нужно не больше {ctx.get('max_length')} элемента(ов)"
        case "list_type":
            return "ожидается список (- ... или [ ... ])"
        case "tuple_type":
            return "ожидается пара координат [x, y]"
        case "model_type" | "dict_type" | "model_attributes_type":
            return "ожидается объект { ключ: значение }"
        case "value_error":
            return str(err["msg"]).removeprefix("Value error, ")
        case _:
            return str(err["msg"])


def parse_model(model: type[M], data: Any, file: str) -> tuple[M | None, list[Issue]]:
    try:
        return model.model_validate(data), []
    except ValidationError as exc:
        issues = [Issue(file, format_loc(e["loc"]), _translate(e)) for e in exc.errors()]
        return None, issues


def load_yaml(path: Path) -> tuple[Any, list[Issue]]:
    file = path.name
    if not path.exists():
        return None, [Issue(file, "", f"файл не найден: {path}")]
    try:
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark
        where = f"строка {mark.line + 1}, столбец {mark.column + 1}" if mark else ""
        return None, [Issue(file, where, f"синтаксическая ошибка YAML: {exc.problem}")]
    except yaml.YAMLError as exc:
        return None, [Issue(file, "", f"синтаксическая ошибка YAML: {exc}")]
    if data is None:
        return None, [Issue(file, "", "файл пустой")]
    return data, []


# --- Правила плана -----------------------------------------------------------


def _wall_list(ids: Sequence[str]) -> str:
    return ", ".join(ids)


def _no_wall(room: Room, wall: str, path: str, file: str) -> Issue:
    known = _wall_list([w.id for w in room.walls])
    return Issue(file, path, f"стены «{wall}» нет в комнате «{room.name}» (есть: {known})")


def _duplicates(
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
            issues.append(_no_wall(room, op.wall, f"{p}.wall", file))
            continue
        length = room.walls[index].length
        end = op.offset + op.width
        if end > length + 1e-6:
            issues.append(
                Issue(
                    file,
                    p,
                    f"{_opening_name(op.type)} выходит за стену {op.wall}: offset {op.offset:g} + "
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


def _opening_name(kind: OpeningType) -> str:
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
        issues += _duplicates(
            ((f"{path}.walls[{w}].id", wall.id) for w, wall in enumerate(room.walls)),
            file,
            "стена",
        )
        contour = trace_contour(room, plan.default_wall_thickness)
        contours[room.id] = contour
        issues += check_contour(room, contour, path, file)
        issues += check_openings(room, path, file)
    issues += _duplicates(
        (
            (f"rooms[{r}].openings[{k}].id", op.id)
            for r, room in enumerate(plan.rooms)
            for k, op in enumerate(room.openings)
        ),
        file,
        "id",
    )
    return issues, contours


# --- Правила электрики -------------------------------------------------------


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


def _check_wall_anchor(
    plan: Plan, room_id: str, wall: str, offset: float, path: str, file: str
) -> list[Issue]:
    room = next((r for r in plan.rooms if r.id == room_id), None)
    if room is None:
        known = ", ".join(r.id for r in plan.rooms)
        return [Issue(file, f"{path}.room", f"комнаты «{room_id}» нет в room.yaml (есть: {known})")]
    index = room.wall_index(wall)
    if index is None:
        return [_no_wall(room, wall, f"{path}.wall", file)]
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
                    f"точка попадает в {_opening_name(op.type)} "
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
    issues += _duplicates(
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


# --- Проект целиком ----------------------------------------------------------


# --- Вопросы и ответы ---------------------------------------------------------

STAGE_FILE = {Stage.PLAN: ROOM_FILE, Stage.ELECTRICAL: ELECTRICAL_FILE}


def _load_optional(path: Path, model: type[M]) -> tuple[M | None, list[Issue]]:
    if not path.exists():
        return None, []
    data, issues = load_yaml(path)
    if data is None:
        return None, issues
    return parse_model(model, data, path.name)


def apply_studio(path: Path, raw: dict[Stage, Any]) -> list[Issue]:
    """Графы штампа из профиля студии — в `sheet` плана, где они не заполнены (raw меняется
    на месте). Заполненное в room.yaml важнее профиля."""
    plan = raw.get(Stage.PLAN)
    studio, issues = _load_optional(path, Studio)
    if studio is None or not isinstance(plan, dict):
        return issues
    sheet = plan.setdefault("sheet", {})
    if not isinstance(sheet, dict):
        return issues  # ошибку типа покажет проверка room.yaml
    for key, value in studio.model_dump(exclude_defaults=True).items():
        if not sheet.get(key):
            sheet[key] = value
    return issues


def apply_answers(
    intake: Intake, answers: Answers, raw: dict[Stage, Any]
) -> tuple[dict[str, QuestionState], list[Issue]]:
    """Наложить ответы на сырые данные этапов (raw меняется на месте).

    Значение и выбор подставляются в target вопроса; текст ждёт анализатора;
    accept оставляет допущение. Исходные YAML не переписываются.
    """
    issues: list[Issue] = []
    states: dict[str, QuestionState] = {q.id: "open" for q in intake.questions}
    by_id = {q.id: q for q in intake.questions}
    for k, q in enumerate(intake.questions):
        data = raw.get(q.stage)
        if q.target is None or data is None:
            continue
        paths = [("target", q.target), *((f"also[{n}]", t) for n, t in enumerate(q.also))]
        for key, target in paths:
            try:
                get_target(data, target)
            except TargetError as exc:
                issues.append(Issue(INTAKE_FILE, f"questions[{k}].{key}", str(exc)))
    for qid, answer in answers.answers.items():
        if qid.startswith(AUTO_PREFIX):
            continue  # вопрос щита — его составит код (apply_auto_answers)
        path = f"answers.{qid}"
        question = by_id.get(qid)
        if question is None:
            issues.append(Issue(ANSWERS_FILE, path, f"вопроса «{qid}» нет в {INTAKE_FILE}"))
            continue
        if isinstance(answer, Accept):
            states[qid] = "accepted"
            continue
        if isinstance(answer, TextAnswer):
            states[qid] = "answered" if answer.resolved else "text"
            continue
        if question.answer == "text":
            issues.append(Issue(ANSWERS_FILE, path, "на этот вопрос нужен ответ { text: ... }"))
            continue
        if question.answer == "value" and not isinstance(answer, float):
            issues.append(Issue(ANSWERS_FILE, path, f"ожидается число{_fmt_value(answer)}"))
            continue
        if question.answer == "choice" and answer not in question.options:
            issues.append(
                Issue(ANSWERS_FILE, path, f"допустимые ответы: {', '.join(question.options)}")
            )
            continue
        data = raw.get(question.stage)
        assert question.target is not None  # value и choice без target запрещает схема
        if data is None:
            issues.append(
                Issue(ANSWERS_FILE, path, f"нет {STAGE_FILE.get(question.stage, question.stage)}")
            )
            continue
        try:
            for target in (question.target, *question.also):
                set_target(data, target, answer)
        except TargetError as exc:
            issues.append(Issue(ANSWERS_FILE, path, str(exc)))
            continue
        states[qid] = "answered"
    return states, issues


def validate_project(project_dir: Path) -> Report:
    """Загрузить и проверить проект: intake, ответы, план, электрику."""
    report = Report()
    intake, issues = _load_optional(project_dir / INTAKE_FILE, Intake)
    report.issues += issues
    report.intake = intake
    answers, issues = _load_optional(project_dir / ANSWERS_FILE, Answers)
    report.issues += issues
    own = [k for k in (answers.answers if answers else {}) if not k.startswith(AUTO_PREFIX)]
    if own and intake is None:
        report.issues.append(Issue(ANSWERS_FILE, "", f"есть ответы, но нет {INTAKE_FILE}"))

    raw: dict[Stage, Any] = {}
    room_path = project_dir / ROOM_FILE
    if room_path.exists() or intake is None:
        data, issues = load_yaml(room_path)
        report.issues += issues
        if data is not None:
            raw[Stage.PLAN] = data
    elec_path = project_dir / ELECTRICAL_FILE
    if elec_path.exists():
        data, issues = load_yaml(elec_path)
        report.issues += issues
        if data is not None:
            raw[Stage.ELECTRICAL] = data
    report.issues += apply_studio(project_dir.parent / STUDIO_FILE, raw)
    if intake is not None:
        report.question_states, issues = apply_answers(intake, answers or Answers(), raw)
        report.issues += issues
        covered = _question_paths(intake, raw)
    else:
        covered = set()
    report.auto_questions, states, issues = apply_auto_answers(answers or Answers(), raw)
    report.question_states.update(states)
    report.issues += issues
    _validate_stages(report, raw, project_dir)
    # Предупреждение о поле, по которому уже есть вопрос, дублирует вопрос
    report.issues = [
        i for i in report.issues if i.severity is Severity.ERROR or (i.file, i.path) not in covered
    ]
    return report


def auto_questions(raw: dict[Stage, Any]) -> list[Question]:
    """Вопросы щита по сырым данным этапов: план и электрика разбираются молча — их ошибки
    покажет проверка."""
    plan_data, elec_data = raw.get(Stage.PLAN), raw.get(Stage.ELECTRICAL)
    if plan_data is None or elec_data is None:
        return []
    try:
        plan = Plan.model_validate(plan_data)
        elec = Electrical.model_validate(elec_data)
    except ValidationError:
        return []
    issues, contours = validate_plan(plan)
    if not any(i.severity is Severity.ERROR for i in issues):
        elec = split_by_lines(plan, contours, elec)
    panel = build_panel(plan, elec)
    return panel_questions(elec, panel) if panel is not None else []


def apply_auto_answers(
    answers: Answers, raw: dict[Stage, Any]
) -> tuple[list[Question], dict[str, QuestionState], list[Issue]]:
    """Вопросы щита и ответы на них. Значение и выбор подставляются в `panel` электрики
    (raw меняется на месте), после чего вопросы составляются заново: отвеченные поля
    вопросов уже не дают, а раздел щита может измениться (резерв, линии)."""
    states: dict[str, QuestionState] = {}
    issues: list[Issue] = []

    def apply(questions: list[Question]) -> None:
        for q in questions:
            answer = answers.answers.get(q.id)
            path = f"answers.{q.id}"
            if answer is None:
                states.setdefault(q.id, "open")
            elif isinstance(answer, Accept):
                states[q.id] = "accepted"
            elif isinstance(answer, TextAnswer):
                states[q.id] = "answered" if answer.resolved else "text"
            elif q.answer == "text":
                issues.append(Issue(ANSWERS_FILE, path, "на этот вопрос нужен ответ { text: ... }"))
            elif q.answer == "choice" and answer not in q.options:
                issues.append(
                    Issue(ANSWERS_FILE, path, f"допустимые ответы: {', '.join(q.options)}")
                )
            elif q.answer == "value" and not isinstance(answer, float):
                issues.append(Issue(ANSWERS_FILE, path, f"ожидается число{_fmt_value(answer)}"))
            else:
                elec = raw.get(Stage.ELECTRICAL)
                assert q.target is not None and isinstance(elec, dict)
                panel = elec.setdefault("panel", {})
                if isinstance(panel, dict):
                    value = int(answer) if q.answer == "value" else answer
                    panel[q.target.removeprefix("panel.")] = value
                    states[q.id] = "answered"

    first = auto_questions(raw)
    apply(first)
    final = auto_questions(raw)
    apply(final)
    ids = {q.id for q in final}
    # Отвеченный вопрос поля больше не составляется — показываем его отвеченным
    final += [q for q in first if q.id not in ids and states.get(q.id) == "answered"]
    known = {q.id for q in final}
    for qid in answers.answers:
        if qid.startswith(AUTO_PREFIX) and qid not in known:
            issues.append(
                Issue(
                    ANSWERS_FILE,
                    f"answers.{qid}",
                    "вопроса щита больше нет — ответ не нужен",
                    Severity.WARNING,
                )
            )
    return final, {k: v for k, v in states.items() if k in known}, issues


def _question_paths(intake: Intake, raw: dict[Stage, Any]) -> set[tuple[str, str]]:
    """(файл, путь по индексам) всех полей, по которым есть вопросы."""
    out: set[tuple[str, str]] = set()
    for q in intake.questions:
        data, file = raw.get(q.stage), STAGE_FILE.get(q.stage)
        if q.target is None or data is None or file is None:
            continue
        for target in (q.target, *q.also):
            try:
                out.add((file, index_path(data, target)))
            except StopIteration:
                continue  # несуществующий target уже отмечен ошибкой
    return out


def _validate_stages(report: Report, raw: dict[Stage, Any], project_dir: Path) -> None:

    if Stage.PLAN not in raw:
        return
    plan, issues = parse_model(Plan, raw[Stage.PLAN], ROOM_FILE)
    report.issues += issues
    if plan is None:
        return
    report.plan = plan
    issues, report.contours = validate_plan(plan)
    report.issues += issues

    if Stage.ELECTRICAL not in raw:
        return
    elec, issues = parse_model(Electrical, raw[Stage.ELECTRICAL], ELECTRICAL_FILE)
    report.issues += issues
    if elec is None:
        return
    report.electrical = elec
    elec_issues = validate_electrical(elec, plan, report.contours)
    report.issues += elec_issues
    if not any(i.severity is Severity.ERROR for i in [*report.issues, *elec_issues]):
        # premium и proper: у каждой линии от щита — своя группа (lines.py)
        report.electrical = split_by_lines(plan, report.contours, elec)
    # Ошибка в правках проводки сборку не останавливает: проводка строится автоматически
    edits, issues = _load_optional(project_dir / WIRING_FILE, WiringEdits)
    report.issues += [
        Issue(i.file, i.path, f"{i.message} — правки проводки не применены", Severity.WARNING)
        for i in issues
    ]
    report.wiring_edits = edits
