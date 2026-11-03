"""PDF facts without an LLM: the input of the `pdf-facts` command and of the analyzer.

Parsing lives in facts/: a format adapter (facts/vector.py) produces page primitives
(facts/primitives.py), the shared analysis (facts/analysis.py) finds dimensions, scale, chains
and labels in them and writes the digest for the model.
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
    """Facts of one PDF as text; a parse error is text too, the analysis does not fail."""
    try:
        return render(extract(path, name))
    except Exception as exc:  # pdfminer raises all sorts of things on broken files
        return f"### {name or path.name}\nPDF не разобран: {exc}\n"


def describe_json(path: Path, name: str | None = None) -> str:
    """The same facts as JSON: a list of pages (to_dict)."""
    pages = [to_dict(f) for f in extract(path, name)]
    return json.dumps(pages, ensure_ascii=False, indent=1)
