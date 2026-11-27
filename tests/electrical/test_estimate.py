"""Electrical estimate: quantities from the model, prices from the price list, items without a
price.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import floorplan_engine.electrical.estimate.texts as estimate_texts
from floorplan_engine.drawing.tables import Guess
from floorplan_engine.electrical.estimate import Estimate, Line, build_estimate
from floorplan_engine.electrical.estimate.items import (
    CHASE_KEYS,
    HINTS,
    LINES,
    SECTIONS,
    Section,
    split_key,
)
from floorplan_engine.electrical.estimate.quantities import quantities
from floorplan_engine.electrical.estimate.texts import format_number
from floorplan_engine.electrical.panel import build_panel, busbars, device_name
from floorplan_engine.electrical.price_list import (
    PriceList,
    unknown_keys,
)
from floorplan_engine.electrical.pricing import MockPriceService, Prices, mock_price
from floorplan_engine.electrical.splices import back_box_joints
from floorplan_engine.electrical.wiring import RESERVE, box_wiring
from floorplan_engine.model.schema import Electrical
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan, room_wiring

RECT = [{"length": 3000}, {"length": 4000}, {"length": 3000}, {"length": 4000}]
DOOR = {"wall": "w2", "type": "door", "offset": 1000, "width": 900}


def _pt(
    pid: str, kind: str, offset: float, height: float, group: str, **extra: Any
) -> dict[str, Any]:
    return {
        "id": pid,
        "room": "r",
        "type": kind,
        "wall": "w3",
        "offset": offset,
        "height": height,
        "group": group,
        **extra,
    }


ELEC: dict[str, Any] = {
    "points": [
        {"id": "l1", "room": "r", "type": "downlight", "ceiling": [1000, 1500], "group": "QF1"},
        _pt("k1", "switch", 2500, 900, "QF1", keys=2),
        _pt("s1", "socket", 500, 300, "QF2", count=2),
        _pt("s2", "socket", 1500, 300, "QF2"),
    ],
    "board": {"room": "r", "wall": "w1", "offset": 500, "height": 1700},
}


def _wiring() -> tuple[Any, Electrical]:
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    elec = Electrical.model_validate(ELEC)
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    return wiring, elec


def test_prices_and_unpriced_lines() -> None:
    wiring, elec = _wiring()
    prices = PriceList.model_validate(
        {
            "items": {
                "cable.3x2.5": 70,
                "work.board_module": 100,
                "socket_box": {"price": 20, "name": "Підрозетник Kopos"},
            },
            "board_kit": [{"name": "Реле", "price": 1500, "modules": 2}],  # deprecated
        }
    )
    est = build_estimate(wiring, elec, prices, "uk")
    by_key = {ln.key: ln for ln in est.lines}
    assert by_key["socket_box"].name == "Підрозетник Kopos" and by_key["socket_box"].total == 80
    box = next(ln for k, ln in by_key.items() if k.startswith("junction_box."))
    assert box.price is None and est.unpriced > 0
    module = by_key["work.board_module"]
    # Without a panel set: one breaker per group; board_kit is not used
    assert module.qty == 2 and module.total == 200
    assert not any(ln.key == "board_kit" for ln in est.lines)
    assert est.total == pytest.approx(sum(ln.total or 0 for ln in est.lines))
    sections = [ln.section for ln in est.lines]
    assert sections == sorted(sections, key=SECTIONS.index)  # materials, rough, finishing
    assert unknown_keys(PriceList.model_validate({"items": {"cabel.3x1.5": 1, "frame.2": 5}})) == [
        "cabel.3x1.5"
    ]


def test_estimate_table_with_and_without_prices() -> None:
    from floorplan_engine.drawing.schedules import estimate_table

    wiring, elec = _wiring()
    prices = PriceList.model_validate({"items": {"socket_box": 20}})
    priced = build_estimate(wiring, elec, prices, "uk")
    table = estimate_table(priced, "uk", priced=True)
    assert table.title == "Кошторис електрики" and len(table.columns) == 6
    names = [r[1] for r in table.rows]
    # Section headings are plain (decision 2026-11-23): the mark is on the materials totals
    assert names[0] == "Чорнові матеріали"
    assert "Чистові матеріали" in names
    assert "Чорнові роботи" in names and "Чистові роботи" in names
    # A section total is a plain "Total": the section name is in the heading right above it
    assert names.count("Разом") == 4
    assert not any(str(n).startswith("Разом:") for n in names)
    assert table.total is not None and table.total[1] == "Усього"
    socket_box = next(r for r in table.rows if r[1] == "Підрозетник")
    assert socket_box[4] == "20" and socket_box[5] == "80"  # 4 posts × 20
    unpriced = next(r for r in table.rows if r[1] == "Розетка із заземленням")
    assert unpriced[4] == unpriced[5] == "—"

    volumes = estimate_table(build_estimate(wiring, elec, PriceList(), "uk"), "uk", priced=False)
    assert volumes.title == "Відомість обсягів електрики"
    assert len(volumes.columns) == 4 and volumes.total is None  # no prices and no totals
    assert not any(str(r[1]).startswith("Разом") for r in volumes.rows)
    assert volumes.rows[0][1] == "Чорнові матеріали"
    assert not any(isinstance(c, Guess) for r in volumes.rows for c in r)  # nothing to mark


def _subtotals(table: Any) -> list[Any]:
    """Amount cells of the section totals of an estimate sheet table, in section order."""
    return [r[5] for r in table.rows if r[1] in ("Разом", "Итого")]


def test_estimate_table_marks_material_totals_as_provisional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While material prices are a placeholder, each materials total is a Guess cell: " !" on
    the sheet; work totals and the grand total stay plain (decision 2026-11-23)."""
    from floorplan_engine.drawing.schedules import estimate_table

    wiring, elec = _wiring()
    est = build_estimate(
        wiring, elec, PriceList.model_validate({"items": {"socket_box": 20}}), "uk"
    )
    cells = _subtotals(estimate_table(est, "uk", priced=True))
    assert [isinstance(c, Guess) for c in cells] == [True, True, False, False]
    assert cells[0].mark == " !" and cells[0].text == format_number(est.subtotal("material_rough"))
    table = estimate_table(est, "uk", priced=True)
    assert table.total is not None and isinstance(table.total[5], str)
    monkeypatch.setattr(estimate_texts, "MATERIAL_PRICES_MOCK", False)
    assert not any(isinstance(c, Guess) for c in _subtotals(estimate_table(est, "uk", True)))


