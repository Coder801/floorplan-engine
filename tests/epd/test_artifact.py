from __future__ import annotations

import json
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from ezdxf.document import Drawing
from ezdxf.filemanagement import readfile
from numpy.typing import NDArray

from floorplan_engine.electrical.splices import back_box_joints
from floorplan_engine.electrical.wiring import box_wiring
from floorplan_engine.epd.artifact import (
    FORMAT_NAME,
    FORMAT_VERSION,
    MANIFEST,
    export_artifact,
    parse_path,
    read_artifact,
    render_page_png,
)
from floorplan_engine.epd.objects import ObjectInfo, describe_objects
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.sheets.document import build_project_document
from floorplan_engine.validation.issues import parse_model
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan, wall_point


def _vertices(d: str, height: float) -> NDArray[np.float64]:
    return np.asarray(parse_path(d, height).vertices, dtype=np.float64)


RECT = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]


def _project(tmp_path: Path) -> tuple[Drawing, Plan]:
    plan = make_plan(RECT, [{"wall": "w1", "type": "door", "offset": 300, "width": 800}])
    _, contours = validate_plan(plan)
    elec, issues = parse_model(
        Electrical,
        {
            "points": [
                {
                    "id": "s1",
                    "room": "r",
                    "wall": "w2",
                    "offset": 500,
                    "type": "socket",
                    "height": 300,
                }
            ]
        },
        "e.yaml",
    )
    assert elec is not None, issues
    doc = build_project_document(plan, contours, elec, today=date(2026, 10, 20))
    path = tmp_path / "project.dxf"
    doc.saveas(path, encoding="utf-8")
    return readfile(path), plan


