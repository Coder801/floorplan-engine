"""The project artifact `.epd`: instructions for building the project page by page in the viewer.

One zip file (deflate):

    manifest.json        format version, project, list of pages
    pages/NN.json        a page: sheet size and primitives

A page is built from a sheet of project.dxf by the same ezdxf engine as the PNG preview:
viewports, blocks, dimensions, hatches, line types and text are already expanded into
outlines. The viewer needs no fonts and no DXF knowledge, it only draws paths.

Page primitive:

    {"k": "s" | "f",      stroke | fill (nonzero rule)
     "c": "#rrggbb",      colour (may be #rrggbbaa)
     "w": 0.25,           line width, mm, only for "s"
     "l": "A-WALL",       DXF layer (layers can be hidden in the viewer)
     "o": "wall:living.w3", project object "type:id" (ids.py); absent on frame, title block, tables
     "d": "M10 20L30 40"} path in SVG path syntax: M, L, Q, C, Z

Coordinates are sheet mm, origin at the top-left corner, Y axis down (as in SVG and canvas),
rounded to 0.01 mm. Consecutive primitives of the same style are merged into one path.
The build is deterministic: the same project gives a byte-identical file.
"""

from __future__ import annotations

import json
import re
import zipfile
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from ezdxf.addons.drawing.backend import BackendInterface, BkPath2d, BkPoints2d, ImageData
from ezdxf.addons.drawing.config import Configuration, LineweightPolicy
from ezdxf.addons.drawing.properties import BackendProperties
from ezdxf.addons.drawing.type_hints import Color
from ezdxf.document import Drawing
from ezdxf.entities.dxfgfx import DXFGraphic
from ezdxf.layouts.layout import Paperspace
from ezdxf.math import Vec2
from ezdxf.npshapes import orient_paths
from ezdxf.path.commands import Curve3To, LineTo, MoveTo
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath

from floorplan_engine import __version__
from floorplan_engine.drawing.ids import object_id
from floorplan_engine.drawing.layers import A_VPORT
from floorplan_engine.epd.objects import ObjectInfo, page_objects
from floorplan_engine.epd.side import STAGE_OBJECTS, LegendEntry, SideTable
from floorplan_engine.model.schema import Plan
from floorplan_engine.sheets.document import sheet_slug
from floorplan_engine.sheets.preview import (
    LONG_SIDE_INCHES,
    MARGIN,
    PREVIEW_DPI,
    draw_sheet_layout,
    paper_size,
    save_axes,
    sheet_layouts,
)

FORMAT_NAME = "floorplan-engine/epd"
FORMAT_VERSION = 1
MANIFEST = "manifest.json"
# Fixed zip entry date, for byte-identical output
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
_PAPER_FORMAT = re.compile(r"_(A\d)_")


