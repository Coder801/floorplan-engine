"""Plumbing for the viewer: object cards (hints), side panel tables of the "Plumbing" sheet,
the estimate for the "Estimate" tab and pipes for the 3D scene. No new calculations: the
network comes from plumbing/network.py, rows from plumbing/rows.py, the estimate from
plumbing/estimate.py.

Object keys match the XDATA (drawing/plumbing.py): fixture:<id>, pipe:<id>,
riser:<id>, collector:<id>, obstacle:<id>.
"""

from __future__ import annotations

import itertools
from typing import Any

from floorplan_engine.drawing.plumbing import COLORS, fixtures_table, pipes_table
from floorplan_engine.drawing.schedules import estimate_table
from floorplan_engine.electrical.pricing import Prices, price_notes
from floorplan_engine.epd.objects import ObjectInfo
from floorplan_engine.epd.side import SideTable, from_table
from floorplan_engine.model.plumbing import Plumbing
from floorplan_engine.model.schema import Plan
from floorplan_engine.model.texts import Language
from floorplan_engine.plumbing.estimate import build_estimate
from floorplan_engine.plumbing.estimate import text as estimate_text
from floorplan_engine.plumbing.network_model import Network, Pipe, fixture_name
from floorplan_engine.plumbing.rows import fixture_numbers, fixture_rows, pipe_rows, plumbing_notes
from floorplan_engine.plumbing.rows import text as rows_text
from floorplan_engine.plumbing.rules import SCREED_MM

FLOOR_Z_MM = 30.0  # water in the screed: slightly above the scene floor so it is visible
SEWER_MIN_Z_MM = 30.0  # sewer in the screed: on the scene floor, axis not lower

TEXT: dict[str, dict[str, str]] = {
    "room": {"ru": "Помещение", "uk": "Приміщення"},
    "wall": {"ru": "Стена", "uk": "Стіна"},
    "offset": {"ru": "От начала стены", "uk": "Від початку стіни"},
    "supply": {"ru": "Водорозетки", "uk": "Водорозетки"},
    "drain": {"ru": "Выпуск", "uk": "Випуск"},
    "assumed": {"ru": " (типовая)", "uk": " (типова)"},
    "sewer_drop": {"ru": "Перепад до стояка", "uk": "Перепад до стояка"},
    "drop_value": {
        "ru": "{L} м, нужно {d} мм при i={i}; врезка {r} мм",
        "uk": "{L} м, треба {d} мм при i={i}; врізка {r} мм",
    },
    "podium": {"ru": "Подиум", "uk": "Подіум"},
    "warning": {"ru": "Внимание", "uk": "Увага"},
    "pipe_cold": {"ru": "Холодная вода Ø{d}", "uk": "Холодна вода Ø{d}"},
    "pipe_hot": {"ru": "Горячая вода Ø{d}", "uk": "Гаряча вода Ø{d}"},
    "pipe_sewer": {"ru": "Канализация Ø{d}", "uk": "Каналізація Ø{d}"},
    "from": {"ru": "Откуда", "uk": "Звідки"},
    "to": {"ru": "Куда", "uk": "Куди"},
    "length": {"ru": "Длина", "uk": "Довжина"},
    "parts": {
        "ru": "{total} м: по полу {floor}, в стене {wall}, вверх {rise}",
        "uk": "{total} м: по підлозі {floor}, у стіні {wall}, вгору {rise}",
    },
    "slope": {"ru": "Уклон", "uk": "Ухил"},
    "branch": {"ru": "отвод от {p}", "uk": "відвід від {p}"},
    "riser": {"ru": "Стояк {id}", "uk": "Стояк {id}"},
    "sewer_riser": {"ru": "Канализация Д110", "uk": "Каналізація Д110"},
    "water_riser": {"ru": "Вода", "uk": "Вода"},
    "yes": {"ru": "есть", "uk": "є"},
    "inlet": {"ru": "Врезка", "uk": "Врізка"},
    "inlet_value": {"ru": "ось на {h} мм от пола{a}", "uk": "вісь на {h} мм від підлоги{a}"},
    "assumption": {"ru": ", допущение", "uk": ", припущення"},
    "collector": {"ru": "Коллектор {kind}", "uk": "Колектор {kind}"},
    "cold": {"ru": "холодной воды", "uk": "холодної води"},
    "hot": {"ru": "горячей воды", "uk": "гарячої води"},
    "outputs": {"ru": "Выходов", "uk": "Виходів"},
    "obstacle": {"ru": "Препятствие", "uk": "Перешкода"},
    "size": {"ru": "Размер", "uk": "Розмір"},
    "riser_name": {"ru": "стояк {id}", "uk": "стояк {id}"},
}


