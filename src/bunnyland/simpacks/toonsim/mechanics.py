"""Toon-sim: presentation data for a 2D sprite client.

This pack attaches the data a graphical client needs to draw the world as stacked
sprites, without the engine itself caring about any of it:

- :class:`SpritePositionComponent` -- float X/Y placement within the entity's room.
- :class:`SpriteImageComponent` -- the sprite asset (a URL and/or inline data).
- :class:`SpriteLayerComponent` -- integer draw order (z-index), low draws first.
- :class:`ToonRoomComponent` -- room-level hints for toon-client presentation.

A single consequence backfills these components on renderable entities (rooms,
furniture, items, doors, characters) that lack them, choosing a default layer by
category so rooms sit at the back, furniture above them, interactive items and doors
above that, and characters on top. Explicit values set by content or worldgen are never
overwritten. Client-side rendering, animation, particles, and effects are out of scope
here -- this only produces the data they consume.
"""

from __future__ import annotations

from hashlib import sha256

from pydantic.dataclasses import dataclass as pydantic_dataclass
from relics import Component, Edge, Entity, World

from ...core.commands import SubmittedCommand
from ...core.components import (
    CharacterComponent,
    ContainerComponent,
    DoorComponent,
    IdentityComponent,
    PortableComponent,
    RoomComponent,
)
from ...core.ecs import container_of, parse_entity_id, replace_component
from ...core.edges import Contains
from ...core.events import DomainEvent, EventVisibility
from ...core.handlers import HandlerContext, HandlerResult, ok, rejected

# Draw layers, spaced so new tiers can slot between existing ones (spec: low draws
# first, so rooms are the background and characters sit on top).
LAYER_BACKGROUND = 0  # rooms
LAYER_FURNITURE = 10  # furniture and static background props
LAYER_ITEM = 20  # interactive items and doors
LAYER_CHARACTER = 30  # characters
LAYER_EFFECT = 40  # reserved for client-side effects/particles (added later)

ROOM_WIDTH = 100.0
ROOM_HEIGHT = 100.0

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

SURFACE_KINDS = frozenset({"table", "desk", "shelf", "counter", "workbench", "workstation"})


@pydantic_dataclass(frozen=True)
class SpritePositionComponent(Component):
    """Float X/Y placement of the sprite within its room's background."""

    x: float = 0.0
    y: float = 0.0


@pydantic_dataclass(frozen=True)
class SpriteImageComponent(Component):
    """The sprite asset: a URL, inline data (e.g. a data URI), or both."""

    url: str = ""
    data: str = ""


@pydantic_dataclass(frozen=True)
class SpriteLayerComponent(Component):
    """Integer draw order. Lower layers render first (further back)."""

    layer: int = LAYER_ITEM


@pydantic_dataclass(frozen=True)
class SpriteScaleComponent(Component):
    """Uniform display scale for the sprite when compositing the scene.

    ``1.0`` is the image's natural size. Because sprites come from different sources at
    different pixel sizes, a client normalizes them by scaling each before drawing it
    into the shared room image.
    """

    scale: float = 1.0


@pydantic_dataclass(frozen=True)
class SpriteBoundsComponent(Component):
    """Axis-aligned sprite footprint in the same coordinate space as ``SpritePositionComponent``."""

    width: float = 4.0
    height: float = 4.0
    solid: bool = False


@pydantic_dataclass(frozen=True)
class ToonRoomComponent(Component):
    """Room-level presentation hints consumed by the toon client."""

    default_start: bool = False


@pydantic_dataclass(frozen=True)
class PlacedOn(Edge):
    """Presentation edge: the source item is visually resting on the target surface."""

    surface: str = "top"


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


def default_bounds_for(entity: Entity) -> SpriteBoundsComponent | None:
    """Return the default sprite footprint for ``entity``."""
    if entity.has_component(RoomComponent):
        return SpriteBoundsComponent(width=ROOM_WIDTH, height=ROOM_HEIGHT)
    if entity.has_component(CharacterComponent):
        return SpriteBoundsComponent(width=5.0, height=8.0, solid=True)

    kind = (
        entity.get_component(IdentityComponent).kind
        if entity.has_component(IdentityComponent)
        else None
    )
    if kind in SURFACE_KINDS:
        return SpriteBoundsComponent(width=22.0, height=12.0, solid=True)
    if kind in FURNITURE_KINDS or entity.has_component(ContainerComponent):
        return SpriteBoundsComponent(width=14.0, height=10.0, solid=True)
    if entity.has_component(DoorComponent):
        return SpriteBoundsComponent(width=10.0, height=8.0)
    if entity.has_component(PortableComponent):
        return SpriteBoundsComponent(width=4.0, height=4.0)
    return None


