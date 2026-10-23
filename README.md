# Agent Orchestrator

A durable agentic workflow engine for running multi-step AI workflows with
dependency-aware scheduling, retries, checkpoint/resume, human-in-the-loop
approval, and distributed tracing.

## Why this exists

LLM agents fail in the middle of long workflows. Naive orchestration loses all
progress when a tool call times out, a model returns malformed JSON, or a human
reviewer is slow to approve. This project treats agent execution as a durable
workflow: every step is checkpointed, retried with backoff, and observable.

## Features

- **DAG-based workflows** — declare steps and dependencies; the engine computes
  a valid execution order and detects cycles.
- **Durable state** — SQLite-backed run store with per-step status so a crashed
  process can resume where it stopped.
- **Retries with backoff** — configurable attempts, delays, and retryable error
  classification.
- **Human-in-the-loop** — steps can pause execution and wait for an approval or
  rejection decision.
- **Tracing** — structured spans for every run and step, exposed through the API.
- **REST API + CLI** — register workflows, start runs, inspect status, approve
  pending steps.
- **Strict models** — Pydantic schemas validate workflow definitions and run
  state at the boundary.

## Architecture

```
Workflow definition (DAG)
        │
        ▼
   Registry ──► Engine ──► Step executor
        │           │           │
        │           ├──► Retry policy
        │           ├──► HITL gate
        │           └──► Tracer
        ▼
   SQLite run store (checkpoint / resume)
        │
        ▼
   FastAPI + CLI
```

See [`docs/architecture.md`](docs/architecture.md) for component detail.

## Project layout

```
agent-orchestrator/
├── src/agent_orchestrator/
│   ├── api/app.py          # FastAPI application
│   ├── cli.py              # Command-line interface
│   ├── config.py           # Settings
│   ├── dag.py              # Graph validation + topological order
│   ├── engine.py           # Execution loop
│   ├── hitl.py             # Human-in-the-loop gate
│   ├── models.py           # Pydantic schemas
│   ├── registry.py         # Workflow registry
│   ├── retry.py            # Retry/backoff policy
│   ├── store/              # SQLite persistence
│   └── tracing.py          # Span recording
├── tests/                  # pytest suite
├── examples/               # Runnable demo workflow
└── docs/
```

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

### Run the demo

```bash
python3 examples/durable_demo.py
```

### Start the API

```bash
uvicorn agent_orchestrator.api.app:app --reload
```

### CLI

```bash
agent-orchestrator --help
```

## Testing

```bash
pytest
pytest --cov=agent_orchestrator --cov-report=term-missing
```

## Design notes

- **Idempotent steps.** The engine records completion before advancing, so a
  resumed run does not re-execute finished steps.
- **Bounded retries.** Retry classification distinguishes transient errors from
  permanent failures; permanent failures stop the run immediately.
- **Explicit HITL.** Approval state lives in the store, so a pending step
  survives process restarts.
- **Observable by default.** Every run emits spans that can be exported to any
  OpenTelemetry-compatible backend.

## Limitations

- Single-process executor; distributed workers are a future extension.
- SQLite store is intended for development and single-node deployments.
- Step payloads are JSON-serializable values only.

## License

MIT
