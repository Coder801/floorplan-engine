"""Артефакт проекта `.epd` — инструкции для постраничного построения проекта в кабинете.

Один zip-файл (deflate):

    manifest.json        версия формата, проект, список страниц
    pages/NN.json        страница: размер листа и примитивы

Страница строится из листа project.dxf тем же движком ezdxf, что и PNG-превью: видовые
экраны, блоки, размеры, штриховки, типы линий и текст уже развёрнуты в контуры. Кабинету
не нужны ни шрифты, ни знание DXF — только рисовать пути.

Примитив страницы:

    {"k": "s" | "f",      обводка (stroke) | заливка (fill, правило nonzero)
     "c": "#rrggbb",      цвет (может быть #rrggbbaa)
     "w": 0.25,           толщина линии, мм — только у "s"
     "l": "A-WALL",       слой DXF (можно прятать слои в кабинете)
     "o": "wall:living.w3", объект проекта «тип:id» (ids.py); нет у рамки, штампа, таблиц
     "d": "M10 20L30 40"} путь в синтаксисе SVG path: M, L, Q, C, Z

Координаты — мм листа, начало в левом верхнем углу, ось Y вниз (как в SVG и canvas),
округление до 0,01 мм. Подряд идущие примитивы одного стиля склеены в один путь.
Сборка детерминирована: одинаковый проект — побайтно одинаковый файл.
"""

from __future__ import annotations

import json
import re
import zipfile
from collections.abc import Iterable
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
from floorplan_engine.epd.side import STAGE_OBJECTS, SideTable
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
# Фиксированная дата записей zip — для побайтной повторяемости
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
_PAPER_FORMAT = re.compile(r"_(A\d)_")