def test_estimate_on_wiring_sheet(tmp_path: Path) -> None:
    """The estimate sits on the wiring CAD sheet with the same text as in the table."""
    from ezdxf.filemanagement import readfile

    from floorplan_engine.sheets.document import build_project_document
    from floorplan_engine.sheets.preview import sheet_layouts

    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    elec = Electrical.model_validate(ELEC)
    prices = Prices(PriceList.model_validate({"items": {"socket_box": 20}}))
    path = tmp_path / "project.dxf"
    build_project_document(plan, contours, elec, prices=prices).saveas(path, encoding="utf-8")
    texts = {
        lay.name: {e.dxf.text for e in lay if e.dxftype() == "TEXT"}
        for lay in sheet_layouts(readfile(path))
    }
    wiring_tab = next(name for name in texts if name.endswith("Проводка"))
    assert "Смета электрики" in texts[wiring_tab]  # the plan language defaults to ru
    # Materials totals are provisional on the sheet: " !" after the amount (decision 2026-11-23)
    assert any(t.endswith(" !") for t in texts[wiring_tab])
    assert not any("Смета электрики" in t for name, t in texts.items() if name != wiring_tab)


def test_box_price_falls_back_to_size_free_key() -> None:
    wiring, elec = _wiring()
    prices = PriceList.model_validate({"items": {"junction_box": 60}})
    est = build_estimate(wiring, elec, prices, "uk")
    boxes = [ln for ln in est.lines if ln.key.startswith("junction_box.")]
    assert boxes and all(ln.price == 60 for ln in boxes)
    assert all("×" in ln.name or "Ø" in ln.name for ln in boxes)  # size in the name


def _line(section: Section, qty: float, price: float | None, key: str = "k") -> Line:
    return Line(section, key, key, "шт", qty, price)


