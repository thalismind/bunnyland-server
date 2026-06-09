"""Dino-sim lifecycle, cloning, eggs, and kaiju incident hooks.

This first slice keeps the package focused on three primary loops:
fossil/species identification and cloning, egg handling/reptile procreation, and kaiju
storyteller support. It intentionally does not add park guests or attraction management.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

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
from ..core.edges import ContainmentMode, Contains, ExitTo
from ..core.events import DomainEvent, EventVisibility
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected
from .lifesim import AgeComponent, LifeStageComponent

DEFAULT_INCUBATION_SECONDS = 24 * 60 * 60


def _event_base(epoch: int, **kwargs) -> dict:
    base = {
        "event_id": uuid4().hex,
        "world_epoch": epoch,
        "created_at": datetime.now(UTC),
    }
    base.update(kwargs)
    return base


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
class TrackComponent(Component):
    room_id: str
    freshness: float = 1.0
    last_tracked_epoch: int = 0


@dataclass(frozen=True)
class ScentComponent(Component):
    species_name: str = ""
    strength: float = 1.0


@dataclass(frozen=True)
class BaitComponent(Component):
    target_species: str = ""
    potency: float = 1.0
    set_by_id: str = ""
    set_at_epoch: int = 0


@dataclass(frozen=True)
class TranquilizerComponent(Component):
    potency: float = 1.0
    uses: int = 1
    sedated_until_epoch: int = 0


@dataclass(frozen=True)
class TamingComponent(Component):
    progress: float = 0.0
    required: float = 3.0
    tamer_id: str = ""
    tamed: bool = False


@dataclass(frozen=True)
class TrustComponent(Component):
    amount: float = 0.0


@dataclass(frozen=True)
class FearComponent(Component):
    amount: float = 0.0


@dataclass(frozen=True)
class TrainingComponent(Component):
    learned_commands: tuple[str, ...] = ()
    progress: dict[str, float] | None = None
    required: float = 2.0


@dataclass(frozen=True)
class CommandComponent(Component):
    command_name: str
    commanded_by_id: str
    target_id: str = ""
    issued_at_epoch: int = 0


@dataclass(frozen=True)
class MountComponent(Component):
    rider_id: str = ""
    mounted: bool = False


@dataclass(frozen=True)
class CompanionComponent(Component):
    owner_id: str
    role: str = "companion"


@dataclass(frozen=True)
class GuardBehaviorComponent(Component):
    location_id: str = ""
    active: bool = True


@dataclass(frozen=True)
class HuntBehaviorComponent(Component):
    target_species: str = ""
    active: bool = True


@dataclass(frozen=True)
class RecallComponent(Component):
    home_room_id: str = ""
    last_recalled_epoch: int = 0


@dataclass(frozen=True)
class EnclosureComponent(Component):
    name: str = "enclosure"
    capacity: int = 4
    built_by_id: str = ""
    built_at_epoch: int = 0


@dataclass(frozen=True)
class FenceComponent(Component):
    integrity: float = 10.0
    maximum: float = 10.0


@dataclass(frozen=True)
class GateComponent(Component):
    open: bool = False
    locked: bool = False


@dataclass(frozen=True)
class ReinforcementComponent(Component):
    amount: float = 0.0


@dataclass(frozen=True)
class FeedingPenComponent(Component):
    feed: float = 0.0


@dataclass(frozen=True)
class QuarantinePenComponent(Component):
    active: bool = True


@dataclass(frozen=True)
class EscapeRiskComponent(Component):
    risk: float = 0.0
    threshold: float = 1.0
    last_updated_epoch: int = 0


@dataclass(frozen=True)
class BreachComponent(Component):
    severity: float = 1.0


@dataclass(frozen=True)
class StampedeComponent(Component):
    active: bool = True
    started_at_epoch: int = 0


@dataclass(frozen=True)
class ContainmentProtocolComponent(Component):
    active: bool = False
    triggered_at_epoch: int = 0


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


class CreatureTrackedEvent(DomainEvent):
    creature_id: str
    tracked_room_id: str
    species_name: str


class BaitSetEvent(DomainEvent):
    bait_id: str
    target_species: str
    potency: float


class CreatureTranquilizedEvent(DomainEvent):
    creature_id: str
    tranquilizer_id: str
    sedated_until_epoch: int


class TamingProgressedEvent(DomainEvent):
    creature_id: str
    progress: float
    required: float
    trust: float
    fear: float


class CreatureTamedEvent(DomainEvent):
    creature_id: str
    owner_id: str
    role: str


class CommandTrainedEvent(DomainEvent):
    creature_id: str
    command_name: str


class CreatureMountedEvent(DomainEvent):
    creature_id: str
    rider_id: str


class CompanionCommandedEvent(DomainEvent):
    creature_id: str
    command_name: str
    target_id: str = ""


class CreatureRecalledEvent(DomainEvent):
    creature_id: str
    recalled_room_id: str


class EnclosureBuiltEvent(DomainEvent):
    enclosure_id: str
    name: str


class FenceRepairedEvent(DomainEvent):
    enclosure_id: str
    integrity: float


class GateReinforcedEvent(DomainEvent):
    enclosure_id: str
    reinforcement: float


class PenLockedEvent(DomainEvent):
    enclosure_id: str


class PenOpenedEvent(DomainEvent):
    enclosure_id: str


class ContainmentTriggeredEvent(DomainEvent):
    enclosure_id: str


class CreatureEscapedEvent(DomainEvent):
    creature_id: str
    from_room_id: str
    to_room_id: str


class CreatureRecapturedEvent(DomainEvent):
    creature_id: str
    enclosure_id: str


class StampedeStartedEvent(DomainEvent):
    enclosure_id: str
    creature_ids: tuple[str, ...] = ()


class RoomEvacuatedEvent(DomainEvent):
    room_id_evacuated: str
    destination_id: str
    character_ids: tuple[str, ...] = ()


class HiddenFromCreatureEvent(DomainEvent):
    creature_id: str
    character_id: str


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


def _entity_name(entity: Entity) -> str:
    if entity.has_component(IdentityComponent):
        return entity.get_component(IdentityComponent).name
    return str(entity.id)


def _is_creature(entity: Entity) -> bool:
    return (
        entity.has_component(DinosaurComponent)
        or entity.has_component(SpeciesComponent)
        or entity.has_component(ReptileProcreationComponent)
        or entity.has_component(KaijuComponent)
    )


def _reachable_creature(
    ctx: HandlerContext, character_id: EntityId, requested_id: object
) -> tuple[Entity | None, str | None]:
    creature_id = parse_entity_id(requested_id)
    if creature_id is None:
        return None, "invalid creature id"
    if not ctx.world.has_entity(creature_id):
        return None, "creature does not exist"
    creature = _reachable_entity(ctx, character_id, creature_id)
    if creature is None:
        return None, "creature is not reachable"
    if not _is_creature(creature):
        return None, "target is not a creature"
    return creature, None


def _reachable_item(
    ctx: HandlerContext, character_id: EntityId, requested_id: object
) -> tuple[Entity | None, str | None]:
    item_id = parse_entity_id(requested_id)
    if item_id is None:
        return None, "invalid item id"
    if not ctx.world.has_entity(item_id):
        return None, "item does not exist"
    item = _reachable_entity(ctx, character_id, item_id)
    if item is None:
        return None, "item is not reachable"
    return item, None


def _companion_for_actor(creature: Entity, character_id: EntityId) -> CompanionComponent | None:
    if not creature.has_component(CompanionComponent):
        return None
    companion = creature.get_component(CompanionComponent)
    if companion.owner_id != str(character_id):
        return None
    return companion


def _matching_bait_bonus(world: World, creature: Entity, character: Entity) -> float:
    species = _species_name(creature)
    bonus = 0.0
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        if not entity.has_component(BaitComponent):
            continue
        bait = entity.get_component(BaitComponent)
        if not bait.target_species or bait.target_species == species:
            bonus = max(bonus, max(0.0, bait.potency))
    return bonus


def _sedation_bonus(creature: Entity, epoch: int) -> float:
    if not creature.has_component(TranquilizerComponent):
        return 0.0
    tranquilizer = creature.get_component(TranquilizerComponent)
    if tranquilizer.sedated_until_epoch < epoch:
        return 0.0
    return max(0.0, tranquilizer.potency)


def _move_to_room(world: World, entity: Entity, room_id: EntityId) -> None:
    parent_id = container_of(entity)
    if parent_id is not None and world.has_entity(parent_id):
        world.get_entity(parent_id).remove_relationship(Contains, entity.id)
    world.get_entity(room_id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )


def _current_or_requested_room(
    ctx: HandlerContext, character_id: EntityId, requested_id: object
) -> tuple[Entity | None, str | None]:
    room_id = parse_entity_id(requested_id) if requested_id is not None else None
    if room_id is None:
        room_id = container_of(ctx.entity(character_id))
    if room_id is None:
        return None, "room is required"
    if not ctx.world.has_entity(room_id):
        return None, "room does not exist"
    room = ctx.entity(room_id)
    if not room.has_component(RoomComponent):
        return None, "target is not a room"
    return room, None


def _enclosure_entity(
    ctx: HandlerContext, character_id: EntityId, requested_id: object
) -> tuple[Entity | None, str | None]:
    enclosure, error = _current_or_requested_room(ctx, character_id, requested_id)
    if enclosure is None:
        return None, error
    if not enclosure.has_component(EnclosureComponent):
        return None, "target is not an enclosure"
    return enclosure, None


def _first_exit_target(room: Entity) -> EntityId | None:
    exits = room.get_relationships(ExitTo)
    if not exits:
        return None
    return exits[0][1]


def _creatures_in_room(world: World, room: Entity) -> list[Entity]:
    creatures: list[Entity] = []
    for _edge, entity_id in room.get_relationships(Contains):
        if not world.has_entity(entity_id):
            continue
        entity = world.get_entity(entity_id)
        if _is_creature(entity):
            creatures.append(entity)
    return creatures


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


class EscapeRiskConsequence:
    """Move creatures out of breached or open enclosures once escape risk crosses threshold."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for room in world.query().with_all([RoomComponent, EnclosureComponent]).execute_entities():
            fence = (
                room.get_component(FenceComponent)
                if room.has_component(FenceComponent)
                else None
            )
            gate = room.get_component(GateComponent) if room.has_component(GateComponent) else None
            breached = room.has_component(BreachComponent)
            unsafe = breached or (fence is not None and fence.integrity <= 0.0)
            unsafe = unsafe or (gate is not None and gate.open and not gate.locked)
            risk = (
                room.get_component(EscapeRiskComponent)
                if room.has_component(EscapeRiskComponent)
                else EscapeRiskComponent(last_updated_epoch=epoch)
            )
            if not unsafe:
                replace_component(room, replace(risk, risk=0.0, last_updated_epoch=epoch))
                continue

            elapsed = max(0, epoch - risk.last_updated_epoch)
            reinforcement = (
                room.get_component(ReinforcementComponent).amount
                if room.has_component(ReinforcementComponent)
                else 0.0
            )
            if risk.risk <= 0.0:
                risk_delta = 1.0
            else:
                risk_delta = elapsed / DEFAULT_INCUBATION_SECONDS
                risk_delta = max(0.1, risk_delta - reinforcement * 0.05)
            updated_risk = replace(
                risk,
                risk=min(risk.threshold, risk.risk + risk_delta),
                last_updated_epoch=epoch,
            )
            replace_component(room, updated_risk)
            if updated_risk.risk < updated_risk.threshold:
                continue

            destination_id = _first_exit_target(room)
            if destination_id is None or not world.has_entity(destination_id):
                continue
            escaped: list[str] = []
            for creature in _creatures_in_room(world, room):
                _move_to_room(world, creature, destination_id)
                escaped.append(str(creature.id))
                events.append(
                    CreatureEscapedEvent(
                        **_event_base(
                            epoch,
                            visibility=EventVisibility.ROOM,
                            room_id=str(room.id),
                            target_ids=(str(creature.id), str(destination_id)),
                            creature_id=str(creature.id),
                            from_room_id=str(room.id),
                            to_room_id=str(destination_id),
                        )
                    )
                )
            if len(escaped) > 1:
                replace_component(room, StampedeComponent(active=True, started_at_epoch=epoch))
                events.append(
                    StampedeStartedEvent(
                        **_event_base(
                            epoch,
                            visibility=EventVisibility.ROOM,
                            room_id=str(room.id),
                            target_ids=tuple(escaped),
                            enclosure_id=str(room.id),
                            creature_ids=tuple(escaped),
                        )
                    )
                )
            replace_component(room, replace(updated_risk, risk=0.0, last_updated_epoch=epoch))
        return events


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


