"""Project object IDs inside the DXF: XDATA of application FLOORPLAN_ENGINE on every model
primitive.

A tag is the object type and its id from YAML:

    room       room id             area outline, name, area
    wall       room.wall           faces, reveals, hatch ("living.w3")
    dimension  room.wall           wall dimensions
    opening    opening id          leaf, swing arc, window, sill label
    point      point id            symbol (block insert with attributes ID, H, GROUP)
    label      point ids with ","  label of a group of neighbouring points
    board      board               panel and its label
    cable      cable id            route and its label
    led_strip  strip id            strip and its label

AutoCAD keeps XDATA on copy, move, stretch and in DWG. The update command will match
AutoCAD edits to the model by these tags, and the viewer matches page primitives to
project objects.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from ezdxf.document import Drawing
from ezdxf.entities.dxfentity import DXFEntity
from ezdxf.layouts.base import BaseLayout

APP_ID = "FLOORPLAN_ENGINE"
_CODE = 1000  # XDATA string


def register_app(doc: Drawing) -> None:
    if APP_ID not in doc.appids:
        doc.appids.add(APP_ID)


def set_object_id(entity: DXFEntity, kind: str, object_id: str) -> None:
    entity.set_xdata(APP_ID, [(_CODE, kind), (_CODE, object_id)])


def object_id(entity: DXFEntity) -> tuple[str, str] | None:
    """(type, id) from the FLOORPLAN_ENGINE tag, or None if the primitive is not ours."""
    if not entity.has_xdata(APP_ID):
        return None
    values = [str(tag.value) for tag in entity.get_xdata(APP_ID) if tag.code == _CODE]
    if len(values) != 2:
        return None
    return values[0], values[1]


@contextmanager
def tagged(layout: BaseLayout, kind: str, object_id: str) -> Iterator[None]:
    """Tag everything added to layout inside the with block."""
    start = len(layout)
    yield
    for k in range(start, len(layout)):
        set_object_id(layout[k], kind, object_id)
