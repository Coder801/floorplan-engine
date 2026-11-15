"""Electric floor heating zones (decision 2026-11-14, second step of the "Floor heating" section):
the heated area, the cable section from the series, the pitch and the serpentine, the floor
sensor and the cold lead to the controller.

1. Heated area: the floor of the room (or of its zone, `zone`), WALL_GAP from the walls, less the
   exclusions (`exclude`), the plumbing fixtures on the floor (`fixtures`: baths, trays,
   installations, WCs, washers — plumbing/floor_spots.py puts them in at the check, the
   electrical stage itself does not know plumbing) and the solid furniture from furniture.yaml
   (`furniture`, model/furniture.solid_spots; furniture on legs is not cut out). An `area` from
   the source is compared with it by the check.
2. Section length: from `length` (the source), otherwise the series length nearest to area ×
   density / linear power (density `density` or DEFAULT_DENSITY) among those that can be laid
   at a pitch of PITCH_MIN…PITCH_MAX; none can — the longest that is laid whole (a section is
   never cut), with a remark.
3. Pitch: by bisection, so the route takes the whole heating length; the route is cut at that
   length exactly (the far end of a two-core cable is an end sleeve and may be anywhere). The
   route geometry is electrical/heating_layout.py.
4. The cold lead runs from the controller down the wall, along the wall in the margin and into
   the start of the serpentine; it is not part of the heating length. The sensor goes in a
   conduit the same way, into the gap between two neighbouring runs, SENSOR_DEPTH deep. A
   controller in another room: down its wall and over the floor through the door openings
   (electrical/routing.Router, no drilled walls) into the zone; no way — the length is a straight
   line, with a remark.
5. The controller's load is the linear power × the section length, the sum of its zones
   (`with_heating`): the panel line and breaker are counted from it as before.
6. A controller no entry names gets a zone built by code (`auto`, electrical/heating_auto.py);
   `with_heating` adds such zones after the written ones.

Linear power, the length row (model/heating_catalog.py) and all constants here are
ASSUMPTIONS until a real series is in the catalogue; the sheet says so.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from itertools import accumulate, pairwise

from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from floorplan_engine.electrical.heating_auto import auto_heating
from floorplan_engine.electrical.heating_layout import (
    Serpentine,
    long_side_first,
    serpentine,
)
from floorplan_engine.electrical.routing import End, Router, free_area, simplify
from floorplan_engine.model.geometry import Contour, Vec, room_geometries
from floorplan_engine.model.heating_catalog import SERIES, HeatingSeries
from floorplan_engine.model.plumbing import TYPICAL_SPOT
from floorplan_engine.model.schema import (
    Electrical,
    ElectricalPoint,
    FloorHeating,
    HeatingExclude,
    Plan,
    PointType,
)
from floorplan_engine.model.zones import zone_outline

WALL_GAP = 100.0  # mm: no cable closer to the walls (assumption)
DEFAULT_DENSITY = 150.0  # W/m²: target density without `density` (assumption)
PITCH_MIN, PITCH_MAX = 120.0, 170.0  # mm: recommended pitch between runs
PITCH_MID = (PITCH_MIN + PITCH_MAX) / 2
# mm: a section this much shorter than the route at PITCH_MAX still fits (the last run is a little
# shorter, no remark about an uncovered floor of a few centimetres)
FIT_SLACK = 100.0
MIN_BEND_DIAMETERS = 6.0  # the smallest turn radius, cable diameters (assumption)
SENSOR_DEPTH = 500.0  # mm: the sensor tip this far into the zone (assumption)
LEAD_GAP = 50.0  # mm: the cold lead and the sensor conduit run this far from the wall face
EDGE_OUT = 40.0  # mm: and come into the zone from this far outside its edge
DIM_AWAY = 3  # the pitch dimension is this many run pairs away from the sensor
BISECT_STEPS = 40
MIN_PART_MM2 = 50_000.0  # pieces of the heated area smaller than this are dropped (0.05 m²)
AREA_TOLERANCE = 0.10  # the layout area may differ from the source `area` by this share


@dataclass(frozen=True)
class HeatingZone:
    """One `floor_heating` entry, computed. index is its place in electrical.yaml (the YAML
    path); remarks are warnings for the report, in Russian."""

    index: int
    spec: FloorHeating
    name: str  # room or zone name
    floor: BaseGeometry  # floor of the room or zone, model mm
    area: BaseGeometry  # heated area
    blocked: tuple[BaseGeometry, ...]  # exclusions and fixtures inside the floor
    series: HeatingSeries
    density: float  # target, W/m²
    length: float  # heating section, m
    pitch: float | None = None
    route: Serpentine | None = None  # cut at the section length
    lead: tuple[Vec, ...] = ()  # cold lead on the floor: from the wall to the serpentine start
    lead_m: float = 0.0  # its whole length with the drop from the controller, m
    sensor: tuple[Vec, ...] = ()  # sensor conduit on the floor, ends at the sensor
    sensor_m: float = 0.0  # its whole length with the drop, m
    gap_dim: tuple[Vec, Vec] | None = None  # one pitch between two runs, for the sheet
    remarks: tuple[str, ...] = field(default=())
    furniture: tuple[str, ...] = ()  # ids of the solid furniture cut out of this floor
    typical: tuple[str, ...] = ()  # ids of the fixtures cut out by their typical size

    @property
    def floor_m2(self) -> float:
        return float(self.floor.area) / 1e6

    @property
    def area_m2(self) -> float:
        return float(self.area.area) / 1e6

    @property
    def power(self) -> float:
        """Heating power, W."""
        return self.series.watts_per_m * self.length

    @property
    def real_density(self) -> float:
        """W/m² of the heated area with the chosen section."""
        return self.power / self.area_m2 if self.area_m2 > 0 else 0.0

    @property
    def laid_m(self) -> float:
        return self.route.length / 1000 if self.route is not None else 0.0

    @property
    def density_assumed(self) -> bool:
        return self.spec.density is None

    @property
    def length_assumed(self) -> bool:
        return self.spec.length is None

    @property
    def area_off(self) -> bool:
        """The layout area differs from the source `area` by more than AREA_TOLERANCE."""
        given = self.spec.area
        return given is not None and abs(self.area_m2 - given) > AREA_TOLERANCE * given


# --- Area --------------------------------------------------------------------------------------


def _rect(origin: tuple[float, float], ex: HeatingExclude) -> Polygon:
    x, y = origin[0] + ex.at[0], origin[1] + ex.at[1]
    return box(x, y, x + ex.size[0], y + ex.size[1])


def floor_outline(plan: Plan, contours: dict[str, Contour], fh: FloorHeating) -> list[Vec] | None:
    """Outline of the room floor or of its zone; None when the room or zone is not there."""
    room = next((r for r in plan.rooms if r.id == fh.room), None)
    if room is None or fh.room not in contours:
        return None
    contour = contours[fh.room]
    if fh.zone is None:
        return contour.vertices
    zone = next((z for z in room.zones if z.name == fh.zone), None)
    return zone_outline(contour, zone) if zone is not None else None


@dataclass(frozen=True)
class HeatedArea:
    """The floor of a zone, its heated area and what is cut out of it, model mm; furniture is the
    ids of the solid furniture among the cut-outs (notes "furniture.yaml: id"), typical — of the
    fixtures cut out by their typical size (TYPICAL_SPOT, an assumption)."""

    floor: BaseGeometry
    area: BaseGeometry
    blocked: tuple[BaseGeometry, ...]
    furniture: tuple[str, ...] = ()
    typical: tuple[str, ...] = ()  # fixtures cut out by their typical size (TYPICAL_SPOT)


def _cut_id(ex: HeatingExclude) -> str:
    return (ex.note or "").rpartition(": ")[2]


def heated_area(plan: Plan, contours: dict[str, Contour], fh: FloorHeating) -> HeatedArea | None:
    """The zone's floor less the wall gap and the cut-outs; None without the room or zone."""
    outline = floor_outline(plan, contours, fh)
    if outline is None or len(outline) < 3:
        return None
    room = next(r for r in plan.rooms if r.id == fh.room)
    floor = Polygon([v.as_tuple() for v in outline]).buffer(0)
    blocked: list[BaseGeometry] = []
    furniture: list[str] = []
    typical: list[str] = []
    # Each cut-out with the list its id goes to when it really stands on this floor
    tagged = [
        *((ex, None) for ex in fh.exclude),
        *(
            (ex, typical if (ex.note or "").startswith(TYPICAL_SPOT) else None)
            for ex in fh.fixtures
        ),
        *((ex, furniture) for ex in fh.furniture),
    ]
    for ex, named in tagged:
        b = _rect(room.origin, ex).intersection(floor)
        if b.is_empty:
            continue
        blocked.append(b)
        if named is not None and b.area > 1.0:
            named.append(_cut_id(ex))
    inner: BaseGeometry = floor.buffer(-WALL_GAP, join_style="mitre")
    for b in blocked:
        inner = inner.difference(b.buffer(WALL_GAP, join_style="mitre"))
    parts = [p for p in getattr(inner, "geoms", [inner]) if p.area >= MIN_PART_MM2]
    area = unary_union(parts) if parts else Polygon()
    return HeatedArea(floor, area, tuple(blocked), tuple(furniture), tuple(typical))


