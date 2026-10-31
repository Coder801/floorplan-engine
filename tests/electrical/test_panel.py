"""Щит в лицо: потребители, автоматы, состав щита по схеме и слабые места."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from floorplan_engine.electrical.loads import Kind, cable_section, parse_breaker, rating_for
from floorplan_engine.electrical.panel import Device, build_panel, din_rows
from floorplan_engine.electrical.panel_questions import panel_questions
from floorplan_engine.epd.panel_data import panel_data
from floorplan_engine.model.intake import Stage
from floorplan_engine.model.panel_catalog import DeviceKind
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
    assert g["QF2"].power == 200  # два поста по 100 Вт — допущение
    assert g["QF3"].kind is Kind.HEAVY and g["QF3"].breaker.rating == 16  # кабель 2,5 держит 16
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
    assert any("не защищает кабель 3x1.5" in t for t in texts)  # 25 А на 1,5 мм²


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
    assert {ld.point for ld in lines["QF1"].loads} == {"s2", "s3"}  # 2,2 + 0,1 кВт
    assert [ld.point for ld in lines["QF1.2"].loads] == ["s1"]
    assert all(g.current <= g.breaker.rating and g.split_of == "QF1" for g in lines.values())
    qs = {q.id: q for q in panel_questions(elec, panel)}
    split = qs["panel_split_QF1"]
    assert split.severity == "major" and "дифавтомат" in split.text and "QF1.2" in split.text
    assert "panel_backup" not in qs  # резерв задан


def test_single_heavy_load_over_breaker_asks_for_cable() -> None:
    elec = _elec(
        [_pt("h1", "outlet", "QF1", note="варильна поверхня"), _pt("s1", "socket", "QF2")],
        {"QF1": "3x4", "QF2": "3x2.5"},
        panel={"input": 25, "backup": "none"},
    )
    panel = build_panel(_plan(), elec)
    assert panel is not None
    g = next(x for x in panel.groups if x.group == "QF1")
    assert g.power == 7200 and g.split_of is None  # один прибор не делится
    q = next(q for q in panel_questions(elec, panel) if q.id == "panel_cable_QF1")
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

    def build(scheme: str) -> dict[str, Device]:
        elec = _elec(points, cables, panel={"scheme": scheme, "backup": "inverter"})
        panel = build_panel(_plan(), elec)
        assert panel is not None
        return {d.id: d for d in panel.devices}

    eco = build("economy")
    assert "KV1" not in eco and "FV1" not in eco and "SA1" in eco and "KM1" not in eco
    rcd = next(d for d in eco.values() if d.kind is DeviceKind.RCD)
    assert set(rcd.feeds) == {"QF2", "QF4"}  # мокрые — под одним УЗО
    assert eco["QF1"].kind is DeviceKind.BREAKER and eco["QF1"].label == "C16"
    std = build("standard")
    assert "KV1" in std and "FV1" not in std and "KM1" in std
    assert std["QF2"].kind is DeviceKind.DIFF and std["QF1"].kind is DeviceKind.BREAKER
    prem = build("premium")
    assert "KV1" in prem and "FV1" in prem
    assert all(prem[g].kind is DeviceKind.DIFF for g in ("QF1", "QF2", "QF3", "QF4", "QF5"))
    assert prem["QF1"].label.startswith("B16") and prem["QF3"].label.startswith("B10")
    assert prem["QF5"].label.startswith("C16")  # кондиционер — пусковой ток


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
    assert reserved == {"QF1", "QF3"}  # кухня: розетки и холодильник; свет; санузел — нет
    qs = {q.id: q for q in panel_questions(elec, panel)}
    assert qs["panel_backup"].target == "panel.backup" and qs["panel_backup"].options
    assert qs["panel_input"].assumption == 63
    assert "panel_reserve" in qs


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


def test_panel_data_carries_catalog_models_and_texts() -> None:
    elec = _elec([_pt("s1", "socket", "QF1", room="b")], {"QF1": "3x2.5"})
    panel = build_panel(_plan(), elec)
    assert panel is not None
    data = panel_data(panel, {"QF1": 0x4E79A7}, "ЩР", "uk")
    devices = data["devices"]
    assert isinstance(devices, list)
    qf1 = next(d for d in devices if d["id"] == "QF1")
    assert qf1["key"] == "device:QF1" and qf1["model"]["id"] == "generic.diff"
    assert qf1["model"]["width"] == 35.0  # 2 модуля по 17,5 мм
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
    assert "panel_reserve" not in states  # резерва нет — вопроса нет
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


def test_three_phase_not_yet() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="трёхфазный"):
        Electrical.model_validate({"panel": {"phases": 3}})
