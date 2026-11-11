"""Group colours by group kind (decision 2026-11-11): lighting is warm, sockets are cool, heavy
lines (cooker, boiler, air conditioner) are red, low-voltage lines are green. The colour tells the
kind at a glance on the wiring, the panel and the colour stickers; the line itself is told by
its mark (QF4). Within a family groups take shades in number order and repeat them in a circle
when there are more groups than shades.

Soft RGB (true color in DXF), readable as a thin line on white (decision 2026-10-25); no greys:
the dark viewer theme recolours grey into ink.
"""

from __future__ import annotations

from collections import Counter

from floorplan_engine.electrical.groups import group_key
from floorplan_engine.electrical.loads import Kind, group_kind
from floorplan_engine.model.schema import Electrical

LOW_VOLTAGE = "low"  # family of groups that are not in the panel (data, TV)

FAMILIES: dict[str, tuple[str, ...]] = {
    Kind.LIGHT: (
        "#f28e2b",  # orange
        "#d4a72c",  # ochre
        "#c9845c",  # terracotta
        "#a6761d",  # dark gold
        "#9c755f",  # brown
    ),
    Kind.SOCKETS: (
        "#4e79a7",  # blue
        "#76b7b2",  # turquoise
        "#7f7fc9",  # lavender
        "#5f9ed1",  # light blue
        "#4fb0a0",  # sea green
        "#3f6fb5",  # cobalt
    ),
    Kind.HEAVY: (
        "#e15759",  # red
        "#a8344f",  # burgundy
        "#e67f8a",  # pink
        "#c2185b",  # crimson
    ),
    LOW_VOLTAGE: (
        "#59a14f",  # green
        "#b07aa1",  # lilac
        "#8cbf5f",  # lime
    ),
}


def rgb(hex_color: str) -> int:
    """Convert "#4e79a7" → DXF true color number (0xRRGGBB)."""
    return int(hex_color.lstrip("#"), 16)


def group_families(elec: Electrical) -> dict[str, str]:
    """Colour family of each model group (a key of FAMILIES), in group number order."""
    groups = sorted(
        {p.group for p in elec.points if p.group} | {c.group for c in elec.cables if c.group},
        key=group_key,
    )
    out: dict[str, str] = {}
    for g in groups:
        kind = group_kind(elec, g)
        out[g] = str(kind) if kind is not None else LOW_VOLTAGE
    return out


def group_colors(elec: Electrical) -> dict[str, int]:
    """Colour (true color, 0xRRGGBB) of each model group: from the family of its kind, shades in
    number order within the family. A line of a split group (QF8.2) takes the colour of the
    group (`panel.color_of`)."""
    used: dict[str, int] = {}
    out: dict[str, int] = {}
    for g, name in group_families(elec).items():
        k = used.get(name, 0)
        used[name] = k + 1
        out[g] = rgb(FAMILIES[name][k % len(FAMILIES[name])])
    return out


def family_colors(elec: Electrical) -> dict[str, tuple[int, ...]]:
    """Families present in the project, in FAMILIES order, with the shades their groups use (for
    the wiring legend)."""
    count = Counter(group_families(elec).values())
    return {
        name: tuple(rgb(c) for c in shades[: count[name]])
        for name, shades in FAMILIES.items()
        if count[name]
    }