def _progress_taming(
    ctx: HandlerContext,
    character_id: EntityId,
    creature: Entity,
    *,
    base_progress: float,
) -> tuple[TamingComponent, TrustComponent, FearComponent]:
    character = ctx.entity(character_id)
    bait_bonus = _matching_bait_bonus(ctx.world, creature, character)
    sedation_bonus = _sedation_bonus(creature, ctx.epoch)

    taming = (
        creature.get_component(TamingComponent)
        if creature.has_component(TamingComponent)
        else TamingComponent(tamer_id=str(character_id))
    )
    trust = (
        creature.get_component(TrustComponent)
        if creature.has_component(TrustComponent)
        else TrustComponent()
    )
    fear = (
        creature.get_component(FearComponent)
        if creature.has_component(FearComponent)
        else FearComponent(amount=1.0)
    )

    progress_delta = max(0.0, base_progress + bait_bonus + sedation_bonus)
    trust_delta = 1.0 + bait_bonus
    fear_delta = 0.5 + sedation_bonus
    updated_taming = replace(
        taming,
        progress=min(taming.required, taming.progress + progress_delta),
        tamer_id=str(character_id),
    )
    updated_trust = replace(trust, amount=trust.amount + trust_delta)
    updated_fear = replace(fear, amount=max(0.0, fear.amount - fear_delta))
    replace_component(creature, updated_taming)
    replace_component(creature, updated_trust)
    replace_component(creature, updated_fear)
    return updated_taming, updated_trust, updated_fear