@pytest.mark.parametrize(
    ("qty", "price", "total"), [(3, 10.0, 30.0), (2.5, 4.0, 10.0), (0, 7.0, 0.0), (5, None, None)]
)
def test_line_total(qty: float, price: float | None, total: float | None) -> None:
    assert _line("material", qty, price).total == total


def test_estimate_subtotals_skip_unpriced_lines() -> None:
    est = Estimate(
        (
            _line("material", 2, 10.0),
            _line("material", 1, None),
            _line("rough", 3, 5.0),
            _line("rough", 4, None),
            _line("finish", 2, 7.0),
        ),
        "грн",
    )
    assert est.subtotal("material") == 20
    assert est.subtotal("rough") == 15 and est.subtotal("finish") == 14
    assert est.work == 29
    assert est.total == 49
    assert est.unpriced == 2


def test_works_split_into_rough_and_finish() -> None:
    """Rough work is before finishing (chases, cable, boxes, panel enclosure, test); finishing is
    after (filling the panel with devices, fitting devices). Materials follow the work they are
    bought for: rough (cable, boxes, enclosures), finish (panel and wiring devices, lights)."""
    works = {k: v[0] for k, v in LINES.items() if k.startswith("work.")}
    finish = {
        "work.board_module",
        "work.panel_labels",
        "work.mechanism",
        "work.led_psu",
        "work.led_psu_din",
        "work.protection_test",
    }
    assert {k for k, s in works.items() if s == "finish"} == finish
    assert all(s == "rough" for k, s in works.items() if s != "finish")
    materials = {k: v[0] for k, v in LINES.items() if not k.startswith("work.")}
    rough = {
        "cable",
        "conduit",
        "conduit_joint",
        "socket_box",
        "junction_box",
        "junction_box_ip",
        "crimp",
        "conduit_clip",
        "cable_pad",
        "board_enclosure",
        "dc_enclosure",
        "led_enclosure",
        "rough_holder",
        "rough_lamp",
        "rough_switch",
        "heating_cable",
        "heating_sensor",
        "heating_conduit",
    }
    assert {k for k, s in materials.items() if s == "material_rough"} == rough
    assert all(s == "material_finish" for k, s in materials.items() if k not in rough)
    wiring, elec = _wiring()
    est = build_estimate(wiring, elec, PriceList(), "ru")
    by_key = {ln.key: ln.section for ln in est.lines}
    assert by_key["work.chase"] == "rough" and by_key["work.mechanism"] == "finish"
    assert by_key["socket_box"] == "material_rough" and by_key["socket"] == "material_finish"
    sections = [ln.section for ln in est.lines]  # rough materials, finish ones, then the work
    assert sections == sorted(sections, key=SECTIONS.index)
    assert est.materials == est.subtotal("material_rough") + est.subtotal("material_finish")
    assert est.total == est.materials + est.work


def test_empty_estimate_is_zero() -> None:
    est = Estimate((), "грн")
    assert est.subtotal("material") == 0 and est.total == 0 and est.unpriced == 0


def test_panel_from_board_sheet_priced_by_kind() -> None:
    """The panel in the estimate is the "Panel" sheet set: a row per kind and rating, as in the
    purchase list; price by kind, refined by rating; assembly by the set's modules; no breaker per
    group."""
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    elec = Electrical.model_validate(ELEC)
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    panel = build_panel(plan, elec)
    assert panel is not None
    prices = PriceList.model_validate(
        {"items": {"breaker": 140, "breaker.C16": 160, "input": 500, "work.board_module": 100}}
    )
    est = build_estimate(wiring, elec, prices, "ru", panel)
    devices = [
        ln for ln in est.lines if split_key(ln.key)[0] in {d.kind.value for d in panel.devices}
    ]
    names = {device_name(d, "ru") for d in panel.devices}
    assert {ln.name for ln in devices} == names  # the same names as in the purchase list
    assert sum(ln.qty for ln in devices) == len(panel.devices)
    by_name = {ln.name: ln for ln in devices}
    for d in panel.devices:
        ln = by_name[device_name(d, "ru")]
        if d.kind.value == "breaker":
            assert ln.price == (160 if d.label == "C16" else 140)
        if d.kind.value == "input":
            assert ln.price == 500
    assert next(ln for ln in est.lines if ln.key == "work.board_module").qty == panel.modules
    keys = [ln.key for ln in est.lines]
    assert "breaker" not in keys  # "per group" breaker only without a panel
    assert keys.index("board_enclosure") < keys.index(devices[0].key)  # devices after the enclosure
    assert not any(k.startswith("busbar") for k in keys)  # lone devices are wired, not combed


