"""AutoCAD fields (FIELD) in MTEXT: text that AutoCAD recalculates itself.

ezdxf 1.4 does not create FIELD objects, so the chain is assembled from raw tags:
MTEXT → ACAD_XDICTIONARY → ACAD_FIELD → TEXT (the `_text` container) → child field
`AcObjProp.16.2` with a reference to the object. All fields are registered in the document's
FIELDLIST. Group order and values copy the area fields written by AutoCAD 2024 (reference
project 381922.207.1992-МЗ1: tables and "Площа - …м²" labels).

Area in m² from a model in mm: format `%lu2%pr2%ds44%ct8[1.0…E-006]`: decimal units,
2 digits, comma, factor 1e-6. The DXF stores a cached value; AutoCAD recalculates it on
open and on REGEN.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial

from ezdxf.document import Drawing
from ezdxf.entities.dxfclass import DXFClass
from ezdxf.entities.dxfentity import DXFEntity, DXFTagStorage
from ezdxf.entities.idbuffer import FieldList
from ezdxf.entities.mtext import MText
from ezdxf.lldxf.extendedtags import ExtendedTags
from ezdxf.lldxf.types import DXFTag

FIELD_INDEX = r"%<\_FldIdx 0>%"
OBJ_PROP = "AcObjProp.16.2"
MM2_TO_M2 = 1e-6

# Field value (AcValue): data type in group 90
_TYPE_UNKNOWN, _TYPE_LONG, _TYPE_DOUBLE, _TYPE_STRING, _TYPE_HANDLE = 0, 1, 2, 4, 64
# Evaluation options: 1 open, 2 save, 4 plot, 8 eTransmit, 16 regen, 32 on demand;
# 63 means "automatic"
_EVAL_AUTO = 63
_STATE_MTEXT_CONTAINER = 13
_STATE_CHILD = 59
_STATUS_OK = 2


@dataclass(frozen=True)
class _Value:
    """AcValue: flags, type, body, format and the displayed text."""

    flags: int
    type: int
    body: tuple[DXFTag, ...] = (DXFTag(91, 0),)
    format: str = ""
    shown: str = ""

    def tags(self) -> list[DXFTag]:
        return [
            DXFTag(93, self.flags),
            DXFTag(90, self.type),
            *self.body,
            DXFTag(94, 0),
            DXFTag(300, self.format),
            DXFTag(302, self.shown),
            DXFTag(304, "ACVALUE_END"),
        ]


def area_format(precision: int = 2, comma: bool = True) -> str:
    """Area field format in m² for a model in mm (as AutoCAD writes it)."""
    separator = "%ds44" if comma else ""
    return f"%lu2%pr{precision}{separator}%ct8[1.000000000000000E-006]"


def format_area(area_mm2: float, precision: int = 2, comma: bool = True) -> str:
    """The same value the field will show: 12000000 mm² → "12,00"."""
    text = f"{area_mm2 * MM2_TO_M2:.{precision}f}"
    return text.replace(".", ",") if comma else text


def text_checksum(text: str) -> float:
    """Checksum of the host text: Σ (position + 1) × UTF-16 code."""
    units = text.encode("utf-16-le")
    codes = [int.from_bytes(units[i : i + 2], "little") for i in range(0, len(units), 2)]
    return float(sum((i + 1) * code for i, code in enumerate(codes)))


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _register_classes(doc: Drawing) -> None:
    names = {cls.dxf.name for cls in doc.classes}
    if "FIELDLIST" not in names:
        doc.classes.add_class("FIELDLIST")
    if "FIELD" not in names:
        cls = DXFClass.new(doc=doc)
        cls.update_dxf_attribs(
            {
                "name": "FIELD",
                "cpp_class_name": "AcDbField",
                "app_name": "ObjectDBX Classes",
                "flags": 1152,
                "was_a_proxy": 0,
                "is_an_entity": 0,
            }
        )
        doc.classes.register(cls)


def _add_raw_object(doc: Drawing, handle: str, owner: str, tags: list[DXFTag]) -> DXFTagStorage:
    head = [
        DXFTag(0, "FIELD"),
        DXFTag(5, handle),
        DXFTag(102, "{ACAD_REACTORS"),
        DXFTag(330, owner),
        DXFTag(102, "}"),
        DXFTag(330, owner),
    ]
    entity = DXFTagStorage.load(ExtendedTags(head + tags), doc)
    doc.entitydb.add(entity)
    doc.objects.add_object(entity)  # type: ignore[arg-type]
    return entity


def _field_tags(
    evaluator: str,
    code: str,
    *,
    eval_option: int,
    state: int,
    children: list[str],
    objects: list[str],
    child_values: list[tuple[str, _Value]],
    value: _Value,
) -> list[DXFTag]:
    tags = [
        DXFTag(100, "AcDbField"),
        DXFTag(1, evaluator),
        DXFTag(2, code),
        DXFTag(90, len(children)),
        *(DXFTag(360, h) for h in children),
        DXFTag(97, len(objects)),
        *(DXFTag(331, h) for h in objects),
        DXFTag(91, eval_option),
        DXFTag(92, 0),
        DXFTag(94, state),
        DXFTag(95, _STATUS_OK),
        DXFTag(96, 0),
        DXFTag(300, ""),
        DXFTag(93, len(child_values)),
    ]
    for key, child_value in child_values:
        tags += [DXFTag(6, key), *child_value.tags()]
    tags += [DXFTag(7, "ACFD_FIELD_VALUE"), *value.tags()]
    tags += [DXFTag(301, value.shown), DXFTag(98, _utf16_len(value.shown))]
    return tags


def _area_child_tags(target_h: str, area_mm2: float, fmt: str) -> list[DXFTag]:
    """Field "area of object target_h" (AcObjProp), as AutoCAD 2024 writes it."""
    display = format_area(area_mm2) if "%ct8" in fmt else f"{area_mm2:g}"
    return _field_tags(
        OBJ_PROP,
        rf'\{OBJ_PROP} Object(%<\_ObjIdx 0>%).Area \f "{fmt}"',
        # for a child field AutoCAD keeps the option in ACAD_ROUNDTRIP_2008_FIELD_EVALOPTION
        eval_option=0,
        state=_STATE_CHILD,
        children=[],
        objects=[target_h],
        child_values=[
            (
                "ACAD_ROUNDTRIP_2008_FIELD_EVALOPTION",
                _Value(2, _TYPE_LONG, (DXFTag(91, _EVAL_AUTO),)),
            ),
            ("ObjectPropertyId", _Value(2, _TYPE_HANDLE, (DXFTag(330, target_h),))),
            ("ObjectPropertyName", _Value(2, _TYPE_STRING, (DXFTag(1, "Area"),))),
        ],
        value=_Value(4, _TYPE_DOUBLE, (DXFTag(140, float(area_mm2)),), fmt, display),
    )


def _attach(doc: Drawing, host: MText, prefix: str, display: str, suffix: str, top: _Node) -> None:
    """Turn host into a field: a `_text` container with one child field tree top."""
    _register_classes(doc)
    host.text = f"{prefix}{display}{suffix}"
    xdict = host.new_extension_dict() if not host.has_extension_dict else host.get_extension_dict()
    field_dict = xdict.add_dictionary("ACAD_FIELD", hard_owned=True)
    field_dict.set_reactors([xdict.dictionary.dxf.handle])
    # AutoCAD writes owner-dictionary entries with code 360; ezdxf defaults to 350,
    # and then AutoCAD treats the fields as orphans
    for owner in (xdict.dictionary, field_dict):
        owner._value_code = 360

    container_h = doc.entitydb.next_handle()
    top_h = _add_tree(doc, top, container_h)
    container_tags = _field_tags(
        "_text",
        f"{prefix}{FIELD_INDEX}{suffix}",
        eval_option=_EVAL_AUTO,
        state=_STATE_MTEXT_CONTAINER,
        children=[top_h],
        objects=[],
        child_values=[
            (
                "ACFD_FIELDTEXT_CHECKSUM",
                _Value(2, _TYPE_DOUBLE, (DXFTag(140, text_checksum(host.text)),)),
            )
        ],
        value=_Value(3, _TYPE_UNKNOWN),
    )
    container = _add_raw_object(doc, container_h, field_dict.dxf.handle, container_tags)
    field_dict["TEXT"] = container  # type: ignore[assignment]


@dataclass(frozen=True)
class _Node:
    """Field with child fields: build(child handles) → field tags."""

    build: Callable[[list[str]], list[DXFTag]]
    children: tuple[_Node, ...] = ()


def _add_tree(doc: Drawing, node: _Node, owner: str) -> str:
    # next_handle() advances the counter: the handle is taken even before the object exists
    handle = doc.entitydb.next_handle()
    child_handles = [_add_tree(doc, child, handle) for child in node.children]
    _add_raw_object(doc, handle, owner, node.build(child_handles))
    return handle


def add_area_field(
    doc: Drawing,
    host: MText,
    target: DXFEntity,
    area_mm2: float,
    *,
    precision: int = 2,
    comma: bool = True,
    prefix: str = "",
    suffix: str = "",
) -> None:
    """Turn `host` into the field "area of `target` in m²" with text around it.

    `target` is a closed polyline; `area_mm2` is its current area: a cache for previews and
    programs that do not evaluate fields.
    """
    fmt = area_format(precision, comma)
    node = _Node(lambda _: _area_child_tags(target.dxf.handle, area_mm2, fmt))
    _attach(doc, host, prefix, format_area(area_mm2, precision, comma), suffix, node)


def _leaf_area(target_h: str, area_mm2: float, _children: list[str]) -> list[DXFTag]:
    """Outline area inside an expression: no conversion to m², the expression does that itself."""
    return _area_child_tags(target_h, area_mm2, "%lu2")


def add_area_sum_field(
    doc: Drawing,
    host: MText,
    targets: Sequence[tuple[DXFEntity, float]],
    *,
    precision: int = 2,
    comma: bool = True,
    prefix: str = "",
    suffix: str = "",
) -> None:
    """Field "sum of areas in m²" (AcExpr over the area fields of each outline).

    targets are pairs (polyline, its current area in mm²). AutoCAD substitutes the raw values
    of the child fields (mm²) into the expression, hence sum × 1e-6.
    """
    total = sum(area for _, area in targets)
    fmt = area_format(precision, comma).split("%ct8")[0]
    display = format_area(total, precision, comma)
    terms = "+".join(rf"%<\_FldIdx {k}>%" for k in range(len(targets)))
    code = rf'\AcExpr (({terms})*{MM2_TO_M2:f}) \f "{fmt}"'

    def expr(children: list[str]) -> list[DXFTag]:
        return _field_tags(
            "AcExpr",
            code,
            eval_option=_EVAL_AUTO,
            state=_STATE_CHILD,
            children=children,
            objects=[],
            child_values=[],
            value=_Value(4, _TYPE_DOUBLE, (DXFTag(140, total * MM2_TO_M2),), fmt, display),
        )

    leaves = tuple(_Node(partial(_leaf_area, entity.dxf.handle, area)) for entity, area in targets)
    _attach(doc, host, prefix, display, suffix, _Node(expr, leaves))


def finalize_fields(doc: Drawing) -> None:
    """Write FIELDLIST (ACAD_FIELDLIST in the root dictionary). Call before saveas."""
    handles = [e.dxf.handle for e in doc.objects if e.dxftype() == "FIELD"]
    if not handles:
        return
    root = doc.rootdict
    if "ACAD_FIELDLIST" in root:
        root.remove("ACAD_FIELDLIST")
    field_list = doc.objects.new_entity("FIELDLIST", {"owner": root.dxf.handle})
    assert isinstance(field_list, FieldList)
    field_list.set_reactors([root.dxf.handle])
    # Autodesk's group 90 is the number of fields; ezdxf calls it flags
    field_list.dxf.flags = len(handles)
    field_list.handles = handles
    root["ACAD_FIELDLIST"] = field_list
