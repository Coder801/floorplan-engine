"""Sewer at 45° (docs/plumbing.md): the plan route is made of 45° bends only.

- `octilinear`: a piece not at a multiple of 45° (a tail to a wall, a riser, a tee spot) is
  split into a straight and a diagonal one;
- `chamfer`: a 90° or 135° corner is built from 45° bends: short pieces are inserted into the
  corner so every bend is exactly 45°;
- `tee45`: a branch enters a pipe through an angled tee: the branch comes in at 45° with the flow;
- `bends`: how many 45° bends are on the plan route.

Pure geometry on Vec, model mm; grid and walls are in plumbing/network.py.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence

from floorplan_engine.model.geometry import Vec

TOL = 0.5  # mm: shorter means the same point; a smaller deviation means the same direction
CHAMFER = 100.0  # mm: length of the insert between two 45° bends
TEE = (100.0, 50.0, 25.0)  # mm: how far the branch leaves the pipe with an angled piece, descending
COS45 = math.cos(math.pi / 4)


def _unit(v: Vec) -> Vec:
    n = v.length()
    return v * (1 / n)


def _rotate(v: Vec, angle: float) -> Vec:
    c, s = math.cos(angle), math.sin(angle)
    return Vec(v.x * c - v.y * s, v.x * s + v.y * c)


def is_octilinear(v: Vec) -> bool:
    """The direction is one of eight: along the axes or diagonal."""
    ax, ay = abs(v.x), abs(v.y)
    return ax < TOL or ay < TOL or abs(ax - ay) < TOL


def turn(u: Vec, v: Vec) -> float:
    """Bend between directions u and v, degrees (0 is straight)."""
    c = u.dot(v) / (u.length() * v.length())
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def simplify(path: Sequence[Vec]) -> list[Vec]:
    """No duplicates and no collinear points (at any angle)."""
    out: list[Vec] = []
    for p in path:
        if out and (p - out[-1]).length() < TOL:
            continue
        if len(out) >= 2:
            u, v = out[-1] - out[-2], p - out[-1]
            if abs(u.cross(v)) < 1e-6 * u.length() * v.length() and u.dot(v) > 0:
                out[-1] = p
                continue
        out.append(p)
    return out


def octilinear(path: Sequence[Vec]) -> list[Vec]:
    """Each piece not at a multiple of 45° becomes a straight and a diagonal one (straight
    first).
    """
    pts = simplify(path)
    out = pts[:1]
    for a, b in itertools.pairwise(pts):
        d = b - a
        if not is_octilinear(d):
            m = min(abs(d.x), abs(d.y))
            diag = Vec(math.copysign(m, d.x), math.copysign(m, d.y))
            out.append(b - diag)
        out.append(b)
    return simplify(out)


def chamfer(path: Sequence[Vec], size: float = CHAMFER) -> list[Vec]:
    """Corners over 45° become 45° bends: pieces of length size are inserted into the corner
    (shorter if the neighbouring pieces are short). The route ends do not move."""
    pts = simplify(path)
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    last = len(pts) - 1
    for i in range(1, last):
        p, u_raw, v_raw = pts[i], pts[i] - pts[i - 1], pts[i + 1] - pts[i]
        k = round(turn(u_raw, v_raw) / 45)
        if k <= 1 or k >= 4:
            out.append(p)
            continue
        u, v = _unit(u_raw), _unit(v_raw)
        sign = 1.0 if u.cross(v) > 0 else -1.0
        dirs = [_rotate(u, sign * math.pi / 4 * (j + 1)) for j in range(k - 1)]
        total = Vec(sum(d.x for d in dirs), sum(d.y for d in dirs))
        reach = total.length() / (u + v).length()  # from the corner to the bend for a 1 mm insert
        room_in = u_raw.length() * (0.5 if i > 1 else 0.9)
        room_out = v_raw.length() * (0.5 if i + 1 < last else 0.9)
        seg = min(size, room_in / reach, room_out / reach)
        q = p - u * (reach * seg)
        out.append(q)
        for d in dirs:
            q = q + d * seg
            out.append(q)
    out.append(pts[-1])
    return simplify(out)


def bends(path: Sequence[Vec]) -> int:
    """45° bends on the plan: a 90° corner counts as two."""
    pts = simplify(path)
    return sum(
        round(turn(b - a, c - b) / 45) for a, b, c in zip(pts, pts[1:], pts[2:], strict=False)
    )


def point_at(path: Sequence[Vec], along: float) -> tuple[Vec, Vec, float]:
    """Point at along mm from the polyline start, the direction of its piece and where the piece
    starts.
    """
    acc = 0.0
    for a, b in itertools.pairwise(path):
        n = (b - a).length()
        if n > 1e-9 and along <= acc + n + 1e-6:
            d = (b - a) * (1 / n)
            return a + d * (along - acc), d, acc
        acc += n
    a, b = path[-2], path[-1]
    return b, _unit(b - a), acc - (b - a).length()


def tee45(path: Sequence[Vec], parent: Sequence[Vec], along: float) -> tuple[list[Vec], float]:
    """Tee the branch path (from the tee spot path[0] to the fixture) into the pipe parent (from the
    riser) at along mm from its start with an angled tee: the last branch piece along the flow
    enters at 45° to the flow in the pipe. The tee spot moves along the pipe towards the riser.
    If impossible, nothing changes."""
    pts = simplify(path)
    if len(pts) < 2 or len(parent) < 2:
        return pts, along
    _, d_parent, seg_start = point_at(parent, along)
    flow = d_parent * -1.0  # the pipe flows towards the riser, i.e. towards its start
    n = _unit(pts[1] - pts[0])
    cos_phi, sin_phi = n.dot(flow), abs(n.cross(flow))
    if -cos_phi >= COS45 - 1e-6 or sin_phi < 1e-3:
        return pts, along  # already at 45° with the flow or along the pipe
    first = (pts[1] - pts[0]).length()
    for e in TEE:
        t = e * (cos_phi + sin_phi)
        if t <= 1e-6 or e > first + 1e-6 or along - t < seg_start - 1e-6:
            continue
        start = pts[0] + flow * t
        out = simplify([start, pts[0] + n * e, *pts[1:]])
        return out, along - t
    return pts, along
