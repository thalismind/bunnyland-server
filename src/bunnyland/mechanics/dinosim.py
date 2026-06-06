"""Dino-sim lifecycle, cloning, eggs, and kaiju incident hooks.

This first slice keeps the package focused on three primary loops:
fossil/species identification and cloning, egg handling/reptile procreation, and kaiju
storyteller support. It intentionally does not add park guests or attraction management.
"""

from __future__ import annotations

from dataclasses import replace

from pydantic.dataclasses import dataclass
from relics import Component, Entity, EntityId, World

from ..core.commands import SubmittedCommand
from ..core.components import (
    CharacterComponent,
    IdentityComponent,
    PortableComponent,
    RoomComponent,
)
from ..core.ecs import container_of, parse_entity_id, reachable_ids, replace_component, spawn_entity
from ..core.edges import ContainmentMode, Contains
from ..core.events import DomainEvent, EventVisibility
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected
from .lifesim import AgeComponent, LifeStageComponent

DEFAULT_INCUBATION_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class DinosimPolicyComponent(Component):
    kaiju_storyteller_incidents: bool = True


@dataclass(frozen=True)
class DinosaurComponent(Component):
    species_name: str


@dataclass(frozen=True)
class SpeciesComponent(Component):
    common_name: str
    scientific_name: str = ""
    diet: str = "omnivore"
    size_class: str = "medium"


@dataclass(frozen=True)
class FossilFragmentComponent(Component):
    sample_quality: float = 1.0
    cleaned: bool = False


@dataclass(frozen=True)
class SpeciesIdentificationComponent(Component):
    species_name: str
    confidence: float = 1.0
    identified_at_epoch: int = 0


@dataclass(frozen=True)
class AncientSampleComponent(Component):
    species_name: str
    viability: float = 1.0
    source_fossil_id: str = ""


@dataclass(frozen=True)
class CloneCandidateComponent(Component):
    species_name: str
    source_sample_id: str
    viability: float = 1.0
    prepared_at_epoch: int = 0


@dataclass(frozen=True)
class EggComponent(Component):
    species_name: str
    laid_at_epoch: int
    fertilized: bool = False
    parent_ids: tuple[str, ...] = ()
    source: str = "natural"


@dataclass(frozen=True)
class FertilityComponent(Component):
    fertile: bool = True


@dataclass(frozen=True)
class ReptileProcreationComponent(Component):
    egg_species_name: str = ""


@dataclass(frozen=True)
class IncubationComponent(Component):
    started_at_epoch: int
    required_seconds: int = DEFAULT_INCUBATION_SECONDS
    progress_seconds: int = 0
    last_updated_epoch: int = 0
    ready: bool = False


@dataclass(frozen=True)
class HatchlingComponent(Component):
    hatched_at_epoch: int
    egg_id: str


@dataclass(frozen=True)
class KaijuComponent(Component):
    threat_level: int = 10
    target_room_id: str | None = None


@dataclass(frozen=True)
class SettlementDamageComponent(Component):
    severity: int = 1
    repaired: bool = False


class FossilIdentifiedEvent(DomainEvent):
    fossil_id: str
    species_name: str
    confidence: float


class AncientSampleExtractedEvent(DomainEvent):
    fossil_id: str
    sample_id: str
    species_name: str


class ClonePreparedEvent(DomainEvent):
    sample_id: str
    egg_id: str
    species_name: str


class EggLaidEvent(DomainEvent):
    parent_id: str
    egg_id: str
    species_name: str


class EggFertilizedEvent(DomainEvent):
    egg_id: str
    parent_id: str
    species_name: str


class EggIncubatedEvent(DomainEvent):
    egg_id: str
    ready_at_epoch: int


class EggHatchedEvent(DomainEvent):
    egg_id: str
    hatchling_id: str
    species_name: str


def _room_id(world: World, character_id: EntityId) -> str | None:
    raw = container_of(world.get_entity(character_id))
    return str(raw) if raw is not None else None


