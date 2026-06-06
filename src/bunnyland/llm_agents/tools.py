"""LLM tool surface (spec 25.2): tools map 1:1 to character verbs.

The same verbs are available to humans (slash commands) and LLMs (tool calls). A tool
call is turned into a validated ``SubmittedCommand``; the engine still enforces costs,
generation, reachability, and policy — the LLM cannot bypass them (spec 25.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.actions import (
    DEFAULT_ACTION_DEFINITIONS,
    REFERENCE_ARG_KEYS,
    ActionDefinition,
    action_definition_for_command_type,
    action_definitions,
    definition_by_command_type,
    definitions_by_tool_name,
    reference_arg_keys,
)
from ..core.commands import SubmittedCommand, build_submitted_command


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


def _definitions_by_tool(
    definitions: tuple[ActionDefinition, ...] | list[ActionDefinition] | None = None,
) -> dict[str, ActionDefinition]:
    return definitions_by_tool_name(definitions)


def _definitions_by_command(
    definitions: tuple[ActionDefinition, ...] | list[ActionDefinition] | None = None,
) -> dict[str, ActionDefinition]:
    return definition_by_command_type(definitions)


def tool_names(
    definitions: tuple[ActionDefinition, ...] | list[ActionDefinition] | None = None,
) -> tuple[str, ...]:
    return tuple(_definitions_by_tool(definitions))


def command_type_for_tool(
    name: str,
    definitions: tuple[ActionDefinition, ...] | list[ActionDefinition] | None = None,
) -> str | None:
    definition = _definitions_by_tool(definitions).get(name)
    return definition.command_type if definition is not None else None


def tool_arg_keys(
    name: str,
    definitions: tuple[ActionDefinition, ...] | list[ActionDefinition] | None = None,
) -> tuple[str, ...]:
    definition = _definitions_by_tool(definitions).get(name)
    return definition.arg_keys if definition is not None else ()


def tool_for_command_type(
    command_type: str,
    definitions: tuple[ActionDefinition, ...] | list[ActionDefinition] | None = None,
) -> str | None:
    definition = _definitions_by_command(definitions).get(command_type)
    return definition.name if definition is not None else None


def tool_schemas(
    definitions: tuple[ActionDefinition, ...] | list[ActionDefinition] | None = None,
) -> list[dict[str, Any]]:
    """JSON-schema-ish tool definitions for the LLM (Ollama/OpenAI ``tools`` format)."""
    return [definition.tool_schema() for definition in action_definitions(definitions or ())]


def command_from_tool_call(
    call: ToolCall,
    *,
    character_id: str,
    controller_id: str,
    controller_generation: int,
    submitted_at_epoch: int = 0,
    definitions: tuple[ActionDefinition, ...] | list[ActionDefinition] | None = None,
) -> SubmittedCommand:
    """Translate an LLM tool call into a validated command envelope."""
    definition = _definitions_by_tool(definitions).get(call.name)
    if definition is None:
        raise ValueError(f"unknown tool {call.name!r}")
    payload = {key: call.arguments[key] for key in definition.arg_keys if key in call.arguments}
    return build_submitted_command(
        character_id=character_id,
        controller_id=controller_id,
        controller_generation=controller_generation,
        command_type=definition.command_type,
        cost=definition.cost,
        lane=definition.lane,
        payload=payload,
        submitted_at_epoch=submitted_at_epoch,
    )


__all__ = [
    "REFERENCE_ARG_KEYS",
    "DEFAULT_ACTION_DEFINITIONS",
    "ToolCall",
    "action_definitions",
    "action_definition_for_command_type",
    "command_from_tool_call",
    "command_type_for_tool",
    "reference_arg_keys",
    "tool_arg_keys",
    "tool_for_command_type",
    "tool_names",
    "tool_schemas",
]
