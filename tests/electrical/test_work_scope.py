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


def test_excluded_operation_names_where_it_is_paid() -> None:
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
    # both chase items are referenced, only the one in this estimate is named
    assert "штроба — отдельная позиция «Штроба узкая, 1–2 кабеля»" in cable.excludes
    assert "соединение жил в коробках — отдельная позиция «Монтаж коробки с опрессовкой»" in (
        cable.excludes
    )
    # the estimate has no conduit item
    assert "укладка в гофротрубу — в этой смете не предусмотрено" in cable.excludes
    mechanism = entries[-1]
    assert (mechanism.section, mechanism.no) == ("finish", 1)
    assert "монтаж светильников — в смету не входит" in mechanism.excludes


def test_reference_uses_the_name_from_this_estimate_and_language() -> None:
    est = _estimate("work.cable", "work.chase", "work.chase_wide")
    renamed = Estimate(
        (
            est.lines[0],
            Line("rough", "work.chase", "Штроба в бетоні", "м", 1.0, None),
            est.lines[2],
        ),
        "грн",
    )
    cable = scope_entries(renamed, "uk")[0]
    assert (
        "штроба — окремі позиції «Штроба в бетоні», «Штроба широкая, 3–4 кабеля»" in cable.excludes
    )
    assert cable.result.startswith("кабель лежить по трасі")


def test_scope_files(tmp_path: Path) -> None:
    est = _estimate("work.cable", "work.junction_box", "work.board_module")
    entries = scope_entries(est, "ru")
    md = write_scope_markdown(entries, tmp_path / "work-scope.md", "Состав работ", ["прим."], "ru")
    text = md.read_text("utf-8")
    assert "## Черновые работы" in text and "## Чистовые работы" in text
    assert "### 1. Прокладка кабеля — 2 м" in text
    assert "- раскладка кабеля по трассе" in text
    assert "- подключение к аппаратам щита — отдельная позиция «Сборка щита»" in text
    assert "**Результат:** соединения опрессованы" in text
    assert "дополнительная: её объём и цена согласуются до выполнения" in text
    assert text.rstrip().endswith("- прим.")

    xlsx = write_xlsx(
        est, tmp_path / "e.xlsx", "Смета", [], "ru", scope_sheet(entries, ["прим."], "ru")
    )
    wb = load_workbook(xlsx)
    assert wb.sheetnames == ["Смета электрики", "Состав работ"]
    cells = [str(c.value) for row in wb["Состав работ"].iter_rows() for c in row if c.value]
    assert "Прокладка кабеля" in cells and "прим." in cells
    assert any("• фиксация кабеля креплениями" in c for c in cells)
