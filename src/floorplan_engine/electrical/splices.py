"""Joints in flush boxes (decisions 2026-11-25): where light in a chain (light_wiring chain) joins
wires in a switch flush box, which conductor joins how many wires, and what with. One
calculation for the estimate (estimate.quantities: clamps or sleeves and the work), the point
card in the viewer (epd/box_card.splice_card) and the "Points" table
(drawing/schedules.points_table), so the drawing and the estimate cannot drift apart.

Sockets in a loop (distribution loop) have no joints (the user's decision, 2026-11-25): the
cables in and out go into the double terminals of the sockets, the sockets of a block are joined
by jumpers through those terminals, PE too. Before plaster, and after it with two chases
(loop_conduit separate), the cable comes in at one edge of the block and leaves at the other;
with one chase for both (shared) both come down into the first flush box and the outgoing one is
pulled through the block to the last (wiring.through_block adds that length to its line).

A switch has no N and PE terminals, so they are joined in its flush box, and the phase too when
it branches on. How is a studio setting, `splice` in its price list (estimate.PriceList): wago —
Wago 221 lever clamps (the default: a flush box has little room, a clamp opens for the
insulation test); crimp — sleeves with heat shrink (permanent, no springs, but harder to fit in
a flush box and it does not open for the test). A flush box with a joint must be deep,
DEEP_BOX_MM and more. Junction boxes are always crimped.

What is joined at a switch: N and PE — the cable in + the cables out, the switch does not take
them; the phase (L) — in + one tap per device + the feeds on (to another switch or an output);
the switched wire to the lights and the travellers to the second pass switch go from the device
terminals, no joint; the second pass switch gets the travellers, not the phase. Lights are
joined at their own outputs, not in flush boxes: they are not counted.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from floorplan_engine.electrical.switch_links import switch_links
from floorplan_engine.electrical.wiring_context import LAMP_TYPES
from floorplan_engine.electrical.wiring_model import Run, Wiring
from floorplan_engine.model.schema import Electrical, PointType
from floorplan_engine.model.texts import Language

Splice = Literal["wago", "crimp"]
DEFAULT_SPLICE: Splice = "wago"
# Wago 221 by the most wires one clamp joins; more wires than the largest one takes — two clamps
# with a jumper between them
WAGO_SIZES: tuple[tuple[int, str], ...] = ((2, "412"), (3, "413"), (5, "415"))
DEEP_BOX_MM = 60  # a flush box with a joint: in, out, tap and the joints behind the device
Conductor = Literal["L", "N", "PE"]
SWITCHES = frozenset({PointType.SWITCH, PointType.PASS_SWITCH})

TEXT: dict[str, dict[str, str]] = {
    "wago": {"ru": "Wago {clamps}", "uk": "Wago {clamps}"},
    "crimp": {"ru": "гильзы ×{n}", "uk": "гільзи ×{n}"},
    "deep": {"ru": "глуб. ≥{mm}", "uk": "глиб. ≥{mm}"},
}


@dataclass(frozen=True)
class Joint:
    """One joined conductor: how many wires, the lines out that are joined to it (the line in is
    always in) and how many device taps."""

    conductor: Conductor
    wires: int
    outs: tuple[str, ...]  # run ids
    taps: int

    @property
    def clamps(self) -> list[str]:
        return wago_clamps(self.wires)


@dataclass(frozen=True)
class FlushBoxJoints:
    """Joints in the flush box of one point: the line in, the lines out, the devices on the
    point, and the joints by conductor (L, N, PE in this order, only the joined ones)."""

    point: str
    feed: str | None  # run id of the line in
    outs: tuple[str, ...]  # run ids of the lines out
    devices: int
    joints: tuple[Joint, ...]


def wago_clamps(wires: int) -> list[str]:
    """Wago 221 clamps that join this many wires of one conductor (WAGO_SIZES): none for fewer
    than two; more than the largest clamp takes — that one plus clamps for the rest, each joined
    to the previous by a jumper (one entry of both)."""
    if wires < 2:
        return []
    for n, model in WAGO_SIZES:
        if wires <= n:
            return [model]
    n, model = WAGO_SIZES[-1]
    return [model, *wago_clamps(wires - n + 2)]


def back_box_joints(wiring: Wiring, elec: Electrical) -> dict[str, FlushBoxJoints]:
    """Joints in the flush boxes of a light chain, by point id in model order: only wall switches
    where a line comes in from a point or goes on to one (Run.source is a point); sockets of a
    loop have none (module docstring: what is joined)."""
    by_id = {p.id: p for p in elec.points}
    outs: dict[str, list[Run]] = {}
    fed_by: dict[str, Run] = {}
    for r in wiring.runs:
        fed_by[r.target] = r
        if r.source in by_id:
            outs.setdefault(r.source, []).append(r)
    chained = set(outs) | {t for t, r in fed_by.items() if r.source in by_id}
    lights = {lk.switch: set(lk.targets) for lk in switch_links(elec)}

    def travellers(a: str, b: str) -> bool:
        """Two pass switches of one set (light_chains._pass_sets): the cable between them carries
        the travellers, not the phase."""
        pa, pb = by_id.get(a), by_id.get(b)
        return (
            pa is not None
            and pb is not None
            and pa.type is pb.type is PointType.PASS_SWITCH
            and bool(lights.get(a, set()) & lights.get(b, set()))
        )

    out: dict[str, FlushBoxJoints] = {}
    for p in elec.points:
        if p.id not in chained or p.ceiling is not None:
            continue
        mine = outs.get(p.id, [])
        ids = tuple(r.id for r in mine)
        feed = fed_by.get(p.id)
        joints: list[Joint] = []
        if p.type in SWITCHES:  # a socket has none: double terminals and jumpers
            feeds = tuple(
                r.id for r in mine
                if r.target in by_id and by_id[r.target].type not in LAMP_TYPES
                and not travellers(p.id, r.target)
            )  # fmt: skip
            phase = 1 + p.count + len(feeds)
            phase_in = feed is None or not travellers(feed.source, p.id)
            if phase_in and phase > 2:
                joints.append(Joint("L", phase, feeds, p.count))
            if mine:  # N and PE pass on
                joints += [Joint(c, 1 + len(mine), ids, 0) for c in ("N", "PE")]
        if joints:
            out[p.id] = FlushBoxJoints(p.id, feed.id if feed else None, ids, p.count, tuple(joints))
    return out


def clamp_counts(joints: Mapping[str, FlushBoxJoints]) -> Counter[str]:
    """Wago clamps of all the joints by model."""
    return Counter(m for fb in joints.values() for j in fb.joints for m in j.clamps)


def sleeves(joints: Mapping[str, FlushBoxJoints]) -> int:
    """Crimp sleeves with heat shrink: one per joined conductor, whatever the wires."""
    return sum(len(fb.joints) for fb in joints.values())


def splice_label(fb: FlushBoxJoints, method: Splice, language: Language) -> str:
    """What the joints of a flush box are made with, for the "Points" table and the point card:
    "Wago 3×413", "Wago 2×412 + 1×413", "гильзы ×3"."""
    if method == "crimp":
        return TEXT["crimp"][language].format(n=len(fb.joints))
    counts = Counter(m for j in fb.joints for m in j.clamps)
    clamps = " + ".join(f"{counts[m]}×{m}" for _, m in WAGO_SIZES if counts[m])
    return TEXT["wago"][language].format(clamps=clamps)


def deep_label(language: Language) -> str:
    """The mark of a flush box with a joint: it must be deep."""
    return TEXT["deep"][language].format(mm=DEEP_BOX_MM)


def splice_cell(fb: FlushBoxJoints, method: Splice, language: Language) -> str:
    """The "Joint" cell of the "Points" table and the row of the point card: what with and the
    deep flush box mark ("Wago 3×413, глуб. ≥60")."""
    return f"{splice_label(fb, method, language)}, {deep_label(language)}"


def splice_cells(
    wiring: Wiring | None, elec: Electrical, method: Splice, language: Language
) -> dict[str, str]:
    """The "Joint" cell of each point whose flush box joins wires (splice_cell), by point id."""
    if wiring is None:
        return {}
    return {
        pid: splice_cell(fb, method, language) for pid, fb in back_box_joints(wiring, elec).items()
    }
