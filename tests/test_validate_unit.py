"""Форматтеры валидации: путь к полю, значение в сообщении, Issue и Report."""

from __future__ import annotations

from typing import Any

import pytest

from shtroba.validate import Issue, Report, Severity, _fmt_value, _wall_list, format_loc


@pytest.mark.parametrize(
    ("loc", "path"),
    [
        ((), ""),
        (("rooms",), "rooms"),
        (("rooms", 0, "walls", 2, "length"), "rooms[0].walls[2].length"),
        ((0, "id"), "[0].id"),
        (("points", 1, 0), "points[1][0]"),
    ],
)
def test_format_loc(loc: tuple[int | str, ...], path: str) -> None:
    assert format_loc(loc) == path


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (5, " (указано: 5)"),
        ("x", " (указано: 'x')"),
        (None, " (указано: None)"),
        ({}, ""),
        ([1], ""),
    ],
)
def test_fmt_value(value: Any, text: str) -> None:
    assert _fmt_value(value) == text


def test_wall_list() -> None:
    assert _wall_list(["w1", "w2", "w3"]) == "w1, w2, w3"
    assert _wall_list([]) == ""


def test_issue_str_with_and_without_path() -> None:
    assert (
        str(Issue("room.yaml", "rooms[0]", "нет стен")) == "[ошибка] room.yaml: rooms[0]: нет стен"
    )
    warn = Issue("room.yaml", "", "мелочь", Severity.WARNING)
    assert str(warn) == "[предупреждение] room.yaml: мелочь"


def test_report_splits_errors_and_warnings() -> None:
    err = Issue("a", "p", "e")
    warn = Issue("a", "p", "w", Severity.WARNING)
    report = Report(issues=[warn, err])
    assert report.errors == [err] and report.warnings == [warn]
    assert not report.ok
    assert Report(issues=[warn]).ok
    assert Report().ok
