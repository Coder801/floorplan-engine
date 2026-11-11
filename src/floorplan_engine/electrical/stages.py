"""Work stages: the estimate split into installation tasks (docs/work-tasks.md, "Черновик из
сметы").

The template is data (stages.yaml next to this module, plumbing/stages.yaml for plumbing): every
estimate item, by its base key (estimate.split_key: `work.chase.brick` goes as `work.chase`),
belongs to exactly one stage. Unknown keys and keys in two stages are errors (StageCatalog);
every key of LINES must have a stage (unstaged, a test), like missing_scope of the work scope.

A draft task is a stage with the lines of this estimate: a stage without lines is left out, and a
task that was to come after it comes after that stage's own predecessors. The acceptance
criterion is the stage's `result`, or else the `result` of its work items in work_scope.yaml.
The draft is a property of the estimate: the same model gives the same draft
(pipeline/work_plan.py puts it into the .epd); the service keeps the tasks themselves.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, ValidationInfo, model_validator

from floorplan_engine.electrical.estimate import LINES, WORK_PREFIX, Estimate, split_key
from floorplan_engine.electrical.work_scope import Phrase, load_scope
from floorplan_engine.model.schema import StrictModel
from floorplan_engine.model.texts import Language

STAGES_FILE = Path(__file__).with_name("stages.yaml")

Photo = Literal["required", "optional", "none"]
Kind = Literal["work", "material"]


class StageTemplate(StrictModel):
    key: str = Field(pattern=r"^[a-z_]+$")
    title: Phrase
    lines: tuple[str, ...] = Field(min_length=1, description="Базовые ключи сметы; «prefix.*»")
    photo: Photo
    after: tuple[str, ...] = ()
    result: tuple[Phrase, ...] = ()


class StageCatalog(StrictModel):
    """stages.yaml: stages in work order. Validated against the estimate keys passed as the
    validation context {"lines": keys}."""

    stages: tuple[StageTemplate, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self, info: ValidationInfo) -> StageCatalog:
        known: Collection[str] = (info.context or {}).get("lines", ())
        seen: dict[str, str] = {}  # estimate key → stage
        earlier: set[str] = set()
        for k, stage in enumerate(self.stages):
            where = f"stages[{k}]"
            if stage.key in earlier:
                raise ValueError(f"{where}.key: этап {stage.key} уже есть")
            for j, ref in enumerate(stage.after):
                if ref not in earlier:
                    raise ValueError(f"{where}.after[{j}]: нет этапа {ref} выше по списку")
            for j, entry in enumerate(stage.lines):
                keys = expand(entry, known)
                if not keys:
                    raise ValueError(f"{where}.lines[{j}]: нет позиции {entry} в смете")
                for key in keys:
                    if key in seen:
                        raise ValueError(
                            f"{where}.lines[{j}]: позиция {key} уже в этапе {seen[key]}"
                        )
                    seen[key] = stage.key
            earlier.add(stage.key)
        return self


def expand(entry: str, known: Collection[str]) -> list[str]:
    """Estimate keys of a stages.yaml entry: the key itself or, for "prefix.*", every key with
    the prefix."""
    if entry.endswith(".*"):
        return sorted(k for k in known if k.startswith(entry[:-1]))
    return [entry] if entry in known else []


def parse_stages(data: object, known: Collection[str]) -> StageCatalog:
    return StageCatalog.model_validate(data or {}, context={"lines": known})


@cache
def load_stages() -> StageCatalog:
    """The electrical template shipped with the code (stages.yaml)."""
    return parse_stages(yaml.safe_load(STAGES_FILE.read_text("utf-8")), LINES)


def stage_by_key(catalog: StageCatalog, known: Collection[str]) -> dict[str, str]:
    """Estimate key → stage key."""
    return {k: s.key for s in catalog.stages for entry in s.lines for k in expand(entry, known)}


def unstaged(catalog: StageCatalog, known: Collection[str]) -> list[str]:
    """Estimate keys in no stage: such an item would fall out of the work plan."""
    staged = stage_by_key(catalog, known)
    return [k for k in known if k not in staged]


@dataclass(frozen=True)
class DraftLine:
    key: str  # the estimate key as is, with its parameter (work.chase.brick)
    kind: Kind
    title: str
    unit: str
    qty: float
    price: float | None  # None: no price in the list ("price to be confirmed")

    @property
    def sum(self) -> float | None:
        return None if self.price is None else round(self.qty * self.price, 2)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "title": self.title,
            "unit": self.unit,
            "qty": self.qty,
            "price": self.price,
            "sum": self.sum,
        }


@dataclass(frozen=True)
class DraftTask:
    """A stage with the lines of this estimate: the .epd work_plan task."""

    key: str  # <domain>.<stage>
    domain: str  # electrical | plumbing
    order: int  # stage number in its template, from 1
    title: str
    after: tuple[str, ...]  # task keys
    photo: Photo
    result: tuple[str, ...]
    lines: tuple[DraftLine, ...]

    def _total(self, kind: Kind) -> float:
        return round(sum(ln.sum or 0.0 for ln in self.lines if ln.kind == kind), 2)

    @property
    def work_total(self) -> float:
        return self._total("work")

    @property
    def material_total(self) -> float:
        return self._total("material")

    @property
    def unpriced(self) -> int:
        return sum(1 for ln in self.lines if ln.price is None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "domain": self.domain,
            "order": self.order,
            "title": self.title,
            "after": list(self.after),
            "photo": self.photo,
            "result": list(self.result),
            "lines": [ln.as_dict() for ln in self.lines],
            "work_total": self.work_total,
            "material_total": self.material_total,
            "unpriced": self.unpriced,
        }


def _after(
    stage: StageTemplate, by_key: Mapping[str, StageTemplate], present: Collection[str]
) -> list[str]:
    """Predecessors that are in the draft: a missing one is replaced by its own predecessors."""
    out: list[str] = []
    for ref in stage.after:
        for key in [ref] if ref in present else _after(by_key[ref], by_key, present):
            if key not in out:
                out.append(key)
    return out


def draft_tasks(
    est: Estimate,
    catalog: StageCatalog,
    known: Collection[str],
    domain: str,
    language: Language,
    scope_result: Callable[[str], str | None] = lambda key: None,
) -> list[DraftTask]:
    """The draft tasks of an estimate, in template order: lines in estimate order; scope_result
    gives the acceptance criterion of a work item (its base key) for stages without their own
    result."""
    staged = stage_by_key(catalog, known)
    lines: dict[str, list[DraftLine]] = {}
    for ln in est.lines:
        base = split_key(ln.key)[0]
        kind: Kind = "work" if base.startswith(WORK_PREFIX) else "material"
        line = DraftLine(ln.key, kind, ln.name, ln.unit, ln.qty, ln.price)
        lines.setdefault(staged[base], []).append(line)
    by_key = {s.key: s for s in catalog.stages}
    out: list[DraftTask] = []
    for no, stage in enumerate(catalog.stages, 1):
        rows = lines.get(stage.key)
        if not rows:
            continue
        result = [p.of(language) for p in stage.result]
        if not result:
            for row in rows:
                found = scope_result(split_key(row.key)[0]) if row.kind == "work" else None
                if found and found not in result:
                    result.append(found)
        out.append(
            DraftTask(
                f"{domain}.{stage.key}",
                domain,
                no,
                stage.title.of(language),
                tuple(f"{domain}.{k}" for k in _after(stage, by_key, lines)),
                stage.photo,
                tuple(result),
                tuple(rows),
            )
        )
    return out


def electrical_draft(est: Estimate, language: Language) -> list[DraftTask]:
    """Draft tasks of the electrical estimate; acceptance criteria from work_scope.yaml."""
    scope = load_scope()

    def result(key: str) -> str | None:
        item = scope.items.get(key)
        return item.result.of(language) if item is not None else None

    return draft_tasks(est, load_stages(), LINES, "electrical", language, result)
