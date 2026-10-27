"""Адаптер векторного PDF (pdfplumber): страница → надписи и отрезки, координаты в pt.

Надписи собираются из символов: направление — по матрице символа, слова и числа
с разделителем тысяч («3 842») — по зазорам между символами. Уверенность — 1: в векторе
текст и координаты точные.
"""

from __future__ import annotations

import itertools
import statistics
from pathlib import Path
from typing import Any

import pdfplumber

from floorplan_engine.service.facts.primitives import Direction, Label, Segment, Sheet

GAP_SPACE = 0.15  # зазор больше этой доли высоты шрифта — пробел
GAP_SPLIT = 0.6  # больше этой — новая надпись


def read_pdf(path: Path, name: str | None = None) -> list[Sheet]:
    with pdfplumber.open(path) as pdf:
        return [page_sheet(p, name or path.name, i) for i, p in enumerate(pdf.pages, 1)]


def page_sheet(page: Any, file: str, page_no: int) -> Sheet:
    return Sheet(
        file, page_no, float(page.width), float(page.height), _labels(page), _segments(page)
    )


def _char_direction(char: dict[str, Any]) -> Direction | None:
    a, b = char["matrix"][0], char["matrix"][1]
    if a > 0.9:
        return "h"
    if b > 0.9:  # повёрнут на 90° против часовой: читается снизу вверх
        return "v"
    return None


def _labels(page: Any) -> list[Label]:
    h = float(page.height)
    by_dir: dict[Direction, list[tuple[float, float, float, float, float, str]]] = {
        "h": [],
        "v": [],
    }
    for c in page.chars:
        direction = _char_direction(c)
        if direction is None or not c["text"].strip():
            continue
        if direction == "h":
            # (база, начало, конец, середина поперёк, высота, текст)
            item = (
                c["matrix"][5],
                c["x0"],
                c["x1"],
                h - (c["top"] + c["bottom"]) / 2,
                c["bottom"] - c["top"],
            )
        else:
            item = (
                c["matrix"][4],
                h - c["bottom"],
                h - c["top"],
                (c["x0"] + c["x1"]) / 2,
                c["x1"] - c["x0"],
            )
        by_dir[direction].append((*item, c["text"]))

    labels: list[Label] = []
    for direction, chars in by_dir.items():
        chars.sort(key=lambda t: (round(t[0], 1), t[1]))
        rows: list[list[tuple[float, float, float, float, float, str]]] = []
        for ch in chars:
            row = rows[-1] if rows else None
            if row and abs(ch[0] - row[0][0]) <= 0.3 * max(ch[4], row[0][4]):
                row.append(ch)
            else:
                rows.append([ch])
        for row in rows:
            row.sort(key=lambda t: t[1])
            run = [row[0]]
            text = row[0][5]
            for ch in row[1:]:
                gap = ch[1] - run[-1][2]
                size = max(ch[4], run[-1][4])
                if gap > GAP_SPLIT * size:
                    labels.append(_label(run, text, direction))
                    run, text = [ch], ch[5]
                    continue
                text += (" " if gap > GAP_SPACE * size else "") + ch[5]
                run.append(ch)
            labels.append(_label(run, text, direction))
    return labels


def _label(
    run: list[tuple[float, float, float, float, float, str]], text: str, direction: Direction
) -> Label:
    return Label(
        text=text,
        direction=direction,
        a0=min(c[1] for c in run),
        a1=max(c[2] for c in run),
        base=statistics.median(c[0] for c in run),
        perp=statistics.median(c[3] for c in run),
        height=max(c[4] for c in run),
    )


def _segments(page: Any) -> list[Segment]:
    h = float(page.height)
    out = []
    for line in page.lines:
        pts = line["pts"]
        for (x0, y0), (x1, y1) in itertools.pairwise(pts):
            out.append(Segment(x0, h - y0, x1, h - y1))
    return out
