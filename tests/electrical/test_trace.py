"""Debug trace: nothing is recorded outside recording(), labels of nested scopes add up."""

from __future__ import annotations

from floorplan_engine.electrical import trace


def test_off_by_default_records_nothing() -> None:
    assert not trace.on()
    with trace.scope(line="wire_1"):
        trace.emit("x")  # no recording: dropped
    with trace.recording() as events:
        pass
    assert events == []


def test_scopes_label_the_events_and_unwind() -> None:
    with trace.recording() as events:
        assert trace.on()
        with trace.scope(round=0):
            with trace.scope(line="wire_1", round=1):
                trace.emit("a")
            trace.emit("b")
        trace.emit("c")
    assert [(dict(e.labels), e.payload) for e in events] == [
        ({"round": 1, "line": "wire_1"}, "a"),
        ({"round": 0}, "b"),
        ({}, "c"),
    ]
    assert not trace.on()


def test_nested_recording_shares_the_outer_list() -> None:
    with trace.recording() as outer, trace.recording() as inner:
        trace.emit("a")
    assert inner is outer and len(outer) == 1
