"""Electrical estimate texts: section headings, the listed-section note, the number format."""

from __future__ import annotations

import pytest

from floorplan_engine.electrical.estimate.texts import (
    format_number,
    parse_number,
    section_title,
    text,
)


@pytest.mark.parametrize(
    ("value", "digits", "text"),
    [
        (10, 2, "10"),
        (1234.5, 2, "1 234,50"),
        (1234567.891, 2, "1 234 567,89"),
        (0.25, 2, "0,25"),
        (0, 2, "0"),
        (1234567, 0, "1 234 567"),
        (5, 0, "5"),
        (2.75, 1, "2,8"),
        (3.0, 1, "3,0"),
    ],
)
def test_num_format(value: float, digits: int, text: str) -> None:
    assert format_number(value, digits) == text
    assert parse_number(text) == round(value, digits)


@pytest.mark.parametrize("text", ["—", "", "нет цены"])
def test_parse_number_no_price(text: str) -> None:
    assert parse_number(text) is None


def test_section_titles_are_plain_and_finish_materials_have_their_note() -> None:
    assert section_title("material", "ru") == "Материалы"
    assert section_title("material_finish", "ru") == "Чистовые материалы"
    assert section_title("material_rough", "uk") == "Чорнові матеріали"
    assert section_title("rough", "ru") == "Черновые работы"
    assert text("listed", "uk") == "Ціни — після вибору серії"
    note = text("note_listed", "ru", n=5)
    assert (
        note.startswith("Чистовые материалы (5 поз.) — ведомость без цен")
        and "имитация" not in note
    )
