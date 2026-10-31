from __future__ import annotations

from pathlib import Path

from ezdxf.entities.insert import Insert
from ezdxf.filemanagement import readfile

from floorplan_engine.drawing.ids import APP_ID, object_id
from floorplan_engine.epd.artifact import export_artifact, read_artifact
from floorplan_engine.model.schema import Electrical
from floorplan_engine.sheets.document import build_project_document
from floorplan_engine.validation.issues import parse_model
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan

RECT = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]
POINT = {"room": "r", "wall": "w2", "type": "socket", "height": 300, "group": "QF1"}


def _build(tmp_path: Path) -> Path:
    plan = make_plan(
        RECT, [{"id": "d1", "wall": "w1", "type": "door", "offset": 300, "width": 800}]
    )
    _, contours = validate_plan(plan)
    elec, issues = parse_model(
        Electrical,
        {
            "points": [{"id": "s1", "offset": 500, **POINT}, {"id": "s2", "offset": 1500, **POINT}],
            "board": {"room": "r", "wall": "w3", "offset": 600, "height": 1700},
            "cables": [{"id": "c1", "from": "board", "to": ["s1", "s2"], "cable": "3x2.5"}],
            "led_strips": [{"id": "led1", "room": "r", "wall": "w4", "start": 0, "end": 1000}],
        },
        "e.yaml",
    )
    assert elec is not None, issues
    path = tmp_path / "project.dxf"
    build_project_document(plan, contours, elec).saveas(path, encoding="utf-8")
    return path


def test_every_model_entity_has_project_id(tmp_path: Path) -> None:
    doc = readfile(_build(tmp_path))
    assert APP_ID in doc.appids
    ids = [object_id(e) for e in doc.modelspace()]
    assert None not in ids
    kinds = {oid[0] for oid in ids if oid}
    assert kinds == {
        "wall",
        "dimension",
        "opening",
        "room",
        "point",
        "label",
        "board",
        "led_strip",
        "box",
        "wire",
    }
    pairs = {oid for oid in ids if oid}
    assert {("wall", "r.w1"), ("opening", "d1"), ("room", "r"), ("box", "box_1")} <= pairs
    assert ("led_strip", "led1") in pairs and ("label", "s1") in pairs


def test_point_insert_carries_invisible_attributes(tmp_path: Path) -> None:
    doc = readfile(_build(tmp_path))
    inserts = {
        oid[1]: e
        for e in doc.modelspace().query("INSERT")
        if isinstance(e, Insert) and (oid := object_id(e)) and oid[0] in ("point", "board")
    }
    s1 = inserts["s1"]
    assert {a.dxf.tag: a.dxf.text for a in s1.attribs} == {"ID": "s1", "H": "300", "GROUP": "QF1"}
    assert all(a.is_invisible for a in s1.attribs)
    assert inserts["board"].get_attrib_text("H") == "1700"
    # В легенде на листе — те же блоки, но без атрибутов и меток
    legend = [e for e in doc.paperspace("02 Электрика").query("INSERT") if e.dxf.name == "E_SOCKET"]
    assert legend and all(isinstance(e, Insert) and not e.attribs for e in legend)


def test_artifact_items_reference_objects(tmp_path: Path) -> None:
    doc = readfile(_build(tmp_path))
    plan = make_plan(RECT)
    _, pages = read_artifact(export_artifact(doc, plan, tmp_path / "p.epd"))
    objects = {item.get("o") for item in pages[1]["items"]}
    assert {"point:s1", "point:s2", "board:board", "wall:r.w2"} <= objects
    # Кабели — только на листе проводки
    assert not any(str(o).startswith("wire:") for o in objects)
    assert {"wire:wire_1", "box:box_1"} <= {item.get("o") for item in pages[2]["items"]}
    # Рамка, штамп и легенда — не объекты проекта
    sheet_items = [i for i in pages[1]["items"] if i["l"] == "A-SHEET"]
    assert sheet_items and all("o" not in i for i in sheet_items)
