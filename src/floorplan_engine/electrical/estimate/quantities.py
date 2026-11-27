"""Electrical estimate quantities: what the model needs, by item key, with no prices. They come
from the same calculation as the wiring sheet (wiring.py); there is no separate product
specification: the estimate without prices is the bill of quantities:

- cable by type, with a RESERVE margin; laying work by actual length;
- flush boxes and devices by wall device posts, frames by blocks;
- junction boxes (IP44 in wet rooms, a separate item); crimp connections: L, N, PE in every
  box plus one per key of each switch it feeds;
- joints in flush boxes (decisions 2026-11-25, splices.back_box_joints): only in the switch
  flush boxes of light in a chain (light_wiring chain) — a switch has no N and PE terminals, so
  N and PE pass on there, and the phase when the switch feeds another switch or an output. One
  work item per flush box with a joint, by the studio's method (a setting in its price list,
  `splice`): `work.splice` with Wago 221 clamps (the default), `work.splice_crimp` with crimp
  sleeves (permanent, no springs, but slower in a tight flush box, it needs a deep one and does
  not open for the insulation test). The clamps or sleeves there are not itemised (decision
  2026-11-25): which method is used and why — only in the note (`note_splice`,
  `note_splice_crimp`); `crimp` counts only junction boxes. The clamps by model stay on the
  installer's side (the "Points" table, the point card). Sockets in a loop have no joints: double
  terminals and jumpers through them, PE too (with one chase for both cables the outgoing one is
  pulled through the block — wiring.through_block, in the cable length); junction boxes are
  always crimped;
- fixings shot with a mounting gun (decision 2026-11-11): conduit — clips with a nail by conduit
  diameter, cable without conduit — mounting pads with a nail and a tie; counted at the same
  spots the "Mounting" sheet draws (mounting.py: step by surface, offset from bends and boxes),
  with the norms' reserve for misfires;
- chases from wall_chases (shared by nearby drops): narrow (up to CHASE_NARROW cables) and
  wide ones are separate items, each split by wall material (`work.chase.concrete`, Kyiv
  2026-11: concrete 200, claydite 150, brick 120, aerated 90 UAH/m; a wide one is the narrow
  one × 1.5); a chase without a known material stays `work.chase`; passes through walls from
  wall_holes;
- one breaker per group and the panel installation; the panel set of the "Panel" sheet, its
  assembly and labels replace them in build_estimate (estimate/__init__.py);
- lights, lighting outputs and appliance outputs by point, LED strip in metres; a floor
  heating controller (`thermostat`) is one item by point with no price yet (pricing.UNPRICED)
  and no flush box, frame or fitting work counted for it;
- a LED power supply per LED output and its fitting (decision 2026-11-11): at the strip, or on
  a DIN rail in the panel (Electrical.led_supply), with its own prices; in the panel the
  supplies stand in a box of their own (decision 2026-11-13): by power as its devices, its
  enclosure, and a second panel installation;
- labelling: a tag at each end of each line (in the cable laying);
- extra options of the wizard (decision 2026-11-13), the first two on unless the variant says
  no: panel labels (Electrical.panel_labels) — a sticker on each panel device, by the "Labels"
  view of the panel, one item at a fixed price per panel whatever its size (decision
  2026-11-13); insulation resistance test with a report (Electrical.insulation_test) for each
  power group; protection test with a tester and a report (Electrical.protection_test, off
  unless chosen): RCD and RCBO tripping and the short-circuit current, for each power group;
- rough light, if chosen (Electrical.rough_light): a lamp holder, a bulb and a rough switch per
  room with lights.
"""

from __future__ import annotations

import math
from collections import Counter

from floorplan_engine.electrical.boxes import BOX_ORDER
from floorplan_engine.electrical.estimate.items import CHASE_KEYS, FIXTURES, WALL_MATERIALS
from floorplan_engine.electrical.floor_heating import RELEASED as HEATING_RELEASED
from floorplan_engine.electrical.led_supply import led_outputs as led_outputs_of
from floorplan_engine.electrical.mounting import (
    conduit_diameter,
    fixings,
    pair_diameter,
    plan_conduits,
    shared_pairs,
    source_conduits,
)
from floorplan_engine.electrical.splices import DEFAULT_SPLICE, Splice, back_box_joints
from floorplan_engine.electrical.wiring import RESERVE
from floorplan_engine.electrical.wiring_model import Run, Wiring
from floorplan_engine.model.schema import (
    LIGHT_TYPES,
    SWITCH_TYPES,
    Conduit,
    Electrical,
    PointType,
    WallMaterial,
)

