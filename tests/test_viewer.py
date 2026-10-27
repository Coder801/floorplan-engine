from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from shtroba.service.viewer import create_viewer

PAGE = {
    "name": "01 План",
    "size": [420, 297],
    "background": "#ffffff",
    "items": [
        {"k": "s", "c": "#000000", "w": 0.5, "l": "A-WALL", "o": "wall:r.w1", "d": "M0 0L10 0"}
    ],
}


def _epd(path: Path, version: int) -> None:
    manifest = {
        "format": "shtroba/epd",
        "version": version,
        "pages": [
            {
                "index": 1,
                "name": "01 План",
                "format": "A3",
                "size": [420, 297],
                "file": "pages/01.json",
            }
        ],
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("pages/01.json", json.dumps(PAGE))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    project = tmp_path / "kv1"
    (project / "out").mkdir(parents=True)
    (project / "source").mkdir()
    (project / "room.yaml").write_text("name: Кв\n", "utf-8")
    (project / "answers.yaml").write_text("answers:\n  q1: 850\n  q2: {accept: true}\n", "utf-8")
    report = {
        "project": "Квартира 1",
        "stages": [{"stage": "plan", "status": "questions", "builds": True}],
        "questions": [{"id": "q1", "state": "answered"}, {"id": "q3", "state": "open"}],
        "issues": [],
    }
    (project / "out" / "report.json").write_text(json.dumps(report), "utf-8")
    (project / "out" / "project.dxf").write_text("0\nEOF\n", "utf-8")
    _epd(project / "out" / "project.epd", version=1)
    (project / "out" / ".DS_Store").write_bytes(b"")
    (project / "source" / "план.pdf").write_bytes(b"%PDF")
    (tmp_path / "secret.txt").write_text("нет", "utf-8")
    (tmp_path / "empty").mkdir()  # не проект: ни модели, ни out/
    # Сборка новее модели
    built = (project / "out" / "report.json").stat().st_mtime
    for f in ("room.yaml", "answers.yaml"):
        os.utime(project / f, (built - 10, built - 10))
    return tmp_path


def test_list_and_project(root: Path) -> None:
    client = TestClient(create_viewer(root))
    [item] = client.get("/api/projects").json()
    assert item["name"] == "kv1" and item["title"] == "Квартира 1"
    assert item["open_questions"] == 1 and item["stale"] is False

    p = client.get("/api/projects/kv1").json()
    assert p["answers"] == {"q1": 850, "q2": {"accept": True}}
    assert p["artifact"] is True and p["dxf"] == "project.dxf"
    assert p["files"] == ["project.dxf", "project.epd", "report.json"]
    assert p["sources"] == ["план.pdf"]
    assert p["model"] == ["room.yaml", "answers.yaml"]

    assert client.get("/api/projects/kv1/sheets").json()["pages"][0]["name"] == "01 План"
    assert client.get("/api/projects/kv1/sheets/1").json() == PAGE
    assert client.get("/api/projects/kv1/sheets/2").status_code == 404
    assert client.get("/api/projects/kv1/source/план.pdf").content == b"%PDF"
    assert client.get("/api/projects/kv1/model/room.yaml").text == "name: Кв\n"


def test_stale_after_model_edit(root: Path) -> None:
    (root / "kv1" / "room.yaml").write_text("name: Кв 2\n", "utf-8")
    os.utime(root / "kv1" / "room.yaml")
    assert TestClient(create_viewer(root)).get("/api/projects/kv1").json()["stale"] is True


def test_no_escape(root: Path) -> None:
    client = TestClient(create_viewer(root))
    assert client.get("/api/projects/nope").status_code == 404
    assert client.get("/api/projects/kv1/out/../../secret.txt").status_code == 404
    assert client.get("/api/projects/kv1/source/%2e%2e/%2e%2e/secret.txt").status_code == 404
    assert client.get("/api/projects/kv1/model/secret.txt").status_code == 400
    assert client.get("/api/projects/%2e%2e/model/room.yaml").status_code == 404


def test_sheets_need_artifact_of_known_version(root: Path) -> None:
    client = TestClient(create_viewer(root))
    _epd(root / "kv1" / "out" / "project.epd", version=99)
    assert client.get("/api/projects/kv1/sheets").status_code == 409  # чужую версию не показываем
    (root / "kv1" / "out" / "project.epd").unlink()
    assert client.get("/api/projects/kv1").json()["artifact"] is False
    assert client.get("/api/projects/kv1/sheets/1").status_code == 404


def test_parsed_sources_from_intake(root: Path) -> None:
    (root / "kv1" / "intake.yaml").write_text(
        "sources:\n  - file: source/план.pdf\n    note: лист 08\n  - file: source/фото.jpg\n",
        "utf-8",
    )
    p = TestClient(create_viewer(root)).get("/api/projects/kv1").json()
    assert p["parsed"] == [
        {"file": "план.pdf", "note": "лист 08"},
        {"file": "фото.jpg", "note": ""},
    ]
    assert p["sources"] == ["план.pdf"]  # фото в intake есть, файла нет — покажет просмотр


def test_save_wiring_edits(root: Path) -> None:
    client = TestClient(create_viewer(root))
    path = root / "kv1" / "wiring.yaml"
    edit = {"from": "board", "to": "s1", "path": [[0, 0], [0, 100], [50, 100]]}
    r = client.post("/api/projects/kv1/wiring", json={"wires": {"wire_1": edit}})
    assert r.status_code == 200, r.text
    assert r.json()["built"] is False  # room.yaml фикстуры не строится — но правка записана
    text = path.read_text("utf-8")
    assert '"wire_1": { from: "board", to: "s1", path: [[0, 0], [0, 100], [50, 100]] }' in text
    assert client.get("/api/projects").json()[0]["stale"] is False  # пересобрано после записи

    diagonal = {"from": "board", "to": "s1", "path": [[0, 0], [50, 100]]}
    r = client.post("/api/projects/kv1/wiring", json={"wires": {"wire_2": diagonal}})
    assert r.status_code == 422 and "wires.wire_2" in r.json()["detail"]
    assert path.read_text("utf-8") == text  # файл не тронут

    box = {"room": "r", "group": "QF1", "at": [100, 200]}
    client.post(
        "/api/projects/kv1/wiring", json={"wires": {"wire_1": None}, "boxes": {"box_1": box}}
    )
    assert "wire_1" not in path.read_text("utf-8")
    client.post("/api/projects/kv1/wiring", json={"boxes": {"box_1": None}})
    assert not path.exists()  # правок нет — нет и файла


def test_api_only(root: Path) -> None:
    client = TestClient(create_viewer(root))
    about = client.get("/").json()
    assert "web/" in about["front"]  # страница — отдельный проект, не в пакете
    assert client.get("/static/app/index.html").status_code == 404
