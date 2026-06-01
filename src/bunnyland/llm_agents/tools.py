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
        "business_id",
        "customer_id",
        "exit_id",
        "fertilizer_id",
        "faction_id",
        "item_id",
        "location_id",
        "objective_id",
        "quest_id",
        "seed_id",
        "seller_id",
        "soil_id",
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
    "till": _Verb("till", Lane.WORLD, _ACTION, ("soil_id",)),
    "plant": _Verb("plant", Lane.WORLD, _ACTION, ("soil_id", "seed_id")),
    "water_crop": _Verb("water-crop", Lane.WORLD, _ACTION, ("soil_id",)),
    "fertilize": _Verb("fertilize", Lane.WORLD, _ACTION, ("soil_id", "fertilizer_id")),
    "harvest_crop": _Verb("harvest-crop", Lane.WORLD, _ACTION, ("soil_id",)),
    "discover_location": _Verb("discover-location", Lane.WORLD, _ACTION, ("location_id",)),
    "accept_quest": _Verb("accept-quest", Lane.WORLD, _ACTION, ("quest_id",)),
    "complete_objective": _Verb("complete-objective", Lane.WORLD, _ACTION, ("objective_id",)),
    "join_faction": _Verb("join-faction", Lane.WORLD, _ACTION, ("faction_id", "rank")),
    "leave_faction": _Verb("leave-faction", Lane.WORLD, _ACTION, ("faction_id",)),
    "claim_ownership": _Verb("claim-ownership", Lane.WORLD, _ACTION, ("target_id",)),
    "release_ownership": _Verb("release-ownership", Lane.WORLD, _ACTION, ("target_id",)),
    "eat": _Verb("eat", Lane.WORLD, _ACTION, ("item_id",)),
    "drink": _Verb("drink", Lane.WORLD, _ACTION, ("source_id",)),
    "adopt_child": _Verb("adopt-child", Lane.WORLD, _ACTION, ("child_id",)),
    "say": _Verb("say", Lane.WORLD, _SPEECH, ("text", "intent")),
    "tell": _Verb("tell", Lane.WORLD, _SPEECH, ("target_id", "text", "intent")),
    "pickpocket": _Verb("pickpocket", Lane.WORLD, _ACTION, ("target_id", "item_id")),
    "open_business": _Verb("open-business", Lane.WORLD, _ACTION, ("name", "default_price")),
    "buy_item": _Verb(
        "buy-item", Lane.WORLD, _ACTION, ("seller_id", "item_id", "business_id", "price")
    ),
    "sell_item": _Verb(
        "sell-item", Lane.WORLD, _ACTION, ("item_id", "customer_id", "business_id", "price")
    ),
    "take_note": _Verb(
        "take-note", Lane.FOCUS, _FOCUS, ("text", "tags", "scope", "collection")
    ),
    "remember": _Verb(
        "remember", Lane.FOCUS, _FOCUS, ("query", "mode", "limit", "scope", "collection")
    ),
    "forget": _Verb("forget", Lane.FOCUS, _FOCUS, ("note_id", "scope", "collection")),
    "reflect": _Verb("reflect", Lane.FOCUS, _FOCUS, ("text", "query", "mode", "limit")),
    "write": _Verb("write", Lane.WORLD, _SPEECH, ("target_id", "text")),
    "wait": _Verb("wait", Lane.WORLD, _FREE, ()),
}


def tool_names() -> tuple[str, ...]:
    return tuple(_VERBS)


def command_type_for_tool(name: str) -> str | None:
    verb = _VERBS.get(name)
    return verb.command_type if verb is not None else None


def tool_arg_keys(name: str) -> tuple[str, ...]:
    verb = _VERBS.get(name)
    return verb.arg_keys if verb is not None else ()


def tool_for_command_type(command_type: str) -> str | None:
    for name, verb in _VERBS.items():
        if verb.command_type == command_type:
            return name
    return None


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
    "command_type_for_tool",
    "tool_arg_keys",
    "tool_for_command_type",
    "tool_names",
    "tool_schemas",
]