# Conduit fittings (decision 2026-11-11): a joint coupling per this many mm of conduit of a
# diameter (roll ends and offcuts; the conduit itself is counted in metres, not rolls); an
# entry at every conduit end at a junction box or the panel, a flush box takes it without one
CONDUIT_JOINT_EVERY = 50_000.0
# Devices in flush boxes: one flush box per post, one frame per block
MOUNTED = frozenset(
    {PointType.SOCKET, PointType.SWITCH, PointType.PASS_SWITCH, PointType.DATA, PointType.TV}
)


def conduit_mm(run: Run, conduit: Conduit) -> float:
    """How much of a line goes in conduit (decisions 2026-11-01, 2026-11-08,
    docs/wiring-variants.md): on the floor always, the whole line including the rise to the
    point; on the ceiling as chosen (Electrical.conduit_level): the ceiling part, and with walls
    the drops in the chases too."""
    if run.route == "floor" or conduit == "walls":
        return run.length_mm
    return run.plan_mm if conduit == "ceiling" else 0.0


def conduit_lengths(wiring: Wiring, conduit: Conduit) -> dict[int, float]:
    """Conduit by diameter, mm, without margin. On the ceiling and on the floor lines lying
    together share a conduit up to its fill (decision 2026-11-13, mounting.plan_conduits), so do
    the lines of a chase on the rise from the panel or the cabinet (mounting.source_conduits).
    The rest of a line's conduit_mm (drops to the points, cable ends) is in the conduit of its
    cable; a chain pair in one conduit (mounting.shared_pairs) — the drop once, in a conduit of
    pair_diameter."""
    out: dict[int, float] = {}
    shared = [*plan_conduits(wiring, conduit), *source_conduits(wiring, conduit)]
    for piece in shared:
        out[piece.diameter] = out.get(piece.diameter, 0.0) + piece.length
    from_source = {rid for piece in shared if piece.surface == "wall" for rid in piece.runs}
    pairs = shared_pairs(wiring)
    for r in wiring.runs:
        mm = conduit_mm(r, conduit)
        if mm <= 0:
            continue
        mm -= r.plan_mm  # the plan part: in the shared conduits above
        if r.id in wiring.shared_rises or r.id in from_source:
            mm -= r.rise_start_mm  # in the conduit of the cable coming in, or a shared one
        if (out_run := pairs.get(r.id)) is not None:
            mm -= r.rise_end_mm
            d = pair_diameter(r.mark, out_run.mark)
            out[d] = out.get(d, 0.0) + r.rise_end_mm
        d = conduit_diameter(r.mark)
        out[d] = out.get(d, 0.0) + mm
    return out


