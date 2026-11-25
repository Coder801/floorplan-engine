"""Electrical estimate files: Markdown and Excel (formulas, provisional totals)."""

from __future__ import annotations

from pathlib import Path

import pytest

import floorplan_engine.electrical.estimate_texts as estimate_texts
from floorplan_engine.electrical.estimate import Estimate, build_estimate
from floorplan_engine.electrical.estimate_files import write_markdown
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
    from floorplan_engine.electrical.estimate_files import write_xlsx

    path = write_xlsx(est, tmp_path / "e.xlsx", "Кошторис", ["примітка"], "uk")
    assert _eval_xlsx(path) == pytest.approx(est.total)
    assert est.unpriced > 0  # items without a price are in the workbook but not in the total


def test_xlsx_material_totals_are_yellow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A provisional materials total keeps its SUM formula and gets the yellow fill; work totals
    and "Total" do not (decision 2026-11-23)."""
    from openpyxl import load_workbook

    from floorplan_engine.electrical.estimate_files import XLSX_GUESS_FILL, write_xlsx

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
    monkeypatch.setattr(estimate_texts, "MATERIAL_PRICES_MOCK", False)
    assert not any(fills(priced, "o.xlsx"))


def test_markdown_marks_material_totals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(estimate_texts, "MATERIAL_PRICES_MOCK", False)
    md = write_markdown(priced, tmp_path / "o.md", "Смета", [], "ru").read_text(encoding="utf-8")
    assert " ! |" not in md
