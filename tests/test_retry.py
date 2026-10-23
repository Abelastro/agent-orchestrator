"""Tests for deterministic backoff computation."""

from __future__ import annotations

import pytest

from agent_orchestrator.models import RetryPolicy
from agent_orchestrator.retry import backoff_sequence, compute_backoff


def test_exponential_growth():
    policy = RetryPolicy(base_delay=1.0, max_delay=100.0, exponential=True)
    assert compute_backoff(1, policy) == 1.0
    assert compute_backoff(2, policy) == 2.0
    assert compute_backoff(3, policy) == 4.0
    assert compute_backoff(4, policy) == 8.0


def test_delay_capped_at_max():
    policy = RetryPolicy(base_delay=1.0, max_delay=5.0, exponential=True)
    assert compute_backoff(10, policy) == 5.0


def test_non_exponential_is_constant():
    policy = RetryPolicy(base_delay=2.0, max_delay=100.0, exponential=False)
    assert compute_backoff(1, policy) == 2.0
    assert compute_backoff(5, policy) == 2.0


def test_jitter_zero_rng_returns_full_delay():
    policy = RetryPolicy(base_delay=4.0, jitter=0.5, exponential=False)
    assert compute_backoff(1, policy, rng=lambda: 0.0) == 4.0


def test_jitter_full_rng_reduces_delay():
    policy = RetryPolicy(base_delay=4.0, jitter=0.5, exponential=False)
    assert compute_backoff(1, policy, rng=lambda: 1.0) == pytest.approx(2.0)


def test_jitter_midpoint():
    policy = RetryPolicy(base_delay=4.0, jitter=0.5, exponential=False)
    assert compute_backoff(1, policy, rng=lambda: 0.5) == pytest.approx(3.0)


def test_jitter_ignored_without_rng():
    policy = RetryPolicy(base_delay=4.0, jitter=0.5, exponential=False)
    assert compute_backoff(1, policy) == 4.0


def test_rng_values_are_clamped():
    policy = RetryPolicy(base_delay=4.0, jitter=1.0, exponential=False)
    assert compute_backoff(1, policy, rng=lambda: 5.0) == pytest.approx(0.0)
    assert compute_backoff(1, policy, rng=lambda: -5.0) == pytest.approx(4.0)


def test_invalid_attempt_raises():
    with pytest.raises(ValueError):
        compute_backoff(0, RetryPolicy())


def test_backoff_sequence_length_and_values():
    policy = RetryPolicy(base_delay=1.0, max_delay=100.0, exponential=True)
    seq = backoff_sequence(policy, 3)
    assert list(seq) == [1.0, 2.0, 4.0]


def test_backoff_sequence_zero():
    assert list(backoff_sequence(RetryPolicy(), 0)) == []
