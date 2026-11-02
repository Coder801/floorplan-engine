"""Канализация под 45° (docs/plumbing.md): трасса по плану — только из отводов 45°.

- `octilinear` — участок не под 45° (хвост к стене, к стояку, к месту врезки) делится на
  прямой и диагональный;
- `chamfer` — излом на 90° или 135° собирается из отводов 45°: в угол вставляются короткие
  участки, у каждого излома — ровно 45°;
- `tee45` — врезка отвода в трубу косым тройником: отвод входит под 45° по течению;
- `bends` — сколько отводов 45° на трассе по плану.

Чистая геометрия на Vec, мм модели; сетка и стены — в plumbing/network.py.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence

from floorplan_engine.model.geometry import Vec

TOL = 0.5  # мм: короче — точка та же; отклонение меньше — направление то же
CHAMFER = 100.0  # мм: длина вставки между двумя отводами 45°
TEE = (100.0, 50.0, 25.0)  # мм: насколько отвод отходит от трубы косым участком, по убыванию
COS45 = math.cos(math.pi / 4)


def _unit(v: Vec) -> Vec:
    n = v.length()
    return v * (1 / n)


def _rotate(v: Vec, angle: float) -> Vec:
    c, s = math.cos(angle), math.sin(angle)
    return Vec(v.x * c - v.y * s, v.x * s + v.y * c)


def is_octilinear(v: Vec) -> bool:
    """Направление — одно из восьми: вдоль осей или по диагонали."""
    ax, ay = abs(v.x), abs(v.y)
    return ax < TOL or ay < TOL or abs(ax - ay) < TOL


def turn(u: Vec, v: Vec) -> float:
    """Излом между направлениями u и v, градусы (0 — прямо)."""
    c = u.dot(v) / (u.length() * v.length())
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def simplify(path: Sequence[Vec]) -> list[Vec]:
    """Без повторов и без точек на прямой (под любым углом)."""
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
    """Каждый участок не под 45° — прямым и диагональным (сначала прямой)."""
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
    """Изломы больше 45° — отводами 45°: в угол вставляются участки длиной size (короче,
    если соседние участки коротки). Концы трассы не двигаются."""
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
        reach = total.length() / (u + v).length()  # от угла до отвода при вставке 1 мм
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
    """Отводов 45° по плану: излом на 90° — два."""
    pts = simplify(path)
    return sum(
        round(turn(b - a, c - b) / 45) for a, b, c in zip(pts, pts[1:], pts[2:], strict=False)
    )


def point_at(path: Sequence[Vec], along: float) -> tuple[Vec, Vec, float]:
    """Точка в along мм от начала ломаной, направление её участка и где участок начинается."""
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
    """Врезка отвода path (от места врезки path[0] к прибору) в трубу parent (от стояка) на
    along мм от её начала — косым тройником: последний участок отвода по течению идёт под 45°
    к течению в трубе. Место врезки сдвигается по трубе к стояку. Нельзя — без изменений."""
    pts = simplify(path)
    if len(pts) < 2 or len(parent) < 2:
        return pts, along
    _, d_parent, seg_start = point_at(parent, along)
    flow = d_parent * -1.0  # в трубе течёт к стояку — к её началу
    n = _unit(pts[1] - pts[0])
    cos_phi, sin_phi = n.dot(flow), abs(n.cross(flow))
    if -cos_phi >= COS45 - 1e-6 or sin_phi < 1e-3:
        return pts, along  # уже под 45° по течению или вдоль трубы
    first = (pts[1] - pts[0]).length()
    for e in TEE:
        t = e * (cos_phi + sin_phi)
        if t <= 1e-6 or e > first + 1e-6 or along - t < seg_start - 1e-6:
            continue
        start = pts[0] + flow * t
        out = simplify([start, pts[0] + n * e, *pts[1:]])
        return out, along - t
    return pts, along
