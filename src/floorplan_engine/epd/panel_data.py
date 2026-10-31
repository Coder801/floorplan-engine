"""Щит в лицо данными для просмотра (ключ `panel` страницы «Щит», docs/epd-format.md):
аппараты с моделью каталога, группы с нагрузкой и цветом, ввод, итоги, слабые места,
инвертор или вилка генератора. Рисует его своим компонентом фронт (web/src/engine/panel)."""

from __future__ import annotations

from floorplan_engine.electrical.loads import (
    current,
)
from floorplan_engine.electrical.panel import (
    BoardPanel,
    color_of,
    scheme_title,
)
from floorplan_engine.electrical.panel_text import text
from floorplan_engine.model.texts import Language

EXTERNAL = {"inverter": "U1", "plug": "XP1"}  # аппарат резерва вне щита


def panel_data(
    panel: BoardPanel, colors: dict[str, int], name: str, language: Language
) -> dict[str, object]:
    """Щит для просмотра (ключ `panel` страницы .epd): аппараты по порядку с моделью
    из каталога, группы с нагрузкой, итоги и слабые места — на языке проекта. Раскладку
    по рейкам и рисунок делает просмотр."""
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
    devices = []
    for d in panel.devices:
        item: dict[str, object] = {
            "id": d.id,
            "key": d.key,
            "kind": d.kind.value,
            "label": d.label,
            "title": d.title,
            "model": d.model.as_dict(),
        }
        if d.group is not None:
            item["group"] = d.group
        if d.feeds:
            item["feeds"] = list(d.feeds)
        if d.assumed:
            item["assumed"] = True
        if d.reserve:
            item["reserve"] = True
        devices.append(item)
    calc = panel.calculated
    out: dict[str, object] = {
        "name": name,
        "phases": 1,
        "scheme": panel.scheme,
        "input": {"label": panel.input.label, "assumed": panel.input.assumed},
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
    if panel.backup is not None:
        out["external"] = {
            "id": EXTERNAL[panel.backup],
            "kind": panel.backup,
            "title": text(panel.backup, language),
            "to": "KM1" if any(d.id == "KM1" for d in panel.devices) else "SA1",
            "feed": "QS2" if panel.backup == "inverter" else None,
        }
    return out
