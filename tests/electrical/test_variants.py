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
    chosen_job,
    default_variant,
    neighbour_variants,
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


def test_option_changes_the_key_only_when_it_differs_from_the_mode() -> None:
    assert Variant(mode="economy", path="shortest").key == "economy-ceiling-boxes"
    assert Variant(mode="proper", conduit="ceiling").key == "proper-ceiling-boxes"
    old = Variant.model_validate({"mode": "proper", "conduit": True})  # variant.yaml before
    assert old.conduit == "ceiling" and old.key == "proper-ceiling-boxes"
    assert Variant(path="shortest").key == "standard-ceiling-boxes-shortest"
    assert Variant(mode="economy", path="right").key == "economy-ceiling-boxes-right"
    assert Variant(conduit="ceiling").key == "standard-ceiling-boxes-conduit"
    assert Variant(mode="proper", conduit="none").key == "proper-ceiling-boxes-bare"
    assert Variant(conduit="walls").key == "standard-ceiling-boxes-walls"
    assert Variant(mode="proper", conduit="walls").key == "proper-ceiling-boxes-walls"
    assert Variant(distribution="loop").key == "standard-ceiling-loop"


def test_apply_variant_sets_the_options() -> None:
    chosen = Variant(distribution="loop", path="shortest", conduit="walls")
    elec = apply_variant(_elec(), chosen)
    assert (elec.distribution, elec.path, elec.conduit) == ("loop", "shortest", "walls")
    assert default_variant(elec).key == chosen.key
    assert apply_variant(_elec(), Variant(path="right", conduit="none")) == _elec()  # as in project


def test_job_options_apply_to_any_variant_and_stay_out_of_the_key() -> None:
    job = Variant(plaster="before", rough_light=True)
    assert job.key == Variant().key  # route edits stay
    elec = apply_variant(_elec(), job)  # "as in project" by the key
    assert (elec.plaster, elec.rough_light) == ("before", True)
    other = apply_variant(_elec(), Variant(mode="proper", plaster="before"))
    assert (other.plaster, other.rough_light) == ("before", False)
    kept = apply_variant(_elec(plaster="before", rough_light=True), Variant(mode="proper"))
    assert (kept.plaster, kept.rough_light) == ("before", True)  # no choice: as in electrical.yaml
    assert default_variant(elec).plaster == "before" and default_variant(elec).rough_light


def test_job_options_show_in_the_summary() -> None:
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    prices = Prices(None, MockPriceService("грн"))
    base = variant_summary(plan, contours, _elec(), Variant(), None, prices)
    job = Variant(plaster="before", rough_light=True)
    summary = variant_summary(plan, contours, _elec(), job, None, prices)
    assert base is not None and summary is not None
    assert summary.chases_m == 0 < base.chases_m
    assert summary.as_dict()["plaster"] == "before" and summary.as_dict()["rough_light"] is True
    assert summary.total != base.total


def _options(v: Variant) -> tuple[object, ...]:
    return (v.mode, v.route, v.distribution, v.wire_path, v.conduit_level, v.plaster, v.rough_light)


def test_neighbours_change_one_option_each() -> None:
    chosen = Variant(mode="standard", route="ceiling")
    base = chosen_job(_elec(), chosen)
    assert base.path == "right" and base.plaster == "after" and base.rough_light is False
    near = neighbour_variants(_elec(), chosen)
    # route 1, distribution 1, path 1, conduit 2, mode 2, plaster 1, rough light 1
    assert len(near) == 9 and len({_options(v) for v in near}) == 9
    for v in near:
        changed = [a != b for a, b in zip(_options(v), _options(base), strict=True)]
        assert sum(changed) == 1 or v.mode != base.mode  # "don't know" conduit follows the mode
    proper = next(v for v in near if v.mode == "proper")
    assert proper.conduit_level == "ceiling" and proper.wire_path == "right"  # path as chosen


def test_neighbours_keep_to_project_routes() -> None:
    near = neighbour_variants(_elec(routes=["ceiling"]), Variant(route="ceiling", conduit="walls"))
    assert {v.route for v in near} == {"ceiling"} and len(near) == 8
    assert all(v.conduit == "walls" for v in near if v.mode != "standard")  # the choice stays


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
    expected = Variant(mode="economy", route="ceiling", plaster="after", rough_light=False)
    assert default == expected
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
    chosen = assess_project(project).report.variant
    assert chosen is not None and chosen.key == Variant().key  # "as in project"
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


def test_job_options_survive_a_variant_change(tmp_path: Path) -> None:
    project = _project(tmp_path)
    assert not save_variant(project, {"mode": "standard", "plaster": "before", "rough_light": True})
    assert not save_variant(project, {"mode": "economy"})  # "Overview" sends only the mode
    saved = yaml.safe_load((project / "variant.yaml").read_text("utf-8"))
    assert saved["plaster"] == "before" and saved["rough_light"] is True
    assert not save_variant(project, {"mode": "economy", "rough_light": False})
    assert yaml.safe_load((project / "variant.yaml").read_text("utf-8"))["rough_light"] is False


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
    assert block["items"][0]["key"] == "proper-ceiling-boxes"  # the chosen set first
    assert len(block["items"]) == 10  # and its neighbours, one option changed each
    assert {i["mode"] for i in block["items"]} == {"economy", "standard", "proper"}
    assert all(i["total"] > 0 and i["devices"] > 0 for i in block["items"])


def test_chosen_set_of_options_joins_the_summary(tmp_path: Path) -> None:
    """A set from the wizard is summed up with its neighbours; a mode alone drops the options."""
    project = _project(tmp_path)
    assert not save_variant(project, {"mode": "standard", "path": "shortest", "conduit": "ceiling"})
    result = build_project(project)
    assert result.artifact is not None
    with zipfile.ZipFile(result.artifact) as zf:
        block = json.loads(zf.read("manifest.json"))["variants"]
    assert block["active"] == "standard-ceiling-boxes-shortest-conduit"
    active = block["items"][0]
    assert active["key"] == block["active"]
    assert active["path"] == "shortest" and active["conduit"] == "ceiling"
    assert block["conduit"] == "ceiling"  # chosen, not by the mode
    assert len(block["items"]) == 10
    assert not save_variant(project, {"mode": "standard"})
    assert assess_project(project).report.variant.key == "standard-ceiling-boxes"  # type: ignore[union-attr]


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
    assert {i["route"] for i in block["items"]} == {"ceiling"} and len(block["items"]) == 9
