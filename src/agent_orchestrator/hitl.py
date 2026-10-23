"""Human-in-the-loop helpers.

These utilities describe the graph consequences of approvals and rejections
without depending on the engine, so they are independently testable.
"""

from __future__ import annotations

from collections import deque
from typing import Sequence

from .models import StepSpec


def _dependents_map(steps: Sequence[StepSpec]) -> dict[str, list[str]]:
    adj: dict[str, list[str]] = {step.id: [] for step in steps}
    for step in steps:
        for dep in step.depends_on:
            adj[dep].append(step.id)
    return adj


def dependents(steps: Sequence[StepSpec], step_id: str) -> list[str]:
    """Return the direct dependents of ``step_id``."""

    return list(_dependents_map(steps).get(step_id, []))


def transitive_dependents(steps: Sequence[StepSpec], step_id: str) -> list[str]:
    """Return every step that directly or indirectly depends on ``step_id``."""

    adj = _dependents_map(steps)
    seen: set[str] = set()
    queue: deque[str] = deque(adj.get(step_id, []))
    order: list[str] = []
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        order.append(node)
        queue.extend(adj.get(node, []))
    return order


def requires_approval(step: StepSpec) -> bool:
    """Return ``True`` when the step must be approved before it runs."""

    return bool(step.requires_approval)