class TrackCreatureHandler:
    command_type = "track-creature"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        creature, error = _reachable_creature(
            ctx, character_id, command.payload.get("creature_id")
        )
        if creature is None:
            return rejected(error if error else "creature is required")
        room_id = _entity_room_id(creature) or _room_id(ctx.world, character_id) or ""
        replace_component(
            creature,
            TrackComponent(room_id=room_id, freshness=1.0, last_tracked_epoch=ctx.epoch),
        )
        return ok(
            CreatureTrackedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature.id),),
                    creature_id=str(creature.id),
                    tracked_room_id=room_id,
                    species_name=_species_name(creature),
                )
            )
        )


class SetBaitHandler:
    command_type = "set-bait"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        bait_item, error = _reachable_item(ctx, character_id, command.payload.get("bait_id"))
        if bait_item is None:
            return rejected(error if error else "bait is required")
        target_species = str(command.payload.get("target_species") or "").strip()
        potency = float(command.payload.get("potency") or 1.0)
        bait = BaitComponent(
            target_species=target_species,
            potency=max(0.0, potency),
            set_by_id=str(character_id),
            set_at_epoch=ctx.epoch,
        )
        replace_component(bait_item, bait)
        return ok(
            BaitSetEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(bait_item.id),),
                    bait_id=str(bait_item.id),
                    target_species=target_species,
                    potency=bait.potency,
                )
            )
        )


