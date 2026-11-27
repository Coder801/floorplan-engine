"""Electrical estimate: quantities come from the model (code), prices from the project price
list (prices.yaml).

There is no drawing, only a table: one item per quantity (Line), sections with their own totals
(Estimate). The modules of the estimate package:

- items.py — the item catalogue: section, unit and name of each key (LINES), notes
  (HINTS), keys with a parameter (split_key), the order of the sections;
- quantities.py — the quantities from the model (quantities): what is counted and how;
- electrical/price_list.py, beside the package — prices.yaml (PriceList), the price source
  protocol (PriceSource), prices derived from another item;
- texts.py — headings, notes and table strings, the provisional mark, number format;
- files.py — out/estimate.md, out/estimate.csv and out/estimate.xlsx.

Here build_estimate puts the items together and prices them. The panel follows the "Panel" sheet:

- panel: enclosure and devices from the "Panel" sheet (panel.build_panel: kind and rating, as
  in the purchase device table), assembly by the modules of that set; no panel means one
  breaker per group; device prices by kind (breaker, diff, rcd, input…), with the rating as a
  key refinement (breaker.C16);
- comb busbars over the group rails instead of wire jumpers (panel.busbars): 1 m bars by
  poles (busbar.1P), only with a panel set;
- the boxes of the battery and of the LED supplies: their enclosures after the panel devices,
  the LED supplies by power as devices of their box;
- panel labels (Electrical.panel_labels): one item at a fixed price per panel, right after the
  assembly.

Prices come only from the studio price list (with the project's on top); they are never
invented: items with no price in the list stay in the estimate marked "no price" and are left out
of the total. Finish materials are a bill of quantities (items.LISTED_SECTIONS, decision
2026-11-27): wiring devices, lights and panel devices depend on the series the client picks, so
their rows carry no price at all, are not "no price" and the section has no total. LED profiles
are not described in the model and are not in the estimate.
"""

from __future__ import annotations

from dataclasses import dataclass

from floorplan_engine.electrical.boxes import BOX_TITLES
from floorplan_engine.electrical.estimate.items import (
    CHASE_KEYS,
    FIXTURES,
    HINTS,
    LINES,
    LISTED_SECTIONS,
    MATERIAL_SECTIONS,
    SECTIONS,
    WALL_MATERIALS,
    Section,
    cable_title,
    split_key,
)
from floorplan_engine.electrical.estimate.quantities import quantities as count_quantities
from floorplan_engine.electrical.panel import BoardPanel, busbars, device_name
from floorplan_engine.electrical.price_list import PriceSource, Quote, derived_quote
from floorplan_engine.electrical.splices import DEFAULT_SPLICE
from floorplan_engine.electrical.wiring_model import Wiring
from floorplan_engine.model.panel_catalog import Enclosure
from floorplan_engine.model.schema import Electrical, WallMaterial
from floorplan_engine.model.texts import Language, tr

# Notes added to an item's hint: no price yet, a price from the price service, a chase
# without a known wall material
PRICE_TBD = {"ru": "Цена уточняется", "uk": "Ціна уточнюється"}
PRICE_SERVICE = {"ru": "Цена — из сервиса цен", "uk": "Ціна — із сервісу цін"}
NO_MATERIAL = {
    "ru": "Материал стены не указан в плане: цена — по кирпичу, уточняется",
    "uk": "Матеріал стіни не вказано в плані: ціна — за цеглою, уточнюється",
}


@dataclass(frozen=True)
class Line:
    section: Section
    key: str
    name: str
    unit: str
    qty: float
    price: float | None  # None: not in the price list, or a listed section (no price at all)
    hint: str | None = None  # item note (HINTS)
    service: bool = False  # price from an external price service, not from the list

    @property
    def total(self) -> float | None:
        return None if self.price is None else self.qty * self.price

    @property
    def listed(self) -> bool:
        """A finish material: quantity only, no price by design (LISTED_SECTIONS)."""
        return self.section in LISTED_SECTIONS


@dataclass(frozen=True)
class Estimate:
    lines: tuple[Line, ...]
    currency: str

    def subtotal(self, section: Section) -> float:
        return sum(ln.total or 0.0 for ln in self.lines if ln.section == section)

    @property
    def materials(self) -> float:
        """All materials: rough and finish (and the ones of an estimate that is not split)."""
        return sum(self.subtotal(s) for s in MATERIAL_SECTIONS)

    @property
    def work(self) -> float:
        """All work: rough and finishing."""
        return self.subtotal("rough") + self.subtotal("finish")

    @property
    def total(self) -> float:
        return sum(self.subtotal(s) for s in SECTIONS)

    @property
    def unpriced(self) -> int:
        """Items the price list has no price for; listed (finish) materials are not counted:
        they have no price by design."""
        return sum(1 for ln in self.lines if ln.price is None and not ln.listed)

    @property
    def listed(self) -> int:
        """Finish material items: a bill of quantities, priced after the client picks a series."""
        return sum(1 for ln in self.lines if ln.listed)

    @property
    def has_prices(self) -> bool:
        """At least one item has a price: an estimate, not a bill of quantities."""
        return any(ln.price is not None for ln in self.lines)

    @property
    def from_service(self) -> int:
        return sum(1 for ln in self.lines if ln.service)


