from __future__ import annotations

import re
from typing import Any

from floorplan_engine.epd.single_line import (
    COL,
    LABELS_W,
    PAD,
    PURPOSE_LINES,
    _wrap,
    assumed_any,
    single_line_svgs,
)

HEADINGS = {
    "group": "Группа",
    "device": "Аппарат",
    "cable": "Кабель",
    "power": "Мощность, Вт",
    "current": "Ток, А",
    "purpose": "Назначение",
}


def _device(id_: str, kind: str, label: str = "", **extra: Any) -> dict[str, Any]:
    return {"id": id_, "kind": kind, "label": label, **extra}


PANEL: dict[str, Any] = {
    "devices": [
        _device("QS1", "input", "C40 2P"),
        _device("KV1", "relay", "40 А"),
        _device("QF1", "breaker", "C10", group="QF1"),
        _device("QF5", "diff", "C16 30 мА", group="QF5"),
        _device("QD1", "rcd", "40 А 30 мА", feeds=["QF2", "QF3"]),
        _device("QF2", "breaker", "C16", group="QF2"),
        _device("QF3", "breaker", "C16", group="QF3"),
    ],
    "groups": {
        "QF1": {"purpose": "Освещение — Кухня", "cable": "3x1.5", "power": 130, "color": "#f28e2b"},
        "QF2": {"purpose": "Розетки — Спальня", "cable": "3x2.5", "power": 1500, "current": 6.5},
        "QF3": {"purpose": "Розетки — Кухня", "cable": "3x2.5"},
        "QF5": {"purpose": "Розетки — Ванная"},
    },
}


def _texts(svg: str) -> list[str]:
    return re.findall(r"<text[^>]*>([^<]*)</text>", svg)


def _size(svg: str) -> tuple[float, float]:
    found = re.match(r'<svg[^>]* width="([\d.]+)mm" height="([\d.]+)mm"', svg)
    assert found is not None
    return float(found.group(1)), float(found.group(2))


def test_chain_columns_and_table() -> None:
    (svg,) = single_line_svgs(PANEL, "Ввод 230 В", HEADINGS, 186)
    texts = _texts(svg)
    assert texts[0] == "Ввод 230 В"
    assert {"QS1", "C40 2P", "KV1", "U", "QD1", "40 А 30 мА"} <= set(texts)
    assert {h.upper() for h in HEADINGS.values()} <= set(texts)
    assert {"3×1,5", "1 500", "6,5", "Розетки — Кухня"} <= set(texts)
    # An RCBO label in two lines: the rating, then the leakage current
    assert {"C16", "30 мА"} <= set(texts)
    # The cable of a group is in its colour, as on the plan
    assert 'stroke="#f28e2b"' in svg


def test_rcd_breakers_once_in_its_order() -> None:
    (svg,) = single_line_svgs(PANEL, "Ввод", HEADINGS, 186)
    numbers = [t for t in _texts(svg) if re.fullmatch(r"QF\d", t)]
    assert numbers == ["QF1", "QF5", "QF2", "QF3"]


def test_contactor_splits_the_bus() -> None:
    panel = {
        "devices": [
            _device("QS1", "input", "C40 2P"),
            _device("KM1", "contactor", "40 А 2P", master=True),
            _device("SF1", "breaker", "B6"),
            _device("QF1", "breaker", "C10", group="QF1", master=True),
        ],
        "groups": {},
    }
    (svg,) = single_line_svgs(panel, "Ввод", HEADINGS, 186)
    numbers = [t for t in _texts(svg) if t in ("SF1", "QF1")]
    # The control circuit is left of the contactor, the switched line right of it
    assert numbers == ["SF1", "QF1"]
    assert "KM1" in _texts(svg)


