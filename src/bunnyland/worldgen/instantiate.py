"""Validate a world proposal and instantiate it into the Relics world (spec 22.2).

This is the boundary the LLM never crosses: it proposes; the engine validates schema and
references, then creates entities, components, edges, and controllers. Emits
``WorldGeneratedEvent`` when done.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from relics import EntityId

from ..core.components import (
    ActionPointsComponent,
    AffectComponent,
    CharacterComponent,
    ContainerComponent,
    DescriptionComponent,
    FocusPointsComponent,
    IdentityComponent,
    InitiativeComponent,
    LightComponent,
    MemoryProfileComponent,
    PortableComponent,
    ReadableComponent,
    RoomComponent,
    TemperatureComponent,
    WritableComponent,
)
from ..core.controllers import LLMControllerComponent
from ..core.ecs import spawn_entity
from ..core.edges import ContainmentMode, Contains, ExitTo
from ..core.events import WorldGeneratedEvent
from ..mechanics.consumables import ConsumableComponent, DrinkableComponent, FoodComponent
from ..mechanics.meter import Meter
from ..mechanics.needs import HungerComponent, ThirstComponent
from ..mechanics.persona import GoalComponent, TraitSetComponent
from .proposal import CharacterSpec, ObjectSpec, WorldProposal

if TYPE_CHECKING:
    from ..core.world_actor import WorldActor


@dataclass
class InstantiatedWorld:
    rooms: dict[str, EntityId] = field(default_factory=dict)
    objects: dict[str, EntityId] = field(default_factory=dict)
    characters: dict[str, EntityId] = field(default_factory=dict)
    #: The literal DM system prompt that built the world ("" for deterministic builders).
    prompt: str = ""


def validate_proposal(proposal: WorldProposal) -> list[str]:
    """Return a list of validation errors ([] means valid)."""
    errors: list[str] = []
    room_keys = {r.key for r in proposal.rooms}
    if len(room_keys) != len(proposal.rooms):
        errors.append("duplicate room keys")
    if not proposal.rooms:
        errors.append("proposal has no rooms")

    object_keys = {o.key for o in proposal.objects}
    if len(object_keys) != len(proposal.objects):
        errors.append("duplicate object keys")

    for exit_ in proposal.exits:
        if exit_.from_key not in room_keys:
            errors.append(f"exit from unknown room {exit_.from_key!r}")
        if exit_.to_key not in room_keys:
            errors.append(f"exit to unknown room {exit_.to_key!r}")
    for obj in proposal.objects:
        if obj.room_key not in room_keys:
            errors.append(f"object {obj.key!r} in unknown room {obj.room_key!r}")
    for character in proposal.characters:
        if character.room_key not in room_keys:
            errors.append(f"character {character.key!r} in unknown room {character.room_key!r}")
        if character.controller not in ("llm", "suspended"):
            errors.append(f"character {character.key!r} has invalid controller")
    return errors


def _object_components(spec: ObjectSpec) -> list:
    components = [IdentityComponent(name=spec.name, kind=spec.kind)]
    if spec.portable:
        components.append(PortableComponent(can_pick_up=True))
    if spec.kind == "food":
        components.append(FoodComponent(nutrition=spec.nutrition, satiety=spec.satiety))
        components.append(ConsumableComponent())
    elif spec.kind == "water":
        components.append(DrinkableComponent(hydration=spec.hydration))
        if not spec.renewable:
            components.append(ConsumableComponent())
    elif spec.kind == "container":
        components.append(ContainerComponent(open=spec.open))
    elif spec.kind == "paper":
        components.append(ReadableComponent())
        if spec.writable:
            components.append(WritableComponent(erasable=True))
    return components


def _character_components(spec: CharacterSpec) -> list:
    components = [
        IdentityComponent(name=spec.name, kind="character"),
        DescriptionComponent(short=f"{spec.name}, a {spec.species}"),
        CharacterComponent(species=spec.species),
        ActionPointsComponent(current=5.0, maximum=5.0),
        FocusPointsComponent(current=3.0, maximum=3.0),
        InitiativeComponent(score=1.0),
        AffectComponent(),
    ]
    if spec.with_needs:
        components.append(HungerComponent(meter=Meter()))
        components.append(ThirstComponent(meter=Meter()))
    if spec.with_memory:
        components.append(MemoryProfileComponent(vector_collection=f"mem:{spec.key}"))
    if spec.traits:
        components.append(TraitSetComponent(traits=tuple(spec.traits)))
    if spec.goals:
        components.append(GoalComponent(active_goals=tuple(spec.goals)))
    return components


async def instantiate(actor: WorldActor, proposal: WorldProposal) -> InstantiatedWorld:
    """Validate then build the proposed world. Raises ValueError on validation failure."""
    errors = validate_proposal(proposal)
    if errors:
        raise ValueError("invalid world proposal: " + "; ".join(errors))

    world = actor.world
    result = InstantiatedWorld()

    async with actor._lock:
        for room in proposal.rooms:
            components = [RoomComponent(title=room.title, biome=room.biome, indoor=room.indoor)]
            if room.light is not None:
                components.append(LightComponent(level=room.light))
            if room.celsius is not None:
                components.append(TemperatureComponent(celsius=room.celsius))
            result.rooms[room.key] = spawn_entity(world, components).id

        for exit_ in proposal.exits:
            world.get_entity(result.rooms[exit_.from_key]).add_relationship(
                ExitTo(direction=exit_.direction, locked=exit_.locked),
                result.rooms[exit_.to_key],
            )

        for obj in proposal.objects:
            entity = spawn_entity(world, _object_components(obj))
            world.get_entity(result.rooms[obj.room_key]).add_relationship(
                Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
            )
            result.objects[obj.key] = entity.id

        for character in proposal.characters:
            entity = spawn_entity(world, _character_components(character))
            world.get_entity(result.rooms[character.room_key]).add_relationship(
                Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
            )
            result.characters[character.key] = entity.id
            _wire_controller(actor, entity.id, character)

        await actor.bus.publish(
            WorldGeneratedEvent(
                event_id=uuid4().hex,
                world_epoch=actor.epoch,
                created_at=datetime.now(UTC),
                seed=proposal.seed,
                room_count=len(result.rooms),
                character_count=len(result.characters),
            )
        )
    return result


def _wire_controller(actor: WorldActor, character_id: EntityId, spec: CharacterSpec) -> None:
    if spec.controller == "llm":
        controller = spawn_entity(
            actor.world,
            [LLMControllerComponent(profile_name=spec.llm_profile, model=spec.llm_model)],
        )
        actor.assign_controller(character_id, controller.id)
    else:  # suspended / claimable
        controller = spawn_entity(actor.world)
        actor.suspend(character_id, controller.id, reason="unclaimed")


__all__ = ["InstantiatedWorld", "instantiate", "validate_proposal"]
