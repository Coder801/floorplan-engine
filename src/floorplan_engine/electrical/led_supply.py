"""LED supplies in the panel (Electrical.led_supply "board", decision 2026-11-13): what each LED
output needs and how its 12 V line is sized. Model only, no drawing.

- An LED output feeds the strips of its room (`led_strips`): a strip on the same wall as an
  output goes to the nearest output on that wall, the rest to the first output of the room.
  An output with no strip in the model gets STRIP_DEFAULT_M metres (assumption: the designer
  did not describe the strip).
- Strip power: the output `power` if the source gives it, otherwise metres × STRIP_W_PER_M
  (a 12 V strip, assumption). The supply is the smallest of LED_PSU_MODULES loaded to at most
  1 / PSU_MARGIN; a strip above the largest supply gets the largest one and a remark.
- The supplies stand in a box of their own under the main panel (panel.LedBox); each is fed
  by the breaker of its output's group, as before.
- The 12 V line from the box to the output is low voltage over a long run, so its cross-section
  goes by the voltage drop: the smallest of SECTIONS with a drop within DROP_MAX at the strip
  current; if even the largest is not enough, the largest and a remark (24 V strip or a supply
  at the strip).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from floorplan_engine.electrical.wiring_model import Wiring
from floorplan_engine.model.panel_catalog import LED_PSU_MODULES
from floorplan_engine.model.schema import Electrical, ElectricalPoint, LedStrip, PointType

STRIP_DEFAULT_M = 5.0  # strip at an output not described in the model, m (assumption)
STRIP_W_PER_M = 14.4  # 12 V strip power, W/m (assumption: 5050, 60 LEDs per metre)
LED_V = 12.0  # strip and supply output voltage, V
PSU_MARGIN = 1.25  # a supply is loaded to at most 80 %
PSU_SERIES = tuple(sorted(LED_PSU_MODULES))  # W
SECTIONS = (1.5, 2.5, 4.0, 6.0)  # copper two-core 12 V line, mm²
DROP_MAX = 0.05  # voltage drop on the 12 V line, share of LED_V
RHO = 0.0175  # copper resistivity, Ω·mm²/m


@dataclass(frozen=True)
class LedLoad:
    """An LED output fed from a supply in the panel: its strips and the supply it needs."""

    point: str
    room: str
    group: str
    strips: tuple[str, ...]  # strip ids from the model; empty — STRIP_DEFAULT_M assumed
    metres: float
    metres_assumed: bool
    power: float  # W
    power_assumed: bool  # by metres, not from the source
    supply: int  # supply rating, W
    oversize: bool  # the strip needs more than the largest supply

    @property
    def current(self) -> float:
        """Strip current at LED_V, A."""
        return self.power / LED_V


@dataclass(frozen=True)
class LedLine:
    """12 V line from the LED box to an output: length, cross-section, voltage drop."""

    point: str
    length_mm: float
    section: float  # mm²
    drop: float  # share of LED_V
    mark: str

    @property
    def ok(self) -> bool:
        return self.drop <= DROP_MAX + 1e-9


def led_outputs(elec: Electrical) -> list[ElectricalPoint]:
    """LED outputs fed from supplies in the panel: only with led_supply "board", a panel and a
    group (a point without a group gets no line)."""
    if elec.led_supply != "board" or elec.board is None:
        return []
    return [p for p in elec.points if p.type is PointType.LED_OUTPUT and p.group]


def strip_owners(elec: Electrical, outputs: Sequence[ElectricalPoint]) -> dict[str, list[LedStrip]]:
    """Strips by output: on the output's wall, to the nearest output there; the rest of the room,
    to its first output. A room without an output keeps its strips to itself."""
    out: dict[str, list[LedStrip]] = {p.id: [] for p in outputs}
    for s in elec.led_strips:
        room = [p for p in outputs if p.room == s.room]
        if not room:
            continue
        same = [p for p in room if p.wall == s.wall and p.offset is not None]
        near = min(same, key=lambda p: _gap(p.offset or 0.0, s.start, s.end)) if same else None
        owner = near or room[0]
        out[owner.id].append(s)
    return out


def _gap(at: float, start: float, end: float) -> float:
    """From a point on the wall to a strip part, mm: 0 inside it."""
    return max(start - at, at - end, 0.0)


def supply_for(power: float) -> tuple[int, bool]:
    """Supply rating for a strip of this power and whether it is above the largest one."""
    need = power * PSU_MARGIN
    for w in PSU_SERIES:
        if w >= need - 1e-9:
            return w, False
    return PSU_SERIES[-1], True


def led_loads(elec: Electrical) -> list[LedLoad]:
    """What each LED output fed from the panel needs, in model order."""
    outputs = led_outputs(elec)
    owners = strip_owners(elec, outputs)
    out: list[LedLoad] = []
    for p in outputs:
        strips = owners[p.id]
        metres = sum(s.end - s.start for s in strips) / 1000 if strips else STRIP_DEFAULT_M
        power = p.power if p.power is not None else metres * STRIP_W_PER_M
        supply, oversize = supply_for(power)
        assert p.group is not None
        out.append(
            LedLoad(
                p.id,
                p.room,
                p.group,
                tuple(s.id for s in strips),
                round(metres, 2),
                not strips,
                round(power, 1),
                p.power is None,
                supply,
                oversize,
            )
        )
    return out


def drop(length_mm: float, current: float, section: float) -> float:
    """Voltage drop on a two-core line there and back, share of LED_V."""
    return 2 * length_mm / 1000 * current * RHO / section / LED_V


def section_for(length_mm: float, current: float) -> float:
    """The smallest cross-section with the drop within DROP_MAX; the largest if none is."""
    for s in SECTIONS:
        if drop(length_mm, current, s) <= DROP_MAX + 1e-9:
            return s
    return SECTIONS[-1]


def led_mark(section: float) -> str:
    """Cable type of a 12 V line: "2x2.5"."""
    return f"2x{section:g}"


def led_lines(wiring: Wiring | None, loads: Sequence[LedLoad]) -> dict[str, LedLine]:
    """12 V lines by output, from the wiring (its LED runs, sized by wiring.box_wiring); empty
    without wiring."""
    if wiring is None:
        return {}
    by_point = {ld.point: ld for ld in loads}
    out: dict[str, LedLine] = {}
    for r in wiring.runs:
        ld = by_point.get(r.target)
        if not r.led or ld is None:
            continue
        section = section_for(r.length_mm, ld.current)
        out[ld.point] = LedLine(
            ld.point, r.length_mm, section, drop(r.length_mm, ld.current, section), r.mark
        )
    return out
