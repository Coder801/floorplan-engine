"""The work plan draft of a project: the electrical and plumbing estimates split into installation
tasks (electrical/stages.py, plumbing/stages.py) — the .epd manifest key `work_plan`
(docs/epd-format.md, docs/work-tasks.md). The service makes its tasks from it; the core knows
nothing about tasks in the database.

Tasks of both sections go in one list by stage number, electrical first on a tie: chases of
both trades come before cable and pipes. Electrical and plumbing do not depend on each other.
"""

from __future__ import annotations

from typing import Any

from floorplan_engine.electrical.estimate import Estimate
from floorplan_engine.electrical.stages import DraftTask, electrical_draft
from floorplan_engine.model.texts import Language
from floorplan_engine.plumbing.stages import plumbing_draft

DOMAINS = ("electrical", "plumbing")  # order of sections on a tie


def draft_tasks(
    electrical: Estimate | None, plumbing: Estimate | None, language: Language
) -> list[DraftTask]:
    tasks = electrical_draft(electrical, language) if electrical is not None else []
    if plumbing is not None:
        tasks += plumbing_draft(plumbing, language)
    return sorted(tasks, key=lambda t: (t.order, DOMAINS.index(t.domain)))


def work_plan(
    electrical: Estimate | None, plumbing: Estimate | None, language: Language
) -> dict[str, Any] | None:
    """The `work_plan` key: currency and tasks; None if neither estimate has a line."""
    tasks = draft_tasks(electrical, plumbing, language)
    if not tasks:
        return None
    currency = next(e.currency for e in (electrical, plumbing) if e is not None)
    return {"currency": currency, "tasks": [t.as_dict() for t in tasks]}
