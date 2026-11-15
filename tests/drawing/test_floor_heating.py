"""The "Floor heating" sheet (drawing/floor_heating.py and its spec in sheets/stages.py): the
cable as lines and arcs tagged with the zone, the controller, the zones table with notes."""

from __future__ import annotations

import pytest

from floorplan_engine.drawing.floor_heating import heating_table, zone_label
from floorplan_engine.drawing.ids import object_id
from floorplan_engine.drawing.layers import H_CABLE, H_LEAD, H_SENSOR, H_TEXT
from floorplan_engine.electrical.floor_heating import heating_zones
from floorplan_engine.model.schema import Electrical
from floorplan_engine.sheets.document import sheet_slug
from floorplan_engine.sheets.stages import draw_stages
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan

WALLS = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]
REG = {"id": "t1", "room": "r", "type": "thermostat", "wall": "w4", "offset": 500, "height": 900}


def _elec(heating: bool = True) -> Electrical:
    fh = [{"id": "fh1", "room": "r", "thermostat": "t1"}] if heating else []
    return Electrical.model_validate({"points": [REG], "floor_heating": fh})


def test_sheet_has_the_serpentine_tagged_with_its_zone() -> None:
    plan = make_plan(WALLS)
    _, contours = validate_plan(plan)
    doc, specs = draw_stages(plan, contours, _elec())
    assert "tab_floor_heating" in [s.tab_key for s in specs]
    msp = doc.modelspace()
    arcs = msp.query(f'ARC[layer=="{H_CABLE.name}"]')
    lines = msp.query(f'LINE[layer=="{H_CABLE.name}"]')
    assert len(arcs) > 5 and len(lines) == len(arcs) + 1
    assert {object_id(e) for e in [*arcs, *lines]} == {("heating", "fh1")}
    (zone,) = heating_zones(plan, contours, _elec())
    assert zone.pitch is not None
    assert all(a.dxf.radius == pytest.approx(zone.pitch / 2) for a in arcs)
    assert msp.query(f'LWPOLYLINE[layer=="{H_LEAD.name}"]')
    assert msp.query(f'CIRCLE[layer=="{H_SENSOR.name}"]')  # the sensor
    regs = msp.query(f'INSERT[layer=="{H_TEXT.name}"]')
    assert [object_id(r) for r in regs] == [("point", "t1")]
    assert msp.query(f'DIMENSION[layer=="{H_TEXT.name}"]')  # one pitch
    _, without = draw_stages(plan, contours, _elec(heating=False))
    assert "tab_floor_heating" not in [s.tab_key for s in without]
    assert sheet_slug("06 Тёплый пол") == "floor_heating"
    assert sheet_slug("06 Тепла підлога") == "floor_heating"


# Title, a column, the assumption word, the typical fixture size in the area note
TABLE_TEXTS = {
    "ru": ("Тёплый пол", "Обогрев, м²", "допущение", "приборы — по типовому размеру"),
    "uk": ("Тепла підлога", "Обігрів, м²", "припущення", "прилади — за типовим розміром"),
}


@pytest.mark.parametrize("lang", ["ru", "uk"])
def test_zones_table_marks_assumptions(lang: str) -> None:
    title, column, assumed, typical = TABLE_TEXTS[lang]
    plan = make_plan(WALLS).model_copy(update={"language": lang})
    _, contours = validate_plan(plan)
    elec = _elec()
    zones = heating_zones(plan, contours, elec)
    built = heating_table(plan, elec, zones)
    assert built is not None
    table, notes = built
    assert table.title == title and column in [c.title for c in table.columns]
    (row,) = table.rows
    assert row[0] == zone_label(zones[0]) == "ТП1" and row[1] == "Комната"
    assert str(row[4]).endswith("*") and str(row[5]).endswith("*")  # length and power assumed
    assert table.total is not None and table.total[5] == f"{zones[0].power:.0f}"
    assert any(assumed in n for n in notes)
    assert any(typical in n for n in notes)  # fixture spots by their typical size
    assert heating_table(plan, elec, []) is None


def test_table_shows_auto_zones_source_area_and_furniture() -> None:
    plan = make_plan(WALLS)
    _, contours = validate_plan(plan)
    spot = {"at": [0, 0], "size": [600, 3000], "note": "furniture.yaml: kitchen_1"}
    written = {"id": "fh1", "room": "r", "thermostat": "t1", "area": 9.5, "furniture": [spot]}
    auto = {"id": "auto_t2", "room": "r", "thermostat": "t2", "auto": True}
    elec = Electrical.model_validate(
        {"points": [REG, REG | {"id": "t2"}], "floor_heating": [written, auto]}
    )
    zones = heating_zones(plan, contours, elec)
    built = heating_table(plan, elec, zones)
    assert built is not None
    table, notes = built
    titles = [c.title for c in table.columns]
    assert "По проекту, м²" in titles
    at = titles.index("По проекту, м²")
    first, second = table.rows
    assert first[0] == "ТП1" and first[at] == "9,50"
    assert second[0] == "ТП2*" and second[at] == "—"
    assert any(n.startswith("ТП2* — зоны нет в проекте") for n in notes)
    assert any("ТП1 — kitchen_1" in n for n in notes)
    # Without areas from the source the column is not there
    plain = heating_table(plan, _elec(), heating_zones(plan, contours, _elec()))
    assert plain is not None and "По проекту, м²" not in [c.title for c in plain[0].columns]
