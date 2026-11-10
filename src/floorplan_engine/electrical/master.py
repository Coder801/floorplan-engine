"""Master switch (decision 2026-11-09): one key by the entrance cuts the flat when nobody is home.

- What it is: an ordinary one-key switch (a bistable one) at the entrance and a modular
  contactor in the panel (`DeviceKind.CONTACTOR`, normally open). The switch feeds the coil
  through its own control breaker (SF1, B6); key off — the coil drops out and the groups behind
  the contactor are cut. Chosen by `panel.master`; unset — a question, and the assumption is
  "yes" if the source has a master switch point, otherwise "no" (master_on).
- What it cuts (`panel.master_off`, model groups; empty — the rule, an assumption): everything
  except what must keep working with nobody home — fridge and freezer, boiler, router, pump,
  gates, intercom, alarm, video surveillance, recuperator (loads.KEEP_ON, by the point note).
  A group with any such load stays on as a whole; if it has other points too, a weak spot.
- Backup bus: its groups get a contactor of their own (KM3) behind the ATS or switch, driven by
  the same key; the control circuit is then fed from the backup bus, so the master switch works
  on backup too. Main bus — KM2.
- Contactor rating — the series CONTACTOR_A by the design current of the groups it cuts (demand
  factor of the flat; on three phases, of the most loaded phase), at most the main breaker: it
  never lets more through; above the series, a weak spot.
- Where the switch is: a switch point with "мастер" / "майстер" in its note (from the source).
  Without one the code puts it next to the panel on its wall at HEIGHT (an assumption and a
  question, panel_master_place). It is a control device, not a light switch: no guessed link to
  lights (lighting.switch_links), and its control cable (CONTROL_MARK) runs from the panel as a
  line of its own whatever group the source gave it (wiring.py); it counts in the estimate.
"""

from __future__ import annotations

import re

from floorplan_engine.model.schema import (
    SWITCH_TYPES,
    Electrical,
    ElectricalPoint,
    Plan,
    PointType,
)

CONTROL_ID = "SF1"  # control circuit breaker; also the "group" of the control cable run
CONTROL_A = 6  # control circuit breaker, A (curve B)
CONTACTOR_A = (25, 40, 63)  # modular contactor series, A (AC-1)
CONTROL_MARK = "3x1.5"  # control cable: feed, switched line, PE
POINT_ID = "MS1"  # the switch the code puts in when the model has none
HEIGHT = 900.0  # switch height, mm
GAP = 150.0  # from the panel edge to the switch box edge, mm
BOX_W = 80.0  # switch frame width, mm
MASTER_NOTE = re.compile(r"мастер|майстер", re.IGNORECASE)
NOTE = {"ru": "мастер-выключатель", "uk": "майстер-вимикач"}


def is_master(p: ElectricalPoint) -> bool:
    return p.type in SWITCH_TYPES and bool(p.note) and bool(MASTER_NOTE.search(p.note or ""))


def master_on(elec: Electrical) -> bool:
    """The flat has a master switch: panel.master, or, unset, a master switch point in the
    source."""
    if elec.panel.master is not None:
        return elec.panel.master
    return any(is_master(p) for p in elec.points)


def master_point(elec: Electrical) -> ElectricalPoint | None:
    """The master switch point of the model; None without the master switch or its point."""
    if not master_on(elec):
        return None
    return next((p for p in elec.points if is_master(p)), None)


def placed_by_code(elec: Electrical) -> bool:
    """The master switch is on, and its place is the code's assumption."""
    p = master_point(elec)
    return p is not None and p.id == POINT_ID and (p.note or "").endswith("*")


def with_master_switch(plan: Plan, elec: Electrical) -> Electrical:
    """The model with the master switch point: with `panel.master: true` and no such point, one is
    put on the panel wall next to it, on the side the wall has room for, at HEIGHT (its note ends
    with "*": an assumption). Unchanged without the master switch, the panel or its wall."""
    if not master_on(elec) or elec.board is None:
        return elec
    if any(is_master(p) for p in elec.points) or any(p.id == POINT_ID for p in elec.points):
        return elec
    b = elec.board
    room = next((r for r in plan.rooms if r.id == b.room), None)
    wall = next((w for w in room.walls if w.id == b.wall), None) if room is not None else None
    if wall is None:
        return elec
    side = b.width / 2 + GAP + BOX_W / 2
    offset = b.offset + side
    if offset + BOX_W / 2 > wall.length:
        offset = max(b.offset - side, BOX_W / 2)
    point = ElectricalPoint(
        id=POINT_ID,
        room=b.room,
        type=PointType.SWITCH,
        wall=b.wall,
        offset=round(offset),
        height=HEIGHT,
        note=NOTE[plan.language] + "*",
    )
    return elec.model_copy(update={"points": [*elec.points, point]})
