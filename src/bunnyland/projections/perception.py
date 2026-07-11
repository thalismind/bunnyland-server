"""Per-character perception (spec 19).

What a character can see in its current room: visible entities (closed opaque containers
hide their contents; open or transparent ones reveal them) and exits. Suspended, dead,
sleeping, and downed characters perceive nothing in MVP (spec 19).
"""

from __future__ import annotations

from dataclasses import dataclass

from relics import Entity, World

from ..core.components import (
    CharacterComponent,
    ContainerComponent,
    DeadComponent,
    DownedComponent,
    IdentityComponent,
    PerceptionComponent,
    SleepingComponent,
    StealthComponent,
    SuspendedComponent,
)
from ..core.ecs import container_of
from ..core.edges import Contains, ExitTo
from .room_summary import RoomExit


@dataclass(frozen=True)
class PerceivedEntity:
    id: str
    name: str
    is_character: bool
    contents: tuple[PerceivedEntity, ...] = ()


@dataclass(frozen=True)
class Perception:
    can_perceive: bool
    room_id: str | None = None
    entities: tuple[PerceivedEntity, ...] = ()
    exits: tuple[RoomExit, ...] = ()


_BLOCKING_COMPONENTS = (SuspendedComponent, DeadComponent, SleepingComponent, DownedComponent)


def _name(entity: Entity) -> str:
    if entity.has_component(IdentityComponent):
        return entity.get_component(IdentityComponent).name
    return "something"


def _reveals_contents(entity: Entity) -> bool:
    if not entity.has_component(ContainerComponent):
        return False
    container = entity.get_component(ContainerComponent)
    return container.open or container.transparent


def _is_hidden(entity: Entity) -> bool:
    if not entity.has_component(StealthComponent):
        return False
    stealth = entity.get_component(StealthComponent)
    return stealth.hiding and stealth.visibility_level <= stealth.hidden_threshold


def _visible_children(
    world: World, entity: Entity, *, recurse: bool
) -> tuple[PerceivedEntity, ...]:
    perceived: list[PerceivedEntity] = []
    for edge, child_id in entity.get_relationships(Contains):
        if not edge.visible:
            continue
        child = world.get_entity(child_id)
        if _is_hidden(child):
            continue
        nested: tuple[PerceivedEntity, ...] = ()
        if recurse and _reveals_contents(child):
            nested = _visible_children(world, child, recurse=False)
        perceived.append(
            PerceivedEntity(
                id=str(child_id),
                name=_name(child),
                is_character=child.has_component(CharacterComponent),
                contents=nested,
            )
        )
    return tuple(sorted(perceived, key=lambda e: (not e.is_character, e.name)))


def perceive(world: World, character: Entity) -> Perception:
    """Return what ``character`` perceives in its current room."""
    if character.has_component(PerceptionComponent):
        perception = character.get_component(PerceptionComponent)
        if not perception.active:
            return Perception(can_perceive=False)
    if any(character.has_component(component) for component in _BLOCKING_COMPONENTS):
        return Perception(can_perceive=False)

    room_id = container_of(character)
    if room_id is None:
        return Perception(can_perceive=True)

    room = world.get_entity(room_id)
    self_id = str(character.id)
    entities = tuple(e for e in _visible_children(world, room, recurse=True) if e.id != self_id)
    exits = tuple(
        sorted(
            (
                RoomExit(direction=edge.direction, to_room_id=str(target), locked=edge.locked)
                for edge, target in room.get_relationships(ExitTo)
                if not edge.hidden
            ),
            key=lambda e: e.direction,
        )
    )
    return Perception(can_perceive=True, room_id=str(room_id), entities=entities, exits=exits)


__all__ = ["PerceivedEntity", "Perception", "perceive"]
