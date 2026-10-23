"""Shared pytest fixtures and helpers for the orchestrator test suite.

Everything here is deterministic: clocks are fake, sleeps are recorded rather
than performed, and randomness is injected. No network access is required.
"""

from __future__ import annotations

import pytest

from agent_orchestrator.engine import Engine
from agent_orchestrator.models import RetryPolicy, StepSpec, WorkflowSpec
from agent_orchestrator.registry import ToolRegistry
from agent_orchestrator.store import SQLiteStore


class FakeClock:
    """Monotonic-ish fake clock advancing a fixed step on each call."""

    def __init__(self, start: float = 1000.0, step: float = 1.0) -> None:
        self.now = start
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


class FakeSleeper:
    """Records requested sleep durations instead of sleeping."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, delay: float) -> None:
        self.calls.append(delay)

    @property
    def total(self) -> float:
        return sum(self.calls)


@pytest.fixture
def store(tmp_path):
    s = SQLiteStore(str(tmp_path / "orch.db"))
    yield s
    s.close()


@pytest.fixture
def registry():
    return ToolRegistry()


@pytest.fixture
def sleeper():
    return FakeSleeper()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def make_engine(registry, store, sleeper, clock):
    def _make(**kwargs):
        kwargs.setdefault("registry", registry)
        kwargs.setdefault("store", store)
        kwargs.setdefault("sleep_fn", sleeper)
        kwargs.setdefault("clock", clock)
        kwargs.setdefault("rng", lambda: 0.0)
        return Engine(**kwargs)

    return _make


def step(
    step_id: str,
    tool: str,
    *,
    inputs: dict | None = None,
    depends_on: list[str] | None = None,
    retry: RetryPolicy | None = None,
    requires_approval: bool = False,
    timeout: float | None = None,
) -> StepSpec:
    """Convenience builder for :class:`StepSpec`."""

    return StepSpec(
        id=step_id,
        tool=tool,
        inputs=inputs or {},
        depends_on=depends_on or [],
        retry=retry or RetryPolicy(),
        requires_approval=requires_approval,
        timeout=timeout,
    )


def workflow(name: str, *steps: StepSpec) -> WorkflowSpec:
    """Convenience builder for :class:`WorkflowSpec`."""

    return WorkflowSpec(name=name, steps=list(steps))
