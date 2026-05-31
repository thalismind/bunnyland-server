"""Admin ECS patch application for live editor clients."""

from __future__ import annotations

from typing import Any

from relics import Component, Edge

from ..core.ecs import ensure_blank_prefab, parse_entity_id, replace_component
from ..core.world_actor import WorldActor
from ..persistence import type_registries
from .models import (
    AddComponentPatchRequest,
    AddEntityPatchRequest,
    DeleteEntityPatchRequest,
    RemoveComponentPatchRequest,
    RemoveEdgePatchRequest,
    SetComponentPatchRequest,
    SetEdgePatchRequest,
    WorldPatchRequest,
    WorldPatchResponse,
)
from .serialization import serialize_entity


class WorldPatchError(ValueError):
    pass


def _component_registry(actor: WorldActor) -> dict[str, type[Component]]:
    registry = type_registries()[0]
    registry.update(getattr(actor.world, "_component_types", {}))
    return registry


def _edge_registry(actor: WorldActor) -> dict[str, type[Edge]]:
    registry = type_registries()[1]
    registry.update(getattr(actor.world, "_edge_types", {}))
    return registry


def _entity_id(actor: WorldActor, raw: str, aliases: dict[str, Any] | None = None):
    if aliases and raw in aliases:
        return aliases[raw]
    entity_id = parse_entity_id(raw)
    if entity_id is None or not actor.world.has_entity(entity_id):
        raise WorldPatchError(f"entity {raw!r} does not exist")
    return entity_id


def _component(
    actor: WorldActor, spec, *, fallback: type[Component] | None = None
) -> Component:
    component_type = fallback or _component_registry(actor).get(spec.type)
    if component_type is None:
        raise WorldPatchError(f"unknown component {spec.type!r}")
    try:
        return component_type(**spec.fields)
    except Exception as exc:  # noqa: BLE001 - surface validation errors to the API caller.
        raise WorldPatchError(f"invalid {spec.type}: {exc}") from exc


def _edge(actor: WorldActor, spec) -> Edge:
    edge_type = _edge_registry(actor).get(spec.type)
    if edge_type is None:
        raise WorldPatchError(f"unknown edge {spec.type!r}")
    try:
        return edge_type(**spec.fields)
    except Exception as exc:  # noqa: BLE001 - surface validation errors to the API caller.
        raise WorldPatchError(f"invalid {spec.type}: {exc}") from exc


def _add_changed(changed: set[Any], entity_id: Any | None) -> None:
    if entity_id is not None:
        changed.add(entity_id)


def _apply_add_entity(
    actor: WorldActor,
    operation: AddEntityPatchRequest,
    changed: set[Any],
    aliases: dict[str, Any],
) -> None:
    ensure_blank_prefab(actor.world)
    if operation.client_id is not None and operation.client_id in aliases:
        raise WorldPatchError(f"duplicate client entity id {operation.client_id!r}")
    entity = actor.world.spawn(operation.prefab)
    for spec in operation.components:
        entity.add_component(_component(actor, spec))
    if operation.client_id is not None:
        aliases[operation.client_id] = entity.id
    _add_changed(changed, entity.id)


def _apply_delete_entity(
    actor: WorldActor,
    operation: DeleteEntityPatchRequest,
    changed: set[Any],
    deleted: set[str],
    aliases: dict[str, Any],
) -> None:
    entity_id = _entity_id(actor, operation.entity_id, aliases)
    entity = actor.world.get_entity(entity_id)
    for edge_type in _edge_registry(actor).values():
        for source_id, _edge_value in entity.get_incoming_relationships(edge_type):
            _add_changed(changed, source_id)
    actor.world.remove(entity_id)
    changed.discard(entity_id)
    deleted.add(str(entity_id))


def _apply_add_component(
    actor: WorldActor,
    operation: AddComponentPatchRequest,
    changed: set[Any],
    aliases: dict[str, Any],
) -> None:
    entity_id = _entity_id(actor, operation.entity_id, aliases)
    actor.world.get_entity(entity_id).add_component(_component(actor, operation.component))
    _add_changed(changed, entity_id)


