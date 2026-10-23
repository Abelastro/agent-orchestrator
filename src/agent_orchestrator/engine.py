"""The durable workflow execution engine.

The engine walks a workflow DAG, executing ready steps sequentially. For each
step it applies the configured retry policy, records state transitions, writes a
checkpoint after every transition and emits tracing spans/events. It supports
resuming a failed or paused run and human-in-the-loop approval gates.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import random
import time
import uuid
from typing import Any, Callable

from .config import Settings, get_settings
from .dag import blocked_steps, ready_steps, topological_sort
from .hitl import transitive_dependents
from .models import (
    RetryPolicy,
    RunRecord,
    RunStatus,
    StepRecord,
    StepSpec,
    StepState,
    WorkflowSpec,
)
from .registry import DEFAULT_REGISTRY, ToolNotFoundError, ToolRegistry
from .retry import compute_backoff
from .store.sqlite_store import SQLiteStore
from .tracing import Tracer


class OrchestratorError(Exception):
    """Base class for orchestrator errors."""


class WorkflowError(OrchestratorError):
    """Raised for invalid workflow operations (e.g. bad approval target)."""


class NotFoundError(OrchestratorError):
    """Raised when a requested run cannot be found."""


def _run_awaitable(awaitable: Any) -> Any:
    """Run an awaitable even when called from within a running event loop."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(awaitable)).result()


Clock = Callable[[], float]
Sleeper = Callable[[float], None]
RandomFn = Callable[[], float]