def quantities(
    wiring: Wiring, elec: Electrical, splice: Splice = DEFAULT_SPLICE
) -> dict[str, float]:
    """Quantities by item key (no prices); splice — how the flush box joints are made."""
    q: dict[str, float] = {}
    for mark, m in wiring.by_mark().items():
        q[f"cable.{mark}"] = round(m * (1 + RESERVE), 1)
    conduit = conduit_lengths(wiring, elec.conduit_level)
    for d in sorted(conduit):
        if conduit[d] > 0:
            q[f"conduit.{d}"] = round(conduit[d] / 1000 * (1 + RESERVE), 1)
    for d in sorted(conduit):
        if conduit[d] > 0:
            q[f"conduit_joint.{d}"] = math.ceil(conduit[d] / CONDUIT_JOINT_EVERY)
    mounted = [p for p in elec.points if p.type in MOUNTED]
    posts = sum(p.count for p in mounted)
    q["socket_box"] = posts
    for b in sorted(wiring.boxes, key=lambda b: BOX_ORDER.index(b.size)):
        key = f"{'junction_box_ip' if b.wet else 'junction_box'}.{b.size}"
        q[key] = q.get(key, 0) + 1
    by_id = {p.id: p for p in elec.points}
    box_ids = {b.id for b in wiring.boxes}
    keys = sum(  # a switch fed from a flush box is spliced there with clamps, not crimped
        by_id[r.target].keys
        for r in wiring.runs
        if r.source in box_ids and r.target in by_id and by_id[r.target].type in SWITCH_TYPES
    )
    q["crimp"] = 3 * len(wiring.boxes) + keys
    # Switch flush boxes of a light chain (splices.py): the work only, by the studio's method;
    # the clamps or sleeves there are not itemised (decision 2026-11-25), the note says which
    joints = back_box_joints(wiring, elec)
    q.update(fixings(wiring, elec.conduit_level))
    if elec.board is not None:
        q["board_enclosure"] = 1
    q["breaker"] = len({r.group for r in wiring.runs})
    pieces: Counter[str] = Counter()
    for p in mounted:
        if p.type is PointType.SWITCH:
            pieces["switch2" if p.keys == 2 else "switch1"] += p.count
        else:
            pieces[p.type.value] += p.count
    for key in ("socket", "switch1", "switch2", "pass_switch", "data", "tv"):
        if pieces[key]:
            q[key] = pieces[key]
    for n, k in sorted(Counter(p.count for p in mounted).items()):
        q[f"frame.{n}"] = k
    fixtures: Counter[str] = Counter()
    for p in elec.points:
        if p.type.value in FIXTURES:
            fixtures[p.type.value] += p.count
    for key in FIXTURES:
        if fixtures[key]:
            q[key] = fixtures[key]
    led_m = sum(s.end - s.start for s in elec.led_strips) / 1000
    if led_m:
        q["led_strip"] = round(led_m, 2)
    led_psu = "led_psu_din" if elec.led_supply == "board" else "led_psu"
    led_outputs = sum(p.count for p in elec.points if p.type is PointType.LED_OUTPUT)
    q[led_psu] = led_outputs
    rough_rooms = len({p.room for p in elec.points if p.type in LIGHT_TYPES})
    if elec.rough_light and rough_rooms:
        q["rough_holder"] = q["rough_lamp"] = q["rough_switch"] = rough_rooms
    if HEATING_RELEASED:  # held back until the next release (floor_heating.RELEASED)
        q.update(heating_quantities(wiring))
    q["work.cable"] = round(sum(r.length_mm for r in wiring.runs) / 1000, 1)
    in_conduit = sum(conduit_mm(r, elec.conduit_level) for r in wiring.runs)
    if in_conduit > 0:
        q["work.conduit"] = round(in_conduit / 1000, 1)
    q.update(chase_quantities(wiring))
    heated = sum(z.area_m2 for z in wiring.heating if z.route is not None)
    if heated and HEATING_RELEASED:
        q["work.floor_heating"] = round(heated, 1)
    q["work.wall_hole"] = sum(1 for h in wiring.holes if not h.large)
    q["work.wall_hole_large"] = sum(1 for h in wiring.holes if h.large)
    q["work.socket_box"] = posts
    q["work.junction_box"] = len(wiring.boxes)
    q["work.splice_crimp" if splice == "crimp" else "work.splice"] = len(joints)
    if elec.board is not None:  # the LED supplies box is a second panel to mount
        q["work.board_install"] = 1 + (1 if led_outputs_of(elec) else 0)
    q["work.mechanism"] = sum(pieces.values())
    q[f"work.{led_psu}"] = led_outputs
    if elec.rough_light and rough_rooms:
        q["work.rough_light"] = q["work.rough_switch"] = rough_rooms
    power_groups = len({r.group for r in wiring.runs if r.circuit == "power"})
    if elec.insulation_test:
        q["work.insulation_test"] = power_groups
    if elec.protection_test:
        q["work.protection_test"] = power_groups
    return {k: v for k, v in q.items() if v}


def heating_quantities(wiring: Wiring) -> dict[str, float]:
    """Floor heating materials (decision 2026-11-14): a section by its length, a floor sensor and
    its conduit (with RESERVE) per zone that has a layout; a zone without one (empty heated
    area) buys nothing — the report says why."""
    q: dict[str, float] = {}
    laid = [z for z in wiring.heating if z.route is not None]
    for z in sorted(laid, key=lambda z: z.length):
        if z.length > 0:
            key = f"heating_cable.{z.length:g}"
            q[key] = q.get(key, 0) + 1
    if laid:
        q["heating_sensor"] = len(laid)
        conduit = sum(z.sensor_m for z in laid)
        if conduit > 0:
            q["heating_conduit"] = round(conduit * (1 + RESERVE), 1)
    return q


def chase_quantities(wiring: Wiring) -> dict[str, float]:
    """Chase metres by item: narrow, then wide, each by wall material from the hardest one; a
    chase without a known material — the item without a parameter, after the others."""
    order: list[WallMaterial | None] = [*WALL_MATERIALS, None]
    out: dict[str, float] = {}
    for base, wide in zip(CHASE_KEYS, (False, True), strict=True):
        for m in order:
            mm = sum(c.length_mm for c in wiring.chases if c.wide == wide and c.material == m)
            if mm > 0:
                out[base if m is None else f"{base}.{m.value}"] = round(mm / 1000, 1)
    return out
