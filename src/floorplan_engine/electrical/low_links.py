"""Low-voltage lines: internet and TV without a group, and the 12 V lines of LED supplies in the
panel. Each is a line of its own, outside the groups' boxes.

Points without a group are not counted, except low-voltage (decision 2026-11-11): internet and
TV without a group get a line of their own each (group "Связь" by language) from the
low-voltage cabinet `media`, without it from the panel (assumption); the cabinet tail is like
the panel's. A cable without a group whose targets are all such points (decision 2026-11-17,
low_feeds) sets their source from the project: `board`, `media` or another low point (one UTP
to the TV zone, separate lines from there on); each target gets a line of its own from it, of
the cable's type. A line from a point goes through the whole flat via the openings.

LED supplies in the panel (Electrical.led_supply "board", decision 2026-11-11): each LED
output gets a 12 V line of its own from the panel (Run.led, low-voltage chases), in the
group of the output; its switch stays in the group as before. The supplies stand in a box
under the panel (decision 2026-11-13), the line starts at the panel; its cross-section goes
by the voltage drop over its final length (led_supply.section_for, led_sections), LED_MARK at
least.
With supplies at the strip ("room") the output is a light point of the group, through its box
(wiring_links.py).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from floorplan_engine.electrical.groups import text as group_text
from floorplan_engine.electrical.led_supply import led_loads, led_mark, section_for
from floorplan_engine.electrical.loads import DEFAULT_MARK, LOW_TYPES
from floorplan_engine.electrical.wiring_context import Context, Link, rise
from floorplan_engine.electrical.wiring_model import Route, Run
from floorplan_engine.model.schema import Cable, Electrical, ElectricalPoint, PointType

LED_MARK = "2x1.5"  # 12 V line from a LED supply in the panel to its output (assumption)


def is_low(p: ElectricalPoint) -> bool:
    """Internet or TV point without a group: its line is low-voltage, not of a panel group."""
    return not p.group and p.type in LOW_TYPES


def low_feeds(elec: Electrical) -> dict[str, Cable]:
    """Low-voltage topology from the project (decision 2026-11-17): low point id → the cable
    without a group that feeds it. Such a cable has only low points in `to` and comes from
    `board`, `media` or a low point. A point fed twice or a ring is skipped here (the check
    reports it: validation.electrical); a point not in any cable is not in the result."""
    low = {p.id for p in elec.points if is_low(p)}
    feeds: dict[str, Cable] = {}
    for c in elec.cables:
        if c.group is not None or not all(t in low for t in c.to):
            continue
        if c.from_ not in ("board", "media") and c.from_ not in low:
            continue
        for t in c.to:
            if t not in feeds and t not in feeds_chain(feeds, c.from_):
                feeds[t] = c
    return feeds


def feeds_chain(feeds: dict[str, Cable], source: str) -> list[str]:
    """The source and what feeds it, up to the panel or the cabinet: a target among them is a
    ring."""
    chain = [source]
    while chain[-1] in feeds and len(chain) <= len(feeds):
        chain.append(feeds[chain[-1]].from_)
    return chain


def low_link(ctx: Context, elec: Electrical, p: ElectricalPoint, cable: Cable | None) -> Link:
    """Low-voltage point without a group: a line of its own from the cabinet, else the panel;
    with a cable of the project (low_feeds), from its source and of its type. The route is the
    cable's if set there, else the shared one. A line from a point goes through the flat via the
    openings (cross), as a branch behind a door."""
    if cable is None:
        source = "media" if ctx.media is not None else "board"
        mark, assumed = DEFAULT_MARK["tv" if p.type is PointType.TV else "data"], True
    else:
        source = "board" if cable.from_ == "media" and ctx.media is None else cable.from_
        mark, assumed = cable.cable, False
    own = cable is not None and "route" in cable.model_fields_set
    floor = cable.route == "floor" if cable is not None and own else elec.route == "floor"
    route: Route = "floor" if floor else "ceiling"
    group = group_text("low", ctx.plan.language)
    down = rise(p, ctx.ceiling, route)
    head = ctx.points.get(source)
    if head is not None:
        up = rise(head, ctx.ceiling, route)
        return Link(group, mark, assumed, source, p.id, ctx.anchors[p.id], up, down, route,
                    "low", cross=True)  # fmt: skip
    up = ctx.source_rise(route, source)
    return Link(group, mark, assumed, source, p.id, ctx.anchors[p.id], up, down, route, "low")


def led_link(ctx: Context, elec: Electrical, p: ElectricalPoint) -> Link:
    """LED output fed from a supply in the panel: a 12 V line of its own from the panel along the
    electrical route, in the group of the output (its breaker feeds the supply). Low voltage, so
    it does not share chases with 230 V cables."""
    assert p.group is not None
    route: Route = "floor" if elec.route == "floor" else "ceiling"
    up = ctx.source_rise(route)
    down = rise(p, ctx.ceiling, route)
    anchor = ctx.anchors[p.id]
    return Link(p.group, LED_MARK, True, "board", p.id, anchor, up, down, route, "low", led=True)


def led_sections(runs: Sequence[Run], elec: Electrical) -> list[Run]:
    """12 V LED lines get their cross-section by length and strip current (led_supply), after
    the manual routes: the final length counts."""
    loads = {ld.point: ld for ld in led_loads(elec)}
    out = []
    for r in runs:
        ld = loads.get(r.target) if r.led else None
        if ld is not None:
            r = replace(r, mark=led_mark(section_for(r.length_mm, ld.current)))
        out.append(r)
    return out
