"""Electrical estimate: quantities from the model, prices from the price list, items without a
price.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

import floorplan_engine.electrical.estimate as estimate_module
from floorplan_engine.drawing.tables import Guess
from floorplan_engine.electrical.estimate import (
    CHASE_KEYS,
    HINTS,
    LINES,
    SECTIONS,
    Estimate,
    Line,
    Price,
    PriceList,
    Section,
    build_estimate,
    cable_title,
    derived_quote,
    edit_price_items,
    format_number,
    parse_number,
    quantities,
    split_key,
    unknown_keys,
)
from floorplan_engine.electrical.led_supply import (
    LED_V,
    STRIP_DEFAULT_M,
    STRIP_W_PER_M,
    led_mark,
    section_for,
)
from floorplan_engine.electrical.low_links import LED_MARK
from floorplan_engine.electrical.panel import build_panel, busbars, device_name
from floorplan_engine.electrical.pricing import MockPriceService, Prices, mock_price
from floorplan_engine.electrical.splices import Splice, back_box_joints
from floorplan_engine.electrical.wiring import RESERVE, box_wiring
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.pipeline import build_project, estimate_project
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
    assert "work.marking" not in q  # end marking is part of work.cable
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
    md, csv_path, xlsx, scope = result.files
    assert scope.name == "work-scope.md" and "work-scope.md" in md.read_text("utf-8")
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
    holes = q.get("work.wall_hole", 0) + q.get("work.wall_hole_large", 0)
    assert holes == len(wiring.holes)


def test_large_hole_costs_two_and_a_half_times() -> None:
    """A large hole (core drill) is priced from an ordinary one × 2.5, unless the price
    list names it itself; the price service mock follows the same rule."""
    own = PriceList.model_validate({"items": {"work.wall_hole": 200}})
    quote = derived_quote(Prices(own, MockPriceService()), "work.wall_hole_large")
    assert quote.price is not None and quote.price.price == 500 and not quote.service
    named = PriceList.model_validate({"items": {"work.wall_hole_large": 260}})
    quote = derived_quote(Prices(named, MockPriceService()), "work.wall_hole_large")
    assert quote.price is not None and quote.price.price == 260
    assert mock_price("work.wall_hole_large") == 2.5 * (mock_price("work.wall_hole") or 0)


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
    monkeypatch.setattr(estimate_module, "MATERIAL_PRICES_MOCK", False)
    assert not any(isinstance(c, Guess) for c in _subtotals(estimate_table(est, "uk", True)))


def test_section_titles_are_plain_and_markdown_marks_material_totals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from floorplan_engine.electrical.estimate import provisional, section_title, write_markdown

    assert section_title("material", "ru") == "Материалы"
    assert section_title("material_finish", "ru") == "Чистовые материалы"
    assert section_title("material_rough", "uk") == "Чорнові матеріали"
    assert section_title("rough", "ru") == "Черновые работы"
    assert provisional("material", True) and provisional("material_finish", True)
    assert not provisional("material", False) and not provisional("rough", True)
    wiring, elec = _wiring()
    priced = build_estimate(
        wiring, elec, PriceList.model_validate({"items": {"socket_box": 20}}), "ru"
    )
    md = write_markdown(priced, tmp_path / "e.md", "Смета", [], "ru").read_text(encoding="utf-8")
    assert "## Черновые материалы\n" in md and "имитация" not in md
    totals = [ln for ln in md.splitlines() if ln.startswith("| | **Итого**")]
    assert [ln.endswith("** ! |") for ln in totals] == [True, True, False, False]
    assert not any(ln.startswith("**Всего") and "!" in ln for ln in md.splitlines())
    volumes = build_estimate(wiring, elec, PriceList(), "ru")
    md = write_markdown(volumes, tmp_path / "v.md", "Смета", [], "ru").read_text(encoding="utf-8")
    assert "## Черновые материалы\n" in md and " ! |" not in md
    monkeypatch.setattr(estimate_module, "MATERIAL_PRICES_MOCK", False)
    md = write_markdown(priced, tmp_path / "o.md", "Смета", [], "ru").read_text(encoding="utf-8")
    assert " ! |" not in md


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


def test_xlsx_material_totals_are_yellow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A provisional materials total keeps its SUM formula and gets the yellow fill; work totals
    and "Total" do not (decision 2026-11-23)."""
    from openpyxl import load_workbook

    from floorplan_engine.electrical.estimate import XLSX_GUESS_FILL, write_xlsx

    def fills(est: Estimate, name: str) -> list[bool]:
        ws = load_workbook(write_xlsx(est, tmp_path / name, "Кошторис", [], "uk")).active
        assert ws is not None
        rows = [
            r for r in range(1, ws.max_row + 1) if ws[f"B{r}"].value in ("Разом", "Усього, грн")
        ]
        assert all(str(ws[f"F{r}"].value).startswith("=") for r in rows)  # still formulas
        return [str(ws[f"F{r}"].fill.start_color.rgb).endswith(XLSX_GUESS_FILL) for r in rows]

    wiring, elec = _wiring()
    priced = build_estimate(
        wiring, elec, PriceList.model_validate({"items": {"work.cable": 30}}), "uk"
    )
    assert fills(priced, "p.xlsx") == [True, True, False, False, False]
    assert not any(fills(build_estimate(wiring, elec, PriceList(), "uk"), "v.xlsx"))
    monkeypatch.setattr(estimate_module, "MATERIAL_PRICES_MOCK", False)
    assert not any(fills(priced, "o.xlsx"))


