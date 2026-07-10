"""Validate a world proposal and instantiate it into the Relics world (spec 22.2).

This is the boundary the LLM never crosses: it proposes; the engine validates schema and
references, then creates entities, components, edges, and controllers. Emits
``WorldGeneratedEvent`` when done.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field, replace
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
    GenerationIntentComponent,
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
from ..core.controllers import (
    BehaviorControllerComponent,
    LLMControllerComponent,
    ScriptedControllerComponent,
)
from ..core.ecs import parse_entity_id, spawn_entity
from ..core.edges import ContainmentMode, Contains, ExitTo
from ..core.events import (
    CharacterGeneratedEvent,
    GeneratedEntityEvent,
    ObjectGeneratedEvent,
    RoomGeneratedEvent,
    WorldGeneratedEvent,
)
from ..core.generation import (
    GenerationError,
    GenerationPipeline,
    GenerationPlan,
    GenerationRequest,
)
from ..llm_agents.behavior_tree import behavior_tree_names
from ..llm_agents.scripts import script_names
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
        if character.controller not in ("llm", "suspended", "behavioral", "scripted"):
            errors.append(f"character {character.key!r} has invalid controller")
        elif character.controller == "behavioral" and (
            character.behavior_name not in behavior_tree_names()
        ):
            errors.append(
                f"character {character.key!r} has unknown behavior {character.behavior_name!r}"
            )
        elif character.controller == "scripted" and character.script_name not in script_names():
            errors.append(
                f"character {character.key!r} has unknown script {character.script_name!r}"
            )
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


def _memory_collection_name(key: str) -> str:
    return f"mem-{key}"


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
        components.append(
            MemoryProfileComponent(vector_collection=_memory_collection_name(spec.key))
        )
    if spec.traits:
        components.append(TraitSetComponent(traits=tuple(spec.traits)))
    if spec.goals:
        components.append(GoalComponent(active_goals=tuple(spec.goals)))
    return components


def _generation_tags(*values: str, extra: tuple[str, ...] = ()) -> tuple[str, ...]:
    tags: list[str] = []
    for value in (*values, *extra):
        clean = value.strip()
        if clean and clean not in tags:
            tags.append(clean)
    return tuple(tags)


def _generation_intent(
    base: GenerationIntentComponent,
    *,
    description: str,
    tags: tuple[str, ...] = (),
    wants: tuple[str, ...] = (),
    needs: tuple[str, ...] = (),
    source_seed: str,
    source_key: str,
    entity_kind: str,
) -> GenerationIntentComponent:
    return GenerationIntentComponent(
        description=base.description or description,
        tags=_generation_tags(*tags, extra=base.tags),
        wants=_generation_tags(*wants, extra=base.wants),
        needs=_generation_tags(*needs, extra=base.needs),
        source_seed=source_seed,
        source_key=source_key,
        entity_kind=entity_kind,
    )


async def _cooperative_components(
    actor: WorldActor,
    generation: GenerationIntentComponent,
    components: list,
) -> tuple[list, GenerationIntentComponent, GenerationPlan]:
    request = GenerationRequest(
        entity_kind=generation.entity_kind,
        description=generation.description,
        capabilities=(*generation.wants, *generation.needs),
        tags=generation.tags,
        source_seed=generation.source_seed,
        source_key=generation.source_key,
        context={"base_components": tuple(components), "world_epoch": actor.epoch},
    )
    plan = await GenerationPipeline(actor.plugins).compile(
        request,
        base_components=tuple(components),
    )
    finalized = replace(
        generation,
        wants=plan.request.capabilities,
        unmet_capabilities=plan.unmet_capabilities,
    )
    return [*plan.components, finalized], finalized, plan


async def _finalize_legacy_hooks(actor: WorldActor, event: GeneratedEntityEvent) -> None:
    method_name = {
        RoomGeneratedEvent: "_on_room",
        ObjectGeneratedEvent: "_on_object",
        CharacterGeneratedEvent: "_on_character",
    }.get(type(event))
    for hook in actor._worldgen_hooks:
        handler = getattr(hook, method_name, None) if method_name is not None else None
        handler = handler or getattr(hook, "_on_entity", None)
        if handler is None and isinstance(event, (RoomGeneratedEvent, ObjectGeneratedEvent)):
            handler = getattr(hook, "_on_site", None)
        if handler is None and callable(hook):
            handler = hook
        if handler is not None:
            result = handler(event)
            if inspect.isawaitable(result):
                await result


def _validate_plan_edges(actor: WorldActor, plan: GenerationPlan) -> None:
    for edge_delta in plan.edges:
        target_id = edge_delta.target_id
        if isinstance(target_id, str):
            target_id = parse_entity_id(target_id)
        if target_id is None or not actor.world.has_entity(target_id):
            raise GenerationError(
                f"generation edge references missing entity {edge_delta.target_id!r}"
            )


def _apply_plan_edges(actor: WorldActor, entity, plan: GenerationPlan) -> None:
    for edge_delta in plan.edges:
        target_id = edge_delta.target_id
        if isinstance(target_id, str):
            target_id = parse_entity_id(target_id)
        entity.add_relationship(edge_delta.edge, target_id)


async def instantiate(actor: WorldActor, proposal: WorldProposal) -> InstantiatedWorld:
    """Validate then build the proposed world. Raises ValueError on validation failure."""
    errors = validate_proposal(proposal)
    if errors:
        raise ValueError("invalid world proposal: " + "; ".join(errors))

    world = actor.world
    result = InstantiatedWorld()
    room_plans: dict[str, tuple[list, GenerationIntentComponent, GenerationPlan]] = {}
    object_plans: dict[str, tuple[list, GenerationIntentComponent, GenerationPlan]] = {}
    character_plans: dict[str, tuple[list, GenerationIntentComponent, GenerationPlan]] = {}

    # Compile every declarative enrichment before mutating the ECS. A conflict or plugin
    # failure therefore aborts the proposal without leaving a partially generated world.
    for room in proposal.rooms:
        components = [RoomComponent(title=room.title, biome=room.biome, indoor=room.indoor)]
        if room.light is not None:
            components.append(LightComponent(level=room.light))
        if room.celsius is not None:
            components.append(TemperatureComponent(celsius=room.celsius))
        generation = _generation_intent(
            room.generation,
            description=room.title,
            tags=(room.biome, "indoor" if room.indoor else "outdoor"),
            source_seed=proposal.seed,
            source_key=room.key,
            entity_kind="room",
        )
        room_plans[room.key] = await _cooperative_components(actor, generation, components)
    for obj in proposal.objects:
        generation = _generation_intent(
            obj.generation,
            description=obj.name,
            tags=(obj.kind,),
            source_seed=proposal.seed,
            source_key=obj.key,
            entity_kind=obj.kind,
        )
        object_plans[obj.key] = await _cooperative_components(
            actor, generation, _object_components(obj)
        )
    for character in proposal.characters:
        generation = _generation_intent(
            character.generation,
            description=f"{character.name}, a {character.species}",
            tags=(character.species, *character.traits),
            source_seed=proposal.seed,
            source_key=character.key,
            entity_kind="character",
        )
        character_plans[character.key] = await _cooperative_components(
            actor, generation, _character_components(character)
        )
    for _components, _generation, plan in (
        *room_plans.values(),
        *object_plans.values(),
        *character_plans.values(),
    ):
        _validate_plan_edges(actor, plan)

    async with actor._lock:
        for room in proposal.rooms:
            components, generation, plan = room_plans[room.key]
            entity = spawn_entity(world, components)
            _apply_plan_edges(actor, entity, plan)
            result.rooms[room.key] = entity.id
            event = RoomGeneratedEvent(
                **actor._event_base(
                    seed=proposal.seed,
                    entity_id=str(entity.id),
                    entity_key=room.key,
                    entity_kind="room",
                    room_id=str(entity.id),
                    room_key=room.key,
                    generation=generation,
                    biome=room.biome,
                    indoor=room.indoor,
                )
            )
            await _finalize_legacy_hooks(actor, event)
            await actor.bus.publish(event)

        for exit_ in proposal.exits:
            world.get_entity(result.rooms[exit_.from_key]).add_relationship(
                ExitTo(direction=exit_.direction, locked=exit_.locked),
                result.rooms[exit_.to_key],
            )

        for obj in proposal.objects:
            components, generation, plan = object_plans[obj.key]
            entity = spawn_entity(world, components)
            _apply_plan_edges(actor, entity, plan)
            world.get_entity(result.rooms[obj.room_key]).add_relationship(
                Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
            )
            result.objects[obj.key] = entity.id
            event = ObjectGeneratedEvent(
                **actor._event_base(
                    seed=proposal.seed,
                    entity_id=str(entity.id),
                    entity_key=obj.key,
                    entity_kind=obj.kind,
                    object_key=obj.key,
                    room_id=str(result.rooms[obj.room_key]),
                    container_id=str(result.rooms[obj.room_key]),
                    containment_mode=ContainmentMode.ROOM_CONTENT.value,
                    generation=generation,
                )
            )
            await _finalize_legacy_hooks(actor, event)
            await actor.bus.publish(event)

        for character in proposal.characters:
            components, generation, plan = character_plans[character.key]
            entity = spawn_entity(world, components)
            _apply_plan_edges(actor, entity, plan)
            world.get_entity(result.rooms[character.room_key]).add_relationship(
                Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
            )
            result.characters[character.key] = entity.id
            _wire_controller(actor, entity.id, character)
            event = CharacterGeneratedEvent(
                **actor._event_base(
                    seed=proposal.seed,
                    entity_id=str(entity.id),
                    entity_key=character.key,
                    entity_kind="character",
                    character_key=character.key,
                    room_id=str(result.rooms[character.room_key]),
                    generation=generation,
                    species=character.species,
                )
            )
            await _finalize_legacy_hooks(actor, event)
            await actor.bus.publish(event)

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
            [
                LLMControllerComponent(
                    profile_name=spec.llm_profile,
                    model=spec.llm_model,
                    provider=spec.llm_provider,
                )
            ],
        )
        actor.assign_controller(character_id, controller.id)
    elif spec.controller == "behavioral":
        controller = spawn_entity(
            actor.world, [BehaviorControllerComponent(behavior_name=spec.behavior_name)]
        )
        actor.assign_controller(character_id, controller.id)
    elif spec.controller == "scripted":
        controller = spawn_entity(
            actor.world,
            [ScriptedControllerComponent(script_name=spec.script_name, loop=spec.script_loop)],
        )
        actor.assign_controller(character_id, controller.id)
    else:  # suspended / claimable
        controller = spawn_entity(actor.world)
        actor.suspend(character_id, controller.id, reason="unclaimed")


__all__ = ["InstantiatedWorld", "instantiate", "validate_proposal"]
