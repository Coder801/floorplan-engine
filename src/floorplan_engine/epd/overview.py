"""Общие сведения о проекте для первой вкладки просмотра (ключ overview манифеста .epd):
объект из штампа, помещения с площадями, высота потолка, что заложено — точки по видам,
щит, сантехника (приборы, вода, канализация, итог её сметы). Только то, что уже посчитано
из исходных данных: новых расчётов здесь нет. Варианты проводки — отдельным ключом манифеста
(pipeline.variant_block).
"""

from __future__ import annotations

from typing import Any

from floorplan_engine.electrical.anchors import symbol_key
from floorplan_engine.electrical.estimate import Estimate
from floorplan_engine.electrical.panel import BoardPanel
from floorplan_engine.epd.side import legend_entries
from floorplan_engine.model.geometry import Contour
from floorplan_engine.model.plumbing import FixtureType, Plumbing
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.model.texts import Language
from floorplan_engine.plumbing.network import FIXTURE_NAMES, Network, drop_bends


def overview_data(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical | None,
    panel: BoardPanel | None,
    plumbing: Plumbing | None = None,
    net: Network | None = None,
    plumbing_estimate: Estimate | None = None,
) -> dict[str, Any]:
    """Объект, помещения, потолок, точки по видам (как в условных обозначениях), щит и
    сантехника; plumbing_estimate — смета сантехники (та же, что out/plumbing-estimate.*):
    её итог — в итоге проекта вместе со сметой электрики выбранного варианта."""
    sheet = plan.sheet
    areas = {r.id: round(contours[r.id].area_m2, 2) for r in plan.rooms if r.id in contours}
    rooms = [
        {"id": r.id, "name": r.name, "area": areas[r.id], "wet": r.wet}
        for r in plan.rooms
        if r.id in areas
    ]
    out: dict[str, Any] = {
        "object": {
            "name": plan.name,
            "object": sheet.object or plan.name,
            "building": sheet.building,
            "code": sheet.code,
            "stage": sheet.stage,
            "organization": sheet.organization,
        },
        "language": plan.language,
        "rooms": rooms,
        "area": round(sum(areas.values()), 2),
        # не задана в room.yaml — 2700 допущением (как на листе проводки)
        "ceiling": {
            "height": plan.ceiling_height,
            "assumed": "ceiling_height" not in plan.model_fields_set,
        },
    }
    if elec is not None:
        counts: dict[str, float] = {}
        for p in elec.points:
            key = symbol_key(p)
            counts[key] = counts.get(key, 0) + p.count
        if elec.board is not None:
            counts["board"] = 1
        if elec.led_strips:
            counts["led_strip"] = round(sum(s.end - s.start for s in elec.led_strips) / 1000, 2)
        out["points"] = [
            {"key": e.key, "text": e.text, "count": counts.get(e.key, 0),
             "unit": "м" if e.key == "led_strip" else "шт"}
            for e in legend_entries(elec, plan.language)
        ]  # fmt: skip
    if panel is not None:
        out["panel"] = {
            "scheme": panel.scheme,
            "input": panel.input.label,
            "input_assumed": panel.input.assumed,
            "devices": len(panel.devices),
            "groups": len(panel.groups),
            "modules": panel.modules,
            "installed_w": round(panel.installed),
            "calculated_w": round(panel.calculated),
        }
    if plumbing is not None and net is not None:
        out["plumbing"] = plumbing_overview(plumbing, net, plan.language)
        if plumbing_estimate is not None and plumbing_estimate.lines:
            out["plumbing"]["estimate"] = {
                "total": round(plumbing_estimate.total, 2),
                "currency": plumbing_estimate.currency,
                "unpriced": plumbing_estimate.unpriced,
            }
    return out


def _m(mm: float) -> float:
    return round(mm / 1000, 1)


def plumbing_overview(plumbing: Plumbing, net: Network, language: Language) -> dict[str, Any]:
    """Сантехника: приборы по видам, вода (разводка, источник горячей, длины, водорозетки) и
    канализация (длины по диаметрам, стояки, отводы 45°, косые тройники). Длины — по трассам,
    без запаса сметы."""
    fixtures: dict[FixtureType, int] = {}
    for fx in plumbing.fixtures:
        fixtures[fx.type] = fixtures.get(fx.type, 0) + 1
    sewer = net.pipes_of("sewer")
    by_d: dict[int, float] = {}
    for p in sewer:
        d = 110 if p.d >= 100 else 50
        by_d[d] = by_d.get(d, 0.0) + p.total
    hot = net.hot_source
    return {
        "fixtures": [
            {"type": t.value, "text": FIXTURE_NAMES[t][language], "count": n}
            for t, n in fixtures.items()
        ],
        "water": {
            "distribution": net.distribution,
            "hot": None if hot is None else ("riser" if hot == "riser" else "boiler"),
            "cold_m": _m(sum(p.total for p in net.pipes_of("cold"))),
            "hot_m": _m(sum(p.total for p in net.pipes_of("hot"))),
            "outlets": sum(1 for o in net.outlets if o.kind != "sewer"),
            "input_assumed": net.input_assumed,
        },
        "sewer": {
            "pipes": [{"d": d, "m": _m(by_d[d])} for d in sorted(by_d)],
            "risers": sum(1 for r in net.risers if r.sewer),
            "bends": sum(p.bends + drop_bends(p.rise) for p in sewer),
            "tees": sum(1 for p in sewer if p.parent is not None),
            "errors": len(net.sewer_errors),
        },
        "weak": len(net.weak),
    }
