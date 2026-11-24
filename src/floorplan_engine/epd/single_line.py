"""Single-line diagram of the panel as SVG, from the panel page of a built .epd (key `panel`,
docs/epd-format.md, «Щит в лицо»), for the estimate report: the classic panel form, top down.

Layout: the grid comes in at the top left through the input and the voltage relay(s) to the
main bus; top right is the design block — installed power, demand factor, design power and
current, supply (230 V one phase or 400 V three), earthing system, input breaker. Everything
else hangs off a bus as a column, left to right:
- the surge protector (`spd`) — its own branch from the main bus down to earth;
- groups: a breaker or an RCBO straight from the bus, or an RCD over its own bus with the
  breakers it feeds;
- a master-switch contactor: the groups it cuts (`master`) hang off a lower bus behind it,
  the rest stay before it; its control breaker SF1 (electrical/master.CONTROL_ID) is a control
  circuit, not a line: it ends in the coil of the contactor(s), with no cable and no column;
- backup (`external`, `reserve`): the inverter feed QS2 drops from the main bus to the
  inverter U1, its output QS3 goes to input II of the bypass switch SA1 (or the ATS KM1), input I
  comes straight from the main bus; a generator without a feed comes in at a plug terminal.
  The switch feeds the backup bus with its groups and its own contactor; on the way is the
  N–PE link of backup mode (`npe_relay`): drawn solid when the model has it, dashed with "?"
  when it is not known or absent — RCDs on backup do not trip without it.
Under the columns is the table: number (with the group colour, as on the plan; red with "!"
when the calculation has a major warning for the group), device (what it is with its poles,
the rating), cable (mark, section and length from the wiring), installed power, current and
purpose (read top down, from one top line); light rules part the columns. Values the
calculation assumed carry "*" (ASSUMED), as in the viewer. A panel wider than the page goes
on in more tiers, each in its own frame with its own table; a bus that goes on from the tier
above comes in dashed from the left; a tier never splits an RCD or the backup block.

Symbols after IEC 60617: breaker — contact with a cross, RCD — contact with a sensing box,
RCBO — both, contactor — contact with a half-circle, its coil — a narrow box, changeover — a
blade between contacts I and II, voltage relay — box "U", surge protector — box with a
varistor stroke to earth, inverter — box "= / ~". Drawn in mm, plain SVG with the text in the
page font; the same panel always gives the same SVG.
"""

from __future__ import annotations

import html
import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from floorplan_engine.electrical.estimate import cable_title, format_number
from floorplan_engine.electrical.master import CONTROL_ID
from floorplan_engine.model.texts import Language

ASSUMED = "*"  # after a value the calculation assumed, as in the viewer tables

# What a device is, under its id: the abbreviations of the panel device table of the viewer
# (electrical/panel_text.SHORT_NAME, explained by DEVICE_LEGEND under the diagram); poles of
# breakers, RCBOs and RCDs are added by kind_name
KIND: dict[str, dict[Language, str]] = {
    "input": {"ru": "АВ", "uk": "АВ"},
    "breaker": {"ru": "АВ", "uk": "АВ"},
    "feed": {"ru": "АВ", "uk": "АВ"},
    "output": {"ru": "АВ", "uk": "АВ"},
    "diff": {"ru": "АВДТ", "uk": "АВДТ"},
    "rcd": {"ru": "УЗО", "uk": "ПЗВ"},
    "contactor": {"ru": "Контактор", "uk": "Контактор"},
    "relay": {"ru": "Реле напряжения", "uk": "Реле напруги"},
    "spd": {"ru": "УЗИП", "uk": "ПЗІП"},
    "changeover": {"ru": "Переключатель", "uk": "Перемикач"},
    "ats": {"ru": "АВР", "uk": "АВР"},
    "inverter": {"ru": "Инвертор", "uk": "Інвертор"},
    "generator": {"ru": "Генератор", "uk": "Генератор"},
}
TEXT: dict[str, dict[Language, str]] = {
    "installed": {"ru": "Pу", "uk": "Pв"},
    "demand": {"ru": "Kс", "uk": "Kп"},
    "calculated": {"ru": "Pр", "uk": "Pр"},
    "current": {"ru": "Iр", "uk": "Iр"},
    "kw": {"ru": "кВт", "uk": "кВт"},
    "a": {"ru": "А", "uk": "А"},
    "m": {"ru": "м", "uk": "м"},
    "one_phase": {"ru": "230 В, 1 фаза", "uk": "230 В, 1 фаза"},
    "three_phase": {"ru": "400 В, 3 фазы", "uk": "400 В, 3 фази"},
    "input": {"ru": "ввод", "uk": "ввід"},
    "coil": {"ru": "катушка", "uk": "котушка"},
    "npe_yes": {"ru": "связь N–PE в резерве", "uk": "зв'язок N–PE в резерві"},
    "npe_unknown": {"ru": "связь N–PE в резерве?", "uk": "зв'язок N–PE в резерві?"},
    "npe_no": {"ru": "связи N–PE в резерве нет", "uk": "зв'язку N–PE в резерві немає"},
}

