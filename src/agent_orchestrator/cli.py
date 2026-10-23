"""Command-line interface for the orchestrator.

Usage::

    python -m agent_orchestrator run examples/workflow.json
    python -m agent_orchestrator status <run_id>
    python -m agent_orchestrator resume <run_id>
    python -m agent_orchestrator list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .config import get_settings
from .engine import Engine, NotFoundError, OrchestratorError
from .models import RunRecord, WorkflowSpec
from .store.sqlite_store import SQLiteStore
from .tracing import Tracer


def _build_engine(db_path: str) -> Engine:
    store = SQLiteStore(db_path)
    return Engine(store=store, tracer=Tracer())


def _print_run(run: RunRecord, *, as_json: bool) -> None:
    if as_json:
        print(run.model_dump_json(indent=2))
        return
    print(f"run {run.id}")
    print(f"  workflow: {run.workflow.name}")
    print(f"  status:   {run.status.value}")
    for step in run.workflow.steps:
        rec = run.records.get(step.id)
        state = rec.state.value if rec else "missing"
        line = f"  - {step.id} [{step.tool}] -> {state}"
        if rec and rec.attempts:
            line += f" (attempts={rec.attempts})"
        if rec and rec.error:
            line += f" error={rec.error}"
        print(line)


def _load_workflow(path: str) -> WorkflowSpec:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return WorkflowSpec.model_validate(data)


def _cmd_run(args: argparse.Namespace, engine: Engine) -> int:
    workflow = _load_workflow(args.workflow)
    run = engine.run(workflow, run_id=args.run_id)
    _print_run(run, as_json=args.json)
    return 0 if run.status.value in {"succeeded"} else 1


def _cmd_status(args: argparse.Namespace, engine: Engine) -> int:
    try:
        run = engine.get_run(args.run_id)
    except NotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _print_run(run, as_json=args.json)
    return 0


def _cmd_resume(args: argparse.Namespace, engine: Engine) -> int:
    try:
        run = engine.resume(args.run_id)
    except NotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _print_run(run, as_json=args.json)
    return 0 if run.status.value == "succeeded" else 1


def _cmd_list(args: argparse.Namespace, engine: Engine) -> int:
    assert engine.store is not None
    runs = engine.store.list_runs()
    if args.json:
        print(json.dumps([r.model_dump(mode="json") for r in runs], indent=2, default=str))
        return 0
    if not runs:
        print("no runs")
        return 0
    for run in runs:
        print(f"{run.id}\t{run.workflow.name}\t{run.status.value}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser."""

    settings = get_settings()
    parser = argparse.ArgumentParser(
        prog="agent_orchestrator",
        description="Durable agentic workflow orchestrator.",
    )
    parser.add_argument(
        "--db",
        default=settings.db_path,
        help=f"SQLite database path (default: {settings.db_path})",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON output")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run a workflow from a JSON file")
    run_p.add_argument("workflow", help="path to a workflow JSON file")
    run_p.add_argument("--run-id", default=None, help="explicit run id")
    run_p.set_defaults(func=_cmd_run)

    status_p = sub.add_parser("status", help="show a run's status")
    status_p.add_argument("run_id")
    status_p.set_defaults(func=_cmd_status)

    resume_p = sub.add_parser("resume", help="resume a failed or paused run")
    resume_p.add_argument("run_id")
    resume_p.set_defaults(func=_cmd_resume)

    list_p = sub.add_parser("list", help="list runs")
    list_p.set_defaults(func=_cmd_list)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)
    engine = _build_engine(args.db)
    try:
        return int(args.func(args, engine))
    except OrchestratorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        if engine.store is not None:
            engine.store.close()


def to_jsonable(value: Any) -> Any:
    """Best-effort conversion of pydantic models to JSON-compatible data."""

    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value
