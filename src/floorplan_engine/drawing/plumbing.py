"""Сантехника на листе: трубы воды и канализации, приборы с номерами, водорозетки, стояки,
узел ввода и коллекторы, препятствия; таблицы «Сантехприборы» и «Трубы», легенда.

Расчёт — plumbing/network.py; здесь — только DXF. Трубы, что идут по одной линии, — в
своих полосах (lanes, как кабели проводки), повороты скруглены; холодная — синяя, горячая —
красная, канализация — коричневая и толще; её участки по стене над полом (в стяжку не
помещаются, в коробе) — оранжевым пунктиром. У конца трубы — диаметр, у канализации ещё
уклон: «Ø50 i=0,035»; нет места — подписи нет (диаметр есть в таблице «Трубы»).
Номер прибора — в кружке у стены, как номера точек электрики; что за прибор — в таблице.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Sequence
from dataclasses import replace
from functools import partial

from ezdxf.colors import RGB
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.base import BaseLayout
from ezdxf.layouts.layout import Modelspace, Paperspace
from shapely.geometry import LineString, Point, Polygon

from floorplan_engine.drawing.fixture_symbols import SIZES, Frame, Shape, symbol
from floorplan_engine.drawing.ids import tagged
from floorplan_engine.drawing.layers import (
    A_TEXT,
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
    TEXT_ROOM_MM,
    TEXT_SMALL_MM,
    text_width,
)
from floorplan_engine.drawing.plan import add_text
from floorplan_engine.drawing.tables import CELL_PAD, TEXT_GAP, Column, Table, name_width
from floorplan_engine.drawing.titleblock import LW_THICK, LW_THIN
from floorplan_engine.drawing.wiring import (
    Segment,
    _Labels,
    clearance,
    fillet,
    lanes,
    offset_path,
    segments,
)
from floorplan_engine.electrical.routing import CLEARANCE
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.plumbing import Fixture, FixtureType, ObstacleType, Plumbing
from floorplan_engine.model.scale import sheet
from floorplan_engine.model.schema import Plan
from floorplan_engine.model.texts import Language
from floorplan_engine.plumbing.network import Collector, Kind, Network, Pipe
from floorplan_engine.plumbing.rows import (
    fixture_numbers,
    fixture_rows,
    pipe_rows,
)
from floorplan_engine.plumbing.rows import text as rows_text

COLORS: dict[Kind, int] = {"cold": 0x1F77B4, "hot": 0xD62728, "sewer": 0x8C564B}
# Канализация по стене над полом: свой цвет (просмотр и PNG типов линий не рисуют) и пунктир
SURFACE_COLOR = 0xE6862A
LAYERS = {"cold": P_COLD, "hot": P_HOT, "sewer": P_SEWER}
LW_WATER = 25
LW_SEWER = 50
LANE_MM = 0.9  # шаг полос труб на листе
SNAP_LANES = 2.0  # трубы на соседних линиях ближе стольких шагов полосы — одним пучком
BAND_MM = 12.0
FILLET_MM = 1.2
FIXTURE_R_MM = 2.2  # кружок номера прибора
FIXTURE_OUT_MM = 4.0  # кружок — на столько от стены в помещение
OUTLET_R_MM = 0.55  # водорозетка, выпуск
RISER_MIN_R_MM = 1.2
COLLECTOR_LEN = 160.0  # мм модели вдоль стены
COLLECTOR_PLACE = 500.0  # мм: коллекторы ближе — в одном месте, подпись общая
COLLECTOR_DEPTH_MM = 1.6
LABEL_MM = 1.8
OBSTACLE_HATCH = "NET"  # короб, инсталляция — сеткой: стены — косой штриховкой ANSI31
OBSTACLE_HATCH_MM = 1.6  # шаг сетки на листе — редкая, светлее стен
WHITE = 0xFFFFFF
FIXTURE_NEAR = 150.0  # мм: прибор у препятствия «ванна» или «поддон» — нарисован им
# Ванна и поддон, заданные препятствием, рисуются прибором в его контуре, без штриховки
DRAWN_AS_FIXTURE = {
    ObstacleType.BATH: FixtureType.BATH,
    ObstacleType.SHOWER_TRAY: FixtureType.SHOWER,
}
LEGEND_ROW_MM = 6.0
LEGEND_SAMPLE_MM = 10.0
LEGEND_GAP_MM = 6.0

TEXT: dict[str, dict[str, str]] = {
    "legend": {"ru": "Условные обозначения", "uk": "Умовні позначення"},
    "riser": {"ru": "Стояк канализации Д110", "uk": "Стояк каналізації Д110"},
    "collector": {
        "ru": "Узел ввода, коллектор: Х — холодной, Г — горячей",
        "uk": "Вузол вводу, колектор: Х — холодної, Г — гарячої",
    },
    "fixture": {
        "ru": "Прибор (номер — в таблице), точки — водорозетки и выпуск",
        "uk": "Прилад (номер — у таблиці), точки — водорозетки і випуск",
    },
    "surface": {
        "ru": "Канализация по стене над полом (в стяжку не помещается) — в коробе",
        "uk": "Каналізація по стіні над підлогою (у стяжку не вміщується) — у коробі",
    },
    "symbol": {
        "ru": "Сантехприбор контуром — типовой размер, для ориентира",
        "uk": "Сантехприлад контуром — типовий розмір, для орієнтиру",
    },
    "obstacle": {
        "ru": "Препятствие: трубы в обход (в короб — только своего прибора)",
        "uk": "Перешкода: труби в обхід (у короб — лише свого приладу)",
    },
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


def draw_plumbing(msp: Modelspace, plan: Plan, plumbing: Plumbing, net: Network) -> None:
    """Сантехника в модели: препятствия, трубы, водорозетки, приборы, стояки, коллекторы."""
    lang = plan.language
    _draw_obstacles(msp, plumbing, net, lang)
    _draw_symbols(msp, plumbing, net)
    paths = _lay_out(net)
    labels = _Labels(paths)
    for k, pipe in enumerate(net.pipes):
        _draw_pipe(msp, pipe, paths[k], labels)
    _draw_fixtures(msp, plumbing, net, labels)
    _draw_risers(msp, net, labels, lang)
    _draw_collectors(msp, net, lang)


def _lay_out(net: Network) -> list[list[Vec]]:
    """Пути труб со сдвигом в свои полосы (общие для воды и канализации: все по полу).
    Только рисунок: трассы, длины и смета — из сети как есть. Вода — под прямыми углами
    (косой вход отвода в трубу, что идёт парой не по сетке, — уголком); трубы на соседних
    линиях ближе SNAP_LANES шагов полосы — одним пучком в разных полосах, а не одна на другой
    (горячая парой с холодной лежит не на сетке, рядом с чужой трубой)."""
    paths = [list(p.path) if p.kind == "sewer" else _square(p.path) for p in net.pipes]
    all_segs = segments(paths)
    # Участок по грани стены (к водорозетке в стене) — от стены в помещение, первая полоса
    # на грани; вывод к стояку — на месте
    walls = net.rooms.boundary if net.rooms is not None else None
    risers = [r.center for r in net.risers]

    def at_riser(a: Vec, b: Vec) -> bool:
        return any((a - c).length() < 1.0 or (b - c).length() < 1.0 for c in risers)

    def on_wall(a: Vec, b: Vec) -> bool:
        if walls is None:
            return False
        return all(walls.distance(Point(v.as_tuple())) < 1.0 for v in (a, b, (a + b) * 0.5))

    fixed = {
        (s.run, s.index)
        for s in all_segs
        if at_riser(paths[s.run][s.index], paths[s.run][s.index + 1])
    }
    wall = {
        (s.run, s.index)
        for s in all_segs
        if (s.run, s.index) not in fixed
        and on_wall(paths[s.run][s.index], paths[s.run][s.index + 1])
    }
    free_segs = [s for s in all_segs if (s.run, s.index) not in fixed | wall]
    segs, snap = _snap(free_segs, sheet(LANE_MM) * SNAP_LANES)
    margin = max(sheet(0.4), CLEARANCE)
    room = clearance(net.free, margin) if net.free is not None else None
    offsets = lanes(segs, sheet(LANE_MM), sheet(BAND_MM), room)
    offsets = {key: shift + snap.get(key, 0.0) for key, shift in offsets.items()}
    offsets |= _wall_lanes([s for s in all_segs if (s.run, s.index) in wall], net)
    return [
        offset_path(path, [offsets.get((k, i), 0.0) for i in range(len(path) - 1)])
        for k, path in enumerate(paths)
    ]


def _wall_lanes(segs: Sequence[Segment], net: Network) -> dict[tuple[int, int], float]:
    """Участки по грани стены, что идут по одной линии, — в полосы от стены в помещение:
    первая — на грани, следующие — через шаг полосы внутрь (в стену сдвигать нельзя)."""
    out: dict[tuple[int, int], float] = {}
    sym = lanes(segs, sheet(LANE_MM), sheet(BAND_MM), None)
    low: dict[tuple[str, float], float] = {}
    for s in segs:
        key = (s.axis, s.fixed)
        low[key] = min(low.get(key, 0.0), sym.get((s.run, s.index), 0.0))
    inside = net.rooms
    for s in segs:
        shift = sym.get((s.run, s.index), 0.0) - low[(s.axis, s.fixed)]
        if shift < 1e-6 or inside is None:
            out[(s.run, s.index)] = 0.0
            continue
        mid = (s.lo + s.hi) / 2
        probe = Point(mid, s.fixed + 1.0) if s.axis == "h" else Point(s.fixed + 1.0, mid)
        out[(s.run, s.index)] = shift if inside.contains(probe) else -shift
    return out


def _square(path: Sequence[Vec]) -> list[Vec]:
    """Путь воды под прямыми углами: косой участок — уголком (поворот там, где путь и так
    поворачивает, — вдоль предыдущего участка); возврат по той же линии (вперёд и назад у
    врезки отвода) — без «шпильки»."""
    out = [path[0]]
    for a, b in itertools.pairwise(path):
        if abs(a.x - b.x) > 1.0 and abs(a.y - b.y) > 1.0:
            prev = out[-1] - out[-2] if len(out) >= 2 else Vec(0.0, 1.0)
            out.append(Vec(b.x, a.y) if abs(prev.x) >= abs(prev.y) else Vec(a.x, b.y))
        out.append(b)
    clean: list[Vec] = []
    for v in out:
        if clean and (v - clean[-1]).length() < 1.0:
            continue
        while len(clean) >= 2:
            d1, d2 = clean[-1] - clean[-2], v - clean[-1]
            cross = d1.x * d2.y - d1.y * d2.x
            if abs(cross) > 1e-6 * max(d1.length() * d2.length(), 1.0):
                break
            clean.pop()  # на одной прямой: средняя точка лишняя (и при возврате назад)
        clean.append(v)
    return clean


def _snap(
    segs: Sequence[Segment], tol: float
) -> tuple[list[Segment], dict[tuple[int, int], float]]:
    """Участки соседних линий одной оси (ближе tol), что перекрываются вдоль, — на одну
    линию (среднюю), чтобы lanes развёл их по полосам; второе — поправка сдвига участка:
    от его линии к общей."""
    parent = list(range(len(segs)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = sorted(range(len(segs)), key=lambda i: (segs[i].axis, segs[i].fixed))
    for n, i in enumerate(order):
        for j in order[n + 1 :]:
            a, b = segs[i], segs[j]
            if b.axis != a.axis or b.fixed - a.fixed > tol:
                break
            if min(a.hi, b.hi) - max(a.lo, b.lo) > 1.0:
                parent[root(j)] = root(i)
    groups: dict[int, list[int]] = {}
    for i in range(len(segs)):
        groups.setdefault(root(i), []).append(i)
    out = list(segs)
    snap: dict[tuple[int, int], float] = {}
    for members in groups.values():
        if len({segs[i].fixed for i in members}) < 2:
            continue
        line = sum(segs[i].fixed for i in members) / len(members)
        for i in members:
            out[i] = replace(segs[i], fixed=line)
            snap[(segs[i].run, segs[i].index)] = line - segs[i].fixed
    return out, snap


def _draw_pipe(msp: Modelspace, pipe: Pipe, path: Sequence[Vec], labels: _Labels) -> None:
    attribs: dict[str, object] = {
        "layer": LAYERS[pipe.kind].name,
        "true_color": COLORS[pipe.kind],
        "lineweight": LW_SEWER if pipe.kind == "sewer" else LW_WATER,
    }
    with tagged(msp, "pipe", pipe.id):
        for part, surface in _split(path, _scaled(pipe, path)):
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


def _length(path: Sequence[Vec]) -> float:
    return sum((b - a).length() for a, b in itertools.pairwise(path))


def _scaled(pipe: Pipe, path: Sequence[Vec]) -> list[tuple[float, float]]:
    """Участки трубы по стене над полом (мм от начала пути модели) — на путь листа: он
    сдвинут в свою полосу и чуть длиннее или короче."""
    model = _length(pipe.path)
    k = _length(path) / model if model > 1e-9 else 1.0
    return [(a * k, b * k) for a, b in pipe.surface]


def _split(
    path: Sequence[Vec], spans: Sequence[tuple[float, float]]
) -> list[tuple[list[Vec], bool]]:
    """Путь кусками: (точки, по стене над полом ли); spans — мм от начала пути."""
    if not spans:
        return [(list(path), False)]
    cuts = sorted({0.0, _length(path), *(x for span in spans for x in span)})
    out: list[tuple[list[Vec], bool]] = []
    for s0, s1 in itertools.pairwise(cuts):
        if s1 - s0 < 1.0:
            continue
        mid = (s0 + s1) / 2
        surface = any(a <= mid <= b for a, b in spans)
        part = _cut(path, s0, s1)
        if out and out[-1][1] == surface:
            out[-1] = ([*out[-1][0], *part[1:]], surface)
        else:
            out.append((part, surface))
    return out


def _cut(path: Sequence[Vec], s0: float, s1: float) -> list[Vec]:
    """Кусок ломаной от s0 до s1 мм по ней."""
    out: list[Vec] = []
    acc = 0.0
    for a, b in itertools.pairwise(path):
        n = (b - a).length()
        if n < 1e-9:
            continue
        lo, hi = max(s0, acc), min(s1, acc + n)
        if lo <= hi:
            pa = a + (b - a) * ((lo - acc) / n)
            pb = a + (b - a) * ((hi - acc) / n)
            if not out or (out[-1] - pa).length() > 1e-6:
                out.append(pa)
            out.append(pb)
        acc += n
    return out


def _dot(msp: BaseLayout, at: Vec, r: float, layer: str, color: int) -> None:
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
                _dot(msp, o.node, sheet(OUTLET_R_MM), P_FIXT.name, COLORS[o.kind])
            o = outlets[0]
            mid = sum((x.node for x in outlets), Vec(0.0, 0.0)) * (1 / len(outlets))
            center = _clear_of(mid + o.inward * sheet(FIXTURE_OUT_MM), o.inward, r, net, placed)
            placed.append(center)
            msp.add_line(
                (mid + o.inward * sheet(OUTLET_R_MM)).as_tuple(),
                (center - o.inward * r).as_tuple(),
                dxfattribs={"layer": P_FIXT.name, "lineweight": LW_THIN},
            )
            _dot(msp, center, r, P_FIXT.name, WHITE)  # подложка: контур и трубы не под номером
            msp.add_circle(
                center.as_tuple(), r, dxfattribs={"layer": P_FIXT.name, "lineweight": LW_THIN}
            )
            add_text(msp, str(numbers[fx.id]), center, TEXT_SMALL_MM, P_FIXT.name)
        labels.block(Point(center.as_tuple()).buffer(r))


def _clear_of(center: Vec, inward: Vec, r: float, net: Network, placed: Sequence[Vec]) -> Vec:
    """Кружок прибора — не на коробе (прибор на инсталляции — перед ним) и не на кружке
    другого прибора в том же месте стены (бойлер над стиралкой — стопкой от стены)."""
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
    """Коллекторы на стене: в узле ввода оба, горячей от бойлера — у бойлера; подпись — одна
    на место: «КЛ.Х/Г», «КЛ.Х» или «КЛ.Г»."""
    places: list[list[Collector]] = []
    for c in net.collectors:
        place = next((g for g in places if (g[0].node - c.node).length() <= COLLECTOR_PLACE), None)
        if place is None:
            places.append([c])
        else:
            place.append(c)
    for group in places:
        c0 = group[0]
        mid = sum((c.node for c in group), Vec(0.0, 0.0)) * (1 / len(group))
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
            if kind is not None:  # ванна, поддон — прибором в своём контуре
                frame, size = _obstacle_frame(poly)
                _draw_shapes(msp, symbol(kind, frame, size))
                continue
            msp.add_lwpolyline(
                pts, close=True, dxfattribs={"layer": P_OBST.name, "lineweight": LW_THIN}
            )
            hatch = msp.add_hatch(color=256, dxfattribs={"layer": P_OBST.name})
            hatch.set_pattern_fill(OBSTACLE_HATCH, scale=sheet(OBSTACLE_HATCH_MM))
            hatch.paths.add_polyline_path(pts, is_closed=True)
            _obstacle_label(msp, ob.type, poly, lang)


def _obstacle_frame(poly: Polygon) -> tuple[Frame, tuple[float, float]]:
    """Прибор в контуре препятствия (прямоугольник): вдоль длинной стороны."""
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
    """Контур прибора у его стены (типовой размер); висит на коробе или инсталляции — от
    её лица; ванна и душ, заданные препятствием, — пусто (их рисует препятствие)."""
    outlets = net.by_fixture(fx.id)
    if not outlets:
        return []
    o = outlets[0]
    mid = sum((x.node for x in outlets), Vec(0.0, 0.0)) * (1 / len(outlets))
    here = Point(mid.as_tuple())
    v0 = 0.0
    if fx.type is not FixtureType.BOILER:  # бойлер висит над коробом — на стене
        ray = LineString([mid.as_tuple(), (mid + o.inward * 5000.0).as_tuple()])
        for oid in net.hollow:
            poly = net.obstacles[oid]
            if poly.buffer(1.0).contains(here):
                v0 = max(v0, ray.intersection(poly).length)
    frame = Frame(mid + o.inward * v0, Vec(-o.inward.y, o.inward.x), o.inward)
    return symbol(fx.type, frame)


def _draw_symbols(msp: Modelspace, plumbing: Plumbing, net: Network) -> None:
    """Приборы контуром — под трубами и номерами; ванна и душ у препятствия — его рисунком."""
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
    """Ванна или душ у препятствия «ванна» или «поддон» — прибор уже нарисован им."""
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


# --- Таблицы и легенда на листе ---------------------------------------------------


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


LegendDraw = Callable[[Paperspace, Vec], None]  # образец строки; точка — середина слева


def _legend_rows(lang: Language) -> list[tuple[str, LegendDraw]]:
    """Строки легенды: подпись и как нарисовать образец (мм листа)."""
    kinds: tuple[Kind, ...] = ("cold", "hot", "sewer")

    def line(kind: Kind, surface: bool = False) -> LegendDraw:
        def draw(psp: Paperspace, mid: Vec) -> None:
            attribs: dict[str, object] = {
                "layer": LAYERS[kind].name,
                "true_color": COLORS[kind],
                "lineweight": LW_SEWER if kind == "sewer" else LW_WATER,
            }
            if surface:
                attribs |= {
                    "linetype": SURFACE_LINETYPE,
                    "ltscale": 1 / sheet(1.0),
                    "true_color": SURFACE_COLOR,
                }
            psp.add_line(mid.as_tuple(), (mid.x + LEGEND_SAMPLE_MM, mid.y), dxfattribs=attribs)

        return draw

    def riser(psp: Paperspace, mid: Vec) -> None:
        psp.add_circle(
            (mid.x + LEGEND_SAMPLE_MM / 2, mid.y),
            1.4,
            dxfattribs={
                "layer": P_RISER.name,
                "true_color": COLORS["sewer"],
                "lineweight": LW_THICK,
            },
        )

    def collector(psp: Paperspace, mid: Vec) -> None:
        for k, kind in enumerate(kinds[:2]):
            x = mid.x + 1.0 + k * 4.5
            psp.add_lwpolyline(
                [
                    (x, mid.y - 0.8),
                    (x + 3.5, mid.y - 0.8),
                    (x + 3.5, mid.y + 0.8),
                    (x, mid.y + 0.8),
                ],
                close=True,
                dxfattribs={"layer": P_RISER.name, "true_color": COLORS[kind]},
            )

    def fixture(psp: Paperspace, mid: Vec) -> None:
        c = Vec(mid.x + LEGEND_SAMPLE_MM / 2 + 1.5, mid.y)
        psp.add_circle(c.as_tuple(), FIXTURE_R_MM, dxfattribs={"layer": P_FIXT.name})
        add_text(psp, "1", c, TEXT_SMALL_MM, P_FIXT.name, scale=1.0)
        for k, kind in enumerate((kinds[1], kinds[0], kinds[2])):
            _dot(
                psp, Vec(mid.x + 0.6, mid.y + 1.6 - k * 1.6), OUTLET_R_MM, P_FIXT.name, COLORS[kind]
            )

    def symbols(psp: Paperspace, mid: Vec) -> None:
        # Умывальник и ванна в масштабе образца: контуры модели (мм) — в мм листа
        w, d = SIZES[FixtureType.BATH]
        k = LEGEND_SAMPLE_MM / w
        frame = Frame(Vec(0.0, 0.0), Vec(1.0, 0.0), Vec(0.0, -1.0))
        for sh in symbol(FixtureType.BATH, frame):
            pts = [
                (mid.x + LEGEND_SAMPLE_MM / 2 + v.x * k, mid.y + d * k / 2 + v.y * k)
                for v in sh.points
            ]
            psp.add_lwpolyline(pts, close=sh.closed, dxfattribs={"layer": P_SYMB.name})

    def obstacle(psp: Paperspace, mid: Vec) -> None:
        pts = [
            (mid.x, mid.y - 2.0),
            (mid.x + LEGEND_SAMPLE_MM, mid.y - 2.0),
            (mid.x + LEGEND_SAMPLE_MM, mid.y + 2.0),
            (mid.x, mid.y + 2.0),
        ]
        psp.add_lwpolyline(pts, close=True, dxfattribs={"layer": P_OBST.name})
        hatch = psp.add_hatch(color=256, dxfattribs={"layer": P_OBST.name})
        hatch.set_pattern_fill(OBSTACLE_HATCH, scale=OBSTACLE_HATCH_MM)
        hatch.paths.add_polyline_path(pts, is_closed=True)

    rows: list[tuple[str, LegendDraw]] = [(rows_text(k, lang), line(k)) for k in kinds]
    rows += [
        (text("surface", lang), line("sewer", surface=True)),
        (text("riser", lang), riser),
        (text("collector", lang), collector),
        (text("fixture", lang), fixture),
        (text("symbol", lang), symbols),
        (text("obstacle", lang), obstacle),
    ]
    return rows


def legend_variants(lang: Language) -> list[tuple[float, float, LegendDraw]]:
    """Варианты легенды у штампа — (ширина, высота, рисунок от левого верхнего угла): по k
    строк в колонке; раскладка берёт самый низкий, что помещается (layout.fit_legend)."""
    rows = _legend_rows(lang)
    title = text("legend", lang)
    out: list[tuple[float, float, LegendDraw]] = []
    for k in range(3, len(rows) + 1):
        chunks = [rows[i : i + k] for i in range(0, len(rows), k)]
        widths = [
            LEGEND_SAMPLE_MM + 3.0 + max(text_width(t, TEXT_SMALL_MM) for t, _ in chunk)
            for chunk in chunks
        ]
        width = max(
            sum(widths) + LEGEND_GAP_MM * (len(chunks) - 1), text_width(title, TEXT_ROOM_MM)
        )
        height = TEXT_ROOM_MM + 2.0 + k * LEGEND_ROW_MM

        def draw(
            psp: Paperspace,
            tl: Vec,
            *,
            chunks: list[list[tuple[str, LegendDraw]]],
            widths: list[float],
        ) -> None:
            left = TextEntityAlignment.MIDDLE_LEFT
            add_text(
                psp,
                title,
                Vec(tl.x, tl.y - TEXT_ROOM_MM / 2),
                TEXT_ROOM_MM,
                A_TEXT.name,
                align=left,
                scale=1.0,
            )
            x = tl.x
            for chunk, w in zip(chunks, widths, strict=True):
                y = tl.y - TEXT_ROOM_MM - 2.0
                for label, sample in chunk:
                    mid = Vec(x, y - LEGEND_ROW_MM / 2)
                    sample(psp, mid)
                    add_text(
                        psp,
                        label,
                        Vec(x + LEGEND_SAMPLE_MM + 3.0, mid.y),
                        TEXT_SMALL_MM,
                        A_TEXT.name,
                        align=left,
                        scale=1.0,
                    )
                    y -= LEGEND_ROW_MM
                x += w + LEGEND_GAP_MM

        out.append((width, height, partial(draw, chunks=chunks, widths=widths)))
    return out
