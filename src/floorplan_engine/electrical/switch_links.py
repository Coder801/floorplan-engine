"""Which switch turns on what (decision 2026-10-28): the "switch → light" link for the lighting
sheet and for lights wired in a chain without boxes (wiring.py).

The link comes from the switch's `controls` (only from the source). Without it, the link is
guessed by group and room: a switch belongs to the group of the lights it controls (CLAUDE.md
rule) and turns on the lights of its group in its room. Such a link is an assumption marked
"*": for a two-key switch the code does not know which key does what.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from floorplan_engine.electrical.master import is_master, master_on
from floorplan_engine.model.schema import (
    LIGHT_TYPES,
    SWITCH_TYPES,
    Electrical,
    ElectricalPoint,
    PointType,
)


@dataclass(frozen=True)
class SwitchLink:
    switch: str
    targets: tuple[str, ...]  # ids of lights, LED outputs and strips
    assumed: bool  # from group and room, not from controls


# Words in a switch label → which light it turns on (word stems, ru and uk)
KEYWORDS: tuple[tuple[tuple[str, ...], frozenset[PointType]], ...] = (
    (("бра",), frozenset({PointType.SCONCE})),
    (("підвіс", "подвес"), frozenset({PointType.PENDANT})),
    (("підсвіт", "подсвет", "led", "стрічк", "лент"), frozenset({PointType.LED_OUTPUT})),
    (
        ("стел", "потол", "точков", "основн"),
        frozenset({PointType.DOWNLIGHT, PointType.LIGHT}),
    ),
)


def _words(note: str | None) -> set[str]:
    return {w for w in (note or "").lower().replace(",", " ").split() if len(w) >= 4}


def _by_note(s: ElectricalPoint, candidates: Sequence[ElectricalPoint]) -> list[str]:
    """Lights a switch turns on according to its label: by kind ("бра" → wall lamp) or by a word
    shared with the light's label ("підсвітка кухні"). No hint gives []."""
    note = (s.note or "").lower()
    kinds: set[PointType] = set()
    for stems, types in KEYWORDS:
        if any(stem in note for stem in stems):
            kinds |= types
    words = _words(s.note)
    return [c.id for c in candidates if c.type in kinds or (words and words & _words(c.note))]


def switch_links(elec: Electrical) -> list[SwitchLink]:
    """What each switch turns on. From controls, as is. Otherwise an assumption: the lights of its
    group in its room; if the switch label hints at a kind or a shared word ("бра", "стеля",
    "підсвітка кухні"), only those lights; switches without a hint take whatever the hinted ones
    did not take (and if everything is taken, all lights of the group).
    No controls and no group: nothing; the master switch (master.py) drives the panel, not a light.
    A link is never invented."""
    out: list[SwitchLink] = []
    pending: list[tuple[ElectricalPoint, list[ElectricalPoint]]] = []
    claimed: dict[tuple[str, str], set[str]] = {}
    for s in elec.points:
        if s.type not in SWITCH_TYPES:
            continue
        if s.controls:
            out.append(SwitchLink(s.id, tuple(s.controls), False))
            continue
        if s.group is None or (is_master(s) and master_on(elec)):
            continue  # the master switch drives the panel contactor, not a light
        candidates = [
            p
            for p in elec.points
            if p.type in LIGHT_TYPES and p.group == s.group and p.room == s.room
        ]
        hinted = _by_note(s, candidates)
        if hinted:
            out.append(SwitchLink(s.id, tuple(hinted), True))
            claimed.setdefault((s.group, s.room), set()).update(hinted)
        elif candidates:
            pending.append((s, candidates))
    for s, candidates in pending:
        taken = claimed.get((s.group or "", s.room), set())
        rest = [c.id for c in candidates if c.id not in taken] or [c.id for c in candidates]
        out.append(SwitchLink(s.id, tuple(rest), True))
    order = {p.id: k for k, p in enumerate(elec.points)}
    return sorted(out, key=lambda lk: order[lk.switch])
