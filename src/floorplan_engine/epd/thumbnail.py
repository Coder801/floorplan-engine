"""Plan preview for the project card: SVG from the model, not from the DXF.

Rooms are filled along the inner outline, walls are the shared silhouette (the same wall
pieces as on the plan, with gaps for openings), windows are a line along the wall middle.
No colours are set: shapes get classes `room` and the room kind (`room_kind`: `wet`,
`kitchen`, `outdoor`, `service`, `living`), `wall`, `window`; the page colours them (light
and dark theme).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from shapely import unary_union
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from floorplan_engine.drawing.plan import wall_pieces
from floorplan_engine.model.geometry import Contour, Vec, room_geometries
from floorplan_engine.model.schema import OpeningType, Plan

PREVIEW_FILE = "preview.svg"
PAD_MM = 300  # margin around the plan

# Room kind by name (ru / uk), only for the preview colour: not used in calculations.
# Wet rooms by the wet flag, not by name: a bathroom without wet shows up as a data gap
ROOM_WORDS: dict[str, tuple[str, ...]] = {
    "outdoor": ("балкон", "лоджи", "лоджі", "терас"),
    "kitchen": ("кухн", "кухон"),
    "living": (
        "зал", "вітальн", "гостин", "спальн", "кабінет", "кабинет", "дитяч", "детск",
        "їдальн", "столов", "кімнат", "комнат",
    ),
    "service": (
        "коридор", "прихож", "передпок", "хол", "тамбур", "комор", "кладов", "гардероб",
        "техн", "постироч",
    ),
}  # fmt: skip


def room_kind(name: str, wet: bool) -> str:
    """Room kind for the preview: wet by the flag; otherwise by the word that comes first in the
    name ("Кухня-вітальня, коридор" is a kitchen, "Зал + коридор" is living); unknown means
    living."""
    if wet:
        return "wet"
    low = name.lower()
    found = [
        (low.find(word), kind)
        for kind, words in ROOM_WORDS.items()
        for word in words
        if word in low
    ]
    return min(found)[1] if found else "living"


def _y(y: float) -> str:
    """y in SVG: the axis points down, so the plan is flipped (0.0 - y, not -y: avoids "-0")."""
    return f"{0.0 - y:.0f}"


def _ring(points: Iterable[Sequence[float]]) -> str:
    """Closed contour of an SVG path."""
    pts = [f"{p[0]:.0f} {_y(p[1])}" for p in points]
    return "M" + " L".join(pts) + " Z"


def _polygons(geom: BaseGeometry) -> list[Polygon]:
    if isinstance(geom, Polygon):
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]


def _path(geom: BaseGeometry) -> str:
    """Polygons with holes as one path (evenodd fill rule)."""
    rings: list[str] = []
    for poly in _polygons(geom):
        rings.append(_ring(poly.exterior.coords[:-1]))
        rings += [_ring(hole.coords[:-1]) for hole in poly.interiors]
    return " ".join(rings)


def _box(points: Sequence[Vec]) -> tuple[float, float, float, float]:
    xs, ys = [p.x for p in points], [p.y for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def plan_thumbnail(plan: Plan, contours: dict[str, Contour]) -> str:
    """SVG plan preview in model mm; the page sets the size (viewBox fits the plan)."""
    geoms = room_geometries(plan, contours)
    walls = unary_union([p.polygon for g in geoms for p in wall_pieces(g)])
    outline = [v for g in geoms for v in (*g.contour.vertices, *g.corners)]
    x0, y0, x1, y1 = _box(outline)
    w, h = x1 - x0 + 2 * PAD_MM, y1 - y0 + 2 * PAD_MM
    view = f"{x0 - PAD_MM:.0f} {-y1 - PAD_MM:.0f} {w:.0f} {h:.0f}"
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}">']
    for g in geoms:
        cls = f"room {room_kind(g.room.name, g.room.wet)}"
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
