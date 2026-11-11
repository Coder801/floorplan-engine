"""Lighting plan (decision 2026-10-28, P2): lights, switches and which switch turns on what.

The "switch → light" link is electrical/switch_links.py: from the switch's `controls`, otherwise
an assumption by group and room marked "*".

The sheet shows walls and openings, light and switch symbols (layers E-SWITCH, E-LIGHT, E-LED),
links (E-LINK, dashed lines at right angles: switch → nearest light → next one…; a link
differs from a cable by its dashes and layer; decision 2026-11-03: no arcs; decision 2026-11-11:
right angles instead of slanted segments, each leg along the plan axes, the elbow inside the
rooms, from a wall switch the first leg goes away from its wall), point numbers as on the
electrical sheet, only for lights and switches (L-TEXT), and the "Switches" table.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from ezdxf.layouts.layout import Modelspace
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from floorplan_engine.drawing.electrical import (
    label_clusters,
    label_placer,
    place_label,
    strip_area,
    symbol_area,
)
from floorplan_engine.drawing.ids import tagged
from floorplan_engine.drawing.layers import E_LINK, L_TEXT, LW_LINK
from floorplan_engine.drawing.tables import Column, Table, name_width
from floorplan_engine.electrical.anchors import Anchor, point_anchor, stack_shifts
from floorplan_engine.electrical.point_numbers import number_points, point_name, ranges
from floorplan_engine.electrical.switch_links import switch_links
from floorplan_engine.model.geometry import Contour, Vec, room_geometries
from floorplan_engine.model.schema import (
    LIGHT_TYPES,
    SWITCH_TYPES,
    Electrical,
    ElectricalPoint,
    Plan,
)
from floorplan_engine.model.texts import Language

TEXT: dict[str, dict[str, str]] = {
    "title": {"ru": "Выключатели", "uk": "Вимикачі"},
    "number": {"ru": "№", "uk": "№"},
    "switch": {"ru": "Выключатель", "uk": "Вимикач"},
    "controls": {"ru": "Включает", "uk": "Вмикає"},
    "group": {"ru": "Группа", "uk": "Група"},
    "strip": {"ru": "лента {name}", "uk": "стрічка {name}"},
    "assumed": {
        "ru": "* — связь по группе и помещению, не из проекта: уточните (controls в "
        "electrical.yaml); у двухклавишного — какая клавиша что включает",
        "uk": "* — зв'язок за групою і приміщенням, не з проєкту: уточніть (controls в "
        "electrical.yaml); у двоклавішного — яка клавіша що вмикає",
    },
}


def text(key: str, language: Language, **kw: object) -> str:
    return TEXT[key][language].format(**kw)


def is_lighting(p: ElectricalPoint) -> bool:
    return p.type in LIGHT_TYPES or p.type in SWITCH_TYPES


def lighting_model(elec: Electrical) -> Electrical:
    """Lighting-only electrical model: lights, switches and strips, no panel. Used for the legend of
    the "Lighting" sheet and its badge in the viewer."""
    return elec.model_copy(
        update={"points": [p for p in elec.points if is_lighting(p)], "board": None, "media": None}
    )


def line_link(msp: Modelspace, points: Sequence[Vec], attribs: dict[str, object]) -> None:
    """Link through points: straight segments between neighbours, as one polyline."""
    msp.add_lwpolyline([(v.x, v.y) for v in points], format="xy", dxfattribs=attribs)


ALIGNED_MM = 1.0  # points closer than this along an axis are joined by one straight leg


def _manhattan(a: Vec, b: Vec) -> float:
    return abs(a.x - b.x) + abs(a.y - b.y)


def right_angle_path(
    points: Sequence[Vec], inside: BaseGeometry | None = None, first: Vec | None = None
) -> list[Vec]:
    """Path through points with legs along the plan axes: between two points not on one axis an
    elbow is added. Of the two elbows the one whose legs stay inside `inside` (the rooms) wins;
    for the first pair, the one whose first leg goes along `first` (away from the switch's wall);
    otherwise horizontal first."""
    if not points:
        return []
    out = [points[0]]
    for k, (a, b) in enumerate(pairwise(points)):
        if abs(a.x - b.x) < ALIGNED_MM or abs(a.y - b.y) < ALIGNED_MM:
            out.append(b)
            continue
        horizontal, vertical = Vec(b.x, a.y), Vec(a.x, b.y)
        prefer_vertical = k == 0 and first is not None and abs(first.y) > abs(first.x)
        elbows = [vertical, horizontal] if prefer_vertical else [horizontal, vertical]
        if inside is not None:
            fits = [
                e
                for e in elbows
                if inside.covers(LineString([a.as_tuple(), e.as_tuple(), b.as_tuple()]))
            ]
            elbows = fits or elbows
        out += [elbows[0], b]
    return out


def chain(start: Vec, targets: Sequence[tuple[str, Vec]]) -> list[tuple[str, Vec]]:
    """Visit targets from start: always go to the nearest one not yet visited (along the axes, as
    the link is drawn)."""
    left = list(targets)
    out: list[tuple[str, Vec]] = []
    at = start
    while left:
        k = min(range(len(left)), key=lambda i: (_manhattan(left[i][1], at), left[i][0]))
        item = left.pop(k)
        out.append(item)
        at = item[1]
    return out


def draw_lighting(
    msp: Modelspace, plan: Plan, contours: dict[str, Contour], elec: Electrical
) -> None:
    """Switch links and light numbers on their own layers (symbols come from the electrical
    sheet).
    """
    geoms_list = room_geometries(plan, contours)
    geoms = {g.room.id: g for g in geoms_list}
    shifts = stack_shifts(elec.points)
    anchors: dict[str, Anchor] = {
        p.id: point_anchor(p, geoms, shifts[k]) for k, p in enumerate(elec.points)
    }
    spots = {pid: _spot(a) for pid, a in anchors.items()}
    for strip in elec.led_strips:
        c = strip_area(strip, geoms).centroid
        spots[strip.id] = Vec(c.x, c.y)

    # As on the lighting plan: lights of one set form one chain of lines at right angles, and
    # the switch gets one link to the nearest light of the set
    inside = unary_union(
        [Polygon([v.as_tuple() for v in g.contour.vertices]) for g in geoms_list]
    ).buffer(ALIGNED_MM)
    links = switch_links(elec)
    attribs = {"layer": E_LINK.name, "lineweight": LW_LINK}
    drawn: set[frozenset[str]] = set()
    for link in links:
        targets = [(t, spots[t]) for t in link.targets if t in spots]
        if not targets:
            continue
        start = spots[link.switch]
        key = frozenset(t for t, _ in targets)
        if key not in drawn and len(targets) > 1:
            drawn.add(key)
            head = min(targets, key=lambda tv: (_manhattan(tv[1], start), tv[0]))
            path = chain(head[1], [tv for tv in targets if tv[0] != head[0]])
            with tagged(msp, "light_set", ",".join(sorted(key))):
                line_link(msp, right_angle_path([head[1], *(v for _, v in path)], inside), attribs)
        nearest = min(targets, key=lambda tv: (_manhattan(tv[1], start), tv[0]))
        with tagged(msp, "switch_link", link.switch):
            route = right_angle_path([start, nearest[1]], inside, anchors[link.switch].inward)
            line_link(msp, route, attribs)

    lights = [p for p in elec.points if is_lighting(p)]
    symbols = [symbol_area(anchors[p.id]) for p in lights]
    strips = [strip_area(s, geoms) for s in elec.led_strips]
    placer = label_placer(geoms_list, symbols, strips)
    numbers = number_points(plan, elec)
    for cluster in label_clusters(lights):
        ids = [lights[k].id for k in cluster]
        first, last = anchors[ids[0]], anchors[ids[-1]]
        center = first.pos + (last.pos - first.pos) * 0.5
        label_at = Anchor(center, first.inward, first.wall_dir, first.depth)
        own = unary_union([symbol_area(anchors[i]) for i in ids])
        with tagged(msp, "label", ",".join(ids)):
            place_label(
                msp,
                placer,
                [ranges([numbers[i] for i in ids])],
                label_at,
                own,
                lights[cluster[0]].room,
                layer=L_TEXT.name,
            )


def _spot(a: Anchor) -> Vec:
    """Where a link points: the symbol centre (for a wall point, offset from the wall)."""
    if a.inward is None:
        return a.pos
    return a.pos + a.inward * (a.depth / 2)


@dataclass(frozen=True)
class SwitchRow:
    numbers: str
    name: str
    controls: str
    group: str
    point_ids: tuple[str, ...]


def switch_rows(plan: Plan, elec: Electrical) -> list[SwitchRow]:
    """Rows of the "Switches" table by switch number."""
    lang = plan.language
    numbers = number_points(plan, elec)
    by_id = {p.id: p for p in elec.points}
    strips = {s.id: s for s in elec.led_strips}
    rows: list[SwitchRow] = []
    for link in sorted(switch_links(elec), key=lambda lk: numbers[lk.switch]):
        s = by_id[link.switch]
        nums = [numbers[t] for t in link.targets if t in numbers]
        named = [text("strip", lang, name=strips[t].note or t) for t in link.targets if t in strips]
        what = ", ".join(x for x in [ranges(nums), *named] if x)
        rows.append(
            SwitchRow(
                str(numbers[s.id]),
                point_name(s, lang),
                f"{what}*" if link.assumed else what,
                s.group or "",
                (s.id, *link.targets),
            )
        )
    return rows


def switch_table(plan: Plan, elec: Electrical) -> tuple[Table, list[str]] | None:
    """The "Switches" table and a note about assumptions; None if no switch has links."""
    rows = switch_rows(plan, elec)
    if not rows:
        return None
    lang = plan.language
    columns = (
        Column(text("number", lang), 10.0),
        Column(text("switch", lang), name_width([r.name for r in rows]), "left"),
        Column(text("controls", lang), name_width([r.controls for r in rows]), "left"),
        Column(text("group", lang), 16.0),
    )
    cells = tuple((r.numbers, r.name, r.controls, r.group) for r in rows)
    notes = [text("assumed", lang)] if any(r.controls.endswith("*") for r in rows) else []
    return Table(text("title", lang), columns, cells), notes
