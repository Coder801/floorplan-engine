"""Размещение подписей (labels.py) на синтетической геометрии: мм модели = мм листа."""

from __future__ import annotations

from shapely.geometry import Polygon, box

from floorplan_engine.drawing.labels import Align, LabelPlacer, Metrics, door_swing
from floorplan_engine.model.geometry import Vec

M = Metrics(line_h=2.0, step=3.0, gap=1.0, probe=1.0, reach=12, far=40, leader_min=3.0)
# Помещение 100 × 60, стены по 10 мм снаружи
ROOM = Polygon([(0, 0), (100, 0), (100, 60), (0, 60)])
WALLS = box(-10, -10, 110, 70).difference(ROOM)


def placer(**kw: object) -> LabelPlacer:
    args: dict[str, object] = {"walls": WALLS, "symbols": [], "zones": [], "metrics": M}
    args.update(kw)
    return LabelPlacer(**args)  # type: ignore[arg-type]


def test_label_beside_wall_symbol_inside_room() -> None:
    p = placer()
    out = p.place(["h300"], [8.0], Vec(0, 30), Vec(1, 0), 2.0)
    x0, y0, _, y1 = out.rect
    assert out.align is Align.LEFT
    assert x0 == 3.0 and y0 < 30 < y1  # у символа, со стороны помещения, по центру
    assert out.leader is None
    assert out.lines == [("h300", Vec(3.0, 30.0))]


def test_second_label_does_not_overlap_first() -> None:
    p = placer()
    a = p.place(["h300", "h900"], [8.0, 8.0], Vec(0, 30), Vec(1, 0), 2.0)
    b = p.place(["h1100"], [10.0], Vec(0, 31), Vec(1, 0), 2.0)
    assert not box(*a.rect).intersects(box(*b.rect))


def test_label_avoids_symbol_and_door() -> None:
    sym = box(2, 26, 6, 34)  # чужой символ прямо там, где встала бы подпись
    door = door_swing(Vec(20, 0), Vec(40, 0), Vec(0, 1), 20.0)
    p = placer(symbols=[sym], zones=[door])
    out = p.place(["h300"], [8.0], Vec(0, 30), Vec(1, 0), 2.0)
    assert box(*out.rect).intersection(sym).area == 0
    out2 = p.place(["h1100 розетка"], [20.0], Vec(30, 0), Vec(0, 1), 2.0)
    assert box(*out2.rect).intersection(door).area == 0


def test_crowded_spot_gets_leader_and_stays_in_frame() -> None:
    # Всё вокруг символа занято символами — подпись уходит дальше, с выноской
    syms = [box(0, 0, 30, 60)]
    frame = box(-20, -20, 120, 80)
    p = placer(symbols=syms, frame=frame)
    out = p.place(["h300"], [8.0], Vec(0, 30), Vec(1, 0), 2.0, own=box(0, 28, 2, 32))
    assert out.leader is not None
    assert box(*out.rect).within(frame)
    assert box(*out.rect).intersection(syms[0]).area == 0


def test_label_prefers_own_room() -> None:
    left = Polygon([(0, 0), (50, 0), (50, 60), (0, 60)])
    right = Polygon([(50, 0), (100, 0), (100, 60), (50, 60)])
    p = placer(rooms={"a": left, "b": right})
    out = p.place(["h300 розетка"], [30.0], Vec(50, 30), Vec(-1, 0), 2.0, room="a")
    assert box(*out.rect).intersection(right).area == 0