def _num(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


@dataclass
class PageRecorder(BackendInterface):
    """ezdxf engine backend: collects page primitives instead of drawing."""

    height: float  # sheet height, mm, to flip the Y axis
    objects: dict[str, str] = field(default_factory=dict)  # handle → "type:id"
    items: list[dict[str, Any]] = field(default_factory=list)

    def _xy(self, v: Vec2) -> str:
        return f"{_num(v.x)} {_num(self.height - v.y)}"

    def _path(self, path: BkPath2d, close: bool = False) -> str:
        if len(path) == 0:
            return ""
        parts = [f"M{self._xy(path.start)}"]
        for cmd in path.commands():
            if isinstance(cmd, MoveTo):
                parts.append(f"M{self._xy(cmd.end)}")
            elif isinstance(cmd, LineTo):
                parts.append(f"L{self._xy(cmd.end)}")
            elif isinstance(cmd, Curve3To):
                parts.append(f"Q{self._xy(cmd.ctrl)} {self._xy(cmd.end)}")
            else:
                c1, c2, end = self._xy(cmd.ctrl1), self._xy(cmd.ctrl2), self._xy(cmd.end)
                parts.append(f"C{c1} {c2} {end}")
        if close:
            parts.append("Z")
        return "".join(parts)

    def _add(self, kind: str, d: str, props: BackendProperties) -> None:
        if not d:
            return
        item: dict[str, Any] = {"k": kind, "c": props.color}
        if kind == "s":
            item["w"] = round(props.lineweight, 2)
        item["l"] = props.layer
        if props.handle in self.objects:
            item["o"] = self.objects[props.handle]
        last = self.items[-1] if self.items else None
        if last is not None and all(last.get(k) == item.get(k) for k in ("k", "c", "w", "l", "o")):
            last["d"] += d
        else:
            item["d"] = d
            self.items.append(item)

    # --- BackendInterface ---------------------------------------------------

    def configure(self, config: Configuration) -> None:
        pass

    def enter_entity(self, entity: DXFGraphic, properties: Any) -> None:
        pass

    def exit_entity(self, entity: DXFGraphic) -> None:
        pass

    def set_background(self, color: Color) -> None:
        pass

    def draw_point(self, pos: Vec2, properties: BackendProperties) -> None:
        self._add("s", f"M{self._xy(pos)}L{self._xy(pos)}", properties)

    def draw_line(self, start: Vec2, end: Vec2, properties: BackendProperties) -> None:
        self._add("s", f"M{self._xy(start)}L{self._xy(end)}", properties)

    def draw_solid_lines(
        self, lines: Iterable[tuple[Vec2, Vec2]], properties: BackendProperties
    ) -> None:
        d = "".join(f"M{self._xy(a)}L{self._xy(b)}" for a, b in lines)
        self._add("s", d, properties)

    def draw_path(self, path: BkPath2d, properties: BackendProperties) -> None:
        self._add("s", self._path(path), properties)

    def draw_filled_paths(self, paths: Iterable[BkPath2d], properties: BackendProperties) -> None:
        # Outer contours counter-clockwise, holes (letters "o", "a") clockwise: nonzero
        d = "".join(self._path(p, close=True) for p in orient_paths(list(paths)))
        self._add("f", d, properties)

    def draw_filled_polygon(self, points: BkPoints2d, properties: BackendProperties) -> None:
        vertices = points.vertices()
        if len(vertices) < 3:
            return
        d = "M" + "L".join(self._xy(v) for v in vertices) + "Z"
        self._add("f", d, properties)

    def draw_image(self, image_data: ImageData, properties: BackendProperties) -> None:
        # Our drawings contain no raster images
        pass

    def clear(self) -> None:
        self.items.clear()

    def finalize(self) -> None:
        pass


def record_page(doc: Drawing, layout: Paperspace) -> dict[str, Any]:
    width, height = paper_size(layout)
    # Model and sheet objects: the panel diagram is drawn directly on the sheet
    objects = {
        e.dxf.handle: f"{oid[0]}:{oid[1]}"
        for e in (*doc.modelspace(), *layout)
        if (oid := object_id(e)) is not None
    }
    recorder = PageRecorder(height, objects)
    # Line widths as in the DXF, in sheet mm
    config = Configuration(lineweight_policy=LineweightPolicy.ABSOLUTE)
    draw_sheet_layout(doc, layout, recorder, config)
    match = _PAPER_FORMAT.search(layout.dxf_layout.dxf.paper_size)
    page: dict[str, Any] = {
        "name": layout.name,
        "format": match.group(1) if match else None,
        "size": [_round(width), _round(height)],
        "background": "#ffffff",
        "items": recorder.items,
    }
    stage = sheet_slug(layout.name)
    view = view_rect(layout, height)
    if view is None and stage in ("panel", "elevations"):  # a diagram on the sheet: by its objects
        view = objects_rect(recorder.items)
    if view is not None:
        page["view"] = view
    model = model_transform(layout, height)
    if model is not None:
        page["model"] = model
    if stage is not None:
        page["stage"] = stage
    return page


def legend_items(
    items: list[dict[str, Any]], entries: Sequence[LegendEntry]
) -> list[dict[str, Any]]:
    """Page legend for the viewer badge: caption and icon primitives from the sheet (tagged
    legend:<key> in electrical.draw_legend, sheet mm). The tag is removed from the sheet
    primitives: this is not a project object and gets no hint or highlight."""
    by_key: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        kind, _, key = item.get("o", "").partition(":")
        if kind == "legend":
            del item["o"]
            by_key.setdefault(key, []).append(dict(item))
    return [{"key": e.key, "text": e.text, "items": by_key.get(e.key, [])} for e in entries]


def _viewports(layout: Paperspace) -> Iterable[Any]:
    """Drawing viewports; the sheet's service viewport (id 1) does not count."""
    for vp in layout.query("VIEWPORT"):
        if vp.dxf.get("id", 0) != 1 and vp.dxf.layer == A_VPORT.name:
            yield vp


def model_transform(layout: Paperspace, height: float) -> list[float] | None:
    """From model mm to sheet mm: [k, tx, ty]: sheet x = k·x + tx, sheet y = ty − k·y
    (sheet Y axis points down). Needed to edit wiring routes in model mm."""
    for vp in _viewports(layout):
        k = vp.dxf.height / vp.dxf.view_height
        c, v = vp.dxf.center, vp.dxf.view_center_point
        return [round(k, 8), round(c.x - v.x * k, 4), round(height - c.y + v.y * k, 4)]
    return None


def view_rect(layout: Paperspace, height: float) -> list[float] | None:
    """Drawing viewport on the sheet: [x0, y0, x1, y1] in sheet mm, origin at the top-left corner
    (as for primitives). The sheet's service viewport (id 1) does not count."""
    for vp in _viewports(layout):
        cx, cy = vp.dxf.center.x, vp.dxf.center.y
        w, h = vp.dxf.width, vp.dxf.height
        return [
            _round(cx - w / 2),
            _round(height - cy - h / 2),
            _round(cx + w / 2),
            _round(height - cy + h / 2),
        ]
    return None


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
SCHEME_MARGIN = 6.0  # sheet mm around the diagram in the view area


def objects_rect(items: list[dict[str, Any]]) -> list[float] | None:
    """Diagram area without a viewport (panel): the bounding box of all primitives with an object
    and
    the labels above them, plus a margin; None if there are no objects."""
    xs: list[float] = []
    ys: list[float] = []
    for item in items:
        if "o" not in item:
            continue
        nums = [float(n) for n in _NUMBER.findall(item["d"])]
        xs += nums[::2]
        ys += nums[1::2]
    if not xs:
        return None
    m = SCHEME_MARGIN
    # Extra room on top for the panel heading: it has no object
    return [_round(min(xs) - m), _round(min(ys) - 2 * m), _round(max(xs) + m), _round(max(ys) + m)]


def _round(value: float) -> float:
    return round(value, 2)


def _write(zf: zipfile.ZipFile, name: str, data: Any) -> None:
    info = zipfile.ZipInfo(name, date_time=_ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    zf.writestr(info, text.encode("utf-8"), compresslevel=9)


@contextmanager
def _replacing(path: Path) -> Iterator[zipfile.ZipFile]:
    """The archive appears whole: the viewer reads it while the project is being rebuilt, and a
    half-written .epd is not a zip file. If writing fails, the previous file stays."""
    temp = path.with_name(f"{path.name}.tmp")
    try:
        with zipfile.ZipFile(temp, "w") as zf:
            yield zf
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def export_artifact(
    doc: Drawing,
    plan: Plan,
    path: Path,
    objects: dict[str, ObjectInfo] | None = None,
    tables: dict[str, list[SideTable]] | None = None,
    chains: dict[str, list[str]] | None = None,
    groups: dict[str, list[str]] | None = None,
    edit: dict[str, Any] | None = None,
    scene: dict[str, Any] | None = None,
    panel: dict[str, Any] | None = None,
    elevations: list[dict[str, Any]] | None = None,
    legends: dict[str, list[LegendEntry]] | None = None,
    variants: dict[str, Any] | None = None,
    overview: dict[str, Any] | None = None,
    plan_chains: dict[str, list[str]] | None = None,
    plan_areas: dict[str, list[list[tuple[float, float]]]] | None = None,
) -> Path:
    """Write the .epd: the manifest and one page per document sheet. objects are object cards for
    hints (objects.describe_objects): a page gets only its own objects and only those of the sheet
    topic (side.STAGE_OBJECTS). tables are side panel tables for the sheet topic
    (side.side_tables). chains are lines to highlight on click on the wiring sheet
    (objects.line_chains): a page gets only those drawn on it; groups is the group membership
    for highlighting neighbours of the selected line (objects.line_groups); edit is what can be
    edited on the wiring sheet (objects.wiring_handles); scene is the 3D wiring scene
    (scene3d.build_scene); panel is the panel for its own view in the viewer
    (panel_data.panel_data); elevations are elevations as data (elevations.elevation_data): a
    sheet gets the ones on it; legends is the legend for the sheet topic (side.side_legends) for
    the viewer badge: captions from here, icons are the legend:<key> primitives from the sheet
    itself; variants are the wiring variants (pipeline.variant_block): the chosen one and a
    summary of all go into the manifest; overview is the project overview
    (overview.overview_data) for the first viewer tab, also in the manifest; plan_chains is what
    to highlight on click on the plan sheet (objects.plan_chains); plan_areas is where a click
    lands on a wall of that sheet (objects.plan_areas), mm of the model."""
    pages = []
    path.parent.mkdir(parents=True, exist_ok=True)
    with _replacing(path) as zf:
        for no, layout in enumerate(sheet_layouts(doc), 1):
            page = record_page(doc, layout)
            stage = page.get("stage")
            if legends and stage in legends:
                page["legend"] = legend_items(page["items"], legends[stage])
            if objects:
                keys = {item["o"] for item in page["items"] if "o" in item}
                if stage in STAGE_OBJECTS:
                    keys = {k for k in keys if k.partition(":")[0] in STAGE_OBJECTS[stage]}
                page["objects"] = page_objects(keys, objects, plan.language)
            if tables and stage in tables:
                page["tables"] = [t.as_dict() for t in tables[stage]]
            if tables and stage == "wiring" and tables.get("estimate"):
                page["estimate"] = tables["estimate"][0].as_dict()  # "Estimate" tab
            if tables and stage == "plumbing" and tables.get("plumbing_estimate"):
                page["estimate"] = tables["plumbing_estimate"][0].as_dict()
            sheet_chains = {"wiring": chains, "plan": plan_chains}.get(stage or "")
            if sheet_chains:
                drawn = {item["o"] for item in page["items"] if "o" in item}
                page["chains"] = {
                    k: [x for x in chain if x in drawn]
                    for k, chain in sorted(sheet_chains.items())
                    if k in drawn
                }
            if plan_areas and stage == "plan" and "model" in page:
                drawn = {item["o"] for item in page["items"] if "o" in item}
                k, tx, ty = page["model"]
                page["areas"] = {
                    key: [
                        [[round(k * x + tx, 2), round(ty - k * y, 2)] for x, y in r] for r in rings
                    ]
                    for key, rings in sorted(plan_areas.items())
                    if key in drawn
                }
            if groups and stage == "wiring":
                drawn = {item["o"] for item in page["items"] if "o" in item}
                page["groups"] = {g: [k for k in keys if k in drawn] for g, keys in groups.items()}
            if edit and stage == "wiring" and "model" in page:
                page["edit"] = edit
            if scene and stage == "wiring":
                page["scene"] = scene
            if panel and stage == "panel":
                page["panel"] = panel
            if elevations and stage == "elevations":
                drawn = {item["o"] for item in page["items"] if "o" in item}
                page["elevations"] = [e for e in elevations if e["key"] in drawn]
            file = f"pages/{no:02d}.json"
            _write(zf, file, page)
            pages.append(
                {
                    "index": no,
                    "name": page["name"],
                    "format": page["format"],
                    "size": page["size"],
                    "file": file,
                    **({"stage": page["stage"]} if "stage" in page else {}),
                }
            )
        manifest = {
            "format": FORMAT_NAME,
            "version": FORMAT_VERSION,
            "generator": f"floorplan-engine {__version__}",
            "project": {"name": plan.name, "language": plan.language},
            "units": "mm",
            "pages": pages,
            **({"variants": variants} if variants else {}),
            **({"overview": overview} if overview else {}),
        }
        _write(zf, MANIFEST, manifest)
    return path


def read_artifact(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Manifest and pages in order; checks format and version."""
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read(MANIFEST))
        if manifest.get("format") != FORMAT_NAME:
            raise ValueError(f"{path}: это не артефакт {FORMAT_NAME}")
        if manifest.get("version") != FORMAT_VERSION:
            raise ValueError(
                f"{path}: версия формата {manifest.get('version')}, поддерживается {FORMAT_VERSION}"
            )
        pages = [json.loads(zf.read(p["file"])) for p in manifest["pages"]]
    return manifest, pages


# --- Reference render: .epd page → PNG without DXF and ezdxf -----------------

_TOKEN = re.compile(r"[MLQCZ]|-?\d+(?:\.\d+)?")
_ARGS = {"M": 2, "L": 2, "Q": 4, "C": 6, "Z": 0}
_CODES: dict[str, list[np.uint8]] = {
    "M": [MplPath.MOVETO],
    "L": [MplPath.LINETO],
    "Q": [MplPath.CURVE3] * 2,
    "C": [MplPath.CURVE4] * 3,
}


def parse_path(d: str, height: float) -> MplPath:
    """SVG path (M, L, Q, C, Z, absolute, Y axis down) → matplotlib path (Y axis up)."""
    tokens = _TOKEN.findall(d)
    vertices: list[tuple[float, float]] = []
    codes: list[np.uint8] = []
    start = (0.0, 0.0)
    k = 0
    while k < len(tokens):
        cmd = tokens[k]
        n = _ARGS[cmd]
        nums = [float(t) for t in tokens[k + 1 : k + 1 + n]]
        k += 1 + n
        if cmd == "Z":
            vertices.append(start)
            codes.append(MplPath.CLOSEPOLY)
            continue
        points = [(x, height - y) for x, y in zip(nums[::2], nums[1::2], strict=True)]
        if cmd == "M":
            start = points[0]
        vertices.extend(points)
        codes.extend(_CODES[cmd])
    return MplPath(vertices, codes)


def render_page_png(page: dict[str, Any], png_path: Path, dpi: int = PREVIEW_DPI) -> Path:
    width, height = page["size"]
    scale = LONG_SIDE_INCHES / max(width, height)
    fig = plt.figure(figsize=(width * scale, height * scale), dpi=dpi)
    try:
        ax = fig.add_axes((MARGIN, MARGIN, 1 - 2 * MARGIN, 1 - 2 * MARGIN))
        # Line width: sheet mm → points in the image
        points_per_mm = scale * (1 - 2 * MARGIN) * 72
        for item in page["items"]:
            path = parse_path(item["d"], height)
            if item["k"] == "f":
                patch = PathPatch(path, facecolor=item["c"], edgecolor="none", lw=0)
            else:
                lw = max(item["w"], 0.05) * points_per_mm
                patch = PathPatch(path, fill=False, edgecolor=item["c"], lw=lw)
            ax.add_patch(patch)
        save_axes(fig, ax, width, height, png_path, dpi)
    finally:
        plt.close(fig)
    return png_path
