"""Toon-sim: presentation data for a 2D sprite client.

This pack attaches the data a graphical client needs to draw the world as stacked
sprites, without the engine itself caring about any of it:

- :class:`SpritePosition` -- float X/Y placement within the entity's room.
- :class:`SpriteImage` -- the sprite asset (a URL and/or inline data).
- :class:`SpriteLayer` -- integer draw order (z-index), low draws first.

A single consequence backfills these components on renderable entities (rooms,
furniture, items, doors, characters) that lack them, choosing a default layer by
category so rooms sit at the back, furniture above them, interactive items and doors
above that, and characters on top. Explicit values set by content or worldgen are never
overwritten. Client-side rendering, animation, particles, and effects are out of scope
here -- this only produces the data they consume.
"""

from __future__ import annotations

from pydantic.dataclasses import dataclass as pydantic_dataclass
from relics import Component, Entity, World

from ..core.components import (
    CharacterComponent,
    ContainerComponent,
    DoorComponent,
    IdentityComponent,
    PortableComponent,
    RoomComponent,
)
from ..core.events import DomainEvent

# Draw layers, spaced so new tiers can slot between existing ones (spec: low draws
# first, so rooms are the background and characters sit on top).
LAYER_BACKGROUND = 0  # rooms
LAYER_FURNITURE = 10  # furniture and static background props
LAYER_ITEM = 20  # interactive items and doors
LAYER_CHARACTER = 30  # characters
LAYER_EFFECT = 40  # reserved for client-side effects/particles (added later)

#: Kinds that read as furniture/background props but carry no distinguishing component.
FURNITURE_KINDS = frozenset(
    {
        "chair",
        "table",
        "bed",
        "art",
        "window",
        "workstation",
        "sofa",
        "couch",
        "shelf",
        "desk",
        "lamp",
        "rug",
        "cabinet",
        "dresser",
        "stool",
        "bench",
    }
)


@pydantic_dataclass(frozen=True)
class SpritePosition(Component):
    """Float X/Y placement of the sprite within its room's background."""

    x: float = 0.0
    y: float = 0.0


@pydantic_dataclass(frozen=True)
class SpriteImage(Component):
    """The sprite asset: a URL, inline data (e.g. a data URI), or both."""

    url: str = ""
    data: str = ""


@pydantic_dataclass(frozen=True)
class SpriteLayer(Component):
    """Integer draw order. Lower layers render first (further back)."""

    layer: int = LAYER_ITEM


def default_layer_for(entity: Entity) -> int | None:
    """Return the default draw layer for ``entity``, or ``None`` if not renderable.

    Categories are checked from the back of the scene forward. Abstract entities
    (factions, quests, the world clock, ...) match nothing and return ``None`` so they
    never receive sprite components.
    """
    if entity.has_component(RoomComponent):
        return LAYER_BACKGROUND
    if entity.has_component(CharacterComponent):
        return LAYER_CHARACTER

    kind = (
        entity.get_component(IdentityComponent).kind
        if entity.has_component(IdentityComponent)
        else None
    )
    if kind in FURNITURE_KINDS or entity.has_component(ContainerComponent):
        return LAYER_FURNITURE
    if entity.has_component(DoorComponent) or entity.has_component(PortableComponent):
        return LAYER_ITEM
    return None


class SpriteBackfillConsequence:
    """Attach sprite components to renderable entities that are missing them.

    Querying ``with_none([SpriteLayer])`` keeps this cheap: once an entity is tagged it
    drops out of the scan. Non-renderable entities are skipped (and re-checked on later
    ticks, which is fine -- they are few and the check is a handful of component lookups).
    Each component is added independently and only when absent, so positions or images
    assigned elsewhere are left untouched.
    """

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        for entity in list(world.query().with_none([SpriteLayer]).execute_entities()):
            layer = default_layer_for(entity)
            if layer is None:
                continue
            entity.add_component(SpriteLayer(layer=layer))
            if not entity.has_component(SpritePosition):
                entity.add_component(SpritePosition())
            if not entity.has_component(SpriteImage):
                entity.add_component(SpriteImage())
        return []


def install_toonsim(actor) -> None:
    """Register the sprite backfill consequence on an actor."""
    actor.register_consequence(SpriteBackfillConsequence())


__all__ = [
    "FURNITURE_KINDS",
    "LAYER_BACKGROUND",
    "LAYER_CHARACTER",
    "LAYER_EFFECT",
    "LAYER_FURNITURE",
    "LAYER_ITEM",
    "SpriteBackfillConsequence",
    "SpriteImage",
    "SpriteLayer",
    "SpritePosition",
    "default_layer_for",
    "install_toonsim",
]
