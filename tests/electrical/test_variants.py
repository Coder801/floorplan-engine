"""Wiring variants (electrical/variants.py, docs/wiring-variants.md): applying a variant, the "as
in project" variant, a summary without drawings; in the project, variant.yaml, route edits per
variant (pipeline.save_wiring_edits), the summary in the .epd manifest."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from floorplan_engine.electrical.pricing import MockPriceService, Prices
from floorplan_engine.electrical.variants import (
    all_variants,
    apply_variant,
    default_variant,
    project_variants,
    variant_summary,
)
from floorplan_engine.model.schema import Electrical, Variant, WireEdit, WiringEdits, WiringFile
from floorplan_engine.pipeline import (
    assess_project,
    build_project,
    save_variant,
    save_wiring_edits,
)
from floorplan_engine.validation.issues import Severity
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan
from tests.electrical.test_estimate import DOOR, ELEC, RECT

EDIT = {"from": "board", "to": "s1", "path": [[0, 0], [0, 100], [50, 100]]}


def _elec(**extra: Any) -> Electrical:
    return Electrical.model_validate({**ELEC, **extra})


def test_all_variants_and_keys() -> None:
    keys = [v.key for v in all_variants()]
    assert len(keys) == len(set(keys)) == 6  # 3 modes × 2 routes × 1 distribution
    assert "economy-floor-boxes" in keys and "proper-ceiling-boxes" in keys


def test_project_routes_limit_variants() -> None:
    assert project_variants(_elec()) == all_variants()
    ceiling_only = project_variants(_elec(routes=["ceiling"]))
    assert [v.key for v in ceiling_only] == [
        "economy-ceiling-boxes", "standard-ceiling-boxes", "proper-ceiling-boxes"
    ]  # fmt: skip


def test_routes_must_agree_with_route_and_cables() -> None:
    with pytest.raises(ValidationError, match="route"):
        _elec(routes=["ceiling"], route="floor")
    cables = [{"id": "c1", "from": "board", "to": ["s1"], "cable": "3x2.5", "route": "floor"}]
    with pytest.raises(ValidationError, match="cables"):
        _elec(routes=["ceiling"], cables=cables)
    with pytest.raises(ValidationError, match="повторяются"):
        _elec(routes=["ceiling", "ceiling"])
    assert _elec(routes=["floor"], route="floor").routes == ["floor"]


def test_default_variant_keeps_project_as_is() -> None:
    elec = _elec(mode="economy")
    default = default_variant(elec)
    assert default == Variant(mode="economy", route="ceiling")
    assert apply_variant(elec, default) is elec  # "as in project": no changes
    floor = apply_variant(elec, Variant(mode="proper", route="floor"))
    assert floor.mode == "proper" and floor.points == elec.points  # points come from the project


def test_apply_variant_sets_one_route_for_all_cables() -> None:
    cables = [
        {"id": "c1", "from": "board", "to": ["s1"], "cable": "3x2.5", "route": "floor"},
        {"id": "c2", "from": "board", "to": ["l1"], "cable": "3x1.5"},
    ]
    elec = _elec(cables=cables)
    assert default_variant(elec).route == "ceiling"  # not all on the floor
    assert {c.route for c in apply_variant(elec, Variant(route="floor")).cables} == {"floor"}
    assert {c.route for c in apply_variant(elec, Variant(mode="economy")).cables} == {"ceiling"}
    all_floor = _elec(cables=[{**c, "route": "floor"} for c in cables])
    assert default_variant(all_floor).route == "floor"


def test_wiring_file_edits_for_variant_and_legacy() -> None:
    edit = WireEdit.model_validate(EDIT)
    data = WiringFile(
        wires={"wire_1": edit},
        variants={"economy-floor-boxes": WiringEdits(wires={"wire_2": edit})},
    )
    default = "standard-ceiling-boxes"
    legacy = data.edits_for(default, default)  # pre-variant edits belong to the default variant
    assert legacy is not None and set(legacy.wires) == {"wire_1"}
    own = data.edits_for("economy-floor-boxes", default)
    assert own is not None and set(own.wires) == {"wire_2"}
    assert data.edits_for("proper-floor-boxes", default) is None


def test_variant_summary_differs_by_mode_and_route() -> None:
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    elec = _elec()
    prices = Prices(None, MockPriceService())
    summaries = {
        v.key: variant_summary(plan, contours, elec, v, None, prices) for v in all_variants()
    }
    assert all(s is not None for s in summaries.values())
    std, prem = summaries["standard-ceiling-boxes"], summaries["proper-ceiling-boxes"]
    floor = summaries["standard-floor-boxes"]
    assert std is not None and prem is not None and floor is not None
    assert prem.total > std.total  # premium: RCBOs, surge protector
    assert floor.cable_m != std.cable_m  # on the floor: different routes
    d = std.as_dict()
    assert d["key"] == "standard-ceiling-boxes" and d["currency"] == "грн" and not d["edited"]


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "kv"
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
    return project


def test_variant_choice_and_edits_kept_per_variant(tmp_path: Path) -> None:
    project = _project(tmp_path)
    assert assess_project(project).report.variant == Variant()  # "as in project"
    assert not save_wiring_edits(project, {"wires": {"wire_1": EDIT}})
    assert save_variant(project, {"mode": "cheap"})[0].path == "mode"  # error with a path
    assert not save_variant(project, {"mode": "economy", "route": "floor"})
    report = assess_project(project).report
    assert report.variant is not None and report.variant.key == "economy-floor-boxes"
    assert report.electrical is not None and report.electrical.mode == "economy"
    assert report.wiring_edits is None  # this variant has no edits
    assert not save_wiring_edits(project, {"wires": {"wire_5": EDIT}})
    data = yaml.safe_load((project / "wiring.yaml").read_text("utf-8"))
    assert set(data["variants"]) == {"standard-ceiling-boxes", "economy-floor-boxes"}
    assert "wires" not in data  # pre-variant edits moved into the variant section
    assert set(data["variants"]["economy-floor-boxes"]["wires"]) == {"wire_5"}
    # Back to the "as in project" variant: its edits are still there
    assert not save_variant(project, {"mode": "standard", "route": "ceiling"})
    back = assess_project(project).report.wiring_edits
    assert back is not None and set(back.wires) == {"wire_1"}


def test_ceiling_height_from_viewer_overrides_plan_and_survives_variant_change(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    assert assess_project(project).report.plan is not None
    for bad in (1999, 4001):  # from 2 to 4 m
        assert save_variant(project, {"ceiling_height": bad})[0].path == "ceiling_height"
    assert not save_variant(project, {"mode": "standard", "ceiling_height": 3100})
    plan = assess_project(project).report.plan
    assert plan is not None and plan.ceiling_height == 3100
    assert "ceiling_height" in plan.model_fields_set  # not an assumption
    assert not save_variant(project, {"mode": "economy"})  # variant change keeps the height
    plan = assess_project(project).report.plan
    assert plan is not None and plan.ceiling_height == 3100


def test_build_writes_variant_summaries_to_manifest(tmp_path: Path) -> None:
    project = _project(tmp_path)
    save_variant(project, {"mode": "proper"})
    result = build_project(project)
    assert result.artifact is not None
    with zipfile.ZipFile(result.artifact) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    block = manifest["variants"]
    assert block["active"] == "proper-ceiling-boxes"
    assert block["default"] == "standard-ceiling-boxes"
    assert {i["key"] for i in block["items"]} == {v.key for v in all_variants()}
    assert all(i["total"] > 0 and i["devices"] > 0 for i in block["items"])


def test_project_without_floor_builds_only_ceiling_variants(tmp_path: Path) -> None:
    """routes: [ceiling]: a floor variant from variant.yaml is not applied (a warning), and the
    manifest has only ceiling variants."""
    project = _project(tmp_path)
    elec_path = project / "electrical.yaml"
    data = yaml.safe_load(elec_path.read_text(encoding="utf-8"))
    elec_path.write_text(yaml.safe_dump({**data, "routes": ["ceiling"]}, allow_unicode=True))
    save_variant(project, {"mode": "economy", "route": "floor"})
    report = assess_project(project).report
    assert report.variant is not None and report.variant.key == "standard-ceiling-boxes"
    warning = [i for i in report.issues if i.severity is Severity.WARNING and i.path == "route"]
    assert warning and "floor" in warning[0].message
    result = build_project(project)
    assert result.artifact is not None
    with zipfile.ZipFile(result.artifact) as zf:
        block = json.loads(zf.read("manifest.json"))["variants"]
    assert block["active"] == "standard-ceiling-boxes"
    assert {i["route"] for i in block["items"]} == {"ceiling"} and len(block["items"]) == 3
