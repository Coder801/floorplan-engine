"""Panel front view: panel set by scheme and backup, group devices, weak spots, DIN rows,
load list (out/panel-loads.csv).

Model calculation only, no drawing (drawing is in drawing/panel.py; for the viewer,
epd/panel_data.py). Loads and group breakers are in electrical/loads.py, stage questions in
electrical/panel_questions.py, labels in electrical/panel_text.py.

- Panel set by scheme (`panel.scheme`, decision 2026-10-27): economy has the main switch,
  voltage relay and groups, wet zones under one RCD; standard puts wet zones on RCBOs;
  premium adds a surge protector, all groups on RCBOs, curve B (curve C for motor loads).
  A voltage relay is in every scheme (decision 2026-11-01).
- Backup (`panel.backup`) is independent of the scheme: if unset, a hybrid inverter is
  assumed and a question is asked. The switch depends on the source: a hybrid inverter
  switches grid and battery itself, so a bypass switch; an inverter without its own switching
  (`inverter: basic`) gets an ATS; a generator gets a changeover switch; the inverter output
  has its own breaker (QS3). An N–PE link in backup mode (`npe_relay`) that is unset or absent
  is a weak spot: RCDs will not trip on backup. The backup bus carries lighting, fridge,
  router, boiler, pump, gates, kitchen sockets.
- Weak spots: a breaker larger than the cable can carry, a heavy load in a shared group,
  design current above the main breaker, no selectivity, backup smaller than the load.
- Battery box (`DcBox`) goes with a hybrid inverter as a separate box next to it: battery
  breaker by discharge current, breakers and DC surge protectors for solar strings
  (`panel.pv_strings`); without data, battery voltage is 48 V and inverter power 5 kW, as
  assumptions. Backup groups stay in the main panel, behind the ATS or switch.
- Three-phase supply (`panel.phases: 3`, decision 2026-11-08): main switch 3P+N, a voltage
  relay per phase (KV1–KV3: a lost phase cuts only its own groups), surge protector 3P+N;
  groups by phase (electrical/phases.py), a three-phase appliance on its 3P breaker (RCBO
  3P+N). The backup source has one phase: the backup bus, the inverter feed and output, the ATS
  or switch are on the phase of the backup bus. Weak spots by phase: a phase above the main
  breaker, a spread of the phases, a three-phase appliance listed for the backup bus.
- Master switch (`panel.master`, decision 2026-11-09; electrical/master.py): a contactor per
  bus (KM2 on the main one, KM3 behind the ATS or switch) with the groups it cuts after the
  ones it does not, a control breaker SF1 (on the backup bus if there is one, so the switch
  works on backup); contactor rating by the design current of its groups.
- LED supplies in the panel (`led_supply: board`, decision 2026-11-13; electrical/led_supply.py)
  stand in a box of their own under it (`LedBox`): a DIN supply per LED output by its strip
  power (strip not described — STRIP_DEFAULT_M, an assumption and a remark), fed by the
  breaker of the output's group; the 12 V line to the output is sized by the voltage drop.
- Enclosure is a real catalogue panel (`panel.enclosure`, or the smallest with 12-module
  rails that fits the devices; 18-module rails only when asked, decision 2026-11-13): rails by
  device kind (`panel_rows`), a device is never split between rails and never sticks out of
  the enclosure; if nothing fits, an on-site enclosure with 12-module rails and a remark.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import groupby
from pathlib import Path
from typing import Literal

from floorplan_engine.electrical.led_supply import STRIP_DEFAULT_M, LedLoad, led_loads
from floorplan_engine.electrical.loads import (
    CABLE_LIMITS,
    SOCKETS_A,
    Breaker,
    Kind,
    PanelGroup,
    backup_peak,
    current,
    demand_factor,
    panel_groups,
    phases_of,
    rating_for,
)
from floorplan_engine.electrical.master import CONTACTOR_A, CONTROL_A, CONTROL_ID
from floorplan_engine.electrical.panel_text import KIND_NAME, SHORT_NAME, amps, kw, text
from floorplan_engine.electrical.phases import (
    PHASES,
    UNBALANCE,
    assign_phases,
    phase_loads,
    unbalance,
)
from floorplan_engine.model.panel_catalog import (
    ENCLOSURE_BY_ARTICLE,
    ENCLOSURES,
    CatalogModel,
    DeviceKind,
    Enclosure,
    fitted_enclosure,
    led_psu_model,
    model_for,
)
from floorplan_engine.model.schema import (
    Electrical,
    ElectricalPoint,
    PanelScheme,
    Plan,
    PointType,
)
from floorplan_engine.model.texts import Language

INPUT_A = 63  # main breaker when the model has none (assumption, decision 2026-10-27)
RCD_A = 40  # RCD for wet zones in economy


@dataclass(frozen=True)
class Device:
    """Device on a DIN rail."""

    id: str  # QS1, KV1, FV1, QD1, SA1, KM1, QF4
    kind: DeviceKind
    label: str  # what is printed on the device: "C16", "40 А 30 мА"
    title: str  # what it is
    group: str | None = None  # panel group of a breaker or RCBO
    feeds: tuple[str, ...] = ()  # groups behind the RCD
    assumed: bool = False
    reserve: bool = False  # on the backup bus
    brand: str = "generic"  # panel brand: the model comes from the catalogue (panel_catalog)
    poles: int = 0  # three-phase variant: 4 — 3P+N, 3 — 3P; 0 — the usual one of the kind
    phase: str | None = None  # L1, L2, L3 or 3P on a three-phase panel
    master: bool = False  # a group cut by the master switch (behind its contactor)
    watts: int = 0  # LED supply rating, W
    point: str | None = None  # LED supply: the output it feeds

    @property
    def model(self) -> CatalogModel:
        if self.kind is DeviceKind.LED_PSU:
            return led_psu_model(self.watts)
        return model_for(self.kind, self.brand, self.poles)

    @property
    def modules(self) -> int:
        return self.model.modules

    @property
    def key(self) -> str:
        """Drawing object: a group is "device:QF4", everything else "device:QS1"."""
        return f"device:{self.group or self.id}"


@dataclass(frozen=True)
class Warning:
    severity: str  # major | minor
    text: dict[str, str]  # by language: ru for the report, the project language for the sheet
    group: str | None = None


LinePurpose = Literal["light", "socket", "device", "low"]


@dataclass(frozen=True)
class LineClass:
    """What a line is on the wiring sheet: purpose and whether it is under an RCBO or an RCD."""

    purpose: LinePurpose
    rcd: bool


OTHER_LINE = LineClass("socket", False)  # a group the panel does not know


@dataclass(frozen=True)
class BoardPanel:
    """The whole panel: groups, devices in order, totals and weak spots."""

    scheme: PanelScheme
    backup: str | None  # inverter | plug | station; None means no backup
    backup_assumed: bool  # backup not set: an inverter is assumed
    groups: tuple[PanelGroup, ...]
    devices: tuple[Device, ...]
    input: Breaker
    installed: float  # W
    demand: float  # demand factor
    warnings: tuple[Warning, ...]
    power_limit: float | None  # allocated power, kW
    backup_power: float | None
    enclosure: Enclosure | None = None  # panel enclosure; None until chosen
    rows: tuple[tuple[Device, ...], ...] = ()  # devices by enclosure rail, top to bottom
    dc: DcBox | None = None  # battery box for the inverter; None without an inverter
    led: LedBox | None = None  # LED supplies box under the panel; None with supplies at the strip
    phases: int = 1  # 1 — 230 V, 3 — 400 V
    phases_assumed: bool = True  # not set in the model

    @property
    def calculated(self) -> float:
        return self.installed * self.demand

    @property
    def phase_loads(self) -> dict[str, float]:
        """Installed power by phase, W; empty on a single-phase panel."""
        return phase_loads(self.groups) if self.phases == 3 else {}

    @property
    def design_current(self) -> float:
        """Design current against the main breaker: of the flat, on three phases of the most
        loaded phase."""
        loads = self.phase_loads
        top = max(loads.values()) if loads else self.installed
        return current(top * self.demand)

    @property
    def modules(self) -> int:
        return sum(d.modules for d in self.devices)

    @property
    def reserve_power(self) -> float:
        """Installed power of the backup bus, W."""
        return sum(g.power for g in self.groups if g.reserved)

    @property
    def reserve_peak(self) -> float:
        """Design peak of the backup bus, W (loads.backup_peak): checked against the source."""
        return backup_peak([ld for g in self.groups if g.reserved for ld in g.loads])

    @property
    def master(self) -> bool:
        """The panel has a master switch: a group behind its contactor."""
        return any(g.master for g in self.groups)

    @property
    def all_devices(self) -> tuple[Device, ...]:
        """Devices of the panel, the battery box and the LED box, for the device table and the
        estimate."""
        dc = self.dc.devices if self.dc is not None else ()
        return self.devices + dc + (self.led.devices if self.led is not None else ())


INVERTER_KW = 5.0  # inverter power without data (assumption)
BATTERY_V = 48  # battery voltage without data (assumption)
DC_RATINGS = (63, 80, 100, 125, 160, 200, 250)  # battery DC breaker series, A
# Copper single-core battery cable by breaker (short, up to 3 m), mm²
BATTERY_CABLE = {63: 16, 80: 25, 100: 25, 125: 35, 160: 50, 200: 70, 250: 95}
PV_A = 16  # solar string breaker, A DC


@dataclass(frozen=True)
class DcBox:
    """Battery box for a hybrid inverter: battery, battery breaker, solar strings."""

    devices: tuple[Device, ...]
    enclosure: Enclosure
    rows: tuple[tuple[Device, ...], ...]
    voltage: int  # V
    voltage_assumed: bool
    capacity: float | None  # kWh
    power: float  # inverter power, kW
    power_assumed: bool
    current: float  # battery discharge current at full power, A
    rating: int  # battery breaker, A
    cable: float  # battery cable cross-section, mm²
    pv_strings: int


def build_dc(elec: Electrical, lang: Language) -> DcBox:
    """Battery box: discharge current is inverter power over battery voltage; the breaker is the
    nearest in the series with a 10 % margin, the cable follows the breaker; each solar string
    gets a breaker and a surge protector."""
    setup = elec.panel
    voltage = setup.battery_voltage or BATTERY_V
    power = setup.backup_power or INVERTER_KW
    amps_ = power * 1000 / voltage
    rating = next((r for r in DC_RATINGS if r >= amps_ * 1.1), DC_RATINGS[-1])
    devices = [Device("QB1", DeviceKind.DC_BATTERY, f"{rating} А DC 2P", text("dc_battery", lang))]
    strings = setup.pv_strings or 0
    for k in range(1, strings + 1):
        devices.append(
            Device(f"QP{k}", DeviceKind.DC_BREAKER, f"{PV_A} А DC 2P", text("dc_pv", lang, n=k))
        )
        devices.append(Device(f"FP{k}", DeviceKind.DC_SPD, "PV 1000 В", text("dc_spd", lang, n=k)))
    devices = [replace(d, brand=setup.brand) for d in devices]
    enclosure, rows, _ = choose_enclosure(devices)
    return DcBox(
        tuple(devices),
        enclosure,
        tuple(tuple(r) for r in rows),
        voltage,
        setup.battery_voltage is None,
        setup.battery_capacity,
        power,
        setup.backup_power is None,
        amps_,
        rating,
        BATTERY_CABLE[rating],
        strings,
    )


@dataclass(frozen=True)
class LedBox:
    """LED supplies in a box of their own under the panel (led_supply "board", decision
    2026-11-13): a supply per LED output, fed by the breaker of the output's group."""

    devices: tuple[Device, ...]
    enclosure: Enclosure
    rows: tuple[tuple[Device, ...], ...]
    loads: tuple[LedLoad, ...]  # in device order


