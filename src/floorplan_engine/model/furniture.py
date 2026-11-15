"""furniture.yaml: the furniture of the flat from the design's furniture plan (decision
2026-11-15). Only rectangles along the room axes: what matters to the other stages is where a
piece stands and whether it stands on the floor all over (`solid`) or on legs (`legs`).

    units: mm
    items:
      - { id: kitchen_1, room: hall, at: [0, 1900], size: [3200, 600], kind: kitchen,
          note: "кухня, нижние модули" }
      - { id: bed, room: bedroom, at: [700, 1200], size: [1600, 2000], kind: bed }
      - { id: chest, room: bedroom, at: [0, 0], size: [900, 450], kind: other, base: solid }

`at` is the lower left corner, mm from the room `origin` (like `HeatingExclude.at`), `size` is
the size along X and Y of the room: a piece turned by 90° just has its sides swapped, other
angles are not drawn. The file is optional and may be edited by hand; no file, no furniture.

`base` by default follows `kind` (SOLID_KINDS): a kitchen, an island, a wardrobe, a cabinet and a
TV stand stand on a plinth (`solid`), a bed, a sofa and a table on legs (`legs`); `other` has no
default, `base` is required there. Floor heating is not laid under `solid` furniture
(electrical/floor_heating.py), `legs` does not change it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from floorplan_engine.model.schema import ID_PATTERN, HeatingExclude, StrictModel

FURNITURE_FILE = "furniture.yaml"


class FurnitureKind(StrEnum):
    KITCHEN = "kitchen"  # kitchen base units
    ISLAND = "island"  # kitchen island
    WARDROBE = "wardrobe"  # wardrobe, built-in closet
    CABINET = "cabinet"  # chest of drawers, sideboard, bathroom vanity on the floor
    TV_STAND = "tv_stand"  # TV stand
    BED = "bed"
    SOFA = "sofa"
    TABLE = "table"  # table, desk
    OTHER = "other"  # anything else: base is required


class FurnitureBase(StrEnum):
    SOLID = "solid"  # on a plinth or on the floor all over: no floor heating under it
    LEGS = "legs"  # on legs: the floor under it is open


# Kinds standing on the floor all over by default; OTHER has no default
SOLID_KINDS = frozenset(
    {
        FurnitureKind.KITCHEN,
        FurnitureKind.ISLAND,
        FurnitureKind.WARDROBE,
        FurnitureKind.CABINET,
        FurnitureKind.TV_STAND,
    }
)
LEGS_KINDS = frozenset({FurnitureKind.BED, FurnitureKind.SOFA, FurnitureKind.TABLE})


class FurnitureItem(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    room: str
    at: tuple[float, float] = Field(description="Левый нижний угол, мм от origin помещения")
    size: tuple[float, float] = Field(description="Размер по X и по Y помещения, мм")
    kind: FurnitureKind
    base: FurnitureBase | None = Field(
        default=None,
        description="solid — глухая (на цоколе), legs — на ножках; нет — по kind (у other "
        "обязательно)",
    )
    note: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> FurnitureItem:
        if self.size[0] <= 0 or self.size[1] <= 0:
            raise ValueError(f"size {list(self.size)}: обе стороны больше нуля")
        if self.kind is FurnitureKind.OTHER and self.base is None:
            raise ValueError("у kind: other укажите base: solid (глухая) или legs (на ножках)")
        return self

    @property
    def resting(self) -> FurnitureBase:
        """How it stands: base from the file, else by kind."""
        if self.base is not None:
            return self.base
        return FurnitureBase.SOLID if self.kind in SOLID_KINDS else FurnitureBase.LEGS

    @property
    def solid(self) -> bool:
        return self.resting is FurnitureBase.SOLID

    @property
    def base_assumed(self) -> bool:
        return self.base is None


class Furniture(StrictModel):
    units: Literal["mm"] = "mm"
    items: list[FurnitureItem] = Field(default_factory=list)


def solid_spots(furniture: Furniture) -> dict[str, list[HeatingExclude]]:
    """Room id → rectangles of the solid furniture (no floor heating under them), in file order;
    the note names the piece for the sheet and the zone card."""
    out: dict[str, list[HeatingExclude]] = {}
    for item in furniture.items:
        if item.solid:
            spot = HeatingExclude(at=item.at, size=item.size, note=f"{FURNITURE_FILE}: {item.id}")
            out.setdefault(item.room, []).append(spot)
    return out