def test_studio_prices_used_when_project_has_none(tmp_path: Path) -> None:
    from floorplan_engine.pipeline import find_prices

    project = tmp_path / "kv"
    project.mkdir()
    assert find_prices(project) is None
    (tmp_path / "prices.yaml").write_text("items: {}\n", "utf-8")
    assert find_prices(project) == tmp_path / "prices.yaml"
    (project / "prices.yaml").write_text("items: {}\n", "utf-8")
    assert find_prices(project) == project / "prices.yaml"  # the top layer names the notes


def test_project_prices_change_only_their_keys(tmp_path: Path) -> None:
    """Decision 2026-11-25: the studio list is the base, the project's own list wins only for the
    keys it names; terms merge the same way; a broken layer stops the estimate prices."""
    from floorplan_engine.pipeline import load_price_layers

    project = tmp_path / "kv"
    project.mkdir()
    assert load_price_layers(project) == (None, [])
    (tmp_path / "prices.yaml").write_text(
        'date: "2026-11"\nitems:\n  work.cable: 45\n  work.mechanism: 125\n  socket_box: 20\n',
        "utf-8",
    )
    studio, issues = load_price_layers(project)
    assert issues == [] and studio is not None and studio.items["work.cable"] == 45
    (project / "prices.yaml").write_text("items:\n  work.mechanism: 100\n", "utf-8")
    merged, issues = load_price_layers(project)
    assert issues == [] and merged is not None
    assert merged.items == {"work.cable": 45, "work.mechanism": 100, "socket_box": 20}
    assert merged.date == "2026-11"  # the project list does not set it: the studio's stays
    (project / "prices.yaml").write_text("items:\n  no.such.item: 1\n", "utf-8")
    broken, issues = load_price_layers(project)
    assert broken is None and issues and issues[0].path == "items.no.such.item"


def test_studio_splice_setting_reaches_every_project(tmp_path: Path) -> None:
    """splice is set once in the studio list (decision 2026-11-25); a project list without it keeps
    the studio's, one that sets it wins, like terms."""
    from floorplan_engine.pipeline import load_price_layers

    project = tmp_path / "kv"
    project.mkdir()
    (tmp_path / "prices.yaml").write_text("splice: crimp\nitems:\n  socket_box: 20\n", "utf-8")
    (project / "prices.yaml").write_text("items:\n  socket_box: 25\n", "utf-8")
    merged, issues = load_price_layers(project)
    assert issues == [] and merged is not None and merged.splice == "crimp"
    (project / "prices.yaml").write_text("splice: wago\n", "utf-8")
    merged, _ = load_price_layers(project)
    assert merged is not None and merged.splice == "wago"
    (tmp_path / "prices.yaml").write_text("splice: solder\n", "utf-8")
    broken, issues = load_price_layers(project)
    assert broken is None and issues and issues[0].path == "splice"


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


def test_unknown_keys_skips_retired_items() -> None:
    # an old price list with end marking, now part of work.cable, still loads
    prices = PriceList.model_validate({"items": {"work.marking": 10, "work.cable": 34}})
    assert unknown_keys(prices) == []


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
        "wago",
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
    assert parse_number(text) == round(value, digits)


@pytest.mark.parametrize("text", ["—", "", "нет цены"])
def test_parse_number_no_price(text: str) -> None:
    assert parse_number(text) is None


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


