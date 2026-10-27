"""ID объектов проекта внутри DXF: XDATA приложения FLOORPLAN_ENGINE на каждом примитиве модели.

Метка — тип объекта и его id из YAML:

    room       id комнаты          контур площади, название, площадь
    wall       комната.стена       грани, откосы, штриховка («living.w3»)
    dimension  комната.стена       размеры стены
    opening    id проёма           створка, дуга, окно, подпись подоконника
    point      id точки            символ (вставка блока с атрибутами ID, H, GROUP)
    label      id точек через «,»  подпись группы соседних точек
    board      board               щит и его подпись
    cable      id кабеля           трасса и её подпись
    led_strip  id ленты            лента и её подпись

AutoCAD сохраняет XDATA при копировании, переносе, растяжении и в DWG. По меткам
команда update сопоставит правки в AutoCAD с моделью, а кабинет — примитивы страницы
с объектами проекта.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from ezdxf.document import Drawing
from ezdxf.entities.dxfentity import DXFEntity
from ezdxf.layouts.base import BaseLayout

APP_ID = "FLOORPLAN_ENGINE"
_CODE = 1000  # строка XDATA


def register_app(doc: Drawing) -> None:
    if APP_ID not in doc.appids:
        doc.appids.add(APP_ID)


def set_object_id(entity: DXFEntity, kind: str, object_id: str) -> None:
    entity.set_xdata(APP_ID, [(_CODE, kind), (_CODE, object_id)])


def object_id(entity: DXFEntity) -> tuple[str, str] | None:
    """(тип, id) из метки FLOORPLAN_ENGINE или None, если примитив не наш."""
    if not entity.has_xdata(APP_ID):
        return None
    values = [str(tag.value) for tag in entity.get_xdata(APP_ID) if tag.code == _CODE]
    if len(values) != 2:
        return None
    return values[0], values[1]


@contextmanager
def tagged(layout: BaseLayout, kind: str, object_id: str) -> Iterator[None]:
    """Пометить всё, что добавлено в layout внутри блока with."""
    start = len(layout)
    yield
    for k in range(start, len(layout)):
        set_object_id(layout[k], kind, object_id)