class TranquilizeCreatureHandler:
    command_type = "tranquilize-creature"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        creature, error = _reachable_creature(
            ctx, character_id, command.payload.get("creature_id")
        )
        if creature is None:
            return rejected(error if error else "creature is required")
        item, error = _reachable_item(ctx, character_id, command.payload.get("tranquilizer_id"))
        if item is None:
            return rejected(error if error else "tranquilizer is required")
        if not item.has_component(TranquilizerComponent):
            return rejected("item is not a tranquilizer")
        tranquilizer = item.get_component(TranquilizerComponent)
        if tranquilizer.uses <= 0:
            return rejected("tranquilizer is spent")

        duration = int(command.payload.get("duration_seconds") or 60 * 60)
        sedated_until = ctx.epoch + max(60, duration)
        replace_component(
            item,
            replace(tranquilizer, uses=tranquilizer.uses - 1),
        )
        replace_component(
            creature,
            TranquilizerComponent(
                potency=tranquilizer.potency,
                uses=0,
                sedated_until_epoch=sedated_until,
            ),
        )
        return ok(
            CreatureTranquilizedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature.id), str(item.id)),
                    creature_id=str(creature.id),
                    tranquilizer_id=str(item.id),
                    sedated_until_epoch=sedated_until,
                )
            )
        )


class ApproachCreatureHandler:
    command_type = "approach-creature"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        creature, error = _reachable_creature(
            ctx, character_id, command.payload.get("creature_id")
        )
        if creature is None:
            return rejected(error if error else "creature is required")
        taming, trust, fear = _progress_taming(
            ctx, character_id, creature, base_progress=0.5
        )
        return ok(
            TamingProgressedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature.id),),
                    creature_id=str(creature.id),
                    progress=taming.progress,
                    required=taming.required,
                    trust=trust.amount,
                    fear=fear.amount,
                )
            )
        )


