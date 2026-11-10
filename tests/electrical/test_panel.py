"""Panel front view: loads, breakers, panel set by scheme and weak spots."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import yaml
from pydantic import ValidationError

from floorplan_engine.electrical.loads import (
    Kind,
    cable_section,
    heavy_cable,
    parse_breaker,
    rating_for,
)
from floorplan_engine.electrical.panel import (
    BoardPanel,
    Device,
    build_panel,
    choose_enclosure,
    device_name,
    din_rows,
    line_classes,
    panel_rows,
    panel_title,
    reserve_groups,
)
from floorplan_engine.electrical.panel_questions import panel_questions
from floorplan_engine.electrical.panel_text import TEXT
from floorplan_engine.epd.panel_data import panel_data, reserve_data
from floorplan_engine.model.intake import Stage
from floorplan_engine.model.panel_catalog import ENCLOSURES, DeviceKind
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.validation.assess import assess
from floorplan_engine.validation.validate import validate_project

ROOMS = [
    {
        "id": "k",
        "name": "Кухня",
        "walls": [{"id": f"w{n}", "length": 3000} for n in range(1, 5)],
    },
    {
        "id": "b",
        "name": "Санвузол",
        "origin": [4000, 0],
        "wet": True,
        "walls": [{"id": f"w{n}", "length": 2000} for n in range(1, 5)],
    },
]


def _plan() -> Plan:
    return Plan.model_validate(
        {"name": "T", "default_wall_thickness": 100, "source": "text", "rooms": ROOMS}
    )


def _pt(pid: str, kind: str, group: str, room: str = "k", **kw: Any) -> dict[str, Any]:
    return {
        "id": pid,
        "room": room,
        "type": kind,
        "wall": "w1",
        "offset": 500,
        "height": 300,
        "group": group,
        **kw,
    }


def test_line_classes_purpose_and_protection() -> None:
    """Light, sockets, appliances; premium puts every line under an RCBO."""
    points = [
        _pt("l1", "sconce", "QF1"),
        _pt("s1", "socket", "QF2"),
        _pt("s2", "socket", "QF2"),
        _pt("f1", "socket", "QF3", note="холодильник"),
        _pt("o1", "outlet", "QF4"),
        _pt("o2", "outlet", "QF4"),
        _pt("b1", "socket", "QF5"),  # one socket with no name is still a socket
    ]
    cables = {f"QF{k}": "ВВГнг 3x2.5" for k in range(1, 6)}
    lines = line_classes(_plan(), _elec(points, cables))
    assert {g: c.purpose for g, c in lines.items()} == {
        "QF1": "light",
        "QF2": "socket",
        "QF3": "device",
        "QF4": "device",
        "QF5": "socket",
    }
    assert not any(c.rcd for c in lines.values())
    premium = line_classes(_plan(), _elec(points, cables, panel={"scheme": "premium"}))
    assert all(c.rcd for c in premium.values())


def _ids(points: list[dict[str, Any]], group: str) -> list[str]:
    return [p["id"] for p in points if p["group"] == group]


def _elec(points: list[dict[str, Any]], cables: dict[str, str], **extra: Any) -> Electrical:
    return Electrical.model_validate(
        {
            "points": points,
            "board": {"room": "k", "wall": "w1", "offset": 2000, "height": 1700},
            "cables": [
                {
                    "id": f"c_{g}",
                    "from": "board",
                    "to": [p["id"] for p in points if p["group"] == g],
                    "group": g,
                    "cable": mark,
                }
                for g, mark in cables.items()
            ],
            **extra,
        }
    )


def test_parsers() -> None:
    assert cable_section("ВВГнг 3х2,5") == 2.5
    assert cable_section("3x1.5") == 1.5 and cable_section("кабель") is None
    assert parse_breaker("C16") == ("C", 16) and parse_breaker("b10") == ("B", 10)
    assert parse_breaker("16 А") == ("C", 16) and parse_breaker("—") is None
    assert rating_for(17.0) == 20 and rating_for(3.0, 10) == 10


def test_breakers_by_kind_light_10_sockets_16_heavy_by_current() -> None:
    elec = _elec(
        [
            {"id": "l1", "room": "k", "type": "downlight", "ceiling": [500, 500], "group": "QF1"},
            _pt("s1", "socket", "QF2", count=2),
            _pt("o1", "socket", "QF3", note="духовка"),
        ],
        {"QF1": "3x1.5", "QF2": "3x2.5", "QF3": "3x2.5"},
    )
    panel = build_panel(_plan(), elec)
    assert panel is not None
    g = {x.group: x for x in panel.groups}
    assert (g["QF1"].kind, g["QF1"].breaker.rating) == (Kind.LIGHT, 10)
    assert (g["QF2"].kind, g["QF2"].breaker.rating) == (Kind.SOCKETS, 16)
    assert g["QF2"].power == 200  # two 100 W posts, an assumption
    assert g["QF3"].kind is Kind.HEAVY and g["QF3"].breaker.rating == 16  # a 2.5 cable carries 16
    assert all(gr.breaker.assumed for gr in panel.groups)


def test_source_power_and_breaker_win_over_defaults() -> None:
    elec = _elec(
        [_pt("s1", "socket", "QF1", power=3000)],
        {"QF1": "3x1.5"},
        groups={"QF1": {"breaker": "C25"}},
    )
    panel = build_panel(_plan(), elec)
    assert panel is not None
    grp = panel.groups[0]
    assert grp.power == 3000 and not grp.assumed and grp.breaker.label == "C25"
    texts = [w.text["ru"] for w in panel.warnings]
    assert any("не защищает кабель 3x1.5" in t for t in texts)  # 25 A on 1.5 mm²


def test_overloaded_group_is_split_into_lines_and_asked() -> None:
    elec = _elec(
        [
            _pt("s1", "socket", "QF1", room="b", note="бойлер"),
            _pt("s2", "socket", "QF1", room="b", note="пральна машина"),
            _pt("s3", "socket", "QF1", room="b"),
        ],
        {"QF1": "3x2.5"},
        panel={"backup": "none"},
    )
    panel = build_panel(_plan(), elec)
    assert panel is not None
    lines = {g.group: g for g in panel.groups}
    assert set(lines) == {"QF1", "QF1.2"}
    assert {ld.point for ld in lines["QF1"].loads} == {"s2", "s3"}  # 2.2 + 0.1 kW
    assert [ld.point for ld in lines["QF1.2"].loads] == ["s1"]
    assert all(g.current <= g.breaker.rating and g.split_of == "QF1" for g in lines.values())
    qs = {q.id: q for q in panel_questions(elec, panel, "ru")}
    split = qs["panel_split_QF1"]
    assert split.severity == "major" and "дифавтомат" in split.text and "QF1.2" in split.text
    assert "panel_backup" not in qs  # backup is set


def test_single_heavy_load_over_breaker_asks_for_cable() -> None:
    elec = _elec(
        [_pt("h1", "outlet", "QF1", note="варильна поверхня"), _pt("s1", "socket", "QF2")],
        {"QF1": "3x4", "QF2": "3x2.5"},
        panel={"input": 25, "backup": "none"},
    )
    panel = build_panel(_plan(), elec)
    assert panel is not None
    g = next(x for x in panel.groups if x.group == "QF1")
    assert g.power == 7200 and g.split_of is None  # a single appliance is not split
    q = next(q for q in panel_questions(elec, panel, "ru") if q.id == "panel_cable_QF1")
    assert "3x6" in q.text and "32 А" in q.text
    texts = [w.text["ru"] for w in panel.warnings]
    assert any("больше вводного автомата 25 А" in t for t in texts)


def test_schemes_rcd_curve_relay_spd_ats() -> None:
    points = [
        _pt("s1", "socket", "QF1"),
        _pt("s2", "socket", "QF2", room="b"),
        _pt("s3", "socket", "QF4", room="b"),
        {"id": "l1", "room": "k", "type": "light", "ceiling": [500, 500], "group": "QF3"},
        _pt("a1", "outlet", "QF5", note="кондиціонер"),
    ]
    cables = {"QF1": "3x2.5", "QF2": "3x2.5", "QF3": "3x1.5", "QF4": "3x2.5", "QF5": "3x2.5"}

    def build(scheme: str, **kw: Any) -> dict[str, Device]:
        elec = _elec(points, cables, panel={"scheme": scheme, "backup": "inverter", **kw})
        panel = build_panel(_plan(), elec)
        assert panel is not None
        return {d.id: d for d in panel.devices}

    eco = build("economy")
    assert "KV1" in eco and "FV1" not in eco  # relay in every scheme
    assert "SA1" in eco and "KM1" not in eco and eco["QS3"].kind is DeviceKind.OUTPUT
    rcd = next(d for d in eco.values() if d.kind is DeviceKind.RCD)
    assert set(rcd.feeds) == {"QF2", "QF4"}  # wet groups under one RCD
    assert eco["QF1"].kind is DeviceKind.BREAKER and eco["QF1"].label == "C16"
    std = build("standard")
    assert "KV1" in std and "FV1" not in std
    assert "SA1" in std and "KM1" not in std  # a hybrid switches itself: bypass switch
    assert "KM1" in build("standard", inverter="basic")  # no switching of its own: ATS
    assert "KM1" in build("economy", ats=True)  # explicitly set wins
    assert std["QF2"].kind is DeviceKind.DIFF and std["QF1"].kind is DeviceKind.BREAKER
    prem = build("premium")
    assert "KV1" in prem and "FV1" in prem
    assert all(prem[g].kind is DeviceKind.DIFF for g in ("QF1", "QF2", "QF3", "QF4", "QF5"))
    assert prem["QF1"].label.startswith("B16") and prem["QF3"].label.startswith("B10")
    assert prem["QF5"].label.startswith("C16")  # air conditioner: inrush current


def test_mode_maps_to_scheme_and_backup_defaults_to_inverter_with_question() -> None:
    points = [
        _pt("s1", "socket", "QF1", note="холодильник"),
        _pt("s2", "socket", "QF2", room="b"),
        {"id": "l1", "room": "k", "type": "light", "ceiling": [500, 500], "group": "QF3"},
    ]
    cables = {"QF1": "3x2.5", "QF2": "3x2.5", "QF3": "3x1.5"}
    elec = _elec(points, cables, mode="proper")
    panel = build_panel(_plan(), elec)
    assert panel is not None and panel.scheme == "premium"
    assert panel.backup == "inverter" and panel.backup_assumed
    assert not panel.input.assumed or panel.input.rating == 63
    reserved = {g.group for g in panel.groups if g.reserved}
    assert reserved == {"QF1", "QF3"}  # kitchen: sockets and fridge; lighting; bathroom: no
    qs = {q.id: q for q in panel_questions(elec, panel, "ru")}
    assert qs["panel_backup"].target == "panel.backup" and qs["panel_backup"].options
    assert qs["panel_input"].assumption == 63
    assert "panel_reserve" in qs


def test_panel_questions_follow_project_language() -> None:
    elec = _elec([_pt("s1", "socket", "QF1")], {"QF1": "3x2.5"}, mode="proper")
    panel = build_panel(_plan(), elec)
    assert panel is not None and panel.dc is not None
    ru = {q.id: q for q in panel_questions(elec, panel, "ru")}
    uk = {q.id: q for q in panel_questions(elec, panel, "uk")}
    assert ru.keys() == uk.keys() and {"panel_backup", "panel_npe", "panel_pv"} <= uk.keys()
    assert uk["panel_backup"].text != ru["panel_backup"].text
    assert uk["panel_backup"].option_labels["none"] == "Без резерву"
    for q in uk.values():
        shown = [q.text, *(q.option_labels or {}).values()]
        assert not re.search("[ыэъё]", " ".join(shown), re.IGNORECASE), q.id


def test_panel_texts_have_both_languages() -> None:
    assert all(set(by_language) == {"ru", "uk"} for by_language in TEXT.values())


def test_backup_plug_reserve_bus_and_warning() -> None:
    points = [
        _pt("s1", "socket", "QF1", note="холодильник"),
        _pt("s2", "socket", "QF2", room="b"),
        {"id": "l1", "room": "k", "type": "light", "ceiling": [500, 500], "group": "QF3"},
    ]
    cables = {"QF1": "3x2.5", "QF2": "3x2.5", "QF3": "3x1.5"}
    setup = {"scheme": "economy", "backup": "plug", "backup_power": 0.2}
    panel = build_panel(_plan(), _elec(points, cables, panel=setup))
    assert panel is not None
    sa = next(d for d in panel.devices if d.id == "SA1")
    after = panel.devices[panel.devices.index(sa) + 1 :]
    assert {d.group for d in after if d.group} == {g.group for g in panel.groups if g.reserved}
    texts = [w.text["ru"] for w in panel.warnings]
    assert any("вилка-вилка" in t for t in texts)
    assert any("Резервная шина" in t for t in texts)
    ats = build_panel(_plan(), _elec(points, cables, panel={**setup, "ats": True}))
    assert ats is not None and any(d.kind is DeviceKind.ATS for d in ats.devices)


def test_reserve_kinds_for_quick_picks() -> None:
    points = [
        _pt("s1", "socket", "QF1", note="холодильник"),
        {"id": "l1", "room": "k", "type": "light", "ceiling": [500, 500], "group": "QF2"},
        _pt("f1", "outlet", "QF2", note="вентилятор", power=40),  # bathroom light with its fan
        _pt("ac", "outlet", "QF3", note="кондиционер", power=1500),
        _pt("ov", "socket", "QF4", note="духовка", power=3500),
    ]
    cables = {"QF1": "3x2.5", "QF2": "3x1.5", "QF3": "3x2.5", "QF4": "3x2.5"}
    elec = _elec(points, cables, panel={"backup": "plug", "backup_power": 3})
    panel = build_panel(_plan(), elec)
    assert panel is not None
    block = reserve_data(panel, elec)
    assert block is not None
    kinds = {g["id"]: g["kind"] for g in cast(list[dict[str, Any]], block["items"])}
    assert kinds == {"QF1": "sockets", "QF2": "light", "QF3": "heavy", "QF4": "heavy"}


def test_charging_station_comes_in_through_a_plug() -> None:
    elec = _elec([_pt("s1", "socket", "QF1")], {"QF1": "3x2.5"}, panel={"backup": "station"})
    panel = build_panel(_plan(), elec)
    assert panel is not None and panel.dc is None
    assert any(d.id == "SA1" for d in panel.devices)
    assert any("Зарядная станция" in w.text["ru"] for w in panel.warnings)
    assert "panel_battery" not in {q.id for q in panel_questions(elec, panel, "ru")}
    external = cast(dict[str, str], panel_data(panel, {}, "ЩР", "ru")["external"])
    assert external["id"] == "XP1" and "зарядной станции" in external["title"]
    with pytest.raises(ValidationError):
        _elec([_pt("s1", "socket", "QF1")], {}, panel={"backup": "station", "pv_strings": 1})


def test_panel_data_carries_catalog_models_and_texts() -> None:
    elec = _elec([_pt("s1", "socket", "QF1", room="b")], {"QF1": "3x2.5"})
    panel = build_panel(_plan(), elec)
    assert panel is not None
    data = panel_data(panel, {"QF1": 0x4E79A7}, "ЩР", "uk")
    devices = data["devices"]
    assert isinstance(devices, list)
    qf1 = next(d for d in devices if d["id"] == "QF1")
    assert qf1["key"] == "device:QF1" and qf1["model"]["id"] == "generic.diff"
    assert qf1["model"]["width"] == 35.0  # 2 modules of 17.5 mm
    assert data["groups"]["QF1"]["color"] == "#4e79a7"  # type: ignore[index]
    assert "звичайний, резерв: інвертор*" in data["texts"]["title"]  # type: ignore[index]


def test_answers_to_panel_questions_apply_to_model(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    plan = {"name": "T", "default_wall_thickness": 100, "source": "text", "rooms": ROOMS}
    points = [_pt("s1", "socket", "QF1", room="b")]
    elec = {
        "points": points,
        "board": {"room": "k", "wall": "w1", "offset": 2000, "height": 1700},
        "cables": [{"id": "c1", "from": "board", "to": ["s1"], "group": "QF1", "cable": "3x2.5"}],
    }
    (project / "room.yaml").write_text(yaml.safe_dump(plan, allow_unicode=True), "utf-8")
    (project / "electrical.yaml").write_text(yaml.safe_dump(elec, allow_unicode=True), "utf-8")
    report = validate_project(project)
    ids = {q.id for q in report.auto_questions}
    assert {"panel_backup", "panel_input", "panel_reserve"} <= ids
    answers = {"answers": {"panel_backup": "none", "panel_input": 40, "panel_xyz": 1}}
    (project / "answers.yaml").write_text(yaml.safe_dump(answers), "utf-8")
    report = validate_project(project)
    assert report.electrical is not None
    assert report.electrical.panel.backup == "none" and report.electrical.panel.input == 40
    states = report.question_states
    assert states["panel_backup"] == "answered" and states["panel_input"] == "answered"
    assert "panel_reserve" not in states  # no backup, no question
    assert not report.errors
    assert any(i.path == "answers.panel_xyz" for i in report.warnings)
    stages = {r.stage: r for r in assess(report)}
    assert stages[Stage.PANEL].status.builds


def test_unknown_brand_is_an_error() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="нет в каталоге"):
        Electrical.model_validate({"panel": {"brand": "acme"}})


def test_din_rows_keep_devices_whole() -> None:
    elec = _elec(
        [_pt(f"s{k}", "socket", f"QF{k}") for k in range(1, 9)],
        {f"QF{k}": "3x2.5" for k in range(1, 9)},
    )
    panel = build_panel(_plan(), elec)
    assert panel is not None
    rows = din_rows(panel.devices, 12)
    assert all(sum(d.modules for d in r) <= 12 for r in rows)
    assert [d for r in rows for d in r] == list(panel.devices)


def _breakers(n: int, kind: DeviceKind = DeviceKind.BREAKER) -> list[Device]:
    return [Device(f"QF{k}", kind, "C16", "", group=f"QF{k}") for k in range(1, n + 1)]


def test_panel_rows_by_kind_never_wider_than_rail() -> None:
    common = [
        Device("KV1", DeviceKind.RELAY, "63 А", ""),
        Device("QS1", DeviceKind.INPUT, "C63 2P", ""),
    ]
    devices = common + _breakers(13) + _breakers(3, DeviceKind.DIFF)
    rows = panel_rows(devices, 12)
    assert rows is not None
    assert [d.id for d in rows[0]] == ["QS1", "KV1"]  # shared devices on their own rail, in order
    assert [len(r) for r in rows] == [2, 12, 1, 3]  # breakers 12 + 1, RCBOs separately
    assert all(sum(d.modules for d in r) <= 12 for r in rows)
    assert panel_rows([Device("KM1", DeviceKind.ATS, "АВР", "")], 3) is None  # wider than a rail


def test_smallest_enclosure_that_fits() -> None:
    devices = [Device("QS1", DeviceKind.INPUT, "C63 2P", ""), *_breakers(10)]
    enc, rows, note = choose_enclosure(devices)
    assert enc.article == "VS212PD" and len(rows) == 2 and note is None
    assert (enc.width, enc.height) == (282.0, 377.0)
    enc, rows, note = choose_enclosure([*devices, *_breakers(14)])  # 24 breakers
    assert enc.article == "VS312PD"  # 3 × 12 has fewer modules than 2 × 18
    assert all(sum(d.modules for d in r) <= enc.per_row for r in rows)


def test_asked_enclosure_and_fallbacks() -> None:
    devices = [Device("QS1", DeviceKind.INPUT, "C63 2P", ""), *_breakers(10)]
    enc, _, note = choose_enclosure(devices, "VS418PD")
    assert enc.article == "VS418PD" and note is None
    enc, _, note = choose_enclosure(devices, "VS112PD")  # does not fit: larger, with a remark
    assert enc.article == "VS212PD" and note is not None and "VS112PD" in note.text["ru"]
    many = [*devices, *_breakers(80)]
    enc, rows, note = choose_enclosure(many)  # fits nowhere: on-site enclosure
    assert not enc.article and enc.rows == len(rows) and note is not None
    assert all(sum(d.modules for d in r) <= enc.per_row for r in rows)


def test_enclosure_catalog_is_hager_golf_and_goes_to_epd() -> None:
    assert {e.article for e in ENCLOSURES} >= {"VS112PD", "VS418PD"}
    assert all(e.per_row * 17.5 < e.width for e in ENCLOSURES)  # rail inside the enclosure
    elec = _elec([_pt("s1", "socket", "QF1")], {"QF1": "3x2.5"}, panel={"enclosure": "VS218PD"})
    panel = build_panel(_plan(), elec)
    assert panel is not None and panel.enclosure is not None
    data = panel_data(panel, {}, "ЩР", "ru")
    enc = data["enclosure"]
    assert isinstance(enc, dict) and enc["title"] == "Hager Golf VS218PD" and enc["per_row"] == 18
    devices = data["devices"]
    assert isinstance(devices, list) and all("row" in d for d in devices)


def test_unknown_enclosure_is_an_error() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="щита «VX1» нет в каталоге"):
        Electrical.model_validate({"panel": {"enclosure": "VX1"}})


def test_inverter_gets_battery_box_with_assumptions_and_questions() -> None:
    elec = _elec([_pt("s1", "socket", "QF1")], {"QF1": "3x2.5"})
    panel = build_panel(_plan(), elec)
    assert panel is not None and panel.backup == "inverter" and panel.dc is not None
    dc = panel.dc
    assert (dc.voltage, dc.voltage_assumed, dc.power) == (48, True, 5.0)
    assert dc.rating == 125 and dc.cable == 35  # 5 kW / 48 V ≈ 104 A → 125 A, 35 mm²
    assert [d.id for d in dc.devices] == ["QB1"]  # no solar panels
    assert dc.enclosure.article == "VS112PD"
    assert any("АКБ 48 В" in w.text["ru"] for w in panel.warnings)
    assert [d.id for d in panel.all_devices][-1] == "QB1"
    ids = {q.id for q in panel_questions(elec, panel, "ru")}
    assert {"panel_battery", "panel_pv", "panel_dc_place"} <= ids


def test_battery_box_from_source_with_pv_strings() -> None:
    setup = {"backup": "inverter", "backup_power": 8, "battery_voltage": 48, "pv_strings": 2}
    elec = _elec([_pt("s1", "socket", "QF1")], {"QF1": "3x2.5"}, panel=setup)
    panel = build_panel(_plan(), elec)
    assert panel is not None and panel.dc is not None
    dc = panel.dc
    assert dc.rating == 200 and dc.cable == 70  # 8 kW / 48 V ≈ 167 A
    assert [d.id for d in dc.devices] == ["QB1", "QP1", "FP1", "QP2", "FP2"]
    assert dc.enclosure.per_row == 18  # 13 modules
    ids = {q.id for q in panel_questions(elec, panel, "ru")}
    assert "panel_battery" not in ids and "panel_pv" not in ids
    data = panel_data(panel, {}, "ЩР", "ru")
    block = data["dc"]
    assert isinstance(block, dict) and block["pv_strings"] == 2
    assert block["battery"]["rating"] == 200
    assert block["texts"]["kwh"] == "кВт·ч"  # capacity unit in the project language
    uk = panel_data(panel, {}, "ЩР", "uk")["dc"]
    assert isinstance(uk, dict) and uk["texts"]["kwh"] == "кВт·год"


def test_no_battery_box_without_inverter() -> None:
    import pytest
    from pydantic import ValidationError

    elec = _elec([_pt("s1", "socket", "QF1")], {"QF1": "3x2.5"}, panel={"backup": "plug"})
    panel = build_panel(_plan(), elec)
    assert panel is not None and panel.dc is None
    with pytest.raises(ValidationError, match="только с инвертором"):
        Electrical.model_validate({"panel": {"backup": "none", "pv_strings": 1}})


def test_inverter_output_breaker_and_npe_question() -> None:
    from floorplan_engine.validation.assess import severity

    elec = _elec([_pt("s1", "socket", "QF1")], {"QF1": "3x2.5"})
    panel = build_panel(_plan(), elec)
    assert panel is not None
    ids = [d.id for d in panel.devices]
    assert ids.index("QS3") == ids.index("SA1") + 1  # inverter output next to the switch
    assert any("N з PE" in w.text["uk"] and w.severity == "major" for w in panel.warnings)
    qs = {q.id: q for q in panel_questions(elec, panel, "ru")}
    assert severity(qs["panel_npe"]).value == "major"
    assert qs["panel_inverter"].options == ["hybrid", "basic"]
    answered = _elec([_pt("s1", "socket", "QF1")], {"QF1": "3x2.5"}, panel={"npe_relay": "no"})
    panel = build_panel(_plan(), answered)
    assert panel is not None
    assert any("контактор N–PE" in w.text["ru"] for w in panel.warnings)
    assert "panel_npe" not in {q.id for q in panel_questions(answered, panel, "ru")}


def _three_phase(**panel: Any) -> tuple[BoardPanel, Electrical]:
    points = [
        _pt("cook", "outlet", "QF1", note="варочная панель"),
        _pt("oven", "outlet", "QF2", note="духовка"),
        _pt("wash", "outlet", "QF3", room="b", note="стиральная машина"),
        _pt("s1", "socket", "QF4", count=4),
        _pt("l1", "light", "QF5"),
        _pt("l2", "light", "QF6", room="b"),
    ]
    elec = Electrical.model_validate(
        {"panel": {"phases": 3, "backup": "none", **panel}, "points": points}
    )
    built = build_panel(_plan(), elec)
    assert built is not None
    return built, elec


def test_three_phase_panel() -> None:
    """Three phases: main switch and surge protector 3P+N, a relay per phase, the cooktop on its
    3P breaker with a five-core cable, the other groups spread over the phases."""
    panel, elec = _three_phase(scheme="premium")
    by_id = {d.id: d for d in panel.devices}
    assert by_id["QS1"].label.endswith("4P") and by_id["QS1"].modules == 4
    assert [by_id[k].phase for k in ("KV1", "KV2", "KV3")] == ["L1", "L2", "L3"]
    assert by_id["FV1"].modules == 4
    cook = by_id["QF1"]
    assert cook.phase == "3P" and cook.label == "B16 30 мА 4P" and cook.modules == 4
    assert device_name(cook, "ru") == "Дифавтомат 3P+N B16 30 мА"
    groups = {g.group: g for g in panel.groups}
    assert groups["QF1"].current == pytest.approx(7200 / 230 / 3)
    assert {groups[g].phase for g in ("QF2", "QF3", "QF4", "QF5", "QF6")} <= {"L1", "L2", "L3"}
    assert groups["QF5"].phase != groups["QF6"].phase  # lighting on two phases
    assert len({groups[g].phase for g in ("QF2", "QF3", "QF4")}) == 3  # appliances spread out
    assert heavy_cable(elec, "QF1", [p for p in elec.points if p.group == "QF1"]) == "5x2.5"
    assert sum(panel.phase_loads.values()) == pytest.approx(panel.installed)
    assert "3 фазы, 400 В" in panel_title(panel, "ЩР", "ru")
    data = panel_data(panel, {}, "ЩР", "ru")
    assert data["phases"] == 3 and set(cast(dict[str, float], data["phase_loads"])) == {
        "L1",
        "L2",
        "L3",
    }


def test_three_phase_weak_spots_and_questions() -> None:
    """The input question is per phase; a phase above the main breaker; a three-phase appliance
    listed for the backup bus; unset phases ask a question with one phase as the assumption."""
    panel, elec = _three_phase(input=16)
    texts = [w.text["ru"] for w in panel.warnings]
    assert any(t.startswith("Расчётный ток фазы") for t in texts)
    asked = {q.id: q for q in panel_questions(elec, panel, "ru")}
    assert "panel_phases" not in asked
    backup, _ = _three_phase(backup="plug", reserve=["QF1", "QF5"])
    assert any("трёхфазный прибор" in w.text["ru"] for w in backup.warnings)
    assert not next(g for g in backup.groups if g.group == "QF1").reserved
    reserve = {d.phase for d in backup.devices if d.reserve or d.id == "SA1"}
    assert len(reserve) == 1  # the backup source has one phase
    single = Electrical.model_validate({"points": [_pt("s1", "socket", "QF1")]})
    one = build_panel(_plan(), single)
    assert one is not None and one.phases == 1 and one.phase_loads == {}
    q = next(q for q in panel_questions(single, one, "ru") if q.id == "panel_phases")
    assert q.target == "panel.phases" and q.assumption == 1


def test_reserve_groups_gather_the_lines_of_a_model_group() -> None:
    def group(name: str) -> SimpleNamespace:
        return SimpleNamespace(group=name)

    lines = [group(n) for n in ("QF1", "QF1.2", "QF1.3", "QF2", "QF8.2", "QF8.2.2")]
    panel = cast(BoardPanel, SimpleNamespace(groups=lines))
    points = [group(n) for n in ("QF1", "QF2", "QF8.2")]
    model = cast(Electrical, SimpleNamespace(points=points, cables=[]))
    assert {k: [g.group for g in v] for k, v in reserve_groups(panel, model).items()} == {
        "QF1": ["QF1", "QF1.2", "QF1.3"],
        "QF2": ["QF2"],
        "QF8.2": ["QF8.2", "QF8.2.2"],  # a dot in the model's own group name stays
    }
