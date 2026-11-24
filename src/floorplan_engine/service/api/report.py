"""Estimate report for the PDF (epd/report.py): the page the PDF service prints.

GET /api/projects/{key}/result?parts=plan,material_rough,…&orientation=portrait
    the report as HTML (right `view`, as the sheets) from the latest build's .epd. No `parts`
    means all of them (`epd.report.PARTS`); `orientation` is the A4 page, portrait (default) or
    landscape — the same value goes to the PDF service. An unknown part or orientation is 400.
GET /api/projects/{key}/result.pdf?parts=…&orientation=…
    the same page printed to PDF by the external service (api/pdf.py), as a download named
    "<project> — <document>.pdf"; 503 without the service, 502 when it fails.
"""

from __future__ import annotations

import json
import zipfile
from typing import Any, cast
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, Response

from floorplan_engine.epd.report import (
    ORIENTATIONS,
    PARTS,
    Orientation,
    Part,
    parts_of,
    report_filename,
    report_html,
)
from floorplan_engine.service.api.pdf import render_pdf


def result_page(
    zf: zipfile.ZipFile, manifest: dict[str, Any], parts: str | None, orientation: str
) -> HTMLResponse:
    """The report of an open .epd (its manifest already checked, viewer_db.check_manifest)."""
    return HTMLResponse(_report(zf, manifest, _parts(parts), _orientation(orientation)))


def result_pdf(
    zf: zipfile.ZipFile, manifest: dict[str, Any], parts: str | None, orientation: str
) -> Response:
    """The same report as a PDF download."""
    chosen, side = _parts(parts), _orientation(orientation)
    name = report_filename(manifest, chosen)
    pdf = render_pdf(_report(zf, manifest, chosen, side), side, name)
    # The plain name for old clients: the real one when it is ASCII, otherwise a neutral one
    ascii_name = name if name.isascii() else "report.pdf"
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": disposition})


def _orientation(orientation: str) -> str:
    if orientation not in ORIENTATIONS:
        raise HTTPException(400, f"ориентация — одна из: {', '.join(ORIENTATIONS)}")
    return orientation


def _parts(parts: str | None) -> tuple[Part, ...]:
    try:
        return parts_of([p for p in parts.split(",") if p]) if parts is not None else PARTS
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _report(
    zf: zipfile.ZipFile, manifest: dict[str, Any], chosen: tuple[Part, ...], orientation: str
) -> str:
    """The report HTML: the pages it needs read from the .epd."""
    entry = next((p for p in manifest["pages"] if p.get("stage") == "wiring"), None)
    wiring = json.loads(zf.read(entry["file"])) if entry is not None else None
    panel = None
    if "panel" in chosen:
        page = next((p for p in manifest["pages"] if p.get("stage") == "panel"), None)
        panel = json.loads(zf.read(page["file"])).get("panel") if page is not None else None
    legend: list[dict[str, Any]] = []
    if "plan" in chosen:  # the point symbols for the plan legend: the electrical sheet legend
        page = next((p for p in manifest["pages"] if p.get("stage") == "electrical"), None)
        legend = json.loads(zf.read(page["file"])).get("legend", []) if page is not None else []
    return report_html(manifest, wiring, chosen, cast(Orientation, orientation), panel, legend)
