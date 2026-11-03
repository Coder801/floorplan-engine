---
name: verify
description: Full check of Shtroba changes without an LLM and without looking at images: tests, types, linter, PDF digest regression and sheet layout checked by code. Use it before saying a change is done.
---

# Checking changes

1. Code. The service database tests need Postgres, so run `docker compose up -d db` first; without
   it they are skipped, and `TEST_REQUIRE_DB=1` turns the skip into an error, so always run it that
   way:
   ```bash
   docker compose up -d db
   TEST_REQUIRE_DB=1 uv run pytest -q && uv run mypy && uv run ruff check . && uv run ruff format --check . && uv run lint-imports
   ```
   `lint-imports` checks the package layers and import bans (contracts in `pyproject.toml`).
   If the frontend (`web/`) changed, also run the types, tests and build (into `web/dist`):
   ```bash
   cd web && npm run check && npm test && npm run build
   ```
2. If source parsing changed (`service/facts/`), the Markdown digest of the vector PDFs must match
   the reference from before the change (save the reference in the scratchpad before editing):
   ```bash
   for f in projects/*/source/*.pdf; do uv run floorplan-engine pdf-facts "$f"; done > after.md
   diff before.md after.md
   ```
3. If sheets changed (`sheets/document.py`, tables, legend, title block), build the projects and
   check the layout with code: paper size, scale, nothing overflowing or lying on top of the plan:
   ```bash
   uv run floorplan-engine build projects/<name>
   uv run python scripts/check_layout.py <name> [<name>…]
   ```
   Open sheet images (`render-artifact`) only if the user asks or code cannot find the problem: it
   is expensive.
4. Report the result: what was checked, what matched, what did not. Do not say "done" if a step was
   skipped.
