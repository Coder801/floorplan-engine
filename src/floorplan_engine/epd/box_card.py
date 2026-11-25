"""Junction box card in the viewer: where its cables come from and go to (decision 2026-11-17),
and the joints in a flush box of a chain (decision 2026-11-25).

The wiring sheet shows a box as its square and "К1" only; the card (objects.describe_objects,
key "box" of the box:<id> card in the .epd, docs/epd-format.md) carries the cable in and the
cables out with their groups, cable types and lengths, and the viewer draws them. A point whose
flush box joins wires (splices.back_box_joints, the same calculation as the estimate) gets the
key "splice" on its point:<id> card: the method, the cables and the joints by conductor.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from floorplan_engine.electrical.boxes import BOX_TITLES
from floorplan_engine.electrical.splices import DEEP_BOX_MM, FlushBoxJoints, Splice
from floorplan_engine.electrical.wiring_model import JunctionBox, Run, Wiring
from floorplan_engine.model.schema import ElectricalPoint


def box_card(
    b: JunctionBox,
    wiring: Wiring,
    numbers: Mapping[str, int],
    points: Mapping[str, ElectricalPoint],
    short: Callable[[str], str],
) -> dict[str, object]:
    """Where the cables of a box come from and go to, for the box card in the viewer (decision
    2026-11-17: instead of a block of lines beside the box on the wiring sheet). "in" is the
    cable feeding the box, "out" the cables leaving it: boxes by their number, then points by
    their number on the sheets (point_numbers.number_points), then the rest. Names are as in the
    other cards (short); lengths in m to 0.1, as in the cable log."""
    labels = {x.id: x.label for x in wiring.boxes}
    feed = next((r for r in wiring.runs if r.target == b.id), None)
    cable_in = _cable_in(feed, labels, points, short) if feed is not None else None

    def order(r: Run) -> tuple[int, int, str]:
        if r.target in labels:
            return 0, _box_no(labels[r.target]), r.id
        if r.target in numbers:
            return 1, numbers[r.target], r.id
        return 2, 0, r.target + " " + r.id

    cables_out = [
        _cable_out(r, labels, numbers, points, short)
        for r in sorted((r for r in wiring.runs if r.source == b.id), key=order)
    ]
    return {
        "label": b.label,
        "size": BOX_TITLES.get(b.size, b.size),
        "in": cable_in,
        "out": cables_out,
    }


def splice_card(
    fb: FlushBoxJoints,
    method: Splice,
    wiring: Wiring,
    numbers: Mapping[str, int],
    points: Mapping[str, ElectricalPoint],
    short: Callable[[str], str],
) -> dict[str, object]:
    """Joints in the flush box of a point (decision 2026-11-25), for its card in the viewer: the
    method (the studio setting), the cable in and the cables out as in the box card, the devices
    tapped, and each joined conductor — how many wires, which cables out it joins (the cable in
    always), the taps, and what with: Wago clamps by model or one crimp sleeve. A cable out that
    is not in a conductor's joint comes off the device terminals (the switched wire, the
    travellers). deep: the flush box must be DEEP_BOX_MM deep and more."""
    labels = {x.id: x.label for x in wiring.boxes}
    runs = {r.id: r for r in wiring.runs}
    feed = runs.get(fb.feed) if fb.feed is not None else None
    return {
        "method": method,
        "deep_mm": DEEP_BOX_MM,
        "in": _cable_in(feed, labels, points, short) if feed is not None else None,
        "out": [_cable_out(runs[i], labels, numbers, points, short) for i in fb.outs],
        "devices": fb.devices,
        "joints": [
            {
                "conductor": j.conductor,
                "wires": j.wires,
                "out": [f"wire:{i}" for i in j.outs],
                "taps": j.taps,
                "clamps": j.clamps if method == "wago" else [],
                "sleeves": 1 if method == "crimp" else 0,
            }
            for j in fb.joints
        ],
    }


def _end_key(end: str, labels: Mapping[str, str], points: Mapping[str, object]) -> str | None:
    if end == "board":
        return "board"
    if end in labels:
        return f"box:{end}"
    return f"point:{end}" if end in points else None


def _cable_in(
    r: Run,
    labels: Mapping[str, str],
    points: Mapping[str, ElectricalPoint],
    short: Callable[[str], str],
) -> dict[str, object]:
    """The cable feeding a box or a flush box: where from, group, type, length."""
    return {
        "key": f"wire:{r.id}",
        "from": short(r.source),
        "from_key": _end_key(r.source, labels, points),
        "group": r.group,
        "mark": r.mark,
        "length_m": _length_m(r),
    }


def _cable_out(
    r: Run,
    labels: Mapping[str, str],
    numbers: Mapping[str, int],
    points: Mapping[str, ElectricalPoint],
    short: Callable[[str], str],
) -> dict[str, object]:
    """A cable leaving a box or a flush box: where to (a box or a point with its number)."""
    pt = points.get(r.target)
    return {
        "key": f"wire:{r.id}",
        "to": short(r.target),
        "to_key": _end_key(r.target, labels, points),
        "kind": "box" if r.target in labels else "point",
        "point_type": pt.type.value if pt is not None else None,
        "number": numbers.get(r.target),
        "group": r.group,
        "mark": r.mark,
        "length_m": _length_m(r),
    }


def _box_no(label: str) -> int:
    """Number of a box label: "К12" → 12."""
    digits = "".join(ch for ch in label if ch.isdigit())
    return int(digits) if digits else 0


def _length_m(run: Run) -> float:
    return round(run.length_mm / 1000, 1)
