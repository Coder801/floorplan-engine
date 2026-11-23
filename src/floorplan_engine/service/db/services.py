"""Services of a project (decision 2026-11-23, docs/database.md, «Сервисы проекта»): which
sections of the work the flat gets — the admin ticks them in the admin page, the viewer hides
the sections of the services that are off.

The catalog is ordered and its keys are machine ones: electrical (floor heating is part of it),
plumbing, demolition (mounting and demolition — not built yet: the tick exists, the build and
the viewer ignore it). Project.services is None for all services: projects made before the
column lose nothing.
"""

from __future__ import annotations

from collections.abc import Iterable

SERVICES: tuple[str, ...] = ("electrical", "plumbing", "demolition")


def normalize(services: Iterable[str] | None) -> list[str]:
    """The enabled services in catalog order: None — all; unknown keys are dropped."""
    if services is None:
        return list(SERVICES)
    chosen = set(services)
    return [s for s in SERVICES if s in chosen]


def unknown(services: Iterable[str]) -> list[str]:
    """Keys that are not in the catalog, in the order given, without repeats."""
    return list(dict.fromkeys(s for s in services if s not in SERVICES))
