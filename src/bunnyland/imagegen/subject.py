"""Assemble a text description of what to draw from ECS state (spec 27).

A *subject* is the plain-language seed the prompt enhancer turns into a model prompt. A single
entity (character or object) becomes a description of itself; a world-history record becomes a
scene: the recorded summary plus the room it happened in and the characters and items present,
so event images can show a room with multiple subjects.
"""

from __future__ import annotations

from relics import Entity, World

from bunnyland.foundation.history.mechanics import WorldHistoryRecordComponent

from ..core.components import DescriptionComponent, IdentityComponent, RoomComponent
from ..core.ecs import container_of, entity_name, parse_entity_id


def subject_for_entity(entity: Entity) -> str:
    """Describe a single entity (its name, kind, and appearance/description)."""
    parts = [entity_name(entity)]
    if entity.has_component(IdentityComponent):
        kind = entity.get_component(IdentityComponent).kind
        if kind:
            parts.append(kind)
    if entity.has_component(DescriptionComponent):
        description = entity.get_component(DescriptionComponent)
        text = description.appearance or description.long or description.short
        if text:
            parts.append(text)
    return ", ".join(parts)


def _room_member_names(world: World, room_id) -> list[str]:
    names = [
        entity_name(entity)
        for entity in world.query().with_all([IdentityComponent]).execute_entities()
        if container_of(entity) == room_id
    ]
    return sorted(names)


def subject_for_event(world: World, record_entity: Entity) -> str:
    """Describe a world-history record as a scene: summary, room, and who/what is present."""
    record = record_entity.get_component(WorldHistoryRecordComponent)
    parts = [record.summary]
    location_id = parse_entity_id(record.location_id) if record.location_id else None
    if location_id is not None and world.has_entity(location_id):
        room = world.get_entity(location_id)
        if room.has_component(RoomComponent):
            parts.append(f"in {room.get_component(RoomComponent).title}")
        members = _room_member_names(world, location_id)
        if members:
            parts.append("present: " + ", ".join(members))
    if record.tags:
        parts.append("themes: " + ", ".join(record.tags))
    return ". ".join(parts)


__all__ = ["subject_for_entity", "subject_for_event"]