def enclosure_name(key: str, enclosure: Enclosure, language: Language) -> str:
    """Name of an enclosure row: the item name with the chosen model and its width
    ("Корпус щита Hager Golf VS112PD, 12 мод.")."""
    base = LINES[key][2 if language == "ru" else 3]
    return f"{base} {enclosure.title}, {enclosure.modules} мод."


def build_estimate(
    wiring: Wiring,
    elec: Electrical,
    prices: PriceSource,
    language: Language = "ru",
    panel: BoardPanel | None = None,
) -> Estimate:
    """Estimate: one item per quantity. The panel follows the "Panel" sheet set (panel): a row per
    device kind and rating, assembly by the modules of the set; no panel means one breaker per
    group. prices is a price list or the list merged with the price service (pricing.Prices);
    its splice says how the flush box joints are made."""
    q = count_quantities(wiring, elec, prices.splice or DEFAULT_SPLICE)
    if panel is not None:
        q.pop("breaker", None)
    if panel is not None and panel.led is not None:  # supplies by power, as LED box devices
        q.pop("led_psu_din", None)
    if "work.board_install" in q:  # assembly right after the panel installation
        modules = panel.modules if panel is not None else q.get("breaker", 0.0)
        items = list(q.items())
        at = next(k for k, (key, _) in enumerate(items) if key == "work.board_install") + 1
        items.insert(at, ("work.board_module", modules))
        if elec.panel_labels and panel is not None:  # fixed price per panel (stickers.py)
            items.insert(at + 1, ("work.panel_labels", 1))
        q = dict(items)

    def line(key: str, qty: float, name: str | None = None) -> Line:
        base, param = split_key(key)
        section, unit, ru, uk = LINES[base]
        listed = section in LISTED_SECTIONS
        quote = Quote(None, None, False) if listed else derived_quote(prices, key)
        p, exact = quote.price, quote.exact
        if exact and exact.name:
            name = exact.name
        elif p and p.name and name is None:
            name = p.name
        elif name is None and base in FIXTURES:
            name = tr(FIXTURES[base], language)
        elif name is None:
            mark = cable_title(param) if base == "cable" else BOX_TITLES.get(param, param)
            name = (ru if language == "ru" else uk).format(mark=mark, n=param)
            if base in CHASE_KEYS and param:
                name = f"{name}, {WALL_MATERIALS[WallMaterial(param)][language]}"
        hint = HINTS.get(base, {}).get(language)
        if base in CHASE_KEYS and not param:
            hint = NO_MATERIAL[language]
        if hint and p is None and not listed:
            hint = f"{hint}. {PRICE_TBD[language]}"
        if quote.service and p is not None:
            hint = f"{hint}. {PRICE_SERVICE[language]}" if hint else PRICE_SERVICE[language]
        return Line(section, key, name, unit, qty, p.price if p else None, hint, quote.service)

    names: dict[str, str] = {}
    if panel is not None and panel.enclosure is not None:  # enclosure from the Panel sheet
        names["board_enclosure"] = enclosure_name("board_enclosure", panel.enclosure, language)
    lines = [line(k, v, names.get(k)) for k, v in q.items()]
    if panel is not None:
        # Panel devices by kind and rating, in panel order; next to the enclosure
        counts: dict[tuple[str, str], tuple[str, int]] = {}
        for d in panel.all_devices:
            key = f"{d.kind.value}.{d.label}"
            name, n = counts.get((key, d.label), (device_name(d, language), 0))
            counts[(key, d.label)] = (name, n + 1)
        devices = [line(key, n, name) for (key, _), (name, n) in counts.items()]
        # Comb busbars of the group rails, right after the devices they join
        devices += [line(f"busbar.{poles}P", n) for poles, n in busbars(panel).items()]
        if panel.dc is not None:  # battery box enclosure after the devices
            name = enclosure_name("dc_enclosure", panel.dc.enclosure, language)
            devices.append(line("dc_enclosure", 1, name))
        if panel.led is not None:  # LED supplies box enclosure after the devices
            name = enclosure_name("led_enclosure", panel.led.enclosure, language)
            devices.append(line("led_enclosure", 1, name))
        at = next((k + 1 for k, ln in enumerate(lines) if ln.key == "board_enclosure"), len(lines))
        lines[at:at] = devices
    lines.sort(key=lambda ln: SECTIONS.index(ln.section))
    return Estimate(tuple(lines), prices.currency)
