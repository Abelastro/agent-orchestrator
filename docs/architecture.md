# Architecture

The Agent Orchestrator is a small, dependency-light engine for running
multi-step AI/tool workflows **reliably**. It deliberately separates pure
computation (graph logic, backoff math, models) from side-effecting
orchestration (the engine, the store, the API) so each piece is independently
testable and deterministic.

## Layering

```
                ┌────────────────────────────────────────────┐
                │                 Interfaces                  │
                │   cli.py            api/app.py              │
                └───────────────┬───────────────┬────────────┘
                                │               │
                        ┌───────▼───────────────▼───────┐
                        │            engine.py          │
                        │  DAG walk · retries · HITL ·  │
                        │  checkpoints · tracing spans  │
                        └───┬───────┬───────┬───────┬───┘
                            │       │       │       │
             ┌──────────────▼─┐ ┌───▼────┐ ┌▼─────┐ ┌▼────────────┐
             │ dag.py         │ │retry.py│ │hitl. │ │ tracing.py  │
             │ topo · ready   │ │backoff │ │py    │ │ spans/events│
             └────────────────┘ └────────┘ └──────┘ └─────────────┘
                            │
                    ┌───────▼─────────┐     ┌────────────────────┐
                    │ registry.py     │     │ store/sqlite_store │
                    │ @tool resolve   │     │ durable checkpoints│
                    └─────────────────┘     └────────────────────┘
                            │
                    ┌───────▼─────────┐
                    │ models.py       │
                    │ pydantic DAG    │
                    └─────────────────┘
```

## Execution model

1. `Engine.run()` validates the DAG (`topological_sort`, which detects cycles and
   unknown dependencies) and creates a `RunRecord` with one `StepRecord` per
   step. The workflow is snapshotted into the store.
2. `_advance()` repeatedly resolves the set of *ready* steps using
   `dag.ready_steps` (all dependencies `SUCCEEDED`). Execution is sequential and
   deterministic: ties are broken by declaration order.
3. Steps whose dependencies `FAILED` or `SKIPPED` are transitioned to `SKIPPED`
   by `dag.blocked_steps`, cascading through the graph.
4. A step with `requires_approval` that has not been approved halts the run in
   `RunStatus.AWAITING_APPROVAL`. `Engine.approve()` flips the flag and resumes;
   `Engine.reject()` marks the step `SKIPPED` and skips its transitive
   dependents (`hitl.transitive_dependents`).
5. Every state transition is persisted immediately (`_persist`), so a crash at
   any point leaves a durable checkpoint.

## Durability and resume

The store persists three tables: `workflows`, `runs` (metadata + a JSON snapshot
of the workflow, so a run is self-contained even if the spec is edited later)
and `step_records` (per-step checkpoints). `Engine.resume(run_id)` reloads the
run, resets non-terminal-by-failure states (`RUNNING`, `FAILED`, `SKIPPED`) back
to `PENDING`, and continues from the last good checkpoint. A succeeded run is a
no-op on resume, making resume idempotent.

## Retries

`retry.compute_backoff` is a pure function of `(attempt, RetryPolicy, rng)`.
Exponential growth is capped at `max_delay` and optionally reduced by
multiplicative jitter. The engine injects `sleep_fn`, `clock` and `rng`, so
tests exercise the full retry path without real time or randomness.

## Timeouts

When a step declares `timeout`, the tool is dispatched to a worker thread and
awaited with `Future.result(timeout=...)`. A timeout surfaces as a normal
exception, so it participates in the retry policy. The worker executor is shut
down without waiting so a hung tool cannot block the engine.

## Tracing

`Tracer.span()` emits a span per run and per step; retries and failures are
recorded as nested events. Traces export to dicts/JSON and are kept entirely
in-memory.

## Determinism and testing

No network, no real sleeps and no global randomness are required anywhere in
the runtime path used by the test suite. Clocks, sleepers and RNGs are injected,
which keeps the 90+ tests fast and flake-free.
