"""Debug trace of the wiring (`floorplan-engine trace`): routes one project with recording on
(electrical/trace.py) and draws what the search saw as SVG, without building the DXF.

The wiring is the one of the estimate (estimate_wiring, scale 1:25 as on the sheets) for the
chosen variant (variant.yaml) with the manual edits of wiring.yaml. For each line the last
search is kept: lines are routed again while boxes move off passing lines (round) and internet
and TV once more apart from power (stage "apart"); the last search is the final route unless the
line has a manual route.

The SVG has layers (g id) that can be switched off in the browser: rooms, drillable walls, the
grid of the focused line (free cells, wall bands, cells beside power, search cost), all lines,
the focused lines (grid path before pull dashed, final route solid), boxes and their moves.
Hovering a line shows its id, group, ends and costs.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from floorplan_engine.electrical import trace
from floorplan_engine.electrical.routing import STEP, RouteTrace, search_memo
from floorplan_engine.electrical.wiring import BoxMove, estimate_wiring
from floorplan_engine.electrical.wiring_model import JunctionBox, Run, Wiring
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.intake import Stage
from floorplan_engine.pipeline.assessment import assess_project
from floorplan_engine.pipeline.files import OUT_DIR

DEBUG_DIR = "debug"  # out/debug/: debug output, not for the client
MARGIN = 600.0  # mm around the plan
LEGEND = 900.0  # mm above the plan for the legend
FONT = 110.0  # mm
BOX = 160.0  # mm: box square on the debug drawing


class TraceError(RuntimeError):
    """The project has no wiring to trace: the message is for the user."""


@dataclass(frozen=True)
class TracedLine:
    run: Run  # the final line, as in the build
    search: RouteTrace | None  # its last search; None for a jumper along one frame
    routed: int  # how many times it was routed
    manual: bool  # manual route from wiring.yaml: the search is not what is drawn

    def matches(self, lines: Iterable[str], groups: Iterable[str], points: Iterable[str]) -> bool:
        r = self.run
        return r.id in lines or r.group in groups or bool({r.source, r.target} & set(points))


@dataclass(frozen=True)
class WiringTrace:
    rooms: tuple[tuple[Vec, ...], ...]  # inner outlines of the rooms
    wiring: Wiring
    walls: tuple[Polygon, ...]  # drillable walls (as the board router saw them)
    lines: tuple[TracedLine, ...]
    moves: tuple[BoxMove, ...]


def trace_wiring(project: Path) -> WiringTrace:
    """Route the project's wiring with recording on; TraceError if there is nothing to route."""
    assessment = assess_project(project)
    report = assessment.report
    if not assessment.plan_builds or report.plan is None:
        raise TraceError("План нельзя построить — см. floorplan-engine check.")
    status = assessment.status(Stage.ELECTRICAL)
    elec = report.electrical if status is not None and status.status.builds else None
    if elec is None:
        raise TraceError("Электрику нельзя построить — см. floorplan-engine check.")
    with search_memo(), trace.recording() as events:
        wiring = estimate_wiring(report.plan, report.contours, elec, report.wiring_edits)
    if wiring is None:
        raise TraceError("Проводки через коробки нет: нет щита или точек с группой.")
    last: dict[str, RouteTrace] = {}
    count: dict[str, int] = {}
    moves: list[BoxMove] = []
    walls: tuple[Polygon, ...] = ()
    for e in events:
        if isinstance(e.payload, BoxMove):
            moves.append(e.payload)
        elif isinstance(e.payload, RouteTrace):
            line = e.labels.get("line")
            if isinstance(line, str):
                last[line] = e.payload
                count[line] = count.get(line, 0) + 1
                if e.labels.get("source") == "board":
                    walls = e.payload.walls
    lines = tuple(
        TracedLine(r, last.get(r.id), count.get(r.id, 0), f"wire:{r.id}" in wiring.edited)
        for r in wiring.runs
    )
    rooms = tuple(tuple(c.vertices) for c in report.contours.values())
    return WiringTrace(rooms, wiring, walls, lines, tuple(moves))


def trace_file(project: Path, tags: Sequence[str]) -> Path:
    """out/debug/trace.svg, or trace-<tags>.svg for a selection."""
    name = "-".join(t.replace("/", "_") for t in tags)
    return project / OUT_DIR / DEBUG_DIR / (f"trace-{name}.svg" if name else "trace.svg")


def line_note(t: TracedLine) -> str:
    """One line of the text summary: what the search decided for the line."""
    r = t.run
    parts = [
        f"{r.id:<9} {r.group:<6} {r.source} → {r.target}",
        "пол" if r.route == "floor" else "потолок",
        f"план {r.plan_mm / 1000:.2f} м, всего {r.length_mm / 1000:.2f} м",
    ]
    if t.search is not None:
        parts.append(f"цена поиска {t.search.cost:.0f}")
        if t.search.wall_cells:
            parts.append("сквозь стену")
    if t.routed > 1:
        parts.append(f"поисков {t.routed}")
    if t.manual:
        parts.append("ручная трасса (wiring.yaml)")
    if r.circuit == "low" and not r.led:
        parts.append("слаботочка")
    return " · ".join(parts)