def test_wide_panel_in_tiers_rcd_kept_whole() -> None:
    breakers = [_device(f"QF{i}", "breaker", "C16", group=f"QF{i}") for i in range(1, 15)]
    rcd = _device("QD1", "rcd", "40 А 30 мА", feeds=["QF13", "QF14"])
    panel = {"devices": [_device("QS1", "input", "C40 2P"), rcd, *breakers], "groups": {}}
    width = LABELS_W + 2 * PAD + 8 * COL
    tiers = single_line_svgs(panel, "Ввод", HEADINGS, width)
    assert len(tiers) == 2
    assert all(_size(t)[0] <= width + 0.01 for t in tiers)
    # The input is drawn once; the later tier continues the bus dashed from the left
    assert "QS1" in _texts(tiers[0]) and "QS1" not in _texts(tiers[1])
    assert "stroke-dasharray" in tiers[1]
    shown = [t for svg in tiers for t in _texts(svg) if re.fullmatch(r"QF\d+", t)]
    assert sorted(shown) == sorted(f"QF{i}" for i in range(1, 15))
    assert any({"QF13", "QF14"} <= set(_texts(t)) for t in tiers)


def test_purpose_wrapped_and_cut() -> None:
    assert _wrap("Розетки — Кухня") == ["Розетки — Кухня"]
    lines = _wrap("очень длинное назначение группы " * 10)
    assert len(lines) == PURPOSE_LINES and lines[-1].endswith("…")


def test_text_escaped_deterministic_empty_panel() -> None:
    panel = {**PANEL, "groups": {"QF1": {"purpose": "<b>&"}}}
    (svg,) = single_line_svgs(panel, "Ввод", HEADINGS, 186)
    assert "&lt;b&gt;&amp;" in svg
    first = single_line_svgs(PANEL, "Ввод", HEADINGS, 186)
    assert first == single_line_svgs(PANEL, "Ввод", HEADINGS, 186)
    (empty,) = single_line_svgs({}, "Ввод", HEADINGS, 186)
    assert empty.startswith("<svg")


def test_spd_is_a_branch_to_earth_with_its_column() -> None:
    panel = {
        "devices": [
            _device("QS1", "input", "C63 2P"),
            _device("FV1", "spd", "T2 20 кА", title="УЗИП"),
            _device("QF1", "breaker", "C10", group="QF1"),
        ],
        "groups": {},
    }
    (svg,) = single_line_svgs(panel, "Ввод", HEADINGS, 186)
    texts = _texts(svg)
    # Its own column before the groups, not a box in the input chain
    assert texts.index("FV1") < texts.index("QF1")
    assert {"T2", "20 кА", "УЗИП"} <= set(texts)


BACKUP: dict[str, Any] = {
    "external": {
        "id": "U1",
        "kind": "inverter",
        "title": "Инвертор",
        "to": "QS3",
        "switch": "SA1",
        "feed": "QS2",
    },
    "devices": [
        _device("QS1", "input", "C63 2P"),
        _device("KM2", "contactor", "40 А 2P", master=True),
        _device("QF9", "breaker", "C16", group="QF9", master=True),
        _device("QS2", "feed", "C32 2P"),
        _device("SA1", "changeover", "I-0-II", reserve=True),
        _device("QS3", "output", "C32 2P"),
        _device("SF1", "breaker", "B6", reserve=True),
        _device("KM3", "contactor", "25 А 2P", reserve=True, master=True),
        _device("QF1", "breaker", "C10", group="QF1", reserve=True, master=True),
    ],
    "groups": {},
}


def test_backup_block_and_two_contactors() -> None:
    (svg,) = single_line_svgs(BACKUP, "Ввод", HEADINGS, 400)
    texts = _texts(svg)
    xs = {
        t: float(x) for x, t in reversed(re.findall(r'<text x="([\d.]+)"[^>]*>([^<]*)</text>', svg))
    }
    # Left to right: KM2 and its group on the main bus; the inverter, the switch; the backup
    # bus: the control circuit before KM3, the cut group behind it
    order = ["KM2", "QF9", "U1", "SA1", "SF1", "KM3", "QF1"]
    assert sorted(order, key=xs.__getitem__) == order
    assert {"QS2", "QS3"} <= set(texts)
    assert {"I", "II", "Инвертор"} <= set(texts)


def test_tiers_framed_same_width_and_bus_goes_on() -> None:
    tiers = single_line_svgs(BACKUP, "Ввод", HEADINGS, LABELS_W + 2 * PAD + 70)
    assert len(tiers) > 1
    assert len({_size(t)[0] for t in tiers}) == 1
    assert all('stroke-width="0.5"' in t for t in tiers)  # the frame


