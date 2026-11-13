"""Cable mounting for the installer: fixing norms and fixing spots along each line (decision
2026-11-11, the "Mounting" sheet).

Fixings are shot with a mounting gun: conduit gets a clip by conduit diameter, cable without
conduit a pad with a nail and a tie. Each straight piece of a route gets a fixing `offset` from
its ends (a bend, a box, a flush box, the panel) and between them evenly, no farther apart than
the step of its surface (ceiling, wall, floor). The estimate counts the same spots the sheet
draws, plus a reserve for misfires.

The norms are a profile (MountingNorms): the studio practice based on DBN, values from the
studio; a strict "by DBN" profile is added only with clause references from the document — no
value is made up.
"""

from __future__ import annotations

import itertools
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from floorplan_engine.electrical.bundles import bundles, segments
from floorplan_engine.electrical.chases import source_rises
from floorplan_engine.electrical.routing import APART
from floorplan_engine.electrical.wiring_model import Route, Run, Wiring
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.schema import Conduit, Electrical, PointType
from floorplan_engine.model.texts import Language

Surface = Literal["ceiling", "wall", "floor"]
SURFACES: tuple[Surface, ...] = ("ceiling", "wall", "floor")
# Cross-section, mm² → conduit Ø, mm. A flat 3×1.5 is up to 11.5 mm wide: it does not go in a
# Ø16, so it takes a Ø20 like 3×2.5 (studio data 2026-11-11, docs/mounting.md)
CONDUIT_SIZES = ((2.5, 20), (6.0, 25), (1e9, 32))
# A chain point's cable in and cable out in one conduit (Electrical.loop_conduit "shared"): by
# the larger cross-section, two cables fill a conduit to about 40 % up to Ø25 for 2×1.5 and Ø32
# for 2×2.5 (decision 2026-11-11)
PAIR_SIZES = ((1.5, 25), (1e9, 32))
# Inner Ø of a light PVC corrugated conduit by its outer Ø, mm (typical DKC, IEK), and how much of
# its inner cross-section cables may fill (decision 2026-11-13). Lines lying together on a
# stretch share a conduit up to that fill (conduits); the largest shared conduit is the largest
# size here. CONDUIT_SIZES and PAIR_SIZES give the same sizes as this fill
CONDUIT_INNER: dict[int, float] = {16: 10.7, 20: 14.1, 25: 18.3, 32: 24.3}
CONDUIT_FILL = 0.4
# Flat ВВГ-Пнг(А) by cross-section: thickness × width, mm, the upper bound of the studio sizes
# (docs/mounting.md, internal: not shown to clients)
FLAT_CABLE: dict[float, tuple[float, float]] = {
    1.5: (5.5, 11.5),
    2.5: (6.0, 13.0),
    4.0: (6.5, 15.0),
    6.0: (7.0, 16.5),
}
# Smallest bend radius of a conduit, mm: 3–4 outer diameters (IEK, DKC, Ruvinil), the upper bound
CONDUIT_BEND: dict[int, float] = {16: 65.0, 20: 80.0, 25: 100.0, 32: 130.0}
# Practical radius on the conduit axis by the cable inside, mm (studio, 2026-11-11)
CABLE_IN_CONDUIT_BEND: dict[float, float] = {1.5: 80.0, 2.5: 90.0, 4.0: 100.0, 6.0: 100.0}
AXIS_TOL_MM = 1.0  # a route piece closer than this to an axis is bundled (bundles.segments)
PAD = "cable_pad"  # estimate key of a pad for cable without conduit
CLIP = "conduit_clip"  # estimate key of a conduit clip, conduit_clip.<Ø>


