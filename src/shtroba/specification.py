"""Спецификация изделий электрики — количество по модели, без марок и артикулов.

Механизмы и светильники — по точкам (`count` — постов в блоке), подрозетники — по постам
настенных механизмов, рамки — по числу постов в блоке, LED-лента — в метрах.
Кабель, гофра и крепления сюда пока не входят: их длины зависят от способа разводки.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from shtroba.schema import Electrical, ElectricalPoint, PointType
from shtroba.tables import Column, Table, name_width
from shtroba.texts import Language, tr

# Механизмы в подрозетнике: на каждый пост — подрозетник, на блок — рамка
MOUNTED = frozenset(
    {PointType.SOCKET, PointType.SWITCH, PointType.PASS_SWITCH, PointType.DATA, PointType.TV}
)


@dataclass(frozen=True)
class SpecItem:
    name: str
    unit: str  # pcs | m
    quantity: float


def _mechanism_key(p: ElectricalPoint) -> str:
    if p.type is PointType.SWITCH:
        return "spec_switch2" if p.keys == 2 else "spec_switch1"
    return f"symbol_{p.type.value}"


def specification(elec: Electrical, language: Language = "ru") -> list[SpecItem]:
    """Позиции в порядке: механизмы, подрозетники, рамки, светильники, LED, щит."""
    items: list[SpecItem] = []
    pieces: Counter[str] = Counter()
    for p in elec.points:
        pieces[_mechanism_key(p)] += p.count
    order = [
        "symbol_socket",
        "spec_switch1",
        "spec_switch2",
        "symbol_pass_switch",
        "symbol_data",
        "symbol_tv",
    ]
    items += [SpecItem(tr(k, language), "pcs", pieces[k]) for k in order if pieces[k]]

    mounted = [p for p in elec.points if p.type in MOUNTED]
    boxes = sum(p.count for p in mounted)
    if boxes:
        items.append(SpecItem(tr("spec_box", language), "pcs", boxes))
    frames = Counter(p.count for p in mounted)
    items += [SpecItem(tr("spec_frame", language, n=n), "pcs", frames[n]) for n in sorted(frames)]

    lights = ["symbol_light", "symbol_downlight", "symbol_pendant", "symbol_sconce"]
    items += [SpecItem(tr(k, language), "pcs", pieces[k]) for k in lights if pieces[k]]
    for key in ("symbol_led_output", "symbol_outlet"):
        if pieces[key]:
            items.append(SpecItem(tr(key, language), "pcs", pieces[key]))
    led_m = sum(s.end - s.start for s in elec.led_strips) / 1000
    if led_m:
        items.append(SpecItem(tr("legend_led_strip", language), "m", round(led_m, 2)))
    if elec.board is not None:
        items.append(SpecItem(tr("symbol_board", language), "pcs", 1))
    return items


def _quantity(item: SpecItem) -> str:
    return f"{item.quantity:g}".replace(".", ",")


def specification_table(elec: Electrical, language: Language) -> Table | None:
    """Таблица на лист электрики; None — изделий нет."""
    items = specification(elec, language)
    if not items:
        return None
    columns = (
        Column(tr("schedule_no", language), 12.0),
        Column(tr("spec_name", language), name_width([i.name for i in items]), "left"),
        Column(tr("spec_unit", language), 14.0),
        Column(tr("spec_qty", language), 16.0),
    )
    rows = tuple(
        (str(k), i.name, tr(f"unit_{i.unit}", language), _quantity(i))
        for k, i in enumerate(items, 1)
    )
    return Table(tr("spec_title", language), columns, rows)
