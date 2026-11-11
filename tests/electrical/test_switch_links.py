"""Which switch turns on what (switch_links.py): from controls, or assumed by group, room and
switch label."""

from __future__ import annotations

from floorplan_engine.electrical.switch_links import switch_links
from floorplan_engine.model.schema import Electrical
from floorplan_engine.validation.issues import parse_model

SW = {"room": "r", "wall": "w1", "height": 900, "group": "QF1"}
CEIL = {"room": "r", "type": "downlight", "group": "QF1"}


def _elec(points: list[dict[str, object]]) -> Electrical:
    elec, issues = parse_model(Electrical, {"points": points}, "e.yaml")
    assert elec is not None, issues
    return elec


def _links(elec: Electrical) -> dict[str, tuple[tuple[str, ...], bool]]:
    return {lk.switch: (lk.targets, lk.assumed) for lk in switch_links(elec)}


def test_controls_from_source_win() -> None:
    elec = _elec(
        [
            {"id": "s1", "type": "switch", "offset": 500, "controls": ["l2"], **SW},
            {"id": "l1", "ceiling": [1000, 1000], **CEIL},
            {"id": "l2", "ceiling": [2000, 1000], **CEIL},
        ]
    )
    assert _links(elec) == {"s1": (("l2",), False)}


def test_note_hints_and_rest() -> None:
    elec = _elec(
        [
            {"id": "s_bra", "type": "switch", "offset": 500, "note": "бра", **SW},
            {"id": "s_main", "type": "switch", "offset": 800, **SW},
            {"id": "s_led", "type": "switch", "offset": 1100, "note": "підсвітка кухні", **SW},
            {"id": "sc", "type": "sconce", "room": "r", "wall": "w2", "offset": 900,
             "height": 1500, "group": "QF1"},
            {"id": "l1", "ceiling": [1000, 1000], **CEIL},
            {"id": "led", "type": "led_output", "room": "r", "wall": "w3", "offset": 500,
             "height": 2200, "group": "QF1", "note": "підсвітка кухні"},
            # A light of another group is not linked
            {"id": "other", "ceiling": [2000, 2000], "room": "r", "type": "downlight",
             "group": "QF2"},
        ]
    )  # fmt: skip
    links = _links(elec)
    assert links["s_bra"] == (("sc",), True)
    assert links["s_led"] == (("led",), True)
    assert links["s_main"] == (("l1",), True)  # whatever the hinted ones did not take


def test_no_group_no_link() -> None:
    sw = {k: v for k, v in SW.items() if k != "group"}
    elec = _elec(
        [
            {"id": "s1", "type": "switch", "offset": 500, **sw},
            {"id": "l1", "ceiling": [1000, 1000], **CEIL},
        ]
    )
    assert switch_links(elec) == []  # no link is invented