@dataclass(frozen=True)
class MountingNorms:
    key: str
    steps: Mapping[Surface, float]  # mm: the largest gap between fixings by surface, bare cable
    conduit_steps: Mapping[Surface, float]  # mm: the same for conduit
    offset: float  # mm: from a bend, box, flush box or the panel to the nearest fixing
    bend_factor: float  # smallest flat cable bend radius, in cable widths (bent lying flat)
    bend_reserve: int  # free lanes left inside a bundle turn for cables added later
    reserve: float  # fixings lost to misfires and bent nails, share
    source: Mapping[Language, str]  # where the values come from, for the sheet

    def step(self, surface: Surface, in_conduit: bool) -> float:
        """The largest gap between fixings on this surface, in conduit or bare."""
        return (self.conduit_steps if in_conduit else self.steps)[surface]


# Studio practice (answers 2026-11-11): the overhead step is shorter, the conduit and the cable
# sag; in wall chases and on the floor under the screed a longer one holds
PRACTICE = MountingNorms(
    key="practice",
    steps={"ceiling": 300.0, "wall": 500.0, "floor": 500.0},
    # Conduit is stiffer: the studio fixes it every 450 mm overhead, 550 mm on a wall (2026-11-12)
    conduit_steps={"ceiling": 450.0, "wall": 550.0, "floor": 500.0},
    offset=50.0,
    bend_factor=10.0,
    bend_reserve=2,
    reserve=0.1,
    source={"ru": "практика студии на основе ДБН", "uk": "практика студії на основі ДБН"},
)
NORMS: dict[str, MountingNorms] = {PRACTICE.key: PRACTICE}


def cable_section(mark: str) -> float | None:
    """Conductor cross-section of a cable type, mm² ("3x2.5" → 2.5); None if unreadable."""
    m = re.search(r"[x×]\s*([\d.,]+)", mark)
    return float(m.group(1).replace(",", ".")) if m else None


def conduit_diameter(mark: str) -> int:
    """Conduit by cable type, mm: up to 2.5 mm² Ø20, up to 6 Ø25, larger Ø32; an unreadable
    type (low-voltage) gets Ø20."""
    section = cable_section(mark) or 2.5
    return next((d for limit, d in CONDUIT_SIZES if section <= limit), CONDUIT_SIZES[-1][1])


def pair_diameter(a: str, b: str) -> int:
    """Conduit of a chain pair, mm (PAIR_SIZES): by the larger cross-section of the two cable
    types; an unreadable type counts as 2.5 mm²."""
    section = max(cable_section(a) or 2.5, cable_section(b) or 2.5)
    return next(d for limit, d in PAIR_SIZES if section <= limit)


def cable_area(mark: str) -> float | None:
    """Cross-section a cable takes in a conduit, mm²: the ellipse of a flat cable (FLAT_CABLE,
    three cores), more cores in proportion; None for a cable without sizes."""
    section = cable_section(mark)
    size = FLAT_CABLE.get(section) if section is not None else None
    if size is None:
        return None
    cores = re.match(r"\s*(\d+)", mark)
    return math.pi / 4 * size[0] * size[1] * max(int(cores.group(1)) if cores else 3, 3) / 3


def shared_diameter(marks: Sequence[str]) -> int | None:
    """The smallest conduit the cables together fill to at most CONDUIT_FILL of its inner
    cross-section, mm; None if the largest one is not enough or a cable has no sizes."""
    areas = [cable_area(m) for m in marks]
    if not areas or any(a is None for a in areas):
        return None
    total = sum(a for a in areas if a is not None)
    for d, inner in sorted(CONDUIT_INNER.items()):
        if total <= CONDUIT_FILL * math.pi / 4 * inner**2 + 1e-9:
            return d
    return None


