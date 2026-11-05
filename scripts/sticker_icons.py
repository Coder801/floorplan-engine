"""Rebuilds src/floorplan_engine/sheets/stickers_assets/icons.json from Tabler outline icons (MIT).

The sticker PDF and the viewer draw one set of paths, so arcs and relative commands are
flattened here to absolute M/L/C/Z once. Add an icon: unpack `@tabler/icons`, then
uv run --with svgelements python scripts/sticker_icons.py <package>/icons/outline <name>...
with every name, old and new (the key used in electrical/stickers.py).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from svgelements import SVG, Arc, Close, CubicBezier, Line, Move, Point, QuadraticBezier
from svgelements import Path as SvgPath

OUT = Path("src/floorplan_engine/sheets/stickers_assets/icons.json")


def flat(path: SvgPath) -> str:
    """Absolute M/L/C/Z with coordinates to 0.01 of a 24-unit icon."""

    def p2(q: Point) -> str:
        return " ".join(f"{float(v):.2f}".rstrip("0").rstrip(".") for v in (q.x, q.y))

    path = abs(path)
    path.approximate_arcs_with_cubics()
    out: list[str] = []
    for s in path:
        if isinstance(s, Move):
            out.append(f"M{p2(s.end)}")
        elif isinstance(s, Close):
            out.append("Z")
        elif isinstance(s, Line):
            out.append(f"L{p2(s.end)}")
        elif isinstance(s, QuadraticBezier):
            c1 = s.start + (s.control - s.start) * (2 / 3)
            c2 = s.end + (s.control - s.end) * (2 / 3)
            out.append(f"C{p2(c1)} {p2(c2)} {p2(s.end)}")
        elif isinstance(s, CubicBezier):
            out.append(f"C{p2(s.control1)} {p2(s.control2)} {p2(s.end)}")
        else:
            assert not isinstance(s, Arc), "arcs are approximated above"
    return "".join(out)


def main(folder: str, names: list[str]) -> None:
    icons: dict[str, list[str]] = {}
    for name in sorted(names):
        svg = SVG.parse(str(Path(folder) / f"{name}.svg"), reify=True)
        paths = [e for e in svg.elements() if isinstance(e, SvgPath)]
        # Tabler starts each icon with an invisible bounding box path
        icons[name] = [flat(p) for p in paths if p.values.get("stroke") != "none"]
    OUT.write_text(json.dumps(icons, indent=0, sort_keys=True) + "\n", "utf-8")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