def text(key: str, language: Language, **values: object) -> str:
    return TEXT[key][language].format(**values)


def _m(mm: float) -> str:
    return f"{mm / 1000:.1f}".replace(".", ",")


def plumbing_objects(plan: Plan, plumbing: Plumbing, net: Network) -> dict[str, ObjectInfo]:
    """Plumbing object cards by "type:id"."""
    lang = plan.language
    rooms = {r.id: r.name for r in plan.rooms}
    numbers = fixture_numbers(plumbing)
    out: dict[str, ObjectInfo] = {}
    sewer = {s.fixture: s for s in net.sewer}
    weak: dict[str, list[str]] = {}
    for w in net.weak:
        weak.setdefault(w.target, []).append(w.text[lang])
    names: dict[str, str] = {f.id: fixture_name(f, lang) for f in plumbing.fixtures}
    for fx in plumbing.fixtures:
        rows: list[tuple[str, str]] = [
            (text("room", lang), rooms.get(fx.room, fx.room)),
            (text("wall", lang), fx.wall),
            (text("offset", lang), f"{fx.offset:g} мм"),
        ]
        outlets = net.by_fixture(fx.id)
        water = [o for o in outlets if o.kind in ("cold", "hot")]
        if water:
            letters = ", ".join(rows_text(f"letter_{o.kind}", lang) for o in water)
            tail = text("assumed", lang) if water[0].assumed else ""
            rows.append((text("supply", lang), f"{letters} — {water[0].height:g} мм{tail}"))
        drain = next((o for o in outlets if o.kind == "sewer"), None)
        if drain is not None:
            tail = text("assumed", lang) if drain.assumed else ""
            rows.append((text("drain", lang), f"Ø{drain.d} — {drain.height:g} мм{tail}"))
        check = sewer.get(fx.id)
        if check is not None:
            i = f"{check.slope:g}".replace(".", ",")
            rows.append(
                (
                    text("sewer_drop", lang),
                    text(
                        "drop_value",
                        lang,
                        L=_m(check.length),
                        d=round(check.drop),
                        i=i,
                        r=f"{check.inlet:g}",
                    ),
                )
            )
            if check.podium > 0:
                rows.append((text("podium", lang), f"{round(check.podium)} мм"))
        rows += [(text("warning", lang), t) for t in weak.get(fx.id, [])]
        out[f"fixture:{fx.id}"] = ObjectInfo(f"{numbers[fx.id]}. {names[fx.id]}", tuple(rows))
    pipes = {p.id: p for p in net.pipes}
    collectors = {c.id: c for c in net.collectors}

    def where(ref: str) -> str:
        if ref in names:
            return f"{names[ref]} ({numbers[ref]})"
        if ref in collectors:
            return text("collector", lang, kind=text(collectors[ref].kind, lang))
        if ref in pipes:
            return text("branch", lang, p=_pipe_title(pipes[ref], lang))
        return text("riser_name", lang, id=ref)

    for p in net.pipes:
        rows = [
            (text("from", lang), where(p.parent or p.source)),
            (text("to", lang), where(p.target)),
            (
                text("length", lang),
                text(
                    "parts",
                    lang,
                    total=_m(p.total),
                    floor=_m(p.length),
                    wall=_m(p.wall_run),
                    rise=_m(p.rise),
                ),
            ),
        ]
        if p.kind == "sewer":
            rows.append((text("slope", lang), f"{p.slope:g}".replace(".", ",")))
        out[f"pipe:{p.id}"] = ObjectInfo(_pipe_title(p, lang), tuple(rows))
    for r in net.risers:
        rows = [(text("room", lang), rooms.get(r.room, r.room))]
        if r.sewer:
            a = text("assumption", lang) if r.inlet_assumed else ""
            rows.append(
                (text("sewer_riser", lang), text("inlet_value", lang, h=f"{r.inlet:g}", a=a))
            )
        if r.water:
            rows.append((text("water_riser", lang), text("yes", lang)))
        out[f"riser:{r.id}"] = ObjectInfo(text("riser", lang, id=r.id), tuple(rows))
    for c in net.collectors:
        out[f"collector:{c.id}"] = ObjectInfo(
            text("collector", lang, kind=text(c.kind, lang)),
            (
                (text("room", lang), rooms.get(c.room, c.room)),
                (text("wall", lang), c.wall),
                (text("outputs", lang), str(c.outputs)),
            ),
        )
    for ob in plumbing.obstacles:
        poly = net.obstacles.get(ob.id)
        if poly is None:
            continue
        x0, y0, x1, y1 = poly.bounds
        out[f"obstacle:{ob.id}"] = ObjectInfo(
            f"{text('obstacle', lang)}: {ob.type.value}",
            (
                (text("room", lang), rooms.get(ob.room, ob.room)),
                (text("size", lang), f"{x1 - x0:.0f} × {y1 - y0:.0f} мм"),
            ),
        )
    return out