def conduits(runs: Sequence[Run]) -> list[tuple[int, tuple[str, ...]]]:
    """Conduits of lines lying together on one stretch, (Ø, line ids), decision 2026-11-13:
    power cables share a conduit while they fill it to at most CONDUIT_FILL (shared_diameter),
    the thickest first, each into the first conduit it fits; a 12 V LED line from the panel lies
    with the power cables (Run.lay). An internet or TV cable and a cable without sizes go in a
    conduit of their own (conduit_diameter)."""
    bins: list[tuple[str, list[int]]] = []  # kind of the lines and their indices in runs
    alone: list[int] = []
    areas = [cable_area(r.mark) for r in runs]
    order = sorted(range(len(runs)), key=lambda k: (-(areas[k] or 0.0), k))
    for k in order:
        r = runs[k]
        if areas[k] is None or (r.circuit == "low" and not r.led):
            alone.append(k)
            continue
        kind = r.lay
        for other, inside in bins:
            marks = [runs[j].mark for j in (*inside, k)]
            if other == kind and shared_diameter(marks) is not None:
                inside.append(k)
                break
        else:
            bins.append((kind, [k]))
    groups = [sorted(inside) for _, inside in bins] + [[k] for k in alone]
    out: list[tuple[int, tuple[str, ...]]] = []
    for group in sorted(groups):
        marks = [runs[k].mark for k in group]
        d = shared_diameter(marks) if len(group) > 1 else None
        out.append((d or conduit_diameter(marks[0]), tuple(runs[k].id for k in group)))
    return out


@dataclass(frozen=True)
class ConduitPiece:
    """A stretch of conduit that lines share (or one line has): on the ceiling or the floor a
    bundle piece, on a wall the rise from the panel or the low-voltage cabinet."""

    diameter: int
    length: float  # mm
    runs: tuple[str, ...]
    surface: Surface


def plan_conduits(wiring: Wiring, conduit: Conduit) -> list[ConduitPiece]:
    """Conduit on the ceiling and on the floor (on the floor always, on the ceiling as chosen):
    on each bundle piece (a piece of a line where the set of cables does not change,
    electrical/bundles.bundles) the lines are packed into conduits; what a line has outside the
    bundles (a slanted piece) is in a conduit of its own."""
    out: list[ConduitPiece] = []
    for route in ("ceiling", "floor"):
        if not (route == "floor" or conduit in ("ceiling", "walls")):
            continue
        runs = [r for r in wiring.runs if r.route == route]
        surface: Surface = "floor" if route == "floor" else "ceiling"
        covered = [0.0] * len(runs)
        for b in bundles(segments([r.path for r in runs]), {}):
            for k in b.runs:
                covered[k] += b.length
            for d, ids in conduits([runs[k] for k in b.runs]):
                out.append(ConduitPiece(d, b.length, ids, surface))
        for r, mm in zip(runs, covered, strict=True):
            if r.plan_mm - mm > AXIS_TOL_MM:
                out.append(ConduitPiece(conduit_diameter(r.mark), r.plan_mm - mm, (r.id,), surface))
    return out


def source_conduits(wiring: Wiring, conduit: Conduit) -> list[ConduitPiece]:
    """Conduit on the rise from the panel and from the low-voltage cabinet (floor routes always,
    ceiling routes with conduit in the walls): the lines of one chase (chases.source_rises) are
    packed into conduits."""
    out: list[ConduitPiece] = []
    for source in ("board", "media"):
        for same in source_rises(wiring.runs, source):
            if same[0].route == "floor" or conduit == "walls":
                for d, ids in conduits(same):
                    out.append(ConduitPiece(d, same[0].rise_start_mm, ids, "wall"))
    return out


def shared_pairs(wiring: Wiring) -> dict[str, Run]:
    """Chain pairs in one conduit: the line coming into a point → the line going out of it, whose
    rise goes in the conduit of the first (Wiring.shared_rises)."""
    coming = {r.target: r for r in wiring.runs}
    return {
        coming[r.source].id: r
        for r in wiring.runs
        if r.id in wiring.shared_rises and r.source in coming
    }


@dataclass(frozen=True)
class BendSize:
    """How a line takes a turn: lane width across the bundle and its own smallest radius, mm."""

    width: float
    radius: float


