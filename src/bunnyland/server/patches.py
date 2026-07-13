"""Admin ECS patch application for live editor clients."""

from __future__ import annotations

from typing import Any, cast

from relics import Component, Edge, EntityId, RelicError

from ..core.ecs import ensure_blank_prefab, parse_entity_id
from ..core.mutations import (
    AddComponent,
    AddEdge,
    AddEntity,
    DeleteEntity,
    EntityReference,
    MutationError,
    MutationPlan,
    RemoveComponent,
    RemoveEdge,
    SetComponent,
    execute_mutation_plan,
)
from ..core.world_actor import WorldActor
from ..persistence import type_registries
from .models import (
    AddComponentPatchRequest,
    AddEntityPatchRequest,
    DeleteEntityPatchRequest,
    RemoveComponentPatchRequest,
    SetComponentPatchRequest,
    SetEdgePatchRequest,
    WorldPatchRequest,
    WorldPatchResponse,
)
from .serialization import serialize_entity


class WorldPatchError(ValueError):
    pass


def _component_registry(actor: WorldActor) -> dict[str, type[Component]]:
    if actor.plugins is None:
        raise RuntimeError("world patching requires an applied PluginRegistry")
    return type_registries(actor.plugins)[0]


def _edge_registry(actor: WorldActor) -> dict[str, type[Edge]]:
    if actor.plugins is None:
        raise RuntimeError("world patching requires an applied PluginRegistry")
    return type_registries(actor.plugins)[1]


def _preflight_entity_id(
    actor: WorldActor,
    raw: str,
    aliases: dict[str, Any],
    deleted: set[str],
):
    if raw in aliases:
        if raw in deleted:
            raise WorldPatchError(f"entity {raw!r} does not exist")
        return raw
    entity_id = parse_entity_id(raw)
    if entity_id is None or not actor.world.has_entity(entity_id) or str(entity_id) in deleted:
        raise WorldPatchError(f"entity {raw!r} does not exist")
    return entity_id


def _component(actor: WorldActor, spec) -> Component:
    component_type = _component_registry(actor).get(spec.type)
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


def _preflight_world_patch(actor: WorldActor, request: WorldPatchRequest) -> None:
    aliases: dict[str, Any] = {}
    alias_components: dict[str, set[type[Component]]] = {}
    pending_components: dict[str, set[type[Component]]] = {}
    deleted: set[str] = set()
    component_registry = _component_registry(actor)
    edge_registry = _edge_registry(actor)

    def component_type(spec) -> type[Component]:
        return type(_component(actor, spec))

    for operation in request.operations:
        if isinstance(operation, AddEntityPatchRequest):
            if operation.client_id is not None and operation.client_id in aliases:
                raise WorldPatchError(f"duplicate client entity id {operation.client_id!r}")
            component_types = [component_type(spec) for spec in operation.components]
            duplicate = next(
                (
                    component.__name__
                    for index, component in enumerate(component_types)
                    if component in component_types[:index]
                ),
                None,
            )
            if duplicate is not None:
                raise WorldPatchError(f"duplicate component {duplicate!r}")
            if operation.client_id is not None:
                aliases[operation.client_id] = operation.client_id
                alias_components[operation.client_id] = set(component_types)
        elif isinstance(operation, DeleteEntityPatchRequest):
            entity_id = _preflight_entity_id(actor, operation.entity_id, aliases, deleted)
            deleted.add(str(entity_id))
        elif isinstance(operation, AddComponentPatchRequest):
            entity_id = _preflight_entity_id(actor, operation.entity_id, aliases, deleted)
            new_type = component_type(operation.component)
            if isinstance(entity_id, str):
                components = alias_components.setdefault(entity_id, set())
                if new_type in components:
                    raise WorldPatchError(
                        f"entity {entity_id!r} already has component {new_type.__name__}"
                    )
                components.add(new_type)
            else:
                entity = actor.world.get_entity(entity_id)
                pending = pending_components.setdefault(str(entity_id), set())
                if entity.has_component(new_type) or new_type in pending:
                    raise WorldPatchError(
                        f"entity {operation.entity_id!r} already has component {new_type.__name__}"
                    )
                pending.add(new_type)
        elif isinstance(operation, SetComponentPatchRequest):
            entity_id = _preflight_entity_id(actor, operation.entity_id, aliases, deleted)
            new_type = component_type(operation.component)
            if isinstance(entity_id, str):
                alias_components.setdefault(entity_id, set()).add(new_type)
            else:
                pending_components.setdefault(str(entity_id), set()).add(new_type)
        elif isinstance(operation, RemoveComponentPatchRequest):
            entity_id = _preflight_entity_id(actor, operation.entity_id, aliases, deleted)
            component_type_ = component_registry.get(operation.component_type)
            if component_type_ is None:
                raise WorldPatchError(f"unknown component {operation.component_type!r}")
            if isinstance(entity_id, str):
                components = alias_components.setdefault(entity_id, set())
                if component_type_ not in components:
                    raise WorldPatchError(
                        f"entity {entity_id!r} does not have component {operation.component_type}"
                    )
                components.remove(component_type_)
            elif not actor.world.get_entity(entity_id).has_component(component_type_):
                pending = pending_components.setdefault(str(entity_id), set())
                if component_type_ not in pending:
                    raise WorldPatchError(
                        f"entity {operation.entity_id!r} does not have component "
                        f"{operation.component_type}"
                    )
                pending.remove(component_type_)
        elif isinstance(operation, SetEdgePatchRequest):
            _preflight_entity_id(actor, operation.source_id, aliases, deleted)
            _preflight_entity_id(actor, operation.target_id, aliases, deleted)
            _edge(actor, operation.edge)
        else:  # RemoveEdgePatchRequest -- the operations union is closed and discriminated.
            _preflight_entity_id(actor, operation.source_id, aliases, deleted)
            _preflight_entity_id(actor, operation.target_id, aliases, deleted)
            if edge_registry.get(operation.edge_type) is None:
                raise WorldPatchError(f"unknown edge {operation.edge_type!r}")