# Sizes, mm
PAD = 5.0  # inside the frame
LABELS_W = 28.0  # the left column: the chain above, the table headings below
CHAIN_X = 7.0  # the input line
COL = 14.0  # one table column
CONTACTOR_W = 24.0  # the contactor column: the symbol and its caption
CONTROL_W = 18.0  # the control circuit: the breaker, its caption and the coil
RCD_MIN = 26.0  # an RCD over one breaker still needs room for its caption
BLOCK_W = 38.0  # the backup block: feed and inverter, then the switch
DEVICE_H = 9.0  # a device symbol, top to bottom
CHAIN_STEP = 14.0  # a shared device in the chain with its lead
CONTACTOR_DROP = DEVICE_H + 8.0  # from a bus to the bus behind its contactor
BLOCK_DROP = 60.0  # from the main bus to the backup bus
FONT = 3.0  # text: about 8.5 pt
SMALL = 2.5  # table headings, second lines
LINE = 0.35  # wires
BUS = 0.8  # buses
CABLE = 0.9  # outgoing cables, in the group colour
INK = "#1d2330"
MUTED = "#6b7280"
RULE = "#d9dce1"
ALERT = "#c62828"
TABLE = (  # row key, height
    ("group", 7.0),
    ("device", 11.5),
    ("cable", 11.0),
    ("power", 6.0),
    ("current", 6.0),
    ("purpose", 62.0),
)
CHARS_PER_LINE = 34  # purpose, read top down
PURPOSE_LINES = 3
CHAIN_KINDS = ("input", "relay")
BLOCK_KINDS = ("feed", "output", "changeover", "ats")
CROSS_KINDS = ("breaker", "diff", "input", "feed", "output")
# Buses: the main one and the one behind its contactor, the backup one and behind its contactor
MAIN, MAIN_CUT, BACKUP, BACKUP_CUT = "main", "main_cut", "backup", "backup_cut"


@dataclass
class _Slot:
    """One part of the bus row: a group, an RCD with its groups, a contactor, the control
    circuit, the surge protector or the backup block; `bus` — the bus it hangs off."""

    kind: str  # "group" | "rcd" | "contactor" | "control" | "spd" | "block"
    device: dict[str, Any]
    bus: str
    feeds: list[dict[str, Any]] = field(default_factory=list)
    block: dict[str, Any] = field(default_factory=dict)  # feed, source, output, switch

    @property
    def width(self) -> float:
        if self.kind == "contactor":
            return CONTACTOR_W
        if self.kind == "control":
            return CONTROL_W
        if self.kind == "rcd":
            return max(len(self.feeds) * COL, RCD_MIN)
        if self.kind == "block":
            return BLOCK_W
        return COL

    def columns(self, x: float) -> list[tuple[float, dict[str, Any]]]:
        """Table columns of the slot at x: centre and the device shown."""
        if self.kind == "rcd":
            step = self.width / max(len(self.feeds), 1)
            return [(x + (i + 0.5) * step, d) for i, d in enumerate(self.feeds)]
        if self.kind == "block":
            return [(x + 10.0, self.block["source"]), (x + 27.0, self.block["switch"])]
        if self.kind in ("contactor", "control"):
            return []
        return [(x + self.width / 2, self.device)]


@dataclass(frozen=True)
class _Levels:
    """Heights of a tier, mm from the top of the drawing (inside the frame)."""

    buses: dict[str, float]
    rcd: float  # RCD symbols
    sub: float  # the RCD buses
    breaker: float  # group breakers
    end: float  # cable ends
    table: float  # the table top

    @property
    def height(self) -> float:
        return self.table + sum(h for _, h in TABLE)


@dataclass(frozen=True)
class _Panel:
    """What the drawing reads of the panel page, once."""

    groups: dict[str, dict[str, Any]]
    lengths: dict[str, str]  # group → cable length, m, from the wiring (formatted)
    flagged: frozenset[str]  # groups with a major warning
    input_assumed: bool
    contactors: tuple[str, ...]  # ids, for the control circuit caption
    npe: bool | None
    language: Language


