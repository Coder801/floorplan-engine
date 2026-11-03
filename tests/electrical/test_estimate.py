"""Electrical estimate: quantities from the model, prices from the price list, items without a
price.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from floorplan_engine.electrical.estimate import (
    LINES,
    SECTIONS,
    Estimate,
    Line,
    Price,
    PriceList,
    Section,
    build_estimate,
    edit_price_items,
    format_number,
    quantities,
    split_key,
    unknown_keys,
)
from floorplan_engine.electrical.panel import build_panel, device_name
from floorplan_engine.electrical.pricing import Prices
from floorplan_engine.electrical.wiring import RESERVE, box_wiring
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.pipeline import build_project, estimate_project
from floorplan_engine.validation.plan import validate_plan
from tests.conftest import make_plan

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


def test_quantities_from_model() -> None:
    wiring, elec = _wiring()
    q = quantities(wiring, elec)
    for mark, m in wiring.by_mark().items():
        assert q[f"cable.{mark}"] == pytest.approx(round(m * (1 + RESERVE), 1))
    assert q["socket_box"] == 4  # 2 + 1 sockets + a switch
    assert q["frame.1"] == 2 and q["frame.2"] == 1
    assert q["switch2"] == 1 and q["socket"] == 3
    boxes = len(wiring.boxes)
    assert sum(v for k, v in q.items() if k.startswith("junction_box.")) == boxes
    assert all(f"junction_box.{b.size}" in q for b in wiring.boxes)  # by size
    assert q["crimp"] == 3 * boxes + 2  # two-key switch from a box
    assert q["breaker"] == 2
    narrow, wide = wiring.chase_length(wide=False), wiring.chase_length(wide=True)
    assert narrow + wide == pytest.approx(wiring.chase_mm)
    assert q["work.chase"] == pytest.approx(round(narrow / 1000, 1))
    assert q.get("work.chase_wide", 0) == pytest.approx(round(wide / 1000, 1))
    assert q["work.marking"] == 2 * len(wiring.runs)  # a tag at each end
    assert q["work.insulation_test"] == 2  # per power group
    assert q["work.cable"] == pytest.approx(round(sum(r.length_mm for r in wiring.runs) / 1000, 1))


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

    # Without prices.yaml all prices come from the price service (mock); the estimate still has a
    # total
    no_prices = estimate_project(project)
    est = no_prices.estimate
    assert est is not None and est.total > 0 and est.unpriced == 0
    assert est.from_service == len(est.lines) and no_prices.prices is None
    assert "Все цены — из сервиса цен" in no_prices.files[0].read_text("utf-8")

    (project / "prices.yaml").write_text("items:\n  socket_box: 20\n  work.chase: 200\n", "utf-8")
    result = estimate_project(project)
    assert result.estimate is not None and result.estimate.total > 0
    assert result.estimate.from_service == len(result.estimate.lines) - 2  # own price list on top
    md, csv_path, xlsx = result.files
    assert xlsx.suffix == ".xlsx" and xlsx.stat().st_size > 0
    text = md.read_text("utf-8")
    assert "Смета электрики: Кв" in text and "из сервиса цен (пока имитация" in text
    raw = csv_path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM: Excel recognises UTF-8
    assert "socket_box;Подрозетник;шт;4;20;80,00" in raw.decode("utf-8-sig")

    (project / "prices.yaml").write_text("items:\n  sockt_box: 20\n", "utf-8")
    bad = estimate_project(project)
    assert bad.estimate is None
    assert any(i.file == "prices.yaml" and i.path == "items.sockt_box" for i in bad.issues)

    # build writes the same estimate, so the Excel in the viewer matches the sheets; a price list
    # with errors gives no estimate (errors go to price_issues)
    (project / "prices.yaml").write_text("items:\n  socket_box: 20\n", "utf-8")
    built = build_project(project)
    assert [f.name for f in built.estimate] == ["estimate.md", "estimate.csv", "estimate.xlsx"]
    (project / "prices.yaml").write_text("items:\n  sockt_box: 20\n", "utf-8")
    broken = build_project(project)
    assert broken.price_issues and not broken.estimate
    assert not (project / "out" / "estimate.xlsx").exists()


def test_wet_boxes_and_wall_holes_in_estimate() -> None:
    data = make_plan(RECT, [DOOR]).model_dump()
    data["rooms"][0]["wet"] = True
    plan = Plan.model_validate(data)
    _, contours = validate_plan(plan)
    elec = Electrical.model_validate(ELEC)
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    q = quantities(wiring, elec)
    ip = sum(v for k, v in q.items() if k.startswith("junction_box_ip."))
    assert ip == len(wiring.boxes) and not any(k.startswith("junction_box.") for k in q)
    assert q.get("work.wall_hole", 0) == len(wiring.holes)


def test_estimate_table_with_and_without_prices() -> None:
    from floorplan_engine.drawing.schedules import estimate_table

    wiring, elec = _wiring()
    prices = PriceList.model_validate({"items": {"socket_box": 20}})
    priced = build_estimate(wiring, elec, prices, "uk")
    table = estimate_table(priced, "uk", priced=True)
    assert table.title == "Кошторис електрики" and len(table.columns) == 6
    names = [r[1] for r in table.rows]
    assert names[0] == "Матеріали" and "Чорнові роботи" in names and "Чистові роботи" in names
    assert "Разом: матеріали" in names and "Разом: чорнові роботи" in names
    assert "Разом: чистові роботи" in names
    assert table.total is not None and table.total[1] == "Усього"
    socket_box = next(r for r in table.rows if r[1] == "Підрозетник")
    assert socket_box[4] == "20" and socket_box[5] == "80"  # 4 posts × 20
    unpriced = next(r for r in table.rows if r[1] == "Розетка із заземленням")
    assert unpriced[4] == unpriced[5] == "—"

    volumes = estimate_table(build_estimate(wiring, elec, PriceList(), "uk"), "uk", priced=False)
    assert volumes.title == "Відомість обсягів електрики"
    assert len(volumes.columns) == 4 and volumes.total is None  # no prices and no totals
    assert not any(str(r[1]).startswith("Разом") for r in volumes.rows)


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
    assert not any("Смета электрики" in t for name, t in texts.items() if name != wiring_tab)


def test_box_price_falls_back_to_size_free_key() -> None:
    wiring, elec = _wiring()
    prices = PriceList.model_validate({"items": {"junction_box": 60}})
    est = build_estimate(wiring, elec, prices, "uk")
    boxes = [ln for ln in est.lines if ln.key.startswith("junction_box.")]
    assert boxes and all(ln.price == 60 for ln in boxes)
    assert all("×" in ln.name or "Ø" in ln.name for ln in boxes)  # size in the name


def _eval_xlsx(path: Path) -> float:
    """Recompute the "Total" of the estimate workbook from its formulas (no Excel at hand)."""
    import re

    from openpyxl import load_workbook

    ws = load_workbook(path).active
    assert ws is not None
    values: dict[str, float] = {}

    def cell(ref: str) -> float:
        if ref in values:
            return values[ref]
        v = ws[ref].value
        if isinstance(v, str) and v.startswith("=IF("):
            r = re.findall(r"\d+", v)[0]
            price = ws[f"E{r}"].value
            out = 0.0 if price is None else float(ws[f"D{r}"].value) * float(price)
        elif isinstance(v, str) and v.startswith("=SUM("):
            a, b = (int(x) for x in re.findall(r"F(\d+)", v))
            out = sum(cell(f"F{k}") for k in range(a, b + 1))
        elif isinstance(v, str) and v.startswith("="):
            out = sum(cell(ref) for ref in re.findall(r"F\d+", v))
        else:
            out = float(v or 0)
        values[ref] = out
        return out

    grand = next(
        r for r in range(1, ws.max_row + 1) if str(ws[f"B{r}"].value or "").startswith("Усього")
    )
    return cell(f"F{grand}")


def test_xlsx_formulas_give_estimate_total(tmp_path: Path) -> None:
    wiring, elec = _wiring()
    prices = PriceList.model_validate({"items": {"cable.3x2.5": 70, "work.cable": 30}})
    est = build_estimate(wiring, elec, prices, "uk")
    from floorplan_engine.electrical.estimate import write_xlsx

    path = write_xlsx(est, tmp_path / "e.xlsx", "Кошторис", ["примітка"], "uk")
    assert _eval_xlsx(path) == pytest.approx(est.total)
    assert est.unpriced > 0  # items without a price are in the workbook but not in the total


def test_studio_prices_used_when_project_has_none(tmp_path: Path) -> None:
    from floorplan_engine.pipeline import find_prices

    project = tmp_path / "kv"
    project.mkdir()
    assert find_prices(project) is None
    (tmp_path / "prices.yaml").write_text("items: {}\n", "utf-8")
    assert find_prices(project) == tmp_path / "prices.yaml"
    (project / "prices.yaml").write_text("items: {}\n", "utf-8")
    assert find_prices(project) == project / "prices.yaml"  # own price list beats the studio one


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("cable.3x1.5", ("cable", "3x1.5")),
        ("frame.2", ("frame", "2")),
        ("cable", ("cable", "")),
        ("cable.", ("cable.", "")),
        ("work.cable", ("work.cable", "")),
        ("socket", ("socket", "")),
        ("", ("", "")),
    ],
)
def test_split_key(key: str, expected: tuple[str, str]) -> None:
    assert split_key(key) == expected


def test_unknown_keys_lists_only_foreign_keys_in_order() -> None:
    prices = PriceList.model_validate(
        {
            "items": {
                "socket": 1,
                "sokcet": 2,
                "cable.3x2.5": 3,
                "work.cable": 4,
                "work.unknown": 5,
                "frame.3": 6,
            }
        }
    )
    assert unknown_keys(prices) == ["sokcet", "work.unknown"]


def test_unknown_keys_empty_price_list() -> None:
    assert unknown_keys(PriceList()) == []


def test_price_number_becomes_price_without_name() -> None:
    prices = PriceList.model_validate({"items": {"socket": 120, "crimp": 2.5}})
    assert prices.price("socket") == Price(price=120)
    assert prices.price("crimp") == Price(price=2.5)


def test_price_object_keeps_own_name() -> None:
    prices = PriceList.model_validate({"items": {"socket": {"price": 99, "name": "Розетка X"}}})
    p = prices.price("socket")
    assert p is not None and p.price == 99 and p.name == "Розетка X"


def test_price_missing_key_is_none() -> None:
    assert PriceList().price("socket") is None


def test_price_list_defaults() -> None:
    prices = PriceList()
    assert prices.currency == "грн" and prices.items == {} and prices.board_kit == []


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
    after (filling the panel with devices, fitting devices). Materials are one section."""
    works = {k: v[0] for k, v in LINES.items() if k.startswith("work.")}
    assert {k for k, s in works.items() if s == "finish"} == {"work.board_module", "work.mechanism"}
    assert all(s == "rough" for k, s in works.items() if s != "finish")
    assert all(v[0] == "material" for k, v in LINES.items() if not k.startswith("work."))
    wiring, elec = _wiring()
    est = build_estimate(wiring, elec, PriceList(), "ru")
    by_key = {ln.key: ln.section for ln in est.lines}
    assert by_key["work.chase"] == "rough" and by_key["work.mechanism"] == "finish"


