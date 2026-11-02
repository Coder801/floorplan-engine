"""plumbing.yaml — водоснабжение и канализация квартиры (docs/plumbing.md).

    distribution: collector        # collector — лучевая от коллекторов; tee — тройниковая
    risers:                        # стояки: канализация Д110, вода — если стояк водяной
      - { id: riser_1, room: bath, at: [150, 2100], sewer: true, water: true }
    input:                         # узел ввода: краны, фильтр, редуктор, коллекторы
      { room: bath, wall: w1, offset: 300, hot: true, height: 1300 }
    fixtures:                      # мокрые точки: прибор у стены
      - { id: bath_wc_1, room: bath, type: wc_installation, wall: w2, offset: 600 }
    obstacles:                     # что трубы обходят: инсталляция, ванна, поддон, короб
      - { id: bath_inst_1, room: bath, type: installation, wall: w2, offset: 350,
          width: 500, depth: 200 }

Координаты `at` и `rect` — мм от `origin` помещения, как `ceiling` у точек электрики.
Прибор стоит у стены: `offset` — от начала стены до середины подводки. Какие подводы
нужны прибору, на какой высоте и какого диаметра — `FIXTURE_SPECS`; высоты из источника
(`supply_height`, `drain_height`) важнее типовых. Типовые — допущение, оно перечисляется
на листе. Трассы идут по полу (вода — в стяжке), в обход стен и препятствий; канализация —
не через дверные проёмы, отводами 45°, в стяжке или скрыто (короб, инсталляция, под
ванной); считает их `plumbing/network.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from floorplan_engine.model.schema import ID_PATTERN, StrictModel

PLUMBING_FILE = "plumbing.yaml"
SEWER_INLET_MM = 100.0  # ось врезки в стояк от чистого пола — допущение, если не задана


class FixtureType(StrEnum):
    WC = "wc"  # унитаз напольный
    WC_INSTALLATION = "wc_installation"  # унитаз подвесной на инсталляции
    SINK = "sink"  # умывальник
    KITCHEN_SINK = "kitchen_sink"  # мойка на кухне
    BATH = "bath"  # ванна: смеситель на стене, выпуск у пола
    SHOWER = "shower"  # душ: смеситель на стене, трап поддона
    WASHER = "washer"  # стиральная машина
    DISHWASHER = "dishwasher"  # посудомоечная машина
    BOILER = "boiler"  # бойлер: вход холодной, выход горячей
    HYGIENIC_SHOWER = "hygienic_shower"  # гигиенический душ: смеситель без выпуска


@dataclass(frozen=True)
class FixtureSpec:
    """Подводы прибора: холодная, горячая, выпуск (диаметр, мм) и типовые высоты оси от
    чистого пола, мм. Высоты — ориентир по типовым моделям; у конкретной модели — по паспорту."""

    cold: bool
    hot: bool
    sewer: int | None  # Ø выпуска, мм; None — без канализации
    supply_height: float
    drain_height: float | None
    hot_source: bool = False  # выдаёт горячую воду (бойлер)


FIXTURE_SPECS: dict[FixtureType, FixtureSpec] = {
    FixtureType.WC: FixtureSpec(True, False, 110, 200.0, 180.0),
    FixtureType.WC_INSTALLATION: FixtureSpec(True, False, 110, 1000.0, 230.0),
    FixtureType.SINK: FixtureSpec(True, True, 50, 550.0, 500.0),
    FixtureType.KITCHEN_SINK: FixtureSpec(True, True, 50, 550.0, 500.0),
    FixtureType.BATH: FixtureSpec(True, True, 50, 800.0, 100.0),  # сифон ванны на ножках
    FixtureType.SHOWER: FixtureSpec(True, True, 50, 1100.0, 50.0),
    FixtureType.WASHER: FixtureSpec(True, False, 50, 700.0, 600.0),
    FixtureType.DISHWASHER: FixtureSpec(True, False, 50, 400.0, 400.0),
    FixtureType.BOILER: FixtureSpec(True, False, None, 1300.0, None, hot_source=True),
    FixtureType.HYGIENIC_SHOWER: FixtureSpec(True, True, None, 800.0, None),
}
# Приборы, которые бывают вне мокрых помещений (кухня, коридор, кладовка)
DRY_ROOM_FIXTURES = frozenset(
    {FixtureType.KITCHEN_SINK, FixtureType.DISHWASHER, FixtureType.WASHER, FixtureType.BOILER}
)


class ObstacleType(StrEnum):
    INSTALLATION = "installation"  # рама инсталляции в коробе
    BATH = "bath"
    SHOWER_TRAY = "shower_tray"  # душевой поддон
    BOX = "box"  # короб из гипсокартона
    CABINET = "cabinet"  # шкаф, тумба на полу
    COLUMN = "column"
    OTHER = "other"


class Riser(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    room: str = Field(description="Помещение, в котором (или в стене которого) стояк")
    at: tuple[float, float] = Field(description="Центр стояка, мм от origin помещения")
    sewer: bool = Field(default=True, description="Стояк канализации Д110")
    water: bool = Field(default=False, description="Стояки холодной и горячей воды рядом")
    sewer_inlet: float | None = Field(
        default=None,
        ge=-35,
        le=1000,
        description=f"Ось врезки в стояк от чистого пола, мм; ниже пола (в стяжке 90 мм) — "
        f"отрицательная, не ниже -35: низ тройника Ø110 — на плите; нет — {SEWER_INLET_MM:g} "
        "допущением",
    )


class WaterInput(StrictModel):
    """Узел ввода: краны, фильтр, редуктор, счётчики и коллекторы — на стене."""

    room: str
    wall: str = Field(description="id стены помещения")
    offset: float = Field(ge=0, description="От начала стены до середины узла, мм")
    hot: bool | None = Field(
        default=None,
        description="Горячая вода из стояка (централизованная); нет — от бойлера, если он "
        "есть, иначе из стояка допущением",
    )
    meters: bool | None = Field(default=None, description="Счётчики в узле; только из источника")
    height: float | None = Field(
        default=None,
        ge=0,
        le=2500,
        description="Ось выходов коллекторов от чистого пола, мм (узел над инсталляцией — "
        "выше неё); нет — 400 допущением",
    )


class Fixture(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    room: str
    type: FixtureType
    wall: str = Field(description="id стены, у которой прибор")
    offset: float = Field(ge=0, description="От начала стены до середины подводки, мм")
    supply_height: float | None = Field(
        default=None, ge=0, le=2500, description="Ось водорозеток от чистого пола, мм"
    )
    drain_height: float | None = Field(
        default=None, ge=0, le=1500, description="Ось выпуска от чистого пола, мм"
    )
    note: str | None = None

    @property
    def spec(self) -> FixtureSpec:
        return FIXTURE_SPECS[self.type]


class Obstacle(StrictModel):
    """Препятствие на полу: прямоугольник у стены (wall, offset — от начала стены до края,
    width — вдоль стены, depth — от стены в помещение) или rect [x0, y0, x1, y1] от origin."""

    id: str = Field(pattern=ID_PATTERN)
    room: str
    type: ObstacleType
    wall: str | None = None
    offset: float | None = Field(default=None, ge=0)
    width: float | None = Field(default=None, gt=0)
    depth: float | None = Field(default=None, gt=0)
    rect: tuple[float, float, float, float] | None = None
    height: float | None = Field(default=None, gt=0, le=3000, description="Высота, мм (короб)")
    note: str | None = None

    @model_validator(mode="after")
    def _placement(self) -> Obstacle:
        by_wall = (self.wall, self.offset, self.width, self.depth)
        if self.rect is not None:
            if any(v is not None for v in by_wall):
                raise ValueError("rect или wall + offset + width + depth — что-то одно")
            x0, y0, x1, y1 = self.rect
            if x1 <= x0 or y1 <= y0:
                raise ValueError("rect: [x0, y0, x1, y1], x1 > x0 и y1 > y0")
        elif any(v is None for v in by_wall):
            raise ValueError("нужно rect или все четыре: wall, offset, width, depth")
        return self


Distribution = Literal["collector", "tee"]


class Plumbing(StrictModel):
    units: Literal["mm"] = "mm"
    distribution: Distribution = Field(
        default="collector",
        description="collector — лучевая от коллекторов (по умолчанию); tee — тройниковая, эконом",
    )
    route: Literal["floor"] = Field(default="floor", description="Трассы — по полу")
    risers: list[Riser] = Field(default_factory=list)
    input: WaterInput | None = Field(
        default=None, description="Узел ввода; нет — у водяного стояка допущением"
    )
    fixtures: list[Fixture] = Field(default_factory=list)
    obstacles: list[Obstacle] = Field(default_factory=list)
