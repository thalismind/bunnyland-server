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


__all__ = [
    "BLANK_PREFAB",
    "Component",
    "Entity",
    "EntityId",
    "World",
    "container_of",
    "contents",
    "ensure_blank_prefab",
    "get_or_none",
    "parse_entity_id",
    "replace_component",
    "spawn_entity",
]
