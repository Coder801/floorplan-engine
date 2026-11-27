"""Electrical estimate files: Markdown and Excel (formulas, provisional totals)."""

from __future__ import annotations

from pathlib import Path

import pytest

from floorplan_engine.electrical.estimate import build_estimate
from floorplan_engine.electrical.estimate.files import write_markdown
from floorplan_engine.electrical.price_list import (
    PriceList,
)
from tests.electrical.test_estimate import _wiring


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
    from floorplan_engine.electrical.estimate.files import write_xlsx

    path = write_xlsx(est, tmp_path / "e.xlsx", "Кошторис", ["примітка"], "uk")
    assert _eval_xlsx(path) == pytest.approx(est.total)
    assert est.unpriced > 0  # items without a price are in the workbook but not in the total


def test_xlsx_totals_are_plain_and_finish_materials_are_a_list(tmp_path: Path) -> None:
    """No yellow provisional fill any more (decision 2026-11-27): every total is a plain SUM
    formula; finish materials have no price, no sum, no total — the note stands in its place."""
    from openpyxl import load_workbook

    from floorplan_engine.electrical.estimate.files import write_xlsx

    wiring, elec = _wiring()
    priced = build_estimate(
        wiring, elec, PriceList.model_validate({"items": {"work.cable": 30, "socket": 180}}), "uk"
    )
    ws = load_workbook(write_xlsx(priced, tmp_path / "p.xlsx", "Кошторис", [], "uk")).active
    assert ws is not None
    totals = [r for r in range(1, ws.max_row + 1) if ws[f"B{r}"].value in ("Разом", "Усього, грн")]
    assert len(totals) == 4  # three section totals and "Total": none for finish materials
    assert all(str(ws[f"F{r}"].value).startswith("=") for r in totals)
    assert all(ws[f"F{r}"].fill.start_color.rgb in (None, "00000000") for r in totals)
    socket = next(r for r in range(1, ws.max_row + 1) if ws[f"G{r}"].value == "socket")
    assert (
        ws[f"D{socket}"].value and ws[f"E{socket}"].value is None and ws[f"F{socket}"].value is None
    )
    notes = [ws[f"B{r}"].value for r in range(socket, ws.max_row + 1)]
    assert "Ціни — після вибору серії" in notes
    assert _eval_xlsx(tmp_path / "p.xlsx") == pytest.approx(priced.total)


def test_markdown_totals_are_plain_and_finish_materials_are_a_list(tmp_path: Path) -> None:
    wiring, elec = _wiring()
    priced = build_estimate(
        wiring, elec, PriceList.model_validate({"items": {"socket_box": 20, "socket": 180}}), "ru"
    )
    md = write_markdown(priced, tmp_path / "e.md", "Смета", [], "ru").read_text(encoding="utf-8")
    assert "## Черновые материалы\n" in md and "имитация" not in md
    totals = [ln for ln in md.splitlines() if ln.startswith("| | **Итого**")]
    assert len(totals) == 3 and not any(ln.endswith(" ! |") for ln in totals)
    assert "| | *Цены — после выбора серии* | | | | |" in md
    socket = next(ln for ln in md.splitlines() if "| Розетка с заземлением |" in ln)
    assert socket.endswith("|  |  |")  # quantity only: no price, no "no price"
    volumes = build_estimate(wiring, elec, PriceList(), "ru")
    md = write_markdown(volumes, tmp_path / "v.md", "Смета", [], "ru").read_text(encoding="utf-8")
    assert "## Черновые материалы\n" in md and " ! |" not in md
