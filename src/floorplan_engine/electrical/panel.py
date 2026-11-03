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
- Enclosure is a real catalogue panel (`panel.enclosure`, or the smallest that fits the
  devices): rails by device kind (`panel_rows`), a device is never split between rails and
  never sticks out of the enclosure; if nothing fits, an on-site enclosure and a remark.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from floorplan_engine.electrical.loads import (
    CABLE_LIMITS,
    SOCKETS_A,
    Breaker,
    PanelGroup,
    current,
    demand_factor,
    panel_groups,
    rating_for,
)
from floorplan_engine.electrical.panel_text import KIND_NAME, amps, kw, text
from floorplan_engine.model.panel_catalog import (
    ENCLOSURE_BY_ARTICLE,
    ENCLOSURES,
    CatalogModel,
    DeviceKind,
    Enclosure,
    fitted_enclosure,
    model_for,
)
from floorplan_engine.model.schema import Electrical, PanelScheme, Plan
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

    @property
    def model(self) -> CatalogModel:
        return model_for(self.kind, self.brand)

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


@dataclass(frozen=True)
class BoardPanel:
    """The whole panel: groups, devices in order, totals and weak spots."""

    scheme: PanelScheme
    backup: str | None  # inverter | plug; None means no backup
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

    @property
    def calculated(self) -> float:
        return self.installed * self.demand

    @property
    def modules(self) -> int:
        return sum(d.modules for d in self.devices)

    @property
    def reserve_power(self) -> float:
        return sum(g.power for g in self.groups if g.reserved)

    @property
    def all_devices(self) -> tuple[Device, ...]:
        """Devices of the panel and the battery box, for the device table and the estimate."""
        return self.devices + (self.dc.devices if self.dc is not None else ())


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
    lighting gets breakers and everything else RCBOs."""
    out: list[Device] = []
    under_rcd: list[PanelGroup] = []
    for g in groups:
        if scheme == "economy" and g.rcd is not None:
            under_rcd.append(g)
            continue
        kind = DeviceKind.DIFF if g.rcd is not None else DeviceKind.BREAKER
        label = g.breaker.label + (f" {g.rcd}" if g.rcd else "")
        out.append(Device(g.group, kind, label, g.purpose, g.group, (), g.breaker.assumed, reserve))
    if under_rcd:
        name = f"QD{rcds + 1}"
        rating = max(RCD_A, max(g.breaker.rating for g in under_rcd))
        rcd_label = f"{rating_for(rating, RCD_A)} А 30 мА"
        title = text("rcd_wet", lang)
        feeds = tuple(g.group for g in under_rcd)
        out.append(Device(name, DeviceKind.RCD, rcd_label, title, None, feeds, True, reserve))
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
                )
            )
    return out


def build_panel(plan: Plan, elec: Electrical) -> BoardPanel | None:
    """Panel from the model; None if there are no groups."""
    lang = plan.language
    setup = elec.panel
    scheme = scheme_of(elec)
    backup, backup_assumed = backup_of(elec)
    groups = panel_groups(plan, elec, scheme, backup is not None)
    if not groups:
        return None
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

    devices = [Device("QS1", DeviceKind.INPUT, f"{inp.label} 2P", text("input", lang))]
    if relay:
        label = f"{inp.rating} А"
        devices.append(Device("KV1", DeviceKind.RELAY, label, text("relay", lang)))
    if spd:
        devices.append(Device("FV1", DeviceKind.SPD, "T2 20 кА", text("spd", lang)))
    main = [g for g in groups if not g.reserved]
    reserved = [g for g in groups if g.reserved]
    devices += _group_devices(main, scheme, False, lang, 0)
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
        devices += _group_devices(reserved, scheme, True, lang, rcds)

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
    )
    enclosure, rows, fit_note = choose_enclosure(panel.devices, setup.enclosure)
    dc = build_dc(elec, lang) if backup == "inverter" else None
    panel = replace(panel, enclosure=enclosure, rows=tuple(tuple(r) for r in rows), dc=dc)
    warnings = weak_spots(panel, relay, setup.npe_relay)
    if fit_note is not None:
        warnings.append(fit_note)
    return replace(panel, warnings=tuple(warnings))


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


def choose_enclosure(
    devices: Sequence[Device], article: str | None = None
) -> tuple[Enclosure, list[list[Device]], Warning | None]:
    """Enclosure and devices by its rails. If an article is given and the devices fit, use it;
    otherwise the smallest catalogue panel they fit in (fewer modules, then lower), with a
    remark if the given one did not fit; if nothing fits, an on-site enclosure and a remark."""
    asked = ENCLOSURE_BY_ARTICLE.get(article) if article else None
    order = sorted(ENCLOSURES, key=lambda e: (e.modules, e.height))
    if asked is not None:
        order.insert(0, asked)
    for enc in order:
        rows = panel_rows(devices, enc.per_row)
        if rows is not None and len(rows) <= enc.rows:
            note = None
            if asked is not None and enc is not asked:
                note = Warning("major", _both("w_enclosure", a=asked.article, b=enc.article))
            return enc, rows, note
    per_row = max(24, *(d.modules for d in devices))
    rows = panel_rows(devices, per_row) or [list(devices)]
    total = sum(d.modules for d in devices)
    note = Warning("major", _both("w_enclosure_none", m=total))
    return fitted_enclosure(len(rows), per_row), rows, note


def _both(key: str, **kw_: object) -> dict[str, str]:
    return {lang: text(key, lang, **kw_) for lang in ("ru", "uk")}


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
    calc_a = current(panel.calculated)
    if calc_a > panel.input.rating:
        out.append(Warning("major", _both("w_total", i=amps(calc_a), r=panel.input.rating)))
    if panel.power_limit is not None and panel.calculated / 1000 > panel.power_limit:
        out.append(
            Warning("major", _both("w_power", p=kw(panel.calculated), lim=f"{panel.power_limit:g}"))
        )
    if panel.input.assumed:
        out.append(Warning("minor", _both("w_input_assumed", r=panel.input.rating)))
    if not relay:
        out.append(Warning("minor", _both("w_no_relay")))
    if panel.backup is not None:
        res = panel.reserve_power
        if panel.backup_power is None:
            out.append(Warning("minor", _both("w_backup_unknown", p=kw(res))))
        elif res / 1000 > panel.backup_power:
            out.append(
                Warning("major", _both("w_backup", p=kw(res), lim=f"{panel.backup_power:g}"))
            )
        if panel.backup == "plug":
            out.append(Warning("minor", _both("w_plug")))
    if panel.backup == "inverter" and not npe:
        out.append(Warning("major", _both("w_npe_unknown" if npe is None else "w_npe_no")))
    if panel.dc is not None and panel.dc.voltage_assumed:
        dc = panel.dc
        out.append(Warning("minor", _both("w_battery", v=dc.voltage, a=amps(dc.current))))
    return out


def device_name(d: Device, language: Language) -> str:
    """Device for purchase: "Автомат 1P C16", "Вводной автомат, C63 2P"; the same in the estimate
    and in the purchase device table."""
    kind = KIND_NAME.get(d.kind)
    return f"{kind[language]} {d.label}" if kind is not None else f"{d.title}, {d.label}"


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
    """Scheme label such as "преміум, резерв: інвертор*": scheme and backup, "*" marks an
    assumption."""
    out = text(panel.scheme, language)
    if panel.backup is not None:
        out += ", " + text(f"with_{panel.backup}", language) + ("*" if panel.backup_assumed else "")
    return out


def color_of(group: str | None, colors: dict[str, int]) -> int | None:
    """Group colour; a line of a split group (QF8.2) uses the colour of the group (QF8)."""
    if group is None:
        return None
    return colors.get(group, colors.get(group.split(".")[0]))


# --- Panel questions ------------------------------------------------------------