def single_line_svgs(
    panel: dict[str, Any],
    grid: str,
    headings: dict[str, str],
    width: float,
    language: Language = "ru",
    lengths: dict[str, str] | None = None,
) -> list[str]:
    """The diagram of panel (the `panel` key of the panel page) as SVG strings, one framed
    tier each, at most width mm wide (unless one slot is wider) and sized in mm. grid is the
    caption of the input line; headings — the table rows by key (group, device, cable, power,
    current, purpose); language — of the captions; lengths — cable length per group, m, as the
    wiring sheet writes it ("51,6"), none — the cable row has no length."""
    devices: list[dict[str, Any]] = list(panel.get("devices") or [])
    info = _Panel(
        groups=panel.get("groups") or {},
        lengths=lengths or {},
        flagged=frozenset(
            str(w["group"])
            for w in panel.get("warnings") or []
            if w.get("severity") == "major" and w.get("group")
        ),
        input_assumed=bool((panel.get("input") or {}).get("assumed")),
        contactors=tuple(d["id"] for d in devices if d["kind"] == "contactor"),
        npe=panel.get("npe_relay"),
        language=language,
    )
    chain = [d for d in devices if d["kind"] in CHAIN_KINDS]
    slots = _slots(devices, panel.get("external"))
    svgs: list[str] = []
    begun: set[str] = set()
    tiers = _tiers(slots, width - 2 * PAD - LABELS_W)
    # Every tier in a frame of the same width: the widest tier's
    frame = LABELS_W + max(sum(s.width for s in t) for t in tiers)
    for i, tier in enumerate(tiers):
        top = 12.0 + len(chain) * CHAIN_STEP if i == 0 else 6.0
        levels = _levels(top, tier, first=i == 0)
        out = _Svg(info)
        if i == 0:
            _chain(out, chain, grid, top)
            _design(out, panel, frame)
            begun.add(MAIN)
        _tier(out, tier, levels, begun, first=i == 0)
        _table(out, tier, levels, headings)
        svgs.append(out.svg(frame, levels.height))
    return svgs


def assumed_any(panel: dict[str, Any]) -> bool:
    """Whether the diagram carries an ASSUMED mark: the input, a device or a group value."""
    groups: dict[str, dict[str, Any]] = panel.get("groups") or {}
    return (
        bool((panel.get("input") or {}).get("assumed"))
        or bool((panel.get("totals") or {}).get("demand_assumed"))
        or any(d.get("assumed") for d in panel.get("devices") or [])
        or any(
            g.get(k)
            for g in groups.values()
            for k in ("assumed", "cable_assumed", "purpose_assumed")
        )
    )


def _slots(devices: Sequence[dict[str, Any]], external: dict[str, Any] | None) -> list[_Slot]:
    """Slots in bus order: surge protector, main bus (before its contactor, the contactor,
    behind it), the backup block, the backup bus the same way. An RCD takes the breakers it
    feeds, in its own order."""
    by_id = {d["id"]: d for d in devices}
    fed = {g for d in devices if d["kind"] == "rcd" for g in d.get("feeds") or []}
    spd: list[_Slot] = []
    parts: dict[str, list[_Slot]] = {MAIN: [], MAIN_CUT: [], BACKUP: [], BACKUP_CUT: []}
    contactors: dict[str, _Slot] = {}
    for d in devices:
        kind = d["kind"]
        backup = bool(d.get("reserve")) and external is not None
        bus = BACKUP if backup else MAIN
        if kind in CHAIN_KINDS or kind in BLOCK_KINDS:
            continue
        if kind == "spd":
            spd.append(_Slot("spd", d, MAIN))
        elif kind == "contactor":
            contactors[bus] = _Slot("contactor", d, bus)
        elif d["id"] == CONTROL_ID:
            parts[bus].append(_Slot("control", d, bus))
        elif kind == "rcd" or (d.get("group") not in fed and d["id"] not in fed):
            under = [by_id[g] for g in d.get("feeds") or [] if g in by_id]
            behind = bool(d.get("master")) and bus in contactors
            slot = _Slot("rcd" if kind == "rcd" else "group", d, bus, under)
            parts[(BACKUP_CUT if backup else MAIN_CUT) if behind else bus].append(slot)
    slots = [*spd]
    for bus, cut in ((MAIN, MAIN_CUT), (BACKUP, BACKUP_CUT)):
        if bus == BACKUP and external is not None:
            slots.append(_block(by_id, external))
        slots += parts[bus]
        if bus in contactors:
            slots.append(contactors[bus])
            for s in parts[cut]:
                s.bus = cut
            slots += parts[cut]
    return slots


def _block(by_id: dict[str, dict[str, Any]], external: dict[str, Any]) -> _Slot:
    """The backup block: the inverter (or generator) with its feed and output, the switch."""
    feed = by_id.get(str(external.get("feed") or ""))
    to = by_id.get(str(external.get("to") or ""))
    switch = by_id.get(str(external.get("switch") or "")) or {
        "id": "SA1",
        "kind": "changeover",
        "label": "I-0-II",
        "title": "",
    }
    source = {
        "id": str(external.get("id") or "U1"),
        "kind": str(external.get("kind") or "inverter"),
        "label": "",
        "title": str(external.get("title") or ""),
    }
    output = to if to is not None and to["kind"] == "output" else None
    block = {"feed": feed, "source": source, "output": output, "switch": switch}
    return _Slot("block", switch, MAIN, block=block)


