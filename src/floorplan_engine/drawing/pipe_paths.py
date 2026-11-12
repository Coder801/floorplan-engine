"""Pipe paths on the sheet: lanes for pipes on one line, pieces along the wall above the floor.

Drawing only, no DXF here: routes, lengths and the estimate come from the network as is.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import replace

from shapely.geometry import Point

from floorplan_engine.drawing.wiring import clearance, lanes, offset_path
from floorplan_engine.electrical.bundles import Segment, segments
from floorplan_engine.electrical.routing import CLEARANCE
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.scale import sheet
from floorplan_engine.plumbing.network_model import Network, Pipe

LANE_MM = 0.9  # pipe lane step on the sheet
SNAP_LANES = 2.0  # pipes on neighbouring lines closer than this many lane steps form one bundle
BAND_MM = 12.0


def lay_out(net: Network) -> list[list[Vec]]:
    """Pipe paths shifted into their lanes (shared by water and sewer: all run on the floor).
    Drawing only: routes, lengths and the estimate come from the network as is. Water runs at
    right angles (a slanted branch entering a pipe that runs as an off-grid pair becomes an
    elbow); pipes on neighbouring lines closer than SNAP_LANES lane steps go as one bundle in
    different lanes, not on top of each other (hot paired with cold lies off the grid, next to
    another pipe)."""
    paths = [list(p.path) if p.kind == "sewer" else _square(p.path) for p in net.pipes]
    all_segs = segments(paths)
    # A piece along the wall face (to a water outlet in the wall) goes from the wall into the
    # room, the first lane on the face; the outlet to the riser stays in place
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
    """Pieces along a wall face that run on one line go into lanes from the wall into the room:
    the first on the face, the next ones one lane step further in (never into the wall)."""
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
    """Water path at right angles: a slanted piece becomes an elbow (the turn goes where the path
    already turns, along the previous piece); going back along the same line (forth and back at
    a branch tee) is done without a hairpin."""
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
            clean.pop()  # collinear: the middle point is redundant (also when going back)
        clean.append(v)
    return clean


def _snap(
    segs: Sequence[Segment], tol: float
) -> tuple[list[Segment], dict[tuple[int, int], float]]:
    """Pieces of neighbouring lines on one axis (closer than tol) that overlap lengthwise are put on
    one line (the middle one) so that lanes can spread them; the second value is the piece shift
    correction from its line to the shared one."""
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


def _length(path: Sequence[Vec]) -> float:
    return sum((b - a).length() for a, b in itertools.pairwise(path))


def surface_parts(pipe: Pipe, path: Sequence[Vec]) -> list[tuple[list[Vec], bool]]:
    """Sheet path of a pipe in pieces: (points, whether along the wall above the floor). The model
    spans (mm from the start) are mapped to the sheet path: it is shifted into its lane and
    slightly longer or shorter."""
    model = _length(pipe.path)
    k = _length(path) / model if model > 1e-9 else 1.0
    return _split(path, [(a * k, b * k) for a, b in pipe.surface])


def _split(
    path: Sequence[Vec], spans: Sequence[tuple[float, float]]
) -> list[tuple[list[Vec], bool]]:
    """Path in pieces: (points, whether along the wall above the floor); spans are mm from the
    start.
    """
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
    """Piece of a polyline from s0 to s1 mm along it."""
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
