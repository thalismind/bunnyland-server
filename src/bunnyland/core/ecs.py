"""Thin helpers over the Relics ECS.

Relics stores authoritative world state. bunnyland treats components as immutable
values (spec section 4.2): rather than mutating component fields in place, we replace
the whole component. Relics' ``add_component`` rejects duplicates, so replacement is
remove-then-add. ``replace_component`` is the single chokepoint for that idiom.
"""

from __future__ import annotations

from collections.abc import Iterable

from relics import Component, Entity, EntityId, World, list_prefabs

#: Prefab name for a blank entity. Relics only creates entities via prefabs, so we
#: register one empty prefab and build entities up by adding components.
BLANK_PREFAB = "entity"


def ensure_blank_prefab(world: World) -> None:
    """Register the blank prefab if it is not already present (idempotent)."""
    if BLANK_PREFAB not in list_prefabs(world):
        world.register_prefab(BLANK_PREFAB, {})


def spawn_entity(world: World, components: Iterable[Component] = ()) -> Entity:
    """Spawn a blank entity and attach the given components."""
    ensure_blank_prefab(world)
    entity = world.spawn(BLANK_PREFAB)
    for component in components:
        entity.add_component(component)
    return entity


def replace_component(entity: Entity, component: Component) -> None:
    """Replace (or add) a component on an entity.

    This is bunnyland's canonical mutation primitive. Components are frozen values;
    to change state we build a new value (typically via ``dataclasses.replace``) and
    swap it in. See spec section 4.2.
    """
    component_type = type(component)
    if entity.has_component(component_type):
        entity.remove_component(component_type)
    entity.add_component(component)


def get_or_none(entity: Entity, component_type: type[Component]):
    """Return the component of the given type, or ``None`` if absent."""
    if entity.has_component(component_type):
        return entity.get_component(component_type)
    return None


def parse_entity_id(raw: object) -> EntityId | None:
    """Accept either an ``EntityId`` or its ``prefab_sequence`` string form."""
    if isinstance(raw, EntityId):
        return raw
    if isinstance(raw, str) and "_" in raw:
        prefab, _, seq = raw.rpartition("_")
        if seq.isdigit():
            return EntityId(prefab=prefab, sequence=int(seq))
    return None


def container_of(entity: Entity):
    """Return the ``EntityId`` of the entity's direct ``Contains`` parent, or ``None``.

    Each physical entity has at most one direct container (spec 10.3), so the first
    incoming ``Contains`` edge is authoritative.
    """
    from .edges import Contains

    incoming = entity.get_incoming_relationships(Contains)
    if not incoming:
        return None
    source_id, _edge = incoming[0]
    return source_id


def contents(entity: Entity) -> list[EntityId]:
    """Return the ids of entities directly contained by ``entity`` (outgoing ``Contains``)."""
    from .edges import Contains

    return [target_id for _edge, target_id in entity.get_relationships(Contains)]


def reachable_ids(world: World, character: Entity) -> set[EntityId]:
    """Entities a character can interact with: itself, its inventory, its room, and the
    room's direct contents (MVP reachability — no nested containers yet)."""
    reachable: set[EntityId] = {character.id}
    reachable.update(item_id for item_id in contents(character) if world.has_entity(item_id))
    room_id = container_of(character)
    if room_id is not None:
        if world.has_entity(room_id):
            reachable.add(room_id)
            reachable.update(
                item_id
                for item_id in contents(world.get_entity(room_id))
                if world.has_entity(item_id)
            )
    return reachable


def entity_name(entity: Entity) -> str:
    """Return an entity's display name, falling back to its id."""
    from .components import IdentityComponent

    if entity.has_component(IdentityComponent):
        return entity.get_component(IdentityComponent).name
    return str(entity.id)


def room_id_for(world: World, entity_id: EntityId) -> str | None:
    """Return the containing room id string for an existing entity, if any."""
    if not world.has_entity(entity_id):
        return None
    raw = container_of(world.get_entity(entity_id))
    return str(raw) if raw is not None else None


def entity_room_id(entity: Entity) -> str | None:
    """Return the containing room id string for an entity, if any."""
    raw = container_of(entity)
    return str(raw) if raw is not None else None


def remove_from_container(world: World, entity_id: EntityId) -> None:
    """Remove an entity from its direct container when both still exist."""
    from .edges import Contains

    if not world.has_entity(entity_id):
        return
    parent_id = container_of(world.get_entity(entity_id))
    if parent_id is not None and world.has_entity(parent_id):
        world.get_entity(parent_id).remove_relationship(Contains, entity_id)


def reachable_entity(world: World, character_id: EntityId, target_id: EntityId) -> Entity | None:
    """Resolve a reachable entity without raising on dangling ids."""
    if not world.has_entity(character_id) or not world.has_entity(target_id):
        return None
    character = world.get_entity(character_id)
    if target_id not in reachable_ids(world, character):
        return None
    return world.get_entity(target_id)


def reachable_component(
    world: World,
    character_id: EntityId,
    target_id: object,
    component_type: type[Component],
) -> tuple[Entity | None, str | None]:
    """Resolve a reachable target carrying ``component_type`` with stable rejection text."""
    parsed = parse_entity_id(target_id)
    if not world.has_entity(character_id):
        return None, "character does not exist"
    if parsed is None or not world.has_entity(parsed):
        return None, "target does not exist"
    character = world.get_entity(character_id)
    if parsed not in reachable_ids(world, character):
        return None, "target is not reachable"
    entity = world.get_entity(parsed)
    if not entity.has_component(component_type):
        return None, "target is the wrong kind"
    return entity, None


__all__ = [
    "BLANK_PREFAB",
    "Component",
    "Entity",
    "EntityId",
    "World",
    "container_of",
    "contents",
    "entity_name",
    "entity_room_id",
    "ensure_blank_prefab",
    "get_or_none",
    "parse_entity_id",
    "reachable_component",
    "reachable_entity",
    "reachable_ids",
    "replace_component",
    "remove_from_container",
    "room_id_for",
    "spawn_entity",
]
