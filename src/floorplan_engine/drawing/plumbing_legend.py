"""Legend of the "Plumbing" sheet: rows of caption and sample, variants by columns."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.layout import Paperspace

from floorplan_engine.drawing.fixture_symbols import SIZES, Frame, symbol
from floorplan_engine.drawing.layers import (
    A_TEXT,
    P_FIXT,
    P_OBST,
    P_RISER,
    P_SYMB,
    SURFACE_LINETYPE,
    TEXT_ROOM_MM,
    TEXT_SMALL_MM,
    text_width,
)
from floorplan_engine.drawing.plan import add_text
from floorplan_engine.drawing.plumbing import (
    COLORS,
    FIXTURE_R_MM,
    OBSTACLE_HATCH_MM,
    OUTLET_R_MM,
    SURFACE_COLOR,
    dot,
    net_hatch,
    pipe_attribs,
)
from floorplan_engine.drawing.titleblock import LW_THICK
from floorplan_engine.model.geometry import Vec
from floorplan_engine.model.plumbing import FixtureType
from floorplan_engine.model.scale import sheet
from floorplan_engine.model.texts import Language
from floorplan_engine.plumbing.rows import text as rows_text
from floorplan_engine.plumbing.rules import Kind

LEGEND_ROW_MM = 6.0
LEGEND_SAMPLE_MM = 10.0
LEGEND_GAP_MM = 6.0

TEXT: dict[str, dict[str, str]] = {
    "legend": {"ru": "Условные обозначения", "uk": "Умовні позначення"},
    "riser": {"ru": "Стояк канализации Д110", "uk": "Стояк каналізації Д110"},
    "collector": {
        "ru": "Узел ввода, коллектор: Х — холодной, Г — горячей",
        "uk": "Вузол вводу, колектор: Х — холодної, Г — гарячої",
    },
    "fixture": {
        "ru": "Прибор (номер — в таблице), точки — водорозетки и выпуск",
        "uk": "Прилад (номер — у таблиці), точки — водорозетки і випуск",
    },
    "surface": {
        "ru": "Канализация по стене над полом (в стяжку не помещается) — в коробе",
        "uk": "Каналізація по стіні над підлогою (у стяжку не вміщується) — у коробі",
    },
    "symbol": {
        "ru": "Сантехприбор контуром — типовой размер, для ориентира",
        "uk": "Сантехприлад контуром — типовий розмір, для орієнтиру",
    },
    "obstacle": {
        "ru": "Препятствие: трубы в обход (в короб — только своего прибора)",
        "uk": "Перешкода: труби в обхід (у короб — лише свого приладу)",
    },
}


LegendDraw = Callable[[Paperspace, Vec], None]  # row sample; the point is the middle on the left


def text(key: str, language: Language) -> str:
    return TEXT[key][language]


def _legend_rows(lang: Language) -> list[tuple[str, LegendDraw]]:
    """Legend rows: caption and how to draw the sample (sheet mm)."""
    kinds: tuple[Kind, ...] = ("cold", "hot", "sewer")

    def line(kind: Kind, surface: bool = False) -> LegendDraw:
        def draw(psp: Paperspace, mid: Vec) -> None:
            attribs = pipe_attribs(kind)
            if surface:
                attribs |= {
                    "linetype": SURFACE_LINETYPE,
                    "ltscale": 1 / sheet(1.0),
                    "true_color": SURFACE_COLOR,
                }
            psp.add_line(mid.as_tuple(), (mid.x + LEGEND_SAMPLE_MM, mid.y), dxfattribs=attribs)

        return draw

    def riser(psp: Paperspace, mid: Vec) -> None:
        psp.add_circle(
            (mid.x + LEGEND_SAMPLE_MM / 2, mid.y),
            1.4,
            dxfattribs={
                "layer": P_RISER.name,
                "true_color": COLORS["sewer"],
                "lineweight": LW_THICK,
            },
        )

    def collector(psp: Paperspace, mid: Vec) -> None:
        for k, kind in enumerate(kinds[:2]):
            x = mid.x + 1.0 + k * 4.5
            psp.add_lwpolyline(
                [
                    (x, mid.y - 0.8),
                    (x + 3.5, mid.y - 0.8),
                    (x + 3.5, mid.y + 0.8),
                    (x, mid.y + 0.8),
                ],
                close=True,
                dxfattribs={"layer": P_RISER.name, "true_color": COLORS[kind]},
            )

    def fixture(psp: Paperspace, mid: Vec) -> None:
        c = Vec(mid.x + LEGEND_SAMPLE_MM / 2 + 1.5, mid.y)
        psp.add_circle(c.as_tuple(), FIXTURE_R_MM, dxfattribs={"layer": P_FIXT.name})
        add_text(psp, "1", c, TEXT_SMALL_MM, P_FIXT.name, scale=1.0)
        for k, kind in enumerate((kinds[1], kinds[0], kinds[2])):
            dot(
                psp, Vec(mid.x + 0.6, mid.y + 1.6 - k * 1.6), OUTLET_R_MM, P_FIXT.name, COLORS[kind]
            )

    def symbols(psp: Paperspace, mid: Vec) -> None:
        # Basin and bath at sample scale: model outlines (mm) in sheet mm
        w, d = SIZES[FixtureType.BATH]
        k = LEGEND_SAMPLE_MM / w
        frame = Frame(Vec(0.0, 0.0), Vec(1.0, 0.0), Vec(0.0, -1.0))
        for sh in symbol(FixtureType.BATH, frame):
            pts = [
                (mid.x + LEGEND_SAMPLE_MM / 2 + v.x * k, mid.y + d * k / 2 + v.y * k)
                for v in sh.points
            ]
            psp.add_lwpolyline(pts, close=sh.closed, dxfattribs={"layer": P_SYMB.name})

    def obstacle(psp: Paperspace, mid: Vec) -> None:
        pts = [
            (mid.x, mid.y - 2.0),
            (mid.x + LEGEND_SAMPLE_MM, mid.y - 2.0),
            (mid.x + LEGEND_SAMPLE_MM, mid.y + 2.0),
            (mid.x, mid.y + 2.0),
        ]
        psp.add_lwpolyline(pts, close=True, dxfattribs={"layer": P_OBST.name})
        net_hatch(psp, pts, OBSTACLE_HATCH_MM)

    rows: list[tuple[str, LegendDraw]] = [(rows_text(k, lang), line(k)) for k in kinds]
    rows += [
        (text("surface", lang), line("sewer", surface=True)),
        (text("riser", lang), riser),
        (text("collector", lang), collector),
        (text("fixture", lang), fixture),
        (text("symbol", lang), symbols),
        (text("obstacle", lang), obstacle),
    ]
    return rows


def _draw_legend(
    psp: Paperspace,
    tl: Vec,
    *,
    title: str,
    chunks: list[list[tuple[str, LegendDraw]]],
    widths: list[float],
) -> None:
    left = TextEntityAlignment.MIDDLE_LEFT
    add_text(
        psp,
        title,
        Vec(tl.x, tl.y - TEXT_ROOM_MM / 2),
        TEXT_ROOM_MM,
        A_TEXT.name,
        align=left,
        scale=1.0,
    )
    x = tl.x
    for chunk, w in zip(chunks, widths, strict=True):
        y = tl.y - TEXT_ROOM_MM - 2.0
        for label, sample in chunk:
            mid = Vec(x, y - LEGEND_ROW_MM / 2)
            sample(psp, mid)
            add_text(
                psp,
                label,
                Vec(x + LEGEND_SAMPLE_MM + 3.0, mid.y),
                TEXT_SMALL_MM,
                A_TEXT.name,
                align=left,
                scale=1.0,
            )
            y -= LEGEND_ROW_MM
        x += w + LEGEND_GAP_MM


def legend_variants(lang: Language) -> list[tuple[float, float, LegendDraw]]:
    """Legend variants next to the title block: (width, height, drawing from the top-left corner),
    k rows per column; the layout takes the lowest one that fits (layout.fit_legend)."""
    rows = _legend_rows(lang)
    title = text("legend", lang)
    out: list[tuple[float, float, LegendDraw]] = []
    for k in range(3, len(rows) + 1):
        chunks = [rows[i : i + k] for i in range(0, len(rows), k)]
        widths = [
            LEGEND_SAMPLE_MM + 3.0 + max(text_width(t, TEXT_SMALL_MM) for t, _ in chunk)
            for chunk in chunks
        ]
        width = max(
            sum(widths) + LEGEND_GAP_MM * (len(chunks) - 1), text_width(title, TEXT_ROOM_MM)
        )
        height = TEXT_ROOM_MM + 2.0 + k * LEGEND_ROW_MM
        draw = partial(_draw_legend, title=title, chunks=chunks, widths=widths)
        out.append((width, height, draw))
    return out