def build_led_box(plan: Plan, elec: Electrical) -> LedBox | None:
    """LED box: supplies G1, G2… in model order of the outputs, titled by what they light
    (led_title); None without outputs fed from the panel."""
    loads = led_loads(elec)
    if not loads:
        return None
    lang = plan.language
    rooms = {r.id: r.name for r in plan.rooms}
    points = {p.id: p for p in elec.points}
    devices = [
        Device(
            f"G{k}",
            DeviceKind.LED_PSU,
            f"{ld.supply} Вт 12 В",
            led_title(points[ld.point], rooms.get(ld.room, ld.room), lang),
            assumed=ld.power_assumed,
            brand=elec.panel.brand,
            watts=ld.supply,
            point=ld.point,
        )
        for k, ld in enumerate(loads, 1)
    ]
    enclosure, rows, _ = choose_enclosure(devices)
    return LedBox(tuple(devices), enclosure, tuple(tuple(r) for r in rows), tuple(loads))


def led_title(point: ElectricalPoint, room: str, lang: Language) -> str:
    """LED supply line, like a group purpose: what it lights — room ("Подсветка шкафа —
    Спальня"); what comes from the output note, without one "Подсветка LED"."""
    note = (point.note or "").strip()
    what = note[:1].upper() + note[1:] if note else text("led_what", lang)
    return text("led_psu", lang, what=what, room=room)


