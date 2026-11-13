"""Sheet tables for the viewer side panel: the same data as the tables on the sheet, as text,
and each row has the drawing objects it refers to (keys "type:id", as in XDATA). Hovering an
object highlights its row, hovering a row highlights its objects.

This module also defines which objects belong to a sheet topic: hints on the wiring sheet
only for wiring, on the plan only for the plan; and the legend for the viewer badge
(legend_entries).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from floorplan_engine.drawing.electrical import legend_rows, wiring_legend_rows
from floorplan_engine.drawing.fields import format_area
from floorplan_engine.drawing.lighting import lighting_model, switch_rows, switch_table
from floorplan_engine.drawing.mounting import bends_table, fixings_table
from floorplan_engine.drawing.panel import ASSUMED, devices_table, panel_notes
from floorplan_engine.drawing.schedules import (
    estimate_table,
    groups_table,
    points_table,
)
from floorplan_engine.drawing.tables import Mark, Table
from floorplan_engine.drawing.wiring import wiring_notes
from floorplan_engine.electrical.colors import group_colors
from floorplan_engine.electrical.estimate import build_estimate
from floorplan_engine.electrical.estimate import text as estimate_text
from floorplan_engine.electrical.groups import group_rows
from floorplan_engine.electrical.groups import text as groups_text
from floorplan_engine.electrical.led_supply import led_lines
from floorplan_engine.electrical.mounting import PRACTICE, mounting_notes
from floorplan_engine.electrical.mounting import text as mounting_text
from floorplan_engine.electrical.panel import BoardPanel, build_panel, color_of
from floorplan_engine.electrical.point_numbers import point_rows
from floorplan_engine.electrical.pricing import Prices, price_notes
from floorplan_engine.electrical.wiring_model import Wiring
from floorplan_engine.electrical.work_scope import ScopeEntry, scope_entries
from floorplan_engine.model.geometry import Contour
from floorplan_engine.model.schema import Electrical, Plan
from floorplan_engine.model.texts import Language, tr
from floorplan_engine.model.zones import plan_floors

# Sheet topic (sheets.SHEET_SLUGS) → object types that get hints on it
STAGE_OBJECTS: dict[str, frozenset[str]] = {
    "plan": frozenset({"room", "zone", "wall", "dimension", "opening"}),
    "electrical": frozenset({"point", "label", "board", "cable", "led_strip"}),
    "lighting": frozenset({"point", "led_strip"}),
    "wiring": frozenset({"wire", "box", "board"}),
    "panel": frozenset({"device", "board"}),
    "elevations": frozenset({"elevation", "dim"}),  # walls, ceilings, ceiling scale values
    "plumbing": frozenset({"fixture", "pipe", "riser", "collector", "obstacle"}),
}

TEXT: dict[str, dict[str, str]] = {
    "consumers": {"ru": "Роспись потребителей", "uk": "Розпис споживачів"},
    "group": {"ru": "Группа", "uk": "Група"},
    "consumer": {"ru": "Потребитель", "uk": "Споживач"},
    "room": {"ru": "Помещение", "uk": "Приміщення"},
    "watts": {"ru": "P, Вт", "uk": "P, Вт"},
    "total": {"ru": "Установленная", "uk": "Встановлена"},
    "common": {"ru": "Ввод и резерв", "uk": "Введення і резерв"},
    "lines": {"ru": "Линии групп", "uk": "Лінії груп"},
    "dc": {"ru": "Щит АКБ", "uk": "Щит АКБ"},
    "led": {"ru": "Щит блоков питания LED", "uk": "Щит блоків живлення LED"},
}


def text(key: str, language: Language) -> str:
    return TEXT[key][language]


@dataclass(frozen=True)
class SideRow:
    cells: tuple[str, ...]
    keys: tuple[str, ...] = ()  # drawing objects of this row
    section: bool = False  # section heading (estimate): one non-empty cell
    color: str | None = None  # group colour "#rrggbb": a dot at the first cell
    hint: str | None = None  # row note: an "i" icon in the estimate, a tooltip in the panel
    marker: str | None = None  # icon of an uncoloured first cell: square = off-line device
    group: str | None = None  # QF group of a "Groups" row: its eye in the viewer
    scope: ScopeEntry | None = None  # work scope of an estimate row: it unfolds in the viewer

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"cells": list(self.cells)}
        if self.hint:
            out["hint"] = self.hint
        if self.color:
            out["color"] = self.color
        if self.marker:
            out["marker"] = self.marker
        if self.group:
            out["group"] = self.group
        if self.scope:
            out["scope"] = {
                "includes": list(self.scope.includes),
                "excludes": list(self.scope.excludes),
                "result": self.scope.result,
            }
        if self.keys:
            out["keys"] = list(self.keys)
        if self.section:
            out["section"] = True
        return out


@dataclass(frozen=True)
class SideTable:
    title: str
    columns: tuple[str, ...]
    align: tuple[str, ...]  # center | left, as on the sheet
    rows: tuple[SideRow, ...]
    total: tuple[str, ...] | None = None
    notes: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "title": self.title,
            "columns": list(self.columns),
            "align": list(self.align),
            "rows": [r.as_dict() for r in self.rows],
        }
        if self.total is not None:
            out["total"] = list(self.total)
        if self.notes:
            out["notes"] = list(self.notes)
        return out


def from_table(
    table: Table, keys: Sequence[tuple[str, ...]] = (), notes: Sequence[str] = ()
) -> SideTable:
    """Sheet table as text. AutoCAD field cells (areas) are not included: they have their own
    builder (room_table)."""

    def cells(row: Sequence[object]) -> tuple[str, ...]:
        assert all(isinstance(c, str | Mark) for c in row), "ячейка-поле: соберите отдельно"
        return tuple(c.text if isinstance(c, Mark) else str(c) for c in row)

    rows = []
    for k, row in enumerate(table.rows):
        texts = cells(row)
        mark = next((c for c in row if isinstance(c, Mark)), None)
        rows.append(
            SideRow(
                texts,
                keys[k] if k < len(keys) else (),
                section=sum(1 for c in texts if c) == 1 and not texts[0],
                color=f"#{mark.color:06x}" if mark is not None else None,
            )
        )
    return SideTable(
        table.title,
        tuple(c.title for c in table.columns),
        tuple(c.align for c in table.columns),
        tuple(rows),
        cells(table.total) if table.total is not None else None,
        tuple(notes),
    )


def drop_column(table: SideTable, index: int) -> SideTable:
    """Table without the index column; its total caption moves into the first total cell."""

    def cut(cells: Sequence[str]) -> tuple[str, ...]:
        return tuple(c for k, c in enumerate(cells) if k != index)

    total = None
    if table.total is not None:
        total = cut(table.total)
        if not total[0] and table.total[index]:
            total = (table.total[index], *total[1:])
    return replace(
        table,
        columns=cut(table.columns),
        align=cut(table.align),
        rows=tuple(replace(r, cells=cut(r.cells)) for r in table.rows),
        total=total,
    )


def room_table(plan: Plan, contours: dict[str, Contour]) -> SideTable:
    """Room schedule: the same rows as on the sheet (a room, or each zone of an open-plan room);
    area as the AutoCAD field will show it."""
    lang = plan.language
    rows = []
    total = 0.0
    for k, floor in enumerate(plan_floors(plan, contours), 1):
        room, contour = floor.room, contours[floor.room.id]
        area = floor.area_mm2
        total += area
        walls = set(floor.walls)
        keys = [floor.key]
        for seg in contour.segments:
            if seg.id in walls:
                keys += [f"wall:{room.id}.{seg.id}", f"dimension:{room.id}.{seg.id}"]
        keys += [f"opening:{op.id}" for op in room.openings if op.wall in walls]
        rows.append(SideRow((str(k), floor.name, format_area(area)), tuple(keys)))
    return SideTable(
        tr("schedule_title", lang),
        (tr("schedule_no", lang), tr("schedule_name", lang), tr("schedule_area", lang)),
        ("center", "left", "center"),
        tuple(rows),
        ("", tr("schedule_total", lang), format_area(total)),
    )


@dataclass(frozen=True)
class LegendEntry:
    """Viewer legend row: the icon is the legend:<key> object on the sheet, and what it means."""

    key: str
    text: str


def legend_entries(elec: Electrical, language: Language) -> list[LegendEntry]:
    """Legend for the viewer badge: the same rows as on the sheet (electrical.legend_rows), without
    the heading: only icon and caption, no counts and no group colours."""
    return [LegendEntry(r.tag, r.text) for r in legend_rows(elec, language) if r.tag]


def side_legends(elec: Electrical, language: Language) -> dict[str, list[LegendEntry]]:
    """Legend by sheet topic: electrical has all symbols of the sheet, lighting only lights,
    wiring the line colour families (electrical.wiring_legend_rows)."""
    return {
        "electrical": legend_entries(elec, language),
        "lighting": legend_entries(lighting_model(elec), language),
        "wiring": [LegendEntry(r.tag, r.text) for r in wiring_legend_rows(elec, language) if r.tag],
    }


def points_side_table(plan: Plan, elec: Electrical) -> SideTable | None:
    """Points: row → points with these numbers."""
    table = points_table(plan, elec)
    if table is None:
        return None
    keys = [tuple(f"point:{p}" for p in r.point_ids) for r in point_rows(plan, elec)]
    return from_table(table, keys)


def lighting_side_table(plan: Plan, elec: Electrical) -> SideTable | None:
    """Switches: row → the switch and the lights it turns on."""
    built = switch_table(plan, elec)
    if built is None:
        return None
    table, notes = built
    keys = []
    strips = {s.id for s in elec.led_strips}
    for r in switch_rows(plan, elec):
        keys.append(tuple(f"led_strip:{i}" if i in strips else f"point:{i}" for i in r.point_ids))
    return from_table(table, keys, notes)


def group_side_table(
    plan: Plan,
    elec: Electrical,
    wiring: Wiring | None = None,
    panel: BoardPanel | None = None,
    extra: Sequence[str] = (),
) -> SideTable | None:
    """The "Groups": row → points, cables, lines and boxes of the group. In the narrow panel the
    "Points" column is dropped (it is on the sheet), otherwise the power does not fit, and the
    purpose becomes the row hint: the viewer shows it when the pointer stays on the row."""
    built = groups_table(plan, elec, wiring, panel)
    if built is None:
        return None
    table, notes = built
    runs = wiring.runs if wiring is not None else ()
    boxes = wiring.boxes if wiring is not None else ()
    keys = [
        tuple(
            [f"point:{p}" for p in r.point_ids]
            + [f"cable:{c}" for c in r.cable_ids]
            + [f"wire:{w.id}" for w in runs if w.group == r.group]
            + [f"box:{b.id}" for b in boxes if b.group == r.group]
        )
        for r in group_rows(plan, elec)
    ]
    side = from_table(table, keys, [*notes, *extra])
    purpose = side.columns.index(groups_text("purpose", plan.language))
    rows = tuple(replace(r, hint=r.cells[purpose], group=r.cells[0]) for r in side.rows)
    points = side.columns.index(groups_text("points", plan.language))
    return drop_column(drop_column(replace(side, rows=rows), points), purpose)


def estimate_side_table(
    wiring: Wiring,
    elec: Electrical,
    language: Language,
    prices: Prices | None,
    panel: BoardPanel | None = None,
) -> SideTable:
    """Estimate (prices from the list on top of the price service) or bill of quantities (prices
    None), for the viewer "Estimate" tab (key estimate of the wiring page); for print the same
    calculation is on the wiring sheet (stages.wiring_panels). A work row carries its scope
    (work_scope.scope_entries): what the price includes, what it does not and the result."""
    priced = prices is not None and prices.priced
    est = build_estimate(wiring, elec, prices or Prices(), language, panel)
    notes = [estimate_text("note_panel", language)] if panel is not None else []
    if prices is not None and priced:
        notes = price_notes(est, prices, language) + notes
    table = from_table(estimate_table(est, language, priced=priced), notes=notes)
    hints = {ln.name: ln.hint for ln in est.lines if ln.hint}
    scopes = {e.name: e for e in scope_entries(est, language)}
    rows = tuple(
        replace(r, hint=hints.get(r.cells[1]), scope=scopes.get(r.cells[1]))
        if len(r.cells) > 1
        else r
        for r in table.rows
    )
    return replace(table, rows=rows)


def side_tables(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical | None,
    wiring: Wiring | None,
    prices: Prices | None = None,
    quantities: Wiring | None = None,
) -> dict[str, list[SideTable]]:
    """Side panel tables by sheet topic (plan / electrical / wiring / panel …) and the estimate
    (estimate) as a separate key on the wiring page, for the viewer "Estimate" tab."""
    lang = plan.language
    out = {"plan": [room_table(plan, contours)]}
    if elec is not None:
        # "Electrical": "Points" has kind, height and count; the legend is a badge on the drawing
        points = points_side_table(plan, elec)
        out["electrical"] = [points] if points is not None else []
        lighting = lighting_side_table(plan, elec)
        out["lighting"] = [lighting] if lighting is not None else []
        if points is not None:
            out["points"] = [points]
        panel = build_panel(plan, elec)
        if wiring is not None:
            groups = group_side_table(plan, elec, wiring, panel, wiring_notes(wiring, lang))
            out["wiring"] = [groups] if groups is not None else []
            out["estimate"] = [estimate_side_table(quantities or wiring, elec, lang, prices, panel)]
            # The elevations carry the installer notes for the side panel (on a ceiling page)
            out["elevations"] = mounting_side_tables(elec, wiring, lang)
        if panel is not None:
            out["panel"] = panel_tables(panel, elec, lang, wiring)
    return out


def mounting_side_tables(elec: Electrical, wiring: Wiring, language: Language) -> list[SideTable]:
    """ "Mounting" in the side panel (decision 2026-11-12: on the sheet the text was too small):
    the installer notes as a list (a table without columns), the fixings by the drawing with the
    reserve note and the smallest bend radii."""
    conduit = elec.conduit_level
    out = [
        SideTable(
            mounting_text("title", language),
            (),
            (),
            (),
            notes=tuple(mounting_notes(elec, language)),
        )
    ]
    fixings = fixings_table(wiring, conduit, language)
    if fixings is not None:
        reserve = mounting_text("reserve", language, pct=round(PRACTICE.reserve * 100))
        out.append(from_table(fixings, notes=[reserve]))
    bends = bends_table(wiring, language)
    if bends is not None:
        out.append(from_table(bends))
    return out


def panel_tables(
    panel: BoardPanel, elec: Electrical, language: Language, wiring: Wiring | None = None
) -> list[SideTable]:
    """The "Panel" sheet: devices with load and weak spots (row → device) and the load list by
    group. Device purchase is in the estimate ("Estimate" tab). LED supplies get their 12 V
    line from the wiring."""
    colors = group_colors(elec)
    led = led_lines(wiring, panel.led.loads) if panel.led is not None else {}
    table = devices_table(panel, language, colors, led)
    keys = [(d.key,) for d in panel.all_devices]
    # The purpose does not fit in the panel: it is in the device card shown on row click
    devices = drop_column(from_table(table, keys, panel_notes(panel, language)), 1)
    out = [replace(devices, rows=_device_sections(panel, devices.rows, language))]
    rows = []
    for g in panel.groups:
        c = color_of(g.group, colors)
        color = f"#{c:06x}" if c is not None else None
        head = (g.group, g.purpose, "", f"{g.power:g}")
        rows.append(SideRow(head, (f"device:{g.group}",), section=True, color=color))
        for ld in g.loads:
            title = ld.title + (f" ×{ld.count}" if ld.count > 1 else "")
            power = f"{ld.power:g}" + (ASSUMED if ld.assumed else "")
            rows.append(SideRow(("", title, ld.room, power), (f"device:{g.group}",)))
    out.append(
        SideTable(
            text("consumers", language),
            (
                text("group", language),
                text("consumer", language),
                text("room", language),
                text("watts", language),
            ),
            ("center", "left", "left", "center"),
            tuple(rows),
            ("", text("total", language), "", f"{panel.installed:g}"),
        )
    )
    return out


def _device_sections(
    panel: BoardPanel, rows: Sequence[SideRow], language: Language
) -> tuple[SideRow, ...]:
    """Panel devices by section: supply and backup (not on a line, square icon), group lines
    (dot in the group colour), battery box and LED supplies box (square icon). One row per device in
    panel.all_devices order."""
    by_id = dict(zip((d.id for d in panel.all_devices), rows, strict=True))
    dc = {d.id for d in panel.dc.devices} if panel.dc is not None else set()
    led = {d.id for d in panel.led.devices} if panel.led is not None else set()
    parts = (
        ("common", [d for d in panel.devices if d.group is None]),
        ("lines", [d for d in panel.devices if d.group is not None]),
        ("dc", [d for d in panel.all_devices if d.id in dc]),
        ("led", [d for d in panel.all_devices if d.id in led]),
    )
    width = len(rows[0].cells) if rows else 0
    out: list[SideRow] = []
    for key, devs in parts:
        if not devs:
            continue
        out.append(SideRow(("", text(key, language), *[""] * (width - 2)), section=True))
        for d in devs:
            row = by_id[d.id]
            out.append(row if d.group is not None else replace(row, marker="square"))
    return tuple(out)