def _tiers(slots: Sequence[_Slot], room: float) -> list[list[_Slot]]:
    """Slots in tiers no wider than room; an over-wide slot gets a tier of its own."""
    tiers: list[list[_Slot]] = [[]]
    used = 0.0
    for s in slots:
        if tiers[-1] and used + s.width > room:
            tiers.append([])
            used = 0.0
        tiers[-1].append(s)
        used += s.width
    return tiers


def _levels(top: float, tier: Sequence[_Slot], first: bool) -> _Levels:
    """Heights of the buses this tier uses, from top down, and its rows under the lowest:
    the backup bus is a block drop under the main one when the block is in the tier, else
    just under the buses above it; a bus behind a contactor — a contactor drop under its bus."""
    used = {s.bus for s in tier} | ({MAIN} if first else set())
    for s in tier:
        if s.kind == "contactor":
            used.add(MAIN_CUT if s.bus == MAIN else BACKUP_CUT)
        if s.kind == "block":
            used.add(BACKUP)
    buses: dict[str, float] = {}
    if MAIN in used:
        buses[MAIN] = top
    if MAIN_CUT in used:
        buses[MAIN_CUT] = top + CONTACTOR_DROP if MAIN in used else top
    if BACKUP in used:
        block = any(s.kind == "block" for s in tier)
        above = max(buses.values(), default=None)
        buses[BACKUP] = (
            top + BLOCK_DROP if block else top if above is None else above + CONTACTOR_DROP
        )
    if BACKUP_CUT in used:
        above = max(buses.values(), default=None)
        if BACKUP in buses:
            buses[BACKUP_CUT] = buses[BACKUP] + CONTACTOR_DROP
        else:
            buses[BACKUP_CUT] = top if above is None else above + CONTACTOR_DROP
    lowest = max(buses.values())
    has_rcd = any(s.kind == "rcd" for s in tier)
    rcd_y = lowest + 4.0
    sub = rcd_y + DEVICE_H + 2.0 if has_rcd else lowest
    breaker = sub + 4.0
    end = breaker + DEVICE_H + 7.0
    return _Levels(buses, rcd_y, sub, breaker, end, end + 3.0)


class _Svg:
    """Collects the drawing; coordinates in mm inside the frame."""

    def __init__(self, info: _Panel) -> None:
        self.parts: list[str] = []
        self.info = info
        self.language = info.language

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        stroke: str = INK,
        width: float = LINE,
        dash: bool = False,
    ) -> None:
        dashes = ' stroke-dasharray="1 0.8"' if dash else ""
        self.parts.append(
            f'<path d="M{_n(x1)} {_n(y1)}L{_n(x2)} {_n(y2)}" stroke="{stroke}"'
            f' stroke-width="{_n(width)}"{dashes}/>'
        )

    def path(self, d: str, stroke: str = INK, width: float = LINE) -> None:
        self.parts.append(f'<path d="{d}" stroke="{stroke}" stroke-width="{_n(width)}"/>')

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        fill: str = "#ffffff",
        line: bool = True,
        dash: bool = False,
    ) -> None:
        stroke = f' stroke="{INK}" stroke-width="{_n(LINE)}"' if line else ""
        dashes = ' stroke-dasharray="1 0.8"' if dash else ""
        self.parts.append(
            f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}"'
            f' fill="{fill}"{stroke}{dashes}/>'
        )

    def circle(self, x: float, y: float, r: float, fill: str = INK) -> None:
        stroke = f' stroke="{INK}" stroke-width="{_n(LINE)}"' if fill != INK else ""
        self.parts.append(f'<circle cx="{_n(x)}" cy="{_n(y)}" r="{_n(r)}" fill="{fill}"{stroke}/>')

    def dot(self, x: float, y: float) -> None:
        self.circle(x, y, 0.8)

    def text(
        self,
        x: float,
        y: float,
        value: str,
        size: float = FONT,
        anchor: str = "start",
        colour: str = INK,
        bold: bool = False,
        down: bool = False,
    ) -> None:
        if not value:
            return
        turn = f' transform="rotate(90 {_n(x)} {_n(y)})"' if down else ""
        weight = ' font-weight="600"' if bold else ""
        self.parts.append(
            f'<text x="{_n(x)}" y="{_n(y)}" font-size="{_n(size)}" text-anchor="{anchor}"'
            f' dominant-baseline="central" fill="{colour}"{weight}{turn}>'
            f"{html.escape(value)}</text>"
        )

    def caption(self, x: float, y: float, device: dict[str, Any], anchor: str = "start") -> None:
        """Id in bold, then what the device is and its label, beside a symbol starting at y."""
        self.text(x, y + 2.2, str(device["id"]), anchor=anchor, bold=True)
        self.text(x, y + 5.6, kind_name(device, self.language), SMALL, anchor=anchor)
        self.text(x, y + 8.8, self.label(device), SMALL, anchor=anchor, colour=MUTED)

    def label(self, device: dict[str, Any]) -> str:
        """The rating, starred when the calculation assumed it (the input: panel.input)."""
        assumed = device.get("assumed") or (device["kind"] == "input" and self.info.input_assumed)
        return str(device.get("label") or "") + (ASSUMED if assumed else "")

    def svg(self, w: float, h: float) -> str:
        """The drawing in its frame: PAD all round, the frame on the edge."""
        fw, fh = w + 2 * PAD, h + 2 * PAD
        frame = (
            f'<rect x="0.25" y="0.25" width="{_n(fw - 0.5)}" height="{_n(fh - 0.5)}"'
            f' stroke="{INK}" stroke-width="0.5"/>'
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_n(fw)} {_n(fh)}"'
            f' width="{_n(fw)}mm" height="{_n(fh)}mm" fill="none" stroke-linecap="round"'
            f' stroke-linejoin="round">{frame}<g transform="translate({_n(PAD)} {_n(PAD)})">'
            f"{''.join(self.parts)}</g></svg>"
        )


