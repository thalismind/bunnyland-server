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

from ..core.commands import SubmittedCommand
from ..core.components import (
    CharacterComponent,
    ContainerComponent,
    DoorComponent,
    IdentityComponent,
    PortableComponent,
    RoomComponent,
)
from ..core.ecs import container_of, parse_entity_id, replace_component
from ..core.events import DomainEvent, EventVisibility
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected

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


@pydantic_dataclass(frozen=True)
class SpriteScale(Component):
    """Uniform display scale for the sprite when compositing the scene.

    ``1.0`` is the image's natural size. Because sprites come from different sources at
    different pixel sizes, a client normalizes them by scaling each before drawing it
    into the shared room image.
    """

    scale: float = 1.0


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
            if not entity.has_component(SpriteScale):
                entity.add_component(SpriteScale())
        return []


class SpriteMovedEvent(DomainEvent):
    """A character repositioned its sprite within its current room."""

    x: float
    y: float


class MoveSpriteHandler:
    """Set a character's in-room sprite position.

    This is the toon client's movement verb: it only changes where the character's
    sprite sits within its room (X/Y), never which room it occupies. The client applies
    the move optimistically and syncs on a throttled interval by submitting this command
    with **zero action/focus cost**, so in-room movement is free.
    """

    command_type = "move-sprite"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None or not ctx.world.has_entity(character_id):
            return rejected("invalid character id")
        try:
            x = float(command.payload["x"])
            y = float(command.payload["y"])
        except (KeyError, TypeError, ValueError):
            return rejected("invalid x/y position")

        character = ctx.entity(character_id)
        replace_component(character, SpritePosition(x=x, y=y))
        room_id = container_of(character)
        return ok(
            SpriteMovedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(room_id) if room_id is not None else None,
                    target_ids=(str(character_id),),
                    x=x,
                    y=y,
                )
            )
        )


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
    "MoveSpriteHandler",
    "SpriteBackfillConsequence",
    "SpriteImage",
    "SpriteLayer",
    "SpriteMovedEvent",
    "SpritePosition",
    "SpriteScale",
    "default_layer_for",
    "install_toonsim",
]
