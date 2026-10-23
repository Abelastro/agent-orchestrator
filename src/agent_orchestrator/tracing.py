"""Lightweight structured tracing.

A :class:`Tracer` collects :class:`Span` objects (with nested events) emitted
while a workflow runs. Traces are exportable as plain dicts or JSON and are
fully in-memory and dependency-free.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from pydantic import BaseModel, ConfigDict, Field


class Event(BaseModel):
    """A timestamped point-in-time event attached to a span or the tracer."""

    name: str
    timestamp: float
    attributes: dict[str, Any] = Field(default_factory=dict)


class Span(BaseModel):
    """A named interval of work with arbitrary attributes and child events."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    start: float
    end: float | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[Event] = Field(default_factory=list)

    @property
    def duration(self) -> float | None:
        """Return the span duration in seconds, or ``None`` if unfinished."""

        if self.end is None:
            return None
        return self.end - self.start


class Tracer:
    """Collects spans and events for a single process/session."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.time
        self.spans: list[Span] = []
        self.events: list[Event] = []

    def start_span(self, name: str, **attributes: Any) -> Span:
        """Create and register a new open span."""

        span = Span(name=name, start=self._clock(), attributes=dict(attributes))
        self.spans.append(span)
        return span

    def end_span(self, span: Span) -> Span:
        """Close a span, recording its end time."""

        span.end = self._clock()
        return span

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[Span]:
        """Context manager that opens and closes a span."""

        span = self.start_span(name, **attributes)
        try:
            yield span
        finally:
            self.end_span(span)

    def event(self, name: str, *, span: Span | None = None, **attributes: Any) -> Event:
        """Record an event, nested under ``span`` when provided."""

        event = Event(name=name, timestamp=self._clock(), attributes=dict(attributes))
        if span is not None:
            span.events.append(event)
        else:
            self.events.append(event)
        return event

    def reset(self) -> None:
        """Clear all collected spans and events."""

        self.spans.clear()
        self.events.clear()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the trace."""

        return {
            "spans": [span.model_dump(mode="json") for span in self.spans],
            "events": [event.model_dump(mode="json") for event in self.events],
        }

    def to_json(self, *, indent: int | None = None) -> str:
        """Serialize the trace to JSON."""

        return json.dumps(self.to_dict(), indent=indent, default=str)

    def find_span(self, name: str) -> Span | None:
        """Return the first span with the given name, if any."""

        for span in self.spans:
            if span.name == name:
                return span
        return None
