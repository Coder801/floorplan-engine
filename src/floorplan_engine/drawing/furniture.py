"""Furniture from furniture.yaml on the plan and on the "Floor heating" sheet (decision
2026-11-15): a thin rectangle on its own layer F-FURN — solid furniture continuous, on legs
dashed — with what it is in the middle (turned along the long side when it does not fit).

Each piece is one object `furniture:<id>`: the viewer shows its card (epd/objects.py).
"""

from __future__ import annotations

from ezdxf.layouts.layout import Modelspace

from floorplan_engine.drawing.ids import tagged
from floorplan_engine.drawing.layers import F_FURN, LED_LINETYPE, TEXT_SMALL_MM, text_width
from floorplan_engine.drawing.plan import add_text
from floorplan_engine.drawing.titleblock import LW_THIN
from floorplan_engine.model.furniture import Furniture, FurnitureItem
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.scale import sheet
from floorplan_engine.model.schema import Plan
from floorplan_engine.model.texts import Language, tr

LABEL_PAD_MM = 1.0  # the label keeps this far from the rectangle sides, sheet mm


def furniture_label(item: FurnitureItem, language: Language) -> str:
    return tr(f"furn_{item.kind.value}", language)


def _draw_item(
    msp: Modelspace, origin: tuple[float, float], item: FurnitureItem, lang: Language
) -> None:
    x, y = origin[0] + item.at[0], origin[1] + item.at[1]
    w, h = item.size
    attribs: dict[str, object] = {"layer": F_FURN.name, "lineweight": LW_THIN}
    if not item.solid:
        attribs |= {"linetype": LED_LINETYPE}
    msp.add_lwpolyline(
        [(x, y), (x + w, y), (x + w, y + h), (x, y + h)], close=True, dxfattribs=attribs
    )
    label = furniture_label(item, lang)
    need = sheet(text_width(label, TEXT_SMALL_MM) + 2 * LABEL_PAD_MM)
    tall = sheet(TEXT_SMALL_MM + 2 * LABEL_PAD_MM)
    along, across = (w, h) if w >= h else (h, w)
    if need > along or tall > across:
        return  # no room for the label: the card says what it is
    angle = 0.0 if w >= h else 90.0
    add_text(msp, label, Vec(x + w / 2, y + h / 2), TEXT_SMALL_MM, F_FURN.name, angle=angle)


def draw_furniture(msp: Modelspace, plan: Plan, furniture: Furniture) -> None:
    """Every piece whose room is in the plan, in file order."""
    rooms = {r.id: r for r in plan.rooms}
    for item in furniture.items:
        room = rooms.get(item.room)
        if room is None:
            continue
        with tagged(msp, "furniture", item.id):
            _draw_item(msp, room.origin, item, plan.language)
