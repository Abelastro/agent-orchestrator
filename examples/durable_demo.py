"""Runnable demonstration of failure -> resume and human-in-the-loop approval.

Run with::

    python3 examples/durable_demo.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from agent_orchestrator import (
    Engine,
    RetryPolicy,
    StepSpec,
    Tracer,
    WorkflowSpec,
)
from agent_orchestrator.store import SQLiteStore
from agent_orchestrator.registry import ToolRegistry


def build_registry(flaky_state: dict[str, bool]) -> ToolRegistry:
    registry = ToolRegistry()

    def flaky_download(**_: object) -> str:
        if flaky_state["fail"]:
            raise RuntimeError("network blip")
        return "downloaded-payload"

    def approve_publish(**_: object) -> str:
        return "published"

    registry.register("download", flaky_download)
    registry.register("publish", approve_publish)
    return registry


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = SQLiteStore(str(Path(tmp) / "demo.db"))
        flaky_state = {"fail": True}
        engine = Engine(registry=build_registry(flaky_state), store=store, tracer=Tracer())

        workflow = WorkflowSpec(
            name="release",
            steps=[
                StepSpec(
                    id="download",
                    tool="download",
                    retry=RetryPolicy(max_attempts=1),
                ),
                StepSpec(
                    id="publish",
                    tool="publish",
                    depends_on=["download"],
                    requires_approval=True,
                ),
            ],
        )

        run = engine.run(workflow)
        print(f"[1] first attempt -> status={run.status.value}")
        for record in run.records.values():
            print(f"    {record.step_id}: {record.state.value} ({record.error})")

        print("[2] transient fault cleared, resuming...")
        flaky_state["fail"] = False
        run = engine.resume(run.id)
        print(f"    status={run.status.value}")

        print("[3] run is now blocked on human approval")
        run = engine.get_run(run.id)
        print(f"    status={run.status.value}")

        print("[4] approving 'publish'...")
        run = engine.approve(run.id, "publish")
        print(f"    status={run.status.value}")
        for record in run.records.values():
            print(f"    {record.step_id}: {record.state.value} -> {record.output}")

        print("[5] trace spans:")
        for span in engine.tracer.spans:
            print(f"    {span.name} duration={span.duration}")

        store.close()


if __name__ == "__main__":
    main()
