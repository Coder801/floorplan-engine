"""Sticker layout and the PDF: everything fits a 10 × 25 mm sticker."""

from __future__ import annotations

from pathlib import Path

import pytest

from floorplan_engine.electrical.loads import Breaker
from floorplan_engine.electrical.panel import BoardPanel, Device
from floorplan_engine.electrical.stickers import DEVICE_ICONS, GROUP_ICONS, KIND_ICONS, Sticker
from floorplan_engine.model.panel_catalog import DeviceKind
from floorplan_engine.sheets.stickers import (
    NAME_BOTTOM,
    NAME_EMS,
    NAME_FONT,
    NAME_PAD,
    NAME_TOP,
    NUMBER_EM,
    NUMBER_FONT,
    PAD,
    WIDTH,
    _can_cut,
    _pages,
    _width,
    icons,
    lay_out,
    stickers_data,
    write_stickers,
)


def sticker(*lines: str, number: str = "QF1", row: int = 0) -> Sticker:
    return Sticker(number, row, tuple(lines), "plug", " ".join(lines))


def panel() -> BoardPanel:
    relay = Device("KV1", DeviceKind.RELAY, "63 А", "Реле напряжения")
    return BoardPanel(
        "standard", None, False, (), (relay,), Breaker("C", 63, False), 0.0, 1.0, (), None, None,
        rows=((relay,),),
    )  # fmt: skip


def test_every_icon_in_use_is_in_the_set() -> None:
    used = {i for i, _ in GROUP_ICONS} | set(KIND_ICONS.values()) | set(DEVICE_ICONS.values())
    assert used <= set(icons())


def test_short_name_keeps_the_largest_size() -> None:
    laid = lay_out(sticker("Реле"))
    assert laid.name_em == NAME_EMS[0]
    assert [t for t, _ in laid.lines] == ["Реле"]


def test_breaks_after_a_hyphen() -> None:
    assert [t for t, _ in lay_out(sticker("Розетки", "Кухня-вітальня")).lines] == [
        "Розетки",
        "Кухня-",
        "вітальня",
    ]


def test_too_long_word_is_hyphenated_by_syllable() -> None:
    assert [t for t, _ in lay_out(sticker("Кондиціонер")).lines] == ["Кондиціо-", "нер"]


@pytest.mark.parametrize(
    ("word", "at", "ok"), [("Холодильник", 8, True), ("Посудомийка", 8, False)]
)
def test_can_cut(word: str, at: int, ok: bool) -> None:
    assert _can_cut(word, at) is ok


def test_nothing_leaves_the_sticker() -> None:
    long = "Надзвичайно довга назва лінії якої не вигадаєш навіть спеціально для перевірки"
    laid = lay_out(sticker(long, "Кухня-вітальня +3", number="QF100.12"))
    assert laid.lines[-1][0].endswith("…")
    assert laid.lines[0][1] > NAME_TOP
    assert laid.lines[-1][1] <= NAME_BOTTOM
    for line, _ in laid.lines:
        assert _width(line, laid.name_em, NAME_FONT) <= WIDTH - 2 * NAME_PAD
    assert laid.number_em < NUMBER_EM
    assert _width("QF100.12", laid.number_em, NUMBER_FONT) <= WIDTH - 2 * PAD + 0.01


def test_each_rail_starts_a_new_line() -> None:
    laid = [lay_out(sticker("Реле", row=r)) for r in (0, 0, 1)]
    (a, ax, ay), (_, bx, by), (_, cx, cy) = _pages(laid)[0]
    assert a is laid[0]
    assert (ay == by) and bx > ax
    assert cx == ax and cy > ay


def test_more_stickers_than_a_page_go_on_the_next() -> None:
    laid = [lay_out(sticker("Реле", row=r)) for r in range(12)]
    assert [len(p) for p in _pages(laid)] == [9, 3]


def test_data_for_the_viewer_carries_only_used_icons() -> None:
    data = stickers_data(panel())
    assert set(data["icons"]) == {"gauge"}  # type: ignore[call-overload]
    item = data["items"][0]  # type: ignore[index]
    assert item["id"] == "KV1"
    assert item["text"].startswith("M") and "Z" in item["text"]


def test_pdf_is_written_and_stable(tmp_path: Path) -> None:
    a = write_stickers(panel(), "ЩР", "uk", tmp_path / "a.pdf")
    b = write_stickers(panel(), "ЩР", "uk", tmp_path / "b.pdf")
    assert a.read_bytes().startswith(b"%PDF")
    assert a.read_bytes() == b.read_bytes()
