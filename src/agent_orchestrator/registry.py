"""Tool registry and the ``@tool`` registration decorator.

Tools are plain sync or async callables registered under a name and invoked by
the engine as ``fn(**inputs)``. A process-wide :data:`DEFAULT_REGISTRY` holds
the built-in demo tools (``echo``, ``add``, ``multiply``, ``fail``).
"""

from __future__ import annotations

from typing import Any, Callable, Iterator

ToolFn = Callable[..., Any]


class ToolNotFoundError(KeyError):
    """Raised when a tool name cannot be resolved in a registry."""


class ToolRegistry:
    """A mutable mapping of tool name to callable."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolFn] = {}

    def register(
        self, name: str, fn: ToolFn, *, overwrite: bool = False
    ) -> ToolFn:
        """Register ``fn`` under ``name`` and return the callable."""

        if not callable(fn):
            raise TypeError("tool must be callable")
        if name in self._tools and not overwrite:
            raise ValueError(f"tool '{name}' is already registered")
        self._tools[name] = fn
        return fn

    def unregister(self, name: str) -> None:
        """Remove a tool; a no-op if it is not registered."""

        self._tools.pop(name, None)

    def resolve(self, name: str) -> ToolFn:
        """Return the callable registered under ``name``."""

        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"unknown tool: {name}") from exc

    def names(self) -> list[str]:
        """Return registered tool names in sorted order."""

        return sorted(self._tools)

    def items(self) -> Iterator[tuple[str, ToolFn]]:
        """Iterate over ``(name, callable)`` pairs."""

        return iter(sorted(self._tools.items()))

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)


DEFAULT_REGISTRY = ToolRegistry()


def tool(
    fn: ToolFn | None = None, *, name: str | None = None, registry: ToolRegistry | None = None
) -> Any:
    """Register a callable as a tool, usable as ``@tool`` or ``@tool(name=...)``."""

    target = registry if registry is not None else DEFAULT_REGISTRY

    def decorator(func: ToolFn) -> ToolFn:
        target.register(name or func.__name__, func, overwrite=True)
        setattr(func, "__tool_name__", name or func.__name__)
        return func

    if fn is None:
        return decorator
    return decorator(fn)


@tool
def echo(text: str = "", **_: Any) -> str:
    """Return ``text`` unchanged."""

    return text


@tool
def add(a: float, b: float, **_: Any) -> float:
    """Return the sum of ``a`` and ``b``."""

    return a + b


@tool
def multiply(a: float, b: float, **_: Any) -> float:
    """Return the product of ``a`` and ``b``."""

    return a * b


@tool
def fail(message: str = "intentional failure", **_: Any) -> Any:
    """Always raise a :class:`RuntimeError`; useful for demos and tests."""

    raise RuntimeError(message)
