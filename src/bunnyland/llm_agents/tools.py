"""LLM tool surface (spec 25.2): tools map 1:1 to character verbs.

The same verbs are available to humans (slash commands) and LLMs (tool calls). A tool
call is turned into a validated ``SubmittedCommand``; the engine still enforces costs,
generation, reachability, and policy — the LLM cannot bypass them (spec 25.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..core.actions import (
    REFERENCE_ARG_KEYS,
    ActionDefinition,
    action_definitions,
    definition_by_command_type,
    definitions_by_tool_name,
    reference_arg_keys,
)
from ..core.commands import SubmittedCommand, build_submitted_command

if TYPE_CHECKING:
    from relics import Entity

    from ..core.world_actor import WorldActor

DISCOVER_ACTION_TOOL = "discover_action"


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


def contextual_action_definitions(
    actor: WorldActor, character: Entity
) -> tuple[ActionDefinition, ...]:
    """Select the native tool surface relevant to one character's local world state.

    Core and foundation actions stay available everywhere. Sim and addon actions are
    included when their owning plugin has live ECS state on the character, current room,
    inventory, or another reachable entity. Command validation still uses the actor's full
    registry; this only avoids sending hundreds of irrelevant schemas to the provider.
    """

    definitions = action_definitions(actor.action_definitions())
    registry = actor.plugins
    if registry is None:
        return definitions

    from ..core.ecs import container_of, reachable_ids
    from ..plugins.model import PluginPlacement

    active_owners = {
        plugin_id
        for plugin_id in registry.plugins
        if registry.placement(plugin_id) in {PluginPlacement.CORE, PluginPlacement.FOUNDATION}
    }
    entity_ids = reachable_ids(actor.world, character)
    entity_ids.add(character.id)
    room_id = container_of(character)
    if room_id is not None:
        entity_ids.add(room_id)

    entities = [
        actor.world.get_entity(entity_id)
        for entity_id in entity_ids
        if actor.world.has_entity(entity_id)
    ]
    for _name, (owner, component_type) in registry.components.items():
        if any(entity.has_component(component_type) for entity in entities):
            active_owners.add(owner)
    for _name, (owner, edge_type) in registry.edges.items():
        if any(entity.get_relationships(edge_type) for entity in entities):
            active_owners.add(owner)

    return tuple(
        definition
        for definition in definitions
        if registry.actions.get(definition.command_type, (None,))[0] in active_owners
    )


def action_discovery_schema(definitions: tuple[ActionDefinition, ...]) -> dict[str, Any] | None:
    """Native meta-tool for progressively exposing omitted registered actions."""

    names = sorted(definition.name for definition in definitions)
    if not names:
        return None
    return {
        "type": "function",
        "function": {
            "name": DISCOVER_ACTION_TOOL,
            "description": (
                "Make one installed game action available on the next decision when the "
                "needed action is not already offered as a tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action_name": {
                        "type": "string",
                        "description": "Installed action to expose.",
                        "enum": names,
                    }
                },
                "required": ["action_name"],
            },
        },
    }


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
    "DISCOVER_ACTION_TOOL",
    "ToolCall",
    "action_definitions",
    "action_discovery_schema",
    "command_from_tool_call",
    "command_type_for_tool",
    "contextual_action_definitions",
    "reference_arg_keys",
    "tool_arg_keys",
    "tool_for_command_type",
    "tool_names",
    "tool_schemas",
]
