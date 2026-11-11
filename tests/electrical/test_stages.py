"""Work stages of electrical (electrical/stages.py): the template covers every estimate item exactly
once, and the draft takes only the stages this estimate has, with criteria from the work scope."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from floorplan_engine.electrical.estimate import LINES, Estimate, Line, split_key
from floorplan_engine.electrical.stages import (
    draft_tasks,
    electrical_draft,
    expand,
    load_stages,
    parse_stages,
    stage_by_key,
    unstaged,
)
from floorplan_engine.electrical.work_scope import load_scope

PHRASE = {"ru": "этап", "uk": "етап"}


def _stage(key: str, lines: list[str], **more: Any) -> dict[str, Any]:
    return {"key": key, "title": PHRASE, "lines": lines, "photo": "optional", **more}


def _estimate(*rows: tuple[str, float, float | None]) -> Estimate:
    lines = []
    for key, qty, price in rows:
        section, unit, ru, _ = LINES[split_key(key)[0]]
        lines.append(Line(section, key, ru or key, unit, qty, price))
    return Estimate(tuple(lines), "грн")


def test_template_covers_every_estimate_item_once() -> None:
    catalog = load_stages()
    assert unstaged(catalog, LINES) == []
    assert set(stage_by_key(catalog, LINES)) == set(LINES)
    assert "work.marking" not in LINES  # retired: folded into work.cable


def test_unstaged_lists_items_without_a_stage() -> None:
    catalog = parse_stages({"stages": [_stage("a", ["work.cable"])]}, LINES)
    missing = unstaged(catalog, LINES)
    assert "work.cable" not in missing and "cable" in missing


@pytest.mark.parametrize(
    ("stages", "message"),
    [
        ([_stage("a", ["work.cabel"])], r"stages\[0\].lines\[0\]: нет позиции work.cabel"),
        ([_stage("a", ["nope.*"])], r"stages\[0\].lines\[0\]: нет позиции nope.\*"),
        (
            [_stage("a", ["cable"]), _stage("b", ["work.cable", "cable"])],
            r"stages\[1\].lines\[1\]: позиция cable уже в этапе a",
        ),
        ([_stage("a", ["cable"]), _stage("a", ["work.cable"])], r"stages\[1\].key: этап a уже"),
        (
            [_stage("a", ["cable"], after=["b"]), _stage("b", ["work.cable"])],
            r"stages\[0\].after\[0\]: нет этапа b выше",
        ),
    ],
)
def test_bad_template_names_the_field(stages: list[dict[str, Any]], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        parse_stages({"stages": stages}, LINES)


def test_prefix_entry_expands_to_every_key() -> None:
    assert expand("dc_*", LINES) == []  # only "prefix.*"
    assert expand("work.*", ["work.a", "work.b", "cable"]) == ["work.a", "work.b"]
    assert expand("cable", LINES) == ["cable"]


def test_draft_groups_lines_by_stage_with_parameters() -> None:
    est = _estimate(
        ("work.chase.brick", 10.0, 120.0),
        ("socket_box", 4.0, 15.0),
        ("cable.3x1.5", 100.0, 30.0),
        ("work.cable", 90.0, 34.0),
        ("breaker.C16", 3.0, None),
        ("work.board_module", 6.0, 150.0),
        ("work.insulation_test", 3.0, 300.0),
    )
    tasks = electrical_draft(est, "ru")
    keys = [t.key for t in tasks]
    assert keys == [
        "electrical.chases",
        "electrical.cable",
        "electrical.insulation",
        "electrical.assembly",
    ]
    chases, cable, insulation, assembly = tasks
    assert [ln.key for ln in chases.lines] == ["work.chase.brick", "socket_box"]
    assert (chases.work_total, chases.material_total) == (1200.0, 60.0)
    assert [t.order for t in tasks] == [1, 2, 5, 7]
    assert cable.after == ("electrical.chases",) and cable.photo == "required"
    # No boxes stage in this estimate: insulation comes after the cable only
    assert insulation.after == ("electrical.cable",)
    # No panel enclosure stage: assembly after the insulation only
    assert assembly.after == ("electrical.insulation",)
    assert assembly.unpriced == 1 and assembly.material_total == 0.0
    assert assembly.lines[0].sum is None and assembly.as_dict()["lines"][0]["price"] is None
    scope = load_scope()
    assert cable.result == (scope.items["work.cable"].result.ru,)
    assert insulation.result == (scope.items["work.insulation_test"].result.ru,)
    assert "work.chase" in [split_key(ln.key)[0] for ln in chases.lines]


def test_draft_text_in_the_project_language() -> None:
    [task] = electrical_draft(_estimate(("work.cable", 1.0, 34.0)), "uk")
    assert task.title == "Прокладання кабелю"
    assert task.result == (load_scope().items["work.cable"].result.uk,)
    data = task.as_dict()
    assert data["key"] == "electrical.cable" and data["after"] == []
    assert data["lines"] == [
        {
            "key": "work.cable",
            "kind": "work",
            "title": "Прокладка кабеля",
            "unit": "м",
            "qty": 1.0,
            "price": 34.0,
            "sum": 34.0,
        }
    ]
    assert (data["work_total"], data["material_total"], data["unpriced"]) == (34.0, 0.0, 0)


def test_own_result_wins_over_the_scope() -> None:
    catalog = parse_stages(
        {"stages": [_stage("a", ["work.cable"], result=[{"ru": "готово", "uk": "готово"}])]},
        LINES,
    )
    [task] = draft_tasks(_estimate(("work.cable", 1.0, 1.0)), catalog, LINES, "x", "ru")
    assert task.result == ("готово",) and task.key == "x.a"


def test_empty_estimate_has_no_tasks() -> None:
    assert electrical_draft(Estimate((), "грн"), "ru") == []
