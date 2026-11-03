"""Pydantic models of the input YAML: room.yaml (plan) and electrical.yaml (electrical).

Conventions:
- all sizes in millimetres;
- room walls are listed clockwise along the inner outline, starting at `origin` (the
  bottom-left inner corner); the first wall goes up by default;
- `turn` is the room's inner angle between a wall and the next one:
  90 is a normal corner, 270 the reflex corner of an L-shaped room, 180 means the wall goes on
  straight;
- every object has a stable `id`: a wall is unique within its room; a room, opening, point,
  cable, LED strip within the project. Walls are referenced by `id`, not by number: the
  number changes when a wall is added or removed, the `id` does not.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from floorplan_engine.model.panel_catalog import BRANDS, ENCLOSURE_BY_ARTICLE
from floorplan_engine.model.texts import Language

ID_PATTERN = r"^[A-Za-z0-9_\-]+$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


# --- Plan -------------------------------------------------------------------


class Wall(StrictModel):
    id: str = Field(pattern=ID_PATTERN, description="Уникален в комнате: w1, w2…")
    length: float = Field(gt=0, description="Длина по внутреннему контуру, мм")
    turn: float = Field(
        default=90, gt=0, lt=360, description="Внутренний угол к следующей стене, градусы"
    )
    thickness: float | None = Field(
        default=None, gt=0, description="Толщина, мм; по умолчанию default_wall_thickness"
    )
    bearing: bool = Field(default=False, description="Несущая стена (штрихуется)")
    partition: bool = Field(
        default=False,
        description="Ненесущая перегородка любой толщины (из источника или со слов заказчика): "
        "трубы сквозь неё можно",
    )

    @model_validator(mode="after")
    def _bearing_or_partition(self) -> Wall:
        if self.bearing and self.partition:
            raise ValueError("стена не может быть и несущей (bearing), и перегородкой (partition)")
        return self


class OpeningType(StrEnum):
    DOOR = "door"
    WINDOW = "window"
    OPENING = "opening"  # opening without a door or window


class Opening(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    wall: str = Field(description="id стены в этой комнате")
    type: OpeningType
    offset: float = Field(ge=0, description="От начала стены до края проёма, мм")
    width: float = Field(gt=0)
    sill: float | None = Field(default=None, ge=0, le=3000, description="Высота подоконника")
    height: float | None = Field(default=None, gt=0, le=3000, description="Высота проёма")
    hinge: Literal["start", "end"] = Field(
        default="start", description="Петли двери со стороны начала или конца стены"
    )
    swing: Literal["in", "out"] = Field(default="in", description="Открывание внутрь/наружу")

    @model_validator(mode="after")
    def _sill_only_for_windows(self) -> Opening:
        if self.sill is not None and self.type is not OpeningType.WINDOW:
            raise ValueError("подоконник (sill) бывает только у окна (type: window)")
        return self


class Room(StrictModel):
    id: str = Field(pattern=ID_PATTERN, description="Латиница, цифры, _ и -")
    name: str = Field(min_length=1)
    origin: tuple[float, float] = (0.0, 0.0)
    start_angle: float = Field(
        default=90, description="Направление первой стены, градусы (90 — вверх)"
    )
    walls: list[Wall] = Field(min_length=3)
    openings: list[Opening] = Field(default_factory=list)
    wet: bool = Field(
        default=False, description="Влажное помещение (санузел, ванная, прачечная): коробки IP44"
    )

    def wall_index(self, wall_id: str) -> int | None:
        """Wall index in the walk by its id; None if there is no such wall."""
        return next((k for k, w in enumerate(self.walls) if w.id == wall_id), None)


SheetFormat = Literal["auto", "A4", "A3", "A2", "A1", "A0"]


class Signature(StrictModel):
    role: str = Field(min_length=1, max_length=12, description="Разраб., Пров., Н.контр. …")
    name: str = Field(default="", max_length=20)
    date: str | None = Field(default=None, description="ММ.ГГ; по умолчанию — дата сборки")


class SheetInfo(StrictModel):
    """Title block per form 3 of DSTU B A.2.4-4:2009: box numbers are in the field descriptions."""

    code: str = Field(default="", description="Графа 1: обозначение документа")
    object: str | None = Field(default=None, description="Графа 2: объект; по умолчанию name")
    building: str = Field(default="", description="Графа 3: здание, помещение")
    stage: str = Field(default="", max_length=3, description="Графа 6: стадия (П, Р)")
    organization: str = Field(default="", description="Графа 9: организация")
    format: SheetFormat = Field(default="auto", description="Формат листа (ГОСТ 2.301 по ДСТУ)")
    signatures: list[Signature] = Field(default_factory=list, max_length=8)


class Studio(StrictModel):
    """Studio profile (studio.yaml next to the project folders): shared title block boxes.

    Applied to the `sheet` of every project where that box is empty. Boxes specific to a
    project (designation, object, building) are not set here.
    """

    organization: str = Field(default="", description="Графа 9: организация")
    stage: str = Field(default="", max_length=3, description="Графа 6: стадия (П, Р)")
    signatures: list[Signature] = Field(default_factory=list, max_length=8)


CEILING_MIN = 2000  # ceiling height, mm: editable in the viewer from 2 to 4 m
CEILING_MAX = 4000


class Plan(StrictModel):
    units: Literal["mm"] = "mm"
    name: str = Field(min_length=1)
    default_wall_thickness: float = Field(gt=0)
    ceiling_height: float = Field(
        default=2700, gt=0, description="Высота потолка, мм; не задана — 2700 (допущение)"
    )
    rooms: list[Room] = Field(min_length=1)
    source: Literal["photo", "text", "measured"]
    language: Language = Field(default="ru", description="Язык надписей на чертеже: ru | uk")
    sheet: SheetInfo = Field(default_factory=SheetInfo)


# --- Electrical -------------------------------------------------------------


class PointType(StrEnum):
    SOCKET = "socket"
    SWITCH = "switch"  # keys: 1 or 2 keys
    PASS_SWITCH = "pass_switch"  # two-way switch
    LIGHT = "light"  # ceiling light (general)
    DOWNLIGHT = "downlight"  # spot light
    PENDANT = "pendant"  # pendant
    SCONCE = "sconce"  # wall lamp
    DATA = "data"  # internet
    TV = "tv"  # TV socket
    LED_OUTPUT = "led_output"  # lighting output (LED only)
    OUTLET = "outlet"  # power cable output to an appliance: hood, air conditioner, towel rail


# Lights: what switches turn on ("Lighting" sheet)
LIGHT_TYPES = frozenset(
    {
        PointType.LIGHT,
        PointType.DOWNLIGHT,
        PointType.PENDANT,
        PointType.SCONCE,
        PointType.LED_OUTPUT,
    }
)
SWITCH_TYPES = frozenset({PointType.SWITCH, PointType.PASS_SWITCH})

# What may hang on the ceiling and what may only hang there
CEILING_TYPES = frozenset({PointType.LIGHT, PointType.DOWNLIGHT, PointType.PENDANT})
CEILING_ONLY_TYPES = frozenset({PointType.DOWNLIGHT, PointType.PENDANT})


class ElectricalPoint(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    room: str
    type: PointType
    wall: str | None = Field(default=None, description="id стены комнаты")
    offset: float | None = Field(default=None, ge=0)
    ceiling: tuple[float, float] | None = Field(
        default=None, description="Координаты на потолке относительно origin комнаты"
    )
    height: float | None = Field(default=None, description="Высота от чистого пола, мм")
    count: int = Field(default=1, ge=1, le=6, description="Постов в блоке")
    keys: int = Field(default=1, ge=1, le=2, description="Клавиш у выключателя")
    group: str | None = None
    note: str | None = None
    controls: list[str] = Field(
        default_factory=list,
        description="У выключателя: id светильников, выводов LED и лент, которые он включает — "
        "только из источника; нет — связь по группе и помещению (допущение, лист «Освещение»)",
    )
    power: float | None = Field(
        default=None,
        gt=0,
        description="Мощность потребителя, Вт — только из источника; нет — типовая по виду "
        "и пометке (допущение, лист щита)",
    )

    @model_validator(mode="after")
    def _placement(self) -> ElectricalPoint:
        on_wall = self.wall is not None or self.offset is not None
        if on_wall and self.ceiling is not None:
            raise ValueError("укажите либо wall + offset, либо ceiling — не всё сразу")
        if self.ceiling is None:
            if self.wall is None or self.offset is None:
                raise ValueError("для точки на стене нужны и wall, и offset (или ceiling)")
            if self.height is None:
                raise ValueError("для точки на стене нужна высота height, мм")
        elif self.type not in CEILING_TYPES:
            allowed = ", ".join(sorted(t.value for t in CEILING_TYPES))
            raise ValueError(f"на потолке может быть только {allowed}, а не {self.type.value}")
        if self.ceiling is None and self.type in CEILING_ONLY_TYPES:
            raise ValueError(f"{self.type.value} ставится только на потолок: укажите ceiling")
        if self.keys > 1 and self.type is not PointType.SWITCH:
            raise ValueError("keys (число клавиш) бывает только у switch")
        if self.controls and self.type not in SWITCH_TYPES:
            raise ValueError("controls (что включает) бывает только у выключателя")
        return self


class Board(StrictModel):
    room: str
    wall: str = Field(description="id стены комнаты")
    offset: float = Field(ge=0, description="От начала стены до середины щита, мм")
    height: float
    name: str = "ЩР"
    width: float = Field(default=300, gt=0)


class Cable(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    from_: str = Field(alias="from", description="board или id точки")
    to: list[str] = Field(min_length=1)
    group: str | None = None
    cable: str = Field(min_length=1, description="Марка/сечение, напр. 3x2.5")
    route: Literal["wall", "ceiling", "floor"] = Field(
        default="wall", description="floor — по полу в стяжке; wall и ceiling — по потолку"
    )
    direct: bool | None = Field(
        default=None,
        description="Каждая точка — своей линией от щита, без коробок. По умолчанию — да "
        "для сечения от 4 мм², выводов к технике и слаботочки",
    )


class LedStrip(StrictModel):
    """LED strip along a wall: the part from start to end (mm from the wall start)."""

    id: str = Field(pattern=ID_PATTERN)
    room: str
    wall: str = Field(description="id стены комнаты")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    note: str | None = None

    @model_validator(mode="after")
    def _order(self) -> LedStrip:
        if self.end <= self.start:
            raise ValueError(f"end {self.end:g} должен быть больше start {self.start:g}")
        return self


class Group(StrictModel):
    """Panel group: purpose and device only from the source (never invented)."""

    name: str | None = Field(default=None, description="Назначение: «Розетки кухні»")
    breaker: str | None = Field(default=None, description="Автомат: «C16», «B10»")
    rcd: str | None = Field(default=None, description="УЗО / диф: «30 мА»")


# Panel scheme (decision 2026-10-27): economy has the fewest devices, wet zones under one RCD,
# manual backup input; standard has a voltage relay, wet zones on RCBOs, ATS; premium adds
# a surge protector, all groups on RCBOs, curve B
PanelScheme = Literal["economy", "standard", "premium"]
Earthing = Literal["TN-C-S", "TN-S", "TT"]


class PanelSetup(StrictModel):
    """Panel front view ("Panel" sheet): supply, scheme and backup. Supply ratings and power only
    from the source (grid connection terms, contract); otherwise an assumption and a question on
    the sheet."""

    phases: Literal[1, 3] = Field(default=1, description="Фаз на вводе: пока только 1")
    earthing: Earthing = Field(
        default="TN-C-S", description="Система заземления: TN-C-S | TN-S; TT — позже"
    )
    scheme: PanelScheme | None = Field(
        default=None,
        description="economy | standard | premium; не задана — по mode (proper → premium)",
    )
    input: int | None = Field(default=None, gt=0, description="Вводной автомат, А")
    power: float | None = Field(default=None, gt=0, description="Выделенная мощность, кВт")
    voltage_relay: bool | None = Field(
        default=None, description="Реле напряжения; по умолчанию — во всех схемах"
    )
    spd: bool | None = Field(default=None, description="УЗИП; по умолчанию — только premium")
    backup: Literal["none", "inverter", "plug"] | None = Field(
        default=None,
        description="Резерв: none — нет, inverter — гибридный инвертор с АКБ, plug — генератор "
        "через силовую вилку; не задан — вопрос, допущение inverter",
    )
    ats: bool | None = Field(
        default=None,
        description="АВР вместо ручного переключателя; по умолчанию — только у инвертора без "
        "своего переключения (inverter: basic)",
    )
    inverter: Literal["hybrid", "basic"] | None = Field(
        default=None,
        description="Инвертор: hybrid — сам переключает сеть и АКБ (резерв — обходным "
        "переключателем), basic — без своего переключения (резерв — через АВР); не задан — "
        "hybrid (допущение)",
    )
    npe_relay: bool | None = Field(
        default=None,
        description="Связь N–PE в резервном режиме есть (реле инвертора или контактор); "
        "не задано — вопрос: без неё УЗО на резерве не сработают",
    )
    brand: str = Field(
        default="generic", description="Бренд аппаратов щита — модели из каталога (panel_catalog)"
    )
    enclosure: str | None = Field(
        default=None,
        description="Корпус щита — артикул из каталога (panel_catalog, «VS218PD»); не задан — "
        "самый маленький, куда помещаются аппараты",
    )
    backup_power: float | None = Field(
        default=None, gt=0, description="Мощность инвертора или генератора, кВт"
    )
    battery_voltage: Literal[12, 24, 48] | None = Field(
        default=None, description="Напряжение АКБ инвертора, В; не задано — 48 (допущение)"
    )
    battery_capacity: float | None = Field(
        default=None, gt=0, description="Ёмкость АКБ, кВт·ч — только из источника"
    )
    pv_strings: int | None = Field(
        default=None,
        ge=0,
        le=2,
        description="Строк солнечных панелей на инвертор (0–2); не задано — панелей нет (вопрос)",
    )
    reserve: list[str] = Field(
        default_factory=list,
        description="Группы на резервной шине; пусто — свет, холодильник, роутер, котёл, "
        "насос, ворота, розетки кухни (допущение)",
    )

    @model_validator(mode="after")
    def _setup(self) -> PanelSetup:
        if self.phases != 1:
            raise ValueError("трёхфазный щит пока не поддерживается: phases: 1")
        if self.earthing == "TT":
            raise ValueError("система TT пока не поддерживается: earthing: TN-C-S или TN-S")
        if self.reserve and self.backup == "none":
            raise ValueError("reserve — только с резервом (backup: inverter | plug)")
        dc: tuple[object, ...] = (self.battery_voltage, self.battery_capacity, self.pv_strings)
        dc += (self.inverter, self.npe_relay)
        if self.backup in ("none", "plug") and any(v is not None for v in dc):
            raise ValueError(
                "battery_voltage, battery_capacity, pv_strings, inverter, npe_relay — только "
                "с инвертором "
                "(backup: inverter)"
            )
        if self.brand not in BRANDS:
            raise ValueError(f"бренда «{self.brand}» нет в каталоге: {', '.join(sorted(BRANDS))}")
        if self.enclosure is not None and self.enclosure not in ENCLOSURE_BY_ARTICLE:
            names = ", ".join(ENCLOSURE_BY_ARTICLE)
            raise ValueError(f"щита «{self.enclosure}» нет в каталоге: {names}")
        return self


# Electrical layout (decision 2026-10-25): economy has fewer breakers, low budget;
# standard gives lights and sockets of each room their own group; proper is "done right"
ElectricalMode = Literal["economy", "standard", "proper"]


class Electrical(StrictModel):
    units: Literal["mm"] = "mm"
    mode: ElectricalMode = Field(
        default="standard",
        description="Раскладка: economy — меньше автоматов; standard — помещения отдельными "
        "группами; proper — по правильному",
    )
    route: Literal["ceiling", "floor"] | None = Field(
        default=None,
        description="Трасса групп без своего кабеля в cables: floor — по полу в стяжке; "
        "нет — по потолку. Ставит вариант проводки (variant.yaml) или источник",
    )
    routes: list[Literal["ceiling", "floor"]] | None = Field(
        default=None,
        min_length=1,
        description="Трассы, допустимые в проекте (варианты проводки): [ceiling] — по полу "
        "проводки не будет. Нет — обе; только со слов заказчика или из источника",
    )
    groups: dict[str, Group] = Field(
        default_factory=dict, description="Группы щита по имени (QF4): назначение, автомат"
    )
    points: list[ElectricalPoint] = Field(default_factory=list)
    board: Board | None = None
    cables: list[Cable] = Field(default_factory=list)
    led_strips: list[LedStrip] = Field(default_factory=list)
    panel: PanelSetup = Field(default_factory=PanelSetup, description="Щит в лицо: схема, ввод")

    @model_validator(mode="after")
    def _routes(self) -> Electrical:
        if self.routes is None:
            return self
        if len(set(self.routes)) != len(self.routes):
            raise ValueError("routes: трассы не повторяются")
        if self.route is not None and self.route not in self.routes:
            raise ValueError(f"route: {self.route} — такой трассы нет в routes {list(self.routes)}")
        if "floor" not in self.routes and any(c.route == "floor" for c in self.cables):
            raise ValueError(f"cables: трасса floor не входит в routes {list(self.routes)}")
        return self


# --- Manual wiring edits (wiring.yaml) ---------------------------------------


class WireEdit(StrictModel):
    """Line route dragged in the viewer: points in model mm, from source to target.
    from / to are a check: if the line with this id now goes differently, the edit is not applied.
    Slanted pieces only in economy: checked by the build (wiring._manual_runs)."""

    from_: str = Field(alias="from", description="board или id коробки")
    to: str = Field(description="id коробки или точки")
    path: list[tuple[float, float]] = Field(min_length=2)


class BoxEdit(StrictModel):
    """Spot of a junction box moved in the viewer, model mm. A wall box gets a point on its wall.
    room and group are a check: if the box with this id is now a different one, the edit is
    not applied."""

    room: str
    group: str
    at: tuple[float, float]


class WiringEdits(StrictModel):
    """wiring.yaml: wiring edits from the viewer: lines and boxes by wiring sheet id.
    Everything else is built automatically; loads and the panel do not move."""

    wires: dict[str, WireEdit] = Field(default_factory=dict)
    boxes: dict[str, BoxEdit] = Field(default_factory=dict)


WireRoute = Literal["ceiling", "floor"]
Distribution = Literal["boxes"]  # loop: daisy chain, later (docs/wiring-variants.md)


class Variant(StrictModel):
    """variant.yaml: the wiring variant chosen in the viewer (docs/wiring-variants.md): mode, route
    and distribution. Points come from the project and do not change between variants. Ceiling
    height (mm) is an edit from the "Overview" page: it is applied on top of room.yaml, the
    original is not changed."""

    mode: ElectricalMode = "standard"
    route: WireRoute = "ceiling"
    distribution: Distribution = "boxes"
    ceiling_height: float | None = Field(default=None, ge=CEILING_MIN, le=CEILING_MAX)

    @property
    def key(self) -> str:
        """Key such as "economy-floor-boxes": the key for this variant's route edits in
        wiring.yaml."""
        return f"{self.mode}-{self.route}-{self.distribution}"


class WiringFile(StrictModel):
    """wiring.yaml: route edits by variant (variants: {variant key: edits}). Top-level wires and
    boxes are edits written before variants existed: they belong to the "as in project"
    variant (variants.default_variant)."""

    wires: dict[str, WireEdit] = Field(default_factory=dict)
    boxes: dict[str, BoxEdit] = Field(default_factory=dict)
    variants: dict[str, WiringEdits] = Field(default_factory=dict)

    def edits_for(self, key: str, default_key: str) -> WiringEdits | None:
        """Variant edits; the default variant also gets the pre-variant edits."""
        edits = self.variants.get(key)
        if key == default_key and (self.wires or self.boxes):
            base = edits or WiringEdits()
            edits = WiringEdits(
                wires={**self.wires, **base.wires}, boxes={**self.boxes, **base.boxes}
            )
        return edits if edits is not None and (edits.wires or edits.boxes) else None