def test_comb_busbars_after_the_panel_devices() -> None:
    """Comb busbars of the group rails (instead of wire jumpers): 1 m bars by poles, as counted
    by panel.busbars, in the materials right after the panel devices; priced as any item."""
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    more = [_pt(f"x{k}", "socket", 400 + 300 * k, 300, f"QF{k}") for k in range(3, 7)]
    elec = Electrical.model_validate({**ELEC, "points": [*ELEC["points"], *more]})
    wiring = box_wiring(plan, contours, elec)
    panel = build_panel(plan, elec)
    assert wiring is not None and panel is not None
    counted = {f"busbar.{p}P": n for p, n in busbars(panel).items()}
    assert counted
    prices = PriceList.model_validate({"items": {"busbar": 180, "busbar.2P": 390}})
    est = build_estimate(wiring, elec, prices, "ru", panel)
    combs = [ln for ln in est.lines if split_key(ln.key)[0] == "busbar"]
    assert {ln.key: ln.qty for ln in combs} == counted
    assert all(ln.section == "material_finish" and ln.unit == "шт" for ln in combs)
    assert all(ln.price == (390 if ln.key == "busbar.2P" else 180) for ln in combs)
    assert combs[0].name.startswith("Шина гребенчатая") and "перемычек" in (combs[0].hint or "")
    keys = [ln.key for ln in est.lines]
    kinds = {d.kind.value for d in panel.all_devices}
    last = max(k for k, key in enumerate(keys) if split_key(key)[0] in kinds)
    # Right after the devices (the battery box ones too); the box enclosures are rough materials
    assert keys.index(combs[0].key) == last + 1 and keys.index("dc_enclosure") < last
    assert build_estimate(wiring, elec, PriceList(), "ru").lines  # no panel set: no busbars
    assert not any(
        ln.key.startswith("busbar") for ln in build_estimate(wiring, elec, PriceList()).lines
    )


def test_battery_box_in_estimate() -> None:
    """The inverter battery box is in the estimate: a battery breaker with the panel devices and an
    enclosure with an article number next to the panel one.
    """
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    elec = Electrical.model_validate(ELEC)
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    panel = build_panel(plan, elec)
    assert panel is not None and panel.dc is not None
    est = build_estimate(wiring, elec, PriceList(), "ru", panel)
    keys = [ln.key for ln in est.lines]
    assert "dc_battery.125 А DC 2P" in keys
    box = next(ln for ln in est.lines if ln.key == "dc_enclosure")
    assert box.name == "Корпус щита АКБ Hager Golf VS112PD, 12 мод."
    # The enclosure is a rough material next to the panel one, the devices are finish ones
    assert keys.index("board_enclosure") + 1 == keys.index("dc_enclosure")
    assert box.section == "material_rough"
    assert keys.index("dc_enclosure") < keys.index("dc_battery.125 А DC 2P")


def test_fixtures_and_led_in_estimate() -> None:
    """Lights, outputs and LED strip are in the estimate, named as in the legend."""
    wiring, _ = _wiring()
    outlet = _pt("o1", "outlet", 2000, 2200, "QF2")
    led = {"id": "led1", "room": "r", "wall": "w1", "start": 0, "end": 1500}
    elec = Electrical.model_validate(
        {**ELEC, "points": [*ELEC["points"], outlet], "led_strips": [led]}
    )
    est = build_estimate(wiring, elec, PriceList(), "uk")
    by_key = {ln.key: ln for ln in est.lines}
    assert (by_key["downlight"].name, by_key["downlight"].qty) == ("Світильник точковий", 1)
    assert (by_key["outlet"].name, by_key["outlet"].qty) == ("Вивід кабелю до техніки", 1)
    assert (by_key["led_strip"].unit, by_key["led_strip"].qty) == ("м", 1.5)


