"""Panel stickers: what each device of the panel gets on its sticker, rail by rail.

One sticker per device: the number (QF12, QS1), a short name from the group purpose or the
device title and an icon. Name and icon come only from the model: purpose words and device kind.
Layout, fonts and the PDF are in sheets/stickers.py. A word list misses an appliance: the
sticker gets the icon of the group kind.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from floorplan_engine.electrical.loads import Kind, PanelGroup
from floorplan_engine.electrical.panel import BoardPanel, Device
from floorplan_engine.model.panel_catalog import DeviceKind


@dataclass(frozen=True)
class Sticker:
    """One sticker: `lines` are the name blocks (what, where), each wraps on its own."""

    id: str  # QF12
    row: int  # rail, top to bottom; the battery box follows the panel
    lines: tuple[str, ...]  # short name
    icon: str  # key in sheets/stickers_assets/icons.json
    title: str  # full purpose, as in the "Groups" table
    group: str | None = None  # panel group: its colour on colour stickers

    @property
    def short_id(self) -> str:
        """The line number alone, for the owner of the flat: QF12 → 12, QF8.2 → 8.2. A device
        that is no line of its own (QS1, KV1) keeps its designation: it has no number to show."""
        return (re.sub(r"^[^\W\d]+", "", self.id) or self.id) if self.group else self.id


# Words of the purpose, ru and uk stems, first match wins: appliances before generic kinds, so
# "Розетка: бойлер" gets the boiler
GROUP_ICONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("fridge", ("холодильн",)),
    ("microwave", ("микроволн", "мікрохвил", "свч", "нвч")),
    ("wash-tumble-dry", ("сушильн",)),
    ("wash-machine", ("стиральн", "пральн")),
    ("cooker", ("духов", "плит", "варильн", "варочн")),
    ("tools-kitchen-2", ("посудом", "кухн")),
    ("wind", ("вытяжк", "витяжк", "вентил")),
    ("air-conditioning", ("кондиц", "кондиці")),
    ("droplet-bolt", ("бойлер", "водонагр")),
    ("flame", ("котел", "котёл", "котл")),
    ("temperature", ("тёпл", "тепл", "сушка", "сушарк", "рушникосуш", "полотенцесуш", "конвектор")),
    ("router", ("интернет", "інтернет", "роутер", "слаботоч", "слабкий струм")),
    ("device-tv", ("телев",)),
    ("toggle-left", ("выключат", "вимикач")),
    ("bulb", ("освещ", "освітл", "подсвет", "підсвіт")),
    ("plug", ("розетк",)),
)
KIND_ICONS = {Kind.LIGHT: "bulb", Kind.SOCKETS: "plug", Kind.HEAVY: "bolt"}
DEVICE_ICONS = {
    DeviceKind.INPUT: "power",
    DeviceKind.RELAY: "gauge",
    DeviceKind.SPD: "shield-bolt",
    DeviceKind.RCD: "shield-check",
    DeviceKind.CHANGEOVER: "arrows-exchange",
    DeviceKind.ATS: "arrows-exchange",
    DeviceKind.FEED: "plug-connected",
    DeviceKind.OUTPUT: "plug-connected",
    DeviceKind.CONTACTOR: "toggle-left",
    DeviceKind.DC_BATTERY: "battery-charging",
    DeviceKind.DC_BREAKER: "solar-panel",
    DeviceKind.DC_SPD: "shield-bolt",
}
FALLBACK_ICON = "bolt"


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


def _what(head: str) -> str:
    """What the line feeds: the appliance of "Розетка: бойлер", the first of "Розетки, вивід"."""
    _, colon, appliance = head.partition(": ")
    return _capital(appliance if colon else head.split(", ")[0])


def _where(tail: str, rooms: list[str]) -> str:
    """The first place, without its details, and how many more: "Кімната +2". Room names go
    from the loads: they may hold commas themselves ("Кухня-вітальня, коридор, передпокій")."""
    known = sorted((r for r in rooms if r and r in tail), key=tail.find)
    places = known or re.split(r", | \+ ", tail)
    first = re.split(r",| \+ | \(", places[0])[0].strip()
    more = f" +{len(places) - 1}" if len(places) > 1 else ""
    return f"{_capital(first)}{more}" if first else ""


def short_name(purpose: str, rooms: list[str]) -> tuple[str, ...]:
    """Name blocks from the purpose "what — where"; a block without a place is one line."""
    head, _, tail = purpose.partition(" — ")
    where = _where(tail.strip(), rooms)
    return (_what(head.strip()), where) if where else (_what(head.strip()),)


def group_icon(group: PanelGroup) -> str:
    """Icon by what the line feeds: the place in the purpose does not count ("Санвузол 2
    (пральня)" is no washing machine)."""
    head = group.purpose.partition(" — ")[0].lower()
    for icon, words in GROUP_ICONS:
        if any(w in head for w in words):
            return icon
    return KIND_ICONS[group.kind]


def _device_sticker(d: Device, row: int, groups: dict[str, PanelGroup]) -> Sticker:
    group = groups.get(d.group) if d.group is not None else None
    if group is not None:
        rooms = list(dict.fromkeys(ld.room for ld in group.loads))
        lines = short_name(group.purpose, rooms)
        return Sticker(d.id, row, lines, group_icon(group), group.purpose, group.group)
    name = re.split(r"[:(]", d.title)[0].strip()
    return Sticker(d.id, row, (name,), DEVICE_ICONS.get(d.kind, FALLBACK_ICON), d.title)


def build_stickers(panel: BoardPanel) -> list[Sticker]:
    """Stickers in the order of the devices: rail by rail, left to right, then the battery box."""
    groups = {g.group: g for g in panel.groups}
    rails = [*panel.rows, *(panel.dc.rows if panel.dc is not None else ())]
    placed = {d.id for rail in rails for d in rail}
    extra = tuple(d for d in panel.all_devices if d.id not in placed)
    if extra:
        rails.append(extra)
    return [_device_sticker(d, r, groups) for r, rail in enumerate(rails) for d in rail]
