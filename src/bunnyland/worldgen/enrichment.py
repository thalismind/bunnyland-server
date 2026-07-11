"""Plugin-neutral helpers for declarative generation enrichers."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.components import CharacterComponent, IdentityComponent, RoomComponent
from ..core.generation import GenerationRequest

_RESOURCE_TYPES = (
    "wood",
    "stone",
    "metal",
    "ore",
    "food",
    "water",
    "fuel",
    "scrap",
    "medicine",
    "bone",
    "hide",
    "sap",
)


@dataclass(frozen=True)
class GenerationContext:
    """A read-only semantic view of one normalized generation request."""

    entity_kind: str
    description: str
    tags: tuple[str, ...]
    wants: tuple[str, ...]
    needs: tuple[str, ...]
    seed: str
    entity_key: str
    entity_id: str
    room_id: str
    room_key: str
    object_key: str
    character_key: str
    species: str
    biome: str
    indoor: bool
    world_epoch: int
    name: str
    is_room: bool
    is_character: bool

    @classmethod
    def from_request(cls, request: GenerationRequest) -> GenerationContext:
        base_components = tuple(request.context.get("base_components", ()))
        room = next(
            (component for component in base_components if isinstance(component, RoomComponent)),
            None,
        )
        character = next(
            (
                component
                for component in base_components
                if isinstance(component, CharacterComponent)
            ),
            None,
        )
        identity = next(
            (
                component
                for component in base_components
                if isinstance(component, IdentityComponent)
            ),
            None,
        )
        wants = tuple(dict.fromkeys(request.capabilities))
        entity_id = request.request_id
        room_key = str(request.context.get("room_key", request.source_key))
        room_id = str(request.context.get("room_id", room_key))
        name = identity.name if identity is not None else request.source_key
        return cls(
            entity_kind=request.entity_kind,
            description=request.description,
            tags=request.tags,
            wants=wants,
            needs=(),
            seed=request.source_seed,
            entity_key=request.source_key,
            entity_id=entity_id,
            room_id=room_id,
            room_key=request.source_key if room is not None else room_key,
            object_key=request.source_key,
            character_key=request.source_key,
            species=(
                character.species
                if character is not None
                else str(request.context.get("species", request.entity_kind))
            ),
            biome=(room.biome if room is not None else str(request.context.get("biome", ""))),
            indoor=(
                room.indoor if room is not None else bool(request.context.get("indoor", False))
            ),
            world_epoch=int(request.context.get("world_epoch", 0)),
            name=name,
            is_room=room is not None or request.entity_kind == "room",
            is_character=character is not None or request.entity_kind == "character",
        )

    @property
    def generation(self) -> GenerationContext:
        return self

    @property
    def intent(self) -> str:
        return self.description

    @property
    def is_object(self) -> bool:
        return not self.is_room and not self.is_character


def generation_wants(context: GenerationContext, *names: str) -> bool:
    wanted = {value.casefold() for value in (*context.wants, *context.needs)}
    return any(name.casefold() in wanted for name in names)


def generation_mentions(context: GenerationContext, *terms: str) -> bool:
    text = " ".join(
        (
            context.entity_kind,
            context.description,
            *context.tags,
            *context.wants,
            *context.needs,
        )
    ).casefold()
    return any(term.casefold() in text for term in terms)


def generation_resource_type(context: GenerationContext) -> str:
    text = " ".join(
        (context.entity_kind, context.description, *context.tags, *context.wants)
    ).casefold()
    return next((value for value in _RESOURCE_TYPES if value in text), "scrap")


def generation_crop_type(context: GenerationContext) -> str:
    text = " ".join((context.description, *context.tags, *context.wants)).casefold()
    for suffix in (" seeds", " seed"):
        if suffix in text:
            return text.split(suffix, 1)[0].rsplit(" ", 1)[-1] or "turnip"
    return "turnip"


def generation_expansion_trigger(context: GenerationContext) -> str:
    if generation_wants(context, "bunnyland.daggersim.rumor"):
        return "rumor"
    if generation_wants(context, "bunnyland.dragonsim.quest"):
        return "quest"
    return "worldgen"


def generation_orbital_body_type(context: GenerationContext) -> str:
    if generation_mentions(context, "moon"):
        return "moon"
    if generation_mentions(context, "asteroid"):
        return "asteroid-belt"
    if generation_mentions(context, "station"):
        return "station"
    return "planet"


def generation_generated_id(context: GenerationContext, suffix: str) -> str:
    return f"generated-{context.entity_key}-{suffix}"


def generation_trade_faction(context: GenerationContext) -> str:
    if generation_mentions(context, "trader"):
        return "generated-trader"
    if generation_mentions(context, "faction"):
        return "generated-faction"
    return "generated-colony"


def generation_animal_species(context: GenerationContext) -> str:
    for species in ("chicken", "cow", "goat", "sheep", "duck", "rabbit"):
        if generation_mentions(context, species):
            return species
    return context.entity_kind if context.entity_kind != "object" else "animal"


def generation_fish_type(context: GenerationContext) -> str:
    for fish_type in ("trout", "bass", "catfish", "salmon", "carp"):
        if generation_mentions(context, fish_type):
            return fish_type
    return "trout"


def generation_season(context: GenerationContext) -> str:
    for season in ("spring", "summer", "autumn", "winter"):
        if generation_mentions(context, season):
            return season
    return "spring"


__all__ = [
    "GenerationContext",
    "generation_animal_species",
    "generation_crop_type",
    "generation_expansion_trigger",
    "generation_fish_type",
    "generation_generated_id",
    "generation_mentions",
    "generation_orbital_body_type",
    "generation_resource_type",
    "generation_season",
    "generation_trade_faction",
    "generation_wants",
]