def _led_spots(led: LedBox) -> list[Warning]:
    """LED box weak spots: strips the model does not describe (STRIP_DEFAULT_M assumed) and a
    strip above the largest supply."""
    out: list[Warning] = []
    guessed = [ld.point for ld in led.loads if ld.metres_assumed and ld.power_assumed]
    if guessed:
        m = f"{STRIP_DEFAULT_M:g}"
        out.append(Warning("minor", _both("w_led_strip", p=", ".join(guessed), m=m)))
    for ld in led.loads:
        if ld.oversize:
            warn = _both("w_led_big", p=ld.point, w=f"{ld.power:g}", s=ld.supply)
            out.append(Warning("major", warn, ld.group))
    return out


MODE_SCHEME: dict[str, PanelScheme] = {
    "economy": "economy",
    "standard": "standard",
    "proper": "premium",
}


def scheme_of(elec: Electrical) -> PanelScheme:
    if elec.panel.scheme is not None:
        return elec.panel.scheme
    return MODE_SCHEME[elec.mode]


def backup_of(elec: Electrical) -> tuple[str | None, bool]:
    """Backup and whether it is an assumption: unset means a hybrid inverter (decision
    2026-10-27).
    """
    b = elec.panel.backup
    if b is None:
        return "inverter", True
    return (None if b == "none" else b), False