class TameCreatureHandler:
    command_type = "tame-creature"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        creature, error = _reachable_creature(
            ctx, character_id, command.payload.get("creature_id")
        )
        if creature is None:
            return rejected(error if error else "creature is required")
        if _companion_for_actor(creature, character_id) is not None:
            return rejected("creature is already your companion")
        taming, trust, fear = _progress_taming(ctx, character_id, creature, base_progress=1.0)
        events: list[DomainEvent] = [
            TamingProgressedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature.id),),
                    creature_id=str(creature.id),
                    progress=taming.progress,
                    required=taming.required,
                    trust=trust.amount,
                    fear=fear.amount,
                )
            )
        ]
        if taming.progress >= taming.required:
            role = str(command.payload.get("role") or "companion")
            replace_component(creature, replace(taming, tamed=True))
            replace_component(creature, CompanionComponent(owner_id=str(character_id), role=role))
            events.append(
                CreatureTamedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.ROOM,
                        actor_id=str(character_id),
                        room_id=_room_id(ctx.world, character_id),
                        target_ids=(str(creature.id),),
                        creature_id=str(creature.id),
                        owner_id=str(character_id),
                        role=role,
                    )
                )
            )
        return ok(*events)


class TrainCommandHandler:
    command_type = "train-command"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        creature, error = _reachable_creature(
            ctx, character_id, command.payload.get("creature_id")
        )
        if creature is None:
            return rejected(error if error else "creature is required")
        if _companion_for_actor(creature, character_id) is None:
            return rejected("creature is not your companion")
        command_name = str(command.payload.get("command_name") or "").strip()
        if not command_name:
            return rejected("command name is required")

        training = (
            creature.get_component(TrainingComponent)
            if creature.has_component(TrainingComponent)
            else TrainingComponent()
        )
        progress = dict(training.progress or {})
        progress[command_name] = progress.get(command_name, 0.0) + float(
            command.payload.get("progress") or 1.0
        )
        learned = training.learned_commands
        if progress[command_name] >= training.required and command_name not in learned:
            learned = (*learned, command_name)
        replace_component(
            creature,
            replace(training, learned_commands=learned, progress=progress),
        )
        if command_name not in learned:
            return ok()
        return ok(
            CommandTrainedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature.id),),
                    creature_id=str(creature.id),
                    command_name=command_name,
                )
            )
        )


class MountCreatureHandler:
    command_type = "mount-creature"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        creature, error = _reachable_creature(
            ctx, character_id, command.payload.get("creature_id")
        )
        if creature is None:
            return rejected(error if error else "creature is required")
        if _companion_for_actor(creature, character_id) is None:
            return rejected("creature is not your companion")
        replace_component(creature, MountComponent(rider_id=str(character_id), mounted=True))
        return ok(
            CreatureMountedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature.id),),
                    creature_id=str(creature.id),
                    rider_id=str(character_id),
                )
            )
        )


class CommandCompanionHandler:
    command_type = "command-companion"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        creature, error = _reachable_creature(
            ctx, character_id, command.payload.get("creature_id")
        )
        if creature is None:
            return rejected(error if error else "creature is required")
        if _companion_for_actor(creature, character_id) is None:
            return rejected("creature is not your companion")
        command_name = str(command.payload.get("command_name") or "").strip()
        if not command_name:
            return rejected("command name is required")
        training = (
            creature.get_component(TrainingComponent)
            if creature.has_component(TrainingComponent)
            else TrainingComponent()
        )
        if command_name not in training.learned_commands:
            return rejected("command has not been trained")

        target_id = str(command.payload.get("target_id") or "")
        replace_component(
            creature,
            CommandComponent(
                command_name=command_name,
                commanded_by_id=str(character_id),
                target_id=target_id,
                issued_at_epoch=ctx.epoch,
            ),
        )
        if command_name == "guard":
            replace_component(
                creature,
                GuardBehaviorComponent(
                    location_id=target_id or (_room_id(ctx.world, character_id) or ""),
                    active=True,
                ),
            )
        if command_name == "hunt":
            replace_component(
                creature,
                HuntBehaviorComponent(target_species=target_id, active=True),
            )
        return ok(
            CompanionCommandedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature.id),),
                    creature_id=str(creature.id),
                    command_name=command_name,
                    target_id=target_id,
                )
            )
        )


class RecallCreatureHandler:
    command_type = "recall-creature"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        creature_id = parse_entity_id(command.payload.get("creature_id"))
        if creature_id is None:
            return rejected("invalid creature id")
        if not ctx.world.has_entity(creature_id):
            return rejected("creature does not exist")
        creature = ctx.entity(creature_id)
        if not _is_creature(creature):
            return rejected("target is not a creature")
        if _companion_for_actor(creature, character_id) is None:
            return rejected("creature is not your companion")
        room_id = container_of(ctx.entity(character_id))
        if room_id is None or not ctx.world.has_entity(room_id):
            return rejected("character is not in a room")
        _move_to_room(ctx.world, creature, room_id)
        replace_component(
            creature,
            RecallComponent(home_room_id=str(room_id), last_recalled_epoch=ctx.epoch),
        )
        return ok(
            CreatureRecalledEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    recalled_room_id=str(room_id),
                    target_ids=(str(creature.id),),
                    creature_id=str(creature.id),
                    room_id=str(room_id),
                )
            )
        )


