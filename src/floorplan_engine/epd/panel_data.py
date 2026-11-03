"""Panel front view as data for the viewer (key `panel` of the "Panel" page, docs/epd-format.md):
enclosure from the catalogue, devices with their catalogue model and enclosure rail, groups
with load and colour, supply, totals, weak spots, inverter or generator plug. The frontend
draws it with its own component (web/src/engine/panel)."""

from __future__ import annotations

from floorplan_engine.electrical.loads import (
    current,
)
from floorplan_engine.electrical.panel import (
    BoardPanel,
    DcBox,
    Device,
    color_of,
    scheme_title,
)
from floorplan_engine.electrical.panel_text import text
from floorplan_engine.model.texts import Language

EXTERNAL = {"inverter": "U1", "plug": "XP1"}  # backup device outside the panel


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
        }
    devices = _devices(panel.devices, panel.rows)
    calc = panel.calculated
    out: dict[str, object] = {
        "name": name,
        "phases": 1,
        "scheme": panel.scheme,
        "input": {"label": panel.input.label, "assumed": panel.input.assumed},
        "enclosure": panel.enclosure.as_dict() if panel.enclosure is not None else None,
        "devices": devices,
        "groups": groups,
        "totals": {
            "installed": round(panel.installed),
            "demand": panel.demand,
            "calculated": round(calc),
            "current": round(current(calc), 1),
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
            "title": text("title", language, name=name, scheme=scheme_title(panel, language)),
            "grid": text("grid", language),
            "reserve": text("reserve_bus", language),
        },
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
