"""Named scripts for the scripted controller (spec 7).

A script is a fixed sequence of tool calls replayed turn by turn. ``ScriptedAgent`` does the
replay; this registry maps a name to a sequence so a ``ScriptedControllerComponent`` can
reference one by name and persist as just a string. Built-in scripts are deliberately
minimal; world authors register world-specific scripts with ``register_script``.
"""

from __future__ import annotations

from collections.abc import Iterable

from .tools import ToolCall

BUILTIN_SCRIPTS: dict[str, tuple[ToolCall, ...]] = {
    # Empty script: the character always waits. A safe default for an unconfigured scripted
    # controller.
    "wait": (),
    # Pace back and forth. The directions are illustrative; most worlds register their own.
    "patrol": (
        ToolCall("move", {"direction": "north"}),
        ToolCall("move", {"direction": "south"}),
    ),
    # Offer a single greeting, then wait.
    "greeter": (
        ToolCall("say", {"text": "Welcome.", "intent": "praise", "approach": "friendly"}),
    ),
}

_REGISTRY: dict[str, tuple[ToolCall, ...]] = {
    name: tuple(calls) for name, calls in BUILTIN_SCRIPTS.items()
}


def register_script(name: str, calls: Iterable[ToolCall]) -> None:
    """Register (or replace) a named script so scripted controllers can reference it."""
    _REGISTRY[name] = tuple(calls)


def resolve_script(name: str) -> tuple[ToolCall, ...]:
    """Return the named script, or raise ``ValueError`` if it is not registered."""
    script = _REGISTRY.get(name)
    if script is None:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise ValueError(f"unknown script {name!r}; available: {available}")
    return script


def script_names() -> frozenset[str]:
    """Names of all registered scripts."""
    return frozenset(_REGISTRY)


__all__ = [
    "BUILTIN_SCRIPTS",
    "register_script",
    "resolve_script",
    "script_names",
]
