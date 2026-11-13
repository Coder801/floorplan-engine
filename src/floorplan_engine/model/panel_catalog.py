"""Panel catalogue: enclosures (boxes) and manufacturer device models: width in DIN modules,
size and kind.

An enclosure (`Enclosure`) is a real manufacturer panel: rows, modules per row and size; the
panel front view is drawn inside it (viewer, "Panel" sheet), devices are chosen so they do
not stick out of it (`electrical/panel.choose_enclosure`).

A panel device (panel.Device) gets a model by panel brand (`panel.brand` in electrical.yaml),
device kind and poles (a three-phase panel: main switch and surge protector 3P+N, group breaker
3P, RCBO 3P+N); if the brand has no such model, the typical one (`generic`) is used. The
model goes into the .epd page (key `panel`): the viewer draws the device by its kind
(`style`) and colours.

Brands and series are added here only with data from the manufacturer catalogue (width,
height, body colours); article numbers are never invented.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DeviceKind(StrEnum):
    INPUT = "input"  # main switch 2P
    RELAY = "relay"  # voltage relay
    SPD = "spd"  # surge protector
    RCD = "rcd"  # RCD for several groups
    CHANGEOVER = "changeover"  # changeover I-0-II or bypass
    ATS = "ats"  # ATS
    FEED = "feed"  # inverter supply 2P
    OUTPUT = "output"  # inverter output 2P (AC OUT → ATS or switch)
    BREAKER = "breaker"  # group breaker 1P
    DIFF = "diff"  # group RCBO 1P+N
    CONTACTOR = "contactor"  # modular contactor of the master switch, 2P (4P on three phases)
    DC_BATTERY = "dc_battery"  # battery breaker, DC 2P (battery box at the inverter)
    DC_BREAKER = "dc_breaker"  # solar string breaker, DC 2P
    DC_SPD = "dc_spd"  # solar string surge protector, DC (+, −, PE)
    # LED power supply 230 → 12 V on a DIN rail (LED box under the panel, led_supply "board");
    # the value is the estimate item of a DIN supply
    LED_PSU = "led_psu_din"


MODULE_MM = 17.5  # DIN module width, mm


@dataclass(frozen=True)
class CatalogModel:
    id: str  # «generic.breaker»
    brand: str
    series: str
    kind: DeviceKind
    modules: int
    height: float  # mm, on the front face
    style: (
        str  # how to draw: breaker, diff, rcd, relay, spd, changeover, ats, input, feed, contactor
    )
    body: str = "#f4f4f2"  # body colour
    lever: str = "#2b2b2b"  # lever colour
    accent: str | None = None  # insert colour (the "Test" button on an RCBO)

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "id": self.id,
            "brand": self.brand,
            "series": self.series,
            "modules": self.modules,
            "width": round(self.modules * MODULE_MM, 1),
            "height": self.height,
            "style": self.style,
            "body": self.body,
            "lever": self.lever,
        }
        if self.accent is not None:
            out["accent"] = self.accent
        return out


def _generic(
    kind: DeviceKind, modules: int, height: float = 85.0, poles: int = 0, **kw: str
) -> CatalogModel:
    name = f"generic.{kind.value}" + (f".{poles}p" if poles else "")
    return CatalogModel(name, "generic", "", kind, modules, height, kind.value, **kw)


GENERIC: dict[DeviceKind, CatalogModel] = {
    m.kind: m
    for m in (
        _generic(DeviceKind.INPUT, 2),
        _generic(DeviceKind.RELAY, 3, 90.0),
        _generic(DeviceKind.SPD, 2, 90.0),
        _generic(DeviceKind.RCD, 2, accent="#3a6ea5"),
        _generic(DeviceKind.CHANGEOVER, 3, 90.0),
        _generic(DeviceKind.ATS, 4, 90.0),
        _generic(DeviceKind.FEED, 2),
        _generic(DeviceKind.OUTPUT, 2),
        _generic(DeviceKind.BREAKER, 1),
        _generic(DeviceKind.DIFF, 2, accent="#3a6ea5"),
        _generic(DeviceKind.CONTACTOR, 2, 90.0),
        # A 80–250 A DC battery breaker is wider than modular: one and a half modules per pole
        _generic(DeviceKind.DC_BATTERY, 3, 90.0, accent="#c62828"),
        _generic(DeviceKind.DC_BREAKER, 2, accent="#c62828"),
        _generic(DeviceKind.DC_SPD, 3, 90.0),
        _generic(DeviceKind.LED_PSU, 3, 90.0, body="#e9ecef", accent="#f2b705"),
    )
}
# DIN-rail 12 V LED supplies by rated power, W → modules (a typical series: 17.5 mm per
# module, wider with power); a supply is drawn and laid out by its own width
LED_PSU_MODULES: dict[int, int] = {15: 1, 30: 2, 60: 3, 100: 4, 150: 6}


def led_psu_model(watts: int) -> CatalogModel:
    """Typical DIN-rail LED supply of this power: width by LED_PSU_MODULES."""
    modules = LED_PSU_MODULES.get(watts, GENERIC[DeviceKind.LED_PSU].modules)
    base = GENERIC[DeviceKind.LED_PSU]
    return CatalogModel(
        f"{base.id}.{watts}",
        base.brand,
        base.series,
        base.kind,
        modules,
        base.height,
        base.style,
        base.body,
        base.lever,
        base.accent,
    )


# Three-phase panel: a module per pole, N too (a typical modular device)
GENERIC_POLES: dict[tuple[DeviceKind, int], CatalogModel] = {
    (m.kind, poles): m
    for m, poles in (
        (_generic(DeviceKind.INPUT, 4, poles=4), 4),
        (_generic(DeviceKind.SPD, 4, 90.0, poles=4), 4),
        (_generic(DeviceKind.BREAKER, 3, poles=3), 3),
        (_generic(DeviceKind.DIFF, 4, poles=4, accent="#3a6ea5"), 4),
        (_generic(DeviceKind.CONTACTOR, 3, 90.0, poles=4), 4),
    )
}


@dataclass(frozen=True)
class Enclosure:
    """Panel enclosure: rows of DIN rails with `per_row` modules each, outer size, mm."""

    id: str  # «hager.VS212PD»
    brand: str
    series: str
    article: str  # manufacturer article; empty for an on-site enclosure
    rows: int
    per_row: int
    width: float
    height: float
    depth: float
    pitch: float = 125.0  # rail step, mm
    body: str = "#f6f6f3"  # body colour

    @property
    def modules(self) -> int:
        return self.rows * self.per_row

    @property
    def title(self) -> str:
        if not self.article:
            return f"{self.rows}×{self.per_row}"
        return f"{self.brand.capitalize()} {self.series} {self.article}"

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "brand": self.brand,
            "series": self.series,
            "article": self.article,
            "title": self.title,
            "rows": self.rows,
            "per_row": self.per_row,
            "width": self.width,
            "height": self.height,
            "depth": self.depth,
            "pitch": self.pitch,
            "body": self.body,
        }


def _golf(rows: int, per_row: int, width: float, height: float) -> Enclosure:
    article = f"VS{rows}{per_row}PD"
    return Enclosure(
        f"hager.{article}", "hager", "Golf", article, rows, per_row, width, height, 99.0
    )


# Hager Golf, surface mounted, white door, IP40 (hager.com/ua, VS…PD cards):
# size H × W × D; rail step 125 mm is the height difference of one and two rows (252 → 377)
ENCLOSURES: tuple[Enclosure, ...] = (
    _golf(1, 12, 282.0, 252.0),
    _golf(2, 12, 282.0, 377.0),
    _golf(3, 12, 282.0, 500.0),
    _golf(4, 12, 282.0, 647.0),
    _golf(1, 18, 390.0, 252.0),
    _golf(2, 18, 390.0, 377.0),
    _golf(3, 18, 390.0, 500.0),
    _golf(4, 18, 390.0, 647.0),
)
ENCLOSURE_BY_ARTICLE = {e.article: e for e in ENCLOSURES}

RAIL_MARGIN = 37.5  # from the wall to the rail for an on-site enclosure, mm
TOP_BOTTOM = 126.0  # above the first and below the last rail axis for such an enclosure, mm


def fitted_enclosure(rows: int, per_row: int) -> Enclosure:
    """On-site enclosure, used when the devices fit no catalogue panel: the same fields and rail
    step as Golf."""
    width = per_row * MODULE_MM + 2 * RAIL_MARGIN
    height = 2 * TOP_BOTTOM + (rows - 1) * 125.0
    return Enclosure(f"fitted.{rows}x{per_row}", "", "", "", rows, per_row, width, height, 99.0)


# Brand → models by device kind. A new brand is a dict right here, from manufacturer data
BRANDS: dict[str, dict[DeviceKind, CatalogModel]] = {"generic": GENERIC}


def model_for(kind: DeviceKind, brand: str = "generic", poles: int = 0) -> CatalogModel:
    """Brand device model; the typical one if the brand has none. poles: the three-phase
    variant (4 — 3P+N, 3 — 3P), 0 — the usual one of the kind."""
    if poles:
        return GENERIC_POLES[(kind, poles)]
    return BRANDS.get(brand, {}).get(kind) or GENERIC[kind]