def _entity_room_id(entity: Entity) -> str | None:
    raw = container_of(entity)
    return str(raw) if raw is not None else None


def _reachable_entity(ctx: HandlerContext, character_id: EntityId, target_id: EntityId):
    character = ctx.entity(character_id)
    if target_id not in reachable_ids(ctx.world, character):
        return None
    return ctx.entity(target_id)


def _remove_from_container(world: World, entity_id: EntityId) -> None:
    entity = world.get_entity(entity_id)
    parent_id = container_of(entity)
    if parent_id is not None:
        world.get_entity(parent_id).remove_relationship(Contains, entity_id)


def _hatch_room_id(world: World, actor: Entity, egg: Entity) -> EntityId | None:
    egg_container_id = container_of(egg)
    if egg_container_id is not None and world.has_entity(egg_container_id):
        egg_container = world.get_entity(egg_container_id)
        if egg_container.has_component(RoomComponent):
            return egg_container_id
    return container_of(actor)


def _species_name(entity: Entity) -> str:
    if entity.has_component(SpeciesComponent):
        return entity.get_component(SpeciesComponent).common_name
    if entity.has_component(DinosaurComponent):
        return entity.get_component(DinosaurComponent).species_name
    if entity.has_component(CharacterComponent):
        return entity.get_component(CharacterComponent).species
    if entity.has_component(IdentityComponent):
        return entity.get_component(IdentityComponent).name
    return "unknown reptile"


def _spawn_egg(
    world: World,
    species_name: str,
    epoch: int,
    *,
    fertilized: bool = False,
    parent_ids: tuple[str, ...] = (),
    source: str = "natural",
) -> Entity:
    return spawn_entity(
        world,
        [
            IdentityComponent(name=f"{species_name} egg", kind="egg", tags=("dinosim",)),
            EggComponent(
                species_name=species_name,
                laid_at_epoch=epoch,
                fertilized=fertilized,
                parent_ids=parent_ids,
                source=source,
            ),
            PortableComponent(can_pick_up=True),
        ],
    )


def ensure_dinosim_policy(actor) -> DinosimPolicyComponent:
    for entity in actor.world.query().with_all([DinosimPolicyComponent]).execute_entities():
        return entity.get_component(DinosimPolicyComponent)
    entity = spawn_entity(actor.world, [DinosimPolicyComponent()])
    return entity.get_component(DinosimPolicyComponent)