def _chain(out: _Svg, chain: Sequence[dict[str, Any]], grid: str, bus: float) -> None:
    """The input from the top down to the bus, the shared devices on it, captions right."""
    x = CHAIN_X
    out.text(x - 2.0, 3.0, grid, bold=True)
    y = 7.0
    for d in chain:
        out.line(x, y, x, y + CHAIN_STEP - DEVICE_H)
        y += CHAIN_STEP - DEVICE_H
        _symbol(out, d, x, y)
        out.caption(x + 5.0, y, d)
        y += DEVICE_H
    out.line(x, y, x, bus)


def _design(out: _Svg, panel: dict[str, Any], right: float) -> None:
    """The design block at the top right: loads, supply, earthing, the input breaker."""
    lang = out.language
    totals = panel.get("totals") or {}

    def t(key: str) -> str:
        return TEXT[key][lang]

    def kw(watts: object) -> str:
        return format_number(float(str(watts)) / 1000, 1)

    lines: list[str] = []
    if totals:
        lines.append(
            f"{t('installed')} {kw(totals.get('installed', 0))} {t('kw')} · "
            f"{t('demand')} {format_number(float(totals.get('demand', 0)), 2)}"
            f"{ASSUMED if totals.get('demand_assumed') else ''} · "
            f"{t('calculated')} {kw(totals.get('calculated', 0))} {t('kw')} · "
            f"{t('current')} {format_number(float(totals.get('current', 0)), 1)} {t('a')}"
        )
    supply = t("three_phase") if panel.get("phases") == 3 else t("one_phase")
    earthing = str(panel.get("earthing") or "TN-C-S")
    label = str((panel.get("input") or {}).get("label") or "")
    star = ASSUMED if out.info.input_assumed else ""
    lines.append(f"{supply} · {earthing} · {t('input')} {label}{star}".rstrip(" ·"))
    for i, line in enumerate(lines):
        out.text(right, 3.0 + i * 4.0, line, anchor="end", bold=i == 0)


def _tier(
    out: _Svg,
    tier: Sequence[_Slot],
    lv: _Levels,
    begun: set[str],
    first: bool,
) -> None:
    """Buses, branches, breakers and cable ends of one tier; begun — buses with taps in the
    tiers above (they come in dashed from the left), updated."""
    x = LABELS_W
    taps: dict[str, list[float]] = {}

    def tap(bus: str, at: float) -> None:
        taps.setdefault(bus, []).append(at)

    for s in tier:
        centre = x + s.width / 2
        y = lv.buses[s.bus]
        if s.kind == "contactor":
            cx = x + 6.0
            cut = MAIN_CUT if s.bus == MAIN else BACKUP_CUT
            tap(s.bus, cx)
            out.line(cx, y, cx, y + 4.0)
            _symbol(out, s.device, cx, y + 4.0)
            out.caption(cx + 5.0, y + 4.0, s.device)
            out.line(cx, y + 4.0 + DEVICE_H, cx, lv.buses[cut])
            tap(cut, cx)
        elif s.kind == "control":
            cx = x + 4.0
            tap(s.bus, cx)
            _control(out, s.device, cx, y)
        elif s.kind == "block":
            _backup(out, s, x, lv, tap)
        elif s.kind == "spd":
            tap(s.bus, centre)
            _spd(out, s.device, centre, y)
        elif s.kind == "rcd":
            tap(s.bus, centre)
            out.line(centre, y, centre, lv.rcd)
            _symbol(out, s.device, centre, lv.rcd)
            out.caption(centre - 3.6, lv.rcd, s.device, anchor="end")
            out.line(centre, lv.rcd + DEVICE_H, centre, lv.sub)
            xs = [cx for cx, _ in s.columns(x)]
            if xs:
                out.line(min(xs[0], centre), lv.sub, max(xs[-1], centre), lv.sub, width=BUS)
                out.dot(centre, lv.sub)
            for fx, d in zip(xs, s.feeds, strict=True):
                _group(out, d, fx, lv.sub, lv)
        else:
            tap(s.bus, centre)
            _group(out, s.device, centre, y, lv)
        x += s.width
    for bus, xs in taps.items():
        y = lv.buses[bus]
        start = min(xs)
        if first and bus == MAIN:  # the main bus starts at the input
            start = CHAIN_X
        elif bus in begun:  # it goes on from the tier above: dashed in from the left
            out.line(LABELS_W - 6.0, y, start, y, width=BUS, dash=True)
        out.line(start, y, max(xs), y, width=BUS)
        for cx in xs:
            out.dot(cx, y)
        begun.add(bus)


