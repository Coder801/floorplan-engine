from __future__ import annotations

from pathlib import Path

from ezdxf.entities.dictionary import Dictionary
from ezdxf.entities.dxfentity import DXFTagStorage
from ezdxf.entities.idbuffer import FieldList
from ezdxf.entities.mtext import MText
from ezdxf.filemanagement import readfile

from floorplan_engine.drawing.fields import (
    add_area_field,
    add_area_sum_field,
    finalize_fields,
    format_area,
    text_checksum,
)
from floorplan_engine.drawing.layers import new_document


def _field_value(tags: list[tuple[int, object]], code: int) -> object:
    return next(value for c, value in tags if c == code)


def test_text_checksum() -> None:
    # Σ (i + 1) × код: 'A' = 65, 'B' = 66 → 65 + 132
    assert text_checksum("AB") == 197.0


def test_text_checksum_matches_autocad() -> None:
    # значение из эталонного DWG (AutoCAD 2024)
    assert text_checksum(r"{\W0.7;2 мм}") == 26685.0


def test_format_area() -> None:
    assert format_area(8_977_769.2, precision=1) == "9,0"
    assert format_area(12_000_000, comma=False) == "12.00"


def test_area_field_round_trip(tmp_path: Path) -> None:
    doc = new_document()
    msp = doc.modelspace()
    room = msp.add_lwpolyline([(0, 0), (0, 3000), (4000, 3000), (4000, 0)], close=True)
    text = msp.add_mtext("")
    add_area_field(doc, text, room, 12_000_000, prefix="Зал ", suffix=" м²")
    finalize_fields(doc)
    path = tmp_path / "f.dxf"
    doc.saveas(path, encoding="utf-8")

    reread = readfile(path)
    assert not reread.audit().has_errors
    mtext = next(iter(reread.modelspace().query("MTEXT")))
    assert isinstance(mtext, MText)
    assert mtext.text == "Зал 12,00 м²"

    field_dict = mtext.get_extension_dict()["ACAD_FIELD"]
    assert isinstance(field_dict, Dictionary)
    container = field_dict["TEXT"]
    assert isinstance(container, DXFTagStorage)
    container_tags = [(t.code, t.value) for t in container.xtags.subclasses[1]]
    assert _field_value(container_tags, 1) == "_text"
    assert _field_value(container_tags, 2) == r"Зал %<\_FldIdx 0>% м²"

    child = reread.entitydb[str(_field_value(container_tags, 360))]
    assert isinstance(child, DXFTagStorage)
    child_tags = [(t.code, t.value) for t in child.xtags.subclasses[1]]
    assert _field_value(child_tags, 1) == "AcObjProp.16.2"
    assert ").Area " in str(_field_value(child_tags, 2))
    room_handle = next(iter(reread.modelspace().query("LWPOLYLINE"))).dxf.handle
    assert _field_value(child_tags, 331) == room_handle
    assert _field_value(child_tags, 140) == 12_000_000.0

    field_list = reread.rootdict["ACAD_FIELDLIST"]
    assert isinstance(field_list, FieldList)
    assert set(field_list.handles) == {container.dxf.handle, child.dxf.handle}
    assert {"FIELD", "FIELDLIST"} <= {cls.dxf.name for cls in reread.classes}


def test_area_sum_field_is_expression_over_area_fields(tmp_path: Path) -> None:
    doc = new_document()
    msp = doc.modelspace()
    a = msp.add_lwpolyline([(0, 0), (0, 3000), (4000, 3000), (4000, 0)], close=True)
    b = msp.add_lwpolyline([(0, 0), (0, 1000), (2000, 1000), (2000, 0)], close=True)
    text = msp.add_mtext("")
    add_area_sum_field(doc, text, [(a, 12_000_000), (b, 2_000_000)])
    finalize_fields(doc)
    path = tmp_path / "sum.dxf"
    doc.saveas(path, encoding="utf-8")

    reread = readfile(path)
    assert not reread.audit().has_errors
    mtext = next(iter(reread.modelspace().query("MTEXT")))
    assert isinstance(mtext, MText)
    assert mtext.text == "14,00"
    container = mtext.get_extension_dict()["ACAD_FIELD"]["TEXT"]
    assert isinstance(container, DXFTagStorage)
    expr = reread.entitydb[str(_field_value(_tags(container), 360))]
    assert isinstance(expr, DXFTagStorage)
    expr_tags = _tags(expr)
    assert _field_value(expr_tags, 1) == "AcExpr"
    assert str(_field_value(expr_tags, 2)).startswith(
        r"\AcExpr ((%<\_FldIdx 0>%+%<\_FldIdx 1>%)*0.000001)"
    )
    leaves = [reread.entitydb[str(v)] for c, v in expr_tags if c == 360]
    targets = {_field_value(_tags(leaf), 331) for leaf in leaves}  # type: ignore[arg-type]
    assert targets == {a.dxf.handle, b.dxf.handle}
    field_list = reread.rootdict["ACAD_FIELDLIST"]
    assert isinstance(field_list, FieldList)
    assert len(field_list.handles) == 4  # контейнер, выражение, два контура


def _tags(entity: DXFTagStorage) -> list[tuple[int, object]]:
    return [(t.code, t.value) for t in entity.xtags.subclasses[1]]
