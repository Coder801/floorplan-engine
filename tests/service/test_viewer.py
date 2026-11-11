from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from floorplan_engine.pipeline import build_project
from floorplan_engine.service.api.viewer import create_viewer
from tests.electrical.test_variants import _project

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
        "format": "floorplan-engine/epd",
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
    (tmp_path / "empty").mkdir()  # not a project: no model and no out/
    # The build is newer than the model
    built = (project / "out" / "report.json").stat().st_mtime
    for f in ("room.yaml", "answers.yaml"):
        os.utime(project / f, (built - 10, built - 10))
    return tmp_path


def test_list_and_project(root: Path) -> None:
    client = TestClient(create_viewer(root))
    [item] = client.get("/api/projects").json()
    assert item["name"] == "kv1" and item["title"] == "Квартира 1"
    assert item["id"] == "kv1"  # the key in addresses: the folder name here
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
    assert client.get("/api/projects/kv1/sheets").status_code == 409  # another version is not shown
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
    assert p["sources"] == ["план.pdf"]  # photo in intake, file missing


def test_save_wiring_edits(root: Path) -> None:
    client = TestClient(create_viewer(root))
    path = root / "kv1" / "wiring.yaml"
    edit = {"from": "board", "to": "s1", "path": [[0, 0], [0, 100], [50, 100]]}
    r = client.post("/api/projects/kv1/wiring", json={"wires": {"wire_1": edit}})
    assert r.status_code == 200, r.text
    assert r.json()["built"] is False  # fixture does not build; edit saved
    text = path.read_text("utf-8")
    assert '"wire_1": { from: "board", to: "s1", path: [[0, 0], [0, 100], [50, 100]] }' in text
    assert client.get("/api/projects").json()[0]["stale"] is False  # rebuilt after writing

    broken = {"from": "board", "to": "s1", "path": [[0, 0]]}  # fewer than two points
    r = client.post("/api/projects/kv1/wiring", json={"wires": {"wire_2": broken}})
    assert r.status_code == 422 and "wires.wire_2" in r.json()["detail"]
    assert path.read_text("utf-8") == text  # file untouched
    r = client.post("/api/projects/kv1/wiring", json={"wires": "x"})  # not a dict: no crash
    assert r.status_code == 422 and "wires" in r.json()["detail"]

    box = {"room": "r", "group": "QF1", "at": [100, 200]}
    client.post(
        "/api/projects/kv1/wiring", json={"wires": {"wire_1": None}, "boxes": {"box_1": box}}
    )
    assert "wire_1" not in path.read_text("utf-8")
    client.post("/api/projects/kv1/wiring", json={"boxes": {"box_1": None}})
    assert not path.exists()  # no edits, no file


def test_api_only(root: Path) -> None:
    client = TestClient(create_viewer(root))
    about = client.get("/").json()
    assert "web/" in about["front"]  # the page is a separate project, not in the package
    assert client.get("/static/app/index.html").status_code == 404


def test_choose_variant_open_viewer(root: Path) -> None:
    """Login off: everything allowed; the wizard's variant → variant.yaml, an error gives 422
    with a field path."""
    client = TestClient(create_viewer(root))
    assert client.get("/api/projects/kv1").json()["can"] == {
        "edit_wiring": True,
        "choose_variant": True,
        "answer": True,
        "review": True,
    }
    bad = client.post("/api/projects/kv1/wizard", json={"variant": {"route": "air"}})
    assert bad.status_code == 422
    assert [i["path"] for i in bad.json()["detail"]["issues"]] == ["route"]
    variant = {"mode": "economy", "route": "floor"}
    assert client.post("/api/projects/kv1/wizard", json={"variant": variant}).status_code == 200
    assert client.post("/api/projects/kv1/variant", json=variant).status_code in (404, 405)
    text = (root / "kv1" / "variant.yaml").read_text("utf-8")
    assert "mode: economy" in text and "route: floor" in text


MARKET = """region: Київ
collected: "2026-11-03"
sources:
  a: { name: A, url: "https://a", date: "2026-03" }
  b: { name: B, url: "https://b" }
  unused: { name: U, url: "https://u", date: "2020" }
items:
  work.chase:
    basis: бетон
    quotes:
      a: { price: 80, text: "штроба бетон" }
      b: { price: 120, text: "штробление" }
"""


def test_price_page_and_edit(root: Path) -> None:
    (root / "prices.yaml").write_text(
        "# прайс\ncurrency: грн\nitems:\n  work.chase: 200  # узкая\n", "utf-8"
    )
    (root / "market.yaml").write_text(MARKET, "utf-8")
    client = TestClient(create_viewer(root))
    page = client.get("/api/prices").json()
    assert page["editable"] is True and page["issues"] == []
    rows = {r["key"]: r for r in page["rows"]}
    assert all(k.startswith("work.") for k in rows)
    chase = rows["work.chase"]
    assert chase["price"] == 200 and chase["service"] is None
    assert chase["market"]["median"] == 100 and chase["market"]["n"] == 2
    assert [q["source"] for q in chase["market"]["quotes"]] == ["a", "b"]
    assert rows["work.cable"]["price"] is None and rows["work.cable"]["service"] == 30
    assert rows["work.cable"]["market"] is None
    market = page["market"]
    assert market["period"] == {"start": "2026-03", "end": "2026-03", "dated": 1, "undated": 1}
    assert [s["id"] for s in market["sources"]] == ["a", "b"]  # without the unused one

    saved = client.post("/api/prices", json={"items": {"work.chase": 150, "work.cable": 25}})
    assert saved.status_code == 200
    text = (root / "prices.yaml").read_text("utf-8")
    assert "# прайс" in text and "work.chase: 150  # узкая" in text and "work.cable: 25" in text
    assert {r["key"]: r["price"] for r in saved.json()["rows"]}["work.cable"] == 25

    # Only works; a price is a number not below 0; the file is unchanged on errors
    assert client.post("/api/prices", json={"items": {"socket": 10}}).status_code == 422
    assert client.post("/api/prices", json={"items": {"work.chase": -1}}).status_code == 422
    assert (root / "prices.yaml").read_text("utf-8") == text