def _pipe_title(p: Pipe, lang: Language) -> str:
    return text(f"pipe_{p.kind}", lang, d=p.d)


def plumbing_tables(
    plan: Plan, plumbing: Plumbing, net: Network, prices: Prices | None
) -> dict[str, list[SideTable]]:
    """Side panel tables of the "Plumbing" sheet and the estimate for the "Estimate" tab."""
    lang = plan.language
    out: list[SideTable] = []
    fixtures = fixtures_table(plan, plumbing, net)
    if fixtures is not None:
        keys = [r.keys for r in fixture_rows(plan, plumbing, net)]
        out.append(from_table(fixtures, keys, plumbing_notes(plan, plumbing, net)))
    pipes = pipes_table(plan, net)
    if pipes is not None:
        out.append(from_table(pipes, [r.keys for r in pipe_rows(net)]))
    tables = {"plumbing": out}
    priced = prices is not None and prices.priced
    est = build_estimate(net, plumbing, prices or Prices(), lang)
    if est.lines:
        title = estimate_text("sheet_title" if priced else "sheet_volumes", lang)
        notes = price_notes(est, prices, lang) if prices is not None and priced else []
        side = from_table(estimate_table(est, lang, priced=priced, title=title), notes=notes)
        tables["plumbing_estimate"] = [side]
    return tables


def plumbing_scene(net: Network, ceiling: float) -> dict[str, Any]:
    """Plumbing for the 3D scene (key scene, next to wiring): pipes by height: water on the floor in
    the screed and up to the water outlet at the wall; sewer from the drain with a slope to the
    riser; fixtures as points at the wall; risers vertical from floor to ceiling. Sewer: from the
    riser inlet up along the slope along walls, at the fixture up inside the wall to the drain."""
    pipes: dict[str, dict[str, Any]] = {}
    by_fixture = {(o.fixture, o.kind): o for o in net.outlets}
    for p in net.pipes:
        pts = list(p.path)
        color = f"#{COLORS[p.kind]:06x}"
        if p.kind == "sewer":
            # Axis from the finished floor: pipe bottom from the slab (network: z0, slope) minus the
            # screed plus the radius; in the screed it sits on the scene floor so it is visible. At
            # the
            # fixture it goes up in the wall to the drain; a drain below the pipe means a podium, no
            # vertical
            lift = p.d / 2 - SCREED_MM
            z = p.z0 + lift
            z_pts = [[round(pts[0].x, 1), round(pts[0].y, 1), round(max(z, SEWER_MIN_Z_MM), 1)]]
            for a, b in itertools.pairwise(pts):
                z += (b - a).length() * p.slope
                z_pts.append([round(b.x, 1), round(b.y, 1), round(max(z, SEWER_MIN_Z_MM), 1)])
            outlet = by_fixture.get((p.target, "sewer"))
            if outlet is not None and outlet.height > max(z, SEWER_MIN_Z_MM) + 1.0:
                last = pts[-1]
                z_pts.append([round(last.x, 1), round(last.y, 1), round(outlet.height, 1)])
        else:
            outlet = by_fixture.get((p.target, p.kind))
            top = outlet.height if outlet is not None else FLOOR_Z_MM
            z_pts = [[round(v.x, 1), round(v.y, 1), FLOOR_Z_MM] for v in pts]
            last = pts[-1]
            z_pts.append([round(last.x, 1), round(last.y, 1), round(top, 1)])
        pipes[p.id] = {
            "key": f"pipe:{p.id}",
            "kind": p.kind,
            "d": p.d,
            "color": color,
            "room": p.room,
            "pts": z_pts,
        }
    fixtures = {}
    for o in net.outlets:
        fixtures[f"{o.fixture}.{o.kind}"] = {
            "key": f"fixture:{o.fixture}",
            "kind": o.kind,
            "color": f"#{COLORS[o.kind]:06x}",
            "pos": [round(o.node.x, 1), round(o.node.y, 1), round(o.height, 1)],
            "inward": [round(o.inward.x, 6), round(o.inward.y, 6)],
            "room": o.room,
        }
    risers = [
        {
            "key": f"riser:{r.id}",
            "pos": [round(r.center.x, 1), round(r.center.y, 1)],
            "r": 55.0,
            "z": [0.0, round(ceiling, 1)],
            "room": r.room,
        }
        for r in net.risers
    ]
    return {"pipes": pipes, "fixtures": fixtures, "risers": risers}