def bend_size(mark: str, in_conduit: bool, norms: MountingNorms = PRACTICE) -> BendSize | None:
    """Conduit: its diameter, the radius of the conduit or of the cable inside, whichever is
    larger. Flat cable lying flat (studio practice): its width, bend_factor widths. None for a
    cable without sizes (low voltage, LED): the radius is the manufacturer's."""
    section = cable_section(mark)
    if in_conduit:
        d = conduit_diameter(mark)
        inside = CABLE_IN_CONDUIT_BEND.get(section, 0.0) if section is not None else 0.0
        return BendSize(float(d), max(CONDUIT_BEND[d], inside))
    if section is None or section not in FLAT_CABLE:
        return None
    width = FLAT_CABLE[section][1]
    return BendSize(width, norms.bend_factor * width)


def bundle_radii(lines: Sequence[BendSize], norms: MountingNorms = PRACTICE) -> list[float]:
    """Radii of a bundle turn, inner line first (studio rule 2026-11-11): the inner line is the
    reference, its smallest radius stays free for bend_reserve lanes of its width (cables added
    later), each next line goes out by half its width and half the previous one (axis to axis);
    a line never gets less than its own smallest radius."""
    out: list[float] = []
    r = 0.0
    for k, line in enumerate(lines):
        if k == 0:
            r = line.radius + norms.bend_reserve * line.width
        else:
            r += (lines[k - 1].width + line.width) / 2
        r = max(r, line.radius)
        out.append(r)
    return out


def fixing_key(run: Run, in_conduit: bool) -> str:
    """Estimate item of a fixing: a clip by conduit diameter, or a pad."""
    return f"{CLIP}.{conduit_diameter(run.mark)}" if in_conduit else PAD


def spots(length: float, step: float, offset: float) -> list[float]:
    """Fixings along a straight piece, mm from its start: the first and last `offset` from the
    ends, between them evenly no farther apart than `step`. A piece up to 2·offset gets one in
    the middle; one shorter than offset gets none (the neighbours' fixings hold it)."""
    if length < offset or length <= 0:
        return []
    if length <= 2 * offset:
        return [length / 2]
    inner = length - 2 * offset
    n = max(1, math.ceil(inner / step - 1e-9))
    return [offset + inner * k / n for k in range(n + 1)]


@dataclass(frozen=True)
class Fixing:
    """One fixing of a line. A plan fixing (ceiling or floor) lies on piece `piece` of the route,
    `at` mm from its start; a wall one (piece None) is on a rise, `at` mm from its top."""

    surface: Surface
    in_conduit: bool
    piece: int | None
    at: float
    pair: bool = False  # on the conduit of a chain pair (shared_pairs): a clip of pair_diameter


def fixing_spans(run: Run, conduit: Conduit) -> list[tuple[bool, Surface, float]]:
    """Fixed stretches of a line: (in conduit, surface, mm). The plan part lies on the ceiling
    or, for a floor route, on the floor; the rises go along the walls; the ends inside boxes and
    the panel are not fixed. In conduit: on the floor always, on the ceiling as chosen, the
    rises with conduit in the walls (estimate.conduit_mm)."""
    on_floor = run.route == "floor"
    plan_in = on_floor or conduit in ("ceiling", "walls")
    wall_in = on_floor or conduit == "walls"
    return [
        (plan_in, "floor" if on_floor else "ceiling", run.plan_mm),
        (wall_in, "wall", run.rise_start_mm),
        (wall_in, "wall", run.rise_end_mm),
    ]


