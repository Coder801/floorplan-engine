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
    NEUTRAL,
    NUMBER_EM,
    NUMBER_FONT,
    PAD,
    WIDTH,
    _can_cut,
    _pages,
    _tokens,
    _width,
    icons,
    lay_out,
    number_em,
    on_color,
    sticker_color,
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


def test_number_stays_with_its_word() -> None:
    assert _tokens("Робоча зона 1") == ["Робоча", "зона 1"]
    assert _tokens("Коридор +1") == ["Коридор +1"]


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
    assert number_em("QF100.12") < NUMBER_EM
    assert _width("QF100.12", number_em("QF100.12"), NUMBER_FONT) <= WIDTH - 2 * PAD


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
    data = stickers_data(panel(), {})
    assert set(data["icons"]) == {"gauge"}  # type: ignore[call-overload]
    item = data["items"][0]  # type: ignore[index]
    assert item["id"] == item["short_id"] == "KV1"
    assert item["number"].startswith("M") and "Z" in item["name"]
    assert item["color"] == NEUTRAL


def test_colour_of_a_sticker_is_the_group_colour() -> None:
    line = Sticker("QF8.2", 0, ("Бойлер",), "plug", "Бойлер", "QF8.2")
    assert sticker_color(line, {"QF8": 0x4C8DD6}) == "#4c8dd6"
    assert sticker_color(sticker("Реле"), {"QF8": 0x4C8DD6}) == NEUTRAL


@pytest.mark.parametrize(("color", "text"), [("#000000", "#ffffff"), ("#f2d24b", "#000000")])
def test_number_stays_readable_on_the_band(color: str, text: str) -> None:
    assert on_color(color) == text


def test_short_number_drops_the_letters_of_a_line() -> None:
    line = Sticker("QF12", 0, ("Бойлер",), "plug", "Бойлер", "QF12")
    split = Sticker("QF8.2", 0, ("Бойлер",), "plug", "Бойлер", "QF8.2")
    assert (line.short_id, split.short_id) == ("12", "8.2")


def test_short_number_keeps_a_device_without_a_line_and_a_name_without_digits() -> None:
    assert sticker("Реле", number="QS1").short_id == "QS1"
    assert Sticker("Кухня", 0, ("Кухня",), "plug", "Кухня", "Кухня").short_id == "Кухня"


def test_short_number_goes_to_the_viewer_and_the_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    line = Sticker("QF1", 0, ("Розетки",), "plug", "Розетки", "QF1")
    monkeypatch.setattr("floorplan_engine.sheets.stickers.build_stickers", lambda _: [line])
    item = stickers_data(panel(), {})["items"][0]  # type: ignore[index]
    assert item["short_id"] == "1"
    assert item["short_number"] != item["number"]
    full = write_stickers(panel(), "ЩР", "uk", tmp_path / "a.pdf")
    short = write_stickers(panel(), "ЩР", "uk", tmp_path / "b.pdf", short=True)
    assert full.read_bytes() != short.read_bytes()


def test_pdf_is_written_and_stable(tmp_path: Path) -> None:
    a = write_stickers(panel(), "ЩР", "uk", tmp_path / "a.pdf")
    b = write_stickers(panel(), "ЩР", "uk", tmp_path / "b.pdf")
    assert a.read_bytes().startswith(b"%PDF")
    assert a.read_bytes() == b.read_bytes()


def test_colour_pdf_differs_from_the_black_one(tmp_path: Path) -> None:
    black = write_stickers(panel(), "ЩР", "uk", tmp_path / "a.pdf")
    color = write_stickers(panel(), "ЩР", "uk", tmp_path / "b.pdf", {})
    assert color.read_bytes().startswith(b"%PDF")
    assert color.read_bytes() != black.read_bytes()
