"""Общие сведения для первой вкладки просмотра (epd/overview.py): объект, помещения,
потолок, точки по видам, щит, сантехника — и что они попадают в манифест .epd."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from floorplan_engine.electrical.panel import build_panel
from floorplan_engine.epd.overview import overview_data
from floorplan_engine.pipeline import build_project
from tests.electrical.test_variants import _project
from tests.epd.test_objects import _model
from tests.plumbing.test_estimate import PLUMBING, _net


def test_overview_counts_points_rooms_and_panel() -> None:
    plan, contours, elec, _ = _model()
    data = overview_data(plan, contours, elec, build_panel(plan, elec))
    assert data["object"]["object"] == plan.name  # графа «объект» не задана — имя проекта
    assert data["rooms"][0]["area"] == 12.0 and data["area"] == 12.0  # 3 × 4 м
    assert data["ceiling"] == {"height": 2700, "assumed": True}
    points = {p["key"]: p["count"] for p in data["points"]}
    assert points == {"socket": 4, "board": 1}  # s1 ×2, s2, s3 — как в условных обозначениях
    assert data["panel"]["devices"] > 0 and data["panel"]["input"]


def test_overview_without_electrical() -> None:
    plan, contours, _, _ = _model()
    data = overview_data(plan, contours, None, None)
    assert "points" not in data and "panel" not in data


def test_build_writes_overview_to_manifest(tmp_path: Path) -> None:
    result = build_project(_project(tmp_path))
    assert result.artifact is not None
    with zipfile.ZipFile(result.artifact) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["overview"]["rooms"][0]["name"] == "К"
    assert all("conduit_m" in i for i in manifest["variants"]["items"])


def test_overview_plumbing_water_and_sewer() -> None:
    plan, contours, _, _ = _model()
    net = _net()
    data = overview_data(plan, contours, None, None, PLUMBING, net)["plumbing"]
    assert {f["type"]: f["count"] for f in data["fixtures"]} == {"wc": 1, "sink": 1}
    assert data["water"]["distribution"] == "collector" and data["water"]["outlets"] == 3
    assert data["water"]["hot"] == "riser" and data["water"]["cold_m"] > 0
    assert {p["d"] for p in data["sewer"]["pipes"]} == {50, 110}  # умывальник и унитаз
    assert data["sewer"]["risers"] == 1 and data["sewer"]["bends"] > 0
    assert "plumbing" not in overview_data(plan, contours, None, None)
    assert "estimate" not in data  # смету не передали — итога сантехники нет


def test_overview_plumbing_estimate_total() -> None:
    from floorplan_engine.electrical.pricing import MockPriceService, Prices
    from floorplan_engine.plumbing.estimate import MOCK_PRICES, build_estimate

    plan, contours, _, _ = _model()
    net = _net()
    est = build_estimate(net, PLUMBING, Prices(None, MockPriceService(extra=MOCK_PRICES)))
    data = overview_data(plan, contours, None, None, PLUMBING, net, est)["plumbing"]
    assert data["estimate"] == {
        "total": round(est.total, 2),
        "currency": est.currency,
        "unpriced": 0,
    }
