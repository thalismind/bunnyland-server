"""LLM tool surface (spec 25.2): tools map 1:1 to character verbs.

The same verbs are available to humans (slash commands) and LLMs (tool calls). A tool
call is turned into a validated ``SubmittedCommand``; the engine still enforces costs,
generation, reachability, and policy — the LLM cannot bypass them (spec 25.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.commands import CommandCost, Lane, SubmittedCommand, build_submitted_command


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class _Verb:
    command_type: str
    lane: Lane
    cost: CommandCost
    # maps tool argument names -> payload keys (identity unless renamed)
    arg_keys: tuple[str, ...]


_ACTION = CommandCost(action=1)
_SPEECH = CommandCost(action=1, focus=1)
_FOCUS = CommandCost(focus=1)
_FREE = CommandCost()

#: Payload keys whose value names an entity (resolved name -> id during dispatch). Other
#: keys (direction, text, intent, tags, query, mode, limit, collection) are free text.
REFERENCE_ARG_KEYS: frozenset[str] = frozenset(
    {
        "child_id",
        "exit_id",
        "item_id",
        "target_container_id",
        "target_id",
        "tool_id",
        "source_id",
    }
)

# tool name -> verb definition. ``drop`` and ``take_note`` rename to engine command types.
_VERBS: dict[str, _Verb] = {
    "move": _Verb("move", Lane.WORLD, _ACTION, ("direction", "exit_id")),
    "take": _Verb("take", Lane.WORLD, _ACTION, ("item_id",)),
    "drop": _Verb("put", Lane.WORLD, _ACTION, ("item_id",)),
    "put": _Verb("put", Lane.WORLD, _ACTION, ("item_id", "target_container_id")),
    "use": _Verb("use", Lane.WORLD, _ACTION, ("target_id", "tool_id")),
    "eat": _Verb("eat", Lane.WORLD, _ACTION, ("item_id",)),
    "drink": _Verb("drink", Lane.WORLD, _ACTION, ("source_id",)),
    "adopt_child": _Verb("adopt-child", Lane.WORLD, _ACTION, ("child_id",)),
    "say": _Verb("say", Lane.WORLD, _SPEECH, ("text", "intent")),
    "tell": _Verb("tell", Lane.WORLD, _SPEECH, ("target_id", "text", "intent")),
    "pickpocket": _Verb("pickpocket", Lane.WORLD, _ACTION, ("target_id", "item_id")),
    "take_note": _Verb(
        "take-note", Lane.FOCUS, _FOCUS, ("text", "tags", "scope", "collection")
    ),
    "remember": _Verb(
        "remember", Lane.FOCUS, _FOCUS, ("query", "mode", "limit", "scope", "collection")
    ),
    "reflect": _Verb("reflect", Lane.FOCUS, _FOCUS, ("text", "query", "mode", "limit")),
    "write": _Verb("write", Lane.WORLD, _SPEECH, ("target_id", "text")),
    "wait": _Verb("wait", Lane.WORLD, _FREE, ()),
}


def tool_names() -> tuple[str, ...]:
    return tuple(_VERBS)


def tool_schemas() -> list[dict[str, Any]]:
    """JSON-schema-ish tool definitions for the LLM (Ollama/OpenAI ``tools`` format)."""
    schemas: list[dict[str, Any]] = []
    for name, verb in _VERBS.items():
        properties = {key: {"type": "string"} for key in verb.arg_keys}
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"Character action: {name}",
                    "parameters": {"type": "object", "properties": properties},
                },
            }
        )
    return schemas


def command_from_tool_call(
    call: ToolCall,
    *,
    character_id: str,
    controller_id: str,
    controller_generation: int,
    submitted_at_epoch: int = 0,
) -> SubmittedCommand:
    """Translate an LLM tool call into a validated command envelope."""
    verb = _VERBS.get(call.name)
    if verb is None:
        raise ValueError(f"unknown tool {call.name!r}")
    payload = {key: call.arguments[key] for key in verb.arg_keys if key in call.arguments}
    return build_submitted_command(
        character_id=character_id,
        controller_id=controller_id,
        controller_generation=controller_generation,
        command_type=verb.command_type,
        cost=verb.cost,
        lane=verb.lane,
        payload=payload,
        submitted_at_epoch=submitted_at_epoch,
    )


__all__ = [
    "REFERENCE_ARG_KEYS",
    "ToolCall",
    "command_from_tool_call",
    "tool_names",
    "tool_schemas",
]