# --- Length and pitch ---------------------------------------------------------------------------


def _bisect(needed: Callable[[float], float], length_mm: float) -> float:
    """Pitch at which the route is at least the cable long and as sparse as possible: the cable
    is cut there and ends in the last run (the needed length is a sawtooth: shorter rows mean
    fewer turns, more rows at a jump)."""
    lo, hi = PITCH_MIN, PITCH_MAX
    for _ in range(BISECT_STEPS):
        mid = (lo + hi) / 2
        if needed(mid) >= length_mm:
            lo = mid
        else:
            hi = mid
    return lo


def choose_length(
    area_m2: float,
    density: float,
    series: HeatingSeries,
    shortest: float,
    longest: float,
) -> tuple[float, bool]:
    """Section length from the series, m, and whether it can be laid at PITCH_MIN…PITCH_MAX:
    shortest and longest are the route lengths at PITCH_MAX and PITCH_MIN, mm. Among the lengths
    that fit — the nearest to area × density / linear power. None fits — the longest that is
    laid whole (a heating section is never cut: a leftover cable cannot go anywhere, a part of the
    floor without cable can), and only when even the shortest one is too long — the shortest."""
    target = area_m2 * density / series.watts_per_m
    order = sorted(series.lengths, key=lambda m: (abs(m - target), m))
    fitting = next((m for m in order if shortest - FIT_SLACK <= m * 1000 <= longest), None)
    if fitting is not None:
        return fitting, True
    whole = [m for m in series.lengths if m * 1000 <= longest]
    return (max(whole) if whole else min(series.lengths)), False


