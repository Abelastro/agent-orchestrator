"""Tests for the tool registry and ``@tool`` decorator."""

from __future__ import annotations

import asyncio
import inspect

import pytest

from agent_orchestrator.registry import (
    DEFAULT_REGISTRY,
    ToolNotFoundError,
    ToolRegistry,
    tool,
)


def test_register_and_resolve():
    reg = ToolRegistry()
    reg.register("double", lambda x: x * 2)
    assert reg.resolve("double")(21) == 42


def test_register_requires_callable():
    reg = ToolRegistry()
    with pytest.raises(TypeError):
        reg.register("bad", 123)  # type: ignore[arg-type]


def test_duplicate_registration_raises():
    reg = ToolRegistry()
    reg.register("t", lambda: None)
    with pytest.raises(ValueError):
        reg.register("t", lambda: None)


def test_overwrite_registration():
    reg = ToolRegistry()
    reg.register("t", lambda: 1)
    reg.register("t", lambda: 2, overwrite=True)
    assert reg.resolve("t")() == 2


def test_resolve_missing_raises():
    reg = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        reg.resolve("nope")


def test_decorator_uses_function_name():
    reg = ToolRegistry()

    @tool(registry=reg)
    def my_tool(value):
        return value + 1

    assert "my_tool" in reg
    assert reg.resolve("my_tool")(1) == 2
    assert my_tool.__tool_name__ == "my_tool"


def test_decorator_with_explicit_name():
    reg = ToolRegistry()

    @tool(name="renamed", registry=reg)
    def original():
        return "ok"

    assert "renamed" in reg
    assert reg.resolve("renamed")() == "ok"


def test_async_tool_registration_and_invocation():
    reg = ToolRegistry()

    @tool(name="async_double", registry=reg)
    async def async_double(x):
        return x * 2

    fn = reg.resolve("async_double")
    assert inspect.iscoroutinefunction(fn)
    assert asyncio.run(fn(5)) == 10


def test_names_len_contains_unregister():
    reg = ToolRegistry()
    reg.register("b", lambda: None)
    reg.register("a", lambda: None)
    assert reg.names() == ["a", "b"]
    assert len(reg) == 2
    assert "a" in reg
    reg.unregister("a")
    assert "a" not in reg
    reg.unregister("missing")


def test_builtin_tools_registered_by_default():
    assert "echo" in DEFAULT_REGISTRY
    assert "add" in DEFAULT_REGISTRY
    assert DEFAULT_REGISTRY.resolve("echo")(text="hi") == "hi"
    assert DEFAULT_REGISTRY.resolve("add")(a=2, b=3) == 5


def test_items_iterates_sorted():
    reg = ToolRegistry()
    reg.register("z", lambda: None)
    reg.register("a", lambda: None)
    assert [name for name, _ in reg.items()] == ["a", "z"]