class SpriteBackfillConsequence:
    """Attach sprite components to renderable entities that are missing them.

    Querying ``with_none([SpriteLayerComponent])`` keeps this cheap: once an entity is tagged it
    drops out of the scan. Non-renderable entities are skipped (and re-checked on later
    ticks, which is fine -- they are few and the check is a handful of component lookups).
    Each component is added independently and only when absent, so positions or images
    assigned elsewhere are left untouched.
    """

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        for entity in list(world.query().with_none([SpriteLayerComponent]).execute_entities()):
            layer = default_layer_for(entity)
            if layer is None:
                continue
            entity.add_component(SpriteLayerComponent(layer=layer))
            if not entity.has_component(SpritePositionComponent):
                entity.add_component(SpritePositionComponent())
            if not entity.has_component(SpriteImageComponent):
                entity.add_component(SpriteImageComponent())
            if not entity.has_component(SpriteScaleComponent):
                entity.add_component(SpriteScaleComponent())
            if not entity.has_component(SpriteBoundsComponent):
                bounds = default_bounds_for(entity)
                if bounds is not None:
                    entity.add_component(bounds)
        return []


def _kind(entity: Entity) -> str:
    if entity.has_component(IdentityComponent):
        return entity.get_component(IdentityComponent).kind
    return ""