def _control(out: _Svg, device: dict[str, Any], x: float, bus: float) -> None:
    """The master-switch control circuit: its breaker, then a thin line to the contactor coil
    (a narrow box), captioned with the contactors it drives; no cable, no table column."""
    top = bus + 4.0
    out.line(x, bus, x, top)
    _symbol(out, device, x, top)
    out.caption(x + 4.0, top, device)
    coil = top + DEVICE_H + 6.0
    out.line(x, top + DEVICE_H, x, coil)
    out.rect(x - 1.5, coil, 3.0, 5.0)
    ids = ", ".join(out.info.contactors)
    out.text(x + 4.0, coil + 1.6, ids, SMALL, bold=True)
    out.text(x + 4.0, coil + 4.6, TEXT["coil"][out.language], SMALL, colour=MUTED)
    out.line(x, coil + 5.0, x, coil + 7.0)
    for i, half in enumerate((1.6, 1.0, 0.4)):  # the coil returns to N: a short earth-like stub
        out.line(x - half, coil + 7.0 + i * 0.8, x + half, coil + 7.0 + i * 0.8)


def _backup(out: _Svg, s: _Slot, x: float, lv: _Levels, tap: Any) -> None:
    """Feed → inverter → output → input II of the switch, input I from the main bus, the
    switch output down through the N–PE link of backup mode to the backup bus."""
    top = lv.buses[MAIN]
    xf, xs = x + 10.0, x + 27.0  # the inverter line, the switch
    contact = top + 38.0  # the switch inputs
    feed, source, output, switch = (s.block[k] for k in ("feed", "source", "output", "switch"))
    y = top
    if feed is not None:
        tap(MAIN, xf)
        out.line(xf, y, xf, y + 3.0)
        _symbol(out, feed, xf, y + 3.0)
        out.caption(xf - 3.6, y + 3.0, feed, anchor="end")
        y += 3.0 + DEVICE_H
    if source["kind"] == "inverter":
        out.line(xf, y, xf, top + 14.0)
        out.rect(xf - 4.0, top + 14.0, 8.0, 9.0)
        out.path(f"M{_n(xf - 4.0)} {_n(top + 23.0)}L{_n(xf + 4.0)} {_n(top + 14.0)}")
        out.text(xf - 1.8, top + 16.6, "=", SMALL, anchor="middle")
        out.text(xf + 1.8, top + 20.6, "~", SMALL + 0.4, anchor="middle")
        out.text(xf - 5.0, top + 16.8, source["id"], anchor="end", bold=True)
        out.text(xf - 5.0, top + 20.2, kind_name(source, out.language), SMALL, anchor="end")
        y = top + 23.0
    else:  # a generator plugged in by hand: a terminal
        out.circle(xf, top + 20.0, 1.2, fill="#ffffff")
        out.text(xf - 2.6, top + 18.3, source["id"], anchor="end", bold=True)
        out.text(xf - 2.6, top + 21.7, kind_name(source, out.language), SMALL, anchor="end")
        y = top + 21.2
    if output is not None:
        out.line(xf, y, xf, top + 26.0)
        _symbol(out, output, xf, top + 26.0)
        out.caption(xf - 3.6, top + 26.0, output, anchor="end")
        y = top + 26.0 + DEVICE_H
    out.line(xf, y, xf, contact)
    out.line(xf, contact, xs - 2.5, contact)
    # Input I straight from the main bus
    tap(MAIN, xs + 2.5)
    out.line(xs + 2.5, top, xs + 2.5, contact)
    # The switch: contacts I (right) and II (left), the blade on I, the output down
    pivot = contact + 8.0
    out.line(xs - 2.5, contact, xs - 2.5, contact + 1.5)
    out.line(xs + 2.5, contact, xs + 2.5, contact + 1.5)
    out.line(xs, pivot, xs + 2.3, contact + 1.9)
    out.circle(xs, pivot, 0.5, fill="#ffffff")
    out.text(xs - 2.5, contact - 2.2, "II", SMALL, anchor="middle", colour=MUTED)
    out.text(xs + 4.6, contact - 2.2, "I", SMALL, anchor="middle", colour=MUTED)
    out.caption(xs + 4.0, contact + 1.5, switch)
    # The N–PE link of backup mode on the way to the backup bus: a box across the line, solid
    # when the model has it, dashed with "?" when not known, with a stroke when absent
    npe_y = pivot + 4.0
    out.line(xs, pivot + 0.5, xs, npe_y)
    npe = out.info.npe
    out.rect(xs - 4.5, npe_y, 9.0, 4.0, dash=npe is not True)
    out.text(xs, npe_y + 2.0, "N–PE" if npe is not None else "N–PE?", SMALL - 0.4, "middle")
    if npe is False:
        out.line(xs - 4.5, npe_y + 4.0, xs + 4.5, npe_y, stroke=ALERT, width=0.5)
    key = "npe_yes" if npe else "npe_no" if npe is False else "npe_unknown"
    out.text(xs + 5.5, npe_y + 2.0, TEXT[key][out.language], SMALL, colour=MUTED)
    out.line(xs, npe_y + 4.0, xs, lv.buses[BACKUP])
    tap(BACKUP, xs)


