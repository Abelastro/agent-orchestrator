"""Tests for the execution engine: ordering, retries, resume and checkpoints."""

from __future__ import annotations

import threading

import pytest

from agent_orchestrator.dag import CycleError, UnknownDependencyError
from agent_orchestrator.engine import NotFoundError
from agent_orchestrator.models import RetryPolicy, RunStatus, StepState
from conftest import step, workflow


def test_run_linear_success(make_engine, registry):
    registry.register("echo", lambda text="": text)
    wf = workflow(
        "linear",
        step("a", "echo", inputs={"text": "one"}),
        step("b", "echo", inputs={"text": "two"}, depends_on=["a"]),
    )
    run = make_engine().run(wf)
    assert run.status is RunStatus.SUCCEEDED
    assert run.records["a"].state is StepState.SUCCEEDED
    assert run.records["b"].output == "two"


def test_dependency_ordering(make_engine, registry):
    order: list[str] = []
    registry.register("rec", lambda name: order.append(name) or name)
    wf = workflow(
        "ordered",
        step("a", "rec", inputs={"name": "a"}),
        step("b", "rec", inputs={"name": "b"}, depends_on=["a"]),
        step("c", "rec", inputs={"name": "c"}, depends_on=["b"]),
    )
    make_engine().run(wf)
    assert order == ["a", "b", "c"]


def test_independent_steps_all_run(make_engine, registry):
    registry.register("noop", lambda: "ok")
    wf = workflow("fan", step("a", "noop"), step("b", "noop"))
    run = make_engine().run(wf)
    assert run.status is RunStatus.SUCCEEDED
    assert {r.state for r in run.records.values()} == {StepState.SUCCEEDED}


def test_failure_marks_dependents_skipped(make_engine, registry, sleeper):
    registry.register("boom", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    registry.register("ok", lambda: "ok")
    wf = workflow(
        "fail",
        step("a", "boom", retry=RetryPolicy(max_attempts=2, base_delay=1.0)),
        step("b", "ok", depends_on=["a"]),
        step("c", "ok", depends_on=["b"]),
    )
    run = make_engine().run(wf)
    assert run.status is RunStatus.FAILED
    assert run.records["a"].state is StepState.FAILED
    assert run.records["a"].attempts == 2
    assert run.records["b"].state is StepState.SKIPPED
    assert run.records["c"].state is StepState.SKIPPED
    assert sleeper.calls == [1.0]


def test_retry_then_success(make_engine, registry, sleeper):
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient")
        return "done"

    registry.register("flaky", flaky)
    wf = workflow(
        "retry",
        step("a", "flaky", retry=RetryPolicy(max_attempts=3, base_delay=1.0)),
    )
    run = make_engine().run(wf)
    assert run.status is RunStatus.SUCCEEDED
    assert run.records["a"].attempts == 3
    assert run.records["a"].output == "done"
    assert sleeper.calls == [1.0, 2.0]


def test_retry_delay_respects_max(make_engine, registry, sleeper):
    registry.register("boom", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    wf = workflow(
        "cap",
        step(
            "a",
            "boom",
            retry=RetryPolicy(max_attempts=4, base_delay=10.0, max_delay=10.0),
        ),
    )
    make_engine().run(wf)
    assert sleeper.calls == [10.0, 10.0, 10.0]


def test_missing_tool_fails_without_retry(make_engine, sleeper):
    wf = workflow("missing", step("a", "does-not-exist"))
    run = make_engine().run(wf)
    assert run.status is RunStatus.FAILED
    assert run.records["a"].state is StepState.FAILED
    assert "does-not-exist" in run.records["a"].error
    assert run.records["a"].attempts == 0
    assert sleeper.calls == []


def test_resume_after_failure(make_engine, registry, store):
    state = {"fail": True}

    def flaky():
        if state["fail"]:
            raise RuntimeError("boom")
        return "recovered"

    registry.register("flaky", flaky)
    wf = workflow(
        "resume",
        step("a", "flaky", retry=RetryPolicy(max_attempts=1)),
        step("b", "flaky", retry=RetryPolicy(max_attempts=1), depends_on=["a"]),
    )
    engine = make_engine()
    run = engine.run(wf)
    assert run.status is RunStatus.FAILED
    assert run.records["b"].state is StepState.SKIPPED

    state["fail"] = False
    resumed = engine.resume(run.id)
    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed.records["a"].state is StepState.SUCCEEDED
    assert resumed.records["b"].state is StepState.SUCCEEDED
    assert store.load_run(run.id).status is RunStatus.SUCCEEDED


def test_resume_succeeded_run_is_idempotent(make_engine, registry):
    registry.register("echo", lambda text="": text)
    engine = make_engine()
    run = engine.run(workflow("ok", step("a", "echo")))
    again = engine.resume(run.id)
    assert again.status is RunStatus.SUCCEEDED


def test_run_persisted_to_store(make_engine, registry, store):
    registry.register("echo", lambda text="": text)
    run = make_engine().run(workflow("persist", step("a", "echo")))
    loaded = store.load_run(run.id)
    assert loaded is not None
    assert loaded.workflow.name == "persist"


def test_get_run_missing_raises(make_engine):
    with pytest.raises(NotFoundError):
        make_engine().get_run("nope")


def test_cycle_raises_on_run(make_engine, registry):
    registry.register("echo", lambda: None)
    wf = workflow(
        "cycle",
        step("a", "echo", depends_on=["b"]),
        step("b", "echo", depends_on=["a"]),
    )
    with pytest.raises(CycleError):
        make_engine().run(wf)


def test_unknown_dependency_raises(make_engine, registry):
    registry.register("echo", lambda: None)
    wf = workflow("unknown", step("a", "echo", depends_on=["missing"]))
    with pytest.raises(UnknownDependencyError):
        make_engine().run(wf)


def test_empty_workflow_succeeds(make_engine):
    run = make_engine().run(workflow("empty"))
    assert run.status is RunStatus.SUCCEEDED
    assert run.records == {}


def test_async_tool_execution(make_engine, registry):
    async def acompute(x):
        return x * 2

    registry.register("acompute", acompute)
    wf = workflow("async", step("a", "acompute", inputs={"x": 21}))
    run = make_engine().run(wf)
    assert run.status is RunStatus.SUCCEEDED
    assert run.records["a"].output == 42


def test_tool_timeout_fails(make_engine, registry):
    gate = threading.Event()

    def blocker():
        gate.wait(0.5)

    registry.register("blocker", blocker)
    wf = workflow(
        "timeout",
        step("a", "blocker", timeout=0.01, retry=RetryPolicy(max_attempts=1)),
    )
    run = make_engine().run(wf)
    assert run.status is RunStatus.FAILED
    assert "TimeoutError" in run.records["a"].error
    gate.set()


def test_pause_run(make_engine, registry):
    registry.register("echo", lambda text="": text)
    engine = make_engine()
    run = engine.run(workflow("p", step("a", "echo")))
    paused = engine.pause(run.id)
    assert paused.status is RunStatus.PAUSED


def test_tracing_emits_span_per_step(make_engine, registry):
    registry.register("boom", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    wf = workflow("trace", step("a", "boom", retry=RetryPolicy(max_attempts=2)))
    engine = make_engine()
    run = engine.run(wf)
    span = engine.tracer.find_span("step:a")
    assert span is not None
    events = {e.name for e in span.events}
    assert "attempt_failed" in events
    assert "retry" in events
    run_span = engine.tracer.find_span(f"run:{run.id}")
    assert run_span is not None
    assert run_span.attributes["workflow"] == "trace"
    assert run_span.duration is not None
