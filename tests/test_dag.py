"""Tests for DAG ordering, cycle detection and readiness resolution."""

from __future__ import annotations

import pytest

from agent_orchestrator.dag import (
    CycleError,
    GraphError,
    UnknownDependencyError,
    ancestors,
    blocked_steps,
    find_cycle,
    has_cycle,
    pending_steps,
    ready_steps,
    topological_sort,
)
from agent_orchestrator.models import StepState
from conftest import step


def _spec(step_id: str, *deps: str):
    return step(step_id, "t", depends_on=list(deps))


def test_topological_sort_respects_dependencies():
    steps = [_spec("c", "b"), _spec("b", "a"), _spec("a")]
    order = topological_sort(steps)
    assert order.index("a") < order.index("b") < order.index("c")


def test_topological_sort_handles_independent_nodes():
    steps = [_spec("a"), _spec("b"), _spec("c")]
    order = topological_sort(steps)
    assert sorted(order) == ["a", "b", "c"]


def test_topological_sort_diamond():
    steps = [_spec("a"), _spec("b", "a"), _spec("c", "a"), _spec("d", "b", "c")]
    order = topological_sort(steps)
    assert order.index("a") < order.index("b")
    assert order.index("a") < order.index("c")
    assert order.index("b") < order.index("d")
    assert order.index("c") < order.index("d")


def test_cycle_detection_raises():
    steps = [_spec("a", "b"), _spec("b", "a")]
    with pytest.raises(CycleError):
        topological_sort(steps)


def test_self_cycle_raises():
    steps = [_spec("a", "a")]
    with pytest.raises(CycleError):
        topological_sort(steps)


def test_unknown_dependency_raises():
    steps = [_spec("a", "missing")]
    with pytest.raises(UnknownDependencyError):
        topological_sort(steps)


def test_duplicate_ids_raise():
    steps = [_spec("a"), _spec("a")]
    with pytest.raises(GraphError):
        topological_sort(steps)


def test_has_cycle_true_and_false():
    assert has_cycle([_spec("a", "b"), _spec("b", "a")]) is True
    assert has_cycle([_spec("a"), _spec("b", "a")]) is False


def test_find_cycle_returns_cycle_nodes():
    cycle = find_cycle([_spec("a", "b"), _spec("b", "a")])
    assert set(cycle) == {"a", "b"}
    assert find_cycle([_spec("a"), _spec("b", "a")]) == []


def test_ready_steps_no_dependencies():
    steps = [_spec("a"), _spec("b", "a")]
    states = {"a": StepState.PENDING, "b": StepState.PENDING}
    assert ready_steps(steps, states) == ["a"]


def test_ready_steps_after_dependency_succeeds():
    steps = [_spec("a"), _spec("b", "a")]
    states = {"a": StepState.SUCCEEDED, "b": StepState.PENDING}
    assert ready_steps(steps, states) == ["b"]


def test_ready_steps_excludes_non_pending():
    steps = [_spec("a")]
    states = {"a": StepState.RUNNING}
    assert ready_steps(steps, states) == []


def test_blocked_steps_on_failed_dependency():
    steps = [_spec("a"), _spec("b", "a")]
    states = {"a": StepState.FAILED, "b": StepState.PENDING}
    assert blocked_steps(steps, states) == ["b"]


def test_blocked_steps_on_skipped_dependency():
    steps = [_spec("a"), _spec("b", "a")]
    states = {"a": StepState.SKIPPED, "b": StepState.PENDING}
    assert blocked_steps(steps, states) == ["b"]


def test_pending_steps_lists_only_pending():
    steps = [_spec("a"), _spec("b", "a"), _spec("c")]
    states = {
        "a": StepState.SUCCEEDED,
        "b": StepState.PENDING,
        "c": StepState.FAILED,
    }
    assert pending_steps(steps, states) == ["b"]


def test_ancestors_transitive():
    edges = {"c": ["b"], "b": ["a"], "a": []}
    assert ancestors(edges, "c") == {"a", "b"}
    assert ancestors(edges, "a") == set()
