"""Tests for structured tracing."""

from __future__ import annotations

import json

from agent_orchestrator.tracing import Tracer
from conftest import FakeClock


def test_span_records_start_end_and_duration():
    tracer = Tracer(clock=FakeClock(start=0.0, step=1.0))
    with tracer.span("work") as span:
        pass
    assert span.start == 1.0
    assert span.end == 2.0
    assert span.duration == 1.0
    assert tracer.spans == [span]


def test_span_attributes_recorded():
    tracer = Tracer()
    with tracer.span("work", step="a", tool="echo") as span:
        pass
    assert span.attributes == {"step": "a", "tool": "echo"}


def test_event_attached_to_span():
    tracer = Tracer()
    with tracer.span("work") as span:
        tracer.event("retry", span=span, attempt=1)
    assert len(span.events) == 1
    assert span.events[0].name == "retry"
    assert span.events[0].attributes == {"attempt": 1}


def test_global_event_without_span():
    tracer = Tracer()
    tracer.event("note", value=42)
    assert tracer.events[0].name == "note"
    assert tracer.events[0].attributes == {"value": 42}


def test_to_dict_and_json():
    tracer = Tracer()
    with tracer.span("work") as span:
        tracer.event("done", span=span)
    data = tracer.to_dict()
    assert data["spans"][0]["name"] == "work"
    payload = json.loads(tracer.to_json())
    assert payload["spans"][0]["events"][0]["name"] == "done"


def test_reset_clears_state():
    tracer = Tracer()
    tracer.start_span("a")
    tracer.event("e")
    tracer.reset()
    assert tracer.spans == []
    assert tracer.events == []


def test_find_span():
    tracer = Tracer()
    with tracer.span("first"):
        pass
    with tracer.span("second"):
        pass
    assert tracer.find_span("second").name == "second"
    assert tracer.find_span("missing") is None


def test_unfinished_span_has_no_duration():
    tracer = Tracer()
    span = tracer.start_span("open")
    assert span.duration is None