def test_mechanism_hint_says_price_tbd_only_without_price() -> None:
    """Device fitting has a note; "price to be confirmed" only while there is no price."""
    wiring, elec = _wiring()
    open_ = build_estimate(wiring, elec, PriceList(), "uk")
    line = next(ln for ln in open_.lines if ln.key == "work.mechanism")
    assert line.hint == "Встановлення розеток, вимикачів, інтернет- і ТВ-виводів. Ціна уточнюється"
    priced = build_estimate(
        wiring, elec, PriceList.model_validate({"items": {"work.mechanism": 80}})
    )
    line = next(ln for ln in priced.lines if ln.key == "work.mechanism")
    assert line.hint == "Установка розеток, выключателей, интернет- и ТВ-выводов"
    # A chase without a wall material has its own note (CHASE_KEYS)
    rest = [ln for ln in priced.lines if split_key(ln.key)[0] not in HINTS]
    assert all(ln.hint is None for ln in rest if ln.key not in CHASE_KEYS)


def test_gun_fixing_names_and_mock_prices() -> None:
    wiring, elec = _wiring()
    elec = elec.model_copy(update={"conduit": "ceiling"})
    est = build_estimate(wiring, elec, Prices(None, MockPriceService()))
    by_key = {ln.key: ln for ln in est.lines}
    clip = next(ln for k, ln in by_key.items() if k.startswith("conduit_clip."))
    assert "под монтажный пистолет" in clip.name and clip.price == mock_price(clip.key)
    assert by_key["cable_pad"].name.startswith("Площадка под монтажный пистолет")
    assert by_key["cable_pad"].hint is not None
    assert unknown_keys(PriceList.model_validate({"items": {"cable_fixing": 2}})) == []


def test_extra_options_panel_labels_and_insulation_test() -> None:
    """Both on by default: panel labels at a fixed price right after the assembly, an insulation
    test per power group; the variant can drop each of them."""
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    elec = Electrical.model_validate(ELEC)
    wiring = box_wiring(plan, contours, elec)
    panel = build_panel(plan, elec)
    assert wiring is not None and panel is not None
    keys = [ln.key for ln in build_estimate(wiring, elec, PriceList(), "ru", panel).lines]
    at = keys.index("work.board_module")
    assert keys[at + 1] == "work.panel_labels" and "work.insulation_test" in keys
    by_key = {ln.key: ln for ln in build_estimate(wiring, elec, PriceList(), "ru", panel).lines}
    assert by_key["work.panel_labels"].qty == 1  # a fixed price per panel, whatever its size
    assert by_key["work.panel_labels"].unit == "щит"
    off = elec.model_copy(update={"panel_labels": False, "insulation_test": False})
    keys = [ln.key for ln in build_estimate(wiring, off, PriceList(), "ru", panel).lines]
    assert "work.panel_labels" not in keys and "work.insulation_test" not in keys
    no_panel = [ln.key for ln in build_estimate(wiring, elec, PriceList(), "ru").lines]
    assert "work.panel_labels" not in no_panel  # nothing to label without the panel sheet
    # The protection test (RCD tripping, short-circuit current): off unless chosen, per power
    # group as the insulation test, in the finishing work
    assert "work.protection_test" not in by_key
    on = elec.model_copy(update={"protection_test": True})
    by_key = {ln.key: ln for ln in build_estimate(wiring, on, PriceList(), "ru", panel).lines}
    test = by_key["work.protection_test"]
    assert test.qty == by_key["work.insulation_test"].qty and test.unit == "гр."
    assert LINES["work.protection_test"][0] == "finish"


LED = _pt("led1", "led_output", 2000, 1500, "QF1")