class BuildEnclosureHandler:
    command_type = "build-enclosure"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        room, error = _current_or_requested_room(ctx, character_id, command.payload.get("room_id"))
        if room is None:
            return rejected(error if error else "room is required")
        if room.has_component(EnclosureComponent):
            return rejected("room is already an enclosure")
        name = str(command.payload.get("name") or _entity_name(room))
        capacity = int(command.payload.get("capacity") or 4)
        replace_component(
            room,
            EnclosureComponent(
                name=name,
                capacity=max(1, capacity),
                built_by_id=str(character_id),
                built_at_epoch=ctx.epoch,
            ),
        )
        replace_component(room, FenceComponent())
        replace_component(room, GateComponent(open=False, locked=True))
        if command.payload.get("feeding_pen"):
            replace_component(room, FeedingPenComponent())
        if command.payload.get("quarantine"):
            replace_component(room, QuarantinePenComponent())
        return ok(
            EnclosureBuiltEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(room.id),
                    target_ids=(str(room.id),),
                    enclosure_id=str(room.id),
                    name=name,
                )
            )
        )


class RepairFenceHandler:
    command_type = "repair-fence"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        enclosure, error = _enclosure_entity(
            ctx, character_id, command.payload.get("enclosure_id")
        )
        if enclosure is None:
            return rejected(error if error else "enclosure is required")
        fence = (
            enclosure.get_component(FenceComponent)
            if enclosure.has_component(FenceComponent)
            else FenceComponent(integrity=0.0)
        )
        amount = float(command.payload.get("amount") or 2.0)
        updated = replace(fence, integrity=min(fence.maximum, fence.integrity + max(0.0, amount)))
        replace_component(enclosure, updated)
        return ok(
            FenceRepairedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(enclosure.id),
                    target_ids=(str(enclosure.id),),
                    enclosure_id=str(enclosure.id),
                    integrity=updated.integrity,
                )
            )
        )


class ReinforceGateHandler:
    command_type = "reinforce-gate"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        enclosure, error = _enclosure_entity(
            ctx, character_id, command.payload.get("enclosure_id")
        )
        if enclosure is None:
            return rejected(error if error else "enclosure is required")
        if not enclosure.has_component(GateComponent):
            return rejected("enclosure has no gate")
        current = (
            enclosure.get_component(ReinforcementComponent)
            if enclosure.has_component(ReinforcementComponent)
            else ReinforcementComponent()
        )
        amount = float(command.payload.get("amount") or 1.0)
        updated = replace(current, amount=current.amount + max(0.0, amount))
        replace_component(enclosure, updated)
        return ok(
            GateReinforcedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(enclosure.id),
                    target_ids=(str(enclosure.id),),
                    enclosure_id=str(enclosure.id),
                    reinforcement=updated.amount,
                )
            )
        )


class LockPenHandler:
    command_type = "lock-pen"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        enclosure, error = _enclosure_entity(
            ctx, character_id, command.payload.get("enclosure_id")
        )
        if enclosure is None:
            return rejected(error if error else "enclosure is required")
        gate = (
            enclosure.get_component(GateComponent)
            if enclosure.has_component(GateComponent)
            else GateComponent()
        )
        replace_component(enclosure, replace(gate, open=False, locked=True))
        return ok(
            PenLockedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(enclosure.id),
                    target_ids=(str(enclosure.id),),
                    enclosure_id=str(enclosure.id),
                )
            )
        )


class OpenPenHandler:
    command_type = "open-pen"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        enclosure, error = _enclosure_entity(
            ctx, character_id, command.payload.get("enclosure_id")
        )
        if enclosure is None:
            return rejected(error if error else "enclosure is required")
        gate = (
            enclosure.get_component(GateComponent)
            if enclosure.has_component(GateComponent)
            else GateComponent()
        )
        replace_component(enclosure, replace(gate, open=True, locked=False))
        return ok(
            PenOpenedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(enclosure.id),
                    target_ids=(str(enclosure.id),),
                    enclosure_id=str(enclosure.id),
                )
            )
        )


