"""The estimate report as PDF: the HTML of the report goes to the external PDF service.

The service (pdf-generator-service, Playwright) prints a ready page: `POST /generate-pdf-html`
with `{html, orientation, filename}` → `application/pdf`. It gets the page itself, not its
address: the report is behind the login, and the service browser has no session. The page is
the same as `GET …/result` (epd/report.py, self-contained: fonts embedded, no scripts or
external files), so the PDF is what the viewer opens.

The service address is SHTROBA_PDF_URL (e.g. http://127.0.0.1:8090 locally, the Railway URL on
the server); without it the PDF route answers 503, the HTML report still works.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

import httpx
from fastapi import HTTPException

PDF_URL_ENV = "SHTROBA_PDF_URL"
TIMEOUT_S = 120.0  # a report of a dozen A4 pages prints in about 5 s; the first start is slower


def render_pdf(
    html: str, orientation: str, filename: str, env: Mapping[str, str] | None = None
) -> bytes:
    """PDF of the report page from the service; 503 — no service set, 502 — it failed."""
    base = (os.environ if env is None else env).get(PDF_URL_ENV, "").strip().rstrip("/")
    if not base:
        raise HTTPException(503, f"PDF-сервис не настроен: задайте {PDF_URL_ENV}")
    body = {"html": html, "orientation": orientation, "filename": filename}
    try:
        response = httpx.post(f"{base}/generate-pdf-html", json=body, timeout=TIMEOUT_S)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"PDF-сервис недоступен: {exc}") from exc
    if response.status_code != 200 or not response.content.startswith(b"%PDF"):
        raise HTTPException(502, f"PDF-сервис не сделал PDF: ответ {response.status_code}")
    return response.content
