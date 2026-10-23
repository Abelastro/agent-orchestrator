"""Deterministic retry/backoff computation.

Backoff delays are computed purely from an attempt number and a
:class:`RetryPolicy`. Randomness is injected through a ``rng`` callable so tests
can supply deterministic values instead of real random numbers or sleeps.
"""

from __future__ import annotations

from typing import Callable, Sequence

from .models import RetryPolicy

RandomFn = Callable[[], float]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def compute_backoff(
    attempt: int, policy: RetryPolicy, rng: RandomFn | None = None
) -> float:
    """Compute the delay before the next attempt.

    ``attempt`` is the 1-based number of the *completed* attempt. The delay for
    the next attempt grows exponentially when ``policy.exponential`` is set,
    is capped at ``policy.max_delay`` and optionally reduced by multiplicative
    jitter using ``rng`` (a callable returning ``[0, 1]``).
    """

    if attempt < 1:
        raise ValueError("attempt must be >= 1")

    if policy.exponential:
        delay = policy.base_delay * (2 ** (attempt - 1))
    else:
        delay = policy.base_delay

    delay = min(delay, policy.max_delay)

    if policy.jitter > 0.0 and rng is not None:
        r = _clamp(rng(), 0.0, 1.0)
        delay = delay * (1.0 - policy.jitter * r)

    return delay


def backoff_sequence(
    policy: RetryPolicy,
    attempts: int,
    rng: RandomFn | None = None,
) -> Sequence[float]:
    """Return the list of delays for ``attempts`` retries (attempt 1..N)."""

    if attempts < 0:
        raise ValueError("attempts must be >= 0")
    return [compute_backoff(i, policy, rng) for i in range(1, attempts + 1)]
