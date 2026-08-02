"""Shared observer-relative stealth rules."""

from __future__ import annotations

from relics import Entity, EntityId, World

from .components import RoomComponent, StealthComponent
from .ecs import container_of
from .edges import DetectedStealth


def is_hidden(entity: Entity) -> bool:
    if not entity.has_component(StealthComponent):
        return False
    stealth = entity.get_component(StealthComponent)
    return stealth.hiding and stealth.visibility_level <= stealth.hidden_threshold


def containing_room(world: World, entity: Entity) -> EntityId | None:
    """Resolve physical nesting to a room without trusting cyclic containment."""

    current = entity
    visited = {current.id}
    while True:
        parent_id = container_of(current)
        if parent_id is None or parent_id in visited or not world.has_entity(parent_id):
            return None
        parent = world.get_entity(parent_id)
        if parent.has_component(RoomComponent):
            return parent_id
        visited.add(parent_id)
        current = parent


def observer_detects(world: World, observer: Entity, target: Entity) -> bool:
    """Return whether an edge is valid for this target's current hide attempt."""

    if observer.id == target.id or not is_hidden(target):
        return observer.id == target.id
    observer_room = containing_room(world, observer)
    if observer_room is None or observer_room != containing_room(world, target):
        return False
    stealth = target.get_component(StealthComponent)
    return any(
        edge.target_since_epoch == stealth.since_epoch
        for edge, target_id in observer.get_relationships(DetectedStealth)
        if target_id == target.id
    )


def observer_can_see(world: World, observer: Entity, target: Entity) -> bool:
    return not is_hidden(target) or observer_detects(world, observer, target)


__all__ = ["containing_room", "is_hidden", "observer_can_see", "observer_detects"]
