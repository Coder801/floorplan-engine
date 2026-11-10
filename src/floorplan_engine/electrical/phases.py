"""Groups by phase on a three-phase panel (decision 2026-11-08): the phases carry about the same
load, and best practice is kept where the load allows it.

- A three-phase appliance (loads.is_three_phase: a cooktop, an electric boiler) is on all three
  phases (3P); its power is shared equally.
- A phase from the model (`groups.<QF>.phase`) is kept; the code places the rest.
- What has to share a phase goes as one unit: the backup bus (the backup source has one phase)
  and, in economy, the groups under the shared RCD of wet zones (a single-phase RCD).
- Units go largest first, each on the least loaded phase; a unit whose room is already on a
  phase goes there if that phase is no more than ROOM_SLACK_W above the least loaded one: one
  room on one phase, no 400 V between neighbouring devices. Lighting takes at least two phases,
  so one phase lost does not leave the whole flat dark.
- Balance is checked on the panel (panel.weak_spots): a phase above the main breaker, a spread
  above UNBALANCE.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from floorplan_engine.electrical.loads import Kind, PanelGroup
from floorplan_engine.model.schema import Electrical, PanelScheme

PHASES = ("L1", "L2", "L3")
ROOM_SLACK_W = 1000.0  # a room keeps its phase while it is this much above the least loaded one
UNBALANCE = 0.15  # spread of the phases, (max − min) / max, from which it is a weak spot


@dataclass
class _Unit:
    """Groups that take one phase together."""

    groups: list[int]  # indexes in the group list
    power: float
    rooms: set[str]
    light: bool  # lighting only
    fixed: str | None  # phase from the model


def phase_loads(groups: Sequence[PanelGroup]) -> dict[str, float]:
    """Power by phase, W; a three-phase group adds a third to each."""
    out = dict.fromkeys(PHASES, 0.0)
    for g in groups:
        if g.three_phase:
            for p in PHASES:
                out[p] += g.power / 3
        elif g.phase in out:
            out[g.phase] += g.power
    return out


def unbalance(loads: dict[str, float]) -> float:
    """Spread of the phases: (max − min) / max; 0 without load."""
    top = max(loads.values())
    return (top - min(loads.values())) / top if top > 0 else 0.0


def _units(groups: Sequence[PanelGroup], elec: Electrical, scheme: PanelScheme) -> list[_Unit]:
    """Single-phase groups as units: the backup bus is one, in economy the wet groups under the
    shared RCD are one; a phase from the model fixes its unit (the first one found wins)."""
    keys: dict[str, int] = {}
    units: list[_Unit] = []
    for k, g in enumerate(groups):
        if g.three_phase:
            continue
        info = elec.groups.get(g.group.split(".")[0])
        fixed = info.phase if info is not None and info.phase in PHASES else None
        if g.reserved:
            key = "reserve"
        elif scheme == "economy" and g.rcd is not None:
            key = "rcd"
        else:
            key = g.group
        if key not in keys:
            keys[key] = len(units)
            units.append(_Unit([], 0.0, set(), True, None))
        u = units[keys[key]]
        u.groups.append(k)
        u.power += g.power
        u.rooms |= {ld.room for ld in g.loads}
        u.light = u.light and g.kind is Kind.LIGHT
        u.fixed = u.fixed or fixed
    return units


def assign_phases(
    groups: Sequence[PanelGroup], elec: Electrical, scheme: PanelScheme
) -> list[PanelGroup]:
    """Each group with its phase: L1, L2, L3 or 3P (see the module). Deterministic: ties go to
    the lower phase."""
    load = phase_loads([g for g in groups if g.three_phase])
    rooms: dict[str, set[str]] = {p: set() for p in PHASES}
    light: set[str] = set()
    phase_of: dict[int, str] = {}
    units = _units(groups, elec, scheme)
    lights = sum(1 for u in units if u.light)

    def put(u: _Unit, p: str) -> None:
        load[p] += u.power
        rooms[p] |= u.rooms
        if u.light:
            light.add(p)
        for k in u.groups:
            phase_of[k] = p

    for u in units:
        if u.fixed is not None:
            put(u, u.fixed)
    for u in sorted((u for u in units if u.fixed is None), key=lambda u: -u.power):
        options = list(PHASES)
        if u.light and lights > 1 and len(light) == 1:
            options.remove(next(iter(light)))  # lighting on a second phase
        least = min(load[p] for p in options)
        near = [p for p in options if rooms[p] & u.rooms and load[p] - least <= ROOM_SLACK_W]
        put(u, min(near or options, key=lambda p: (load[p], p)))
    return [g if g.three_phase else replace(g, phase=phase_of.get(k)) for k, g in enumerate(groups)]
