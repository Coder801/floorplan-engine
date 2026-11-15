from __future__ import annotations

import yaml

from floorplan_engine.service.analysis.sections import replace_section, section_value

ELEC = """\
mode: standard  # режим

points:  # точки
  - { id: t1, room: r, type: thermostat }  # А-29

floor_heating:  # А-29: старое
  - { id: fh_old, room: r, thermostat: t1 }

# щит
panel: { phases: 1 }  # вводной
"""
NEW = "floor_heating:\n  - { id: fh, room: r, thermostat: t1, area: 4.5 }  # S=4,5\n"


def test_section_is_replaced_in_place_and_the_rest_stays() -> None:
    out = replace_section(ELEC, "floor_heating", NEW)
    assert out is not None
    assert "fh_old" not in out and "# S=4,5" in out
    # Everything else byte for byte: the comments before and after the section too
    assert out.startswith(ELEC.split("floor_heating:")[0])
    assert out.endswith("# щит\npanel: { phases: 1 }  # вводной\n")
    data = yaml.safe_load(out)
    assert data["floor_heating"] == [{"id": "fh", "room": "r", "thermostat": "t1", "area": 4.5}]
    assert data["panel"] == {"phases": 1}


def test_section_is_appended_when_missing() -> None:
    plain = ELEC.replace(
        "floor_heating:  # А-29: старое\n  - { id: fh_old, room: r, thermostat: t1 }\n\n", ""
    )
    out = replace_section(plain, "floor_heating", "floor_heating: []\n")
    assert out is not None and out.startswith(plain.rstrip("\n"))
    assert yaml.safe_load(out)["floor_heating"] == []
    assert replace_section("", "floor_heating", NEW) == NEW


def test_bad_section_or_file_is_refused() -> None:
    assert replace_section(ELEC, "floor_heating", "points: []\n") is None
    assert replace_section(ELEC, "floor_heating", NEW + "panel: {}\n") is None
    assert replace_section(ELEC, "floor_heating", "floor_heating: [") is None
    assert replace_section("- a\n- b\n", "floor_heating", NEW) is None
    assert section_value(NEW, "floor_heating")[0]


def test_items_at_column_zero_belong_to_the_section() -> None:
    # PyYAML's default style: the items of a mapping value are not indented
    flat = yaml.safe_dump(
        {
            "mode": "standard",
            "floor_heating": [{"id": "fh_old", "room": "r"}, {"id": "fh_2", "room": "r"}],
            "panel": {"phases": 1},
        },
        sort_keys=False,
    )
    assert "\n- id: fh_old" in flat
    out = replace_section(flat, "floor_heating", NEW)
    assert out is not None
    data = yaml.safe_load(out)
    assert [z["id"] for z in data["floor_heating"]] == ["fh"]
    assert data["mode"] == "standard" and data["panel"] == {"phases": 1}
    assert "fh_2" not in out