class TriggerContainmentHandler:
    command_type = "trigger-containment"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        enclosure, error = _enclosure_entity(
            ctx, character_id, command.payload.get("enclosure_id")
        )
        if enclosure is None:
            return rejected(error if error else "enclosure is required")
        replace_component(
            enclosure,
            ContainmentProtocolComponent(active=True, triggered_at_epoch=ctx.epoch),
        )
        gate = (
            enclosure.get_component(GateComponent)
            if enclosure.has_component(GateComponent)
            else GateComponent()
        )
        replace_component(enclosure, replace(gate, open=False, locked=True))
        replace_component(enclosure, EscapeRiskComponent(risk=0.0, last_updated_epoch=ctx.epoch))
        return ok(
            ContainmentTriggeredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(enclosure.id),
                    target_ids=(str(enclosure.id),),
                    enclosure_id=str(enclosure.id),
                )
            )
        )


class RecaptureCreatureHandler:
    command_type = "recapture-creature"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        creature, error = _reachable_creature(
            ctx, character_id, command.payload.get("creature_id")
        )
        if creature is None:
            return rejected(error if error else "creature is required")
        enclosure, error = _enclosure_entity(
            ctx, character_id, command.payload.get("enclosure_id")
        )
        if enclosure is None:
            return rejected(error if error else "enclosure is required")
        _move_to_room(ctx.world, creature, enclosure.id)
        gate = (
            enclosure.get_component(GateComponent)
            if enclosure.has_component(GateComponent)
            else GateComponent()
        )
        replace_component(enclosure, replace(gate, open=False, locked=True))
        replace_component(enclosure, EscapeRiskComponent(risk=0.0, last_updated_epoch=ctx.epoch))
        if creature.has_component(EscapeRiskComponent):
            replace_component(creature, EscapeRiskComponent())
        return ok(
            CreatureRecapturedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(enclosure.id),
                    target_ids=(str(creature.id), str(enclosure.id)),
                    creature_id=str(creature.id),
                    enclosure_id=str(enclosure.id),
                )
            )
        )


class HideFromCreatureHandler:
    command_type = "hide-from-creature"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        creature, error = _reachable_creature(
            ctx, character_id, command.payload.get("creature_id")
        )
        if creature is None:
            return rejected(error if error else "creature is required")
        fear = (
            creature.get_component(FearComponent)
            if creature.has_component(FearComponent)
            else FearComponent()
        )
        replace_component(creature, replace(fear, amount=max(0.0, fear.amount - 1.0)))
        return ok(
            HiddenFromCreatureEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature.id), str(character_id)),
                    creature_id=str(creature.id),
                    character_id=str(character_id),
                )
            )
        )


