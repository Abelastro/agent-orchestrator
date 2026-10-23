"""Core domain models for workflows, runs and retries.

The models are intentionally pure data structures (Pydantic v2) so they can be
serialized to JSON for persistence and API transport without adapters.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StepState(str, Enum):
    """Lifecycle state of a single workflow step."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    AWAITING_APPROVAL = "awaiting_approval"


class RunStatus(str, Enum):
    """Overall lifecycle state of a workflow run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PAUSED = "paused"
    AWAITING_APPROVAL = "awaiting_approval"


TERMINAL_STEP_STATES: frozenset[StepState] = frozenset(
    {StepState.SUCCEEDED, StepState.FAILED, StepState.SKIPPED}
)


class RetryPolicy(BaseModel):
    """Retry/backoff configuration for a step.

    ``jitter`` is a fraction in ``[0, 1]`` applied multiplicatively to the
    computed delay: ``delay * (1 - jitter * rng())``.
    """

    model_config = ConfigDict(frozen=True)

    max_attempts: int = 3
    base_delay: float = 0.1
    max_delay: float = 5.0
    jitter: float = 0.0
    exponential: bool = True


class StepSpec(BaseModel):
    """Declarative specification of a single step in a workflow DAG."""

    model_config = ConfigDict(frozen=True)

    id: str
    tool: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    timeout: float | None = None
    requires_approval: bool = False


class WorkflowSpec(BaseModel):
    """A named DAG of :class:`StepSpec` nodes."""

    name: str
    steps: list[StepSpec] = Field(default_factory=list)

    def step(self, step_id: str) -> StepSpec:
        """Return the step with ``step_id`` or raise :class:`KeyError`."""

        for spec in self.steps:
            if spec.id == step_id:
                return spec
        raise KeyError(f"unknown step id: {step_id}")

    def step_ids(self) -> list[str]:
        """Return the list of step ids in declaration order."""

        return [spec.id for spec in self.steps]


class StepRecord(BaseModel):
    """Mutable execution record for one step within a run."""

    step_id: str
    state: StepState = StepState.PENDING
    output: Any = None
    error: str | None = None
    attempts: int = 0
    started_at: float | None = None
    finished_at: float | None = None
    approved: bool | None = None


class RunRecord(BaseModel):
    """A single workflow execution, including per-step records."""

    id: str
    workflow: WorkflowSpec
    status: RunStatus = RunStatus.PENDING
    records: dict[str, StepRecord] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    updated_at: float | None = None

    def states(self) -> dict[str, StepState]:
        """Return a mapping of step id to its current state."""

        return {step_id: rec.state for step_id, rec in self.records.items()}

    def record(self, step_id: str) -> StepRecord:
        """Return the :class:`StepRecord` for ``step_id`` or raise ``KeyError``."""

        return self.records[step_id]