def test_price_page_without_files(root: Path) -> None:
    client = TestClient(create_viewer(root))
    page = client.get("/api/prices").json()
    assert page["exists"] is False and page["market"] is None
    assert client.post("/api/prices", json={"items": {"work.chase": 90}}).status_code == 200
    assert "work.chase: 90" in (root / "prices.yaml").read_text("utf-8")


def _answers_project(tmp_path: Path) -> Path:
    project = _project(tmp_path)
    intake = (
        "questions:\n"
        '  - { id: q1, stage: plan, text: "Есть обмер?", answer: text, severity: major }\n'
        '  - { id: q2, stage: plan, text: "Левая стена?", answer: value,'
        " target: rooms.r.walls.w1.length }\n"
    )
    (project / "intake.yaml").write_text(intake, "utf-8")
    build_project(project)
    return project


def test_answer_text_keeps_sheets_fresh_and_value_rebuilds(tmp_path: Path) -> None:
    project = _answers_project(tmp_path)
    (project / "answers.yaml").write_text("answers: {}\n", "utf-8")
    build_project(project)
    client = TestClient(create_viewer(tmp_path))
    # The answer is written after the build, its mtime is newer: only the digest can tell
    saved = client.post("/api/projects/kv/answers", json={"id": "q1", "answer": {"text": "нет"}})
    assert saved.json() == {"built": False, "rebuilt": False}
    p = client.get("/api/projects/kv").json()
    assert p["stale"] is False
    assert next(q for q in p["report"]["questions"] if q["id"] == "q1")["state"] == "text"
    assert p["answers"] == {"q1": {"text": "нет"}}
    assert "q1:" in (project / "answers.yaml").read_text("utf-8")

    saved = client.post("/api/projects/kv/answers", json={"id": "q2", "answer": {"accept": True}})
    assert saved.json() == {"built": True, "rebuilt": True}
    p = client.get("/api/projects/kv").json()
    assert next(q for q in p["report"]["questions"] if q["id"] == "q2")["state"] == "accepted"
    assert p["stale"] is False


def test_changed_answers_make_the_build_stale(tmp_path: Path) -> None:
    project = _answers_project(tmp_path)
    (project / "answers.yaml").write_text("answers:\n  q2: { accept: true }\n", "utf-8")
    report = project / "out" / "report.json"
    os.utime(report, (1, 1))
    assert TestClient(create_viewer(tmp_path)).get("/api/projects/kv").json()["stale"] is True


def test_wizard_saves_everything_with_one_rebuild(tmp_path: Path) -> None:
    project = _answers_project(tmp_path)
    client = TestClient(create_viewer(tmp_path))
    body = {
        "variant": {"mode": "economy", "route": "floor", "distribution": "boxes"},
        "answers": {"q2": {"accept": True}, "panel_backup": "plug", "panel_input": 40},
    }
    saved = client.post("/api/projects/kv/wizard", json=body)
    assert saved.json() == {"built": True, "rebuilt": True}
    assert "economy" in (project / "variant.yaml").read_text("utf-8")
    p = client.get("/api/projects/kv").json()
    assert p["answers"]["panel_backup"] == "plug" and p["answers"]["panel_input"] == 40
    assert p["stale"] is False
    assert not any(q["id"] == "panel_battery" for q in p["report"]["questions"])

    refused = client.post("/api/projects/kv/wizard", json={"answers": {"panel_input": -1}})
    assert refused.status_code == 422 and refused.json()["detail"]["issues"]
    assert client.post("/api/projects/kv/wizard", json={"answers": []}).status_code == 422
    assert client.post("/api/projects/kv/wizard", json={"variant": 1}).status_code == 422
    assert client.post("/api/projects/kv/wizard", json={}).json()["rebuilt"] is False


def test_answer_refused_with_field_and_blocker(tmp_path: Path) -> None:
    _answers_project(tmp_path)
    client = TestClient(create_viewer(tmp_path))
    assert client.post("/api/projects/kv/answers", json={"answer": 1}).status_code == 422
    assert client.post("/api/projects/nope/answers", json={"id": "q1"}).status_code == 404
    assert (
        client.post("/api/projects/kv/answers", json={"id": "panel_battery", "answer": 48}).json()[
            "rebuilt"
        ]
        is True
    )
    bad = client.post("/api/projects/kv/answers", json={"id": "panel_backup", "answer": "none"})
    assert bad.status_code == 422
    detail = bad.json()["detail"]
    assert detail["issues"][0]["path"] and detail["issues"][0]["message"]
    assert [b["id"] for b in detail["blocked_by"]] == ["panel_battery"]