def test_chases_split_by_wall_material() -> None:
    """Chase metres by wall material: the wall's own one, otherwise the plan default; a chase
    without a known material stays work.chase, priced as brick with a note (Kyiv 2026-11)."""
    walls = [{**w, "material": "concrete"} if k == 0 else w for k, w in enumerate(RECT)]
    plan = make_plan(walls, [DOOR])
    elec = Electrical.model_validate(ELEC)
    _, contours = validate_plan(plan)
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    on = {c.wall: c.material for c in wiring.chases if c.wall}
    assert on.get("w1") == "concrete" and all(m is None for w, m in on.items() if w != "w1")
    q = quantities(wiring, elec)
    chase = {k: v for k, v in q.items() if split_key(k)[0] in CHASE_KEYS}
    assert sum(chase.values()) == pytest.approx(wiring.chase_mm / 1000, abs=0.2)
    assert "work.chase.concrete" in chase and "work.chase" in chase
    est = build_estimate(wiring, elec, Prices(None, MockPriceService()), "ru")
    by_key = {ln.key: ln for ln in est.lines}
    concrete = by_key["work.chase.concrete"]
    assert (concrete.name, concrete.price) == ("Штроба узкая, 1–2 кабеля, бетон", 200)
    unknown = by_key["work.chase"]
    assert unknown.price == 120 and unknown.hint is not None
    assert unknown.hint.startswith("Материал стены не указан")
    # the plan default covers walls without their own material
    plan = plan.model_copy(update={"default_wall_material": "aerated"})
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    keys = {k for k in quantities(wiring, elec) if split_key(k)[0] in CHASE_KEYS}
    assert "work.chase" not in keys and "work.chase.aerated" in keys


def test_thermostat_is_one_row_by_point() -> None:
    """A floor heating controller: its own item by point, priced by the mock (2026-11-24); no flush
    box, frame or fitting work is counted for it (its work comes later)."""
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    reg = [_pt("t1", "thermostat", 2000, 1500, "QF5"), _pt("t2", "thermostat", 2800, 1500, "QF5")]
    elec = Electrical.model_validate({**ELEC, "points": [*ELEC["points"], *reg]})
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    base_wiring, base = _wiring()
    q, q0 = quantities(wiring, elec), quantities(base_wiring, base)
    assert q["thermostat"] == 2 and "thermostat" not in q0
    for key in ("socket_box", "work.socket_box", "work.mechanism", "frame.1", "switch2"):
        assert q.get(key) == q0.get(key), key
    prices = Prices(None, MockPriceService())
    est = build_estimate(wiring, elec, prices, "ru")
    row = next(ln for ln in est.lines if ln.key == "thermostat")
    assert (row.name, row.unit, row.qty) == ("Регулятор тёплого пола", "шт", 2)
    assert row.price == 3000 and row.total == 6000 and row.section == "material_finish"
    assert est.unpriced == 0
    assert est.total == pytest.approx(sum(ln.total for ln in est.lines if ln.total is not None))
    assert build_estimate(wiring, elec, prices, "uk").lines[est.lines.index(row)].name == (
        "Регулятор теплої підлоги"
    )
    # A studio price list beats the mock like for any other item
    own = PriceList.model_validate({"items": {"thermostat": 1000}})
    priced = build_estimate(wiring, elec, Prices(own, MockPriceService()), "ru")
    assert priced.unpriced == 0 and priced.total == pytest.approx(est.total - 4000)


@pytest.mark.usefixtures("heating_released")
def test_floor_heating_rows_by_zone_without_prices() -> None:
    """Floor heating (decision 2026-11-14): a section per zone by its length, a sensor and its
    conduit, the laying work by heated area — all without a price (pricing.UNPRICED)."""
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    reg = _pt("t1", "thermostat", 2000, 1500, "QF5")
    fh = [{"id": "fh1", "room": "r", "thermostat": "t1"}]
    elec = Electrical.model_validate(
        {**ELEC, "points": [*ELEC["points"], reg], "floor_heating": fh}
    )
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    (zone,) = wiring.heating
    q = quantities(wiring, elec)
    assert q[f"heating_cable.{zone.length:g}"] == 1
    assert q["heating_sensor"] == 1
    assert q["heating_conduit"] == pytest.approx(round(zone.sensor_m * (1 + RESERVE), 1))
    assert q["work.floor_heating"] == pytest.approx(round(zone.area_m2, 1))
    est = build_estimate(wiring, elec, Prices(None, MockPriceService()), "ru")
    rows = {ln.key: ln for ln in est.lines if "heating" in ln.key}
    assert set(rows) == {
        f"heating_cable.{zone.length:g}",
        "heating_sensor",
        "heating_conduit",
        "work.floor_heating",
    }
    assert all(ln.price is None for ln in rows.values())
    cable = rows[f"heating_cable.{zone.length:g}"]
    assert cable.name == f"Секция нагревательного кабеля {zone.length:g} м"
    assert cable.hint is not None and "допущение" in cable.hint
    assert "heating_sensor" not in quantities(*_wiring())