def test_artifact_appears_whole(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc, plan = _project(tmp_path)
    epd = export_artifact(doc, plan, tmp_path / "project.epd")
    old = epd.read_bytes()
    assert not epd.with_name("project.epd.tmp").exists()

    def broken(*_: object) -> None:
        raise RuntimeError("сборка упала")

    monkeypatch.setattr("floorplan_engine.epd.artifact.record_page", broken)
    with pytest.raises(RuntimeError):
        export_artifact(doc, plan, epd)
    assert epd.read_bytes() == old  # the viewer keeps reading the previous build
    assert not epd.with_name("project.epd.tmp").exists()


def test_artifact_round_trip(tmp_path: Path) -> None:
    doc, plan = _project(tmp_path)
    epd = export_artifact(doc, plan, tmp_path / "project.epd")
    manifest, pages = read_artifact(epd)
    assert manifest["format"] == FORMAT_NAME and manifest["version"] == FORMAT_VERSION
    assert manifest["project"] == {"name": "тест", "language": "ru"}
    names = [p["name"] for p in manifest["pages"]]
    assert names == ["01 План", "02 Электрика", "03 Точки", "04 Развёртки электрики"]
    for meta, page in zip(manifest["pages"], pages, strict=True):
        width, height = page["size"]
        assert meta["size"] == page["size"] and page["format"].startswith("A")
        assert {item["k"] for item in page["items"]} == {"s", "f"}  # lines and filled letters
        for item in page["items"]:
            assert ("w" in item) == (item["k"] == "s")
            vertices = _vertices(item["d"], height)
            # Everything within the sheet (with a margin for line width)
            assert vertices[:, 0].min() >= -1 and vertices[:, 0].max() <= width + 1
            assert vertices[:, 1].min() >= -1 and vertices[:, 1].max() <= height + 1
    layers = {item["l"] for item in pages[1]["items"]}
    assert {"A-WALL", "E-SOCKET", "A-SHEET"} <= layers
    assert "A-DIMS" not in layers  # frozen in the electrical sheet viewport


def test_elevations_page_gets_cards_of_its_boxes(tmp_path: Path) -> None:
    doc, plan = _project(tmp_path)
    _, pages = read_artifact(export_artifact(doc, plan, tmp_path / "probe.epd"))
    page = next(p for p in pages if p.get("stage") == "elevations")
    key = next(item["o"] for item in page["items"] if item.get("o", "").startswith("elevation:"))
    elevations = [
        {"key": key, "boxes": [{"key": "box:b1"}]},
        {"key": "elevation:other.w1", "boxes": [{"key": "box:b2"}]},  # not on this sheet
    ]
    objects = {
        "box:b1": ObjectInfo("Коробка К1", (("Группа", "QF1"),)),
        "box:b2": ObjectInfo("Коробка К2", ()),
    }
    epd = export_artifact(
        doc, plan, tmp_path / "project.epd", objects=objects, elevations=elevations
    )
    _, pages = read_artifact(epd)
    page = next(p for p in pages if p.get("stage") == "elevations")
    assert [e["key"] for e in page["elevations"]] == [key]
    assert page["objects"]["box:b1"]["title"] == "Коробка К1"
    assert "box:b2" not in page["objects"]


def test_model_transform_maps_model_to_sheet(tmp_path: Path) -> None:
    from floorplan_engine.sheets.document import document_scale

    doc, plan = _project(tmp_path)
    _, pages = read_artifact(export_artifact(doc, plan, tmp_path / "project.epd"))
    k, tx, ty = pages[0]["model"]
    assert k == pytest.approx(1 / document_scale(doc))
    # The inner room corner (0, 0) and (3000 up, 4000 right) are at the wall edges on the sheet
    walls = [it for it in pages[0]["items"] if it.get("o", "").startswith("wall:")]
    pts = np.concatenate([_vertices(it["d"], 0) for it in walls])
    xs, ys = pts[:, 0], -pts[:, 1]  # parse_path with height 0 flips y: flip it back
    assert xs.min() < tx < xs.max() and xs.min() < k * 4000 + tx < xs.max()
    assert ys.min() < ty < ys.max() and ys.min() < ty - k * 3000 < ys.max()
    assert "edit" not in pages[0]  # editing only on the wiring sheet


def test_artifact_is_deterministic_and_compressed(tmp_path: Path) -> None:
    doc, plan = _project(tmp_path)
    a = export_artifact(doc, plan, tmp_path / "a.epd").read_bytes()
    b = export_artifact(doc, plan, tmp_path / "b.epd").read_bytes()
    assert a == b
    with zipfile.ZipFile(tmp_path / "a.epd") as zf:
        assert all(i.compress_type == zipfile.ZIP_DEFLATED for i in zf.infolist())
        assert sorted(zf.namelist()) == [
            MANIFEST,
            "pages/01.json",
            "pages/02.json",
            "pages/03.json",
            "pages/04.json",
        ]


def test_read_rejects_foreign_or_newer_files(tmp_path: Path) -> None:
    path = tmp_path / "x.epd"
    for manifest, message in (
        ({"format": "other"}, "не артефакт"),
        ({"format": FORMAT_NAME, "version": FORMAT_VERSION + 1}, "версия формата"),
    ):
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(MANIFEST, json.dumps(manifest))
        with pytest.raises(ValueError, match=message):
            read_artifact(path)


def test_parse_path_flips_y_and_closes() -> None:
    vertices = _vertices("M0 0L10 0Q10 5 5 5C2 5 0 3 0 0Z", height=100)
    assert vertices[0].tolist() == [0, 100]
    assert vertices[1].tolist() == [10, 100]
    assert len(vertices) == 1 + 1 + 2 + 3 + 1


def test_render_page_png(tmp_path: Path) -> None:
    doc, plan = _project(tmp_path)
    _, pages = read_artifact(export_artifact(doc, plan, tmp_path / "p.epd"))
    png = render_page_png(pages[0], tmp_path / "page.png")
    assert png.stat().st_size > 10_000


def test_block_entities_on_layer_0_take_their_entity_layer(tmp_path: Path) -> None:
    # Dimension lines and ticks live in the dimension's block on layer "0": in the viewer they
    # must hide with the dimension's own layer
    doc, plan = _project(tmp_path)
    _, pages = read_artifact(export_artifact(doc, plan, tmp_path / "project.epd"))
    dims = [i for i in pages[0]["items"] if str(i.get("o", "")).startswith("dimension:")]
    assert dims and {i["l"] for i in dims} == {"A-DIMS"}
    assert not [i for p in pages for i in p["items"] if i["l"] == "0" and "o" in i]


def test_wiring_page_gets_cards_of_points_with_joints(tmp_path: Path) -> None:
    """The wiring page shows no point cards, except a flush box with joints (decision
    2026-11-25): its card with the splice key, so the viewer can mark it and draw its joints."""
    plan = make_plan(RECT, [{"wall": "w2", "type": "door", "offset": 1000, "width": 900}])
    _, contours = validate_plan(plan)
    points = [
        {"id": "l1", "room": "r", "type": "downlight", "ceiling": [1500, 2000], "group": "QF1"},
        wall_point("k1", "switch", 500, 900, "QF1"),
        wall_point("k2", "switch", 2500, 900, "QF1"),
        *(wall_point(f"s{k}", "socket", 300 + 900 * k, 300, "QF2") for k in range(3)),
    ]
    board = {"room": "r", "wall": "w1", "offset": 500, "height": 1700}
    elec = Electrical.model_validate(
        {"points": points, "board": board, "distribution": "loop", "light_wiring": "chain"}
    )
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    joints = back_box_joints(wiring, elec)
    assert set(joints) == {"k1", "k2"}  # sockets of the loop have none
    doc = build_project_document(plan, contours, elec, today=date(2026, 10, 20))
    path = tmp_path / "project.dxf"
    doc.saveas(path, encoding="utf-8")
    objects = describe_objects(plan, contours, elec, wiring)
    _, pages = read_artifact(
        export_artifact(readfile(path), plan, tmp_path / "p.epd", objects=objects)
    )
    page = next(p for p in pages if p.get("stage") == "wiring")
    cards = {k for k in page["objects"] if k.startswith("point:")}
    assert cards == {f"point:{pid}" for pid in joints}
    drawn = {item["o"] for item in page["items"] if "o" in item}
    assert cards <= drawn  # the symbol is on the sheet: the viewer marks it there
    assert all(page["objects"][k]["splice"]["method"] == "wago" for k in cards)