class IncubationConsequence:
    """Advance fertilized eggs until they are ready to hatch."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        for egg in world.query().with_all([EggComponent, IncubationComponent]).execute_entities():
            egg_component = egg.get_component(EggComponent)
            incubation = egg.get_component(IncubationComponent)
            if incubation.ready or not egg_component.fertilized:
                continue
            elapsed = max(0, epoch - incubation.last_updated_epoch)
            progress = min(
                incubation.required_seconds,
                incubation.progress_seconds + elapsed,
            )
            replace_component(
                egg,
                replace(
                    incubation,
                    progress_seconds=progress,
                    last_updated_epoch=epoch,
                    ready=progress >= incubation.required_seconds,
                ),
            )
        return []


class IdentifyFossilHandler:
    command_type = "identify-fossil"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        fossil_id = parse_entity_id(command.payload.get("fossil_id"))
        species_name = str(command.payload.get("species_name", "")).strip()
        if character_id is None or fossil_id is None or not species_name:
            return rejected("invalid character, fossil, or species name")
        if not ctx.world.has_entity(fossil_id):
            return rejected("fossil does not exist")
        fossil = _reachable_entity(ctx, character_id, fossil_id)
        if fossil is None:
            return rejected("fossil is not reachable")
        if not fossil.has_component(FossilFragmentComponent):
            return rejected("target is not a fossil")

        fossil_component = fossil.get_component(FossilFragmentComponent)
        replace_component(fossil, replace(fossil_component, cleaned=True))
        identification = SpeciesIdentificationComponent(
            species_name=species_name,
            confidence=max(0.0, min(1.0, fossil_component.sample_quality)),
            identified_at_epoch=ctx.epoch,
        )
        replace_component(fossil, identification)
        return ok(
            FossilIdentifiedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(fossil_id),),
                    fossil_id=str(fossil_id),
                    species_name=species_name,
                    confidence=identification.confidence,
                )
            )
        )


class ExtractAncientSampleHandler:
    command_type = "extract-ancient-sample"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        fossil_id = parse_entity_id(command.payload.get("fossil_id"))
        if character_id is None or fossil_id is None:
            return rejected("invalid character or fossil id")
        if not ctx.world.has_entity(fossil_id):
            return rejected("fossil does not exist")
        character = ctx.entity(character_id)
        fossil = _reachable_entity(ctx, character_id, fossil_id)
        if fossil is None:
            return rejected("fossil is not reachable")
        if not fossil.has_component(FossilFragmentComponent):
            return rejected("target is not a fossil")
        if not fossil.has_component(SpeciesIdentificationComponent):
            return rejected("fossil has not been identified")

        identification = fossil.get_component(SpeciesIdentificationComponent)
        sample = spawn_entity(
            ctx.world,
            [
                IdentityComponent(
                    name=f"{identification.species_name} ancient sample",
                    kind="sample",
                    tags=("dinosim",),
                ),
                AncientSampleComponent(
                    species_name=identification.species_name,
                    viability=identification.confidence,
                    source_fossil_id=str(fossil_id),
                ),
                PortableComponent(can_pick_up=True),
            ],
        )
        character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), sample.id)
        return ok(
            AncientSampleExtractedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(fossil_id), str(sample.id)),
                    fossil_id=str(fossil_id),
                    sample_id=str(sample.id),
                    species_name=identification.species_name,
                )
            )
        )


class PrepareCloneHandler:
    command_type = "prepare-clone"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        sample_id = parse_entity_id(command.payload.get("sample_id"))
        if character_id is None or sample_id is None:
            return rejected("invalid character or sample id")
        if not ctx.world.has_entity(sample_id):
            return rejected("sample does not exist")
        character = ctx.entity(character_id)
        sample_entity = _reachable_entity(ctx, character_id, sample_id)
        if sample_entity is None:
            return rejected("sample is not reachable")
        if not sample_entity.has_component(AncientSampleComponent):
            return rejected("target is not an ancient sample")

        sample = sample_entity.get_component(AncientSampleComponent)
        egg = _spawn_egg(
            ctx.world,
            sample.species_name,
            ctx.epoch,
            fertilized=True,
            parent_ids=(sample.source_fossil_id,),
            source="clone",
        )
        egg.add_component(
            CloneCandidateComponent(
                species_name=sample.species_name,
                source_sample_id=str(sample_id),
                viability=sample.viability,
                prepared_at_epoch=ctx.epoch,
            )
        )
        character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), egg.id)
        _remove_from_container(ctx.world, sample_id)
        return ok(
            ClonePreparedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(sample_id), str(egg.id)),
                    sample_id=str(sample_id),
                    egg_id=str(egg.id),
                    species_name=sample.species_name,
                )
            )
        )


class LayEggHandler:
    command_type = "lay-egg"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        parent_id = parse_entity_id(command.payload.get("parent_id"))
        if character_id is None or parent_id is None:
            return rejected("invalid character or parent id")
        if not ctx.world.has_entity(parent_id):
            return rejected("parent does not exist")
        parent = _reachable_entity(ctx, character_id, parent_id)
        if parent is None:
            return rejected("parent is not reachable")
        if parent.has_component(FertilityComponent) and not parent.get_component(
            FertilityComponent
        ).fertile:
            return rejected("parent is not fertile")
        if not (
            parent.has_component(ReptileProcreationComponent)
            or parent.has_component(DinosaurComponent)
            or parent.has_component(SpeciesComponent)
        ):
            return rejected("parent cannot lay reptile eggs")

        if parent.has_component(ReptileProcreationComponent):
            procreation = parent.get_component(ReptileProcreationComponent)
            species_name = procreation.egg_species_name or _species_name(parent)
        else:
            species_name = _species_name(parent)
        egg = _spawn_egg(ctx.world, species_name, ctx.epoch, parent_ids=(str(parent_id),))
        room_id = container_of(parent) or container_of(ctx.entity(character_id))
        if room_id is not None and ctx.world.has_entity(room_id):
            ctx.entity(room_id).add_relationship(
                Contains(mode=ContainmentMode.ROOM_CONTENT), egg.id
            )
        return ok(
            EggLaidEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(room_id) if room_id is not None else None,
                    target_ids=(str(parent_id), str(egg.id)),
                    parent_id=str(parent_id),
                    egg_id=str(egg.id),
                    species_name=species_name,
                )
            )
        )


class FertilizeEggHandler:
    command_type = "fertilize-egg"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        egg_id = parse_entity_id(command.payload.get("egg_id"))
        parent_id = parse_entity_id(command.payload.get("parent_id"))
        if character_id is None or egg_id is None or parent_id is None:
            return rejected("invalid character, egg, or parent id")
        if not ctx.world.has_entity(egg_id) or not ctx.world.has_entity(parent_id):
            return rejected("egg or parent does not exist")
        egg_entity = _reachable_entity(ctx, character_id, egg_id)
        parent = _reachable_entity(ctx, character_id, parent_id)
        if egg_entity is None or parent is None:
            return rejected("egg or parent is not reachable")
        if not egg_entity.has_component(EggComponent):
            return rejected("target is not an egg")
        egg = egg_entity.get_component(EggComponent)
        if egg.fertilized:
            return rejected("egg is already fertilized")
        if parent.has_component(FertilityComponent) and not parent.get_component(
            FertilityComponent
        ).fertile:
            return rejected("parent is not fertile")

        parent_ids = tuple(dict.fromkeys((*egg.parent_ids, str(parent_id))))
        replace_component(egg_entity, replace(egg, fertilized=True, parent_ids=parent_ids))
        return ok(
            EggFertilizedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(egg_id), str(parent_id)),
                    egg_id=str(egg_id),
                    parent_id=str(parent_id),
                    species_name=egg.species_name,
                )
            )
        )


class IncubateEggHandler:
    command_type = "incubate-egg"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        egg_id = parse_entity_id(command.payload.get("egg_id"))
        if character_id is None or egg_id is None:
            return rejected("invalid character or egg id")
        if not ctx.world.has_entity(egg_id):
            return rejected("egg does not exist")
        egg_entity = _reachable_entity(ctx, character_id, egg_id)
        if egg_entity is None:
            return rejected("egg is not reachable")
        if not egg_entity.has_component(EggComponent):
            return rejected("target is not an egg")
        egg = egg_entity.get_component(EggComponent)
        if not egg.fertilized:
            return rejected("egg is not fertilized")

        required_seconds = int(
            command.payload.get("duration_seconds", DEFAULT_INCUBATION_SECONDS)
            or DEFAULT_INCUBATION_SECONDS
        )
        required_seconds = max(60, required_seconds)
        replace_component(
            egg_entity,
            IncubationComponent(
                started_at_epoch=ctx.epoch,
                required_seconds=required_seconds,
                last_updated_epoch=ctx.epoch,
            ),
        )
        return ok(
            EggIncubatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(egg_id),),
                    egg_id=str(egg_id),
                    ready_at_epoch=ctx.epoch + required_seconds,
                )
            )
        )


class HatchEggHandler:
    command_type = "hatch-egg"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        egg_id = parse_entity_id(command.payload.get("egg_id"))
        if character_id is None or egg_id is None:
            return rejected("invalid character or egg id")
        if not ctx.world.has_entity(egg_id):
            return rejected("egg does not exist")
        actor = ctx.entity(character_id)
        egg_entity = _reachable_entity(ctx, character_id, egg_id)
        if egg_entity is None:
            return rejected("egg is not reachable")
        if not egg_entity.has_component(EggComponent):
            return rejected("target is not an egg")
        if not egg_entity.has_component(IncubationComponent):
            return rejected("egg is not incubating")
        egg = egg_entity.get_component(EggComponent)
        incubation = egg_entity.get_component(IncubationComponent)
        if not incubation.ready:
            return rejected("egg is not ready to hatch")

        hatchling = spawn_entity(
            ctx.world,
            [
                IdentityComponent(name=f"{egg.species_name} hatchling", kind="character"),
                CharacterComponent(species=egg.species_name, public=True),
                DinosaurComponent(species_name=egg.species_name),
                HatchlingComponent(hatched_at_epoch=ctx.epoch, egg_id=str(egg_id)),
                AgeComponent(born_at_epoch=ctx.epoch),
                LifeStageComponent(stage="child"),
            ],
        )
        room_id = _hatch_room_id(ctx.world, actor, egg_entity)
        _remove_from_container(ctx.world, egg_id)
        egg_entity.remove_component(EggComponent)
        egg_entity.remove_component(IncubationComponent)
        if egg_entity.has_component(CloneCandidateComponent):
            egg_entity.remove_component(CloneCandidateComponent)
        if room_id is not None and ctx.world.has_entity(room_id):
            ctx.entity(room_id).add_relationship(
                Contains(mode=ContainmentMode.ROOM_CONTENT), hatchling.id
            )
        return ok(
            EggHatchedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(room_id) if room_id is not None else None,
                    target_ids=(str(egg_id), str(hatchling.id)),
                    egg_id=str(egg_id),
                    hatchling_id=str(hatchling.id),
                    species_name=egg.species_name,
                )
            )
        )


def dinosim_fragments(world: World, character: Entity) -> list[str]:
    lines: list[str] = []
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        name = (
            entity.get_component(IdentityComponent).name
            if entity.has_component(IdentityComponent)
            else str(entity.id)
        )
        if entity.has_component(FossilFragmentComponent):
            if entity.has_component(SpeciesIdentificationComponent):
                identification = entity.get_component(SpeciesIdentificationComponent)
                lines.append(f"Nearby fossil: {name} ({identification.species_name}).")
            else:
                lines.append(f"Nearby unidentified fossil: {name}.")
        if entity.has_component(AncientSampleComponent):
            sample = entity.get_component(AncientSampleComponent)
            lines.append(f"Nearby ancient sample: {name} ({sample.species_name}).")
        if entity.has_component(EggComponent):
            egg = entity.get_component(EggComponent)
            state = "fertilized" if egg.fertilized else "unfertilized"
            if entity.has_component(IncubationComponent):
                incubation = entity.get_component(IncubationComponent)
                state = "ready to hatch" if incubation.ready else "incubating"
            lines.append(f"Nearby egg: {name} ({egg.species_name}, {state}).")
    return sorted(lines)


def install_dinosim(actor) -> None:
    ensure_dinosim_policy(actor)
    actor.register_consequence(IncubationConsequence())


__all__ = [
    "AncientSampleComponent",
    "AncientSampleExtractedEvent",
    "CloneCandidateComponent",
    "ClonePreparedEvent",
    "DinosaurComponent",
    "DinosimPolicyComponent",
    "EggComponent",
    "EggFertilizedEvent",
    "EggHatchedEvent",
    "EggIncubatedEvent",
    "EggLaidEvent",
    "ExtractAncientSampleHandler",
    "FertilityComponent",
    "FertilizeEggHandler",
    "FossilFragmentComponent",
    "FossilIdentifiedEvent",
    "HatchEggHandler",
    "HatchlingComponent",
    "IdentifyFossilHandler",
    "IncubateEggHandler",
    "IncubationComponent",
    "IncubationConsequence",
    "KaijuComponent",
    "LayEggHandler",
    "PrepareCloneHandler",
    "ReptileProcreationComponent",
    "SettlementDamageComponent",
    "SpeciesComponent",
    "SpeciesIdentificationComponent",
    "dinosim_fragments",
    "ensure_dinosim_policy",
    "install_dinosim",
]