def trace_svg(tr: WiringTrace, focus: Sequence[TracedLine], cost: bool = False) -> str:
    """The debug drawing: the whole wiring, focus lines highlighted with their grid; cost paints
    the search cost of the first focus line over its grid."""
    xs = [v.x for room in tr.rooms for v in room]
    ys = [v.y for room in tr.rooms for v in room]
    minx, maxx = min(xs) - MARGIN, max(xs) + MARGIN
    miny, maxy = min(ys) - MARGIN, max(ys) + MARGIN + LEGEND
    width, height = maxx - minx, maxy - miny
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{minx:.0f} {-maxy:.0f} '
        f'{width:.0f} {height:.0f}" width="{width / 10:.0f}" height="{height / 10:.0f}" '
        f'font-family="sans-serif" font-size="{FONT:.0f}">',
        f'<rect x="{minx:.0f}" y="{-maxy:.0f}" width="{width:.0f}" height="{height:.0f}" '
        'fill="#fff"/>',
    ]
    if tr.wiring.free is not None:
        out.append(_layer("free", [_area(tr.wiring.free, 'fill="#f3f3f3" stroke="none"')]))
    out.append(
        _layer(
            "walls",
            [_area(w, 'fill="#f5a623" fill-opacity="0.35" stroke="none"') for w in tr.walls],
        )
    )
    out.append(
        _layer(
            "rooms",
            [
                f'<polygon points="{" ".join(_pt(v) for v in room)}" fill="none" '
                'stroke="#333" stroke-width="25"/>'
                for room in tr.rooms
            ],
        )
    )
    searched = next((t.search for t in focus if t.search is not None), None)
    if searched is not None:
        out.append(_layer("grid", _grid(searched, cost)))
    focused = {t.run.id for t in focus}
    out.append(
        _layer(
            "lines",
            [
                _line(t, "#9a9a9a" if focus else _color(t.run), 18)
                for t in tr.lines
                if t.run.id not in focused
            ],
        )
    )
    out.append(_layer("focus", [s for t in focus for s in _focus(t)]))
    out.append(_layer("boxes", [s for b in tr.wiring.boxes for s in _box(b)]))
    ends = {e for t in focus for e in (t.run.source, t.run.target)}
    out.append(_layer("moves", [s for m in tr.moves for s in _move(m, m.box in ends)]))
    out.append(_layer("legend", _legend(minx, maxy, focus, cost and searched is not None)))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _pt(v: Vec) -> str:
    return f"{v.x:.0f},{-v.y:.0f}"


def _layer(name: str, items: Sequence[str]) -> str:
    return f'<g id="{name}">\n' + "\n".join(items) + "\n</g>"


def _area(geom: BaseGeometry, style: str) -> str:
    """Polygons of a shapely area as one path (holes cut by evenodd)."""
    parts = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
    d = []
    for p in parts:
        if not isinstance(p, Polygon) or p.is_empty:
            continue
        for ring in (p.exterior, *p.interiors):
            coords = list(ring.coords)
            d.append("M" + " L".join(f"{x:.0f},{-y:.0f}" for x, y in coords) + " Z")
    return f'<path d="{" ".join(d)}" fill-rule="evenodd" {style}/>'


def _color(r: Run) -> str:
    if r.led:
        return "#c9a400"
    return "#2a7ab8" if r.circuit == "low" else "#555"


def _title(t: TracedLine) -> str:
    return f"<title>{escape(line_note(t))}</title>"


def _polyline(path: Sequence[Vec], style: str, title: str = "") -> str:
    pts = " ".join(_pt(v) for v in path)
    return f'<polyline points="{pts}" fill="none" {style}>{title}</polyline>'


def _line(t: TracedLine, color: str, width: float) -> str:
    dash = ' stroke-dasharray="60 40"' if t.run.route == "floor" else ""
    return _polyline(t.run.path, f'stroke="{color}" stroke-width="{width:.0f}"{dash}', _title(t))


