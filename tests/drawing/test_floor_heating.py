"""The "Floor heating" sheet (drawing/floor_heating.py and its spec in sheets/stages.py): the
cable as lines and arcs tagged with the zone, the controller, the zones table with notes."""

from __future__ import annotations

import pytest
from ezdxf.entities.hatch import Hatch

from floorplan_engine.drawing.floor_heating import (
    CABLE_COLOR,
    FRAME_COLOR,
    draw_floor_heating,
    heating_table,
    zone_label,
)
from floorplan_engine.drawing.ids import object_id
from floorplan_engine.drawing.layers import (
    H_CABLE,
    H_LEAD,
    H_SENSOR,
    H_TEXT,
    H_ZONE,
    LW_HEAT,
    new_document,
)
from floorplan_engine.electrical.floor_heating import heating_zones
from floorplan_engine.model.plumbing import TYPICAL_SPOT
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
    # The zone block names the zone, its section and the pitch; no pitch dimension since
    # 2026-11-17 (the block carries it), no zone name at the sensor
    texts = [t.dxf.text for t in msp.query(f'TEXT[layer=="{H_TEXT.name}"]')]
    assert "ТП1" in texts and any(f"{zone.length:g} м · шаг {zone.pitch:.0f}" == t for t in texts)
    assert not msp.query(f'DIMENSION[layer=="{H_TEXT.name}"]')
    # The controller's number next to its symbol, tagged with its point
    reg_texts = [
        t for t in msp.query(f'TEXT[layer=="{H_TEXT.name}"]') if object_id(t) == ("point", "t1")
    ]
    assert [t.dxf.text for t in reg_texts] == ["1"]
    (tint,) = msp.query(f'HATCH[layer=="{H_ZONE.name}"]')
    assert isinstance(tint, Hatch) and tint.transparency == pytest.approx(0.85, abs=0.01)
    # The area's border is a red frame, bolder than the cable; the cable is a paler red
    frames = msp.query(f'LWPOLYLINE[layer=="{H_ZONE.name}"]')
    assert frames and all(f.dxf.true_color == FRAME_COLOR for f in frames)
    assert all(f.dxf.lineweight > LW_HEAT for f in frames)
    assert len(frames[0]) > 4  # the rectangle's corners are rounded
    assert all(a.dxf.true_color == CABLE_COLOR for a in arcs)
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


def test_cut_outs_are_outlines_with_labels_not_hatches() -> None:
    """A fixture spot and an exclude: a thin outline and a label each (the fixture by its name
    from plumbing, the exclude by its note), no hatch; a furniture spot is left to its layer."""
    plan = make_plan(WALLS)
    _, contours = validate_plan(plan)
    elec = Electrical.model_validate(
        {
            "points": [REG],
            "floor_heating": [
                {
                    "id": "fh1",
                    "room": "r",
                    "thermostat": "t1",
                    "exclude": [{"at": [2000, 2000], "size": [800, 600], "note": "подіум"}],
                    "fixtures": [
                        {"at": [0, 0], "size": [1700, 700], "note": f"{TYPICAL_SPOT}: bath1"}
                    ],
                    "furniture": [
                        {"at": [0, 2000], "size": [600, 1000], "note": "furniture.yaml: k"}
                    ],
                }
            ],
        }
    )
    zones = heating_zones(plan, contours, elec)
    assert [s.kind for s in zones[0].blocked] == ["exclude", "fixture", "furniture"]
    doc = new_document((H_ZONE, H_TEXT, H_CABLE, H_LEAD, H_SENSOR))
    msp = doc.modelspace()
    draw_floor_heating(msp, plan, contours, elec, zones, {"bath1": "Ванна"})
    # The heated area is a tint with the cut-outs as its holes (one hatch: the outer ring and
    # the hole round the exclude; the fixture and the furniture bite the edge) and the zone
    # block stands on a white backing; the cut-outs themselves are not hatched
    (tint,) = msp.query(f'HATCH[layer=="{H_ZONE.name}"]')
    assert isinstance(tint, Hatch) and len(tint.paths) == 2
    assert len(msp.query(f'HATCH[layer=="{H_TEXT.name}"]')) == 1
    labels = {t.dxf.text for t in msp.query(f'TEXT[layer=="{H_TEXT.name}"]')}
    assert {"ванна", "подіум"} <= labels and "k" not in labels
    outlines = msp.query(f'LWPOLYLINE[layer=="{H_ZONE.name}"]')
    # The heated area (its outer ring and the hole round the exclude), the fixture, the exclude;
    # the furniture piece is not drawn here
    assert len(outlines) == 4
