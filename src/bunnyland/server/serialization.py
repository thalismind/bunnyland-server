"""JSON-safe world and event serialization for client APIs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import is_dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel

from ..core.commands import Lane, SubmittedCommand
from ..core.components import IdentityComponent
from ..core.events import DomainEvent
from ..core.world_actor import WorldActor
from ..persistence import WorldMeta


def jsonable(value: Any) -> Any:
    """Recursively convert known value objects into JSON-native structures."""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        fields = getattr(value, "__pydantic_fields__", None) or getattr(
            value, "__dataclass_fields__", {}
        )
        return {
            name: jsonable(getattr(value, name))
            for name in fields
            if not name.startswith("_")
        }
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(item) for item in value]
    return value


def _sorted_entities(actor: WorldActor) -> Iterable:
    return sorted(actor.world.query().execute_entities(), key=lambda entity: str(entity.id))


def serialize_entity(actor: WorldActor, entity) -> dict[str, Any]:
    """Return a client-facing snapshot of one ECS entity."""

    exported = actor.world.export_entity(entity.id)
    identity = (
        entity.get_component(IdentityComponent)
        if entity.has_component(IdentityComponent)
        else None
    )
    relationships: dict[str, list[dict[str, Any]]] = {}
    for edge_name, edges in exported.get("relationships", {}).items():
        relationships[edge_name] = [
            {"target_id": str(edge["target"]), "edge": jsonable(edge["edge"])}
            for edge in edges
        ]
    return {
        "id": str(entity.id),
        "prefab": entity.id.prefab,
        "sequence": entity.id.sequence,
        "name": identity.name if identity is not None else None,
        "kind": identity.kind if identity is not None else None,
        "tags": list(identity.tags) if identity is not None else [],
        "components": {
            type_name: jsonable(fields)
            for type_name, fields in exported.get("components", {}).items()
        },
        "relationships": relationships,
    }


def serialize_queued_command(command: SubmittedCommand) -> dict[str, Any]:
    """Return the client-facing fields for one volatile queued command."""

    return {
        "command_id": command.command_id,
        "character_id": command.character_id,
        "command_type": command.command_type,
        "payload": jsonable(command.payload),
        "cost": jsonable(command.cost),
        "lane": command.lane.value,
        "submitted_at_epoch": command.submitted_at_epoch,
        "expires_at_epoch": command.expires_at_epoch,
    }


def serialize_queued_commands(actor: WorldActor) -> list[dict[str, Any]]:
    """Return volatile queued commands grouped by character and lane."""

    return [
        serialize_queued_command(command)
        for command in actor.pending_submissions()
    ] + [
        serialize_queued_command(command)
        for character_id in sorted(actor.queues.characters_with_pending())
        for lane in Lane
        for command in actor.queues.pending(character_id, lane)
    ]


def serialize_world(actor: WorldActor, meta: WorldMeta | None = None) -> dict[str, Any]:
    """Return the initial snapshot payload expected by web/admin/TUI clients."""

    return {
        "schema_version": 1,
        "world_epoch": actor.epoch,
        "metadata": meta.model_dump(mode="json") if meta is not None else None,
        "entities": [serialize_entity(actor, entity) for entity in _sorted_entities(actor)],
        "queued_commands": serialize_queued_commands(actor),
    }


def serialize_event(event: DomainEvent) -> dict[str, Any]:
    """Return a typed event payload with class name and JSON-safe fields."""

    return {
        "event_type": event.__class__.__name__,
        "event": event.model_dump(mode="json"),
    }


def event_message(event: DomainEvent) -> dict[str, Any]:
    """Wrap a serialized event as a websocket message."""

    return {"type": "event", "data": serialize_event(event)}


__all__ = [
    "event_message",
    "jsonable",
    "serialize_entity",
    "serialize_event",
    "serialize_queued_command",
    "serialize_queued_commands",
    "serialize_world",
]
