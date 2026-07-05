"""Named scripts for the scripted controller (spec 7).

A script is a fixed sequence of tool calls replayed turn by turn. ``ScriptedAgent`` does the
replay; this registry maps a name to a sequence so a ``ScriptedControllerComponent`` can
reference one by name and persist as just a string. Built-in scripts are deliberately
minimal; world authors register world-specific scripts with ``register_script``.
"""

from __future__ import annotations

from collections.abc import Iterable

from .specs import ScriptSpec
from .tools import ToolCall, tool_names

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
    # First-run demo intro. Saved Hungry Courier worlds persist only this script name, so
    # it must exist before a saved world is reloaded.
    "hungry-courier-intro": (
        ToolCall(
            "say",
            {
                "text": (
                    "Welcome to Bunnyland. Moss the courier wants to deliver this "
                    "letter, but wants do not bypass world rules. Find food, bring it "
                    "back, and watch what happens."
                ),
                "intent": "inform",
                "approach": "friendly",
            },
        ),
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


def compile_script(spec: ScriptSpec) -> tuple[ToolCall, ...]:
    """Compile a ``ScriptSpec`` into the tuple of tool calls a scripted controller replays.

    Every call must name a registered tool; an unknown tool raises ``ValueError`` so a bad
    spec is rejected at registration time rather than failing silently during replay.
    """
    known = tool_names()
    for call in spec.calls:
        if call.name not in known:
            raise ValueError(f"unknown tool {call.name!r} in script {spec.name!r}")
    return tuple(call.to_tool_call() for call in spec.calls)


def register_script_spec(spec: ScriptSpec) -> tuple[ToolCall, ...]:
    """Compile and register a script from its spec; returns the compiled calls."""
    calls = compile_script(spec)
    register_script(spec.name, calls)
    return calls


__all__ = [
    "BUILTIN_SCRIPTS",
    "compile_script",
    "register_script",
    "register_script_spec",
    "resolve_script",
    "script_names",
]