def _spd(out: _Svg, device: dict[str, Any], x: float, bus: float) -> None:
    """The surge protector branch: from the bus through the protector down to earth."""
    y = bus + 4.0
    out.line(x, bus, x, y)
    out.rect(x - 2.2, y, 4.4, 7.0)
    out.path(
        f"M{_n(x - 2.2)} {_n(y + 5.6)}L{_n(x + 2.2)} {_n(y + 1.4)}L{_n(x + 3.2)} {_n(y + 1.4)}"
    )
    out.caption(x - 3.4, y - 0.5, device, anchor="end")
    earth = y + 12.0
    out.line(x, y + 7.0, x, earth)
    for i, half in enumerate((2.4, 1.6, 0.8)):
        out.line(x - half, earth + i * 0.9, x + half, earth + i * 0.9)


def _group(out: _Svg, device: dict[str, Any], x: float, top: float, lv: _Levels) -> None:
    """A group column: from its bus to the breaker, the breaker, the cable in group colour."""
    out.line(x, top, x, lv.breaker)
    _symbol(out, device, x, lv.breaker)
    group = out.info.groups.get(str(device.get("group") or ""), {})
    colour = str(group.get("color") or INK)
    out.line(x, lv.breaker + DEVICE_H, x, lv.end, stroke=colour, width=CABLE)
    arrow = f"M{_n(x - 1.3)} {_n(lv.end - 1.8)}L{_n(x)} {_n(lv.end)}L{_n(x + 1.3)} "
    out.path(arrow + _n(lv.end - 1.8), stroke=colour, width=CABLE)


def _symbol(out: _Svg, device: dict[str, Any], x: float, y: float) -> None:
    """The device symbol between y and y + DEVICE_H, leads included, on the vertical at x."""
    kind = device["kind"]
    h = DEVICE_H
    if kind not in (*CROSS_KINDS, "rcd", "contactor"):
        mark = "U" if kind == "relay" else str(device["id"])
        out.line(x, y, x, y + 1.5)
        out.rect(x - 3.0, y + 1.5, 6.0, h - 3.0)
        out.text(x, y + h / 2, mark, FONT if len(mark) == 1 else SMALL - 0.4, anchor="middle")
        out.line(x, y + h - 1.5, x, y + h)
        return
    fixed, hinge = y + 2.0, y + h - 2.0
    out.line(x, y, x, fixed)
    out.line(x, hinge, x, y + h)
    out.line(x, hinge, x - 2.7, fixed + 0.5)
    if kind in CROSS_KINDS:
        d = 0.9
        out.line(x - d, fixed - d, x + d, fixed + d)
        out.line(x - d, fixed + d, x + d, fixed - d)
    if kind == "contactor":
        out.path(f"M{_n(x - 1.1)} {_n(fixed)}A1.1 1.1 0 0 0 {_n(x + 1.1)} {_n(fixed)}")
    if kind in ("rcd", "diff"):
        mid = (fixed + hinge) / 2 + 0.3
        out.line(x - 1.3, mid, x + 2.0, mid, dash=True)
        out.rect(x + 2.0, mid - 1.3, 2.6, 2.6)


