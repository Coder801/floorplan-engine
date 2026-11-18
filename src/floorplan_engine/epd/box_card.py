"""Junction box card in the viewer: where its cables come from and go to (decision 2026-11-17).

The wiring sheet shows a box as its square and "К1" only; the card (objects.describe_objects,
key "box" of the box:<id> card in the .epd, docs/epd-format.md) carries the cable in and the
cables out with their groups, cable types and lengths, and the viewer draws them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from floorplan_engine.electrical.boxes import BOX_TITLES
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

    def key(end: str) -> str | None:
        if end == "board":
            return "board"
        if end in labels:
            return f"box:{end}"
        return f"point:{end}" if end in points else None

    feed = next((r for r in wiring.runs if r.target == b.id), None)
    cable_in: dict[str, object] | None = None
    if feed is not None:
        cable_in = {
            "key": f"wire:{feed.id}",
            "from": short(feed.source),
            "from_key": key(feed.source),
            "group": feed.group,
            "mark": feed.mark,
            "length_m": _length_m(feed),
        }

    def order(r: Run) -> tuple[int, int, str]:
        if r.target in labels:
            return 0, _box_no(labels[r.target]), r.id
        if r.target in numbers:
            return 1, numbers[r.target], r.id
        return 2, 0, r.target + " " + r.id

    cables_out: list[dict[str, object]] = []
    for r in sorted((r for r in wiring.runs if r.source == b.id), key=order):
        pt = points.get(r.target)
        cables_out.append(
            {
                "key": f"wire:{r.id}",
                "to": short(r.target),
                "to_key": key(r.target),
                "kind": "box" if r.target in labels else "point",
                "point_type": pt.type.value if pt is not None else None,
                "number": numbers.get(r.target),
                "group": r.group,
                "mark": r.mark,
                "length_m": _length_m(r),
            }
        )
    return {
        "label": b.label,
        "size": BOX_TITLES.get(b.size, b.size),
        "in": cable_in,
        "out": cables_out,
    }


def _box_no(label: str) -> int:
    """Number of a box label: "К12" → 12."""
    digits = "".join(ch for ch in label if ch.isdigit())
    return int(digits) if digits else 0


def _length_m(run: Run) -> float:
    return round(run.length_mm / 1000, 1)