class EvacuateRoomHandler:
    command_type = "evacuate-room"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        room, error = _current_or_requested_room(ctx, character_id, command.payload.get("room_id"))
        if room is None:
            return rejected(error if error else "room is required")
        destination_id = parse_entity_id(command.payload.get("destination_id"))
        if destination_id is None or not ctx.world.has_entity(destination_id):
            return rejected("destination does not exist")
        destination = ctx.entity(destination_id)
        if not destination.has_component(RoomComponent):
            return rejected("destination is not a room")
        moved: list[str] = []
        for _edge, entity_id in tuple(room.get_relationships(Contains)):
            if not ctx.world.has_entity(entity_id):
                continue
            entity = ctx.entity(entity_id)
            if not entity.has_component(CharacterComponent) or _is_creature(entity):
                continue
            _move_to_room(ctx.world, entity, destination_id)
            moved.append(str(entity.id))
        return ok(
            RoomEvacuatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(room.id),
                    target_ids=(str(room.id), str(destination_id), *moved),
                    room_id_evacuated=str(room.id),
                    destination_id=str(destination_id),
                    character_ids=tuple(moved),
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
        if entity.has_component(TrackComponent):
            track = entity.get_component(TrackComponent)
            lines.append(f"Tracked creature: {name} near {track.room_id}.")
        if entity.has_component(TamingComponent):
            taming = entity.get_component(TamingComponent)
            state = "tamed" if taming.tamed else f"{taming.progress:g}/{taming.required:g}"
            lines.append(f"Taming progress for {name}: {state}.")
        if entity.has_component(CompanionComponent):
            companion = entity.get_component(CompanionComponent)
            if companion.owner_id == str(character.id):
                lines.append(f"Your {companion.role}: {name}.")
        if entity.has_component(TrainingComponent):
            training = entity.get_component(TrainingComponent)
            if training.learned_commands:
                commands = ", ".join(training.learned_commands)
                lines.append(f"{name} knows commands: {commands}.")
        if entity.has_component(CommandComponent):
            current = entity.get_component(CommandComponent)
            lines.append(f"{name} is commanded to {current.command_name}.")
        if entity.has_component(BaitComponent):
            bait = entity.get_component(BaitComponent)
            target = bait.target_species or "any creature"
            lines.append(f"Bait set for {target}: {name}.")
        if entity.has_component(EnclosureComponent):
            enclosure = entity.get_component(EnclosureComponent)
            lines.append(f"Enclosure nearby: {enclosure.name}.")
            if entity.has_component(FenceComponent):
                fence = entity.get_component(FenceComponent)
                lines.append(f"{enclosure.name} fence: {fence.integrity:g}/{fence.maximum:g}.")
            if entity.has_component(GateComponent):
                gate = entity.get_component(GateComponent)
                state = "open" if gate.open else "closed"
                lock = "locked" if gate.locked else "unlocked"
                lines.append(f"{enclosure.name} gate: {state}, {lock}.")
            if entity.has_component(EscapeRiskComponent):
                risk = entity.get_component(EscapeRiskComponent)
                if risk.risk > 0.0:
                    lines.append(f"{enclosure.name} escape risk: {risk.risk:g}.")
    return sorted(lines)


def install_dinosim(actor) -> None:
    ensure_dinosim_policy(actor)
    actor.register_consequence(IncubationConsequence())
    actor.register_consequence(EscapeRiskConsequence())


__all__ = [
    "AncientSampleComponent",
    "AncientSampleExtractedEvent",
    "ApproachCreatureHandler",
    "BaitComponent",
    "BaitSetEvent",
    "BreachComponent",
    "BuildEnclosureHandler",
    "CloneCandidateComponent",
    "ClonePreparedEvent",
    "CommandComponent",
    "CommandCompanionHandler",
    "CommandTrainedEvent",
    "CompanionCommandedEvent",
    "CompanionComponent",
    "ContainmentProtocolComponent",
    "ContainmentTriggeredEvent",
    "CreatureEscapedEvent",
    "CreatureMountedEvent",
    "CreatureRecapturedEvent",
    "CreatureRecalledEvent",
    "CreatureTamedEvent",
    "CreatureTrackedEvent",
    "CreatureTranquilizedEvent",
    "DinosaurComponent",
    "DinosimPolicyComponent",
    "EggComponent",
    "EggFertilizedEvent",
    "EggHatchedEvent",
    "EggIncubatedEvent",
    "EggLaidEvent",
    "EnclosureBuiltEvent",
    "EnclosureComponent",
    "EscapeRiskComponent",
    "EscapeRiskConsequence",
    "EvacuateRoomHandler",
    "ExtractAncientSampleHandler",
    "FeedingPenComponent",
    "FertilityComponent",
    "FertilizeEggHandler",
    "FearComponent",
    "FenceComponent",
    "FenceRepairedEvent",
    "FossilFragmentComponent",
    "FossilIdentifiedEvent",
    "GateComponent",
    "GateReinforcedEvent",
    "GuardBehaviorComponent",
    "HatchEggHandler",
    "HatchlingComponent",
    "HiddenFromCreatureEvent",
    "HideFromCreatureHandler",
    "HuntBehaviorComponent",
    "IdentifyFossilHandler",
    "IncubateEggHandler",
    "IncubationComponent",
    "IncubationConsequence",
    "KaijuComponent",
    "LayEggHandler",
    "LockPenHandler",
    "MountComponent",
    "MountCreatureHandler",
    "OpenPenHandler",
    "PenLockedEvent",
    "PenOpenedEvent",
    "PrepareCloneHandler",
    "QuarantinePenComponent",
    "RecallComponent",
    "RecallCreatureHandler",
    "RecaptureCreatureHandler",
    "ReinforceGateHandler",
    "ReinforcementComponent",
    "RepairFenceHandler",
    "ReptileProcreationComponent",
    "RoomEvacuatedEvent",
    "ScentComponent",
    "SettlementDamageComponent",
    "SetBaitHandler",
    "SpeciesComponent",
    "SpeciesIdentificationComponent",
    "StampedeComponent",
    "StampedeStartedEvent",
    "TameCreatureHandler",
    "TamingComponent",
    "TamingProgressedEvent",
    "TrackComponent",
    "TrackCreatureHandler",
    "TrainCommandHandler",
    "TrainingComponent",
    "TranquilizeCreatureHandler",
    "TranquilizerComponent",
    "TriggerContainmentHandler",
    "TrustComponent",
    "dinosim_fragments",
    "ensure_dinosim_policy",
    "install_dinosim",
]
