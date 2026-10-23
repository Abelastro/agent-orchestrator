"""Directed-acyclic-graph utilities: ordering, cycle detection, readiness.

The functions in this module operate on plain lists of :class:`StepSpec` (or any
object exposing ``id`` and ``depends_on``) and a mapping of step states, which
keeps the graph logic independent from the execution engine.
"""

from __future__ import annotations

from collections import deque
from typing import Iterable, Mapping, Protocol, Sequence

from .models import StepState


class _Node(Protocol):  # pragma: no cover - structural typing helper
    id: str
    depends_on: Sequence[str]


class GraphError(ValueError):
    """Base class for DAG validation errors."""


class UnknownDependencyError(GraphError):
    """Raised when a step depends on a non-existent step id."""


class CycleError(GraphError):
    """Raised when the workflow graph contains a cycle."""


def _validate(steps: Sequence[_Node]) -> None:
    ids = {step.id for step in steps}
    if len(ids) != len(steps):
        raise GraphError("duplicate step ids detected")
    for step in steps:
        for dep in step.depends_on:
            if dep not in ids:
                raise UnknownDependencyError(
                    f"step '{step.id}' depends on unknown step '{dep}'"
                )


def _adjacency(steps: Sequence[_Node]) -> dict[str, list[str]]:
    """Return a node -> dependents adjacency map."""

    adj: dict[str, list[str]] = {step.id: [] for step in steps}
    for step in steps:
        for dep in step.depends_on:
            adj[dep].append(step.id)
    return adj


def topological_sort(steps: Sequence[_Node]) -> list[str]:
    """Return step ids in a valid topological order (Kahn's algorithm)."""

    _validate(steps)
    indegree = {step.id: len(set(step.depends_on)) for step in steps}
    adj = _adjacency(steps)

    queue: deque[str] = deque(sid for sid, deg in indegree.items() if deg == 0)
    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for nxt in adj[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(order) != len(steps):
        raise CycleError("workflow graph contains a cycle")
    return order


def has_cycle(steps: Sequence[_Node]) -> bool:
    """Return ``True`` if the graph contains a cycle."""

    try:
        topological_sort(steps)
    except CycleError:
        return True
    return False


def find_cycle(steps: Sequence[_Node]) -> list[str]:
    """Return one cycle as a list of step ids, or an empty list if acyclic."""

    _validate(steps)
    adj = _adjacency(steps)
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def dfs(node: str) -> list[str] | None:
        visiting.add(node)
        stack.append(node)
        for nxt in adj[node]:
            if nxt in visiting:
                idx = stack.index(nxt)
                return stack[idx:] + [nxt]
            if nxt not in visited:
                found = dfs(nxt)
                if found:
                    return found
        visiting.discard(node)
        visited.add(node)
        stack.pop()
        return None

    for step in steps:
        if step.id not in visited:
            found = dfs(step.id)
            if found:
                return found
    return []


def ready_steps(
    steps: Sequence[_Node], states: Mapping[str, StepState]
) -> list[str]:
    """Return ids of pending steps whose dependencies have all succeeded."""

    ready: list[str] = []
    for step in steps:
        if states.get(step.id, StepState.PENDING) is not StepState.PENDING:
            continue
        if all(
            states.get(dep, StepState.PENDING) is StepState.SUCCEEDED
            for dep in step.depends_on
        ):
            ready.append(step.id)
    return ready


def blocked_steps(
    steps: Sequence[_Node], states: Mapping[str, StepState]
) -> list[str]:
    """Return ids of pending steps with a failed or skipped dependency."""

    blocked: list[str] = []
    for step in steps:
        if states.get(step.id, StepState.PENDING) is not StepState.PENDING:
            continue
        if any(
            states.get(dep, StepState.PENDING)
            in (StepState.FAILED, StepState.SKIPPED)
            for dep in step.depends_on
        ):
            blocked.append(step.id)
    return blocked


def pending_steps(
    steps: Sequence[_Node], states: Mapping[str, StepState]
) -> list[str]:
    """Return ids of all steps still in the ``PENDING`` state."""

    return [
        step.id
        for step in steps
        if states.get(step.id, StepState.PENDING) is StepState.PENDING
    ]


def ancestors(edges: Mapping[str, Iterable[str]], node: str) -> set[str]:
    """Return the transitive set of nodes that ``node`` depends on."""

    seen: set[str] = set()
    stack = list(edges.get(node, []))
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(edges.get(current, []))
    return seen
