"""Master switch: what it cuts, contactors and control breaker, questions, its point and cable."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from pydantic import ValidationError

from floorplan_engine.electrical.master import (
    CONTROL_ID,
    CONTROL_MARK,
    POINT_ID,
    master_on,
    master_point,
    placed_by_code,
    with_master_switch,
)
from floorplan_engine.electrical.panel import build_panel
from floorplan_engine.electrical.panel_questions import GROUPS_FIELD, panel_questions
from floorplan_engine.electrical.switch_links import switch_links
from floorplan_engine.electrical.wiring import box_wiring
from floorplan_engine.epd.panel_data import master_data, panel_data
from floorplan_engine.model.panel_catalog import DeviceKind
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.validation.plan import validate_plan
from floorplan_engine.validation.validate import validate_project

ROOMS = [
    {
        "id": "h",
        "name": "Прихожая",
        "walls": [{"id": f"w{n}", "length": 3000} for n in range(1, 5)],
    },
]


def _plan(language: str = "ru") -> Plan:
    return Plan.model_validate(
        {
            "name": "T",
            "default_wall_thickness": 100,
            "source": "text",
            "language": language,
            "rooms": ROOMS,
        }
    )


def _pt(pid: str, kind: str, group: str | None, offset: float = 500, **kw: Any) -> dict[str, Any]:
    return {
        "id": pid,
        "room": "h",
        "type": kind,
        "wall": "w2",
        "offset": offset,
        "height": 300,
        "group": group,
        **kw,
    }


def _elec(
    panel: dict[str, Any] | None = None, extra: list[dict[str, Any]] | None = None
) -> Electrical:
    points = [
        _pt("l1", "sconce", "QF1", height=1800),
        _pt("s1", "socket", "QF2", 900),
        _pt("f1", "socket", "QF3", 1500, note="холодильник"),
        _pt("f2", "socket", "QF3", 1800),
        _pt("b1", "outlet", "QF4", 2200, note="котёл"),
        *(extra or []),
    ]
    return Electrical.model_validate(
        {
            "board": {"room": "h", "wall": "w1", "offset": 600, "height": 1700},
            "points": points,
            "panel": {"backup": "none", **(panel or {})},
        }
    )


def test_master_off_by_default_and_from_source() -> None:
    """Unset: off; a switch noted "мастер" in the source turns it on; an explicit no wins."""
    assert not master_on(_elec())
    noted = [_pt("m", "switch", None, 2600, height=900, note="Мастер-выключатель")]
    assert master_on(_elec(extra=noted))
    assert not master_on(_elec({"master": False}, noted))
    assert master_on(_elec({"master": True}))


def test_master_off_needs_master() -> None:
    with pytest.raises(ValidationError, match="master_off"):
        _elec({"master": False, "master_off": ["QF1"]})


def test_rule_keeps_always_on_groups() -> None:
    """By the rule everything is cut except a group with a fridge or boiler; a mixed group stays
    on as a whole and is a weak spot."""
    panel = build_panel(_plan(), _elec({"master": True}))
    assert panel is not None
    cut = {g.group for g in panel.groups if g.master}
    assert cut == {"QF1", "QF2"}
    mixed = [w for w in panel.warnings if w.group == "QF3"]
    assert any("Холодильник" in w.text["ru"] for w in mixed)
    assert not any(w.group == "QF4" and "мастер" in w.text["ru"] for w in panel.warnings)


def test_master_off_list_wins() -> None:
    panel = build_panel(_plan(), _elec({"master": True, "master_off": ["QF3"]}))
    assert panel is not None
    assert {g.group for g in panel.groups if g.master} == {"QF3"}
    assert not any("мастер" in w.text["ru"] for w in panel.warnings)


def test_contactor_and_control_breaker() -> None:
    """Main bus: KM2 after the shared devices, SF1 B6, the groups behind it after the others."""
    panel = build_panel(_plan(), _elec({"master": True}))
    assert panel is not None
    ids = [d.id for d in panel.devices]
    km = next(d for d in panel.devices if d.id == "KM2")
    assert km.kind is DeviceKind.CONTACTOR and km.label == "25 А 2P"
    assert set(km.feeds) == {"QF1", "QF2"}
    assert "KM3" not in ids
    sf = next(d for d in panel.devices if d.id == CONTROL_ID)
    assert sf.label == "B6" and not sf.reserve
    groups = [d for d in panel.devices if d.group]
    assert [d.master for d in groups] == sorted(d.master for d in groups)  # kept first
    assert any(row[0].kind is DeviceKind.INPUT and km in row for row in panel.rows)


def test_contactor_rating_capped_by_main_breaker() -> None:
    """Heavy groups: the contactor needs no more than the main breaker lets through."""
    heavy = [_pt(f"o{k}", "outlet", f"QF{5 + k}", 300 + 200 * k, power=7000) for k in range(4)]
    panel = build_panel(_plan(), _elec({"master": True, "input": 40}, heavy))
    assert panel is not None
    km = next(d for d in panel.devices if d.id == "KM2")
    assert km.label == "40 А 2P"
    assert not any("контактор" in w.text["ru"] for w in panel.warnings)


def test_backup_bus_gets_its_own_contactor() -> None:
    """Light on the backup bus is cut by KM3 behind the switch; SF1 is on the backup bus so the
    master switch works on backup too."""
    panel = build_panel(_plan(), _elec({"master": True, "backup": "plug"}))
    assert panel is not None
    km3 = next(d for d in panel.devices if d.id == "KM3")
    assert km3.reserve and "QF1" in km3.feeds
    ids = [d.id for d in panel.devices]
    assert ids.index("SA1") < ids.index(CONTROL_ID) < ids.index("KM3")
    assert next(d for d in panel.devices if d.id == CONTROL_ID).reserve


def test_three_phase_contactor_is_4p() -> None:
    panel = build_panel(_plan(), _elec({"master": True, "phases": 3}))
    assert panel is not None
    km = next(d for d in panel.devices if d.id == "KM2")
    assert km.poles == 4 and km.phase == "3P" and km.label.endswith("4P")
    assert km.model.modules == 3


def test_questions_master_then_groups_and_place() -> None:
    plan = _plan()
    elec = _elec()
    panel = build_panel(plan, elec)
    assert panel is not None
    qs = {q.id: q for q in panel_questions(elec, panel, "ru")}
    assert qs["panel_master"].assumption == "no" and qs["panel_master"].target == "panel.master"
    assert "panel_master_off" not in qs
    on = _elec({"master": True})
    panel = build_panel(plan, on)
    assert panel is not None
    qs = {q.id: q for q in panel_questions(on, panel, "ru")}
    assert "panel_master" not in qs
    assert qs["panel_master_off"].options == ["QF1", "QF2", "QF3", "QF4"]
    assert "panel_master_place" in qs
    assert GROUPS_FIELD["panel_master_off"] == "master_off"


def test_question_assumes_yes_with_source_point() -> None:
    noted = [_pt("m", "switch", None, 2600, height=900, note="майстер-вимикач")]
    elec = _elec(extra=noted)
    panel = build_panel(_plan("uk"), elec)
    assert panel is not None
    qs = {q.id: q for q in panel_questions(elec, panel, "uk")}
    assert qs["panel_master"].assumption == "yes"
    assert "panel_master_place" not in qs


def test_point_next_to_panel() -> None:
    """No master point: one next to the panel on its wall, an assumption; a source one is kept."""
    plan = _plan()
    elec = with_master_switch(plan, _elec({"master": True}))
    p = master_point(elec)
    assert p is not None and p.id == POINT_ID and p.wall == "w1" and p.height == 900
    assert p.offset is not None and p.offset > 600
    assert placed_by_code(elec)
    assert with_master_switch(plan, _elec()) == _elec()
    noted = [_pt("m", "switch", None, 2600, height=900, note="мастер")]
    src = _elec({"master": True}, noted)
    assert with_master_switch(plan, src) is src


def test_point_goes_left_at_wall_end() -> None:
    plan = _plan()
    elec = _elec({"master": True}).model_copy(
        update={"board": _elec().board.model_copy(update={"offset": 2800})}  # type: ignore[union-attr]
    )
    p = master_point(with_master_switch(plan, elec))
    assert p is not None and p.offset is not None and p.offset < 2800


def test_control_cable_from_panel_whatever_group() -> None:
    """The master switch gets a control cable of its own from the panel (SF1) even if the source
    put it in a light group, and never a guessed link to lights."""
    plan = _plan()
    noted = [_pt("m", "switch", "QF1", 2600, height=900, note="мастер-выключатель")]
    elec = _elec({"master": True}, noted)
    wiring = box_wiring(plan, validate_plan(plan)[1], elec)
    assert wiring is not None
    control = [r for r in wiring.runs if r.target == "m"]
    assert len(control) == 1
    assert control[0].group == CONTROL_ID and control[0].mark == CONTROL_MARK
    assert control[0].source == "board"
    assert "m" not in wiring.skipped
    assert not any(lk.switch == "m" for lk in switch_links(elec))


def test_viewer_data() -> None:
    """Panel page: groups behind the contactor are marked; overview: what it can cut."""
    plan = _plan()
    off = build_panel(plan, _elec())
    assert off is not None
    data = master_data(off, _elec())
    assert data["active"] is False
    items = {i["id"]: i for i in data["items"]}  # type: ignore[attr-defined]
    assert items["QF1"]["on"] and not items["QF3"]["on"] and items["QF3"]["keep"]
    on = build_panel(plan, _elec({"master": True}))
    assert on is not None
    devices = cast(list[dict[str, Any]], panel_data(on, {}, "ЩР", "ru")["devices"])
    marked = {d["id"] for d in devices if d.get("master")}
    assert marked == {"KM2", "QF1", "QF2"}


def test_answers_turn_master_on_with_groups(tmp_path: Path) -> None:
    """The wizard sends "yes" and the groups at once: the groups question appears with the first
    answer, its list goes into master_off (not reserve), and the model gets the switch point."""
    project = tmp_path / "p"
    project.mkdir()
    plan = {"name": "T", "default_wall_thickness": 100, "source": "text", "rooms": ROOMS}
    elec = _elec().model_dump(mode="json", by_alias=True, exclude_none=True)
    (project / "room.yaml").write_text(yaml.safe_dump(plan, allow_unicode=True), "utf-8")
    (project / "electrical.yaml").write_text(yaml.safe_dump(elec, allow_unicode=True), "utf-8")
    answers = {"answers": {"panel_master": "yes", "panel_master_off": ["QF1"]}}
    (project / "answers.yaml").write_text(yaml.safe_dump(answers), "utf-8")
    report = validate_project(project)
    assert not report.errors
    assert report.electrical is not None
    setup = report.electrical.panel
    assert setup.master is True and setup.master_off == ["QF1"] and setup.reserve == []
    assert report.question_states["panel_master_off"] == "answered"
    assert master_point(report.electrical) is not None