def _group_devices(
    groups: Sequence[PanelGroup], scheme: PanelScheme, reserve: bool, lang: Language, rcds: int
) -> list[Device]:
    """Group devices of one bus: in economy wet groups go under a shared RCD at the end; in proper
    lighting gets breakers and everything else RCBOs. A three-phase group gets a 3P breaker or a
    3P+N RCBO, never under the shared RCD."""
    out: list[Device] = []
    under_rcd: list[PanelGroup] = []
    for g in groups:
        if scheme == "economy" and g.rcd is not None and not g.three_phase:
            under_rcd.append(g)
            continue
        kind = DeviceKind.DIFF if g.rcd is not None else DeviceKind.BREAKER
        label = g.breaker.label + (f" {g.rcd}" if g.rcd else "")
        poles = (4 if g.rcd is not None else 3) if g.three_phase else 0
        label += f" {poles}P" if poles else ""
        out.append(
            Device(
                g.group,
                kind,
                label,
                g.purpose,
                g.group,
                (),
                g.breaker.assumed,
                reserve,
                poles=poles,
                phase=g.phase,
            )
        )
    if under_rcd:
        name = f"QD{rcds + 1}"
        rating = max(RCD_A, max(g.breaker.rating for g in under_rcd))
        rcd_label = f"{rating_for(rating, RCD_A)} А 30 мА"
        title = text("rcd_wet", lang)
        feeds = tuple(g.group for g in under_rcd)
        phase = under_rcd[0].phase  # one unit on a three-phase panel (phases.py)
        out.append(
            Device(name, DeviceKind.RCD, rcd_label, title, None, feeds, True, reserve, phase=phase)
        )
        for g in under_rcd:
            out.append(
                Device(
                    g.group,
                    DeviceKind.BREAKER,
                    g.breaker.label,
                    g.purpose,
                    g.group,
                    (),
                    g.breaker.assumed,
                    reserve,
                    phase=g.phase,
                )
            )
    return out


def _bus_devices(
    groups: Sequence[PanelGroup], scheme: PanelScheme, reserve: bool, lang: Language, rcds: int
) -> list[Device]:
    """Group devices of one bus: the groups the master switch leaves on, then those behind its
    contactor (each part with its own shared RCD in economy: an RCD is never split by a
    contactor)."""
    kept = _group_devices([g for g in groups if not g.master], scheme, reserve, lang, rcds)
    rcds += sum(1 for d in kept if d.kind is DeviceKind.RCD)
    cut = _group_devices([g for g in groups if g.master], scheme, reserve, lang, rcds)
    return kept + [replace(d, master=True) for d in cut]


def contactor_current(
    groups: Sequence[PanelGroup], demand: float, three: bool, limit: float
) -> float:
    """Design current through a master switch contactor: of its groups with the demand factor
    of the flat; on three phases, of the most loaded phase; at most limit, the main breaker."""
    loads = phase_loads(groups) if three else {}
    top = max(loads.values()) if loads else sum(g.power for g in groups)
    return min(current(top * demand), limit)


def _master_devices(
    groups: Sequence[PanelGroup],
    demand: float,
    three: bool,
    backup: bool,
    limit: float,
    lang: Language,
) -> list[Device]:
    """Contactors of the master switch: KM2 on the main bus, KM3 on the backup bus, each only if
    it has groups to cut; a three-phase main one is 4P."""
    out: list[Device] = []
    for reserve, name in ((False, "KM2"), (True, "KM3")):
        cut = [g for g in groups if g.master and g.reserved is reserve]
        if not cut:
            continue
        amps_ = contactor_current(cut, demand, three and not reserve, limit)
        rating = next((r for r in CONTACTOR_A if r >= amps_), CONTACTOR_A[-1])
        poles = 4 if three and not reserve else 0
        key = "master_contactor_reserve" if reserve and backup else "master_contactor"
        out.append(
            Device(
                name,
                DeviceKind.CONTACTOR,
                f"{rating} А {poles or 2}P",
                text(key, lang),
                feeds=tuple(g.group for g in cut),
                reserve=reserve,
                poles=poles,
                phase="3P" if poles else None,
                master=True,
            )
        )
    return out


