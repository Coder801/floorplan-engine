"""Plumbing work stages (docs/work-tasks.md): the plumbing estimate split into installation tasks
by the template stages.yaml next to this module, with the same rules and draft as electrical
(electrical/stages.py). Plumbing has no work scope catalogue, so every stage has its own result.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

from floorplan_engine.electrical.estimate import Estimate
from floorplan_engine.electrical.stages import DraftTask, StageCatalog, draft_tasks, parse_stages
from floorplan_engine.model.texts import Language
from floorplan_engine.plumbing.estimate import LINES

STAGES_FILE = Path(__file__).with_name("stages.yaml")


@cache
def load_stages() -> StageCatalog:
    """The plumbing template shipped with the code (stages.yaml)."""
    return parse_stages(yaml.safe_load(STAGES_FILE.read_text("utf-8")), LINES)


def plumbing_draft(est: Estimate, language: Language) -> list[DraftTask]:
    """Draft tasks of the plumbing estimate."""
    return draft_tasks(est, load_stages(), LINES, "plumbing", language)
