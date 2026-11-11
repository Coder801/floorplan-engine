"""Panel front view as data for the viewer (key `panel` of the "Panel" page, docs/epd-format.md):
enclosure from the catalogue, devices with their catalogue model and enclosure rail, groups
with load and colour, supply, totals, weak spots, inverter or generator plug. The frontend
draws it with its own component (web/src/engine/panel)."""

from __future__ import annotations

from collections.abc import Sequence

from floorplan_engine.electrical.groups import LIGHT
from floorplan_engine.electrical.loads import (
    Kind,
    PanelGroup,
    backup_share,
)
from floorplan_engine.electrical.panel import (
    BoardPanel,
    DcBox,
    Device,
    color_of,
    grid_text,
    panel_title,
    reserve_groups,
)
from floorplan_engine.electrical.panel_text import text
from floorplan_engine.model.schema import Electrical, PointType
from floorplan_engine.model.texts import Language
from floorplan_engine.sheets.stickers import stickers_data

# Backup device outside the panel; a charging station comes in through a plug, like a generator
EXTERNAL = {"inverter": "U1", "plug": "XP1", "station": "XP1"}


def panel_data(
    panel: BoardPanel, colors: dict[str, int], name: str, language: Language
) -> dict[str, object]:
    """Panel for the viewer (key `panel` of an .epd page): devices in order with their catalogue
    model, groups with load, totals and weak spots, in the project language. The viewer does the
    rail layout and the drawing."""
    groups = {}
    for g in panel.groups:
        groups[g.group] = {
            "purpose": g.purpose,
            "purpose_assumed": g.purpose_assumed,
            "cable": g.cable,
            "power": round(g.power),
            "current": round(g.current, 1),
            "assumed": g.assumed,
            "loads": len(g.loads),
            "color": f"#{c:06x}" if (c := color_of(g.group, colors)) is not None else None,
            "split_of": g.split_of,
            **({"phase": g.phase} if g.phase else {}),
        }
    devices = _devices(panel.devices, panel.rows)
    calc = panel.calculated
    out: dict[str, object] = {
        "name": name,
        "phases": panel.phases,
        **(
            {"phase_loads": {p: round(w) for p, w in panel.phase_loads.items()}}
            if panel.phases == 3
            else {}
        ),
        "scheme": panel.scheme,
        "input": {"label": panel.input.label, "assumed": panel.input.assumed},
        "enclosure": panel.enclosure.as_dict() if panel.enclosure is not None else None,
        "devices": devices,
        "groups": groups,
        "totals": {
            "installed": round(panel.installed),
            "demand": panel.demand,
            "calculated": round(calc),
            "current": round(panel.design_current, 1),
            "modules": panel.modules,
        },
        "warnings": [
            {
                "severity": w.severity,
                "text": w.text[language],
                **({"group": w.group} if w.group else {}),
            }
            for w in panel.warnings
        ],
        "texts": {
            "title": panel_title(panel, name, language),
            "grid": grid_text(panel, language),
            "reserve": text("reserve_bus", language),
            "master": text("master_bus", language),
        },
        "stickers": stickers_data(panel, colors),
    }
    if panel.dc is not None:
        out["dc"] = dc_data(panel.dc, language)
    if panel.backup is not None:
        switch = "KM1" if any(d.id == "KM1" for d in panel.devices) else "SA1"
        out["external"] = {
            "id": EXTERNAL[panel.backup],
            "kind": panel.backup,
            "title": text(panel.backup, language),
            # LOAD goes into the inverter output breaker, from there into input II of the ATS or
            # switch
            "to": "QS3" if any(d.id == "QS3" for d in panel.devices) else switch,
            "switch": switch,
            "feed": "QS2" if panel.backup == "inverter" else None,
        }
    return out


def _devices(
    devices: tuple[Device, ...], rows: tuple[tuple[Device, ...], ...]
) -> list[dict[str, object]]:
    """Devices in order with their catalogue model and enclosure rail."""
    row_of = {d.id: r for r, row in enumerate(rows) for d in row}
    out = []
    for d in devices:
        item: dict[str, object] = {
            "id": d.id,
            "key": d.key,
            "kind": d.kind.value,
            "label": d.label,
            "title": d.title,
            "model": d.model.as_dict(),
        }
        if d.id in row_of:
            item["row"] = row_of[d.id]
        if d.group is not None:
            item["group"] = d.group
        if d.feeds:
            item["feeds"] = list(d.feeds)
        if d.assumed:
            item["assumed"] = True
        if d.reserve:
            item["reserve"] = True
        if d.master:
            item["master"] = True
        if d.phase:
            item["phase"] = d.phase
        out.append(item)
    return out