def test_rough_light_per_room_with_lights() -> None:
    wiring, elec = _wiring()
    keys = ("rough_holder", "rough_lamp", "rough_switch", "work.rough_light", "work.rough_switch")
    assert not set(keys) & set(quantities(wiring, elec))
    q = quantities(wiring, elec.model_copy(update={"rough_light": True}))
    assert [q[k] for k in keys] == [1] * 5  # one room


def test_rough_light_without_lights_is_not_in_the_estimate() -> None:
    wiring, elec = _wiring()
    sockets = [p for p in elec.points if p.type.value == "socket"]
    q = quantities(wiring, elec.model_copy(update={"rough_light": True, "points": sockets}))
    assert "rough_holder" not in q and "work.rough_switch" not in q


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


def _led_wiring(supply: str) -> tuple[Any, Electrical]:
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    points = [*ELEC["points"], LED]
    elec = Electrical.model_validate({**ELEC, "points": points, "led_supply": supply})
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    return wiring, elec


def test_led_supply_at_the_strip_is_fed_from_the_room_box() -> None:
    wiring, elec = _led_wiring("room")
    run = next(r for r in wiring.runs if r.target == "led1")
    assert run.source != "board" and run.mark == "3x1.5"
    q = quantities(wiring, elec)
    assert q["led_psu"] == q["work.led_psu"] == 1
    assert "led_psu_din" not in q and "work.led_psu_din" not in q


def test_led_supply_in_the_panel_gives_a_12v_line_of_its_own() -> None:
    wiring, elec = _led_wiring("board")
    run = next(r for r in wiring.runs if r.target == "led1")
    assert (run.source, run.circuit, run.group, run.led) == ("board", "low", "QF1", True)
    # The 12 V line goes by the voltage drop: the default 5 m strip draws 6 A
    current = STRIP_DEFAULT_M * STRIP_W_PER_M / LED_V
    assert run.mark == led_mark(section_for(run.length_mm, current)) != LED_MARK
    q = quantities(wiring, elec)
    assert q["led_psu_din"] == q["work.led_psu_din"] == 1 and "led_psu" not in q
    assert q[f"cable.{run.mark}"] > 0
    assert q["work.board_install"] == 2  # the LED supplies box is a second panel
    assert q["work.insulation_test"] == 2  # the 12 V line is no power group of its own
    assert mock_price("led_psu_din") and mock_price("work.led_psu_din")


def test_no_led_outputs_no_supplies() -> None:
    wiring, elec = _wiring()
    q = quantities(wiring, elec.model_copy(update={"led_supply": "board"}))
    assert not {"led_psu", "led_psu_din", "work.led_psu", "work.led_psu_din"} & set(q)


def test_before_plaster_leaves_no_chase_work() -> None:
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    elec = Electrical.model_validate({**ELEC, "plaster": "before"})
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    q = quantities(wiring, elec)
    assert "work.chase" not in q and "work.chase_wide" not in q and q["work.cable"] > 0


def test_conduit_floor_always_ceiling_only_premium() -> None:
    """Conduit (docs/wiring-variants.md): on the floor always, the whole line; on the ceiling in
    premium, only the ceiling part; the diameter follows the cable cross-section."""
    from floorplan_engine.electrical.estimate import conduit_mm
    from floorplan_engine.electrical.mounting import conduit_diameter

    assert [conduit_diameter(m) for m in ("3x1.5", "3x2.5", "3x4", "5x10", "UTP")] == [
        20,
        20,
        25,
        32,
        20,
    ]
    wiring, elec = _wiring()
    run = wiring.runs[0]
    assert conduit_mm(run, "none") == 0  # ceiling: no conduit unless chosen
    assert conduit_mm(run, "ceiling") == run.plan_mm  # the ceiling part
    assert conduit_mm(run, "walls") == run.length_mm  # and the drops in the walls
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
    # on the floor the whole line with margin; lighting runs on the ceiling (no conduit in
    # standard). Lines lying together share a conduit (2026-11-13): their stretch counts once
    from floorplan_engine.electrical.mounting import plan_conduits, source_conduits

    on_floor = [r for r in floor.runs if r.route == "floor"]
    shared = [*plan_conduits(floor, "none"), *source_conduits(floor, "none")]
    saved = sum(p.length * (len(p.runs) - 1) for p in shared)
    assert saved > 0
    expected = (sum(r.length_mm for r in on_floor) - saved) / 1000 * (1 + RESERVE)
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