def apply_world_patch(actor: WorldActor, request: WorldPatchRequest) -> WorldPatchResponse:
    _preflight_world_patch(actor, request)
    ensure_blank_prefab(actor.world)
    aliases: dict[str, EntityReference] = {}
    operations = []
    changed_targets = []
    deleted_targets = []

    def target(raw: str):
        if raw in aliases:
            return aliases[raw]
        # The request-wide preflight has already proved every non-alias id is valid.
        return cast(EntityId, parse_entity_id(raw))

    for operation in request.operations:
        if isinstance(operation, AddEntityPatchRequest):
            reference = EntityReference()
            operations.append(
                AddEntity(
                    tuple(_component(actor, spec) for spec in operation.components),
                    reference=reference,
                    prefab=operation.prefab,
                )
            )
            if operation.client_id is not None:
                aliases[operation.client_id] = reference
            changed_targets.append(reference)
        elif isinstance(operation, DeleteEntityPatchRequest):
            entity_target = target(operation.entity_id)
            operations.append(DeleteEntity(entity_target))
            deleted_targets.append(entity_target)
        elif isinstance(operation, AddComponentPatchRequest):
            entity_target = target(operation.entity_id)
            operations.append(AddComponent(entity_target, _component(actor, operation.component)))
            changed_targets.append(entity_target)
        elif isinstance(operation, SetComponentPatchRequest):
            entity_target = target(operation.entity_id)
            operations.append(SetComponent(entity_target, _component(actor, operation.component)))
            changed_targets.append(entity_target)
        elif isinstance(operation, RemoveComponentPatchRequest):
            entity_target = target(operation.entity_id)
            component_type = cast(
                type[Component],
                _component_registry(actor).get(operation.component_type),
            )
            operations.append(RemoveComponent(entity_target, component_type))
            changed_targets.append(entity_target)
        elif isinstance(operation, SetEdgePatchRequest):
            source_target = target(operation.source_id)
            operations.append(
                AddEdge(
                    source_target,
                    target(operation.target_id),
                    _edge(actor, operation.edge),
                )
            )
            changed_targets.append(source_target)
        else:  # RemoveEdgePatchRequest -- the operations union is closed and discriminated.
            source_target = target(operation.source_id)
            edge_type = cast(type[Edge], _edge_registry(actor).get(operation.edge_type))
            operations.append(RemoveEdge(source_target, target(operation.target_id), edge_type))
            changed_targets.append(source_target)

    def resolved(entity_target):
        if isinstance(entity_target, EntityReference):
            return entity_target.require()
        return entity_target

    def collect_changes():
        changed = {resolved(entity_target) for entity_target in changed_targets}
        deleted = {resolved(entity_target) for entity_target in deleted_targets}
        for entity_id in deleted:
            entity = actor.world.get_entity(entity_id)
            for edge_type in _edge_registry(actor).values():
                for source_id, _edge_value in entity.get_incoming_relationships(edge_type):
                    changed.add(source_id)
        changed.difference_update(deleted)
        return changed, deleted

    try:
        _summary, (changed, deleted) = execute_mutation_plan(
            actor.world,
            MutationPlan(tuple(operations)),
            after_apply=collect_changes,
        )
    except (MutationError, RelicError) as exc:
        raise WorldPatchError(str(exc)) from exc

    changed_entities = [
        serialize_entity(actor, actor.world.get_entity(entity_id))
        for entity_id in sorted(changed, key=str)
        if actor.world.has_entity(entity_id)
    ]
    return WorldPatchResponse(
        world_epoch=actor.epoch,
        changed_entities=changed_entities,
        deleted_entities=sorted(str(entity_id) for entity_id in deleted),
    )


__all__ = ["WorldPatchError", "apply_world_patch"]