def build_panel(plan: Plan, elec: Electrical) -> BoardPanel | None:
    """Panel from the model; None if there are no groups."""
    lang = plan.language
    setup = elec.panel
    scheme = scheme_of(elec)
    backup, backup_assumed = backup_of(elec)
    phases = phases_of(elec)
    groups = panel_groups(plan, elec, scheme, backup is not None)
    if not groups:
        return None
    if phases == 3:
        groups = assign_phases(groups, elec, scheme)
    installed = sum(g.power for g in groups)
    demand = demand_factor(installed / 1000)
    inp = Breaker("C", setup.input or INPUT_A, setup.input is None)
    # Voltage relay in every scheme (decision 2026-11-01): protects both the flat and the
    # inverter input from a lost neutral
    relay = setup.voltage_relay if setup.voltage_relay is not None else True
    spd = setup.spd if setup.spd is not None else scheme == "premium"
    # ATS only for an inverter without its own switching; a hybrid one switches grid and
    # battery itself, so it gets a bypass switch; a plug-in generator is started by hand: a
    # changeover switch
    ats = setup.ats if setup.ats is not None else backup == "inverter" and setup.inverter == "basic"

    three = phases == 3
    poles = 4 if three else 0
    title = text("input", lang)
    devices = [Device("QS1", DeviceKind.INPUT, f"{inp.label} {poles or 2}P", title, poles=poles)]
    if relay:  # on three phases a relay per phase: a lost phase cuts only its own groups
        label = f"{inp.rating} А"
        for k, ph in enumerate(PHASES if three else (None,), 1):
            title = text("relay", lang) + (f" {ph}" if ph else "")
            devices.append(Device(f"KV{k}", DeviceKind.RELAY, label, title, phase=ph))
    if spd:
        label = "T2 20 кА" + (" 4P" if three else "")
        devices.append(Device("FV1", DeviceKind.SPD, label, text("spd", lang), poles=poles))
    main = [g for g in groups if not g.reserved]
    reserved = [g for g in groups if g.reserved]
    master = any(g.master for g in groups)
    demand = demand_factor(sum(g.power for g in groups) / 1000)
    contactors = _master_devices(groups, demand, three, backup is not None, inp.rating, lang)
    # The main bus contactor after the shared devices; the backup one heads the backup bus
    devices += [d for d in contactors if not d.reserve]
    # The control circuit is on the backup bus if there is one: the switch works on backup too
    control = Device(
        CONTROL_ID,
        DeviceKind.BREAKER,
        f"B{CONTROL_A}",
        text("master_control", lang),
        reserve=backup is not None,
    )
    if master and backup is None:
        devices.append(control)
    devices += _bus_devices(main, scheme, False, lang, 0)
    if backup is not None:
        if backup == "inverter":
            devices.append(
                Device("QS2", DeviceKind.FEED, f"C{SOCKETS_A * 2} 2P", text("inverter_feed", lang))
            )
        if ats:
            devices.append(Device("KM1", DeviceKind.ATS, "АВР", text("ats", lang), reserve=True))
        else:
            key = "bypass" if backup == "inverter" else "changeover"
            devices.append(
                Device("SA1", DeviceKind.CHANGEOVER, "I-0-II", text(key, lang), reserve=True)
            )
        if backup == "inverter":  # inverter output has its own breaker before the ATS or switch
            devices.append(
                Device("QS3", DeviceKind.OUTPUT, f"C{SOCKETS_A * 2} 2P", text("inverter_out", lang))
            )
        rcds = sum(1 for d in devices if d.kind is DeviceKind.RCD)
        if master:
            devices.append(control)
        devices += [d for d in contactors if d.reserve]
        devices += _bus_devices(reserved, scheme, True, lang, rcds)
        if three:  # the backup source has one phase: its devices are on the backup bus phase
            phase = next((g.phase for g in reserved), PHASES[0])
            backup_ids = {"QS2", "KM1", "SA1", "QS3", "KM3", CONTROL_ID}
            devices = [replace(d, phase=phase) if d.id in backup_ids else d for d in devices]

    devices = [replace(d, brand=setup.brand) for d in devices]
    panel = BoardPanel(
        scheme,
        backup,
        backup_assumed,
        tuple(groups),
        tuple(devices),
        inp,
        installed,
        demand,
        (),
        setup.power,
        setup.backup_power,
        phases=phases,
        phases_assumed=setup.phases is None,
    )
    enclosure, rows, fit_note = choose_enclosure(panel.devices, setup.enclosure)
    dc = build_dc(elec, lang) if backup == "inverter" else None
    led = build_led_box(plan, elec)
    panel = replace(panel, enclosure=enclosure, rows=tuple(tuple(r) for r in rows), dc=dc, led=led)
    warnings = weak_spots(panel, relay, setup.npe_relay)
    if three:
        # A three-phase appliance listed for the backup bus: the backup source has one phase
        for g in groups:
            if g.three_phase and (g.split_of or g.group) in setup.reserve:
                warnings.append(Warning("major", _both("w_reserve_3p", g=g.group), g.group))
    warnings += _master_spots(panel, elec)
    if led is not None:
        warnings += _led_spots(led)
    if fit_note is not None:
        warnings.append(fit_note)
    return replace(panel, warnings=tuple(warnings))


def _master_spots(panel: BoardPanel, elec: Electrical) -> list[Warning]:
    """Master switch weak spots: a contactor below the design current of its groups; by the rule
    (no master_off), a group the switch leaves on for one load while it feeds others too."""
    out: list[Warning] = []
    if not panel.master:
        return out
    for d in panel.devices:
        if d.kind is DeviceKind.CONTACTOR:
            cut = [g for g in panel.groups if g.group in d.feeds]
            amps_ = contactor_current(cut, panel.demand, d.poles == 4, panel.input.rating)
            if amps_ > CONTACTOR_A[-1]:
                r = CONTACTOR_A[-1]
                out.append(Warning("major", _both("w_master_overload", i=amps(amps_), r=r)))
    if elec.panel.master_off:
        return out
    for g in panel.groups:
        keep = [ld for ld in g.loads if ld.keep_on]
        if not g.master and keep and len(g.loads) > len(keep):
            what = ", ".join(dict.fromkeys(ld.title for ld in keep))
            out.append(Warning("minor", _both("w_master_mixed", g=g.group, what=what), g.group))
    return out


