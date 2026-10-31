"""Проводка через коробки — что получилось: распаечные коробки (типоразмер, место, по
потолку или полу), линии кабеля с длинами по участкам, штробы по стенам, отверстия в
проёмах; Wiring — всё вместе для листа проводки, сметы, развёрток и 3D."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from shapely.geometry.base import BaseGeometry

from floorplan_engine.electrical.anchors import Anchor
from floorplan_engine.model.geometry import Vec

BOX_BELOW_CEILING = 200.0  # мм: от потолка до коробки
BOX_ABOVE_FLOOR = 300.0  # мм: от пола до коробки у трасс по полу
CHASE_NARROW = 2  # до стольких кабелей штроба узкая, больше — широкая


Route = Literal["ceiling", "floor"]


Circuit = Literal["power", "low"]  # силовые 230 В и слаботочка


ChaseKey = tuple[str, str, Route, Circuit]  # помещение, стена, плоскость трассы, цепь


@dataclass(frozen=True)
class JunctionBox:
    id: str
    label: str  # «К1» на чертеже
    room: str
    group: str
    anchor: Anchor
    route: Route = "ceiling"
    wet: bool = False  # во влажном помещении — коробка IP44
    size: str = "100x100"  # типоразмер по числу линий (box_size), ключ BOX_SIZES

    @property
    def on_ceiling(self) -> bool:
        return self.anchor.inward is None

    @property
    def rise_mm(self) -> float:
        """От коробки до плоскости трассы: потолка или пола; коробка на потолке — 0."""
        if self.on_ceiling:
            return 0.0
        return BOX_ABOVE_FLOOR if self.route == "floor" else BOX_BELOW_CEILING


@dataclass(frozen=True)
class Run:
    """Одна линия кабеля: щит → коробка, щит → точка или коробка → точка."""

    id: str
    group: str
    mark: str
    mark_assumed: bool  # марки нет в модели — взята по типу точек
    source: str  # board или id коробки
    target: str  # id коробки или точки
    path: tuple[Vec, ...]
    plan_mm: float
    rise_start_mm: float  # от начала линии (щит или коробка) до потолка или пола
    rise_end_mm: float  # по стене от потолка (пола) до конца линии; потолочная точка — 0
    ends_mm: float
    route: Route = "ceiling"
    circuit: Circuit = "power"

    @property
    def vertical_mm(self) -> float:
        return self.rise_start_mm + self.rise_end_mm

    @property
    def length_mm(self) -> float:
        return self.plan_mm + self.vertical_mm + self.ends_mm


@dataclass(frozen=True)
class Chase:
    """Штроба по стене от потолка вниз (route floor — от пола вверх): kind — point
    (к точкам), board (у щита), box (у коробки)."""

    kind: str
    room: str
    wall: str  # id стены; у коробки — ""
    offset: float  # от начала стены до середины штробы; у коробки — 0
    length_mm: float
    cables: int
    targets: tuple[str, ...] = ()  # id точек, к которым идут кабели штробы
    route: Route = "ceiling"
    circuit: Circuit = "power"

    @property
    def wide(self) -> bool:
        return self.cables > CHASE_NARROW


@dataclass(frozen=True)
class Hole:
    """Отверстие в стене над дверью или проёмом для трасс по потолку."""

    passage: str  # id двери или проёма
    cables: int
    circuit: Circuit = "power"
    runs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Wiring:
    ceiling_height: float
    height_assumed: bool  # высоты потолка нет в room.yaml — 2700 по умолчанию
    boxes: tuple[JunctionBox, ...]
    runs: tuple[Run, ...]
    skipped: tuple[str, ...] = field(default=())  # точки без группы
    chases: tuple[Chase, ...] = field(default=())
    holes: tuple[Hole, ...] = field(default=())
    # Помещения и проёмы (routing.free_area) — чтобы пучок на листе не заходил на стены
    free: BaseGeometry | None = field(default=None, compare=False, repr=False)
    # Ручные правки: «wire:id» и «box:id», что применены; замечания — (путь в wiring.yaml, текст)
    edited: frozenset[str] = field(default=frozenset())
    edit_notes: tuple[tuple[str, str], ...] = field(default=())

    @property
    def chase_mm(self) -> float:
        return sum(c.length_mm for c in self.chases)

    def chase_length(self, wide: bool) -> float:
        """Длина узких или широких штроб, мм."""
        return sum(c.length_mm for c in self.chases if c.wide == wide)

    def by_mark(self) -> dict[str, float]:
        """Длина по маркам, м, без запаса."""
        out: dict[str, float] = defaultdict(float)
        for r in self.runs:
            out[r.mark] += r.length_mm / 1000
        return dict(sorted(out.items()))
