"""Pydantic-модели входных YAML: room.yaml (план) и electrical.yaml (электрика).

Соглашения:
- все размеры в миллиметрах;
- стены комнаты перечисляются по часовой стрелке по внутреннему контуру,
  начиная от `origin` (левый нижний внутренний угол); первая стена по умолчанию идёт вверх;
- `turn` — внутренний угол комнаты между стеной и следующей за ней:
  90 — обычный угол, 270 — «входящий» угол Г-образной комнаты, 180 — стена продолжается прямо;
- у каждого объекта стабильный `id`: стена — уникальна в своей комнате, комната, проём, точка,
  кабель, LED-лента — в проекте. Ссылки на стены — по `id`, не по номеру: номер меняется,
  когда стену добавляют или убирают, а `id` нет.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shtroba.texts import Language

ID_PATTERN = r"^[A-Za-z0-9_\-]+$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


# --- План -------------------------------------------------------------------


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


class OpeningType(StrEnum):
    DOOR = "door"
    WINDOW = "window"
    OPENING = "opening"  # проём без заполнения


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
        """Номер стены в обходе по её id; None — такой стены нет."""
        return next((k for k, w in enumerate(self.walls) if w.id == wall_id), None)


SheetFormat = Literal["auto", "A4", "A3", "A2", "A1", "A0"]


class Signature(StrictModel):
    role: str = Field(min_length=1, max_length=12, description="Разраб., Пров., Н.контр. …")
    name: str = Field(default="", max_length=20)
    date: str | None = Field(default=None, description="ММ.ГГ; по умолчанию — дата сборки")


class SheetInfo(StrictModel):
    """Основная надпись по форме 3 ДСТУ Б А.2.4-4:2009: номера граф — в описаниях полей."""

    code: str = Field(default="", description="Графа 1: обозначение документа")
    object: str | None = Field(default=None, description="Графа 2: объект; по умолчанию name")
    building: str = Field(default="", description="Графа 3: здание, помещение")
    stage: str = Field(default="", max_length=3, description="Графа 6: стадия (П, Р)")
    organization: str = Field(default="", description="Графа 9: организация")
    format: SheetFormat = Field(default="auto", description="Формат листа (ГОСТ 2.301 по ДСТУ)")
    signatures: list[Signature] = Field(default_factory=list, max_length=8)


class Studio(StrictModel):
    """Профиль студии (studio.yaml рядом с папками проектов): общие графы штампа.

    Подставляется в `sheet` каждого проекта, где эта графа не заполнена. Графы, свои для
    проекта (обозначение, объект, будинок), здесь не задаются.
    """

    organization: str = Field(default="", description="Графа 9: организация")
    stage: str = Field(default="", max_length=3, description="Графа 6: стадия (П, Р)")
    signatures: list[Signature] = Field(default_factory=list, max_length=8)


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


# --- Электрика --------------------------------------------------------------


class PointType(StrEnum):
    SOCKET = "socket"
    SWITCH = "switch"  # keys: 1 или 2 клавиши
    PASS_SWITCH = "pass_switch"  # проходной
    LIGHT = "light"  # потолочный светильник (общий)
    DOWNLIGHT = "downlight"  # точечный
    PENDANT = "pendant"  # подвесной
    SCONCE = "sconce"  # бра
    DATA = "data"  # интернет
    TV = "tv"  # телевизионная розетка
    LED_OUTPUT = "led_output"  # вывод под подсветку (только LED)
    OUTLET = "outlet"  # силовой вывод кабеля к технике: вытяжка, кондиционер, рушникосушка


# Что может висеть на потолке и что — только там
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
    """LED-подсветка вдоль стены: участок от start до end (мм от начала стены)."""

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
    """Группа щита: назначение и аппарат — только из источника (не выдумываются)."""

    name: str | None = Field(default=None, description="Назначение: «Розетки кухні»")
    breaker: str | None = Field(default=None, description="Автомат: «C16», «B10»")
    rcd: str | None = Field(default=None, description="УЗО / диф: «30 мА»")


# Раскладка электрики (решение 2026-10-25): economy — меньше автоматов, бюджетно;
# standard — свет и розетки каждого помещения своей группой; proper — «по правильному»
ElectricalMode = Literal["economy", "standard", "proper"]


class Electrical(StrictModel):
    units: Literal["mm"] = "mm"
    mode: ElectricalMode = Field(
        default="standard",
        description="Раскладка: economy — меньше автоматов; standard — помещения отдельными "
        "группами; proper — по правильному",
    )
    groups: dict[str, Group] = Field(
        default_factory=dict, description="Группы щита по имени (QF4): назначение, автомат"
    )
    points: list[ElectricalPoint] = Field(default_factory=list)
    board: Board | None = None
    cables: list[Cable] = Field(default_factory=list)
    led_strips: list[LedStrip] = Field(default_factory=list)


# --- Ручные правки проводки (wiring.yaml) ------------------------------------

ORTHO_TOL = 0.5  # мм: участок ручной трассы — по оси, если концы расходятся не больше


class WireEdit(StrictModel):
    """Трасса линии, перетянутая в просмотре: точки в мм модели, от источника к цели.
    from / to — сверка: если линия с этим id теперь идёт не так, правка не применяется."""

    from_: str = Field(alias="from", description="board или id коробки")
    to: str = Field(description="id коробки или точки")
    path: list[tuple[float, float]] = Field(min_length=2)

    @model_validator(mode="after")
    def _ortho(self) -> WireEdit:
        for k, (a, b) in enumerate(zip(self.path, self.path[1:], strict=False)):
            if abs(a[0] - b[0]) > ORTHO_TOL and abs(a[1] - b[1]) > ORTHO_TOL:
                raise ValueError(f"участок {k + 1} трассы не по оси: углы только прямые")
        return self


class BoxEdit(StrictModel):
    """Место распаечной коробки, перенесённой в просмотре, мм модели. У коробки на стене —
    точка на её стене. room и group — сверка: коробка с этим id теперь другая — правка
    не применяется."""

    room: str
    group: str
    at: tuple[float, float]


class WiringEdits(StrictModel):
    """wiring.yaml — правки проводки из просмотра: линии и коробки по id листа проводки.
    Остальное строится автоматически; потребители и щит не двигаются."""

    wires: dict[str, WireEdit] = Field(default_factory=dict)
    boxes: dict[str, BoxEdit] = Field(default_factory=dict)