def dc_data(dc: DcBox, language: Language) -> dict[str, object]:
    """Battery box for the inverter (key `panel.dc`): enclosure, devices, battery, solar strings."""
    return {
        "enclosure": dc.enclosure.as_dict(),
        "devices": _devices(dc.devices, dc.rows),
        "battery": {
            "voltage": dc.voltage,
            "voltage_assumed": dc.voltage_assumed,
            "capacity": dc.capacity,
            "power": dc.power,
            "power_assumed": dc.power_assumed,
            "current": round(dc.current, 1),
            "rating": dc.rating,
            "cable": dc.cable,
        },
        "pv_strings": dc.pv_strings,
        "texts": {
            "title": text("dc_title", language),
            "battery": text("battery", language),
            "kwh": text("kwh", language),
            "pv": text("pv_in", language),
        },
    }


HEAVY_OUTLETS_W = 1000.0  # an appliance outlet from this power is heavy for the backup bus


def _reserve_kind(lines: Sequence[PanelGroup], model: Electrical) -> str:
    """What a model group is for the quick picks of the backup bus: light (any lamp: the
    bathroom light with its fan is lighting), heavy (a heavy line, or appliance outlets only of
    HEAVY_OUTLETS_W and more: air conditioner, floor heating) or sockets."""
    by_id = {p.id: p for p in model.points}
    loads = [ld for g in lines for ld in g.loads]
    points = [by_id[ld.point] for ld in loads if ld.point in by_id]
    if any(p.type in LIGHT for p in points):
        return "light"
    outlets = bool(points) and all(p.type is PointType.OUTLET for p in points)
    if any(g.kind is Kind.HEAVY for g in lines) or (
        outlets and sum(ld.power for ld in loads) >= HEAVY_OUTLETS_W
    ):
        return Kind.HEAVY.value
    return Kind.SOCKETS.value


def master_data(panel: BoardPanel, model: Electrical) -> dict[str, object]:
    """What the master switch can cut (key `overview.panel.master`): groups of the model with
    their power and purpose; "on" — cut now, or by the rule while there is no master switch yet
    (the wizard shows the choice before the rebuild); "keep" — a load that stays on by the rule
    (loads.KEEP_ON). active — the panel has the master switch now."""
    active = panel.master

    def on(lines: Sequence[PanelGroup]) -> bool:
        if active:
            return any(g.master for g in lines)
        return not any(ld.keep_on for g in lines for ld in g.loads)

    return {
        "active": active,
        "items": [
            {
                "id": name,
                "purpose": "; ".join(dict.fromkeys(g.purpose for g in lines)),
                "power": round(sum(g.power for g in lines)),
                "kind": _reserve_kind(lines, model),
                "on": on(lines),
                "keep": any(ld.keep_on for g in lines for ld in g.loads),
            }
            for name, lines in reserve_groups(panel, model).items()
        ],
    }


def _peak_share(lines: Sequence[PanelGroup]) -> dict[str, int]:
    """Share of a group in the design peak of the backup bus (loads.backup_share): steady part and
    its largest occasional appliance; the viewer sums the steady parts and adds one appliance."""
    steady, peak = backup_share([ld for g in lines for ld in g.loads])
    return {"steady": round(steady), "peak": round(peak)}


def reserve_data(panel: BoardPanel, model: Electrical) -> dict[str, object] | None:
    """What can go on the backup bus (key `overview.panel.reserve`): groups of the model with
    their power and purpose, their share in the design peak (steady, peak: decision 2026-11-11)
    and the power of the source. None without a backup: there is no bus.
    A plug-in generator of unknown power gives limit_kw None."""
    if panel.backup is None:
        return None
    limit = panel.backup_power
    assumed = limit is None and panel.dc is not None
    if limit is None and panel.dc is not None:
        limit = panel.dc.power
    return {
        "limit_kw": limit,
        "limit_assumed": assumed,
        "items": [
            {
                "id": name,
                "purpose": "; ".join(dict.fromkeys(g.purpose for g in lines)),
                "power": round(sum(g.power for g in lines)),
                **_peak_share(lines),
                "kind": _reserve_kind(lines, model),
                "on": any(g.reserved for g in lines),
            }
            for name, lines in reserve_groups(panel, model).items()
        ],
    }
