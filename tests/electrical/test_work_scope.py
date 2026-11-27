"""Work scope: the catalogue covers every work item, keys are checked, and the project
appendix lists what every work item includes, with no "outside the estimate" section.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from openpyxl import load_workbook
from pydantic import ValidationError

from floorplan_engine.electrical.estimate import Estimate, Line
from floorplan_engine.electrical.estimate.files import write_xlsx
from floorplan_engine.electrical.estimate.items import LINES, WORK_PREFIX
from floorplan_engine.electrical.work_scope import (
    load_scope,
    missing_scope,
    parse_scope,
    scope_entries,
    scope_sheet,
    write_scope_markdown,
)

PHRASE = {"ru": "текст", "uk": "текст"}


def _scope() -> dict[str, Any]:
    return {"includes": [PHRASE], "result": PHRASE}


def _estimate(*keys: str) -> Estimate:
    lines = tuple(Line(LINES[k][0], k, LINES[k][2], LINES[k][1], 2.0, 10.0) for k in keys)
    return Estimate(lines, "грн")


def test_catalogue_covers_every_work_item() -> None:
    catalog = load_scope()
    assert missing_scope(catalog) == []
    assert set(catalog.items) == {k for k in LINES if k.startswith(WORK_PREFIX)}


def test_missing_scope_lists_work_items_without_one() -> None:
    missing = missing_scope(parse_scope({"work.cable": _scope()}))
    assert "work.cable" not in missing and "work.chase" in missing
    assert all(k.startswith(WORK_PREFIX) for k in missing)  # materials need no scope


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"work.cabel": _scope()}, "work.cabel: нет такой работы"),
        ({"cable": _scope()}, "cable: нет такой работы"),  # a material, not a work
    ],
)
def test_catalogue_rejects_unknown_keys(data: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        parse_scope(data)


def test_catalogue_has_no_excludes_any_more() -> None:
    """The "not included" list is gone (decision 2026-11-22): the key is an error, not dead data."""
    with pytest.raises(ValidationError, match="excludes"):
        parse_scope({"work.cable": {**_scope(), "excludes": [PHRASE]}})


def test_catalogue_needs_both_languages_and_an_include() -> None:
    with pytest.raises(ValidationError):
        parse_scope({"work.cable": {"includes": [{"ru": "текст"}], "result": PHRASE}})
    with pytest.raises(ValidationError):
        parse_scope({"work.cable": {"includes": [], "result": PHRASE}})


def test_scope_entries_follow_the_estimate() -> None:
    est = _estimate("cable", "work.cable", "work.chase", "work.junction_box", "work.mechanism")
    entries = scope_entries(est, "ru")
    assert [e.key for e in entries] == [
        "work.cable",
        "work.chase",
        "work.junction_box",
        "work.mechanism",
    ]  # materials have no scope
    cable = entries[0]
    assert (cable.section, cable.no, cable.name) == ("rough", 1, "Прокладка кабеля")
    assert "раскладка кабеля по трассе" in cable.includes
    mechanism = entries[-1]
    assert (mechanism.section, mechanism.no) == ("finish", 1)


def test_scope_is_in_the_project_language() -> None:
    cable = scope_entries(_estimate("work.cable"), "uk")[0]
    assert cable.result.startswith("кабель лежить по трасі")


def test_scope_files(tmp_path: Path) -> None:
    est = _estimate("work.cable", "work.junction_box", "work.board_module")
    entries = scope_entries(est, "ru")
    md = write_scope_markdown(entries, tmp_path / "work-scope.md", "Состав работ", "ru")
    text = md.read_text("utf-8")
    assert "## Черновые работы" in text and "## Чистовые работы" in text
    assert "### 1. Прокладка кабеля — 2 м" in text
    assert "- раскладка кабеля по трассе" in text
    assert "Не входит" not in text and "отдельная позиция" not in text
    assert "вне сметы" not in text and "- укладка в гофротрубу" not in text
    assert "**Результат:** соединения опрессованы" in text
    assert "дополнительная: её объём и цена согласуются до выполнения" in text
    assert "Расходники на инструмент (диски, буры, коронки, свёрла) входят в цену работ" in text

    xlsx = write_xlsx(est, tmp_path / "e.xlsx", "Смета", [], "ru", scope_sheet(entries, "ru"))
    wb = load_workbook(xlsx)
    assert wb.sheetnames == ["Смета электрики", "Состав работ"]
    cells = [str(c.value) for row in wb["Состав работ"].iter_rows() for c in row if c.value]
    assert "Прокладка кабеля" in cells and "Не входит" not in cells
    assert not any("вне сметы" in c for c in cells)
    assert any("• фиксация кабеля площадками" in c for c in cells)
    assert any(c.startswith("Расходники на инструмент") for c in cells)


def test_chases_by_wall_material_share_the_chase_scope() -> None:
    """work.chase.concrete has the scope of work.chase."""
    lines = (
        Line("rough", "work.cable", "Прокладка кабеля", "м", 10.0, 30.0),
        Line("rough", "work.chase.concrete", "Штроба узкая, бетон", "м", 2.0, 200.0),
        Line("rough", "work.chase.aerated", "Штроба узкая, газоблок", "м", 1.0, 90.0),
    )
    entries = scope_entries(Estimate(lines, "грн"), "ru")
    assert [e.key for e in entries] == [ln.key for ln in lines]
    assert entries[1].includes == entries[2].includes
