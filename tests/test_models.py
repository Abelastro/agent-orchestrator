"""Tests for the Pydantic domain models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_orchestrator.models import (
    RetryPolicy,
    RunRecord,
    RunStatus,
    StepRecord,
    StepSpec,
    StepState,
    WorkflowSpec,
)


def test_step_spec_defaults():
    spec = StepSpec(id="a", tool="echo")
    assert spec.inputs == {}
    assert spec.depends_on == []
    assert spec.requires_approval is False
    assert spec.timeout is None
    assert spec.retry.max_attempts == 3


def test_retry_policy_is_frozen():
    policy = RetryPolicy()
    with pytest.raises(ValidationError):
        policy.max_attempts = 5  # type: ignore[misc]


def test_workflow_step_lookup_and_ids():
    wf = WorkflowSpec(
        name="wf",
        steps=[StepSpec(id="a", tool="echo"), StepSpec(id="b", tool="echo")],
    )
    assert wf.step_ids() == ["a", "b"]
    assert wf.step("b").id == "b"
    with pytest.raises(KeyError):
        wf.step("missing")


def test_run_record_states_and_record():
    rec_a = StepRecord(step_id="a", state=StepState.SUCCEEDED)
    rec_b = StepRecord(step_id="b")
    run = RunRecord(
        id="r1",
        workflow=WorkflowSpec(name="wf", steps=[StepSpec(id="a", tool="echo")]),
        records={"a": rec_a, "b": rec_b},
    )
    assert run.states() == {"a": StepState.SUCCEEDED, "b": StepState.PENDING}
    assert run.record("a") is rec_a
    assert run.status is RunStatus.PENDING


def test_step_state_values():
    assert StepState.PENDING.value == "pending"
    assert StepState.AWAITING_APPROVAL.value == "awaiting_approval"
    assert RunStatus.SUCCEEDED.value == "succeeded"


def test_model_json_roundtrip():
    wf = WorkflowSpec(name="wf", steps=[StepSpec(id="a", tool="echo")])
    restored = WorkflowSpec.model_validate_json(wf.model_dump_json())
    assert restored == wf
