"""Transactional typed mutations for authoritative Relics state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from relics import Component, Edge, EntityId, World

from .components import ActionPointsComponent, FocusPointsComponent, WorldClockComponent
from .ecs import parse_entity_id, replace_component, spawn_entity
from .edges import Contains, ControlledBy


class MutationError(RuntimeError):
    pass


@dataclass
class EntityReference:
    """Plan-local reference populated by an earlier ``AddEntity`` operation."""

    entity_id: EntityId | None = None

    def require(self) -> EntityId:
        if self.entity_id is None:
            raise MutationError("entity reference has not been created")
        return self.entity_id

    def __str__(self) -> str:
        return str(self.entity_id) if self.entity_id is not None else "$new"


class MutationOperation(Protocol):
    def preflight(self, world: World) -> None: ...

    def apply(self, world: World) -> Callable[[], None]: ...

    def summary(self) -> dict[str, Any]: ...


EntityTarget = EntityId | str | EntityReference


def _target_id(raw: EntityTarget) -> EntityId | None:
    if isinstance(raw, EntityReference):
        return raw.entity_id
    return parse_entity_id(raw)


def _entity(world: World, raw: EntityTarget):
    entity_id = _target_id(raw)
    if entity_id is None or not world.has_entity(entity_id):
        raise MutationError(f"entity {raw!s} does not exist")
    return world.get_entity(entity_id)


def _same_target(left: EntityTarget, right: EntityTarget) -> bool:
    if isinstance(left, EntityReference) or isinstance(right, EntityReference):
        return left is right
    return _target_id(left) == _target_id(right)


def _preflight_supplied_by_prior(
    operation: MutationOperation,
    prior_operations: tuple[MutationOperation, ...],
) -> bool:
    if isinstance(operation, RemoveComponent):
        return any(
            isinstance(prior, (AddComponent, SetComponent))
            and _same_target(prior.entity_id, operation.entity_id)
            and type(prior.component) is operation.component_type
            for prior in prior_operations
        )
    if isinstance(operation, RemoveEdge):
        return any(
            isinstance(prior, AddEdge)
            and _same_target(prior.source_id, operation.source_id)
            and _same_target(prior.target_id, operation.target_id)
            and type(prior.edge) is operation.edge_type
            for prior in prior_operations
        )
    return False


@dataclass(frozen=True)
class AddEntity:
    components: tuple[Component, ...] = ()
    reference: EntityReference | None = None
    prefab: str | None = None

    def preflight(self, world: World) -> None:
        types = [type(component) for component in self.components]
        if len(types) != len(set(types)):
            raise MutationError("new entity has duplicate component types")

    def apply(self, world: World) -> Callable[[], None]:
        if self.prefab is None:
            entity = spawn_entity(world, self.components)
        else:
            entity = world.spawn(self.prefab)
            try:
                for component in self.components:
                    entity.add_component(component)
            except Exception:
                world.remove(entity.id)
                raise
        if self.reference is not None:
            self.reference.entity_id = entity.id

        def inverse() -> None:
            world.remove(entity.id)
            if self.reference is not None:
                self.reference.entity_id = None

        return inverse

    def summary(self) -> dict[str, Any]:
        return {
            "op": "add_entity",
            "prefab": self.prefab,
            "components": [type(c).__name__ for c in self.components],
        }


@dataclass(frozen=True)
class AddComponent:
    entity_id: EntityTarget
    component: Component

    def preflight(self, world: World) -> None:
        if isinstance(self.entity_id, EntityReference) and self.entity_id.entity_id is None:
            return
        entity = _entity(world, self.entity_id)
        if entity.has_component(type(self.component)):
            raise MutationError(
                f"entity {self.entity_id!s} already has component "
                f"{type(self.component).__name__}"
            )

    def apply(self, world: World) -> Callable[[], None]:
        entity = _entity(world, self.entity_id)
        component_type = type(self.component)
        if entity.has_component(component_type):
            raise MutationError(
                f"entity {self.entity_id!s} already has component {component_type.__name__}"
            )
        entity.add_component(self.component)
        return lambda: entity.remove_component(component_type)

    def summary(self) -> dict[str, Any]:
        return {
            "op": "add_component",
            "entity_id": str(self.entity_id),
            "component": type(self.component).__name__,
        }


@dataclass(frozen=True)
class SetComponent:
    entity_id: EntityTarget
    component: Component

    def preflight(self, world: World) -> None:
        if isinstance(self.entity_id, EntityReference) and self.entity_id.entity_id is None:
            return
        _entity(world, self.entity_id)

    def apply(self, world: World) -> Callable[[], None]:
        entity = _entity(world, self.entity_id)
        component_type = type(self.component)
        previous = (
            entity.get_component(component_type)
            if entity.has_component(component_type)
            else None
        )
        replace_component(entity, self.component)

        def inverse() -> None:
            if previous is None:
                entity.remove_component(component_type)
            else:
                replace_component(entity, previous)

        return inverse

    def summary(self) -> dict[str, Any]:
        return {
            "op": "set_component",
            "entity_id": str(self.entity_id),
            "component": type(self.component).__name__,
        }


@dataclass(frozen=True)
class SetComponentFactory:
    """Set a component whose value depends on earlier plan-local references."""

    entity_id: EntityTarget
    component_type: type[Component]
    factory: Callable[[], Component]

    def preflight(self, world: World) -> None:
        if isinstance(self.entity_id, EntityReference) and self.entity_id.entity_id is None:
            return
        _entity(world, self.entity_id)

    def apply(self, world: World) -> Callable[[], None]:
        entity = _entity(world, self.entity_id)
        component = self.factory()
        if type(component) is not self.component_type:
            raise MutationError(
                f"component factory returned {type(component).__name__}, "
                f"expected {self.component_type.__name__}"
            )
        previous = (
            entity.get_component(self.component_type)
            if entity.has_component(self.component_type)
            else None
        )
        replace_component(entity, component)

        def inverse() -> None:
            if previous is None:
                entity.remove_component(self.component_type)
            else:
                replace_component(entity, previous)

        return inverse

    def summary(self) -> dict[str, Any]:
        return {
            "op": "set_component_factory",
            "entity_id": str(self.entity_id),
            "component": self.component_type.__name__,
        }


@dataclass(frozen=True)
class RemoveComponent:
    entity_id: EntityTarget
    component_type: type[Component]

    def preflight(self, world: World) -> None:
        if isinstance(self.entity_id, EntityReference) and self.entity_id.entity_id is None:
            return
        entity = _entity(world, self.entity_id)
        if not entity.has_component(self.component_type):
            raise MutationError(
                f"entity {self.entity_id!s} does not have component {self.component_type.__name__}"
            )

    def apply(self, world: World) -> Callable[[], None]:
        entity = _entity(world, self.entity_id)
        previous = entity.get_component(self.component_type)
        entity.remove_component(self.component_type)
        return lambda: entity.add_component(previous)

    def summary(self) -> dict[str, Any]:
        return {
            "op": "remove_component",
            "entity_id": str(self.entity_id),
            "component": self.component_type.__name__,
        }


@dataclass(frozen=True)
class AddEdge:
    source_id: EntityTarget
    target_id: EntityTarget
    edge: Edge

    def preflight(self, world: World) -> None:
        if not isinstance(self.source_id, EntityReference):
            _entity(world, self.source_id)
        if not isinstance(self.target_id, EntityReference):
            _entity(world, self.target_id)

    def apply(self, world: World) -> Callable[[], None]:
        source = _entity(world, self.source_id)
        target = _entity(world, self.target_id)
        previous = next(
            (
                edge
                for edge, target_id in source.get_relationships(type(self.edge))
                if target_id == target.id
            ),
            None,
        )
        source.add_relationship(self.edge, target.id)

        def inverse() -> None:
            source.remove_relationship(type(self.edge), target.id)
            if previous is not None:
                source.add_relationship(previous, target.id)

        return inverse

    def summary(self) -> dict[str, Any]:
        return {
            "op": "add_edge",
            "source_id": str(self.source_id),
            "target_id": str(self.target_id),
            "edge": type(self.edge).__name__,
        }


@dataclass(frozen=True)
class RemoveEdge:
    source_id: EntityTarget
    target_id: EntityTarget
    edge_type: type[Edge]

    def preflight(self, world: World) -> None:
        if (
            isinstance(self.source_id, EntityReference)
            and self.source_id.entity_id is None
        ) or (
            isinstance(self.target_id, EntityReference)
            and self.target_id.entity_id is None
        ):
            return
        source = _entity(world, self.source_id)
        target = _entity(world, self.target_id)
        if not source.has_relationship(self.edge_type, target.id):
            raise MutationError(
                f"entity {self.source_id!s} does not have {self.edge_type.__name__} "
                f"edge to {self.target_id!s}"
            )

    def apply(self, world: World) -> Callable[[], None]:
        source = _entity(world, self.source_id)
        target = _entity(world, self.target_id)
        edge = next(
            edge
            for edge, target_id in source.get_relationships(self.edge_type)
            if target_id == target.id
        )
        source.remove_relationship(self.edge_type, target.id)
        return lambda: source.add_relationship(edge, target.id)

    def summary(self) -> dict[str, Any]:
        return {
            "op": "remove_edge",
            "source_id": str(self.source_id),
            "target_id": str(self.target_id),
            "edge": self.edge_type.__name__,
        }


@dataclass(frozen=True)
class DeleteEntity:
    """Terminal deletion committed only after all reversible work succeeds."""

    entity_id: EntityTarget

    def preflight(self, world: World) -> None:
        if isinstance(self.entity_id, EntityReference) and self.entity_id.entity_id is None:
            return
        _entity(world, self.entity_id)

    def apply(self, world: World) -> Callable[[], None]:
        del world
        return lambda: None

    def commit(self, world: World) -> None:
        world.remove(_entity(world, self.entity_id).id)

    def summary(self) -> dict[str, Any]:
        return {"op": "delete_entity", "entity_id": str(self.entity_id)}


Invariant = Callable[[World], None]


def register_world_invariant(world: World, invariant: Invariant) -> None:
    """Register one plugin-owned invariant for every transactional mutation."""

    registered = tuple(getattr(world, "_bunnyland_invariants", ()))
    if invariant not in registered:
        world._bunnyland_invariants = (*registered, invariant)


@dataclass(frozen=True)
class MutationPlan:
    operations: tuple[MutationOperation, ...] = ()
    invariants: tuple[Invariant, ...] = ()

    def summary(self) -> tuple[dict[str, Any], ...]:
        return tuple(operation.summary() for operation in self.operations)


def validate_core_invariants(world: World) -> None:
    clocks = list(world.query().with_all([WorldClockComponent]).execute_entities())
    if len(clocks) != 1:
        raise MutationError(f"expected exactly one world clock, found {len(clocks)}")
    for entity in world.query().execute_entities():
        if len(entity.get_incoming_relationships(Contains)) > 1:
            raise MutationError(f"entity {entity.id} has more than one physical location")
        if len(entity.get_relationships(ControlledBy)) > 1:
            raise MutationError(f"entity {entity.id} has more than one active controller claim")
        for component_type in (ActionPointsComponent, FocusPointsComponent):
            if entity.has_component(component_type):
                meter = entity.get_component(component_type)
                if meter.current < 0 or meter.current > meter.maximum:
                    raise MutationError(
                        f"entity {entity.id} has out-of-bounds {component_type.__name__}"
                    )
    for invariant in getattr(world, "_bunnyland_invariants", ()):
        invariant(world)


def execute_mutation_plan(
    world: World,
    plan: MutationPlan,
    *,
    after_apply: Callable[[], Any] | None = None,
) -> tuple[dict[str, Any], ...] | tuple[tuple[dict[str, Any], ...], Any]:
    """Preflight, apply, assert, and reverse all applied operations on failure."""

    deletions = tuple(
        operation for operation in plan.operations if isinstance(operation, DeleteEntity)
    )
    if deletions and plan.invariants:
        raise MutationError("delete plans cannot use custom invariants")
    for index, operation in enumerate(plan.operations):
        try:
            operation.preflight(world)
        except MutationError:
            if not _preflight_supplied_by_prior(operation, plan.operations[:index]):
                raise
    inverses: list[Callable[[], None]] = []
    try:
        for operation in plan.operations:
            inverses.append(operation.apply(world))
        validate_core_invariants(world)
        for invariant in plan.invariants:
            invariant(world)
        after_result = after_apply() if after_apply is not None else None
        deletion_ids: list[EntityId] = []
        for deletion in deletions:
            deletion_id = _target_id(deletion.entity_id)
            if deletion_id is None:
                raise MutationError("delete entity reference has not been created")
            deletion_ids.append(deletion_id)
        if len(deletion_ids) != len(set(deletion_ids)):
            raise MutationError("entity cannot be deleted more than once in one plan")
        for deletion_id in deletion_ids:
            entity = _entity(world, deletion_id)
            if entity.has_component(WorldClockComponent):
                raise MutationError("the world clock cannot be deleted")
    except Exception:
        for inverse in reversed(inverses):
            inverse()
        raise
    for deletion in deletions:
        deletion.commit(world)
    summary = plan.summary()
    if after_apply is not None:
        return summary, after_result
    return summary


__all__ = [
    "AddComponent",
    "AddEdge",
    "AddEntity",
    "DeleteEntity",
    "EntityReference",
    "MutationError",
    "MutationPlan",
    "register_world_invariant",
    "RemoveComponent",
    "RemoveEdge",
    "SetComponent",
    "execute_mutation_plan",
    "validate_core_invariants",
]
