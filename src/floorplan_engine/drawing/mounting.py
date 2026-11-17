"""Mounting parts of the room unfolds (drawing/ceilings.py): the bundle turns with their radii
and the tables "Fixings by the drawing" and "Smallest bend radius". At a turn of two or more
lines the radii of the inner and the outer line are signed, "R130–160" (bundle_radii: the inner
line is the reference, lanes are kept free for cables added later); a single line, its smallest
radius, "R115". On the ceiling view a turn is drawn round with that radius (lane_turns, rounded;
decision 2026-11-17): the routes are square, the cable is not bent at 90°.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from floorplan_engine.drawing.tables import Column, Table
from floorplan_engine.electrical.mounting import (
    PRACTICE,
    BendSize,
    MountingNorms,
    bend_rows,
    bend_size,
    bundle_radii,
    fixing_counts,
    fixing_rows,
    fixing_spans,
    surface_titles,
    text,
)
from floorplan_engine.electrical.wiring_model import Wiring
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.schema import Conduit
from floorplan_engine.model.texts import Language


def fixings_table(
    wiring: Wiring, conduit: Conduit, language: Language, norms: MountingNorms = PRACTICE
) -> Table | None:
    """The fixings by the drawing: item → ceiling, walls, floor, total; None without fixings."""
    rows = fixing_rows(fixing_counts(wiring, conduit, norms), language)
    if not rows:
        return None
    columns = (
        Column(text("item", language), 38.0, "left"),
        *(Column(t, 16.0) for t in surface_titles(language)),
        Column(text("total", language), 16.0),
    )
    cells = tuple((name, *(str(n) if n else "—" for n in counts)) for name, counts in rows)
    return Table(text("table", language), columns, cells)


_DIR_TOL = 1e-3


def _direction(v: Vec) -> tuple[float, float]:
    n = v.length()
    return (round(v.x / n, 3), round(v.y / n, 3))


@dataclass(frozen=True)
class Bend:
    """A bundle turn: the corner in the model, the inside direction, its lines inner first with
    their radii, mm."""

    at: Vec
    inside: Vec
    runs: tuple[str, ...]
    radii: tuple[float, ...]


Corner = tuple[float, float, frozenset[tuple[float, float]]]  # a turn: point and its two arms


def _corners(wiring: Wiring) -> dict[Corner, list[tuple[int, int]]]:
    """Turns of the plan routes: (line, vertex) by corner. Lines turn together when they bend at
    one corner between the same two arms, whichever way they run."""
    corners: dict[Corner, list[tuple[int, int]]] = defaultdict(list)
    for k, run in enumerate(wiring.runs):
        path = run.path
        for i in range(1, len(path) - 1):
            back, ahead = path[i - 1] - path[i], path[i + 1] - path[i]
            if back.length() < _DIR_TOL or ahead.length() < _DIR_TOL:
                continue
            if abs(back.cross(ahead)) < _DIR_TOL * back.length() * ahead.length():
                continue  # straight on or back
            arms = frozenset({_direction(back), _direction(ahead)})
            corners[(round(path[i].x), round(path[i].y), arms)].append((k, i))
    return corners


def _inside(arms: frozenset[tuple[float, float]]) -> Vec:
    a, b = (Vec(*d) for d in sorted(arms))
    inside = a + b
    return inside * (1 / inside.length())


def _sized(
    wiring: Wiring,
    paths: Sequence[Sequence[Vec]],
    corner: Vec,
    inside: Vec,
    members: Sequence[tuple[int, int]],
    conduit: Conduit,
    norms: MountingNorms,
) -> list[tuple[float, str, BendSize, int, int]]:
    """The lines of a turn with known sizes, inner first (the lane nearest the inside)."""
    sized: list[tuple[float, str, BendSize, int, int]] = []
    for k, i in members:
        run = wiring.runs[k]
        plan_in = fixing_spans(run, conduit)[0][0]
        size = bend_size(run.mark, plan_in, norms)
        if size is not None:
            depth = (paths[k][i] - corner).dot(inside)
            sized.append((-depth, run.id, size, k, i))
    sized.sort(key=lambda t: (t[0], t[1]))
    return sized


def bundle_bends(
    wiring: Wiring,
    paths: Sequence[Sequence[Vec]],
    conduit: Conduit,
    norms: MountingNorms = PRACTICE,
) -> list[Bend]:
    """Turns of the plan routes taken by two or more lines with known sizes; the inner one is
    the one drawn nearest the inside of the corner (paths: lanes, wiring.lay_out)."""
    return [b for b in lane_turns(wiring, paths, conduit, norms).bends if len(b.radii) > 1]


@dataclass(frozen=True)
class Turns:
    """How the lanes take their turns on a ceiling view (decision 2026-11-17: a turn is drawn
    round, with the radius it takes): bends are the signed turns — a bundle of two or more
    sized lines (radii inner to outer) or one sized line (its smallest radius; a jog shorter
    than it is not signed); fillets the
    drawn radius of every lane corner, (line, vertex) → model mm. The lines of one turn are
    drawn concentric around the reference line (the inner sized one), so the lanes do not cross;
    a turn without a sized line (low voltage: the manufacturer's radius) stays square."""

    bends: list[Bend]
    fillets: dict[tuple[int, int], float]


def lane_turns(
    wiring: Wiring,
    paths: Sequence[Sequence[Vec]],
    conduit: Conduit,
    norms: MountingNorms = PRACTICE,
) -> Turns:
    """The turns of the plan routes with their radii and the lane fillets (paths: lanes)."""
    bends: list[Bend] = []
    fillets: dict[tuple[int, int], float] = {}
    for (x, y, arms), members in sorted(_corners(wiring).items(), key=lambda c: (c[0][0], c[0][1])):
        corner, inside = Vec(float(x), float(y)), _inside(arms)
        sized = _sized(wiring, paths, corner, inside, members, conduit, norms)
        if not sized:
            continue
        sizes = [t[2] for t in sized]
        radii = bundle_radii(sizes, norms) if len(sized) > 1 else [sizes[0].radius]
        if len(sized) > 1 or _real_turn(wiring, sized[0][3], sized[0][4], radii[0]):
            bends.append(Bend(corner, inside, tuple(t[1] for t in sized), tuple(radii)))
        # The reference line: its lane turns at its radius around the centre on the bisector;
        # the other lanes of the turn are drawn around the same centre
        _, _, _, k0, i0 = sized[0]
        arm = Vec(*sorted(arms)[0])
        sin_half = abs(arm.cross(inside))  # both unit: the sine of half the turn
        if sin_half < _DIR_TOL:
            continue
        centre = paths[k0][i0] + inside * (radii[0] / sin_half)
        for k, i in members:
            r = abs((centre - paths[k][i]).cross(arm))
            if r > _DIR_TOL:
                fillets[(k, i)] = r
    return Turns(bends, fillets)


def _real_turn(wiring: Wiring, k: int, i: int, radius: float) -> bool:
    """A single line's turn worth signing: both arms at least its radius long; a shorter jog
    (the lane stepping aside to a point or a box) is drawn round but not signed."""
    path = wiring.runs[k].path
    return min((path[i - 1] - path[i]).length(), (path[i + 1] - path[i]).length()) >= radius


def rounded(path: Sequence[Vec], radii: Mapping[int, float], step_deg: float = 10.0) -> list[Vec]:
    """The lane with its corners rounded: vertex i → radius, model mm; an arc is a polyline of
    step_deg pieces. A radius longer than its pieces allow is cut down: a corner takes up to the
    whole piece next to a line end, half of a piece shared with the next rounded corner."""
    if len(path) < 3 or not radii:
        return list(path)
    out = [path[0]]
    last = len(path) - 1
    for i in range(1, last):
        r = radii.get(i)
        p = path[i]
        back, ahead = path[i - 1] - p, path[i + 1] - p
        lb, la = back.length(), ahead.length()
        if r is None or lb < _DIR_TOL or la < _DIR_TOL:
            out.append(p)
            continue
        u, v = back * (1 / lb), ahead * (1 / la)
        turn = math.acos(max(-1.0, min(1.0, u.dot(v))))  # the angle between the arms
        if turn < _DIR_TOL or math.pi - turn < _DIR_TOL:
            out.append(p)
            continue
        share_b = 0.5 if (i - 1) in radii and i - 1 > 0 else 1.0
        share_a = 0.5 if (i + 1) in radii and i + 1 < last else 1.0
        t = min(r / math.tan(turn / 2), lb * share_b, la * share_a)
        r = t * math.tan(turn / 2)
        bis = u + v
        bis = bis * (1 / bis.length())
        centre = p + bis * (r / math.sin(turn / 2))
        a0 = math.atan2((p + u * t - centre).y, (p + u * t - centre).x)
        a1 = math.atan2((p + v * t - centre).y, (p + v * t - centre).x)
        sweep = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi  # the short way round
        n = max(2, math.ceil(abs(math.degrees(sweep)) / step_deg))
        out += [
            centre + Vec(math.cos(a0 + sweep * j / n), math.sin(a0 + sweep * j / n)) * r
            for j in range(n + 1)
        ]
    out.append(path[-1])
    return out


def bend_label(bend: Bend) -> str:
    """The radius label: "R130–160" for a bundle (inner and outer line), "R115" for one line."""
    if len(bend.radii) == 1:
        return f"R{bend.radii[0]:.0f}"
    return f"R{bend.radii[0]:.0f}–{bend.radii[-1]:.0f}"


def bends_table(
    wiring: Wiring, language: Language, norms: MountingNorms = PRACTICE
) -> Table | None:
    """Smallest bend radius by the project's cable types: without conduit and in conduit."""
    rows = bend_rows([r.mark for r in wiring.runs], norms)
    if not rows:
        return None
    columns = (
        Column(text("cable", language), 18.0, "left"),
        Column(text("bare", language), 20.0),
        Column(text("conduit", language), 16.0),
        Column(text("in_conduit", language), 18.0),
    )
    return Table(text("bends", language), columns, tuple(rows))
