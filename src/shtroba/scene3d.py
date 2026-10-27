"""3D-сцена проводки для просмотра: квартира в объёме и трассы по высоте — из модели.

Новых расчётов нет: план трасс, коробки и подъёмы — те же, что у листа проводки и сметы
(wiring.py), здесь они только развёрнуты по высоте. Мм модели, ось Z вверх, пол — 0.

- Стены — призмы по участкам контура (внутренняя грань → внешние углы, как на плане), от
  пола до потолка; над дверью и проёмом — перемычка, под окном — подоконная часть. Общая
  перегородка — один кусок с нормалями в обе комнаты (normals): по ним просмотр срезает
  стены, что стоят между камерой и помещением.
- Трасса: подъём от источника (щит, коробка) до плоскости трассы — потолок или пол (route
  floor), путь по плану в этой плоскости, спуск к точке. Совпадающие трассы — пучком, кабели
  в PITCH_MM друг от друга (на листе полосы шире — это приём чертежа, не место в квартире).
  Концы — у грани стены, а не у макушки символа листа.
- Высоты проёмов, которых нет в room.yaml, — допущения (DOOR_TOP_MM, WINDOW_SILL_MM,
  WINDOW_HEIGHT_MM), перечислены в assumed.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from shtroba.draw_electrical import Anchor, board_anchor, group_colors, point_anchor
from shtroba.draw_plan import RoomGeometry, room_geometries
from shtroba.draw_wiring import lanes as lane_offsets
from shtroba.draw_wiring import offset_path, segments
from shtroba.geometry import Contour, Vec, WallSegment
from shtroba.routing import fit_path
from shtroba.schema import Electrical, Opening, OpeningType, Plan
from shtroba.wiring import JunctionBox, Wiring

PITCH_MM = 15.0  # кабели пучка — друг от друга
WALL_GAP_MM = 20.0  # спуск и символ точки — от грани стены, чтобы не тонуть в ней
FLOOR_Z_MM = 20.0  # трасса по полу (в стяжке) — чуть выше пола сцены, чтобы её было видно
DOOR_TOP_MM = 2100.0  # допущения, если в room.yaml нет высоты проёма
WINDOW_SILL_MM = 900.0
WINDOW_HEIGHT_MM = 1400.0
MIN_AREA_MM2 = 100.0  # осколки стен меньше — не рисуются
SHARED_SHARE = 0.25  # перекрытие больше этой доли куска — общая стена двух комнат
NO_COLOR = "#888888"  # точка без группы


def _xy(v: Vec) -> list[float]:
    return [round(v.x, 1), round(v.y, 1)]


def _xyz(v: Vec, z: float) -> list[float]:
    return [round(v.x, 1), round(v.y, 1), round(z, 1)]


def _rings(geom: BaseGeometry) -> list[list[list[list[float]]]]:
    """Многоугольники: внешний контур и отверстия, без повтора первой точки."""
    polys = getattr(geom, "geoms", [geom])
    out = []
    for p in polys:
        if not isinstance(p, Polygon) or p.area < MIN_AREA_MM2:
            continue
        rings = [p.exterior, *p.interiors]
        out.append([[[round(x, 1), round(y, 1)] for x, y in r.coords[:-1]] for r in rings])
    return out


def _opening_span(op: Opening, ceiling: float) -> list[tuple[float, float]]:
    """Где в проёме есть стена, по высоте: над дверью — перемычка, у окна — ещё и низ."""
    if op.type is OpeningType.WINDOW:
        sill = op.sill if op.sill is not None else WINDOW_SILL_MM
        top = sill + (op.height if op.height is not None else WINDOW_HEIGHT_MM)
        spans = [(0.0, sill), (top, ceiling)]
    else:
        spans = [(op.height if op.height is not None else DOOR_TOP_MM, ceiling)]
    return [(lo, hi) for lo, hi in spans if hi - lo > 1.0]


def _assumed_opening(op: Opening) -> bool:
    if op.type is OpeningType.WINDOW:
        return op.sill is None or op.height is None
    return op.height is None


class _Walls:
    """Куски стен без наложений: общий кусок перегородки — один, с нормалями обеих комнат.
    Наложение — по плану и по высоте сразу: под- и надоконная части одного окна не дубли."""

    def __init__(self) -> None:
        self.pieces: list[dict[str, Any]] = []
        self.shapes: list[tuple[BaseGeometry, tuple[float, float]]] = []

    def add(self, key: str, geom: BaseGeometry, z: tuple[float, float], normal: Vec) -> None:
        n = [round(normal.x, 6) + 0.0, round(normal.y, 6) + 0.0]  # без -0.0
        geom = shapely.make_valid(geom)
        overlap = []
        for piece, (shape, zz) in zip(self.pieces, self.shapes, strict=True):
            if zz[0] >= z[1] - 1.0 or z[0] >= zz[1] - 1.0:
                continue  # одно над другим
            common = shape.intersection(geom).area
            if common <= MIN_AREA_MM2:
                continue
            overlap.append(shape)
            # Общая стена — заметная доля куска; угол соседней стены (стык) — не в счёт
            if common > SHARED_SHARE * min(shape.area, geom.area) and n not in piece["normals"]:
                piece["normals"].append(n)
        rest = geom.difference(unary_union(overlap)) if overlap else geom
        rings = _rings(rest)
        if not rings:
            return
        self.shapes.append((rest, z))
        self.pieces.append({"key": key, "polys": rings, "z": [z[0], z[1]], "normals": [n]})


def _wall_quad(g: RoomGeometry, seg: WallSegment) -> BaseGeometry:
    """Кусок стены: внутренняя грань и внешние углы (на стыке под 180° четырёхугольник
    бывает самопересекающимся — приводится к валидному)."""
    corners = (seg.start, seg.end, g.outer_end(seg), g.outer_start(seg))
    return shapely.make_valid(Polygon([p.as_tuple() for p in corners]))


def _strip(seg: WallSegment, op: Opening) -> Polygon:
    """Проём во всю толщину стены (с запасом — потом пересекается с куском стены)."""
    a, b = seg.point_at(op.offset), seg.point_at(op.offset + op.width)
    out = seg.outward * (seg.thickness * 2 + 10)
    return Polygon([p.as_tuple() for p in (a, b, b + out, a + out)])


def _walls(geoms: Sequence[RoomGeometry], ceiling: float) -> list[dict[str, Any]]:
    walls = _Walls()
    for g in geoms:
        for seg in g.contour.segments:
            key = f"wall:{g.room.id}.{seg.id}"
            quad = _wall_quad(g, seg)
            ops = [o for o in g.room.openings if o.wall == seg.id]
            strips = [_strip(seg, o).intersection(quad) for o in ops]
            walls.add(key, quad.difference(unary_union(strips)), (0.0, ceiling), seg.inward)
            for op, strip in zip(ops, strips, strict=True):
                for span in _opening_span(op, ceiling):
                    walls.add(key, strip, span, seg.inward)
    return walls.pieces


def _face(a: Anchor) -> Vec:
    """Место у грани стены (потолочная точка — сама точка)."""
    return a.pos if a.inward is None else a.pos + a.inward * WALL_GAP_MM


def _box_z(b: JunctionBox, ceiling: float) -> float:
    return b.rise_mm if b.route == "floor" else ceiling - b.rise_mm


def _wires(
    wiring: Wiring,
    ends: dict[str, Anchor],
    colors: dict[str, str],
    ceiling: float,
) -> dict[str, Any]:
    """Трассы в 3D: подъём от источника, путь по плану в плоскости потолка или пола, спуск."""
    paths = [list(r.path) for r in wiring.runs]
    for route in ("ceiling", "floor"):
        idx = [k for k, r in enumerate(wiring.runs) if r.route == route]
        segs = segments([wiring.runs[k].path for k in idx])
        offsets = lane_offsets(segs, PITCH_MM, float("inf"))
        for j, k in enumerate(idx):
            run = wiring.runs[k].path
            shifts = [offsets.get((j, i), 0.0) for i in range(len(run) - 1)]
            paths[k] = offset_path(run, shifts)
    out: dict[str, Any] = {}
    for r, path in zip(wiring.runs, paths, strict=True):
        start, end = _face(ends[r.source]), _face(ends[r.target])
        plan = fit_path(path, start, end) if len(path) >= 2 else [start, end]
        floor = r.route == "floor"
        plane = FLOOR_Z_MM if floor else ceiling
        z0 = r.rise_start_mm if floor else ceiling - r.rise_start_mm
        z1 = r.rise_end_mm if floor else ceiling - r.rise_end_mm
        pts = [_xyz(plan[0], max(z0, 0.0))]
        pts += [_xyz(p, plane) for p in plan]
        pts.append(_xyz(plan[-1], max(z1, 0.0)))
        clean = [p for k, p in enumerate(pts) if k == 0 or p != pts[k - 1]]
        out[r.id] = {
            "group": r.group,
            "color": colors.get(r.group, NO_COLOR),
            "route": r.route,
            "from": r.source,
            "to": r.target,
            "pts": clean,
        }
    return out


def build_scene(
    plan: Plan, contours: dict[str, Contour], elec: Electrical, wiring: Wiring
) -> dict[str, Any]:
    """Сцена для ключа `scene` страницы проводки .epd. Вызывать в масштабе листа
    (layers.drawing_scale): концы трасс — те же узлы, что на чертеже."""
    ceiling = plan.ceiling_height
    geoms = room_geometries(plan, contours)
    by_room = {g.room.id: g for g in geoms}
    colors = {g: f"#{c:06x}" for g, c in group_colors(elec).items()}
    anchors = {p.id: point_anchor(p, by_room) for p in elec.points}
    ends: dict[str, Anchor] = {**anchors, **{b.id: b.anchor for b in wiring.boxes}}
    if elec.board is not None:
        ends["board"] = board_anchor(elec.board, by_room)

    def inward(a: Anchor) -> list[float] | None:
        return None if a.inward is None else [round(a.inward.x, 6), round(a.inward.y, 6)]

    points = {}
    for p in elec.points:
        a = anchors[p.id]
        z = ceiling if p.ceiling is not None else float(p.height or 0.0)
        points[p.id] = {
            "pos": _xyz(_face(a), z),
            "inward": inward(a),
            "type": p.type.value,
            "group": p.group,
            "color": colors.get(p.group or "", NO_COLOR),
        }
    boxes = {
        b.id: {
            "pos": _xyz(_face(b.anchor), _box_z(b, ceiling)),
            "inward": inward(b.anchor),
            "label": b.label,
            "group": b.group,
        }
        for b in wiring.boxes
    }
    scene: dict[str, Any] = {
        "ceiling": ceiling,
        "assumed": {
            "ceiling": "ceiling_height" not in plan.model_fields_set,
            "openings": sorted(o.id for r in plan.rooms for o in r.openings if _assumed_opening(o)),
        },
        "floors": [
            {"key": f"room:{g.room.id}", "rings": [[_xy(v) for v in g.contour.vertices]]}
            for g in geoms
        ],
        "walls": _walls(geoms, ceiling),
        "wires": _wires(wiring, ends, colors, ceiling),
        "points": points,
        "boxes": boxes,
    }
    if elec.board is not None:
        a = ends["board"]
        scene["board"] = {"pos": _xyz(_face(a), elec.board.height), "inward": inward(a)}
    return scene
