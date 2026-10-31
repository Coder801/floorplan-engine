"""Наложение на модель: профиль студии (projects/studio.yaml), ответы из answers.yaml в
поля по `target`, автоответы на вопросы, которые составляет код (вопросы щита)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from floorplan_engine.electrical.lines import split_by_lines
from floorplan_engine.electrical.panel import build_panel
from floorplan_engine.electrical.panel_questions import AUTO_PREFIX, panel_questions
from floorplan_engine.model.intake import (
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
    set_target,
)
from floorplan_engine.model.schema import (
    Electrical,
    Plan,
    Studio,
)
from floorplan_engine.validation.issues import (
    ELECTRICAL_FILE,
    ROOM_FILE,
    Issue,
    M,
    QuestionState,
    Severity,
    format_value,
    load_yaml,
    parse_model,
)
from floorplan_engine.validation.plan import (
    validate_plan,
)

STAGE_FILE = {Stage.PLAN: ROOM_FILE, Stage.ELECTRICAL: ELECTRICAL_FILE}


def load_optional(path: Path, model: type[M]) -> tuple[M | None, list[Issue]]:
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
    studio, issues = load_optional(path, Studio)
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
            issues.append(Issue(ANSWERS_FILE, path, f"ожидается число{format_value(answer)}"))
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
                issues.append(Issue(ANSWERS_FILE, path, f"ожидается число{format_value(answer)}"))
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