class Engine:
    """Executes :class:`WorkflowSpec` objects as durable runs."""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        store: SQLiteStore | None = None,
        tracer: Tracer | None = None,
        *,
        sleep_fn: Sleeper | None = None,
        clock: Clock | None = None,
        rng: RandomFn | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.registry = registry if registry is not None else DEFAULT_REGISTRY
        self.store = store
        self.tracer = tracer or Tracer(clock=clock)
        self._sleep: Sleeper = sleep_fn or time.sleep
        self._clock: Clock = clock or time.time
        self._rng: RandomFn = rng or random.random

    # -- public API --------------------------------------------------------

    def run(self, workflow: WorkflowSpec, run_id: str | None = None) -> RunRecord:
        """Create and execute a new run for ``workflow``."""

        topological_sort(workflow.steps)
        now = self._clock()
        run = RunRecord(
            id=run_id or uuid.uuid4().hex,
            workflow=workflow,
            status=RunStatus.RUNNING,
            records={step.id: StepRecord(step_id=step.id) for step in workflow.steps},
            created_at=now,
            updated_at=now,
        )
        if self.store is not None:
            self.store.save_workflow(workflow)
        self._persist(run)
        with self.tracer.span(f"run:{run.id}", workflow=workflow.name):
            return self._advance(run)

    def get_run(self, run_id: str) -> RunRecord:
        """Load a run by id."""

        return self._load(run_id)

    def resume(self, run_id: str) -> RunRecord:
        """Resume a failed or paused run from its last checkpoint."""

        run = self._load(run_id)
        if run.status is RunStatus.SUCCEEDED:
            return run
        for rec in run.records.values():
            if rec.state in (
                StepState.RUNNING,
                StepState.FAILED,
                StepState.SKIPPED,
            ):
                rec.state = StepState.PENDING
                rec.error = None
        run.status = RunStatus.RUNNING
        self._persist(run)
        with self.tracer.span(f"run:{run.id}", workflow=run.workflow.name, resumed=True):
            return self._advance(run)

    def pause(self, run_id: str) -> RunRecord:
        """Pause a run; it can later be resumed."""

        run = self._load(run_id)
        run.status = RunStatus.PAUSED
        self._persist(run)
        return run

    def approve(self, run_id: str, step_id: str) -> RunRecord:
        """Approve an awaiting step and continue the run."""

        run = self._load(run_id)
        rec = self._require_step(run, step_id)
        if rec.state is not StepState.AWAITING_APPROVAL:
            raise WorkflowError(
                f"step '{step_id}' is not awaiting approval (state={rec.state.value})"
            )
        rec.approved = True
        rec.state = StepState.PENDING
        run.status = RunStatus.RUNNING
        self._persist(run)
        return self._advance(run)

    def reject(self, run_id: str, step_id: str) -> RunRecord:
        """Reject an awaiting step; it and its dependents are skipped."""

        run = self._load(run_id)
        rec = self._require_step(run, step_id)
        if rec.state is not StepState.AWAITING_APPROVAL:
            raise WorkflowError(
                f"step '{step_id}' is not awaiting approval (state={rec.state.value})"
            )
        rec.approved = False
        rec.state = StepState.SKIPPED
        rec.finished_at = self._clock()
        self._skip_dependents(run, step_id)
        run.status = RunStatus.RUNNING
        self._persist(run)
        return self._advance(run)

    # -- execution loop ----------------------------------------------------

    def _advance(self, run: RunRecord) -> RunRecord:
        steps = run.workflow.steps
        while True:
            states = run.states()

            blocked = blocked_steps(steps, states)
            if blocked:
                for step_id in blocked:
                    rec = run.records[step_id]
                    rec.state = StepState.SKIPPED
                    if rec.finished_at is None:
                        rec.finished_at = self._clock()
                self._persist(run)
                continue

            ready = ready_steps(steps, states)
            if not ready:
                break

            step = run.workflow.step(ready[0])
            rec = run.records[step.id]
            if step.requires_approval and rec.approved is not True:
                rec.state = StepState.AWAITING_APPROVAL
                run.status = RunStatus.AWAITING_APPROVAL
                self._persist(run)
                return run

            self._execute_step(run, step)
            if run.records[step.id].state is StepState.FAILED:
                self._skip_dependents(run, step.id)
                run.status = RunStatus.FAILED
                self._persist(run)
                return run

        run.status = self._final_status(run)
        self._persist(run)
        return run

    def _final_status(self, run: RunRecord) -> RunStatus:
        states = [rec.state for rec in run.records.values()]
        if any(state is StepState.FAILED for state in states):
            return RunStatus.FAILED
        if any(state is StepState.AWAITING_APPROVAL for state in states):
            return RunStatus.AWAITING_APPROVAL
        if all(state in (StepState.SUCCEEDED, StepState.SKIPPED) for state in states):
            return RunStatus.SUCCEEDED
        return RunStatus.FAILED

    def _execute_step(self, run: RunRecord, step: StepSpec) -> None:
        rec = run.records[step.id]
        rec.state = StepState.RUNNING
        rec.started_at = self._clock()
        rec.error = None

        policy: RetryPolicy = step.retry
        with self.tracer.span(f"step:{step.id}", step=step.id, tool=step.tool) as span:
            try:
                fn = self.registry.resolve(step.tool)
            except ToolNotFoundError as exc:
                rec.state = StepState.FAILED
                rec.error = str(exc)
                rec.finished_at = self._clock()
                self.tracer.event("tool_not_found", span=span, tool=step.tool)
                self._persist(run)
                return

            attempts = max(1, policy.max_attempts)
            for attempt in range(1, attempts + 1):
                rec.attempts = attempt
                try:
                    output = self._call_tool(fn, step)
                except Exception as exc:  # noqa: BLE001 - surfaced as step error
                    rec.error = f"{type(exc).__name__}: {exc}"
                    self.tracer.event(
                        "attempt_failed", span=span, attempt=attempt, error=rec.error
                    )
                    if attempt < attempts:
                        delay = compute_backoff(attempt, policy, self._rng)
                        self.tracer.event(
                            "retry", span=span, attempt=attempt, delay=delay
                        )
                        self._sleep(delay)
                    else:
                        rec.state = StepState.FAILED
                        rec.finished_at = self._clock()
                        self._persist(run)
                        return
                else:
                    rec.state = StepState.SUCCEEDED
                    rec.output = output
                    rec.finished_at = self._clock()
                    self.tracer.event("succeeded", span=span, attempt=attempt)
                    self._persist(run)
                    return

    def _call_tool(self, fn: Callable[..., Any], step: StepSpec) -> Any:
        if step.timeout is not None:
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = executor.submit(self._invoke, fn, step.inputs)
            try:
                return future.result(timeout=step.timeout)
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        return self._invoke(fn, step.inputs)

    def _invoke(self, fn: Callable[..., Any], inputs: dict[str, Any]) -> Any:
        result = fn(**inputs)
        if inspect.isawaitable(result):
            return _run_awaitable(result)
        return result

    # -- helpers -----------------------------------------------------------

    def _skip_dependents(self, run: RunRecord, step_id: str) -> None:
        for dependent in transitive_dependents(run.workflow.steps, step_id):
            rec = run.records[dependent]
            if rec.state is StepState.PENDING:
                rec.state = StepState.SKIPPED
                if rec.finished_at is None:
                    rec.finished_at = self._clock()

    def _persist(self, run: RunRecord) -> None:
        run.updated_at = self._clock()
        if self.store is not None:
            self.store.save_run(run)

    def _load(self, run_id: str) -> RunRecord:
        if self.store is None:
            raise NotFoundError("no store configured; cannot load run")
        run = self.store.load_run(run_id)
        if run is None:
            raise NotFoundError(f"run not found: {run_id}")
        return run

    @staticmethod
    def _require_step(run: RunRecord, step_id: str) -> StepRecord:
        if step_id not in run.records:
            raise WorkflowError(f"run '{run.id}' has no step '{step_id}'")
        return run.records[step_id]
