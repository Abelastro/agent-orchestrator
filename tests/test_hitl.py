"""Tests for human-in-the-loop approvals and their graph consequences."""

from __future__ import annotations

import pytest

from agent_orchestrator.engine import WorkflowError
from agent_orchestrator.hitl import (
    dependents,
    requires_approval,
    transitive_dependents,
)
from agent_orchestrator.models import RunStatus, StepState
from conftest import step, workflow


def _steps():
    return [
        step("a", "echo"),
        step("b", "echo", depends_on=["a"]),
        step("c", "echo", depends_on=["b"]),
        step("d", "echo", depends_on=["a"]),
    ]


def test_dependents_direct():
    assert dependents(_steps(), "a") == ["b", "d"]


def test_transitive_dependents():
    assert set(transitive_dependents(_steps(), "a")) == {"b", "c", "d"}
    assert transitive_dependents(_steps(), "c") == []


def test_requires_approval_flag():
    assert requires_approval(step("a", "echo", requires_approval=True)) is True
    assert requires_approval(step("a", "echo")) is False


def test_engine_halts_awaiting_approval(make_engine, registry):
    registry.register("echo", lambda text="": text)
    wf = workflow(
        "gate",
        step("a", "echo", inputs={"text": "hi"}, requires_approval=True),
    )
    run = make_engine().run(wf)
    assert run.status is RunStatus.AWAITING_APPROVAL
    assert run.records["a"].state is StepState.AWAITING_APPROVAL


def test_approve_runs_step_and_continues(make_engine, registry):
    registry.register("echo", lambda text="": text)
    wf = workflow(
        "gate",
        step("gate", "echo", inputs={"text": "hi"}, requires_approval=True),
        step("after", "echo", inputs={"text": "done"}, depends_on=["gate"]),
    )
    engine = make_engine()
    run = engine.run(wf)
    assert run.status is RunStatus.AWAITING_APPROVAL

    approved = engine.approve(run.id, "gate")
    assert approved.status is RunStatus.SUCCEEDED
    assert approved.records["gate"].state is StepState.SUCCEEDED
    assert approved.records["gate"].approved is True
    assert approved.records["after"].state is StepState.SUCCEEDED
    assert approved.records["after"].output == "done"


def test_reject_skips_step_and_dependents(make_engine, registry):
    registry.register("echo", lambda text="": text)
    wf = workflow(
        "gate",
        step("gate", "echo", requires_approval=True),
        step("after", "echo", depends_on=["gate"]),
        step("independent", "echo"),
    )
    engine = make_engine()
    run = engine.run(wf)
    assert run.status is RunStatus.AWAITING_APPROVAL

    rejected = engine.reject(run.id, "gate")
    assert rejected.records["gate"].state is StepState.SKIPPED
    assert rejected.records["gate"].approved is False
    assert rejected.records["after"].state is StepState.SKIPPED
    assert rejected.records["independent"].state is StepState.SUCCEEDED


def test_approve_wrong_state_raises(make_engine, registry):
    registry.register("echo", lambda text="": text)
    engine = make_engine()
    run = engine.run(workflow("plain", step("a", "echo")))
    with pytest.raises(WorkflowError):
        engine.approve(run.id, "a")


def test_approve_unknown_step_raises(make_engine, registry):
    registry.register("echo", lambda text="": text)
    engine = make_engine()
    run = engine.run(
        workflow("gate", step("a", "echo", requires_approval=True))
    )
    with pytest.raises(WorkflowError):
        engine.approve(run.id, "missing")


def test_reject_wrong_state_raises(make_engine, registry):
    registry.register("echo", lambda text="": text)
    engine = make_engine()
    run = engine.run(workflow("plain", step("a", "echo")))
    with pytest.raises(WorkflowError):
        engine.reject(run.id, "a")