def _apply_set_component(
    actor: WorldActor,
    operation: SetComponentPatchRequest,
    changed: set[Any],
    aliases: dict[str, Any],
) -> None:
    entity_id = _entity_id(actor, operation.entity_id, aliases)
    entity = actor.world.get_entity(entity_id)
    fallback = None
    registry = _component_registry(actor)
    component_type = registry.get(operation.component.type)
    if component_type is not None and entity.has_component(component_type):
        fallback = type(entity.get_component(component_type))
    replace_component(entity, _component(actor, operation.component, fallback=fallback))
    _add_changed(changed, entity_id)


def _apply_remove_component(
    actor: WorldActor,
    operation: RemoveComponentPatchRequest,
    changed: set[Any],
    aliases: dict[str, Any],
) -> None:
    entity_id = _entity_id(actor, operation.entity_id, aliases)
    component_type = _component_registry(actor).get(operation.component_type)
    if component_type is None:
        raise WorldPatchError(f"unknown component {operation.component_type!r}")
    actor.world.get_entity(entity_id).remove_component(component_type)
    _add_changed(changed, entity_id)


def _apply_set_edge(
    actor: WorldActor,
    operation: SetEdgePatchRequest,
    changed: set[Any],
    aliases: dict[str, Any],
) -> None:
    source_id = _entity_id(actor, operation.source_id, aliases)
    target_id = _entity_id(actor, operation.target_id, aliases)
    actor.world.get_entity(source_id).add_relationship(_edge(actor, operation.edge), target_id)
    _add_changed(changed, source_id)


def _apply_remove_edge(
    actor: WorldActor,
    operation: RemoveEdgePatchRequest,
    changed: set[Any],
    aliases: dict[str, Any],
) -> None:
    source_id = _entity_id(actor, operation.source_id, aliases)
    target_id = _entity_id(actor, operation.target_id, aliases)
    edge_type = _edge_registry(actor).get(operation.edge_type)
    if edge_type is None:
        raise WorldPatchError(f"unknown edge {operation.edge_type!r}")
    actor.world.get_entity(source_id).remove_relationship(edge_type, target_id)
    _add_changed(changed, source_id)


def apply_world_patch(actor: WorldActor, request: WorldPatchRequest) -> WorldPatchResponse:
    changed: set[Any] = set()
    deleted: set[str] = set()
    aliases: dict[str, Any] = {}
    for operation in request.operations:
        if isinstance(operation, AddEntityPatchRequest):
            _apply_add_entity(actor, operation, changed, aliases)
        elif isinstance(operation, DeleteEntityPatchRequest):
            _apply_delete_entity(actor, operation, changed, deleted, aliases)
        elif isinstance(operation, AddComponentPatchRequest):
            _apply_add_component(actor, operation, changed, aliases)
        elif isinstance(operation, SetComponentPatchRequest):
            _apply_set_component(actor, operation, changed, aliases)
        elif isinstance(operation, RemoveComponentPatchRequest):
            _apply_remove_component(actor, operation, changed, aliases)
        elif isinstance(operation, SetEdgePatchRequest):
            _apply_set_edge(actor, operation, changed, aliases)
        elif isinstance(operation, RemoveEdgePatchRequest):
            _apply_remove_edge(actor, operation, changed, aliases)
        else:
            raise WorldPatchError(f"unknown patch operation {operation!r}")

    changed_entities = [
        serialize_entity(actor, actor.world.get_entity(entity_id))
        for entity_id in sorted(changed, key=str)
        if actor.world.has_entity(entity_id)
    ]
    return WorldPatchResponse(
        world_epoch=actor.epoch,
        changed_entities=changed_entities,
        deleted_entities=sorted(deleted),
    )


__all__ = ["WorldPatchError", "apply_world_patch"]