# --- Leads ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Wall:
    at: Vec  # the controller on the wall face
    inward: Vec
    along: Vec
    height: float  # mm from the floor
    same_room: bool


# A way over the floor to a target, entering along out (floor_way); None — no way
FloorWay = Callable[[Vec, Vec], list[Vec] | None]


def _lead(w: _Wall, target: Vec, out: Vec) -> list[Vec]:
    """From the controller along the wall (LEAD_GAP from it) and into target from outside the
    zone along out (unit, pointing out of the zone): right angles only."""
    p0 = w.at + w.inward * LEAD_GAP
    outside = target + out * EDGE_OUT
    corner = p0 + w.along * (outside - p0).dot(w.along)
    path = [w.at, p0, corner, outside, target]
    return [p for k, p in enumerate(path) if k == 0 or (p - path[k - 1]).length() > 1e-6]


def _length(path: Sequence[Vec]) -> float:
    return sum((b - a).length() for a, b in pairwise(path))


def _sensor(
    route: Serpentine, laid_mm: float, w: _Wall, way: FloorWay | None = None
) -> tuple[list[Vec], tuple[Vec, Vec] | None]:
    """Sensor conduit into the gap between two laid neighbouring runs nearest the controller,
    and the pitch dimension on a pair nearest the middle, at least DIM_AWAY pairs from the
    sensor (their labels must not meet). way is for a controller in another room: the conduit
    goes over the floor through the door (floor_way)."""
    visits = route.visits
    r = route.pitch / 2
    ends = list(accumulate(p.length for p in route.pieces))
    # Run i is piece 2i; a pair counts when the second run is laid whole
    laid = [i for i in range(len(visits) - 1) if ends[min(2 * i + 2, len(ends) - 1)] <= laid_mm]
    if not laid:
        return [], None
    best: tuple[float, list[Vec], int] | None = None
    for i in laid:
        a, b = visits[i], visits[i + 1]
        if abs(b.v - a.v) < 1e-6:
            continue
        sign = 1.0 if a.u1 >= a.u0 else -1.0  # run i goes this way from the open side
        edge = min(a.u0, b.u1) if sign > 0 else max(a.u0, b.u1)
        u_edge = edge - sign * r
        depth = min(SENSOR_DEPTH, abs(a.u1 - a.u0) / 2, abs(b.u1 - b.u0) / 2)
        v = (a.v + b.v) / 2
        entry, tip = route.xy(u_edge, v), route.xy(u_edge + sign * (r + depth), v)
        out = Vec(-sign, 0.0) if route.along_x else Vec(0.0, -sign)
        if way is not None:
            found = way(entry, out)
            if found is None:
                continue
            path = [*found, tip]
        else:
            path = [*_lead(w, entry, out), tip]
        d = (entry - w.at).length()
        if best is None or d < best[0] - 1e-6:
            best = (d, path, i)
    centre = laid[len(laid) // 2]
    away = [i for i in laid if best is None or abs(i - best[2]) >= DIM_AWAY]
    mid = min(away, key=lambda i: (abs(i - centre), i)) if away else centre
    a, b = visits[mid], visits[mid + 1]
    lo = max(min(a.u0, a.u1), min(b.u0, b.u1))
    hi = min(max(a.u0, a.u1), max(b.u0, b.u1))
    dim = None
    if hi > lo:
        u = lo + (hi - lo) / 3
        dim = (route.xy(u, a.v), route.xy(u, b.v))
    return (best[1] if best is not None else []), dim


# --- Zones ---------------------------------------------------------------------------------------


def _controller(
    plan: Plan, contours: dict[str, Contour], fh: FloorHeating, points: Sequence[ElectricalPoint]
) -> _Wall | None:
    p = next((p for p in points if p.id == fh.thermostat), None)
    if p is None or p.wall is None or p.offset is None or p.room not in contours:
        return None
    try:
        seg = contours[p.room].segment(p.wall)
    except StopIteration:
        return None
    return _Wall(
        seg.point_at(p.offset), seg.inward, seg.direction, p.height or 0.0, p.room == fh.room
    )


def floor_way(plan: Plan, contours: dict[str, Contour], w: _Wall) -> FloorWay:
    """Ways from a controller in another room: off its wall, over the floor through door openings
    (CLEARANCE from walls, routing.Router; one search for all targets) and into a target from
    outside the zone along out (unit, out of the zone); None when there is no way."""
    geoms = room_geometries(plan, contours)
    p0 = w.at + w.inward * LEAD_GAP
    router = Router(free_area(geoms), End(p0, abs(w.along.x) < 0.5))

    def way(target: Vec, out: Vec) -> list[Vec] | None:
        end = End(target + out * EDGE_OUT, abs(out.x) > 0.5)
        if router.cost(end.node) == float("inf"):
            return None
        return simplify([w.at, *router.route(end), target])

    return way


def _zone_name(plan: Plan, fh: FloorHeating) -> str:
    room = next((r for r in plan.rooms if r.id == fh.room), None)
    return fh.zone or (room.name if room is not None else fh.room)


def _layout(area: BaseGeometry, near: Vec | None) -> Callable[[float], Serpentine | None]:
    """Route at a pitch with the run direction that covers the most cells at the middle pitch
    (along the long side first)."""
    best: tuple[int, int, bool] | None = None
    for k, along_x in enumerate(long_side_first(area)):
        s = serpentine(area, PITCH_MID, along_x, near)
        if s is None:
            continue
        key = (s.cells - s.covered, k, along_x)
        if best is None or key[:2] < best[:2]:
            best = key
    along = best[2] if best is not None else long_side_first(area)[0]
    return lambda pitch: serpentine(area, pitch, along, near)


def heating_zone(
    plan: Plan,
    contours: dict[str, Contour],
    index: int,
    fh: FloorHeating,
    points: Sequence[ElectricalPoint],
) -> HeatingZone | None:
    """One zone computed; None when its room or zone is not in the plan (the check says so)."""
    found = heated_area(plan, contours, fh)
    if found is None:
        return None
    area = found.area
    series = SERIES[fh.series]
    density = fh.density if fh.density is not None else DEFAULT_DENSITY
    area_m2 = float(area.area) / 1e6
    base = HeatingZone(
        index,
        fh,
        _zone_name(plan, fh),
        found.floor,
        area,
        found.blocked,
        series,
        density,
        fh.length or 0.0,
        furniture=found.furniture,
        typical=found.typical,
    )
    remarks: list[str] = []
    if area.is_empty:
        remarks.append(
            "площадь обогрева пустая: зона уже отступов от стен "
            f"({WALL_GAP:g} мм), exclude, сантехприборов (plumbing.yaml) и глухой мебели "
            "(furniture.yaml) — кабель не раскладывается"
        )
        return replace(base, remarks=tuple(remarks))
    wall = _controller(plan, contours, fh, points)
    route_at = _layout(area, wall.at if wall is not None else None)

    def needed(pitch: float) -> float:
        s = route_at(pitch)
        return s.length if s is not None else 0.0

    shortest, longest = needed(PITCH_MAX), needed(PITCH_MIN)
    if fh.length is not None:
        length, fits = fh.length, shortest - FIT_SLACK <= fh.length * 1000 <= longest
    else:
        length, fits = choose_length(area_m2, density, series, shortest, longest)
    length_mm = length * 1000
    if length_mm > longest:
        pitch = PITCH_MIN
    elif length_mm < shortest:
        pitch = PITCH_MAX
    else:
        pitch = _bisect(needed, length_mm)
    full = route_at(pitch)
    assert full is not None
    route = full.truncated(length_mm)
    if not fits:
        remarks.append(_misfit(fh, length, length_mm, shortest, longest))
    if full.covered < full.cells:
        remarks.append(
            f"одной змейкой покрыта не вся зона: {full.covered} из {full.cells} участков — "
            "разбейте зону на две записи floor_heating или поправьте exclude"
        )
    if pitch / 2 < MIN_BEND_DIAMETERS * series.diameter_mm:
        remarks.append(
            f"радиус поворота {pitch / 2:.0f} мм меньше {MIN_BEND_DIAMETERS:g} диаметров кабеля "
            f"({MIN_BEND_DIAMETERS * series.diameter_mm:.0f} мм)"
        )
    zone = replace(base, length=length, pitch=pitch, route=route)
    if wall is None:
        return replace(zone, remarks=tuple(remarks))
    if not wall.same_room:
        to_zone = floor_way(plan, contours, wall)
        lead_way = to_zone(route.start, route.start_out)
        if lead_way is None:
            lead_m = (wall.height + (route.start - wall.at).length()) / 1000
            remarks.append(
                "регулятор в другом помещении, а пути по полу через дверь нет: подводка и "
                "гофра датчика не нарисованы, их длина — по прямой (допущение)"
            )
            return replace(
                zone, lead_m=lead_m, sensor_m=lead_m + SENSOR_DEPTH / 1000, remarks=tuple(remarks)
            )
        sensor, dim = _sensor(full, route.length, wall, to_zone)
        return replace(
            zone,
            lead=tuple(lead_way[1:]),
            lead_m=(wall.height + _length(lead_way)) / 1000,
            sensor=tuple(sensor[1:]),
            sensor_m=(wall.height + _length(sensor)) / 1000 if sensor else 0.0,
            gap_dim=dim,
            remarks=tuple(remarks),
        )
    lead = _lead(wall, route.start, route.start_out)
    sensor, dim = _sensor(full, route.length, wall)
    return replace(
        zone,
        lead=tuple(lead[1:]),
        lead_m=(wall.height + _length(lead)) / 1000,
        sensor=tuple(sensor[1:]),
        sensor_m=(wall.height + _length(sensor)) / 1000 if sensor else 0.0,
        gap_dim=dim,
        remarks=tuple(remarks),
    )


def _misfit(
    fh: FloorHeating, length: float, length_mm: float, shortest: float, longest: float
) -> str:
    """Remark: the section cannot be laid at PITCH_MIN…PITCH_MAX."""
    pitches = f"{PITCH_MIN:g}–{PITCH_MAX:g} мм"
    if length_mm > longest:
        extra = f"не уложено {(length_mm - longest) / 1000:.1f} м"
        if fh.length is not None:
            return (
                f"длина из источника {length:g} м не помещается при шаге {PITCH_MIN:g} мм: "
                f"{extra} — нужна секция короче или площадь больше"
            )
        return f"из ряда серии нет длины с шагом {pitches}: взята {length:g} м, {extra}"
    bare = f"без кабеля ~{(shortest - length_mm) / 1000:.1f} м трассы"
    if fh.length is not None:
        return (
            f"длины из источника {length:g} м не хватает на зону при шаге {PITCH_MAX:g} мм: {bare}"
        )
    return f"из ряда серии нет длины с шагом {pitches}: взята {length:g} м, {bare}"


_CACHE: dict[str, tuple[HeatingZone, ...]] = {}
# The controller's fields the layout reads (_controller): its wall place and room
LAYOUT_FIELDS = {"id", "room", "wall", "offset", "height"}
_CACHE_SIZE = 64


def heating_zones(
    plan: Plan, contours: dict[str, Contour], elec: Electrical
) -> tuple[HeatingZone, ...]:
    """All zones of electrical.yaml that the plan has, in order. The same model gives the same
    zones; the result is cached by the model (the check, the sheet and the estimate all ask)."""
    if not elec.floor_heating:
        return ()
    ids = {fh.thermostat for fh in elec.floor_heating}
    regs = [p for p in elec.points if p.id in ids]
    # Only what the layout reads: the controllers' place, not their power (with_heating sets it
    # from these very zones, and the check, the sheet and the estimate ask again after it)
    key = json.dumps(
        [
            plan.model_dump(mode="json"),
            [fh.model_dump(mode="json") for fh in elec.floor_heating],
            [p.model_dump(mode="json", include=LAYOUT_FIELDS) for p in regs],
        ],
        sort_keys=True,
    )
    if key not in _CACHE:
        if len(_CACHE) >= _CACHE_SIZE:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = tuple(
            z
            for k, fh in enumerate(elec.floor_heating)
            if (z := heating_zone(plan, contours, k, fh, regs)) is not None
        )
    return _CACHE[key]


def heating_power(zones: Sequence[HeatingZone]) -> dict[str, float]:
    """Controller id → power of its zones, W."""
    out: dict[str, float] = {}
    for z in zones:
        out[z.spec.thermostat] = out.get(z.spec.thermostat, 0.0) + z.power
    return out


def with_heating(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical,
    spots: dict[str, list[HeatingExclude]] | None = None,
    furniture: dict[str, list[HeatingExclude]] | None = None,
) -> Electrical:
    """The model with the zones built by code for the controllers no entry names (heating_auto,
    after the written ones), the fixture spots (room id → rectangles from plumbing.yaml) and the
    solid furniture (room id → rectangles from furniture.yaml) in its zones, and the zones' power
    on their controllers (only where the point has no `power` of its own)."""
    auto = auto_heating(plan, elec).zones
    if auto:
        elec = elec.model_copy(update={"floor_heating": [*elec.floor_heating, *auto]})
    if not elec.floor_heating:
        return elec
    if spots or furniture:
        elec = elec.model_copy(
            update={
                "floor_heating": [
                    fh.model_copy(
                        update={
                            "fixtures": [*fh.fixtures, *(spots or {}).get(fh.room, [])],
                            "furniture": [*fh.furniture, *(furniture or {}).get(fh.room, [])],
                        }
                    )
                    for fh in elec.floor_heating
                ]
            }
        )
    power = heating_power(heating_zones(plan, contours, elec))
    points = [
        p.model_copy(update={"power": round(power[p.id], 1)})
        if p.id in power and p.power is None and p.type is PointType.THERMOSTAT
        else p
        for p in elec.points
    ]
    return elec.model_copy(update={"points": points})