# Shared devices go in this order on their rail; then the breaker rails (and RCDs), below
# them the RCBO rails (double busbar L + N)
COMMON_KINDS = (
    DeviceKind.INPUT,
    DeviceKind.RELAY,
    DeviceKind.SPD,
    DeviceKind.CHANGEOVER,
    DeviceKind.ATS,
    DeviceKind.OUTPUT,
    DeviceKind.FEED,
    DeviceKind.CONTACTOR,
)


def row_kind(d: Device) -> str:
    """Device rail: common for shared devices, double for RCBOs, single for the rest."""
    if d.kind in COMMON_KINDS:
        return "common"
    return "double" if d.kind is DeviceKind.DIFF else "single"


def panel_rows(devices: Sequence[Device], per_row: int) -> list[list[Device]] | None:
    """Devices by enclosure rail: shared, breakers, RCBOs, each kind from its own rail, in order
    within a kind (main first, then backup); a device is never split between rails.
    None if a device is wider than a rail."""
    rows: list[list[Device]] = []
    for kind in ("common", "single", "double"):
        devs = [d for d in devices if row_kind(d) == kind]
        if kind == "common":
            devs.sort(key=lambda d: COMMON_KINDS.index(d.kind))
        used = per_row + 1
        for d in devs:
            if d.modules > per_row:
                return None
            if used + d.modules > per_row:
                rows.append([])
                used = 0
            rows[-1].append(d)
            used += d.modules
    return rows


BUSBAR_MODULES = 54  # a comb busbar is bought as a 1 m bar and cut on site


def busbar_runs(panel: BoardPanel) -> list[tuple[int, int]]:
    """Comb busbar pieces of the group rails as (poles, modules): they join the devices from
    above instead of wire jumpers. A piece is a run of neighbours on one rail fed together: main
    and backup apart, the groups behind the master switch contactor apart, the breakers under a
    shared RCD on a piece of their own (fed from its output). Breaker rails take a phase comb,
    RCBO rails a double one (L + N); on a three-phase panel the main bus takes all three phases,
    the backup bus and a shared RCD stay on one. A lone device is wired, not combed; shared
    devices (input, relay, ATS…) are joined by jumpers."""
    under = {g: d.id for d in panel.devices if d.kind is DeviceKind.RCD for g in d.feeds}

    def fed(d: Device) -> tuple[bool, bool, str | None]:
        rcd = under.get(d.group or "") if d.kind is DeviceKind.BREAKER else None
        return d.reserve, d.master, rcd

    out: list[tuple[int, int]] = []
    for row in panel.rows:
        if not row or row_kind(row[0]) == "common":
            continue
        double = row_kind(row[0]) == "double"
        for (reserve, _, rcd), run in groupby(row, key=fed):
            devices = list(run)
            if len(devices) < 2:
                continue
            three = panel.phases == 3 and not reserve and rcd is None
            poles = (3 if three else 1) + (1 if double else 0)
            out.append((poles, sum(d.modules for d in devices)))
    return out


def busbars(panel: BoardPanel) -> dict[int, int]:
    """1 m comb busbars to buy, by poles: the pieces (busbar_runs) are cut from as few bars as
    they fit in, longest first; an offcut goes to the next piece."""
    out: dict[int, int] = {}
    for poles in sorted({p for p, _ in busbar_runs(panel)}):
        left: list[int] = []  # modules left in each bar
        for modules in sorted((m for p, m in busbar_runs(panel) if p == poles), reverse=True):
            while modules > 0:  # a piece longer than a bar takes whole bars first
                k = next(
                    (k for k, free in enumerate(left) if free >= min(modules, BUSBAR_MODULES)), None
                )
                if k is None:
                    left.append(BUSBAR_MODULES)
                    k = len(left) - 1
                cut = min(modules, left[k])
                left[k] -= cut
                modules -= cut
        out[poles] = len(left)
    return out


def choose_enclosure(
    devices: Sequence[Device], article: str | None = None
) -> tuple[Enclosure, list[list[Device]], Warning | None]:
    """Enclosure and devices by its rails. If an article is given and the devices fit, use it;
    otherwise the smallest catalogue panel with 12-module rails they fit in (fewer modules, then
    lower; an 18-module one only when asked), with a remark if the given one did not fit; if
    nothing fits, an on-site enclosure with 12-module rails and a remark."""
    asked = ENCLOSURE_BY_ARTICLE.get(article) if article else None
    # Chosen by itself: rails of at most 12 modules (the narrowest catalogue ones); a wider
    # panel only when it is asked for (panel.enclosure)
    narrow = min(e.per_row for e in ENCLOSURES)
    fits = [e for e in ENCLOSURES if e.per_row == narrow]
    order = sorted(fits, key=lambda e: (e.modules, e.height))
    if asked is not None:
        order.insert(0, asked)
    for enc in order:
        rows = panel_rows(devices, enc.per_row)
        if rows is not None and len(rows) <= enc.rows:
            note = None
            if asked is not None and enc is not asked:
                note = Warning("major", _both("w_enclosure", a=asked.article, b=enc.article))
            return enc, rows, note
    # On-site enclosure: rails of 12 modules too, more rails instead of wider ones; wider only
    # for a device that does not fit such a rail
    per_row = max(narrow, *(d.modules for d in devices))
    rows = panel_rows(devices, per_row) or [list(devices)]
    total = sum(d.modules for d in devices)
    note = Warning("major", _both("w_enclosure_none", m=total))
    return fitted_enclosure(len(rows), per_row), rows, note


