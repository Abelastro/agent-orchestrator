"""Tests for the SQLite persistence layer."""

from __future__ import annotations

from agent_orchestrator.models import (
    RunRecord,
    RunStatus,
    StepRecord,
    StepSpec,
    StepState,
    WorkflowSpec,
)


def _workflow(name: str = "wf") -> WorkflowSpec:
    return WorkflowSpec(name=name, steps=[StepSpec(id="a", tool="echo")])


def _run(run_id: str = "r1", name: str = "wf") -> RunRecord:
    return RunRecord(
        id=run_id,
        workflow=_workflow(name),
        status=RunStatus.RUNNING,
        records={
            "a": StepRecord(
                step_id="a",
                state=StepState.SUCCEEDED,
                output={"value": 7},
                attempts=2,
                started_at=1.0,
                finished_at=2.0,
            )
        },
        created_at=100.0,
        updated_at=200.0,
    )


def test_save_and_load_workflow(store):
    store.save_workflow(_workflow())
    loaded = store.load_workflow("wf")
    assert loaded is not None
    assert loaded.name == "wf"
    assert loaded.step_ids() == ["a"]


def test_load_missing_workflow_returns_none(store):
    assert store.load_workflow("nope") is None


def test_list_workflows_sorted(store):
    store.save_workflow(_workflow("b"))
    store.save_workflow(_workflow("a"))
    assert [wf.name for wf in store.list_workflows()] == ["a", "b"]


def test_save_workflow_is_upsert(store):
    store.save_workflow(_workflow("wf"))
    updated = WorkflowSpec(
        name="wf",
        steps=[StepSpec(id="a", tool="echo"), StepSpec(id="b", tool="add")],
    )
    store.save_workflow(updated)
    assert store.load_workflow("wf").step_ids() == ["a", "b"]


def test_delete_workflow(store):
    store.save_workflow(_workflow())
    store.delete_workflow("wf")
    assert store.load_workflow("wf") is None


def test_save_and_load_run_roundtrip(store):
    store.save_run(_run())
    loaded = store.load_run("r1")
    assert loaded is not None
    assert loaded.status is RunStatus.RUNNING
    assert loaded.workflow.name == "wf"
    rec = loaded.records["a"]
    assert rec.state is StepState.SUCCEEDED
    assert rec.output == {"value": 7}
    assert rec.attempts == 2
    assert rec.started_at == 1.0 and rec.finished_at == 2.0


def test_load_missing_run_returns_none(store):
    assert store.load_run("nope") is None


def test_update_run_state(store):
    run = _run()
    store.save_run(run)
    run.status = RunStatus.SUCCEEDED
    run.records["a"].state = StepState.SUCCEEDED
    run.updated_at = 300.0
    store.save_run(run)
    loaded = store.load_run("r1")
    assert loaded.status is RunStatus.SUCCEEDED
    assert loaded.updated_at == 300.0


def test_run_approved_flag_roundtrip(store):
    run = _run()
    run.records["a"].approved = True
    store.save_run(run)
    assert store.load_run("r1").records["a"].approved is True


def test_list_runs_and_ids(store):
    store.save_run(_run("r1", "wf"))
    store.save_run(_run("r2", "wf"))
    assert store.list_run_ids() == ["r1", "r2"]
    assert [r.id for r in store.list_runs()] == ["r1", "r2"]


def test_delete_run_removes_records(store):
    store.save_run(_run())
    store.delete_run("r1")
    assert store.load_run("r1") is None


def test_string_output_roundtrip(store):
    run = _run()
    run.records["a"].output = "plain text"
    store.save_run(run)
    assert store.load_run("r1").records["a"].output == "plain text"


def test_none_output_roundtrip(store):
    run = _run()
    run.records["a"].output = None
    store.save_run(run)
    assert store.load_run("r1").records["a"].output is None
