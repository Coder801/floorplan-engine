"""Линия от щита — свой автомат (решение 2026-10-28).

В схеме щита premium и в раскладке proper группа модели делится по линиям проводки от щита
(wiring.py: коробка помещения или зоны, прямая линия к точке): QF1 → QF1, QF1.2, QF1.3.
Деление — до щита, проводки, таблиц и сметы: все видят одни и те же группы, у каждой
линии от щита — свой автомат. В economy и standard группа остаётся одной: несколько линий
от щита на одном автомате.

Первая линия сохраняет имя группы и её запись в `groups`; у остальных — автомат и УЗО
группы, назначение составляет код по точкам. Кабели группы и место в резерве щита
(`panel.reserve`) переходят на все её линии. Слаботочка в щит не идёт и не делится.
"""

from __future__ import annotations

from floorplan_engine.geometry import Contour
from floorplan_engine.groups import LOW
from floorplan_engine.panel import scheme_of
from floorplan_engine.schema import Electrical, Group, Plan
from floorplan_engine.wiring import box_wiring


def per_line(elec: Electrical) -> bool:
    """Каждой линии от щита — свой автомат: щит premium или раскладка proper."""
    return elec.mode == "proper" or scheme_of(elec) == "premium"


def line_names(group: str, count: int, taken: set[str]) -> list[str]:
    """Имена линий группы: первая — сама группа, дальше QF1.2, QF1.3…; занятое имя
    пропускается."""
    out = [group]
    k = 2
    while len(out) < count:
        name = f"{group}.{k}"
        if name not in taken:
            out.append(name)
        k += 1
    return out


# Последний результат: проверка и вопросы щита делят одну и ту же модель — проводка
# считается один раз
_last: tuple[str, Electrical] | None = None


def split_by_lines(plan: Plan, contours: dict[str, Contour], elec: Electrical) -> Electrical:
    """Модель, где у каждой линии от щита своя группа; не premium и не proper, нет щита
    или линий — модель как есть."""
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
    # Линия точки — то, что питается от щита: коробка или сама точка
    line_of = {
        r.target: r.source if r.source != "board" else r.target
        for r in wiring.runs
        if r.target in points
    }
    lines: dict[str, list[str]] = {}
    for r in wiring.runs:
        if r.source == "board":
            lines.setdefault(r.group, []).append(r.target)
    taken = {p.group for p in elec.points if p.group} | {c.group for c in elec.cables if c.group}
    rename: dict[str, dict[str, str]] = {}  # группа → линия → новое имя
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