def _both(key: str, **kw_: object) -> dict[str, str]:
    return {lang: text(key, lang, **kw_) for lang in ("ru", "uk")}


def _purpose(group: PanelGroup, points: dict[str, ElectricalPoint]) -> LinePurpose:
    """Light, an appliance (heavy, only outputs, or one named point: "холодильник") or sockets."""
    if group.kind is Kind.LIGHT:
        return "light"
    powered = [points[ld.point] for ld in group.loads if ld.point in points]
    named = len(powered) == 1 and bool(powered[0].note)
    outputs = bool(powered) and all(p.type is PointType.OUTLET for p in powered)
    return "device" if group.kind is Kind.HEAVY or named or outputs else "socket"


def line_classes(plan: Plan, elec: Electrical) -> dict[str, LineClass]:
    """What each group is, for the cable layers: by the panel, so RCDs follow the scheme."""
    panel = build_panel(plan, elec)
    points = {p.id: p for p in elec.points}
    groups = panel.groups if panel is not None else ()
    return {g.group: LineClass(_purpose(g, points), g.rcd is not None) for g in groups}


def weak_spots(panel: BoardPanel, relay: bool, npe: bool | None = True) -> list[Warning]:
    """Panel weak spots: by group first, then supply and backup."""
    out: list[Warning] = []
    for g in panel.groups:
        b = g.breaker
        if g.split_of is not None and g.group == g.split_of:
            msg = _both(
                "w_split", g=g.group, n=sum(1 for x in panel.groups if x.split_of == g.group)
            )
            out.append(Warning("major", msg, g.group))
        if g.current > b.rating and len(g.loads) == 1:
            ld, i = g.loads[0], amps(g.current)
            need = rating_for(g.current)
            msg = _both("w_single", g=g.group, what=ld.title, i=i, r=b.rating, need=need)
            out.append(Warning("major", msg, g.group))
        elif g.current > b.rating:
            msg = _both("w_overload", g=g.group, i=amps(g.current), r=b.rating)
            out.append(Warning("major", msg, g.group))
        if g.section is None:
            out.append(Warning("minor", _both("w_no_cable", g=g.group), g.group))
        elif g.section in CABLE_LIMITS:
            rec, top = CABLE_LIMITS[g.section]
            c = g.cable
            if b.rating > top:
                out.append(
                    Warning("major", _both("w_cable", g=g.group, r=b.rating, c=c, m=top), g.group)
                )
            elif b.rating > rec:
                out.append(
                    Warning(
                        "minor", _both("w_cable_soft", g=g.group, r=b.rating, c=c, m=rec), g.group
                    )
                )
        heavy = [ld for ld in g.loads if ld.heavy]
        if heavy and len(g.loads) > 1:
            for ld in heavy:
                out.append(
                    Warning(
                        "major",
                        _both("w_heavy_shared", g=g.group, what=ld.title, p=kw(ld.power)),
                        g.group,
                    )
                )
        if b.rating >= panel.input.rating:
            out.append(
                Warning(
                    "major", _both("w_select", g=g.group, r=b.rating, i=panel.input.rating), g.group
                )
            )
    calc_a = panel.design_current
    loads = panel.phase_loads
    if loads and calc_a > panel.input.rating:
        worst = max(PHASES, key=lambda p: (loads[p], p))
        msg = _both("w_total_phase", p=worst, i=amps(calc_a), r=panel.input.rating)
        out.append(Warning("major", msg))
    elif calc_a > panel.input.rating:
        out.append(Warning("major", _both("w_total", i=amps(calc_a), r=panel.input.rating)))
    if loads and unbalance(loads) > UNBALANCE:
        spread = " · ".join(f"{p} {kw(loads[p])}" for p in PHASES)
        msg = _both("w_unbalance", s=spread, k=round(unbalance(loads) * 100))
        out.append(Warning("minor", msg))
    if panel.power_limit is not None and panel.calculated / 1000 > panel.power_limit:
        out.append(
            Warning("major", _both("w_power", p=kw(panel.calculated), lim=f"{panel.power_limit:g}"))
        )
    if panel.input.assumed:
        out.append(Warning("minor", _both("w_input_assumed", r=panel.input.rating)))
    if not relay:
        out.append(Warning("minor", _both("w_no_relay")))
    if panel.backup is not None:
        res = panel.reserve_peak
        if panel.backup_power is None:
            out.append(Warning("minor", _both("w_backup_unknown", p=kw(res))))
        elif res / 1000 > panel.backup_power:
            out.append(
                Warning("major", _both("w_backup", p=kw(res), lim=f"{panel.backup_power:g}"))
            )
        if panel.backup in ("plug", "station"):
            out.append(Warning("minor", _both(f"w_{panel.backup}")))
    if panel.backup == "inverter" and not npe:
        out.append(Warning("major", _both("w_npe_unknown" if npe is None else "w_npe_no")))
    if panel.dc is not None and panel.dc.voltage_assumed:
        dc = panel.dc
        out.append(Warning("minor", _both("w_battery", v=dc.voltage, a=amps(dc.current))))
    return out


