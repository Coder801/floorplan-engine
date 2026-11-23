"""Tests of electrical/low_links.py: internet and TV without a group, their topology from the
cables of the project."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from floorplan_engine.electrical.routing import length as length_of
from floorplan_engine.electrical.wiring_context import END_ALLOWANCE
from floorplan_engine.electrical.wiring_model import line_starts
from floorplan_engine.model.schema import Electrical
from tests.conftest import make_flat, make_plan
from tests.electrical.conftest import (
    DOOR,
    RECT,
    base_elec,
    wall_point,
    wiring_of,
)


def test_low_voltage_without_group_from_media_cabinet() -> None:
    """Internet and TV without a group: a line of their own each, from the low-voltage cabinet
    if there is one, with the assumed cable by type; a grouped socket is unaffected."""
    base = base_elec().model_dump(by_alias=True)
    base["points"].append(wall_point("t1", "tv", "w2", 1000, 300, None))
    base["media"] = {"room": "r", "wall": "w2", "offset": 2500, "height": 1500}
    w = wiring_of(make_plan(RECT, [DOOR]), Electrical.model_validate(base))
    low = {r.target: r for r in w.runs if r.circuit == "low"}
    assert set(low) == {"d1", "t1"}
    assert {r.source for r in low.values()} == {"media"}
    assert (low["d1"].mark, low["t1"].mark) == ("UTP cat.6", "RG-6")
    assert all(r.mark_assumed and r.group == "Связь" for r in low.values())
    assert low["d1"].ends_mm == END_ALLOWANCE + 1500  # cabinet tail like the panel's
    assert any(c.kind == "media" and c.circuit == "low" for c in w.chases)
    assert next(r for r in w.runs if r.target == "s1").source == "board"
    assert w.skipped == ()


def _low_flat(cables: list[dict[str, Any]], **extra: Any) -> Any:
    """Bathroom and kitchen (make_flat), the panel in the bathroom; internet d1 in the bathroom,
    d2, d3 and a TV t2 in the kitchen, all without a group; a socket of QF1 in each room."""

    def wall(pid: str, room: str, kind: str, wall: str, offset: float) -> dict[str, Any]:
        return {
            "id": pid,
            "room": room,
            "type": kind,
            "wall": wall,
            "offset": offset,
            "height": 300,
        }

    elec = Electrical.model_validate(
        {
            "points": [
                wall("s1", "bath", "socket", "w1", 500) | {"group": "QF1"},
                wall("s2", "kitchen", "socket", "w3", 1000) | {"group": "QF1"},
                wall("d1", "bath", "data", "w1", 1500),
                wall("d2", "kitchen", "data", "w3", 2000),
                wall("t2", "kitchen", "tv", "w2", 1500),
                wall("d3", "kitchen", "data", "w4", 1000),
            ],
            "board": {"room": "bath", "wall": "w4", "offset": 1000, "height": 1700},
            "cables": [{"cable": "UTP cat.6"} | c for c in cables],
            **extra,
        }
    )
    return wiring_of(make_flat(), elec)


LAN = [
    {"id": "lan_1", "from": "board", "to": ["d1"]},
    {"id": "lan_2", "from": "d1", "to": ["d2", "t2"]},
]


def test_low_voltage_topology_from_cables_without_group() -> None:
    """Decision 2026-11-17: one UTP from the panel to d1, from there a line of its own to d2 and
    to the TV in the next room; d3, in no cable, keeps a line of its own from the panel."""
    w = _low_flat(LAN)
    low = {r.target: r for r in w.runs if r.circuit == "low"}
    assert {t: r.source for t, r in low.items()} == {
        "d1": "board",
        "d2": "d1",
        "t2": "d1",
        "d3": "board",
    }
    for t in ("d1", "d2", "t2"):
        assert (low[t].mark, low[t].mark_assumed, low[t].group) == ("UTP cat.6", False, "Связь")
    assert (low["d3"].mark, low["d3"].mark_assumed) == ("UTP cat.6", True)
    # From a point: up its wall to the ceiling and through the opening into the kitchen
    d2 = low["d2"]
    assert d2.rise_start_mm == pytest.approx(2700 - 300) and d2.ends_mm == 2 * END_ALLOWANCE
    assert d2.path[0] == low["d1"].path[-1]
    assert d2.path[-1].x > 2100 and d2.plan_mm == pytest.approx(length_of(d2.path))
    # At d1 the cable comes in and two go out: one low-voltage chase of three cables
    at_d1 = next(c for c in w.chases if c.targets == ("d1",))
    assert (at_d1.cables, at_d1.circuit) == (3, "low")
    assert line_starts(w.runs)["t2"] == "d1"
    assert {h.circuit for h in w.holes if "wire_4" in h.runs} == {"low"}


def test_low_voltage_topology_from_the_cabinet_and_own_route() -> None:
    """From the cabinet: the chain's head is d1, not the cabinet (one line in the viewer); a route
    set on the cable wins over the shared one."""
    media = {"room": "bath", "wall": "w2", "offset": 1000, "height": 1500}
    cables = [LAN[0] | {"from": "media"}, LAN[1] | {"route": "floor"}]
    w = _low_flat(cables, media=media)
    low = {r.target: r for r in w.runs if r.circuit == "low"}
    assert (low["d1"].source, low["d3"].source) == ("media", "media")
    assert low["d1"].route == "ceiling" and low["d2"].route == low["t2"].route == "floor"
    assert low["d2"].rise_start_mm == 300  # down to the floor from d1
    starts = line_starts(w.runs)
    assert (starts["d2"], starts["d3"]) == ("d1", "d3")


def test_low_feeds_skip_what_the_check_reports() -> None:
    """A point fed twice keeps its first source, a ring and a power source are not used: the build
    stays finite, the check reports them (validation.electrical)."""
    twice = [*LAN, {"id": "lan_3", "from": "board", "to": ["d2"]}]
    ring = [{"id": "r1", "from": "d2", "to": ["d1"]}, *LAN]
    power = [{"id": "p1", "from": "s1", "to": ["d3"]}]
    for cables, d1, d2, d3 in (
        (twice, "board", "d1", "board"),
        (ring, "d2", "board", "board"),
        (power, "board", "board", "board"),
    ):
        low = {r.target: r.source for r in _low_flat(cables).runs if r.circuit == "low"}
        assert (low["d1"], low["d2"], low["d3"]) == (d1, d2, d3)


def test_low_voltage_topology_builds_every_sheet(tmp_path: Path) -> None:
    """End to end: a project with a low-voltage chain builds without errors; the viewer gets the
    lines from the point (wiring scene, ceilings) and the estimate the cable of the project."""
    from floorplan_engine.pipeline import build_project

    plan = make_flat().model_dump(mode="json", by_alias=True, exclude_none=True)
    (tmp_path / "room.yaml").write_text(yaml.safe_dump(plan, allow_unicode=True), "utf-8")
    elec = {
        "points": [
            {"id": "s1", "room": "bath", "type": "socket", "wall": "w1", "offset": 500,
             "height": 300, "group": "QF1"},
            {"id": "d1", "room": "bath", "type": "data", "wall": "w1", "offset": 1500,
             "height": 300},
            {"id": "d2", "room": "kitchen", "type": "data", "wall": "w3", "offset": 2000,
             "height": 300},
        ],
        "board": {"room": "bath", "wall": "w4", "offset": 1000, "height": 1700},
        "media": {"room": "bath", "wall": "w2", "offset": 1000, "height": 1500},
        "cables": [
            {"id": "lan_1", "from": "media", "to": ["d1"], "cable": "UTP cat.6"},
            {"id": "lan_2", "from": "d1", "to": ["d2"], "cable": "UTP cat.6"},
        ],
    }  # fmt: skip
    (tmp_path / "electrical.yaml").write_text(yaml.safe_dump(elec, allow_unicode=True), "utf-8")
    result = build_project(tmp_path)
    assert not [i for i in result.assessment.report.issues if i.severity.value == "error"]
    with zipfile.ZipFile(tmp_path / "out" / "project.epd") as zf:
        pages = [json.loads(zf.read(n)) for n in zf.namelist() if n.startswith("pages/")]
    wires = [w for p in pages if "scene" in p for w in p["scene"]["wires"].values()]
    assert {(w["from"], w["to"]) for w in wires if w["group"] == "Связь"} == {
        ("media", "d1"),
        ("d1", "d2"),
    }
    lines = [ln for p in pages for c in p.get("ceilings", []) for ln in c["lines"]]
    assert ("d1", "d2") in {(ln["source"], ln["target"]) for ln in lines}
    assert "UTP cat.6" in (tmp_path / "out" / "estimate.md").read_text("utf-8")