@pytest.mark.parametrize(
    ("mark", "title"),
    [
        ("3x6", "ВВГнг 3×6"),
        ("3x2.5", "ВВГнг 3×2,5"),
        ("5х2,5", "ВВГнг 5×2,5"),
        ("ВВГнг-LS 3x2.5", "ВВГнг-LS 3x2.5"),
        ("UTP cat.6", "UTP cat.6"),
        ("RG-6", "RG-6"),
    ],
)
def test_cable_title_adds_the_brand_to_a_bare_section(mark: str, title: str) -> None:
    assert cable_title(mark) == title


def test_split_key_with_work_parameter() -> None:
    assert split_key("work.chase.brick") == ("work.chase", "brick")
    assert split_key("work.chase_wide.concrete") == ("work.chase_wide", "concrete")
    assert split_key("work.chase") == ("work.chase", "")
    assert split_key("work.cable") == ("work.cable", "")
    assert split_key("cable.3x1.5") == ("cable", "3x1.5")


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


def test_wide_chase_priced_from_narrow_in_the_same_material() -> None:
    own = PriceList.model_validate({"items": {"work.chase.brick": 100}})
    quote = derived_quote(Prices(own, MockPriceService()), "work.chase_wide.brick")
    assert quote.price is not None and quote.price.price == 150 and not quote.service
    named = PriceList.model_validate({"items": {"work.chase_wide.brick": 170}})
    quote = derived_quote(Prices(named, MockPriceService()), "work.chase_wide.brick")
    assert quote.price is not None and quote.price.price == 170


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


def test_floor_heating_zone_without_a_layout_buys_no_cable() -> None:
    """A zone with an empty heated area has no route: no section, no sensor, no work — the
    report already says why (a remark on the zone)."""
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    reg = _pt("t1", "thermostat", 2000, 1500, "QF5")
    whole = {"at": [0, 0], "size": [6000, 6000]}
    fh = [{"id": "fh1", "room": "r", "thermostat": "t1", "length": 20, "exclude": [whole]}]
    elec = Electrical.model_validate(
        {**ELEC, "points": [*ELEC["points"], reg], "floor_heating": fh}
    )
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None
    (zone,) = wiring.heating
    assert zone.route is None and zone.length == 20
    q = quantities(wiring, elec)
    assert not [k for k in q if "heating" in k]


def test_floor_heating_is_not_in_the_estimate_until_its_release() -> None:
    """Floor heating is held back (floor_heating.RELEASED, decision 2026-11-22): a zone is laid,
    but the estimate buys no section, sensor, conduit or laying work."""
    plan = make_plan(RECT, [DOOR])
    _, contours = validate_plan(plan)
    reg = _pt("t1", "thermostat", 2000, 1500, "QF5")
    fh = [{"id": "fh1", "room": "r", "thermostat": "t1"}]
    elec = Electrical.model_validate(
        {**ELEC, "points": [*ELEC["points"], reg], "floor_heating": fh}
    )
    wiring = box_wiring(plan, contours, elec)
    assert wiring is not None and wiring.heating
    q = quantities(wiring, elec)
    assert not [k for k in q if "heating" in k]


def test_boxes_keep_crimps_and_no_wago() -> None:
    """Through junction boxes nothing changes: crimps as before, no clamps, no splice work."""
    wiring, elec = _wiring()
    q = quantities(wiring, elec)
    assert q["crimp"] == 3 * len(wiring.boxes) + 2
    assert back_box_joints(wiring, elec) == {}
    assert not any(k.startswith("wago") for k in q) and "work.splice" not in q


def _two_switches() -> list[dict[str, Any]]:
    """Light in a chain where one switch feeds the other: panel → k2 → k1 → l1 (test_splices)."""
    return [
        {"id": "l1", "room": "r", "type": "downlight", "ceiling": [1500, 2000], "group": "QF1"},
        _pt("k1", "switch", 500, 900, "QF1"),
        _pt("k2", "switch", 2500, 900, "QF1"),
    ]


def test_wago_lines_without_price_with_note(tmp_path: Path) -> None:
    """Clamps and their work are rough items with no price anywhere (pricing.UNPRICED): in the
    estimate "no price", with the hint; the note says sockets of a loop have no joints and why
    switches have them."""
    wiring, elec = room_wiring(_two_switches(), light_wiring="chain")
    est = build_estimate(wiring, elec, Prices(None, MockPriceService()), "uk")
    by_key = {ln.key: ln for ln in est.lines}
    clamp, work = by_key["wago.413"], by_key["work.splice"]
    assert (clamp.section, clamp.price, clamp.name, clamp.qty) == (
        "material_rough",
        None,
        "Клема важільна Wago 221-413",
        1,
    )
    assert by_key["wago.412"].qty == 4 and (work.section, work.price, work.qty) == (
        "rough",
        None,
        2,
    )
    assert "221-413 — на 3" in (clamp.hint or "") and "уточнюється" in (clamp.hint or "")
    note = estimate_module.text("note_splice", "ru")
    assert "без соединений" in note and "перемычки" in note and "60 мм" in note
    assert "1.7.144" not in note
    assert "опресування" in estimate_module.text("note_splice", "uk")