def test_device_kinds_named_in_the_project_language() -> None:
    (uk,) = single_line_svgs(PANEL, "Ввід", HEADINGS, 186, "uk")
    texts = _texts(uk)
    assert {"АВ", "АВ 1P", "АВДТ 1P+N", "ПЗВ 2P", "Реле напруги"} <= set(texts)
    (ru,) = single_line_svgs(PANEL, "Ввод", HEADINGS, 186, "ru")
    assert {"УЗО 2P", "Реле напряжения"} <= set(_texts(ru))
    three = {**PANEL, "devices": [_device("QF1", "breaker", "C16 3P", group="QF1", phase="3P")]}
    assert "АВ 3P" in _texts(single_line_svgs(three, "Ввод", HEADINGS, 186)[0])


def test_design_block_from_totals_input_and_earthing() -> None:
    panel = {
        **PANEL,
        "totals": {"installed": 24700, "demand": 0.6, "calculated": 14820, "current": 64.4},
        "input": {"label": "C63", "assumed": True},
        "earthing": "TN-S",
        "phases": 3,
    }
    (svg,) = single_line_svgs(panel, "Ввод", HEADINGS, 186, "ru")
    texts = _texts(svg)
    assert "Pу 24,7 кВт · Kс 0,60 · Pр 14,8 кВт · Iр 64,4 А" in texts
    assert "400 В, 3 фазы · TN-S · ввод C63*" in texts
    # An old build without earthing: TN-C-S, one phase, no star on a firm input
    (old,) = single_line_svgs({**PANEL, "input": {"label": "C40"}}, "Ввод", HEADINGS, 186, "ru")
    assert "230 В, 1 фаза · TN-C-S · ввод C40" in _texts(old)


def test_cable_mark_and_length_and_assumption_marks() -> None:
    panel = {
        **PANEL,
        "devices": [_device("QF1", "breaker", "C10", group="QF1", assumed=True)],
        "groups": {
            "QF1": {
                "purpose": "Освещение — Кухня",
                "purpose_assumed": True,
                "cable": "3x1.5",
                "cable_assumed": True,
                "power": 130,
                "assumed": True,
                "current": 0.6,
            }
        },
    }
    (svg,) = single_line_svgs(panel, "Ввод", HEADINGS, 186, "ru", {"QF1": "51,6"})
    texts = _texts(svg)
    assert {"ВВГнг", "3×1,5*", "51,6 м", "C10*", "130*", "Освещение — Кухня*"} <= set(texts)
    assert assumed_any(panel) and not assumed_any({"groups": {"QF1": {"power": 1}}})
    (bare,) = single_line_svgs(panel, "Ввод", HEADINGS, 186, "ru")
    assert "51,6 м" not in _texts(bare)


def test_major_warning_flags_the_group() -> None:
    panel = {
        **PANEL,
        "warnings": [
            {"severity": "major", "text": "QF1: перегрузка", "group": "QF1"},
            {"severity": "minor", "text": "QF2: нет кабеля", "group": "QF2"},
        ],
    }
    (svg,) = single_line_svgs(panel, "Ввод", HEADINGS, 186)
    assert re.search(r'fill="#c62828"[^>]*>QF1 !<', svg)
    assert "QF2 !" not in _texts(svg)


def test_control_circuit_ends_in_the_coil_without_a_column() -> None:
    panel = {
        "devices": [
            _device("QS1", "input", "C40 2P"),
            _device("KM2", "contactor", "40 А 2P", master=True),
            _device("SF1", "breaker", "B6"),
            _device("QF1", "breaker", "C10", group="QF1", master=True),
        ],
        "groups": {},
    }
    (svg,) = single_line_svgs(panel, "Ввод", HEADINGS, 186, "uk")
    texts = _texts(svg)
    assert "SF1" in texts and "котушка" in texts and texts.count("KM2") == 2
    # One group column in the table: QF1; SF1 has no purpose cell
    assert "Коло керування" not in svg


def test_npe_link_states() -> None:
    for npe, mark, note in (
        (True, "N–PE", "связь N–PE в резерве"),
        (None, "N–PE?", "связь N–PE в резерве?"),
        (False, "N–PE", "связи N–PE в резерве нет"),
    ):
        (svg,) = single_line_svgs({**BACKUP, "npe_relay": npe}, "Ввод", HEADINGS, 400, "ru")
        assert {mark, note} <= set(_texts(svg)), npe
