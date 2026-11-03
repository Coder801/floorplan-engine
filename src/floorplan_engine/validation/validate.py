"""Проверка проекта целиком до отрисовки: загрузка моделей, профиль студии и ответы,
проверки плана и электрики по этапам, отчёт (Report). Сообщения — по-русски, с путём к полю
в YAML; сами проверки — validation/plan.py и validation/electrical.py, замечания и загрузка —
validation/issues.py, ответы — validation/answers.py.

Ничего не подгоняется молча: при невязке контура выдаётся ошибка с её величиной
и списком стен, которые вероятно заданы неверно.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from floorplan_engine.electrical.lines import split_by_lines
from floorplan_engine.electrical.panel_questions import AUTO_PREFIX
from floorplan_engine.electrical.variants import (
    apply_variant,
    default_variant,
    project_routes,
)
from floorplan_engine.model.geometry import (
    Contour,
)
from floorplan_engine.model.intake import (
    ANSWERS_FILE,
    INTAKE_FILE,
    Answers,
    Intake,
    Question,
    Stage,
    index_path,
)
from floorplan_engine.model.plumbing import PLUMBING_FILE, Plumbing
from floorplan_engine.model.schema import (
    Electrical,
    Plan,
    Variant,
    WiringEdits,
    WiringFile,
)
from floorplan_engine.validation.answers import (
    STAGE_FILE,
    apply_answers,
    apply_auto_answers,
    apply_studio,
    load_optional,
)
from floorplan_engine.validation.electrical import validate_electrical
from floorplan_engine.validation.issues import (
    ELECTRICAL_FILE,
    ROOM_FILE,
    STUDIO_FILE,
    VARIANT_FILE,
    WIRING_FILE,
    Issue,
    QuestionState,
    Severity,
    load_yaml,
    parse_model,
)
from floorplan_engine.validation.plan import validate_plan
from floorplan_engine.validation.plumbing import validate_plumbing


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    plan: Plan | None = None
    electrical: Electrical | None = None
    plumbing: Plumbing | None = None  # plumbing.yaml — вода и канализация
    contours: dict[str, Contour] = field(default_factory=dict)
    intake: Intake | None = None
    # open — нет ответа; answered — значение подставлено; accepted — оставлено допущение;
    # text — текстовый ответ ждёт анализатора
    question_states: dict[str, QuestionState] = field(default_factory=dict)
    wiring_edits: WiringEdits | None = None  # правки выбранного варианта; сверка — при сборке
    wiring_file: WiringFile | None = None  # wiring.yaml целиком: правки всех вариантов
    # Вариант проводки (docs/wiring-variants.md): выбранный в просмотре (variant.yaml) или
    # «как в проекте»; source_electrical — электрика из electrical.yaml до варианта
    variant: Variant | None = None
    default_variant: Variant | None = None
    source_electrical: Electrical | None = None
    # Вопросы щита, составленные кодом по расчёту (panel_questions.panel_questions), id «panel_…»
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


# --- Правила плана -----------------------------------------------------------


# --- Правила электрики -------------------------------------------------------


# --- Проект целиком ----------------------------------------------------------


# --- Вопросы и ответы ---------------------------------------------------------


def validate_project(project_dir: Path) -> Report:
    """Загрузить и проверить проект: intake, ответы, план, электрику."""
    report = Report()
    intake, issues = load_optional(project_dir / INTAKE_FILE, Intake)
    report.issues += issues
    report.intake = intake
    answers, issues = load_optional(project_dir / ANSWERS_FILE, Answers)
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
    for stage, name in ((Stage.ELECTRICAL, ELECTRICAL_FILE), (Stage.PLUMBING, PLUMBING_FILE)):
        path = project_dir / name
        if path.exists():
            data, issues = load_yaml(path)
            report.issues += issues
            if data is not None:
                raw[stage] = data
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
    chosen, issues = load_optional(project_dir / VARIANT_FILE, Variant)
    report.issues += [
        Issue(i.file, i.path, f"{i.message} — вариант «как в проекте»", Severity.WARNING)
        for i in issues
    ]
    if chosen is not None and chosen.ceiling_height is not None:
        # Правка из просмотра: поле считается заданным (не допущение 2700)
        plan = plan.model_copy(update={"ceiling_height": chosen.ceiling_height})
    report.plan = plan
    issues, report.contours = validate_plan(plan)
    report.issues += issues
    _validate_electrical(report, raw, project_dir, plan, chosen)
    if Stage.PLUMBING in raw:
        plumbing, issues = parse_model(Plumbing, raw[Stage.PLUMBING], PLUMBING_FILE)
        report.issues += issues
        if plumbing is not None:
            report.plumbing = plumbing
            report.issues += validate_plumbing(
                plumbing, plan, report.contours, report.source_electrical
            )


def _validate_electrical(
    report: Report, raw: dict[Stage, Any], project_dir: Path, plan: Plan, chosen: Variant | None
) -> None:
    if Stage.ELECTRICAL not in raw:
        return
    elec, issues = parse_model(Electrical, raw[Stage.ELECTRICAL], ELECTRICAL_FILE)
    report.issues += issues
    if elec is None:
        return
    report.source_electrical = elec
    report.default_variant = default_variant(elec)
    if chosen is not None and chosen.route not in project_routes(elec):
        report.issues.append(
            Issue(
                VARIANT_FILE,
                "route",
                f"трассы «{chosen.route}» в проекте нет (electrical.yaml routes) — "
                "вариант «как в проекте»",
                Severity.WARNING,
            )
        )
        chosen = None
    report.variant = chosen or report.default_variant
    elec = apply_variant(elec, report.variant)
    report.electrical = elec
    elec_issues = validate_electrical(elec, plan, report.contours)
    report.issues += elec_issues
    if not any(i.severity is Severity.ERROR for i in [*report.issues, *elec_issues]):
        # premium и proper: у каждой линии от щита — своя группа (lines.py)
        report.electrical = split_by_lines(plan, report.contours, elec)
    # Ошибка в правках проводки сборку не останавливает: проводка строится автоматически
    wiring_file, issues = load_optional(project_dir / WIRING_FILE, WiringFile)
    report.issues += [
        Issue(i.file, i.path, f"{i.message} — правки проводки не применены", Severity.WARNING)
        for i in issues
    ]
    report.wiring_file = wiring_file
    if wiring_file is not None:
        report.wiring_edits = wiring_file.edits_for(report.variant.key, report.default_variant.key)