def run_fixings(
    run: Run,
    conduit: Conduit,
    norms: MountingNorms = PRACTICE,
    *,
    inside: bool = False,
    pair: bool = False,
) -> list[Fixing]:
    """Fixings of a line: along each piece of the plan route, then along each rise. A chain pair
    in one conduit (shared_pairs) is fixed once: the line going out (inside) has none on its
    first rise, the clips of the line coming in hold both (pair)."""
    out: list[Fixing] = []
    (plan_in, plane, _), (start_in, wall, start), (end_in, _, end) = fixing_spans(run, conduit)
    rises = [(end_in, wall, end, pair)]
    if not (inside and start_in):
        rises.insert(0, (start_in, wall, start, False))
    for i, (a, b) in enumerate(itertools.pairwise(run.path)):
        length = (b - a).length()
        out += [
            Fixing(plane, plan_in, i, d)
            for d in spots(length, norms.step(plane, plan_in), norms.offset)
        ]
    for wall_in, surface, mm, paired in rises:
        out += [
            Fixing(surface, wall_in, None, d, paired and wall_in)
            for d in spots(mm, norms.step(surface, wall_in), norms.offset)
        ]
    return out


@dataclass(frozen=True)
class PlanFixing:
    """A fixing spot on the ceiling or the floor (decision 2026-11-12): one line across the
    bundle — the conduit clips of the cables snap together by their groove, the pads stand side
    by side — so a bundle is fixed at one spot with one clip or pad per line. at is the spot on
    the bundle axis, along the line direction; runs are the line ids held there. A slanted piece
    (routing.any_angle) is not bundled: one line, axis None."""

    route: Route
    at: Vec
    along: Vec
    runs: tuple[str, ...]
    axis: str | None = None  # "h" / "v": the bundle line; fixed is its coordinate across
    fixed: float = 0.0
    first: bool = True  # the first spot of its bundle piece: the number of fixings is signed here
    # Fixings at the spot by estimate item: a pad per bare cable, a clip per conduit (lines that
    # share a conduit have one, conduits)
    keys: tuple[str, ...] = ()


def plan_fixings(
    wiring: Wiring, conduit: Conduit, norms: MountingNorms = PRACTICE
) -> list[PlanFixing]:
    """Fixing spots of the plan routes: along each bundle piece (a piece of a line where the set
    of cables does not change, electrical/bundles.bundles) `offset` from its ends and evenly
    between, no farther apart than the step of the surface (in conduit or bare: on the floor
    always in conduit, on the ceiling as chosen); the same along a slanted piece. In conduit the
    lines of a piece share conduits (conduits): a clip per conduit, by its diameter."""
    out: list[PlanFixing] = []
    for route in ("ceiling", "floor"):
        idx = [k for k, r in enumerate(wiring.runs) if r.route == route]
        surface: Surface = "floor" if route == "floor" else "ceiling"
        in_conduit = route == "floor" or conduit in ("ceiling", "walls")
        step = norms.step(surface, in_conduit)
        for b in bundles(segments([wiring.runs[k].path for k in idx]), {}):
            lines = [wiring.runs[idx[j]] for j in b.runs]
            ids = tuple(r.id for r in lines)
            keys = (
                tuple(f"{CLIP}.{d}" for d, _ in conduits(lines))
                if in_conduit
                else (PAD,) * len(lines)
            )
            along = Vec(1.0, 0.0) if b.axis == "h" else Vec(0.0, 1.0)
            for n, t in enumerate(spots(b.length, step, norms.offset)):
                pos = b.lo + t
                at = Vec(pos, b.fixed) if b.axis == "h" else Vec(b.fixed, pos)
                out.append(PlanFixing(route, at, along, ids, b.axis, b.fixed, n == 0, keys))
        for k in idx:
            r = wiring.runs[k]
            for a, c in itertools.pairwise(r.path):
                d = c - a
                if abs(d.x) <= AXIS_TOL_MM or abs(d.y) <= AXIS_TOL_MM:
                    continue  # along an axis: in a bundle (or a zero piece)
                length = d.length()
                u = d * (1 / length)
                key = fixing_key(r, in_conduit)
                out += [
                    PlanFixing(route, a + u * t, u, (r.id,), keys=(key,))
                    for t in spots(length, step, norms.offset)
                ]
    return out