def test_crimp_splice_in_flush_boxes_counts_sleeves_and_its_own_work() -> None:
    """splice crimp, a studio setting in its price list (decision 2026-11-25): the same joints as
    with clamps, a sleeve with heat shrink per joint in the crimp item, the work —
    work.splice_crimp; no clamps and no work.splice."""
    wiring, elec = room_wiring(_two_switches(), light_wiring="chain")
    joints = back_box_joints(wiring, elec)
    assert sorted(len(fb.joints) for fb in joints.values()) == [2, 3]  # k1: N, PE; k2: L, N, PE
    q = quantities(wiring, elec, "crimp")
    assert q["crimp"] == 5 and q["work.splice_crimp"] == 2
    assert "work.splice" not in q and not any(k.startswith("wago") for k in q)
    wago_q = quantities(wiring, elec, "wago")
    assert "crimp" not in wago_q and wago_q["work.splice"] == 2
    own = PriceList.model_validate({"splice": "crimp"})
    est = build_estimate(wiring, elec, Prices(own, MockPriceService()), "ru")
    by_key = {ln.key: ln for ln in est.lines}
    work = by_key["work.splice_crimp"]
    assert (work.section, work.price, work.name) == (
        "rough",
        None,
        "Соединение в подрозетнике опрессовкой",
    )
    assert by_key["crimp"].qty == 5 and "work.splice" not in by_key
    note = estimate_module.text("note_splice_crimp", "uk")
    assert "60 мм" in note and "без пружин" in note and "перемички" in note


def test_socket_loop_buys_no_clamps_and_no_splice_work() -> None:
    """Sockets in a loop (decision 2026-11-25): double terminals and jumpers, no joints — no
    clamps, no sleeves, no splice work, whatever the studio's setting."""
    sockets = [_pt(f"s{k}", "socket", 600 + 1000 * k, 300, "QF2", count=2) for k in range(3)]
    wiring, elec = room_wiring(sockets, distribution="loop")
    assert not wiring.boxes and back_box_joints(wiring, elec) == {}
    splices: tuple[Splice, ...] = ("wago", "crimp")
    for splice in splices:
        q = quantities(wiring, elec, splice)
        assert not {"crimp", "work.splice", "work.splice_crimp"} & set(q)
        assert not any(k.startswith("wago") for k in q)


def test_splice_defaults_to_wago_without_a_studio_setting() -> None:
    """No splice in the price list, no list at all, or the price service alone — wago."""
    wiring, elec = room_wiring(_two_switches(), light_wiring="chain")
    assert PriceList().splice is None and MockPriceService().splice is None
    for prices in (PriceList(), Prices(), Prices(PriceList(), MockPriceService())):
        keys = {ln.key for ln in build_estimate(wiring, elec, prices, "ru").lines}
        assert "work.splice" in keys and "wago.413" in keys and "work.splice_crimp" not in keys
    crimp = Prices(PriceList.model_validate({"splice": "crimp"}), MockPriceService())
    assert crimp.splice == "crimp" and PriceList.model_validate({"splice": "wago"}).splice == "wago"
    with pytest.raises(ValueError):
        PriceList.model_validate({"splice": "solder"})


def test_crimp_splice_adds_to_box_crimps() -> None:
    """Light in a chain with sockets through boxes: box crimps as before, plus a sleeve per
    flush box joint."""
    points = [
        {"id": "l1", "room": "r", "type": "downlight", "ceiling": [1000, 1500], "group": "QF1"},
        {"id": "l2", "room": "r", "type": "downlight", "ceiling": [2000, 1500], "group": "QF1"},
        _pt("k1", "switch", 2500, 900, "QF1"),
        _pt("s1", "socket", 500, 300, "QF2"),
        _pt("s2", "socket", 1500, 300, "QF2"),
    ]
    wiring, elec = room_wiring(points, light_wiring="chain")
    assert wiring.boxes
    q = quantities(wiring, elec, "crimp")
    assert q["crimp"] == 3 * len(wiring.boxes) + 2  # N and PE at the switch
    assert q["work.junction_box"] == len(wiring.boxes) and q["work.splice_crimp"] == 1