def _table(
    out: _Svg,
    tier: Sequence[_Slot],
    lv: _Levels,
    headings: dict[str, str],
) -> None:
    """The rows under the columns: headings on the left, a cell per column, light rules
    between the columns."""
    columns: list[tuple[float, dict[str, Any]]] = []
    x = LABELS_W
    for s in tier:
        columns += s.columns(x)
        x += s.width
    y = lv.table
    bottom = y + sum(h for _, h in TABLE)
    centres = [cx for cx, _ in columns]
    for left, right in itertools.pairwise(centres):
        out.line((left + right) / 2, y, (left + right) / 2, bottom, stroke=RULE, width=0.3)
    if centres:
        edge = min(LABELS_W, centres[0] - COL / 2)
        out.line(edge, y, edge, bottom, stroke=RULE, width=0.3)
    out.line(0, y, x, y, stroke=RULE, width=0.3)
    for key, h in TABLE:
        heading = headings.get(key, "").upper()
        out.text(0.5, y + min(h / 2, 3.5), heading, SMALL, colour=MUTED, bold=True)
        for cx, d in columns:
            _cell(out, key, d, cx, y, h)
        y += h
        if key != TABLE[-1][0]:
            out.line(0, y, x, y, stroke=RULE, width=0.3)


def _cell(out: _Svg, key: str, device: dict[str, Any], x: float, y: float, h: float) -> None:
    mid = y + h / 2
    name = str(device.get("group") or "")
    group = out.info.groups.get(name, {})
    if key == "group":
        flagged = name in out.info.flagged
        colour = str(group.get("color") or RULE)
        out.rect(x - 5.5, y + 0.6, 11.0, 1.0, fill=colour, line=False)
        number = (name or str(device["id"])) + (" !" if flagged else "")
        out.text(x, mid + 0.6, number, anchor="middle", bold=True, colour=ALERT if flagged else INK)
    elif key == "device":
        # What it is with its poles, then the rating, then the rest of the label (the leakage)
        out.text(x, y + 2.4, kind_name(device, out.language), SMALL - 0.3, anchor="middle")
        top, _, rest = out.label(device).partition(" ")
        out.text(x, y + 6.0, top, anchor="middle")
        out.text(x, y + 9.3, rest, SMALL, anchor="middle", colour=MUTED)
    elif key == "cable":
        cable = str(group.get("cable") or "")
        if cable:
            # Mark and section as the estimate writes them ("ВВГнг 3×2,5"), then the length
            mark, _, section = cable_title(cable).rpartition(" ")
            star = ASSUMED if group.get("cable_assumed") else ""
            out.text(x, y + 2.4, mark, SMALL, anchor="middle", colour=MUTED)
            out.text(x, y + 5.6, section + star, SMALL + 0.2, anchor="middle")
            length = out.info.lengths.get(name)
            if length:
                out.text(x, y + 8.8, f"{length} {TEXT['m'][out.language]}", SMALL, "middle")
    elif key in ("power", "current") and group.get(key) is not None:
        value = format_number(float(group[key]), 0 if key == "power" else 1)
        if key == "power" and group.get("assumed"):
            value += ASSUMED
        out.text(x, mid, value, SMALL + 0.2, anchor="middle")
    elif key == "purpose":
        # Read top down, every column from the same top line; the first line is the right one
        purpose = str(group.get("purpose") or device.get("title") or "")
        lines = _wrap(purpose + (ASSUMED if group.get("purpose_assumed") else ""))
        step = 3.6
        first = x + (len(lines) - 1) * step / 2
        for i, line in enumerate(lines):
            out.text(first - i * step, y + 2.0, line, down=True)


def kind_name(device: dict[str, Any], language: Language) -> str:
    """What the device is, for the caption: АВ 1P, АВДТ 1P+N, УЗО 2P… (3P, 3P+N, 4P for a
    three-phase group, `phase` 3P); other kinds carry their poles in the label; unknown —
    nothing."""
    kind = str(device.get("kind") or "")
    name = KIND.get(kind, {}).get(language, "")
    three = device.get("phase") == "3P"
    poles = {"breaker": ("1P", "3P"), "diff": ("1P+N", "3P+N"), "rcd": ("2P", "4P")}.get(kind)
    return f"{name} {poles[three]}" if poles else name


def _wrap(value: str) -> list[str]:
    """Purpose in lines of CHARS_PER_LINE at word breaks, at most PURPOSE_LINES, then «…»."""
    lines: list[str] = []
    for word in value.split():
        if lines and len(lines[-1]) + 1 + len(word) <= CHARS_PER_LINE:
            lines[-1] += " " + word
        else:
            lines.append(word)
    if len(lines) > PURPOSE_LINES:
        lines = lines[:PURPOSE_LINES]
        lines[-1] = lines[-1][: CHARS_PER_LINE - 1].rstrip() + "…"
    return lines


def _n(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")