def test_empty_estimate_is_zero() -> None:
    est = Estimate((), "грн")
    assert est.subtotal("material") == 0 and est.total == 0 and est.unpriced == 0


@pytest.mark.parametrize(
    ("value", "digits", "text"),
    [
        (10, 2, "10"),
        (1234.5, 2, "1 234,50"),
        (1234567.891, 2, "1 234 567,89"),
        (0.25, 2, "0,25"),
        (0, 2, "0"),
        (1234567, 0, "1 234 567"),
        (5, 0, "5"),
        (2.75, 1, "2,8"),
        (3.0, 1, "3,0"),
    ],
)
def test_num_format(value: float, digits: int, text: str) -> None:
    assert format_number(value, digits) == text


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


def test_battery_box_in_estimate() -> None:
    """The inverter battery box is in the estimate after the panel devices: battery breaker and an
    enclosure with an article number.
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
    assert keys.index("dc_battery.125 А DC 2P") < keys.index("dc_enclosure")


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
    assert all(ln.hint is None for ln in priced.lines if ln.key != "work.mechanism")


def test_conduit_floor_always_ceiling_only_premium() -> None:
    """Conduit (docs/wiring-variants.md): on the floor always, the whole line; on the ceiling in
    premium, only the ceiling part; the diameter follows the cable cross-section."""
    from floorplan_engine.electrical.estimate import conduit_diameter, conduit_mm, quantities

    assert [conduit_diameter(m) for m in ("3x1.5", "3x2.5", "3x4", "5x10", "UTP")] == [
        16,
        20,
        25,
        32,
        20,
    ]
    wiring, elec = _wiring()
    run = wiring.runs[0]
    assert conduit_mm(run, "standard") == 0  # ceiling in standard: no conduit
    assert conduit_mm(run, "proper") == run.plan_mm  # premium: the ceiling part
    assert not any(k.startswith("conduit.") for k in quantities(wiring, elec))
    proper = quantities(wiring, elec.model_copy(update={"mode": "proper"}))
    assert any(k.startswith("conduit.") for k in proper) and proper["work.conduit"] > 0

    floor_elec = elec.model_copy(update={"route": "floor"})
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    floor = box_wiring(plan, contours, floor_elec)
    assert floor is not None and any(r.route == "floor" for r in floor.runs)
    q = quantities(floor, floor_elec)
    total = sum(v for k, v in q.items() if k.startswith("conduit."))
    # on the floor the whole line with margin; lighting runs on the ceiling (no conduit in standard)
    expected = sum(r.length_mm for r in floor.runs if r.route == "floor") / 1000 * (1 + RESERVE)
    assert total == pytest.approx(expected, abs=0.3)


PRICES_TEXT = """# прайс студии
currency: грн
items:
  # Материалы
  socket_box: 20
  board_enclosure: { price: 6000, name: "Корпус" }
  work.cable: 30                 # по потолку
  # work.mechanism — впишите цену
board_kit: []
"""


def test_edit_price_items_keeps_comments() -> None:
    out = edit_price_items(
        PRICES_TEXT,
        {"work.cable": 25.5, "board_enclosure": 6500, "socket_box": None, "work.mechanism": 90},
    )
    cable = "  work.cable: 25.5                 # по потолку"
    assert cable in out
    assert 'board_enclosure: { price: 6500, name: "Корпус" }' in out
    assert "socket_box" not in out
    assert "# прайс студии" in out and "# work.mechanism — впишите цену" in out
    # A new key goes after the last value of items, before the next section
    lines = out.splitlines()
    assert lines.index("  work.mechanism: 90") < lines.index("board_kit: []")
    assert lines.index("  work.mechanism: 90") > lines.index(
        "  work.cable: 25.5                 # по потолку"
    )


def test_edit_price_items_without_items_section() -> None:
    assert edit_price_items("currency: грн\n", {"work.chase": 100}) == (
        "currency: грн\nitems:\n  work.chase: 100\n"
    )