def _two_switches() -> list[dict[str, Any]]:
    """Light in a chain where one switch feeds the other: panel → k2 → k1 → l1 (test_splices)."""
    return [
        {"id": "l1", "room": "r", "type": "downlight", "ceiling": [1500, 2000], "group": "QF1"},
        _pt("k1", "switch", 500, 900, "QF1"),
        _pt("k2", "switch", 2500, 900, "QF1"),
    ]


def test_switch_joint_work_without_clamp_lines_with_note(tmp_path: Path) -> None:
    """Joints in switch flush boxes (decision 2026-11-25): only the work, named for the switch,
    rough, no price anywhere (pricing.UNPRICED); no Wago clamp lines — the note says the method
    and why; sockets of a loop have no joints."""
    wiring, elec = room_wiring(_two_switches(), light_wiring="chain")
    est = build_estimate(wiring, elec, Prices(None, MockPriceService()), "uk")
    by_key = {ln.key: ln for ln in est.lines}
    work = by_key["work.splice"]
    assert (work.section, work.price, work.qty, work.name) == (
        "rough",
        None,
        2,
        "З'єднання N і PE в підрозетнику вимикача",
    )
    assert "уточнюється" in (work.hint or "") and "Wago" in (work.hint or "")
    assert not any(k.startswith("wago") for k in by_key) and "crimp" not in by_key
    assert "wago" not in LINES
    note = estimate_texts.text("note_splice", "ru")
    assert "Wago 221" in note and "отдельной строкой" in note and "60 мм" in note
    assert "без соединений" in note and "1.7.144" not in note
    assert "опресування" in estimate_texts.text("note_splice", "uk")


def test_crimp_splice_counts_only_its_own_work() -> None:
    """splice crimp, a studio setting in its price list (decision 2026-11-25): the work —
    work.splice_crimp, named for the switch; the sleeves of flush boxes are not itemised, crimp
    stays for junction boxes only; no work.splice."""
    wiring, elec = room_wiring(_two_switches(), light_wiring="chain")
    joints = back_box_joints(wiring, elec)
    assert sorted(len(fb.joints) for fb in joints.values()) == [2, 3]  # k1: N, PE; k2: L, N, PE
    q = quantities(wiring, elec, "crimp")
    assert q["work.splice_crimp"] == 2 and "crimp" not in q and "work.splice" not in q
    assert quantities(wiring, elec, "wago")["work.splice"] == 2
    own = PriceList.model_validate({"splice": "crimp"})
    est = build_estimate(wiring, elec, Prices(own, MockPriceService()), "ru")
    by_key = {ln.key: ln for ln in est.lines}
    work = by_key["work.splice_crimp"]
    assert (work.section, work.price, work.name) == (
        "rough",
        None,
        "Соединение N и PE в подрозетнике выключателя опрессовкой",
    )
    assert "crimp" not in by_key and "work.splice" not in by_key
    note = estimate_texts.text("note_splice_crimp", "uk")
    assert "60 мм" in note and "без пружин" in note and "окремим рядком" in note


def test_splice_defaults_to_wago_without_a_studio_setting() -> None:
    """No splice in the price list, no list at all, or the price service alone — wago."""
    wiring, elec = room_wiring(_two_switches(), light_wiring="chain")
    assert PriceList().splice is None and MockPriceService().splice is None
    for prices in (PriceList(), Prices(), Prices(PriceList(), MockPriceService())):
        keys = {ln.key for ln in build_estimate(wiring, elec, prices, "ru").lines}
        assert "work.splice" in keys and "work.splice_crimp" not in keys
    crimp = Prices(PriceList.model_validate({"splice": "crimp"}), MockPriceService())
    assert crimp.splice == "crimp" and PriceList.model_validate({"splice": "wago"}).splice == "wago"
    with pytest.raises(ValueError):
        PriceList.model_validate({"splice": "solder"})