def fixing_counts(
    wiring: Wiring, conduit: Conduit, norms: MountingNorms = PRACTICE
) -> Counter[tuple[str, Surface]]:
    """Fixings by (estimate item, surface), as drawn, without the reserve: on the plan routes a
    pad per bare cable or a clip per conduit at each bundle spot (plan_fixings), on the rises
    along each rise; a chain pair in one conduit by its clips of pair_diameter; the rise from the
    panel or the cabinet in conduit by the conduits its lines share (source_conduits)."""
    count: Counter[tuple[str, Surface]] = Counter()
    for spot in plan_fixings(wiring, conduit, norms):
        surface: Surface = "floor" if spot.route == "floor" else "ceiling"
        for key in spot.keys:
            count[(key, surface)] += 1
    from_source: set[str] = set()
    for piece in source_conduits(wiring, conduit):
        from_source.update(piece.runs)
        n = len(spots(piece.length, norms.step("wall", True), norms.offset))
        count[(f"{CLIP}.{piece.diameter}", "wall")] += n
    pairs = shared_pairs(wiring)
    for r in wiring.runs:
        out = pairs.get(r.id)
        inside = r.id in wiring.shared_rises or r.id in from_source
        for f in run_fixings(r, conduit, norms, inside=inside, pair=out is not None):
            if f.piece is not None:
                continue  # the plan part: by bundle spots above
            paired = f"{CLIP}.{pair_diameter(r.mark, out.mark)}" if f.pair and out else None
            count[(paired or fixing_key(r, f.in_conduit), f.surface)] += 1
    return count


def fixings(wiring: Wiring, conduit: Conduit, norms: MountingNorms = PRACTICE) -> dict[str, int]:
    """Fixings for the estimate by item: clips by diameter, then pads, with the reserve."""
    total: Counter[str] = Counter()
    for (key, _), n in fixing_counts(wiring, conduit, norms).items():
        total[key] += n
    clips = sorted((k for k in total if k != PAD), key=lambda k: int(k.partition(".")[2]))
    return {k: math.ceil(total[k] * (1 + norms.reserve)) for k in [*clips, PAD] if total[k]}


