"""Work scope: the catalogue covers every work item, references are checked, and the project
appendix names where an excluded operation is paid.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from openpyxl import load_workbook
from pydantic import ValidationError

from floorplan_engine.electrical.estimate import (
    LINES,
    WORK_PREFIX,
    Estimate,
    Line,
    write_xlsx,
)
from floorplan_engine.electrical.work_scope import (
    load_scope,
    missing_scope,
    outside_scope,
    parse_scope,
    scope_entries,
    scope_sheet,
    write_scope_markdown,
)

PHRASE = {"ru": "текст", "uk": "текст"}


def _scope(**excluded: Any) -> dict[str, Any]:
    return {"includes": [PHRASE], "excludes": [{**PHRASE, **excluded}], "result": PHRASE}


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
        ({"work.cable": _scope(ref=["work.chas"])}, "work.cable.excludes[0].ref: нет работы"),
        ({"work.cable": _scope(ref=["work.cable"])}, "ссылка на саму позицию"),
    ],
)
def test_catalogue_rejects_unknown_keys_and_references(data: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message.replace("[", r"\[").replace("]", r"\]")):
        parse_scope(data)


def test_catalogue_needs_both_languages_and_an_include() -> None:
    with pytest.raises(ValidationError):
        parse_scope({"work.cable": {"includes": [{"ru": "текст"}], "result": PHRASE}})
    with pytest.raises(ValidationError):
        parse_scope({"work.cable": {"includes": [], "result": PHRASE}})


def test_scope_entries_and_work_outside_the_estimate() -> None:
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
    outside = outside_scope(est, "ru")
    # what another item of this estimate pays for is not listed
    assert "штроба" not in outside and "соединение жил в коробках" not in outside
    # the estimate has no conduit item; fixtures are in no estimate at all
    assert "укладка в гофротрубу" in outside and "монтаж светильников" in outside
    # once each, in estimate order: both chase items would name the same operations
    assert len(outside) == len(set(outside))
    assert outside.index("укладка в гофротрубу") < outside.index("монтаж светильников")
    two = outside_scope(_estimate("work.chase", "work.chase_wide"), "uk")
    assert two.count("вивезення будівельного сміття") == 1


def test_scope_is_in_the_project_language() -> None:
    cable = scope_entries(_estimate("work.cable"), "uk")[0]
    assert cable.result.startswith("кабель лежить по трасі")


def test_scope_files(tmp_path: Path) -> None:
    est = _estimate("work.cable", "work.junction_box", "work.board_module")
    entries = scope_entries(est, "ru")
    outside = outside_scope(est, "ru")
    md = write_scope_markdown(entries, tmp_path / "work-scope.md", "Состав работ", outside, "ru")
    text = md.read_text("utf-8")
    assert "## Черновые работы" in text and "## Чистовые работы" in text
    assert "### 1. Прокладка кабеля — 2 м" in text
    assert "- раскладка кабеля по трассе" in text
    assert "Не входит" not in text and "отдельная позиция" not in text
    assert "## Работы вне сметы" in text and "- укладка в гофротрубу" in text
    assert "- подключение к аппаратам щита" not in text  # paid by "Сборка щита" of this estimate
    assert "**Результат:** соединения опрессованы" in text
    assert "дополнительная: её объём и цена согласуются до выполнения" in text
    assert "Расходники на инструмент (диски, буры, коронки, свёрла) входят в цену работ" in text

    xlsx = write_xlsx(
        est, tmp_path / "e.xlsx", "Смета", [], "ru", scope_sheet(entries, outside, "ru")
    )
    wb = load_workbook(xlsx)
    assert wb.sheetnames == ["Смета электрики", "Состав работ"]
    cells = [str(c.value) for row in wb["Состав работ"].iter_rows() for c in row if c.value]
    assert "Прокладка кабеля" in cells and "Не входит" not in cells
    assert "Работы вне сметы" in cells and "• укладка в гофротрубу" in cells
    assert any("• фиксация кабеля площадками" in c for c in cells)
    assert any(c.startswith("Расходники на инструмент") for c in cells)


def test_chases_by_wall_material_share_the_chase_scope() -> None:
    """work.chase.concrete has the scope of work.chase, and a reference to work.chase names
    every chase line of the estimate."""
    lines = (
        Line("rough", "work.cable", "Прокладка кабеля", "м", 10.0, 30.0),
        Line("rough", "work.chase.concrete", "Штроба узкая, бетон", "м", 2.0, 200.0),
        Line("rough", "work.chase.aerated", "Штроба узкая, газоблок", "м", 1.0, 90.0),
    )
    entries = scope_entries(Estimate(lines, "грн"), "ru")
    assert [e.key for e in entries] == [ln.key for ln in lines]
    assert entries[1].includes == entries[2].includes
    # a chase by wall material is the chase item: "штроба" is paid in this estimate
    assert "штроба" not in outside_scope(Estimate(lines, "грн"), "ru")
