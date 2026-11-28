"""Estimates of a project folder: estimate_project and the estimate files build writes."""

from __future__ import annotations

from pathlib import Path

import yaml

from floorplan_engine.pipeline import build_project, estimate_project
from tests.electrical.test_estimate import DOOR, ELEC, RECT


def test_estimate_project_writes_tables(tmp_path: Path) -> None:
    project = tmp_path / "kv1"
    project.mkdir()
    room = {
        "name": "Кв",
        "default_wall_thickness": 120,
        "source": "text",
        "rooms": [
            {
                "id": "r",
                "name": "К",
                "walls": [{"id": f"w{i + 1}", **w} for i, w in enumerate(RECT)],
                "openings": [{"id": "r_door_1", **DOOR}],
            }
        ],
    }
    (project / "room.yaml").write_text(yaml.safe_dump(room, allow_unicode=True), "utf-8")
    (project / "electrical.yaml").write_text(yaml.safe_dump(ELEC, allow_unicode=True), "utf-8")

    # Without prices.yaml there are no prices at all (no mock, decision 2026-11-27): a bill of
    # quantities
    no_prices = estimate_project(project)
    est = no_prices.estimate
    assert est is not None and est.total == 0 and not est.has_prices
    assert est.from_service == 0 and no_prices.prices is None
    assert "сервиса цен" not in no_prices.files[0].read_text("utf-8")

    (project / "prices.yaml").write_text("items:\n  socket_box: 20\n  work.chase: 200\n", "utf-8")
    result = estimate_project(project)
    assert result.estimate is not None and result.estimate.total > 0
    assert result.estimate.from_service == 0  # the studio list alone
    md, csv_path, xlsx, scope = result.files
    assert scope.name == "work-scope.md" and "work-scope.md" in md.read_text("utf-8")
    assert xlsx.suffix == ".xlsx" and xlsx.stat().st_size > 0
    text = md.read_text("utf-8")
    assert "Смета электрики: Кв" in text and "имитация" not in text
    assert "Чистовые материалы" in text and "ведомость без цен" in text
    raw = csv_path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM: Excel recognises UTF-8
    assert "socket_box;Подрозетник;шт;4;20,00;80,00" in raw.decode("utf-8-sig")

    (project / "prices.yaml").write_text("items:\n  sockt_box: 20\n", "utf-8")
    bad = estimate_project(project)
    assert bad.estimate is None
    assert any(i.file == "prices.yaml" and i.path == "items.sockt_box" for i in bad.issues)

    # build writes the same estimate, so the Excel in the viewer matches the sheets; a price list
    # with errors gives no estimate (errors go to price_issues)
    (project / "prices.yaml").write_text("items:\n  socket_box: 20\n", "utf-8")
    built = build_project(project)
    assert [f.name for f in built.estimate] == [
        "estimate.md",
        "estimate.csv",
        "estimate.xlsx",
        "work-scope.md",
    ]
    (project / "prices.yaml").write_text("items:\n  sockt_box: 20\n", "utf-8")
    broken = build_project(project)
    assert broken.price_issues and not broken.estimate
    assert not (project / "out" / "estimate.xlsx").exists()
    assert not (project / "out" / "work-scope.md").exists()
