"""The "Mounting" sheet drawing: fixing spots on the cable lines (electrical/mounting.py).

A fixing is a short stroke across the line, on the line's own lane (drawing/wiring.lay_out), so
in a bundle every cable shows its own fixings. At a turn of two or more lines the radii of the
inner and the outer line are signed, "R130–160" (bundle_radii: the inner line is the reference,
lanes are kept free for cables added later); a single line takes the radius from the table.
Only the plan part is drawn (ceiling, floor): the rises along the walls are vertical and do not
show on the plan, their fixings are on the elevations. Strokes are tagged as their line: a tap
shows the line's hint.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from ezdxf import bbox
from ezdxf.layouts.layout import Modelspace
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from floorplan_engine.drawing.ids import tagged
from floorplan_engine.drawing.layers import M_FIX, text_width
from floorplan_engine.drawing.plan import add_text
from floorplan_engine.drawing.tables import Column, Table
from floorplan_engine.drawing.wiring import LENGTH_MM, _Labels, lay_out
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
    run_fixings,
    surface_titles,
    text,
)
from floorplan_engine.electrical.wiring_model import Wiring
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.scale import sheet
from floorplan_engine.model.schema import Conduit
from floorplan_engine.model.texts import Language

STROKE_MM = 1.4  # stroke length across the line on the sheet


def fixing_at(path: Sequence[Vec], piece: int, at: float) -> tuple[Vec, Vec] | None:
    """Spot `at` mm along piece `piece` of a drawn path and the unit direction of the piece;
    None for a degenerate piece."""
    a, b = path[piece], path[piece + 1]
    d = b - a
    length = d.length()
    if length <= 0:
        return None
    u = d * (1 / length)
    return a + u * min(at, length), u


def draw_fixings(
    msp: Modelspace, wiring: Wiring, conduit: Conduit, norms: MountingNorms = PRACTICE
) -> None:
    paths, _ = lay_out(wiring)
    half = sheet(STROKE_MM) / 2
    for k, run in enumerate(wiring.runs):
        with tagged(msp, "wire", run.id):
            for f in run_fixings(run, conduit, norms):
                if f.piece is None:
                    continue
                spot = fixing_at(paths[k], f.piece, f.at)
                if spot is None:
                    continue
                p, u = spot
                n = u.left() * half
                msp.add_line(
                    (p + n).as_tuple(), (p - n).as_tuple(), dxfattribs={"layer": M_FIX.name}
                )


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


BEND_TEXT_GAP_MM = 2.5  # from the corner to the radius label, sheet mm
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


def bundle_bends(
    wiring: Wiring,
    paths: Sequence[Sequence[Vec]],
    conduit: Conduit,
    norms: MountingNorms = PRACTICE,
) -> list[Bend]:
    """Turns of the plan routes taken by two or more lines with known sizes. Lines turn together
    when they bend at one corner between the same two arms, whichever way they run; the inner
    one is the one drawn nearest the inside of the corner (paths: lanes, wiring.lay_out)."""
    corners: dict[tuple[float, float, frozenset[tuple[float, float]]], list[tuple[int, int]]]
    corners = defaultdict(list)
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
    out: list[Bend] = []
    for (x, y, arms), members in sorted(corners.items(), key=lambda c: (c[0][0], c[0][1])):
        a, b = (Vec(*d) for d in sorted(arms))
        inside = a + b
        inside = inside * (1 / inside.length())
        corner = Vec(float(x), float(y))
        sized: list[tuple[float, str, BendSize]] = []
        for k, i in members:
            run = wiring.runs[k]
            plan_in = fixing_spans(run, conduit)[0][0]
            size = bend_size(run.mark, plan_in, norms)
            if size is not None:
                depth = (paths[k][i] - corner).dot(inside)
                sized.append((-depth, run.id, size))
        if len(sized) < 2:
            continue
        sized.sort(key=lambda t: (t[0], t[1]))
        radii = bundle_radii([t[2] for t in sized], norms)
        out.append(Bend(corner, inside, tuple(t[1] for t in sized), tuple(radii)))
    return out


def bend_label(bend: Bend) -> str:
    return f"R{bend.radii[0]:.0f}–{bend.radii[-1]:.0f}"


def draw_bends(
    msp: Modelspace, wiring: Wiring, conduit: Conduit, norms: MountingNorms = PRACTICE
) -> list[Bend]:
    """Radius labels at the bundle turns, inside the corner or, if taken, outside; a label that
    finds no free spot is left out (the rule is in the notes)."""
    paths, _ = lay_out(wiring)
    labels = _Labels(paths)
    for t in msp.query("TEXT"):
        labels.block(_text_box(t))
    if wiring.free is not None:  # walls: a label stays inside the rooms
        x0, y0, x1, y1 = wiring.free.bounds
        pad = sheet(BEND_TEXT_GAP_MM) * 20
        labels.block(box(x0 - pad, y0 - pad, x1 + pad, y1 + pad).difference(wiring.free))
    bends = bundle_bends(wiring, paths, conduit, norms)
    along = Vec(1.0, 0.0)
    for bend in bends:
        text = bend_label(bend)
        reach = sheet(BEND_TEXT_GAP_MM) + sheet(text_width(text, LENGTH_MM)) / 2
        spots = [bend.at + bend.inside * (reach * f) for f in (0.8, 1.1, 1.5)]
        spots += [bend.at - bend.inside * (reach * f) for f in (0.8, 1.1)]
        placed = labels.place(text, [(p, along) for p in spots])
        if placed is None:
            continue
        with tagged(msp, "wire", bend.runs[0]):
            add_text(msp, placed[0], placed[1], LENGTH_MM, M_FIX.name, placed[2])
    return bends


def _text_box(entity: object) -> BaseGeometry:
    ext = bbox.extents([entity])  # type: ignore[list-item]
    if not ext.has_data:
        return box(0, 0, 0, 0)
    return box(ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y)


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