def _stable_unit(*parts: object) -> float:
    digest = sha256("|".join(str(part) for part in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF


def _stable_range(low: float, high: float, *parts: object) -> float:
    return low + (high - low) * _stable_unit(*parts)


def _clamp_position(x: float, y: float, bounds: SpriteBoundsComponent) -> SpritePositionComponent:
    half_w = bounds.width / 2.0
    half_h = bounds.height / 2.0
    return SpritePositionComponent(
        x=max(half_w, min(ROOM_WIDTH - half_w, x)),
        y=max(half_h, min(ROOM_HEIGHT - half_h, y)),
    )


def _surface_entities(world: World, room: Entity, exclude_id) -> list[Entity]:
    surfaces: list[Entity] = []
    for _edge, child_id in room.get_relationships(Contains):
        if child_id == exclude_id or not world.has_entity(child_id):
            continue
        child = world.get_entity(child_id)
        if _kind(child) in SURFACE_KINDS and child.has_component(SpritePositionComponent):
            surfaces.append(child)
    return sorted(surfaces, key=lambda entity: str(entity.id))


def _position_on_surface(entity: Entity, surface: Entity) -> SpritePositionComponent:
    surface_pos = surface.get_component(SpritePositionComponent)
    surface_bounds = surface.get_component(SpriteBoundsComponent)
    entity_bounds = entity.get_component(SpriteBoundsComponent)
    usable_w = max(0.0, surface_bounds.width - entity_bounds.width)
    usable_h = max(0.0, surface_bounds.height - entity_bounds.height)
    x = surface_pos.x - usable_w / 2.0 + _stable_range(0.0, usable_w, entity.id, "x")
    y = surface_pos.y - usable_h / 2.0 + _stable_range(0.0, usable_h, entity.id, "y")
    return _clamp_position(x, y, entity_bounds)


def _aabb(
    position: SpritePositionComponent, bounds: SpriteBoundsComponent
) -> tuple[float, float, float, float]:
    half_w = bounds.width / 2.0
    half_h = bounds.height / 2.0
    return (
        position.x - half_w,
        position.y - half_h,
        position.x + half_w,
        position.y + half_h,
    )


def _aabb_overlaps(
    left: tuple[float, float, float, float], right: tuple[float, float, float, float]
) -> bool:
    return left[0] < right[2] and left[2] > right[0] and left[1] < right[3] and left[3] > right[1]


def _inside_room(
    position: SpritePositionComponent,
    bounds: SpriteBoundsComponent,
    room_bounds: SpriteBoundsComponent,
) -> bool:
    left, top, right, bottom = _aabb(position, bounds)
    return (
        left >= 0.0 and top >= 0.0 and right <= room_bounds.width and bottom <= room_bounds.height
    )


def _solid_collision(
    world: World,
    character: Entity,
    room: Entity,
    position: SpritePositionComponent,
    bounds: SpriteBoundsComponent,
) -> bool:
    moving = _aabb(position, bounds)
    for _edge, child_id in room.get_relationships(Contains):
        if child_id == character.id or not world.has_entity(child_id):
            continue
        child = world.get_entity(child_id)
        if not child.has_component(SpritePositionComponent):
            continue
        child_bounds = (
            child.get_component(SpriteBoundsComponent)
            if child.has_component(SpriteBoundsComponent)
            else default_bounds_for(child)
        )
        if child_bounds is None or not child_bounds.solid:
            continue
        if _aabb_overlaps(
            moving, _aabb(child.get_component(SpritePositionComponent), child_bounds)
        ):
            return True
    return False


def _generated_position(
    world: World, entity: Entity, room: Entity, event_key: str
) -> SpritePositionComponent:
    bounds = entity.get_component(SpriteBoundsComponent)
    kind = _kind(entity)
    if entity.has_component(CharacterComponent):
        return _clamp_position(
            _stable_range(30.0, 70.0, event_key, "character-x"),
            _stable_range(55.0, 86.0, event_key, "character-y"),
            bounds,
        )
    if entity.has_component(DoorComponent) or kind == "door":
        name = (
            entity.get_component(IdentityComponent).name.lower()
            if entity.has_component(IdentityComponent)
            else ""
        )
        if "north" in name:
            return _clamp_position(50.0, 4.0, bounds)
        if "south" in name:
            return _clamp_position(50.0, 96.0, bounds)
        if "east" in name:
            return _clamp_position(96.0, 50.0, bounds)
        if "west" in name:
            return _clamp_position(4.0, 50.0, bounds)
        return _clamp_position(
            _stable_range(10.0, 90.0, event_key, "door-x"),
            _stable_range(8.0, 16.0, event_key, "door-y"),
            bounds,
        )
    if kind in FURNITURE_KINDS or entity.has_component(ContainerComponent):
        return _clamp_position(
            _stable_range(14.0, 86.0, event_key, "furniture-x"),
            _stable_range(18.0, 72.0, event_key, "furniture-y"),
            bounds,
        )
    surfaces = _surface_entities(world, room, entity.id)
    if entity.has_component(PortableComponent) and surfaces:
        surface = surfaces[int(_stable_unit(event_key, "surface") * len(surfaces)) % len(surfaces)]
        if not entity.has_relationship(PlacedOn, surface.id):
            entity.add_relationship(PlacedOn(), surface.id)
        return _position_on_surface(entity, surface)
    return _clamp_position(
        _stable_range(18.0, 82.0, event_key, "item-x"),
        _stable_range(58.0, 90.0, event_key, "item-y"),
        bounds,
    )


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
        room_id = container_of(character)
        if room_id is None or not ctx.world.has_entity(room_id):
            return rejected("character is not in a room")
        room = ctx.entity(room_id)
        bounds = (
            character.get_component(SpriteBoundsComponent)
            if character.has_component(SpriteBoundsComponent)
            else default_bounds_for(character)
        )
        if bounds is None:
            return rejected("character has no sprite bounds")
        if not character.has_component(SpriteBoundsComponent):
            replace_component(character, bounds)
        position = SpritePositionComponent(x=x, y=y)
        room_bounds = (
            room.get_component(SpriteBoundsComponent)
            if room.has_component(SpriteBoundsComponent)
            else SpriteBoundsComponent(width=ROOM_WIDTH, height=ROOM_HEIGHT)
        )
        if not _inside_room(position, bounds, room_bounds):
            return rejected("position is outside room bounds")
        if _solid_collision(ctx.world, character, room, position, bounds):
            return rejected("position is blocked")
        replace_component(character, position)
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
    "PlacedOn",
    "SpriteBackfillConsequence",
    "SpriteBoundsComponent",
    "SpriteImageComponent",
    "SpriteLayerComponent",
    "SpriteMovedEvent",
    "SpritePositionComponent",
    "SpriteScaleComponent",
    "SURFACE_KINDS",
    "ToonRoomComponent",
    "default_bounds_for",
    "default_layer_for",
    "install_toonsim",
]