TEXT: dict[str, dict[str, str]] = {
    "title": {"ru": "Памятка монтажника", "uk": "Пам'ятка монтажника"},
    "gun": {
        "ru": "Крепление монтажным пистолетом: гофра — клипсой по диаметру гофры, кабель без "
        "гофры — площадкой с дюбель-гвоздём и стяжкой.",
        "uk": "Кріплення монтажним пістолетом: гофра — кліпсою за діаметром гофри, кабель без "
        "гофри — площадкою з дюбель-цвяхом і стяжкою.",
    },
    "steps": {
        "ru": "Шаг креплений — не больше, мм: кабель без гофры — по потолку {c}, по стене {w}; "
        "гофра — по потолку {cc}, по стене {cw}, по полу {f}.",
        "uk": "Крок кріплень — не більше, мм: кабель без гофри — по стелі {c}, по стіні {w}; "
        "гофра — по стелі {cc}, по стіні {cw}, по підлозі {f}.",
    },
    "offset": {
        "ru": "Ближайшее крепление — {o} мм от поворота, распаечной коробки, подрозетника и щита.",
        "uk": "Найближче кріплення — {o} мм від повороту, розподільчої коробки, підрозетника і "
        "щита.",
    },
    "bend": {
        "ru": "Плоский кабель на повороте гнётся плашмя, плавно, без заломов: радиус — не меньше "
        "{k} ширин кабеля; гофра — не меньше радиуса из таблицы.",
        "uk": "Плоский кабель на повороті гнеться плазом, плавно, без зламів: радіус — не менше "
        "{k} ширин кабелю; гофра — не менше радіуса з таблиці.",
    },
    "bundle": {
        "ru": "Поворот косы: внутренний кабель — опорный, от его наименьшего радиуса оставить "
        "место под {n} кабеля, каждый следующий наружу — дальше на свою ширину (гофра — на свой "
        "диаметр). У поворота косы на виде — радиусы внутреннего и внешнего кабеля, «R130–160».",
        "uk": "Поворот коси: внутрішній кабель — опорний, від його найменшого радіуса залишити "
        "місце під {n} кабелі, кожен наступний назовні — далі на свою ширину (гофра — на свій "
        "діаметр). Біля повороту коси на вигляді — радіуси внутрішнього і зовнішнього кабелю, "
        "«R130–160».",
    },
    "bends": {"ru": "Наименьший радиус изгиба, мм", "uk": "Найменший радіус вигину, мм"},
    "cable": {"ru": "Кабель", "uk": "Кабель"},
    "bare": {"ru": "Без гофры", "uk": "Без гофри"},
    "conduit": {"ru": "Гофра", "uk": "Гофра"},
    "in_conduit": {"ru": "В гофре", "uk": "У гофрі"},
    "conduit_none": {
        "ru": "Гофра — только по полу; по потолку и по стенам кабель без гофры, на площадках.",
        "uk": "Гофра — лише по підлозі; по стелі й по стінах кабель без гофри, на площадках.",
    },
    "conduit_ceiling": {
        "ru": "Гофра — по потолку и по полу; спуски по стенам — без гофры, на площадках.",
        "uk": "Гофра — по стелі й по підлозі; спуски по стінах — без гофри, на площадках.",
    },
    "conduit_walls": {
        "ru": "Гофра — на всей трассе: по потолку, в спусках по стенам и по полу.",
        "uk": "Гофра — на всій трасі: по стелі, у спусках по стінах і по підлозі.",
    },
    "one_line": {
        "ru": "Крепления косы — в одну линию: клипсы гофры соединяются пазом, площадки кабеля "
        "без гофры ставятся рядом; на одном месте — по креплению на каждую гофру и на каждый "
        "кабель без гофры.",
        "uk": "Кріплення коси — в одну лінію: кліпси гофри з'єднуються пазом, площадки кабелю "
        "без гофри ставляться поруч; на одному місці — по кріпленню на кожну гофру і на кожен "
        "кабель без гофри.",
    },
    "shared": {
        "ru": "Общая гофра: кабели, которые идут рядом, — в одной гофре, заполнение не больше "
        "{pct} % внутреннего сечения (до Ø{d}); интернет и ТВ — в своей гофре.",
        "uk": "Спільна гофра: кабелі, що йдуть поруч, — в одній гофрі, заповнення не більше "
        "{pct} % внутрішнього перерізу (до Ø{d}); інтернет і ТБ — у своїй гофрі.",
    },
    "apart": {
        "ru": "Интернет и ТВ — не ближе {mm} мм от силового кабеля, пересечение — под 90°.",
        "uk": "Інтернет і ТБ — не ближче {mm} мм від силового кабелю, перетин — під 90°.",
    },
    "sheet": {
        "ru": "На развёртке: линия поперёк косы — место крепления, на потолке и на спусках по "
        "стенам, рядом — сколько креплений в линию, «×5»; у конца линии на потолке кружок с "
        "точкой — спуск по стене, кружок с крестом — точка на потолке.",
        "uk": "На розгортці: лінія поперек коси — місце кріплення, на стелі й на спусках по "
        "стінах, поруч — скільки кріплень у лінію, «×5»; біля кінця лінії на стелі кружечок із "
        "крапкою — спуск по стіні, кружечок із хрестиком — точка на стелі.",
    },
    "view_title": {
        "ru": "{room} — {plane}, {w} × {h} мм, М 1:{scale}",
        "uk": "{room} — {plane}, {w} × {h} мм, М 1:{scale}",
    },
    "plane_ceiling": {"ru": "потолок", "uk": "стеля"},
    "plane_floor": {"ru": "пол (в стяжке)", "uk": "підлога (у стяжці)"},
    "view_side": {
        "ru": "вид сверху · размеры от стен {left} (слева) и {bottom} (снизу)",
        "uk": "вигляд згори · розміри від стін {left} (ліворуч) і {bottom} (знизу)",
    },
    "view_side_corner": {
        "ru": "вид сверху · размеры от крайних точек помещения",
        "uk": "вигляд згори · розміри від крайніх точок приміщення",
    },
    "source": {"ru": "Значения: {s}.", "uk": "Значення: {s}."},
    "table": {"ru": "Крепления по чертежу", "uk": "Кріплення за кресленням"},
    "item": {"ru": "Крепление", "uk": "Кріплення"},
    "ceiling": {"ru": "Потолок", "uk": "Стеля"},
    "wall": {"ru": "Стены", "uk": "Стіни"},
    "floor": {"ru": "Пол", "uk": "Підлога"},
    "total": {"ru": "Всего", "uk": "Усього"},
    "pad": {"ru": "Площадка, кабель", "uk": "Площадка, кабель"},
    "clip": {"ru": "Клипса, гофра {n} мм", "uk": "Кліпса, гофра {n} мм"},
    "reserve": {
        "ru": "В смете — на {pct} % больше: запас на осечки.",
        "uk": "У кошторисі — на {pct} % більше: запас на осічки.",
    },
}


