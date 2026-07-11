"""Plugin-neutral helpers for hand-built demo worlds."""

from __future__ import annotations

from ..core.components import RegionComponent
from ..core.ecs import replace_component, spawn_entity
from ..core.edges import ContainmentMode, Contains
from .generators import GenOptions
from .instantiate import InstantiatedWorld


def _add(actor, room_id, components):
    """Spawn an entity carrying ``components`` and place it in ``room_id``."""
    entity = spawn_entity(actor.world, components)
    actor.world.get_entity(room_id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity


def _augment(actor, entity_id, *components):
    """Replace generated defaults with a demo's curated components."""
    entity = actor.world.get_entity(entity_id)
    for component in components:
        replace_component(entity, component)
    return entity


def _region_stack(actor, room_ids, levels):
    """Build nested region containers above ``room_ids``."""
    children = list(room_ids)
    for name, kind in reversed(levels):
        region = spawn_entity(actor.world, [RegionComponent(name=name, kind=kind)])
        for child_id in children:
            region.add_relationship(Contains(mode=ContainmentMode.REGION), child_id)
        children = [region.id]


def _with_regions(generate, levels):
    """Wrap a demo generator so it lays nested regions above its rooms."""

    async def generate_with_regions(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
        world = await generate(actor, seed, options)
        async with actor._lock:
            _region_stack(actor, world.rooms.values(), levels)
        return world

    return generate_with_regions
