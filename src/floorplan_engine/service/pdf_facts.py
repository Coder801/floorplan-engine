"""Факты из PDF без LLM: вход команды `pdf-facts` и анализатора.

Разбор живёт в facts/: адаптер формата (facts/vector.py) даёт примитивы страницы
(facts/primitives.py), общий разбор (facts/analysis.py) находит по ним размеры, масштаб,
цепочки и надписи и пишет выжимку для модели.
"""

from __future__ import annotations

import json
from pathlib import Path

from floorplan_engine.service.facts.analysis import PageFacts, page_facts, render, to_dict
from floorplan_engine.service.facts.vector import read_pdf

__all__ = ["PageFacts", "describe", "describe_json", "extract", "render"]


def extract(path: Path, name: str | None = None) -> list[PageFacts]:
    return [page_facts(sheet) for sheet in read_pdf(path, name)]


def describe(path: Path, name: str | None = None) -> str:
    """Факты одного PDF текстом; ошибка разбора — тоже текстом, анализ не падает."""
    try:
        return render(extract(path, name))
    except Exception as exc:  # pdfminer бросает разное на битых файлах
        return f"### {name or path.name}\nPDF не разобран: {exc}\n"


def describe_json(path: Path, name: str | None = None) -> str:
    """Те же факты в JSON: список страниц (to_dict)."""
    pages = [to_dict(f) for f in extract(path, name)]
    return json.dumps(pages, ensure_ascii=False, indent=1)