def _num(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


@dataclass
class PageRecorder(BackendInterface):
    """Бэкенд движка ezdxf: собирает примитивы страницы вместо рисования."""

    height: float  # высота листа, мм — для переворота оси Y
    objects: dict[str, str] = field(default_factory=dict)  # хэндл → «тип:id»
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
        # Внешние контуры против часовой, отверстия (буквы «о», «а») — по часовой: nonzero
        d = "".join(self._path(p, close=True) for p in orient_paths(list(paths)))
        self._add("f", d, properties)

    def draw_filled_polygon(self, points: BkPoints2d, properties: BackendProperties) -> None:
        vertices = points.vertices()
        if len(vertices) < 3:
            return
        d = "M" + "L".join(self._xy(v) for v in vertices) + "Z"
        self._add("f", d, properties)

    def draw_image(self, image_data: ImageData, properties: BackendProperties) -> None:
        # Растровых изображений в наших чертежах нет
        pass

    def clear(self) -> None:
        self.items.clear()

    def finalize(self) -> None:
        pass


def record_page(doc: Drawing, layout: Paperspace) -> dict[str, Any]:
    width, height = paper_size(layout)
    # Объекты модели и листа: схема щита нарисована прямо на листе
    objects = {
        e.dxf.handle: f"{oid[0]}:{oid[1]}"
        for e in (*doc.modelspace(), *layout)
        if (oid := object_id(e)) is not None
    }
    recorder = PageRecorder(height, objects)
    # Толщины — как в DXF, в мм листа
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
    if view is None and stage in ("panel", "elevations"):  # схема на листе — по её объектам
        view = objects_rect(recorder.items)
    if view is not None:
        page["view"] = view
    model = model_transform(layout, height)
    if model is not None:
        page["model"] = model
    if stage is not None:
        page["stage"] = stage
    return page


def _viewports(layout: Paperspace) -> Iterable[Any]:
    """Видовые экраны чертежа; служебный видовой экран листа (id 1) не в счёт."""
    for vp in layout.query("VIEWPORT"):
        if vp.dxf.get("id", 0) != 1 and vp.dxf.layer == A_VPORT.name:
            yield vp


def model_transform(layout: Paperspace, height: float) -> list[float] | None:
    """Из мм модели в мм листа: [k, tx, ty] — x листа = k·x + tx, y листа = ty − k·y
    (ось Y листа вниз). Нужен, чтобы править трассы проводки в мм модели."""
    for vp in _viewports(layout):
        k = vp.dxf.height / vp.dxf.view_height
        c, v = vp.dxf.center, vp.dxf.view_center_point
        return [round(k, 8), round(c.x - v.x * k, 4), round(height - c.y + v.y * k, 4)]
    return None


def view_rect(layout: Paperspace, height: float) -> list[float] | None:
    """Видовой экран чертежа на листе: [x0, y0, x1, y1] в мм листа, начало — левый верхний
    угол (как у примитивов). Служебный видовой экран листа (id 1) не в счёт."""
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
SCHEME_MARGIN = 6.0  # мм листа вокруг схемы в области показа


def objects_rect(items: list[dict[str, Any]]) -> list[float] | None:
    """Область схемы без видового экрана (щит): рамка всех примитивов с объектом и подписью
    над ними, с полем; объектов нет — None."""
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
    # Сверху — ещё на заголовок щита: он без объекта
    return [_round(min(xs) - m), _round(min(ys) - 2 * m), _round(max(xs) + m), _round(max(ys) + m)]


def _round(value: float) -> float:
    return round(value, 2)


def _write(zf: zipfile.ZipFile, name: str, data: Any) -> None:
    info = zipfile.ZipInfo(name, date_time=_ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    zf.writestr(info, text.encode("utf-8"), compresslevel=9)


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
) -> Path:
    """Записать .epd: манифест и по странице на каждый лист документа. objects — карточки
    объектов для подсказок (objects.describe_objects): в страницу — только её объекты
    и только темы листа (side.STAGE_OBJECTS). tables — таблицы боковой панели по теме
    листа (side.side_tables). chains — линии для выделения по клику на листе проводки
    (objects.line_chains): в страницу — только нарисованные на ней; groups — состав групп
    для подсветки соседей выделенной линии (objects.line_groups); edit — что можно
    править на листе проводки (objects.wiring_handles); scene — 3D-сцена проводки
    (scene3d.build_scene); panel — щит для своего показа в просмотре (panel_data.panel_data);
    elevations — развёртки данными (elevations.elevation_data): на лист — те, что на нём."""
    pages = []
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for no, layout in enumerate(sheet_layouts(doc), 1):
            page = record_page(doc, layout)
            stage = page.get("stage")
            if objects:
                keys = {item["o"] for item in page["items"] if "o" in item}
                if stage in STAGE_OBJECTS:
                    keys = {k for k in keys if k.partition(":")[0] in STAGE_OBJECTS[stage]}
                page["objects"] = page_objects(keys, objects, plan.language)
            if tables and stage in tables:
                page["tables"] = [t.as_dict() for t in tables[stage]]
            if tables and stage == "wiring" and tables.get("estimate"):
                page["estimate"] = tables["estimate"][0].as_dict()  # вкладка «Смета»
            if chains and stage == "wiring":
                drawn = {item["o"] for item in page["items"] if "o" in item}
                page["chains"] = {
                    k: [x for x in chain if x in drawn]
                    for k, chain in sorted(chains.items())
                    if k in drawn
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
        }
        _write(zf, MANIFEST, manifest)
    return path


def read_artifact(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Манифест и страницы по порядку; проверяет формат и версию."""
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


# --- Эталонный рендер: страница .epd → PNG без DXF и ezdxf --------------------

_TOKEN = re.compile(r"[MLQCZ]|-?\d+(?:\.\d+)?")
_ARGS = {"M": 2, "L": 2, "Q": 4, "C": 6, "Z": 0}
_CODES: dict[str, list[np.uint8]] = {
    "M": [MplPath.MOVETO],
    "L": [MplPath.LINETO],
    "Q": [MplPath.CURVE3] * 2,
    "C": [MplPath.CURVE4] * 3,
}


def parse_path(d: str, height: float) -> MplPath:
    """Путь SVG (M, L, Q, C, Z — абсолютные, ось Y вниз) → путь matplotlib (ось Y вверх)."""
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
        # Толщина: мм листа → пункты на картинке
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
