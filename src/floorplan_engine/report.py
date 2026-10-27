"""Отчёт по проекту для человека (report.md) и для сервиса (report.json).

Итог по этапам, открытые вопросы по весу, ответы, ошибки и предупреждения валидации.
"""

from __future__ import annotations

import json
from typing import Any

from floorplan_engine.assess import STATUS_TEXT, StageResult, severity
from floorplan_engine.intake import QSeverity, Question
from floorplan_engine.validate import Report

REPORT_MD = "report.md"
REPORT_JSON = "report.json"

STAGE_TEXT = {
    "plan": "План",
    "electrical": "Электрика",
    "furniture": "Мебель",
    "lighting": "Освещение",
    "power": "Розетки",
    "wiring": "Проводка",
    "plumbing": "Вода и канализация",
    "panel": "Щит",
}
SEVERITY_TEXT = {
    QSeverity.CRITICAL: "Критичные — без ответа этап не строится",
    QSeverity.MAJOR: "Важные — построено по допущению",
    QSeverity.MINOR: "Уточнения",
}
STATE_TEXT = {
    "answered": "ответ подставлен",
    "accepted": "оставлено допущение",
    "text": "текстовый ответ — ждёт разбора",
}


UNIT_TEXT = {"mm": "мм"}


def _cell(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = "—" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _answer_hint(q: Question) -> str:
    if q.answer == "value":
        unit = UNIT_TEXT.get(q.unit, q.unit) if q.unit else ""
        return f"число{', ' + unit if unit else ''}"
    if q.answer == "choice":
        return " / ".join(q.options)
    return "текст"


def render_markdown(name: str, report: Report, results: list[StageResult]) -> str:
    lines = [f"# Отчёт по проекту «{name}»", "", "## Этапы", ""]
    lines += ["| Этап | Статус | Критичных | Важных | Уточнений | Вес | Причина |"]
    lines += ["| --- | --- | --- | --- | --- | --- | --- |"]
    for r in results:
        lines.append(
            f"| {STAGE_TEXT[r.stage.value]} | {STATUS_TEXT[r.status]} "
            f"| {r.count(QSeverity.CRITICAL)} | {r.count(QSeverity.MAJOR)} "
            f"| {r.count(QSeverity.MINOR)} | {r.weight} | {_cell(r.reason)} |"
        )
    open_q = [q for r in results for q in r.open_questions]
    for level in QSeverity:
        group = [q for q in open_q if severity(q) is level]
        if not group:
            continue
        lines += ["", f"## {SEVERITY_TEXT[level]}", ""]
        lines += ["| id | Этап | Вопрос | Поле | Сейчас в модели | Ответ |"]
        lines += ["| --- | --- | --- | --- | --- | --- |"]
        for q in group:
            note = (
                " (ответ получен, ждёт разбора)"
                if report.question_states.get(q.id) == "text"
                else ""
            )
            lines.append(
                f"| {q.id} | {STAGE_TEXT[q.stage.value]} | {_cell(q.text)}{note} "
                f"| {_cell(q.target)} | {_cell(q.assumption)} | {_answer_hint(q)} |"
            )
    closed = [
        q
        for q in report.questions
        if report.question_states.get(q.id) in STATE_TEXT and report.question_states[q.id] != "text"
    ]
    if closed:
        lines += ["", "## Закрытые вопросы", "", "| id | Вопрос | Итог |", "| --- | --- | --- |"]
        for q in closed:
            state = report.question_states[q.id]
            lines.append(f"| {q.id} | {_cell(q.text)} | {STATE_TEXT[state]} |")
    if report.issues:
        lines += ["", "## Проверка данных", ""]
        lines += [f"- {issue}" for issue in report.issues]
    return "\n".join(lines) + "\n"


def to_json(name: str, report: Report, results: list[StageResult]) -> str:
    data: dict[str, Any] = {
        "project": name,
        "stages": [
            {
                "stage": r.stage.value,
                "status": r.status.value,
                "builds": r.status.builds,
                "reason": r.reason,
                "weight": r.weight,
                "questions": [q.id for q in r.open_questions],
            }
            for r in results
        ],
        "questions": [
            {
                **q.model_dump(mode="json", exclude_none=True),
                "severity": severity(q).value,
                "state": report.question_states.get(q.id, "open"),
            }
            for q in report.questions
        ],
        "issues": [
            {
                "file": i.file,
                "path": i.path,
                "severity": i.severity.name.lower(),
                "message": i.message,
            }
            for i in report.issues
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
