"""Where floor heating cable does not go because of plumbing (decision 2026-11-14): obstacles on
the floor (installation frame, bath, shower tray, box, cabinet, column) by their outline, and the
fixtures standing on the floor (bath, shower, floor WC, washing and dish washers) by their
typical size at their wall (model/plumbing.FIXTURE_SIZES: an assumption, the note TYPICAL_SPOT
says so on the zone card; the obstacles are real). A spot is the bounding rectangle, mm from the
room origin.

The electrical stage does not know plumbing (plumbing sits above it): the check puts these
spots into the floor heating zones (`FloorHeating.fixtures`, electrical/floor_heating.with_heating)
before anything is counted.
"""

from __future__ import annotations

from shapely.geometry import Point, Polygon

from floorplan_engine.model.geometry import Contour, RoomGeometry, room_geometries
from floorplan_engine.model.plumbing import (
    FIXTURE_SIZES,
    TYPICAL_SPOT,
    Fixture,
    FixtureType,
    ObstacleType,
    Plumbing,
)
from floorplan_engine.model.schema import HeatingExclude, Plan
from floorplan_engine.model.texts import Language
from floorplan_engine.plumbing.context import obstacle_polygon
from floorplan_engine.plumbing.rules import FIXTURE_NAMES

# Fixtures on the floor: no heating cable under them
FLOOR_FIXTURES = frozenset(
    {
        FixtureType.BATH,
        FixtureType.SHOWER,
        FixtureType.WC,
        FixtureType.WASHER,
        FixtureType.DISHWASHER,
    }
)


# A fixture standing on an obstacle of its own kind: the obstacle is its real footprint, the
# typical size is not cut out again (a bath drawn along one wall with its mixer on another)
FOOTPRINTS: dict[FixtureType, frozenset[ObstacleType]] = {
    FixtureType.BATH: frozenset({ObstacleType.BATH}),
    FixtureType.SHOWER: frozenset({ObstacleType.SHOWER_TRAY}),
}
FOOTPRINT_REACH_MM = 50.0  # the fixture's wall point no farther than this from the obstacle


def _on_footprint(
    fx: Fixture, g: RoomGeometry, footprints: list[tuple[ObstacleType, Polygon]]
) -> bool:
    kinds = FOOTPRINTS.get(fx.type)
    if not kinds:
        return False
    try:
        at = Point(g.contour.segment(fx.wall).point_at(fx.offset).as_tuple())
    except StopIteration:
        return False
    return any(t in kinds and poly.distance(at) <= FOOTPRINT_REACH_MM for t, poly in footprints)


def _spot(g: RoomGeometry, bounds: tuple[float, float, float, float], note: str) -> HeatingExclude:
    ox, oy = g.room.origin
    x0, y0, x1, y1 = bounds
    return HeatingExclude(at=(x0 - ox, y0 - oy), size=(x1 - x0, y1 - y0), note=note)


def _fixture_bounds(fx: Fixture, g: RoomGeometry) -> tuple[float, float, float, float] | None:
    try:
        seg = g.contour.segment(fx.wall)
    except StopIteration:
        return None
    w, d = FIXTURE_SIZES[fx.type]
    mid = seg.point_at(fx.offset)
    a, b = mid - seg.direction * (w / 2), mid + seg.direction * (w / 2)
    pts = [a, b, a + seg.inward * d, b + seg.inward * d]
    return (
        min(p.x for p in pts),
        min(p.y for p in pts),
        max(p.x for p in pts),
        max(p.y for p in pts),
    )


def heating_spots(
    plan: Plan, contours: dict[str, Contour], plumbing: Plumbing
) -> dict[str, list[HeatingExclude]]:
    """Room id → rectangles without floor heating, in plumbing.yaml order: obstacles, then
    fixtures on the floor."""
    geoms = {g.room.id: g for g in room_geometries(plan, contours)}
    out: dict[str, list[HeatingExclude]] = {}
    footprints: dict[str, list[tuple[ObstacleType, Polygon]]] = {}
    for ob in plumbing.obstacles:
        g = geoms.get(ob.room)
        if g is None or (ob.wall is not None and ob.wall not in {s.id for s in g.contour.segments}):
            continue
        poly = obstacle_polygon(ob, g)
        out.setdefault(ob.room, []).append(_spot(g, poly.bounds, f"plumbing.yaml: {ob.id}"))
        footprints.setdefault(ob.room, []).append((ob.type, poly))
    for fx in plumbing.fixtures:
        g = geoms.get(fx.room)
        if g is None or fx.type not in FLOOR_FIXTURES:
            continue
        if _on_footprint(fx, g, footprints.get(fx.room, [])):
            continue
        bounds = _fixture_bounds(fx, g)
        if bounds is not None:
            out.setdefault(fx.room, []).append(_spot(g, bounds, f"{TYPICAL_SPOT}: {fx.id}"))
    return out


OBSTACLE_NAMES: dict[ObstacleType, dict[str, str]] = {
    ObstacleType.INSTALLATION: {"ru": "Инсталляция", "uk": "Інсталяція"},
    ObstacleType.BATH: FIXTURE_NAMES[FixtureType.BATH],
    ObstacleType.SHOWER_TRAY: {"ru": "Поддон", "uk": "Піддон"},
    ObstacleType.BOX: {"ru": "Короб", "uk": "Короб"},
    ObstacleType.CABINET: {"ru": "Тумба", "uk": "Тумба"},
    ObstacleType.COLUMN: {"ru": "Колонна", "uk": "Колона"},
}


def spot_names(plumbing: Plumbing, language: Language) -> dict[str, str]:
    """Fixture or obstacle id → what it is, for the labels of the cut-outs on the floor heating
    sheet; an `other` obstacle is named by its note, else by its id."""
    out = {fx.id: FIXTURE_NAMES[fx.type][language] for fx in plumbing.fixtures}
    for ob in plumbing.obstacles:
        names = OBSTACLE_NAMES.get(ob.type)
        out[ob.id] = names[language] if names else (ob.note or ob.id)
    return out
