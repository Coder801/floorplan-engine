"""Debug trace of routing: what the search decided and why, for `floorplan-engine trace`.

Off by default: outside recording() emit() and scope() do nothing, so a build gives the same
files at the same speed. Inside recording() every emit() adds an Event with the labels of the
scope() blocks around it (line id, group, routing round), so a router deep in routing.py does
not need to know which line it routes.

Payloads are typed dataclasses defined next to their producers (routing.RouteTrace,
box_spots.BoxMove); a reader picks them with isinstance.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import MappingProxyType

Labels = Mapping[str, object]

_EMPTY: Labels = MappingProxyType({})
_EVENTS: ContextVar[list[Event] | None] = ContextVar("trace_events", default=None)
_LABELS: ContextVar[Labels] = ContextVar("trace_labels", default=_EMPTY)


@dataclass(frozen=True)
class Event:
    """One recorded decision: the labels of its scope and what was decided."""

    labels: Labels
    payload: object


def on() -> bool:
    """Recording is on: worth building a payload."""
    return _EVENTS.get() is not None


@contextmanager
def recording() -> Iterator[list[Event]]:
    """Record events until the block ends; the list fills as the code runs. A nested block
    records into the outer list."""
    events = _EVENTS.get()
    if events is not None:
        yield events
        return
    events = []
    token = _EVENTS.set(events)
    try:
        yield events
    finally:
        _EVENTS.reset(token)


@contextmanager
def scope(**labels: object) -> Iterator[None]:
    """Labels for the events emitted inside the block, on top of the outer ones."""
    if not on():
        yield
        return
    token = _LABELS.set(MappingProxyType({**_LABELS.get(), **labels}))
    try:
        yield
    finally:
        _LABELS.reset(token)


def emit(payload: object) -> None:
    """Record payload with the current labels; nothing outside recording()."""
    events = _EVENTS.get()
    if events is not None:
        events.append(Event(_LABELS.get(), payload))
