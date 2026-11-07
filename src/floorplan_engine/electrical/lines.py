"""Each line from the panel gets its own breaker (decision 2026-10-28).

With the premium panel scheme and the proper layout, a model group is split by the wiring
lines leaving the panel (wiring.py: a room or zone box, a direct line to a point):
QF1 → QF1, QF1.2, QF1.3. The split happens before the panel, wiring, tables and estimate,
so they all see the same groups and every line from the panel has its own breaker. In
economy and standard the group stays one: several lines from the panel on one breaker.

The first line keeps the group name and its `groups` entry; the others get the group's
breaker and RCD, and the code builds their purpose from the points. The group's cables and
its place on the panel backup bus (`panel.reserve`) carry over to all its lines.
Low-voltage does not go into the panel and is not split.
"""

from __future__ import annotations

from floorplan_engine.electrical.groups import LOW
from floorplan_engine.electrical.panel import scheme_of
from floorplan_engine.electrical.wiring import box_wiring
from floorplan_engine.electrical.wiring_model import line_starts
from floorplan_engine.model.geometry import Contour
from floorplan_engine.model.schema import Electrical, Group, Plan


def per_line(elec: Electrical) -> bool:
    """Each line from the panel has its own breaker: premium panel or proper layout."""
    return elec.mode == "proper" or scheme_of(elec) == "premium"


def line_names(group: str, count: int, taken: set[str]) -> list[str]:
    """Line names of a group: the first is the group itself, then QF1.2, QF1.3…; taken names are
    skipped."""
    out = [group]
    k = 2
    while len(out) < count:
        name = f"{group}.{k}"
        if name not in taken:
            out.append(name)
        k += 1
    return out


# Last result: validation and panel questions share the same model, so wiring is
# computed once
_last: tuple[str, Electrical] | None = None


def split_by_lines(plan: Plan, contours: dict[str, Contour], elec: Electrical) -> Electrical:
    """Model where each line from the panel has its own group; if not premium or proper, or there is
    no panel or no lines, the model is returned as is."""
    global _last
    if not per_line(elec):
        return elec
    key = plan.model_dump_json() + elec.model_dump_json()
    if _last is None or _last[0] != key:
        _last = (key, _split(plan, contours, elec))
    return _last[1]


def _split(plan: Plan, contours: dict[str, Contour], elec: Electrical) -> Electrical:
    wiring = box_wiring(plan, contours, elec)
    if wiring is None:
        return elec
    points = {p.id for p in elec.points}
    # A point's line is what is fed from the panel: a box, the point itself or its daisy chain
    line_of = {t: s for t, s in line_starts(wiring.runs).items() if t in points}
    lines: dict[str, list[str]] = {}
    for r in wiring.runs:
        if r.source == "board":
            lines.setdefault(r.group, []).append(r.target)
    taken = {p.group for p in elec.points if p.group} | {c.group for c in elec.cables if c.group}
    rename: dict[str, dict[str, str]] = {}  # group → line → new name
    for group, keys in lines.items():
        pts = [p for p in elec.points if p.group == group]
        if len(keys) < 2 or all(p.type in LOW for p in pts):
            continue
        names = line_names(group, len(keys), taken)
        taken |= set(names)
        rename[group] = dict(zip(keys, names, strict=True))
    if not rename:
        return elec

    def new_group(group: str | None, point: str) -> str | None:
        if group is None or group not in rename:
            return group
        return rename[group].get(line_of.get(point, ""), group)

    new_points = [p.model_copy(update={"group": new_group(p.group, p.id)}) for p in elec.points]
    cables = []
    groups = dict(elec.groups)
    for c in elec.cables:
        cables.append(c)
        if c.group not in rename:
            continue
        for name in list(rename[c.group].values())[1:]:
            to = [p.id for p in new_points if p.group == name]
            cid = f"{c.id}_{name.rsplit('.', 1)[1]}"
            cables.append(c.model_copy(update={"id": cid, "group": name, "to": to}))
    for group, by_line in rename.items():
        info = elec.groups.get(group)
        if info is None:
            continue
        for name in list(by_line.values())[1:]:
            groups[name] = Group(breaker=info.breaker, rcd=info.rcd)
    reserve = [n for g in elec.panel.reserve for n in (rename[g].values() if g in rename else [g])]
    panel = elec.panel.model_copy(update={"reserve": reserve})
    return elec.model_copy(
        update={"points": new_points, "cables": cables, "groups": groups, "panel": panel}
    )
