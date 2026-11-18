"""Floor heating for the 3D scene (key `heating` of the wiring page scene, next to the wiring).

No new calculations: zones, the serpentine, the cold lead and the sensor conduit are the very
ones of the "Floor heating" sheet (electrical/floor_heating.py), here only lifted into 3D. Model
mm, Z axis up, floor is 0.

- The heated area is a tint just above the scene floor, the cable a polyline in the screed below
  the floor routes (arcs of the turns as short chords).
- The cold lead and the sensor conduit drop from the controller at its height to the floor at
  the wall and then go over the floor, as on the sheet.
- feed: the lines and boxes that bring the power to the controller from the panel (walked back
  from the controller over the wiring runs): the viewer shows them on the floor heating tab with
  the zone, the rest of the wiring stays hidden there.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from floorplan_engine.drawing.floor_heating import CABLE_COLOR, FRAME_COLOR, ZONE_TINT
from floorplan_engine.electrical.floor_heating import HeatingZone, heating_zones
from floorplan_engine.electrical.heating_layout import Arc, Piece
from floorplan_engine.electrical.wiring_model import Wiring
from floorplan_engine.epd.scene3d import polygon_rings
from floorplan_engine.model.geometry import Contour, Vec
from floorplan_engine.model.schema import Electrical, Plan

CABLE_Z_MM = 10.0  # heating cable in the screed: under the floor routes (20) and water (30)
ARC_STEP_DEG = 15.0  # a turn is drawn as chords of at most this angle
LEAD_COLOR = "#0000ff"  # as the E-FLOORHEAT-LEAD layer on the sheet
SENSOR_COLOR = "#9c27b0"  # as the E-FLOORHEAT-SENSOR layer on the sheet


def _xyz(v: Vec, z: float) -> list[float]:
    return [round(v.x, 1), round(v.y, 1), round(z, 1)]


def _arc(a: Arc) -> list[Vec]:
    n = max(2, math.ceil(abs(a.sweep_deg) / ARC_STEP_DEG))
    return [a.at(a.start_deg + a.sweep_deg * k / n) for k in range(n + 1)]


def cable_line(pieces: Sequence[Piece]) -> list[list[float]]:
    """The serpentine as one polyline at the cable height, without repeated vertices."""
    out: list[list[float]] = []
    for p in pieces:
        for v in _arc(p) if isinstance(p, Arc) else [p.a, p.b]:
            q = _xyz(v, CABLE_Z_MM)
            if not out or q != out[-1]:
                out.append(q)
    return out


def _from_wall(path: Sequence[Vec], reg: Sequence[float] | None) -> list[list[float]]:
    """A lead or the sensor conduit: from the controller (its 3D spot at the wall face) down to the
    floor, then over the floor as on the sheet; empty without a path."""
    if len(path) < 2:
        return []
    out = [_xyz(v, CABLE_Z_MM) for v in path]
    if reg is None:
        return out
    x, y, z = (round(float(c), 1) for c in reg)
    return [[x, y, z], [x, y, CABLE_Z_MM], *out]


def feed(wiring: Wiring, point: str) -> tuple[list[str], list[str]]:
    """Lines and boxes from the panel to the point: the run into the point, the run into its source
    box and so on up to the panel (or a point of a daisy chain, which stays itself)."""
    into = {r.target: r for r in wiring.runs}
    boxes = {b.id for b in wiring.boxes}
    wires: list[str] = []
    via: list[str] = []
    at = point
    while (run := into.get(at)) is not None and run.id not in wires:
        wires.append(run.id)
        at = run.source
        if at not in boxes:
            break
        via.append(at)
    return wires, via


def zone_scene(
    zone: HeatingZone, spot: Sequence[float] | None, wiring: Wiring | None
) -> dict[str, Any]:
    """One zone; spot is its controller in the scene (points[…].pos), None when it is not there."""
    reg = zone.spec.thermostat
    wires, boxes = feed(wiring, reg) if wiring is not None else ([], [])
    return {
        "key": f"heating:{zone.spec.id}",
        "room": zone.spec.room,
        "thermostat": reg,
        "area": polygon_rings(zone.area),
        "cable": cable_line(zone.route.pieces) if zone.route is not None else [],
        "lead": _from_wall(zone.lead, spot),
        "sensor": _from_wall(zone.sensor, spot),
        "feed": {"wires": wires, "boxes": boxes},
        "colors": {
            "tint": f"#{ZONE_TINT:06x}",
            "frame": f"#{FRAME_COLOR:06x}",
            "cable": f"#{CABLE_COLOR:06x}",
            "lead": LEAD_COLOR,
            "sensor": SENSOR_COLOR,
        },
    }


def heating_scene(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical,
    wiring: Wiring | None,
    points: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Key `heating` of the scene: zone id → its 3D; empty without zones. points are the scene
    points (build_scene): the leads start at the controller's 3D spot."""
    zones = heating_zones(plan, contours, elec)
    if not zones:
        return {}
    spot = {k: p["pos"] for k, p in points.items()}
    return {
        "heating": {z.spec.id: zone_scene(z, spot.get(z.spec.thermostat), wiring) for z in zones}
    }
