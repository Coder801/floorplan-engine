"""Plumbing on the sheet: water and sewer pipes, numbered fixtures, water outlets, risers,
the supply unit and manifolds, obstacles; "Fixtures" and "Pipes" tables (legend:
plumbing_legend.py).

Calculation lives in plumbing/network.py; this module only draws DXF. Pipes running along one
line go in their own lanes (like wiring cables, pipe_paths.py), corners are rounded; cold is blue,
hot is red, sewer is brown and thicker; sewer parts along the wall above the floor (too big for the
screed, in a box) are dashed orange. At the pipe end: diameter, plus slope for sewer:
"Ø50 i=0,035"; no room means no label (the diameter is in the "Pipes" table).
The fixture number is in a circle by the wall, like electrical point numbers; what the
fixture is, is in the table.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from ezdxf.colors import RGB
from ezdxf.layouts.base import BaseLayout
from ezdxf.layouts.layout import Modelspace
from shapely.geometry import LineString, Point, Polygon

from floorplan_engine.drawing.fixture_symbols import Frame, Shape, symbol
from floorplan_engine.drawing.ids import tagged
from floorplan_engine.drawing.layers import (
    P_COLD,
    P_FIXT,
    P_HOT,
    P_OBST,
    P_RISER,
    P_SEWER,
    P_SYMB,
    P_TEXT,
    SURFACE_LINETYPE,
    TEXT_DIM_MM,
    TEXT_SMALL_MM,
    text_width,
)
from floorplan_engine.drawing.pipe_paths import lay_out, surface_parts
from floorplan_engine.drawing.plan import add_text
from floorplan_engine.drawing.tables import CELL_PAD, TEXT_GAP, Column, Table, name_width
from floorplan_engine.drawing.titleblock import LW_THICK, LW_THIN
from floorplan_engine.drawing.wiring import _Labels, fillet
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.plumbing import Fixture, FixtureType, ObstacleType, Plumbing
from floorplan_engine.model.scale import sheet
from floorplan_engine.model.schema import Plan
from floorplan_engine.model.texts import Language
from floorplan_engine.plumbing.network_model import Collector, Network, Pipe
from floorplan_engine.plumbing.rows import (
    fixture_numbers,
    fixture_rows,
    pipe_rows,
)
from floorplan_engine.plumbing.rows import text as rows_text
from floorplan_engine.plumbing.rules import Kind

COLORS: dict[Kind, int] = {"cold": 0x1F77B4, "hot": 0xD62728, "sewer": 0x8C564B}
# Sewer along the wall above the floor: own colour (viewer and PNG do not draw line types) and
# dashes
SURFACE_COLOR = 0xE6862A
LAYERS = {"cold": P_COLD, "hot": P_HOT, "sewer": P_SEWER}
LW_WATER = 25
LW_SEWER = 50
FILLET_MM = 1.2
FIXTURE_R_MM = 2.2  # fixture number circle
FIXTURE_OUT_MM = 4.0  # circle placed this far from the wall into the room
OUTLET_R_MM = 0.55  # water outlet, drain
RISER_MIN_R_MM = 1.2
COLLECTOR_LEN = 160.0  # model mm along the wall
COLLECTOR_PLACE = 500.0  # mm: manifolds closer than this share one spot and one label
COLLECTOR_DEPTH_MM = 1.6
LABEL_MM = 1.8
OBSTACLE_HATCH = "NET"  # box, installation frame: grid hatch; walls use ANSI31
OBSTACLE_HATCH_MM = 1.6  # grid step on the sheet: sparse, lighter than walls
WHITE = 0xFFFFFF
FIXTURE_NEAR = 150.0  # mm: a fixture at a "bath" or "tray" obstacle is drawn by it
# A bath or tray given as an obstacle is drawn as the fixture inside its outline, no hatch
DRAWN_AS_FIXTURE = {
    ObstacleType.BATH: FixtureType.BATH,
    ObstacleType.SHOWER_TRAY: FixtureType.SHOWER,
}

TEXT: dict[str, dict[str, str]] = {
    "riser_label": {"ru": "Ст.К1-{n}", "uk": "Ст.К1-{n}"},
    "collector_cold": {"ru": "КЛ.Х", "uk": "КЛ.Х"},
    "collector_hot": {"ru": "КЛ.Г", "uk": "КЛ.Г"},
    "installation": {"ru": "инсталляция", "uk": "інсталяція"},
    "bath": {"ru": "ванна", "uk": "ванна"},
    "shower_tray": {"ru": "поддон", "uk": "піддон"},
    "box": {"ru": "короб", "uk": "короб"},
    "cabinet": {"ru": "тумба", "uk": "тумба"},
    "column": {"ru": "колонна", "uk": "колона"},
    "other": {"ru": "препятствие", "uk": "перешкода"},
}


def text(key: str, language: Language, **values: object) -> str:
    return TEXT[key][language].format(**values)


def pipe_attribs(kind: Kind) -> dict[str, object]:
    return {
        "layer": LAYERS[kind].name,
        "true_color": COLORS[kind],
        "lineweight": LW_SEWER if kind == "sewer" else LW_WATER,
    }


def net_hatch(layout: BaseLayout, pts: Sequence[tuple[float, ...]], scale: float) -> None:
    """Obstacle grid hatch: lighter than the walls."""
    hatch = layout.add_hatch(color=256, dxfattribs={"layer": P_OBST.name})
    hatch.set_pattern_fill(OBSTACLE_HATCH, scale=scale)
    hatch.paths.add_polyline_path(pts, is_closed=True)


def _middle(points: Iterable[Vec]) -> Vec:
    nodes = list(points)
    return sum(nodes, Vec(0.0, 0.0)) * (1 / len(nodes))


def draw_plumbing(msp: Modelspace, plan: Plan, plumbing: Plumbing, net: Network) -> None:
    """Plumbing in the model: obstacles, pipes, water outlets, fixtures, risers, manifolds."""
    lang = plan.language
    _draw_obstacles(msp, plumbing, net, lang)
    _draw_symbols(msp, plumbing, net)
    paths = lay_out(net)
    labels = _Labels(paths)
    for k, pipe in enumerate(net.pipes):
        _draw_pipe(msp, pipe, paths[k], labels)
    _draw_fixtures(msp, plumbing, net, labels)
    _draw_risers(msp, net, labels, lang)
    _draw_collectors(msp, net, lang)


def _draw_pipe(msp: Modelspace, pipe: Pipe, path: Sequence[Vec], labels: _Labels) -> None:
    attribs = pipe_attribs(pipe.kind)
    with tagged(msp, "pipe", pipe.id):
        for part, surface in surface_parts(pipe, path):
            extra = {"linetype": SURFACE_LINETYPE, "true_color": SURFACE_COLOR} if surface else {}
            msp.add_lwpolyline(
                fillet(part, sheet(FILLET_MM)), format="xyb", dxfattribs={**attribs, **extra}
            )
        label = f"Ø{pipe.d}"
        if pipe.kind == "sewer":
            label += f" i={pipe.slope:g}".replace(".", ",")
        placed = labels.place_end(path, label, at_end=True)
        if placed is not None:
            t, at, angle = placed
            add_text(msp, t, at, LABEL_MM, P_TEXT.name, angle, color=COLORS[pipe.kind])


def dot(msp: BaseLayout, at: Vec, r: float, layer: str, color: int) -> None:
    hatch = msp.add_hatch(dxfattribs={"layer": layer, "true_color": color})
    hatch.set_solid_fill(rgb=RGB((color >> 16) & 255, (color >> 8) & 255, color & 255))
    hatch.paths.add_edge_path().add_arc(at.as_tuple(), r, 0, 360)


def _draw_fixtures(msp: Modelspace, plumbing: Plumbing, net: Network, labels: _Labels) -> None:
    numbers = fixture_numbers(plumbing)
    r = sheet(FIXTURE_R_MM)
    placed: list[Vec] = []
    for fx in plumbing.fixtures:
        outlets = net.by_fixture(fx.id)
        if not outlets:
            continue
        with tagged(msp, "fixture", fx.id):
            for o in outlets:
                dot(msp, o.node, sheet(OUTLET_R_MM), P_FIXT.name, COLORS[o.kind])
            o = outlets[0]
            mid = _middle(x.node for x in outlets)
            center = _clear_of(mid + o.inward * sheet(FIXTURE_OUT_MM), o.inward, r, net, placed)
            placed.append(center)
            msp.add_line(
                (mid + o.inward * sheet(OUTLET_R_MM)).as_tuple(),
                (center - o.inward * r).as_tuple(),
                dxfattribs={"layer": P_FIXT.name, "lineweight": LW_THIN},
            )
            dot(msp, center, r, P_FIXT.name, WHITE)  # underlay
            msp.add_circle(
                center.as_tuple(), r, dxfattribs={"layer": P_FIXT.name, "lineweight": LW_THIN}
            )
            add_text(msp, str(numbers[fx.id]), center, TEXT_SMALL_MM, P_FIXT.name)
        labels.block(Point(center.as_tuple()).buffer(r))


def _clear_of(center: Vec, inward: Vec, r: float, net: Network, placed: Sequence[Vec]) -> Vec:
    """Fixture circle: not on a box (a fixture on an installation frame goes in front of it) and not
    on another fixture's circle at the same wall spot (boiler above washer: stacked from the
    wall)."""
    boxes = [p for k, p in net.obstacles.items() if k in net.hollow]
    for _ in range(40):
        here = Point(center.as_tuple())
        on_box = any(p.distance(here) < r for p in boxes)
        on_other = any((center - c).length() < 2 * r + sheet(0.4) for c in placed)
        if not on_box and not on_other:
            return center
        center = center + inward * sheet(1.0)
    return center


def _draw_risers(msp: Modelspace, net: Network, labels: _Labels, lang: Language) -> None:
    for n, riser in enumerate(net.risers, 1):
        r = max(55.0, sheet(RISER_MIN_R_MM))
        with tagged(msp, "riser", riser.id):
            msp.add_circle(
                riser.center.as_tuple(),
                r,
                dxfattribs={
                    "layer": P_RISER.name,
                    "true_color": COLORS["sewer"],
                    "lineweight": LW_THICK,
                },
            )
            if riser.water:
                pair: tuple[tuple[Kind, float], ...] = (("cold", -1.0), ("hot", 1.0))
                for kind, dx in pair:
                    at = riser.center + Vec(dx * r * 1.9, r * 1.6)
                    msp.add_circle(
                        at.as_tuple(),
                        r * 0.45,
                        dxfattribs={
                            "layer": P_RISER.name,
                            "true_color": COLORS[kind],
                            "lineweight": LW_THIN,
                        },
                    )
            label = text("riser_label", lang, n=n)
            spot = labels.place_end([riser.center + Vec(-1.0, 0.0), riser.center], label, True)
            at = spot[1] if spot is not None else riser.center + Vec(0.0, -r - sheet(LABEL_MM))
            add_text(msp, label, at, LABEL_MM, P_TEXT.name)


def _draw_collectors(msp: Modelspace, net: Network, lang: Language) -> None:
    """Manifolds on the wall: both at the supply unit, hot from a boiler at the boiler; one label
    per
    spot: "КЛ.Х/Г", "КЛ.Х" or "КЛ.Г"."""
    places: list[list[Collector]] = []
    for c in net.collectors:
        place = next((g for g in places if (g[0].node - c.node).length() <= COLLECTOR_PLACE), None)
        if place is None:
            places.append([c])
        else:
            place.append(c)
    for group in places:
        c0 = group[0]
        mid = _middle(c.node for c in group)
        names = "/".join(
            text(f"collector_{c.kind}", lang).removeprefix("КЛ.")
            for c in sorted(group, key=lambda c: c.kind)
        )
        at = mid + c0.inward * sheet(COLLECTOR_DEPTH_MM + LABEL_MM)
        with tagged(msp, "collector", c0.id):
            add_text(msp, f"КЛ.{names}", at, LABEL_MM, P_TEXT.name)
    for c in net.collectors:
        along = Vec(-c.inward.y, c.inward.x)
        a = c.node - along * (COLLECTOR_LEN / 2)
        b = c.node + along * (COLLECTOR_LEN / 2)
        d = c.inward * sheet(COLLECTOR_DEPTH_MM)
        with tagged(msp, "collector", c.id):
            msp.add_lwpolyline(
                [a.as_tuple(), b.as_tuple(), (b + d).as_tuple(), (a + d).as_tuple()],
                close=True,
                dxfattribs={
                    "layer": P_RISER.name,
                    "true_color": COLORS[c.kind],
                    "lineweight": LW_THICK,
                },
            )


def _draw_obstacles(msp: Modelspace, plumbing: Plumbing, net: Network, lang: Language) -> None:
    for ob in plumbing.obstacles:
        poly = net.obstacles.get(ob.id)
        if poly is None:
            continue
        pts = list(poly.exterior.coords)[:-1]
        with tagged(msp, "obstacle", ob.id):
            kind = DRAWN_AS_FIXTURE.get(ob.type)
            if kind is not None:  # bath, tray: drawn as the fixture inside its outline
                frame, size = _obstacle_frame(poly)
                _draw_shapes(msp, symbol(kind, frame, size))
                continue
            msp.add_lwpolyline(
                pts, close=True, dxfattribs={"layer": P_OBST.name, "lineweight": LW_THIN}
            )
            net_hatch(msp, pts, sheet(OBSTACLE_HATCH_MM))
            _obstacle_label(msp, ob.type, poly, lang)


def _obstacle_frame(poly: Polygon) -> tuple[Frame, tuple[float, float]]:
    """Fixture inside an obstacle outline (rectangle): along the long side."""
    x0, y0, x1, y1 = poly.bounds
    if x1 - x0 >= y1 - y0:
        return Frame(Vec((x0 + x1) / 2, y0), Vec(1.0, 0.0), Vec(0.0, 1.0)), (x1 - x0, y1 - y0)
    return Frame(Vec(x0, (y0 + y1) / 2), Vec(0.0, 1.0), Vec(1.0, 0.0)), (y1 - y0, x1 - x0)


def _draw_shapes(msp: BaseLayout, shapes: Sequence[Shape]) -> None:
    for sh in shapes:
        msp.add_lwpolyline(
            [v.as_tuple() for v in sh.points],
            close=sh.closed,
            dxfattribs={"layer": P_SYMB.name, "lineweight": LW_THIN},
        )


def fixture_shapes(fx: Fixture, net: Network) -> list[Shape]:
    """Fixture outline at its wall (typical size); hanging on a box or installation frame, from its
    face; a bath or shower given as an obstacle gives nothing (the obstacle draws it)."""
    outlets = net.by_fixture(fx.id)
    if not outlets:
        return []
    o = outlets[0]
    mid = _middle(x.node for x in outlets)
    here = Point(mid.as_tuple())
    v0 = 0.0
    if fx.type is not FixtureType.BOILER:  # boiler hangs above the box, on the wall
        ray = LineString([mid.as_tuple(), (mid + o.inward * 5000.0).as_tuple()])
        for oid in net.hollow:
            poly = net.obstacles[oid]
            if poly.buffer(1.0).contains(here):
                v0 = max(v0, ray.intersection(poly).length)
    frame = Frame(mid + o.inward * v0, Vec(-o.inward.y, o.inward.x), o.inward)
    return symbol(fx.type, frame)


def _draw_symbols(msp: Modelspace, plumbing: Plumbing, net: Network) -> None:
    """Fixtures as outlines under pipes and numbers; bath and shower at an obstacle use its
    drawing.
    """
    beside = {
        ob.id: DRAWN_AS_FIXTURE[ob.type]
        for ob in plumbing.obstacles
        if ob.type in DRAWN_AS_FIXTURE and ob.id in net.obstacles
    }
    for fx in plumbing.fixtures:
        if fx.type in (FixtureType.BATH, FixtureType.SHOWER) and _in_obstacle(fx, net, beside):
            continue
        shapes = fixture_shapes(fx, net)
        if shapes:
            with tagged(msp, "fixture", fx.id):
                _draw_shapes(msp, shapes)


def _in_obstacle(fx: Fixture, net: Network, beside: dict[str, FixtureType]) -> bool:
    """Bath or shower at a "bath" or "tray" obstacle: the fixture is already drawn by it."""
    outlets = net.by_fixture(fx.id)
    if not outlets:
        return False
    here = Point(outlets[0].node.as_tuple())
    return any(
        kind is fx.type and net.obstacles[oid].distance(here) <= FIXTURE_NEAR
        for oid, kind in beside.items()
    )


def _obstacle_label(msp: Modelspace, kind: ObstacleType, poly: Polygon, lang: Language) -> None:
    label = text(kind.value, lang)
    minx, miny, maxx, maxy = poly.bounds
    w = sheet(text_width(label, LABEL_MM))
    c = poly.representative_point()
    if w < maxx - minx:
        add_text(msp, label, Vec(c.x, c.y), LABEL_MM, P_OBST.name)
    elif w < maxy - miny:
        add_text(msp, label, Vec(c.x, c.y), LABEL_MM, P_OBST.name, 90.0)


# --- Tables and legend on the sheet --------------------------------------------


def fixtures_table(plan: Plan, plumbing: Plumbing, net: Network) -> Table | None:
    lang = plan.language
    rows = fixture_rows(plan, plumbing, net)
    if not rows:
        return None

    def t(key: str) -> str:
        return rows_text(key, lang)

    def width(title: str, cells: Sequence[str], least: float = 12.0) -> float:
        longest = max(text_width(c, TEXT_DIM_MM) for c in [*cells, ""])
        head = max(text_width(w, TEXT_DIM_MM) for w in title.split(", "))
        return max(least, longest + 2 * CELL_PAD + TEXT_GAP, head + 2 * CELL_PAD + TEXT_GAP)

    columns = (
        Column(t("no"), 8.0),
        Column(t("fixture"), name_width([r.name for r in rows]), "left"),
        Column(t("room"), name_width([r.room for r in rows]), "left"),
        Column(t("supply"), width(t("supply"), [r.supply for r in rows])),
        Column(t("supply_h"), width(t("supply_h"), [r.supply_h for r in rows])),
        Column(t("drain"), width(t("drain"), [r.drain for r in rows])),
        Column(t("drain_h"), width(t("drain_h"), [r.drain_h for r in rows])),
    )
    cells = tuple(
        (str(r.number), r.name, r.room, r.supply, r.supply_h, r.drain, r.drain_h) for r in rows
    )
    return Table(t("fixtures"), columns, cells)


def pipes_table(plan: Plan, net: Network) -> Table | None:
    lang = plan.language
    rows = pipe_rows(net)
    if not rows:
        return None

    def t(key: str) -> str:
        return rows_text(key, lang)

    names = [t(r.kind) for r in rows]
    columns = (
        Column(t("kind"), name_width(names), "left"),
        Column(t("d"), 14.0),
        Column(t("count"), 12.0),
        Column(t("length"), 20.0),
    )
    cells = tuple(
        (name, str(r.d), str(r.count), _m(r.length)) for name, r in zip(names, rows, strict=True)
    )
    total = (t("total"), "", str(sum(r.count for r in rows)), _m(sum(r.length for r in rows)))
    return Table(t("pipes"), columns, cells, total=total)


def _m(mm: float) -> str:
    return f"{mm / 1000:.1f}".replace(".", ",")
