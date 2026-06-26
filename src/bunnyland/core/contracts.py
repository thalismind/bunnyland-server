"""Structural contracts for code that operates on the ECS graph.

These protocols keep shared helpers decoupled from concrete ``WorldActor`` and Relics
classes. Runtime systems can pass the real actor/world/entities, while tests can provide
small doubles that satisfy the same graph contract.
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

from relics import Component

ComponentT = TypeVar("ComponentT", bound=Component)


class EntityLike(Protocol):
    id: Any

    def has_component(self, component_type: type[Component]) -> bool: ...

    def get_component(self, component_type: type[ComponentT]) -> ComponentT: ...

    def add_component(self, component: Component) -> None: ...

    def remove_component(self, component_type: type[Component]) -> None: ...

    def get_relationships(self, edge_type: type[Any]) -> list[tuple[Any, Any]]: ...


class QueryLike(Protocol):
    def with_all(self, component_types: list[type[Component]]) -> QueryLike: ...

    def execute_entities(self) -> list[EntityLike]: ...


class WorldLike(Protocol):
    def has_entity(self, entity_id: Any) -> bool: ...

    def get_entity(self, entity_id: Any) -> EntityLike: ...

    def query(self) -> QueryLike: ...


class ActorContext(Protocol):
    world: WorldLike


__all__ = ["ActorContext", "EntityLike", "QueryLike", "WorldLike"]