def reserve_groups(panel: BoardPanel, model: Electrical) -> dict[str, list[PanelGroup]]:
    """Groups of the model with their panel lines (QF1 → QF1, QF1.2; QF8 → QF8, QF8.2), in panel
    order: panel.reserve holds model groups, which do not change with the wiring variant, and a
    group goes on the backup bus with all its lines (lines.split_by_lines)."""
    names = {p.group for p in model.points if p.group} | {c.group for c in model.cables if c.group}
    out: dict[str, list[PanelGroup]] = {}
    for g in panel.groups:
        name = g.group
        while name not in names and "." in name:
            name = name.rsplit(".", 1)[0]
        out.setdefault(name, []).append(g)
    return out


def device_name(d: Device, language: Language, short: bool = False) -> str:
    """Device for purchase: "Автомат 1P C16", "Вводной автомат, C63 2P"; the same in the estimate
    and in the purchase device table. Short, for the panel device table: "АВ 1P C16"."""
    names = SHORT_NAME if short else KIND_NAME
    kind = names.get((d.kind, d.poles)) or names.get(d.kind)
    if kind is None:
        return f"{d.title}, {d.label}"
    return f"{kind[language]} {d.label.removesuffix(f' {d.poles}P')}"


def ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def row_modules(devices: Sequence[Device]) -> int:
    """Modules per rail: 12 if four rails are enough, otherwise 18 or 24."""
    total = sum(d.modules for d in devices)
    return next((n for n in (12, 18, 24) if ceil_div(total, n) <= 4), 24)


def din_rows(devices: Sequence[Device], per_row: int | None = None) -> list[list[Device]]:
    """Devices on DIN rails in order; a device is never split between rails, the backup bus starts
    on a new rail."""
    if per_row is None:
        per_row = row_modules(devices)
    rows: list[list[Device]] = [[]]
    used = 0
    reserve = False
    for d in devices:
        fresh = d.reserve and not reserve  # backup bus starts on its own rail
        reserve = reserve or d.reserve
        if (used + d.modules > per_row or fresh) and rows[-1]:
            rows.append([])
            used = 0
        rows[-1].append(d)
        used += d.modules
    return rows


def write_loads(panel: BoardPanel, path: Path) -> Path:
    """Load list as CSV: group, device, point, room, load, power and where it comes from (source
    from the model, typical as an assumption)."""
    devices = {d.group: d for d in panel.devices if d.group}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "group",
                "device",
                "cable",
                "point",
                "room",
                "consumer",
                "count",
                "watts",
                "power_from",
            ]
        )
        for g in panel.groups:
            label = devices[g.group].label if g.group in devices else g.breaker.label
            for ld in g.loads:
                w.writerow(
                    [
                        g.group,
                        label,
                        g.cable,
                        ld.point,
                        ld.room,
                        ld.title,
                        ld.count,
                        f"{ld.power:g}",
                        "typical" if ld.assumed else "source",
                    ]
                )
    return path


def scheme_title(panel: BoardPanel, language: Language) -> str:
    """Scheme label such as "автомат на кожну лінію, резерв: інвертор*": scheme and backup, "*"
    marks an assumption."""
    out = text(panel.scheme, language)
    if panel.backup is not None:
        out += ", " + text(f"with_{panel.backup}", language) + ("*" if panel.backup_assumed else "")
    return out


def panel_title(panel: BoardPanel, name: str, language: Language) -> str:
    """Panel title such as "Щит ЩР: 3 фазы, 400 В — автомат на каждую линию": supply and scheme."""
    supply = text(f"supply_{panel.phases}", language)
    return text("title", language, name=name, supply=supply, scheme=scheme_title(panel, language))


def grid_text(panel: BoardPanel, language: Language) -> str:
    """The supply label at the input: "Ввод от сети 400 В"."""
    return text("grid", language, v=400 if panel.phases == 3 else 230)


def color_of(group: str | None, colors: dict[str, int]) -> int | None:
    """Group colour; a line of a split group (QF8.2) uses the colour of the group (QF8)."""
    if group is None:
        return None
    return colors.get(group, colors.get(group.split(".")[0]))


# --- Panel questions ------------------------------------------------------------
