"""Groups by phase on a three-phase panel: balance, one room on one phase, lighting on two
phases, units that share a phase, a phase from the model."""

from __future__ import annotations

from typing import Any

from floorplan_engine.electrical.loads import Breaker, Kind, Load, PanelGroup
from floorplan_engine.electrical.phases import assign_phases, phase_loads, unbalance
from floorplan_engine.model.schema import Electrical


def _g(
    name: str, power: float, room: str = "Кухня", kind: Kind = Kind.SOCKETS, **kw: Any
) -> PanelGroup:
    load = Load(f"p{name}", room, "x", 1, power, False)
    fields: dict[str, Any] = {"rcd": None, "reserved": False, "phase": None, **kw}
    return PanelGroup(
        name, kind, "x", False, (load,), "3x2.5", 2.5, Breaker("C", 16, True),
        fields["rcd"], False, fields["reserved"], phase=fields["phase"],
    )  # fmt: skip


def _phases(items: list[PanelGroup], **elec: Any) -> dict[str, str | None]:
    out = assign_phases(
        items, Electrical.model_validate({"panel": {"phases": 3}, **elec}), "standard"
    )
    return {g.group: g.phase for g in out}


def test_largest_first_on_the_least_loaded_phase() -> None:
    groups = [_g("QF1", 3000, "A"), _g("QF2", 2500, "B"), _g("QF3", 2000, "C"), _g("QF4", 900, "D")]
    phases = _phases(groups)
    assert [phases[g] for g in ("QF1", "QF2", "QF3")] == ["L1", "L2", "L3"]
    assert phases["QF4"] == "L3"  # the least loaded one after the three


def test_a_three_phase_appliance_is_shared_by_all() -> None:
    cooktop = _g("QF1", 7200, phase="3P")
    out = assign_phases([cooktop, _g("QF2", 1000)], Electrical(), "standard")
    assert out[0].phase == "3P" and out[0].current == cooktop.current
    assert phase_loads(out) == {"L1": 3400.0, "L2": 2400.0, "L3": 2400.0}
    assert round(cooktop.current, 1) == round(7200 / 230 / 3, 1)


def test_a_room_keeps_its_phase_while_the_phases_stay_close() -> None:
    groups = [_g("QF1", 3000, "Кухня"), _g("QF2", 1800, "Спальня"), _g("QF3", 1700, "Зал")]
    groups.append(_g("QF4", 300, "Кухня"))  # L1 is 1300 W above the least loaded: too much
    groups.append(_g("QF5", 200, "Зал"))  # L3 is the least loaded and holds the room anyway
    phases = _phases(groups)
    assert phases["QF4"] != phases["QF1"]
    assert phases["QF5"] == phases["QF3"]
    near = [_g("QF1", 1000, "Кухня"), _g("QF2", 900, "Зал"), _g("QF3", 800, "Спальня")]
    assert _phases([*near, _g("QF4", 100, "Кухня")])["QF4"] == "L1"  # 200 W above: stays


def test_lighting_takes_a_second_phase() -> None:
    light = [_g(f"QF{k}", 100, f"R{k}", Kind.LIGHT) for k in (1, 2)]
    phases = _phases([_g("QF9", 5000, "X"), *light])
    assert phases["QF1"] != phases["QF2"]


def test_units_share_a_phase_and_a_model_phase_is_kept() -> None:
    groups = [
        _g("QF1", 2000, "A", reserved=True),
        _g("QF2", 2000, "B", reserved=True),
        _g("QF3", 500, "C"),
        _g("QF4", 500, "D"),
    ]
    phases = _phases(groups, groups={"QF4": {"phase": "L3"}})
    assert phases["QF1"] == phases["QF2"]  # the backup bus has one phase
    assert phases["QF4"] == "L3"
    wet = [_g("QF1", 800, "A", rcd="30 мА"), _g("QF2", 800, "B", rcd="30 мА")]
    out = assign_phases(wet, Electrical.model_validate({"panel": {"phases": 3}}), "economy")
    assert out[0].phase == out[1].phase  # in economy under one shared RCD


def test_unbalance() -> None:
    assert unbalance({"L1": 0.0, "L2": 0.0, "L3": 0.0}) == 0
    assert unbalance({"L1": 1000.0, "L2": 800.0, "L3": 900.0}) == 0.2
