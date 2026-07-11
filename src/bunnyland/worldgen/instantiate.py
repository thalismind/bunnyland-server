"""Validate a world proposal and instantiate it into the Relics world (spec 22.2).

This is the boundary the LLM never crosses: it proposes; the engine validates schema and
references, then creates entities, components, edges, and controllers. Emits
``WorldGeneratedEvent`` when done.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from relics import EntityId

from bunnyland.foundation.consumables.components import (
    ConsumableComponent,
    DrinkableComponent,
    FoodComponent,
)
from bunnyland.foundation.meters.mechanics import Meter
from bunnyland.foundation.needs.mechanics import HungerComponent, ThirstComponent
from bunnyland.foundation.persona.mechanics import GoalComponent, TraitSetComponent

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
    GenerationChild,
    GenerationError,
    GenerationPipeline,
    GenerationPlan,
    GenerationRequest,
    GenerationTarget,
)
from ..llm_agents.behavior_tree import behavior_tree_names
from ..llm_agents.scripts import script_names
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


@dataclass(frozen=True)
class _CompiledChild:
    child: GenerationChild
    components: tuple
    generation: GenerationIntentComponent
    plan: GenerationPlan
    children: tuple[_CompiledChild, ...]


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
    *,
    context: dict | None = None,
) -> tuple[list, GenerationIntentComponent, GenerationPlan]:
    request = GenerationRequest(
        entity_kind=generation.entity_kind,
        description=generation.description,
        capabilities=(*generation.wants, *generation.needs),
        tags=generation.tags,
        source_seed=generation.source_seed,
        source_key=generation.source_key,
        context={
            **(context or {}),
            "base_components": tuple(components),
            "world_epoch": actor.epoch,
        },
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


def _child_base_components(child: GenerationChild) -> list:
    """Build plugin-neutral identity/state for a declarative child request."""

    request = child.request
    name = request.description.strip() or request.source_key or request.entity_kind
    context = request.context
    declared = list(child.components)
    declared_types = {type(component) for component in declared}
    if request.entity_kind == "room":
        generated = [
            RoomComponent(
                title=name,
                biome=str(context.get("biome", "")),
                indoor=bool(context.get("indoor", False)),
            )
        ]
    elif request.entity_kind == "character":
        generated = [
            IdentityComponent(name=name, kind="character"),
            CharacterComponent(),
            ActionPointsComponent(current=0, maximum=3),
            FocusPointsComponent(current=0, maximum=2),
        ]
    else:
        generated = [IdentityComponent(name=name, kind=request.entity_kind or "object")]
        if bool(context.get("portable", False)):
            generated.append(PortableComponent(can_pick_up=True))
    return [
        *declared,
        *(component for component in generated if type(component) not in declared_types),
    ]


async def _compile_children(
    actor: WorldActor,
    plan: GenerationPlan,
    *,
    seen: frozenset[str] = frozenset(),
) -> tuple[_CompiledChild, ...]:
    if plan.request.request_id in seen:
        raise GenerationError(f"recursive generation child request {plan.request.request_id!r}")
    branch = seen | {plan.request.request_id}
    compiled = []
    for child in plan.children:
        base_components = _child_base_components(child)
        request = replace(
            child.request,
            context={**child.request.context, "base_components": tuple(base_components)},
        )
        child_plan = await GenerationPipeline(actor.plugins).compile(
            request,
            base_components=tuple(base_components),
        )
        generation = GenerationIntentComponent(
            description=child_plan.request.description,
            tags=child_plan.request.tags,
            wants=child_plan.request.capabilities,
            source_seed=child_plan.request.source_seed,
            source_key=child_plan.request.source_key,
            entity_kind=child_plan.request.entity_kind,
            unmet_capabilities=child_plan.unmet_capabilities,
        )
        _validate_plan_edges(actor, child_plan)
        compiled.append(
            _CompiledChild(
                child=replace(child, request=child_plan.request),
                components=(*child_plan.components, generation),
                generation=generation,
                plan=child_plan,
                children=await _compile_children(actor, child_plan, seen=branch),
            )
        )
    return tuple(compiled)


def _validate_plan_edges(
    actor: WorldActor,
    plan: GenerationPlan,
    known_targets: frozenset[str] = frozenset(),
) -> None:
    for edge_delta in plan.edges:
        target_id = edge_delta.target_id
        if isinstance(target_id, GenerationTarget):
            if target_id.source_key not in known_targets:
                raise GenerationError(
                    f"generation edge references unknown source key {target_id.source_key!r}"
                )
            continue
        if isinstance(target_id, str):
            target_id = parse_entity_id(target_id)
        if target_id is None or not actor.world.has_entity(target_id):
            raise GenerationError(
                f"generation edge references missing entity {edge_delta.target_id!r}"
            )


def _apply_plan_edges(
    actor: WorldActor,
    entity,
    plan: GenerationPlan,
    generated_ids: dict[str, EntityId] | None = None,
) -> None:
    for edge_delta in plan.edges:
        target_id = edge_delta.target_id
        if isinstance(target_id, GenerationTarget):
            target_id = (generated_ids or {})[target_id.source_key]
        if isinstance(target_id, str):
            target_id = parse_entity_id(target_id)
        entity.add_relationship(edge_delta.edge, target_id)


async def _instantiate_children(
    actor: WorldActor,
    parent,
    children: tuple[_CompiledChild, ...],
    *,
    room_id: EntityId | None,
    spawned_singletons: dict[str, EntityId],
) -> None:
    """Instantiate one precompiled child tree, then publish fully finalized events."""

    for compiled in children:
        singleton_key = compiled.child.singleton_key
        if singleton_key is not None and singleton_key in spawned_singletons:
            entity_id = spawned_singletons[singleton_key]
            parent.add_relationship(compiled.child.parent_edge, entity_id)
            for parent_edge in compiled.child.additional_parent_edges:
                parent.add_relationship(parent_edge, entity_id)
            continue
        request = compiled.plan.request
        entity = spawn_entity(actor.world, compiled.components)
        if singleton_key is not None:
            spawned_singletons[singleton_key] = entity.id
        parent.add_relationship(compiled.child.parent_edge, entity.id)
        for parent_edge in compiled.child.additional_parent_edges:
            parent.add_relationship(parent_edge, entity.id)
        _apply_plan_edges(actor, entity, compiled.plan)
        child_room_id = entity.id if request.entity_kind == "room" else room_id
        if request.entity_kind == "character":
            controller = spawn_entity(actor.world)
            actor.suspend(entity.id, controller.id, reason="generated")

        if request.entity_kind == "room":
            event: GeneratedEntityEvent = RoomGeneratedEvent(
                **actor._event_base(
                    seed=request.source_seed,
                    entity_id=str(entity.id),
                    entity_key=request.source_key,
                    entity_kind="room",
                    room_id=str(entity.id),
                    room_key=request.source_key,
                    generation=compiled.generation,
                    biome=str(request.context.get("biome", "")),
                    indoor=bool(request.context.get("indoor", False)),
                )
            )
        elif request.entity_kind == "character":
            event = CharacterGeneratedEvent(
                **actor._event_base(
                    seed=request.source_seed,
                    entity_id=str(entity.id),
                    entity_key=request.source_key,
                    entity_kind="character",
                    character_key=request.source_key,
                    room_id=str(child_room_id or ""),
                    generation=compiled.generation,
                    species=str(request.context.get("species", "")),
                )
            )
        else:
            event = ObjectGeneratedEvent(
                **actor._event_base(
                    seed=request.source_seed,
                    entity_id=str(entity.id),
                    entity_key=request.source_key,
                    entity_kind=request.entity_kind,
                    object_key=request.source_key,
                    room_id=str(child_room_id or ""),
                    container_id=str(parent.id),
                    containment_mode=getattr(
                        compiled.child.parent_edge, "mode", ContainmentMode.ROOM_CONTENT
                    ).value,
                    generation=compiled.generation,
                )
            )
        await _instantiate_children(
            actor,
            entity,
            compiled.children,
            room_id=child_room_id,
            spawned_singletons=spawned_singletons,
        )
        await actor.bus.publish(event)


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
    child_plans: dict[str, tuple[_CompiledChild, ...]] = {}
    spawned_child_singletons: dict[str, EntityId] = {}

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
            actor,
            generation,
            _object_components(obj),
            context={
                "room_key": obj.room_key,
                "room_objects": tuple(
                    (candidate.key, candidate.kind)
                    for candidate in proposal.objects
                    if candidate.room_key == obj.room_key and candidate.key != obj.key
                ),
            },
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
            actor,
            generation,
            _character_components(character),
            context={"room_key": character.room_key, "species": character.species},
        )
    known_targets = frozenset((*room_plans.keys(), *object_plans.keys(), *character_plans.keys()))
    for _components, _generation, plan in (
        *room_plans.values(),
        *object_plans.values(),
        *character_plans.values(),
    ):
        _validate_plan_edges(actor, plan, known_targets)
        child_plans[plan.request.request_id] = await _compile_children(actor, plan)

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
            await _instantiate_children(
                actor,
                entity,
                child_plans[plan.request.request_id],
                room_id=entity.id,
                spawned_singletons=spawned_child_singletons,
            )
            await actor.bus.publish(event)

        for exit_ in proposal.exits:
            world.get_entity(result.rooms[exit_.from_key]).add_relationship(
                ExitTo(direction=exit_.direction, locked=exit_.locked),
                result.rooms[exit_.to_key],
            )

        for obj in proposal.objects:
            components, _generation, _plan = object_plans[obj.key]
            entity = spawn_entity(world, components)
            world.get_entity(result.rooms[obj.room_key]).add_relationship(
                Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
            )
            result.objects[obj.key] = entity.id

        generated_ids = {
            **result.rooms,
            **result.objects,
            **result.characters,
        }
        for obj in proposal.objects:
            _components, generation, plan = object_plans[obj.key]
            entity = world.get_entity(result.objects[obj.key])
            _apply_plan_edges(actor, entity, plan, generated_ids)
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
            await _instantiate_children(
                actor,
                entity,
                child_plans[plan.request.request_id],
                room_id=result.rooms[obj.room_key],
                spawned_singletons=spawned_child_singletons,
            )
            await actor.bus.publish(event)

        for character in proposal.characters:
            components, generation, plan = character_plans[character.key]
            entity = spawn_entity(world, components)
            _apply_plan_edges(actor, entity, plan, generated_ids)
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
            await _instantiate_children(
                actor,
                entity,
                child_plans[plan.request.request_id],
                room_id=result.rooms[character.room_key],
                spawned_singletons=spawned_child_singletons,
            )
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
