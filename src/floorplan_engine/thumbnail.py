"""Превью плана для карточки проекта: SVG из модели, не из DXF.

Помещения — заливкой по внутреннему контуру, стены — общий силуэт (те же куски стен, что
на плане, с разрывами проёмов), окна — линией по середине стены. Цвета не задаются: у
фигур классы `room`, `wet`, `wall`, `window`, их красит страница (светлая и тёмная тема).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from shapely import unary_union
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from floorplan_engine.draw_plan import room_geometries, wall_pieces
from floorplan_engine.geometry import Contour, Vec
from floorplan_engine.schema import OpeningType, Plan

PREVIEW_FILE = "preview.svg"
PAD_MM = 300  # поле вокруг плана


def _y(y: float) -> str:
    """y в SVG: ось вниз — план переворачивается (0.0 - y, а не -y: без «-0»)."""
    return f"{0.0 - y:.0f}"


def _ring(points: Iterable[Sequence[float]]) -> str:
    """Замкнутый контур пути SVG."""
    pts = [f"{p[0]:.0f} {_y(p[1])}" for p in points]
    return "M" + " L".join(pts) + " Z"


def _polygons(geom: BaseGeometry) -> list[Polygon]:
    if isinstance(geom, Polygon):
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]


def _path(geom: BaseGeometry) -> str:
    """Многоугольники с дырами — один путь (правило заливки evenodd)."""
    rings: list[str] = []
    for poly in _polygons(geom):
        rings.append(_ring(poly.exterior.coords[:-1]))
        rings += [_ring(hole.coords[:-1]) for hole in poly.interiors]
    return " ".join(rings)


def _box(points: Sequence[Vec]) -> tuple[float, float, float, float]:
    xs, ys = [p.x for p in points], [p.y for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def plan_thumbnail(plan: Plan, contours: dict[str, Contour]) -> str:
    """SVG-превью плана в мм модели; размер задаёт страница (viewBox по плану)."""
    geoms = room_geometries(plan, contours)
    walls = unary_union([p.polygon for g in geoms for p in wall_pieces(g)])
    outline = [v for g in geoms for v in (*g.contour.vertices, *g.corners)]
    x0, y0, x1, y1 = _box(outline)
    w, h = x1 - x0 + 2 * PAD_MM, y1 - y0 + 2 * PAD_MM
    view = f"{x0 - PAD_MM:.0f} {-y1 - PAD_MM:.0f} {w:.0f} {h:.0f}"
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}">']
    for g in geoms:
        cls = "room wet" if g.room.wet else "room"
        parts.append(f'<path class="{cls}" d="{_ring(v.as_tuple() for v in g.contour.vertices)}"/>')
    parts.append(f'<path class="wall" fill-rule="evenodd" d="{_path(walls)}"/>')
    for g in geoms:
        for op in g.room.openings:
            if op.type is not OpeningType.WINDOW:
                continue
            seg = g.contour.segment(op.wall)
            mid = seg.outward * (seg.thickness / 2)
            a, b = seg.point_at(op.offset) + mid, seg.point_at(op.offset + op.width) + mid
            ends = f'x1="{a.x:.0f}" y1="{_y(a.y)}" x2="{b.x:.0f}" y2="{_y(b.y)}"'
            parts.append(f'<line class="window" {ends}/>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