def _focus(t: TracedLine) -> list[str]:
    """Focus line: grid path before pull (blue dashes), final route (red), ends and id."""
    out = []
    if t.search is not None and len(t.search.cells) > 1:
        out.append(
            _polyline(
                t.search.cells,
                'stroke="#1f6fd1" stroke-width="22" stroke-dasharray="50 35"',
            )
        )
    out.append(_line(t, "#d62728", 40))
    path = t.run.path
    out.append(f'<circle cx="{path[0].x:.0f}" cy="{-path[0].y:.0f}" r="70" fill="#2ca02c"/>')
    out.append(f'<circle cx="{path[-1].x:.0f}" cy="{-path[-1].y:.0f}" r="70" fill="#d62728"/>')
    mid = path[len(path) // 2]
    out.append(
        f'<text x="{mid.x + 60:.0f}" y="{-mid.y - 60:.0f}" fill="#d62728">'
        f"{escape(t.run.id)} {escape(t.run.group)}</text>"
    )
    return out


def _grid(s: RouteTrace, cost: bool) -> list[str]:
    """Free cells of the search grid: wall bands orange, cells beside power cyan; with cost each
    reached cell is painted from blue (cheap) to red (dear) by its search cost."""
    g = s.grid
    penalty = g.penalty or {}
    beside = (g.apart[0] | g.apart[1]) if g.apart is not None else frozenset()
    top = 0.0
    if cost:
        reached = (s.cell_cost(k) for k, ok in enumerate(g.free) if ok)
        top = max((x for x in reached if math.isfinite(x)), default=0.0)
    out = []
    half = STEP / 2
    for k, ok in enumerate(g.free):
        if not ok:
            continue
        c = g.center(k)
        if cost and top > 0 and math.isfinite(spent := s.cell_cost(k)):
            hue = 240 - 240 * spent / top
            fill = f'fill="hsl({hue:.0f},80%,60%)" fill-opacity="0.55"'
        elif k in penalty:
            fill = 'fill="#f5a623" fill-opacity="0.6"'
        elif k in beside:
            fill = 'fill="#5fc6e0" fill-opacity="0.5"'
        else:
            fill = 'fill="#dde4f0"'
        title = f"<title>{s.cell_cost(k):.0f}</title>" if cost else ""
        out.append(
            f'<rect x="{c.x - half + 4:.0f}" y="{-c.y - half + 4:.0f}" width="{STEP - 8:.0f}" '
            f'height="{STEP - 8:.0f}" {fill}>{title}</rect>'
        )
    for v, color in ((g.center(s.start), "#2ca02c"), (g.center(s.target), "#d62728")):
        out.append(
            f'<rect x="{v.x - half:.0f}" y="{-v.y - half:.0f}" width="{STEP:.0f}" '
            f'height="{STEP:.0f}" fill="none" stroke="{color}" stroke-width="20"/>'
        )
    return out


def _box(b: JunctionBox) -> list[str]:
    v, h = b.anchor.node, BOX / 2
    return [
        f'<rect x="{v.x - h:.0f}" y="{-v.y - h:.0f}" width="{BOX:.0f}" height="{BOX:.0f}" '
        f'fill="#fff" stroke="#111" stroke-width="20"><title>{escape(b.id)} · {escape(b.group)}'
        f" · {escape(b.room)}</title></rect>",
        f'<text x="{v.x + h + 20:.0f}" y="{-v.y + h:.0f}">{escape(b.label)}</text>',
    ]


def _move(m: BoxMove, avoid: bool) -> list[str]:
    """Box move off passing lines: an arrow old → new; with avoid also the area it kept off
    (purple), only for a box of a focus line: for all boxes it covers the plan."""
    area = [_area(m.avoid, 'fill="#9b59b6" fill-opacity="0.15" stroke="none"')] if avoid else []
    return [
        *area,
        f'<line x1="{m.before.x:.0f}" y1="{-m.before.y:.0f}" x2="{m.after.x:.0f}" '
        f'y2="{-m.after.y:.0f}" stroke="#9b59b6" stroke-width="25" stroke-dasharray="40 30">'
        f"<title>{escape(m.box)}: перенесена с чужих трасс</title></line>",
        f'<circle cx="{m.before.x:.0f}" cy="{-m.before.y:.0f}" r="50" fill="none" '
        'stroke="#9b59b6" stroke-width="20"/>',
    ]


def _legend(x0: float, top: float, focus: Sequence[TracedLine], cost: bool) -> list[str]:
    rows = [
        "серые / синие / жёлтые — силовые / слаботочка / 12 В LED; штрих — по полу",
        "оранжевое — стены, которые можно сверлить; фиолетовое — перенос коробки с чужих трасс "
        "(с --point <коробка> — и зона, от которой она уходила)",
    ]
    if focus:
        rows.append(
            "красная — итоговая трасса; синий пунктир — путь по сетке до натяжки; "
            "голубые клетки — рядом с силовым кабелем"
        )
    if cost:
        rows.append("клетки: цена поиска от источника, синие — дёшево, красные — дорого")
    rows += [line_note(t) for t in focus[:4]]
    return [
        f'<text x="{x0 + MARGIN / 2:.0f}" y="{-top + MARGIN / 2 + (i + 1) * FONT * 1.4:.0f}" '
        f'fill="#222">{escape(r)}</text>'
        for i, r in enumerate(rows)
    ]