def text(key: str, language: Language, **values: object) -> str:
    return TEXT[key][language].format(**values)


def mounting_notes(
    elec: Electrical, language: Language, norms: MountingNorms = PRACTICE
) -> list[str]:
    """Installer notes for this project: how to fix, steps, offsets, bends, where conduit goes."""
    s, g = norms.steps, norms.conduit_steps
    return [
        text("gun", language),
        text("one_line", language),
        text(
            "steps",
            language,
            c=f"{s['ceiling']:g}",
            w=f"{s['wall']:g}",
            cc=f"{g['ceiling']:g}",
            cw=f"{g['wall']:g}",
            f=f"{g['floor']:g}",
        ),
        text("offset", language, o=f"{norms.offset:g}"),
        text("bend", language, k=f"{norms.bend_factor:g}"),
        text("bundle", language, n=norms.bend_reserve),
        text(f"conduit_{elec.conduit_level}", language),
        text("shared", language, pct=f"{CONDUIT_FILL * 100:g}", d=max(CONDUIT_INNER)),
        *(
            [text("apart", language, mm=f"{APART:g}")]
            if any(p.type in (PointType.DATA, PointType.TV) for p in elec.points)
            else []
        ),
        text("sheet", language),
        text("source", language, s=norms.source[language]),
    ]


def fixing_rows(
    counts: Mapping[tuple[str, Surface], int], language: Language
) -> list[tuple[str, list[int]]]:
    """Summary rows: item name and counts by SURFACES plus the total; clips by diameter, then
    pads."""
    keys = {k for k, _ in counts}
    clips = sorted((k for k in keys if k != PAD), key=lambda k: int(k.partition(".")[2]))
    rows: list[tuple[str, list[int]]] = []
    for key in [*clips, *([PAD] if PAD in keys else [])]:
        diameter = key.partition(".")[2]
        name = text("pad", language) if key == PAD else text("clip", language, n=diameter)
        by = [counts.get((key, s), 0) for s in SURFACES]
        rows.append((name, [*by, sum(by)]))
    return rows


def surface_titles(language: Language) -> Sequence[str]:
    return [text(s, language) for s in SURFACES]


def bend_rows(
    marks: Sequence[str], norms: MountingNorms = PRACTICE
) -> list[tuple[str, str, str, str]]:
    """Smallest radius by cable type: (type, without conduit, conduit Ø, in conduit), mm; types
    without sizes are left out."""
    rows: list[tuple[str, str, str, str]] = []
    for mark in sorted(set(marks), key=lambda m: (cable_section(m) or 0.0, m)):
        bare, inside = bend_size(mark, False, norms), bend_size(mark, True, norms)
        if bare is None or inside is None:
            continue
        d = conduit_diameter(mark)
        rows.append((mark, f"{bare.radius:g}", f"{d}", f"{inside.radius:g}"))
    return rows
