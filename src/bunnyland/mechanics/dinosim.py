"""Dino-sim lifecycle, cloning, eggs, and kaiju incident hooks.

This first slice keeps the package focused on three primary loops:
fossil/species identification and cloning, egg handling/reptile procreation, and kaiju
storyteller support. It intentionally does not add park guests or attraction management.
"""

from __future__ import annotations

from dataclasses import replace
from random import Random

from pydantic.dataclasses import dataclass
from relics import Component, Entity, EntityId, World

from ..core.commands import SubmittedCommand
from ..core.components import (
    CharacterComponent,
    IdentityComponent,
    PortableComponent,
    RegionComponent,
    RoomComponent,
)
from ..core.ecs import (
    container_of,
    parse_entity_id,
    reachable_ids,
    replace_component,
    spawn_entity,
)
from ..core.ecs import (
    entity_room_id as _entity_room_id,
)
from ..core.ecs import (
    reachable_entity as _reachable_entity,
)
from ..core.ecs import (
    remove_from_container as _remove_from_container,
)
from ..core.ecs import (
    room_id_for as _room_id,
)
from ..core.edges import ContainmentMode, Contains, ExitTo
from ..core.events import DomainEvent, EventVisibility
from ..core.events import event_base as _event_base
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected
from ..prompts import ComponentPromptContext
from .colonysim import ResourceStackComponent
from .lifesim import AgeComponent, LifeStageComponent

DEFAULT_INCUBATION_SECONDS = 24 * 60 * 60

_KAIJU_NAMES = (
    "rampaging kaiju alpha",
    "rampaging kaiju beta",
    "rampaging kaiju gamma",
    "rampaging kaiju delta",
)

_KAIJU_ATTACKS = ("trample", "tail sweep", "sky roar", "building crush")


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

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        name = _entity_name(ctx.entity)
        if ctx.entity.has_component(SpeciesIdentificationComponent):
            identification = ctx.entity.get_component(SpeciesIdentificationComponent)
            return (f"Nearby fossil: {name} ({identification.species_name}).",)
        return (f"Nearby unidentified fossil: {name}.",)


@dataclass(frozen=True)
class FossilSurveyComponent(Component):
    surveyed_by: tuple[str, ...] = ()
    excavation_progress: float = 0.0
    stabilized: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "stabilized" if self.stabilized else f"excavation {self.excavation_progress:g}"
        return (f"Fossil survey {_entity_name(ctx.entity)}: {state}.",)


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

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Nearby ancient sample: {_entity_name(ctx.entity)} ({self.species_name}).",)


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

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "fertilized" if self.fertilized else "unfertilized"
        if ctx.entity.has_component(IncubationComponent):
            incubation = ctx.entity.get_component(IncubationComponent)
            state = "ready to hatch" if incubation.ready else "incubating"
            if incubation.temperature is not None:
                state = f"{state}, {incubation.temperature:g} C"
        return (f"Nearby egg: {_entity_name(ctx.entity)} ({self.species_name}, {state}).",)


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
    temperature: float | None = None
    brooded_by: str | None = None


@dataclass(frozen=True)
class LabIncubationComponent(Component):
    lab_id: str
    active: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not self.active:
            return ()
        return (f"Lab incubation active for {_entity_name(ctx.entity)}: {self.lab_id}.",)


@dataclass(frozen=True)
class HatchlingComponent(Component):
    hatched_at_epoch: int
    egg_id: str


@dataclass(frozen=True)
class EggInspectionComponent(Component):
    inspected_by: str
    viability: float = 1.0
    inspected_at_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Egg inspection for {_entity_name(ctx.entity)}: viability {self.viability:g}.",)


@dataclass(frozen=True)
class ImprintComponent(Component):
    imprinted_by: str
    bond: float = 1.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if ctx.target is None or self.imprinted_by != str(ctx.target.id):
            return ()
        return (f"Imprinted creature: {_entity_name(ctx.entity)} bond {self.bond:g}.",)


@dataclass(frozen=True)
class JuvenileCareComponent(Component):
    cared_by: str
    care_level: float = 0.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Juvenile care for {_entity_name(ctx.entity)}: {self.care_level:g}.",)


@dataclass(frozen=True)
class WaterCreatureComponent(Component):
    species_name: str
    depth_preference: str = "shallows"

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (
            f"Water creature {_entity_name(ctx.entity)}: "
            f"{self.species_name} in {self.depth_preference}.",
        )


@dataclass(frozen=True)
class WaterStudyComponent(Component):
    studied_by: tuple[str, ...] = ()

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        studied = ctx.target is not None and str(ctx.target.id) in self.studied_by
        state = "studied" if studied else "unstudied"
        return (f"Water study {_entity_name(ctx.entity)}: {state}.",)


@dataclass(frozen=True)
class BroodingComponent(Component):
    brooder_id: str
    warmth: float = 1.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Brooding {_entity_name(ctx.entity)}: warmth {self.warmth:g}.",)


@dataclass(frozen=True)
class ContainmentPanicComponent(Component):
    severity: int = 1
    active: bool = True

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not self.active or not ctx.entity.has_component(EnclosureComponent):
            return ()
        enclosure = ctx.entity.get_component(EnclosureComponent)
        return (f"{enclosure.name} containment panic: severity {self.severity}.",)


@dataclass(frozen=True)
class TrackComponent(Component):
    room_id: str
    freshness: float = 1.0
    last_tracked_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Tracked creature: {_entity_name(ctx.entity)} near {self.room_id}.",)


@dataclass(frozen=True)
class TerritoryComponent(Component):
    species_name: str = ""
    marked_by: str | None = None
    marked_at_epoch: int = 0
    threat_level: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "marked" if self.marked_by else "unmarked"
        return (
            f"Territory {_entity_name(ctx.entity)}: "
            f"{self.species_name or 'unknown species'}, {state}.",
        )


@dataclass(frozen=True)
class HerdComponent(Component):
    species_name: str
    size: int = 1
    last_tracked_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Herd {_entity_name(ctx.entity)}: {self.species_name} x{self.size}.",)


@dataclass(frozen=True)
class NestComponent(Component):
    species_name: str
    prepared: bool = False
    prepared_by: str | None = None
    prepared_at_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "prepared" if self.prepared else "unprepared"
        return (f"Nest {_entity_name(ctx.entity)}: {self.species_name}, {state}.",)


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

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        target = self.target_species or "any creature"
        return (f"Bait set for {target}: {_entity_name(ctx.entity)}.",)


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

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "tamed" if self.tamed else f"{self.progress:g}/{self.required:g}"
        return (f"Taming progress for {_entity_name(ctx.entity)}: {state}.",)


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

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not self.learned_commands:
            return ()
        commands = ", ".join(self.learned_commands)
        return (f"{_entity_name(ctx.entity)} knows commands: {commands}.",)


@dataclass(frozen=True)
class CommandComponent(Component):
    command_name: str
    commanded_by_id: str
    target_id: str = ""
    issued_at_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"{_entity_name(ctx.entity)} is commanded to {self.command_name}.",)


@dataclass(frozen=True)
class MountComponent(Component):
    rider_id: str = ""
    mounted: bool = False


@dataclass(frozen=True)
class CompanionComponent(Component):
    owner_id: str
    role: str = "companion"

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if ctx.target is None or self.owner_id != str(ctx.target.id):
            return ()
        return (f"Your {self.role}: {_entity_name(ctx.entity)}.",)


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

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"Enclosure nearby: {self.name}.",)


@dataclass(frozen=True)
class FenceComponent(Component):
    integrity: float = 10.0
    maximum: float = 10.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.entity.has_component(EnclosureComponent):
            return ()
        enclosure = ctx.entity.get_component(EnclosureComponent)
        return (f"{enclosure.name} fence: {self.integrity:g}/{self.maximum:g}.",)


@dataclass(frozen=True)
class GateComponent(Component):
    open: bool = False
    locked: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.entity.has_component(EnclosureComponent):
            return ()
        enclosure = ctx.entity.get_component(EnclosureComponent)
        state = "open" if self.open else "closed"
        lock = "locked" if self.locked else "unlocked"
        return (f"{enclosure.name} gate: {state}, {lock}.",)


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

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if self.risk <= 0.0 or not ctx.entity.has_component(EnclosureComponent):
            return ()
        enclosure = ctx.entity.get_component(EnclosureComponent)
        return (f"{enclosure.name} escape risk: {self.risk:g}.",)


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
    difficulty: str = "major"
    target_room_id: str | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Kaiju threat nearby: {_entity_name(ctx.entity)} threat {self.threat_level}.",)


@dataclass(frozen=True)
class KaijuSpawnSpec:
    name: str
    threat_level: int
    difficulty: str
    attack_type: str = "trample"
    damage: float = 5.0
    roar_fear: float = 3.0


@dataclass(frozen=True)
class SettlementDamageComponent(Component):
    severity: int = 1
    repaired: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if self.repaired:
            return ()
        return (f"Settlement damage on {_entity_name(ctx.entity)}: severity {self.severity}.",)


@dataclass(frozen=True)
class CreatureAttackComponent(Component):
    damage: float = 2.0
    attack_type: str = "bite"

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Dangerous creature: {_entity_name(ctx.entity)} ({self.attack_type}).",)


@dataclass(frozen=True)
class RoarComponent(Component):
    fear: float = 1.0
    radius: str = "room"


@dataclass(frozen=True)
class ChargeComponent(Component):
    damage: float = 3.0
    prepared: bool = False


@dataclass(frozen=True)
class GrappleComponent(Component):
    target_id: str = ""
    active: bool = True


@dataclass(frozen=True)
class TrampleComponent(Component):
    damage: float = 4.0


@dataclass(frozen=True)
class ArmorPlateComponent(Component):
    rating: float = 1.0


@dataclass(frozen=True)
class WeakPointComponent(Component):
    label: str = "weak point"
    exposed: bool = True
    damage_multiplier: float = 2.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not self.exposed:
            return ()
        return (f"{_entity_name(ctx.entity)} has exposed weak point: {self.label}.",)


@dataclass(frozen=True)
class PackHuntComponent(Component):
    pack_id: str = ""
    bonus: float = 1.0


@dataclass(frozen=True)
class ApexPredatorComponent(Component):
    threat_level: int = 5

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if self.threat_level <= 0:
            return ()
        return (f"Apex predator nearby: {_entity_name(ctx.entity)} threat {self.threat_level}.",)


@dataclass(frozen=True)
class ArmyResponseComponent(Component):
    called: bool = False
    strength: float = 5.0
    called_at_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not self.called:
            return ()
        return (
            f"Army response signaled for {_entity_name(ctx.entity)}: "
            f"strength {self.strength:g}.",
        )


@dataclass(frozen=True)
class FeedStoreComponent(Component):
    feed: float = 0.0
    capacity: float = 20.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Feed store at {_entity_name(ctx.entity)}: {self.feed:g}/{self.capacity:g}.",)


@dataclass(frozen=True)
class CreatureNeedComponent(Component):
    """Hunger and stress needs for a living creature (catalogue 11.2).

    Hunger rises over time and feeds stress once the creature goes hungry; feeding and
    calming bring them back down.
    """

    hunger: float = 0.0
    stress: float = 0.0
    hunger_per_hour: float = 5.0
    last_updated_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "hungry" if self.hunger >= HUNGRY_THRESHOLD else "fed"
        return (
            f"Creature {_entity_name(ctx.entity)}: hunger {self.hunger:g} "
            f"({state}), stress {self.stress:g}.",
        )


@dataclass(frozen=True)
class CreatureProductComponent(Component):
    product_type: str
    quantity: float = 1.0
    source_creature_id: str = ""
    collected_at_epoch: int = 0
    renewable: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if self.quantity <= 0.0:
            return ()
        return (
            f"Creature product available from {_entity_name(ctx.entity)}: "
            f"{self.product_type} x{self.quantity:g}.",
        )


@dataclass(frozen=True)
class HideComponent(Component):
    quality: float = 1.0
    harvested: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if self.harvested:
            return ()
        return (f"{_entity_name(ctx.entity)} has harvestable hide.",)


@dataclass(frozen=True)
class BoneComponent(Component):
    quality: float = 1.0
    harvested: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if self.harvested:
            return ()
        return (f"{_entity_name(ctx.entity)} has harvestable bone.",)


@dataclass(frozen=True)
class ToxinComponent(Component):
    potency: float = 1.0
    quantity: float = 1.0
    maximum: float = 1.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if self.quantity <= 0.0:
            return ()
        return (f"{_entity_name(ctx.entity)} has toxin available: {self.quantity:g}.",)


@dataclass(frozen=True)
class CreatureMilkComponent(Component):
    volume: float = 1.0
    maximum: float = 1.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if self.volume <= 0.0:
            return ()
        return (f"{_entity_name(ctx.entity)} has milk available: {self.volume:g}.",)


@dataclass(frozen=True)
class RanchLaborComponent(Component):
    work_type: str = "haul"
    target_id: str = ""
    assigned_by_id: str = ""
    active: bool = True

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not self.active:
            return ()
        return (f"{_entity_name(ctx.entity)} is assigned to ranch work: {self.work_type}.",)


@dataclass(frozen=True)
class GuardAnimalComponent(Component):
    location_id: str = ""
    assigned_by_id: str = ""
    active: bool = True

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not self.active:
            return ()
        return (f"{_entity_name(ctx.entity)} is assigned as guard animal for {self.location_id}.",)


class FossilIdentifiedEvent(DomainEvent):
    fossil_id: str
    species_name: str
    confidence: float


class FossilSurveyedEvent(DomainEvent):
    fossil_id: str


class FossilExcavatedEvent(DomainEvent):
    fossil_id: str
    progress: float


class FossilCleanedEvent(DomainEvent):
    fossil_id: str


class FossilStabilizedEvent(DomainEvent):
    fossil_id: str


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


class LabIncubationStartedEvent(DomainEvent):
    egg_id: str
    lab_id: str


class EggInspectedEvent(DomainEvent):
    egg_id: str
    viability: float


class CreatureImprintedEvent(DomainEvent):
    creature_id: str
    bond: float


class JuvenileCareGivenEvent(DomainEvent):
    creature_id: str
    care_level: float


class WaterCreatureStudiedEvent(DomainEvent):
    creature_id: str
    species_name: str


class BroodingStartedEvent(DomainEvent):
    egg_id: str
    warmth: float


class IncubationTemperatureSetEvent(DomainEvent):
    egg_id: str
    temperature: float


class ContainmentPanicStartedEvent(DomainEvent):
    enclosure_id: str
    severity: int


class EggHatchedEvent(DomainEvent):
    egg_id: str
    hatchling_id: str
    species_name: str


class CreatureTrackedEvent(DomainEvent):
    creature_id: str
    tracked_room_id: str
    species_name: str


class TerritoryMarkedEvent(DomainEvent):
    territory_id: str
    species_name: str


class HerdTrackedEvent(DomainEvent):
    herd_id: str
    species_name: str
    size: int


class NestPreparedEvent(DomainEvent):
    nest_id: str
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


class CreatureAttackedEvent(DomainEvent):
    creature_id: str
    character_id: str
    damage: float
    attack_type: str


class CreatureRoaredEvent(DomainEvent):
    creature_id: str
    fear: float


class CreatureChargedEvent(DomainEvent):
    creature_id: str
    character_id: str
    damage: float
    dodged: bool = False


class CreatureTrampledEvent(DomainEvent):
    creature_id: str
    character_id: str
    damage: float


class WeakPointHitEvent(DomainEvent):
    creature_id: str
    label: str
    damage: float


class ApexPredatorAppearedEvent(DomainEvent):
    creature_id: str
    threat_level: int


class KaijuArrivedEvent(DomainEvent):
    creature_id: str
    threat_level: int


class ArmyCalledEvent(DomainEvent):
    room_id_called: str
    strength: float


class SettlementDamagedEvent(DomainEvent):
    settlement_id: str
    severity: int


class PredatorDrivenOffEvent(DomainEvent):
    creature_id: str
    from_room_id: str
    to_room_id: str = ""


class SettlementDamageRepairedEvent(DomainEvent):
    settlement_id: str
    severity: int
    repaired: bool


class FeedStockedEvent(DomainEvent):
    feed_store_id: str
    amount: float
    feed: float
    resource_type: str = ""
    resource_spent: int = 0


class CreatureNeedsChangedEvent(DomainEvent):
    creature_id: str
    hunger: float
    stress: float


class CreatureFedEvent(DomainEvent):
    creature_id: str
    hunger: float


class CreatureCalmedEvent(DomainEvent):
    creature_id: str
    stress: float


class CreatureObservedEvent(DomainEvent):
    creature_id: str
    hunger: float
    stress: float


class CreatureProductCollectedEvent(DomainEvent):
    creature_id: str
    product_id: str
    product_type: str
    quantity: float


class RanchWorkAssignedEvent(DomainEvent):
    creature_id: str
    work_type: str
    target_id: str = ""


class GuardAssignedEvent(DomainEvent):
    creature_id: str
    location_id: str


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
    if entity.has_component(RoomComponent):
        return entity.get_component(RoomComponent).title
    return str(entity.id)


def _is_creature(entity: Entity) -> bool:
    return (
        entity.has_component(DinosaurComponent)
        or entity.has_component(SpeciesComponent)
        or entity.has_component(ReptileProcreationComponent)
        or entity.has_component(KaijuComponent)
    )


def kaiju_difficulty_for_threat(threat_level: int) -> str:
    if threat_level >= 10:
        return "colossal"
    if threat_level >= 7:
        return "epic"
    return "major"


def generate_kaiju_spawn_specs(
    attack_budget: int | float, seed: str = ""
) -> tuple[KaijuSpawnSpec, ...]:
    total = max(1, int(round(attack_budget)))
    count = 1
    if total >= 18:
        count = 3
    elif total >= 10:
        count = 2
    base = total // count
    remainder = total % count
    threats = [base + (1 if index < remainder else 0) for index in range(count)]
    rng = Random(seed)
    names = list(_KAIJU_NAMES)
    attacks = list(_KAIJU_ATTACKS)
    rng.shuffle(names)
    rng.shuffle(attacks)
    return tuple(
        KaijuSpawnSpec(
            name=names[index],
            threat_level=threat,
            difficulty=kaiju_difficulty_for_threat(threat),
            attack_type=attacks[index],
            damage=float(max(4, threat)),
            roar_fear=float(max(2, threat // 2)),
        )
        for index, threat in enumerate(threats)
    )


def _region_for_room(world: World, room: Entity) -> Entity | None:
    for source_id, edge in room.get_incoming_relationships(Contains):
        if edge.mode != ContainmentMode.REGION or not world.has_entity(source_id):
            continue
        source = world.get_entity(source_id)
        if source.has_component(RegionComponent):
            return source
    return None


def _region_rooms(world: World, region: Entity) -> tuple[Entity, ...]:
    rooms: list[Entity] = []
    stack = [region]
    seen: set[EntityId] = set()
    while stack:
        entity = stack.pop()
        if entity.id in seen:
            continue
        seen.add(entity.id)
        for edge, child_id in entity.get_relationships(Contains):
            if edge.mode != ContainmentMode.REGION or not world.has_entity(child_id):
                continue
            child = world.get_entity(child_id)
            if child.has_component(RoomComponent):
                rooms.append(child)
            if child.has_component(RegionComponent):
                stack.append(child)
    return tuple(sorted(rooms, key=lambda room: str(room.id)))


def selected_kaiju_rooms(
    world: World, target_room_id: EntityId | None, count: int, seed: str = ""
) -> tuple[Entity, ...]:
    if count <= 0 or target_room_id is None or not world.has_entity(target_room_id):
        return ()
    target_room = world.get_entity(target_room_id)
    if not target_room.has_component(RoomComponent):
        return ()
    region = _region_for_room(world, target_room)
    rooms = list(_region_rooms(world, region)) if region is not None else [target_room]
    if not rooms:
        rooms = [target_room]
    rng = Random(seed)
    rng.shuffle(rooms)
    if len(rooms) >= count:
        return tuple(rooms[:count])
    selected = list(rooms)
    while len(selected) < count:
        selected.append(rooms[len(selected) % len(rooms)])
    return tuple(selected)


class DinoIncidentEnrichment:
    """Dino-sim incident enrichment for generated storyteller kaiju attacks."""

    def __init__(self, world: World):
        self.world = world

    def subscribe(self, bus) -> None:
        from .storyteller import IncidentGeneratedEvent

        bus.subscribe(IncidentGeneratedEvent, self._on_incident)

    def _on_incident(self, event) -> None:
        if event.kind != "kaiju_attack" and "kaiju-spawn" not in event.wants:
            return
        from .storyteller import IncidentSpawned

        incident_id = parse_entity_id(event.incident_id)
        room_id = parse_entity_id(event.room_id)
        if (
            incident_id is None
            or room_id is None
            or not self.world.has_entity(incident_id)
            or not self.world.has_entity(room_id)
        ):
            return
        incident = self.world.get_entity(incident_id)
        if incident.get_relationships(IncidentSpawned):
            return
        specs = generate_kaiju_spawn_specs(event.budget_spent, event.seed)
        rooms = selected_kaiju_rooms(self.world, room_id, len(specs), event.seed)
        if len(rooms) != len(specs):
            return
        for spec, room in zip(specs, rooms, strict=True):
            kaiju = spawn_entity(
                self.world,
                [
                    IdentityComponent(
                        name=spec.name,
                        kind="character",
                        tags=("dinosim", "kaiju", spec.difficulty),
                    ),
                    CharacterComponent(species="kaiju"),
                    KaijuComponent(
                        threat_level=spec.threat_level,
                        difficulty=spec.difficulty,
                        target_room_id=str(room.id),
                    ),
                    CreatureAttackComponent(damage=spec.damage, attack_type=spec.attack_type),
                    RoarComponent(fear=spec.roar_fear, radius="region"),
                    TrampleComponent(damage=spec.damage),
                    ArmorPlateComponent(rating=max(1.0, spec.threat_level / 5)),
                    WeakPointComponent(label="glowing dorsal plate"),
                ],
            )
            room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), kaiju.id)
            incident.add_relationship(IncidentSpawned(kind="monster"), kaiju.id)
        replace_component(
            incident,
            SettlementDamageComponent(severity=max(1, int(round(event.budget_spent / 5)))),
        )
        incident.add_relationship(IncidentSpawned(kind="damage"), incident.id)


def _reachable_creature(
    ctx: HandlerContext, character_id: EntityId, requested_id: object
) -> tuple[Entity | None, str | None]:
    creature_id = parse_entity_id(requested_id)
    if creature_id is None:
        return None, "invalid creature id"
    if not ctx.world.has_entity(creature_id):
        return None, "creature does not exist"
    creature = _reachable_entity(ctx.world, character_id, creature_id)
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
    item = _reachable_entity(ctx.world, character_id, item_id)
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


def _creature_attack_damage(creature: Entity) -> tuple[float, str]:
    if not creature.has_component(CreatureAttackComponent):
        return 1.0, "attack"
    attack = creature.get_component(CreatureAttackComponent)
    return max(0.0, attack.damage), attack.attack_type


def _armor_rating(creature: Entity) -> float:
    if not creature.has_component(ArmorPlateComponent):
        return 0.0
    return max(0.0, creature.get_component(ArmorPlateComponent).rating)


def _pack_bonus(creature: Entity) -> float:
    if not creature.has_component(PackHuntComponent):
        return 0.0
    return max(0.0, creature.get_component(PackHuntComponent).bonus)


def _signal_room(
    ctx: HandlerContext, character_id: EntityId, requested_id: object
) -> tuple[Entity | None, str | None]:
    room, error = _current_or_requested_room(ctx, character_id, requested_id)
    if room is None:
        return None, error
    return room, None


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


def _spawn_creature_product(
    world: World,
    character: Entity,
    *,
    product_type: str,
    quantity: float,
    source_creature_id: str,
    epoch: int,
) -> Entity:
    product = spawn_entity(
        world,
        [
            IdentityComponent(
                name=f"{product_type} product",
                kind="creature_product",
                tags=("dinosim", "product", product_type),
            ),
            CreatureProductComponent(
                product_type=product_type,
                quantity=quantity,
                source_creature_id=source_creature_id,
                collected_at_epoch=epoch,
            ),
            PortableComponent(can_pick_up=True),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), product.id)
    return product


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
                room.get_component(FenceComponent) if room.has_component(FenceComponent) else None
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
        fossil = _reachable_entity(ctx.world, character_id, fossil_id)
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
        fossil = _reachable_entity(ctx.world, character_id, fossil_id)
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
        sample_entity = _reachable_entity(ctx.world, character_id, sample_id)
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
        parent = _reachable_entity(ctx.world, character_id, parent_id)
        if parent is None:
            return rejected("parent is not reachable")
        if (
            parent.has_component(FertilityComponent)
            and not parent.get_component(FertilityComponent).fertile
        ):
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
        egg_entity = _reachable_entity(ctx.world, character_id, egg_id)
        parent = _reachable_entity(ctx.world, character_id, parent_id)
        if egg_entity is None or parent is None:
            return rejected("egg or parent is not reachable")
        if not egg_entity.has_component(EggComponent):
            return rejected("target is not an egg")
        egg = egg_entity.get_component(EggComponent)
        if egg.fertilized:
            return rejected("egg is already fertilized")
        if (
            parent.has_component(FertilityComponent)
            and not parent.get_component(FertilityComponent).fertile
        ):
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
        egg_entity = _reachable_entity(ctx.world, character_id, egg_id)
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
        egg_entity = _reachable_entity(ctx.world, character_id, egg_id)
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


class SurveyFossilHandler:
    command_type = "survey-fossil"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        fossil_id = parse_entity_id(command.payload.get("fossil_id"))
        if character_id is None or fossil_id is None:
            return rejected("invalid character or fossil id")
        fossil = _reachable_entity(ctx.world, character_id, fossil_id)
        if fossil is None or not fossil.has_component(FossilFragmentComponent):
            return rejected("fossil is not reachable")
        survey = (
            fossil.get_component(FossilSurveyComponent)
            if fossil.has_component(FossilSurveyComponent)
            else FossilSurveyComponent()
        )
        replace_component(
            fossil,
            replace(survey, surveyed_by=tuple(sorted((*survey.surveyed_by, str(character_id))))),
        )
        return ok(
            FossilSurveyedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(fossil_id),),
                    fossil_id=str(fossil_id),
                )
            )
        )


class ExcavateFossilHandler:
    command_type = "excavate-fossil"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        fossil_id = parse_entity_id(command.payload.get("fossil_id"))
        if character_id is None or fossil_id is None:
            return rejected("invalid character or fossil id")
        fossil = _reachable_entity(ctx.world, character_id, fossil_id)
        if fossil is None or not fossil.has_component(FossilFragmentComponent):
            return rejected("fossil is not reachable")
        survey = (
            fossil.get_component(FossilSurveyComponent)
            if fossil.has_component(FossilSurveyComponent)
            else FossilSurveyComponent()
        )
        progress = min(
            1.0, survey.excavation_progress + float(command.payload.get("progress", 0.5))
        )
        replace_component(fossil, replace(survey, excavation_progress=progress))
        return ok(
            FossilExcavatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(fossil_id),),
                    fossil_id=str(fossil_id),
                    progress=progress,
                )
            )
        )


class CleanFossilHandler:
    command_type = "clean-fossil"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        fossil_id = parse_entity_id(command.payload.get("fossil_id"))
        if character_id is None or fossil_id is None:
            return rejected("invalid character or fossil id")
        fossil = _reachable_entity(ctx.world, character_id, fossil_id)
        if fossil is None or not fossil.has_component(FossilFragmentComponent):
            return rejected("fossil is not reachable")
        fragment = fossil.get_component(FossilFragmentComponent)
        replace_component(fossil, replace(fragment, cleaned=True))
        return ok(
            FossilCleanedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(fossil_id),),
                    fossil_id=str(fossil_id),
                )
            )
        )


class StabilizeFossilHandler:
    command_type = "stabilize-fossil"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        fossil_id = parse_entity_id(command.payload.get("fossil_id"))
        if character_id is None or fossil_id is None:
            return rejected("invalid character or fossil id")
        fossil = _reachable_entity(ctx.world, character_id, fossil_id)
        if fossil is None or not fossil.has_component(FossilFragmentComponent):
            return rejected("fossil is not reachable")
        survey = (
            fossil.get_component(FossilSurveyComponent)
            if fossil.has_component(FossilSurveyComponent)
            else FossilSurveyComponent()
        )
        replace_component(fossil, replace(survey, stabilized=True))
        return ok(
            FossilStabilizedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(fossil_id),),
                    fossil_id=str(fossil_id),
                )
            )
        )


class LabIncubateEggHandler:
    command_type = "lab-incubate-egg"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        result = IncubateEggHandler().execute(ctx, command)
        character_id = parse_entity_id(command.character_id)
        egg_id = parse_entity_id(command.payload.get("egg_id"))
        lab_id = str(command.payload.get("lab_id", "")).strip()
        if character_id is None or egg_id is None or not result.ok:
            return result
        egg = ctx.entity(egg_id)
        replace_component(egg, LabIncubationComponent(lab_id=lab_id, active=True))
        return ok(
            *result.events,
            LabIncubationStartedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(egg_id),),
                    egg_id=str(egg_id),
                    lab_id=lab_id,
                )
            ),
        )


class InspectEggHandler:
    command_type = "inspect-egg"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        egg_id = parse_entity_id(command.payload.get("egg_id"))
        if character_id is None or egg_id is None:
            return rejected("invalid character or egg id")
        egg = _reachable_entity(ctx.world, character_id, egg_id)
        if egg is None or not egg.has_component(EggComponent):
            return rejected("egg is not reachable")
        viability = float(command.payload.get("viability", 1.0))
        replace_component(
            egg,
            EggInspectionComponent(
                inspected_by=str(character_id),
                viability=viability,
                inspected_at_epoch=ctx.epoch,
            ),
        )
        return ok(
            EggInspectedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(egg_id),),
                    egg_id=str(egg_id),
                    viability=viability,
                )
            )
        )


class ImprintCreatureHandler:
    command_type = "imprint-creature"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        creature_id = parse_entity_id(command.payload.get("creature_id"))
        if character_id is None or creature_id is None:
            return rejected("invalid character or creature id")
        creature = _reachable_entity(ctx.world, character_id, creature_id)
        if creature is None or not _is_creature(creature):
            return rejected("creature is not reachable")
        bond = float(command.payload.get("bond", 1.0))
        replace_component(creature, ImprintComponent(imprinted_by=str(character_id), bond=bond))
        return ok(
            CreatureImprintedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature_id),),
                    creature_id=str(creature_id),
                    bond=bond,
                )
            )
        )


class CareForJuvenileHandler:
    command_type = "care-for-juvenile"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        creature_id = parse_entity_id(command.payload.get("creature_id"))
        if character_id is None or creature_id is None:
            return rejected("invalid character or creature id")
        creature = _reachable_entity(ctx.world, character_id, creature_id)
        if creature is None or not _is_creature(creature):
            return rejected("creature is not reachable")
        current = (
            creature.get_component(JuvenileCareComponent)
            if creature.has_component(JuvenileCareComponent)
            else JuvenileCareComponent(cared_by=str(character_id))
        )
        care_level = current.care_level + float(command.payload.get("care", 1.0))
        replace_component(
            creature, replace(current, cared_by=str(character_id), care_level=care_level)
        )
        return ok(
            JuvenileCareGivenEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature_id),),
                    creature_id=str(creature_id),
                    care_level=care_level,
                )
            )
        )


class StudyWaterCreatureHandler:
    command_type = "study-water-creature"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        creature_id = parse_entity_id(command.payload.get("creature_id"))
        if character_id is None or creature_id is None:
            return rejected("invalid character or creature id")
        creature = _reachable_entity(ctx.world, character_id, creature_id)
        if creature is None or not creature.has_component(WaterCreatureComponent):
            return rejected("water creature is not reachable")
        water = creature.get_component(WaterCreatureComponent)
        study = (
            creature.get_component(WaterStudyComponent)
            if creature.has_component(WaterStudyComponent)
            else WaterStudyComponent()
        )
        replace_component(
            creature,
            replace(study, studied_by=tuple(sorted((*study.studied_by, str(character_id))))),
        )
        return ok(
            WaterCreatureStudiedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature_id),),
                    creature_id=str(creature_id),
                    species_name=water.species_name,
                )
            )
        )


class BroodEggHandler:
    command_type = "brood-egg"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        egg_id = parse_entity_id(command.payload.get("egg_id"))
        if character_id is None or egg_id is None:
            return rejected("invalid character or egg id")
        egg = _reachable_entity(ctx.world, character_id, egg_id)
        if egg is None or not egg.has_component(EggComponent):
            return rejected("egg is not reachable")
        warmth = float(command.payload.get("warmth", 1.0))
        replace_component(egg, BroodingComponent(brooder_id=str(character_id), warmth=warmth))
        if egg.has_component(IncubationComponent):
            incubation = egg.get_component(IncubationComponent)
            replace_component(egg, replace(incubation, brooded_by=str(character_id)))
        return ok(
            BroodingStartedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(egg_id),),
                    egg_id=str(egg_id),
                    warmth=warmth,
                )
            )
        )


class SetIncubationTemperatureHandler:
    command_type = "set-incubation-temperature"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        egg_id = parse_entity_id(command.payload.get("egg_id"))
        if character_id is None or egg_id is None:
            return rejected("invalid character or egg id")
        egg = _reachable_entity(ctx.world, character_id, egg_id)
        if egg is None or not egg.has_component(IncubationComponent):
            return rejected("egg is not incubating")
        temperature = float(command.payload.get("temperature", 30.0))
        incubation = egg.get_component(IncubationComponent)
        replace_component(egg, replace(incubation, temperature=temperature))
        return ok(
            IncubationTemperatureSetEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(egg_id),),
                    egg_id=str(egg_id),
                    temperature=temperature,
                )
            )
        )


class TriggerContainmentPanicHandler:
    command_type = "trigger-containment-panic"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        enclosure_id = parse_entity_id(command.payload.get("enclosure_id"))
        if character_id is None or enclosure_id is None:
            return rejected("invalid character or enclosure id")
        enclosure = _reachable_entity(ctx.world, character_id, enclosure_id)
        if enclosure is None or not enclosure.has_component(EnclosureComponent):
            return rejected("enclosure is not reachable")
        severity = int(command.payload.get("severity", 1))
        replace_component(enclosure, ContainmentPanicComponent(severity=severity, active=True))
        return ok(
            ContainmentPanicStartedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(enclosure_id),),
                    enclosure_id=str(enclosure_id),
                    severity=severity,
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
        creature, error = _reachable_creature(ctx, character_id, command.payload.get("creature_id"))
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


class MarkTerritoryHandler:
    command_type = "mark-territory"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        territory_id = parse_entity_id(command.payload.get("territory_id"))
        if character_id is None or territory_id is None:
            return rejected("invalid character or territory id")
        territory = _reachable_entity(ctx.world, character_id, territory_id)
        if territory is None:
            return rejected("territory is not reachable")
        if not territory.has_component(TerritoryComponent):
            return rejected("target is not a territory")
        component = territory.get_component(TerritoryComponent)
        if component.marked_by == str(character_id):
            return rejected("territory is already marked by you")
        replace_component(
            territory,
            replace(component, marked_by=str(character_id), marked_at_epoch=ctx.epoch),
        )
        return ok(
            TerritoryMarkedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(territory.id),),
                    territory_id=str(territory.id),
                    species_name=component.species_name,
                )
            )
        )


class TrackHerdHandler:
    command_type = "track-herd"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        herd_id = parse_entity_id(command.payload.get("herd_id"))
        if character_id is None or herd_id is None:
            return rejected("invalid character or herd id")
        herd = _reachable_entity(ctx.world, character_id, herd_id)
        if herd is None:
            return rejected("herd is not reachable")
        if not herd.has_component(HerdComponent):
            return rejected("target is not a herd")
        component = herd.get_component(HerdComponent)
        replace_component(herd, replace(component, last_tracked_epoch=ctx.epoch))
        return ok(
            HerdTrackedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(herd.id),),
                    herd_id=str(herd.id),
                    species_name=component.species_name,
                    size=component.size,
                )
            )
        )


class PrepareNestHandler:
    command_type = "prepare-nest"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        nest_id = parse_entity_id(command.payload.get("nest_id"))
        if character_id is None or nest_id is None:
            return rejected("invalid character or nest id")
        nest = _reachable_entity(ctx.world, character_id, nest_id)
        if nest is None:
            return rejected("nest is not reachable")
        if not nest.has_component(NestComponent):
            return rejected("target is not a nest")
        component = nest.get_component(NestComponent)
        if component.prepared:
            return rejected("nest is already prepared")
        replace_component(
            nest,
            replace(
                component,
                prepared=True,
                prepared_by=str(character_id),
                prepared_at_epoch=ctx.epoch,
            ),
        )
        return ok(
            NestPreparedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(nest.id),),
                    nest_id=str(nest.id),
                    species_name=component.species_name,
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
        creature, error = _reachable_creature(ctx, character_id, command.payload.get("creature_id"))
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
        creature, error = _reachable_creature(ctx, character_id, command.payload.get("creature_id"))
        if creature is None:
            return rejected(error if error else "creature is required")
        taming, trust, fear = _progress_taming(ctx, character_id, creature, base_progress=0.5)
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
        creature, error = _reachable_creature(ctx, character_id, command.payload.get("creature_id"))
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
        creature, error = _reachable_creature(ctx, character_id, command.payload.get("creature_id"))
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
        creature, error = _reachable_creature(ctx, character_id, command.payload.get("creature_id"))
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
        creature, error = _reachable_creature(ctx, character_id, command.payload.get("creature_id"))
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
        enclosure, error = _enclosure_entity(ctx, character_id, command.payload.get("enclosure_id"))
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
        enclosure, error = _enclosure_entity(ctx, character_id, command.payload.get("enclosure_id"))
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
        enclosure, error = _enclosure_entity(ctx, character_id, command.payload.get("enclosure_id"))
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
        enclosure, error = _enclosure_entity(ctx, character_id, command.payload.get("enclosure_id"))
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
        enclosure, error = _enclosure_entity(ctx, character_id, command.payload.get("enclosure_id"))
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
        creature, error = _reachable_creature(ctx, character_id, command.payload.get("creature_id"))
        if creature is None:
            return rejected(error if error else "creature is required")
        enclosure, error = _enclosure_entity(ctx, character_id, command.payload.get("enclosure_id"))
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
        creature, error = _reachable_creature(ctx, character_id, command.payload.get("creature_id"))
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


class DodgeCreatureHandler:
    command_type = "dodge-creature"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        creature, error = _reachable_creature(ctx, character_id, command.payload.get("creature_id"))
        if creature is None:
            return rejected(error if error else "creature is required")
        if creature.has_component(ChargeComponent):
            charge = creature.get_component(ChargeComponent)
            replace_component(creature, replace(charge, prepared=False))
            damage = charge.damage
        else:
            damage = _creature_attack_damage(creature)[0]
        fear = (
            creature.get_component(FearComponent)
            if creature.has_component(FearComponent)
            else FearComponent()
        )
        replace_component(creature, replace(fear, amount=fear.amount + 0.5))
        return ok(
            CreatureChargedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature.id), str(character_id)),
                    creature_id=str(creature.id),
                    character_id=str(character_id),
                    damage=damage,
                    dodged=True,
                )
            )
        )


class FightCreatureHandler:
    command_type = "fight-creature"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        creature, error = _reachable_creature(ctx, character_id, command.payload.get("creature_id"))
        if creature is None:
            return rejected(error if error else "creature is required")
        damage = max(0.0, float(command.payload.get("damage") or 1.0) - _armor_rating(creature))
        fear = (
            creature.get_component(FearComponent)
            if creature.has_component(FearComponent)
            else FearComponent()
        )
        replace_component(creature, replace(fear, amount=fear.amount + damage))
        if creature.has_component(GrappleComponent):
            grapple = creature.get_component(GrappleComponent)
            if not grapple.target_id or grapple.target_id == str(character_id):
                replace_component(
                    creature,
                    replace(grapple, target_id=str(character_id), active=False),
                )

        attack_damage, attack_type = _creature_attack_damage(creature)
        events: list[DomainEvent] = [
            CreatureAttackedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature.id), str(character_id)),
                    creature_id=str(creature.id),
                    character_id=str(character_id),
                    damage=attack_damage + _pack_bonus(creature),
                    attack_type=attack_type,
                )
            )
        ]
        if creature.has_component(RoarComponent):
            roar = creature.get_component(RoarComponent)
            events.append(
                CreatureRoaredEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.ROOM,
                        actor_id=str(character_id),
                        room_id=_room_id(ctx.world, character_id),
                        target_ids=(str(creature.id),),
                        creature_id=str(creature.id),
                        fear=roar.fear,
                    )
                )
            )
        if creature.has_component(TrampleComponent):
            trample = creature.get_component(TrampleComponent)
            events.append(
                CreatureTrampledEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.ROOM,
                        actor_id=str(character_id),
                        room_id=_room_id(ctx.world, character_id),
                        target_ids=(str(creature.id), str(character_id)),
                        creature_id=str(creature.id),
                        character_id=str(character_id),
                        damage=trample.damage,
                    )
                )
            )
        if creature.has_component(ApexPredatorComponent):
            apex = creature.get_component(ApexPredatorComponent)
            events.append(
                ApexPredatorAppearedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.ROOM,
                        actor_id=str(character_id),
                        room_id=_room_id(ctx.world, character_id),
                        target_ids=(str(creature.id),),
                        creature_id=str(creature.id),
                        threat_level=apex.threat_level,
                    )
                )
            )
        if creature.has_component(KaijuComponent):
            kaiju = creature.get_component(KaijuComponent)
            events.append(
                KaijuArrivedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.ROOM,
                        actor_id=str(character_id),
                        room_id=_room_id(ctx.world, character_id),
                        target_ids=(str(creature.id),),
                        creature_id=str(creature.id),
                        threat_level=kaiju.threat_level,
                    )
                )
            )
        return ok(*events)


class TargetWeakPointHandler:
    command_type = "target-weak-point"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        creature, error = _reachable_creature(ctx, character_id, command.payload.get("creature_id"))
        if creature is None:
            return rejected(error if error else "creature is required")
        if not creature.has_component(WeakPointComponent):
            return rejected("creature has no exposed weak point")
        weak_point = creature.get_component(WeakPointComponent)
        if not weak_point.exposed:
            return rejected("weak point is not exposed")
        base_damage = max(0.0, float(command.payload.get("damage") or 1.0))
        damage = base_damage * max(1.0, weak_point.damage_multiplier)
        replace_component(creature, replace(weak_point, exposed=False))
        if creature.has_component(ApexPredatorComponent):
            apex = creature.get_component(ApexPredatorComponent)
            threat = max(0, apex.threat_level - int(damage))
            replace_component(creature, replace(apex, threat_level=threat))
        if creature.has_component(KaijuComponent):
            kaiju = creature.get_component(KaijuComponent)
            threat = max(0, kaiju.threat_level - int(damage))
            replace_component(creature, replace(kaiju, threat_level=threat))
        return ok(
            WeakPointHitEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature.id),),
                    creature_id=str(creature.id),
                    label=weak_point.label,
                    damage=damage,
                )
            )
        )


class DriveOffPredatorHandler:
    command_type = "drive-off-predator"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        creature, error = _reachable_creature(ctx, character_id, command.payload.get("creature_id"))
        if creature is None:
            return rejected(error if error else "creature is required")
        from_room_id = container_of(creature)
        if from_room_id is None or not ctx.world.has_entity(from_room_id):
            return rejected("creature is not in a room")
        from_room = ctx.entity(from_room_id)
        to_room_id = _first_exit_target(from_room)
        if to_room_id is not None and ctx.world.has_entity(to_room_id):
            _move_to_room(ctx.world, creature, to_room_id)
        fear = (
            creature.get_component(FearComponent)
            if creature.has_component(FearComponent)
            else FearComponent()
        )
        replace_component(creature, replace(fear, amount=fear.amount + 2.0))
        if creature.has_component(ApexPredatorComponent):
            apex = creature.get_component(ApexPredatorComponent)
            replace_component(creature, replace(apex, threat_level=0))
        return ok(
            PredatorDrivenOffEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(from_room_id),
                    target_ids=(str(creature.id),),
                    creature_id=str(creature.id),
                    from_room_id=str(from_room_id),
                    to_room_id=str(to_room_id) if to_room_id is not None else "",
                )
            )
        )


class CallForHelpHandler:
    command_type = "call-for-help"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        room, error = _signal_room(ctx, character_id, command.payload.get("room_id"))
        if room is None:
            return rejected(error if error else "room is required")
        strength = max(0.0, float(command.payload.get("strength") or 1.0))
        replace_component(
            room,
            ArmyResponseComponent(
                called=True,
                strength=strength,
                called_at_epoch=ctx.epoch,
            ),
        )
        return ok(
            ArmyCalledEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(room.id),
                    target_ids=(str(room.id),),
                    room_id_called=str(room.id),
                    strength=strength,
                )
            )
        )


class SignalArmyHandler:
    command_type = "signal-army"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        room, error = _signal_room(ctx, character_id, command.payload.get("room_id"))
        if room is None:
            return rejected(error if error else "room is required")
        strength = max(1.0, float(command.payload.get("strength") or 5.0))
        replace_component(
            room,
            ArmyResponseComponent(
                called=True,
                strength=strength,
                called_at_epoch=ctx.epoch,
            ),
        )
        events: list[DomainEvent] = [
            ArmyCalledEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(room.id),
                    target_ids=(str(room.id),),
                    room_id_called=str(room.id),
                    strength=strength,
                )
            )
        ]
        creature_id = parse_entity_id(command.payload.get("creature_id"))
        if creature_id is not None and ctx.world.has_entity(creature_id):
            creature = _reachable_entity(ctx.world, character_id, creature_id)
            if creature is not None and _is_creature(creature):
                if creature.has_component(KaijuComponent):
                    kaiju = creature.get_component(KaijuComponent)
                    replace_component(
                        creature,
                        replace(kaiju, threat_level=max(0, kaiju.threat_level - int(strength))),
                    )
                if creature.has_component(ApexPredatorComponent):
                    apex = creature.get_component(ApexPredatorComponent)
                    replace_component(
                        creature,
                        replace(apex, threat_level=max(0, apex.threat_level - int(strength))),
                    )
                events.append(
                    PredatorDrivenOffEvent(
                        **ctx.event_base(
                            visibility=EventVisibility.ROOM,
                            actor_id=str(character_id),
                            room_id=str(room.id),
                            target_ids=(str(creature.id),),
                            creature_id=str(creature.id),
                            from_room_id=str(room.id),
                            to_room_id="",
                        )
                    )
                )
        return ok(*events)


class RepairDamageHandler:
    command_type = "repair-damage"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        damage_id = parse_entity_id(command.payload.get("damage_id"))
        if damage_id is None:
            damage_id = container_of(ctx.entity(character_id))
        if damage_id is None or not ctx.world.has_entity(damage_id):
            return rejected("damage target does not exist")
        target = ctx.entity(damage_id)
        if target.id not in reachable_ids(ctx.world, ctx.entity(character_id)):
            return rejected("damage target is not reachable")
        if not target.has_component(SettlementDamageComponent):
            return rejected("target has no settlement damage")
        current = target.get_component(SettlementDamageComponent)
        amount = max(1, int(command.payload.get("amount") or 1))
        severity = max(0, current.severity - amount)
        updated = replace(current, severity=severity, repaired=severity == 0)
        replace_component(target, updated)
        return ok(
            SettlementDamageRepairedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target.id),),
                    settlement_id=str(target.id),
                    severity=updated.severity,
                    repaired=updated.repaired,
                )
            )
        )


SECONDS_PER_HOUR = 60 * 60
HUNGRY_THRESHOLD = 60.0
HUNGER_STRESS_PER_HOUR = 4.0
FEED_HUNGER_RELIEF = 50.0
FEED_COST = 1.0
CALM_STRESS_RELIEF = 30.0


class CreatureNeedConsequence:
    """Raise creature hunger over time and let hunger feed stress."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for creature in world.query().with_all([CreatureNeedComponent]).execute_entities():
            need = creature.get_component(CreatureNeedComponent)
            elapsed = max(0, epoch - need.last_updated_epoch)
            if elapsed <= 0:
                continue
            hours = elapsed / SECONDS_PER_HOUR
            hunger = min(100.0, need.hunger + need.hunger_per_hour * hours)
            stress = need.stress
            if hunger >= HUNGRY_THRESHOLD:
                stress = min(100.0, stress + HUNGER_STRESS_PER_HOUR * hours)
            updated = replace(need, hunger=hunger, stress=stress, last_updated_epoch=epoch)
            if updated == need:
                continue
            replace_component(creature, updated)
            became_hungry = need.hunger < HUNGRY_THRESHOLD <= hunger
            if became_hungry:
                events.append(
                    CreatureNeedsChangedEvent(
                        **_event_base(
                            epoch,
                            visibility=EventVisibility.ROOM,
                            room_id=_creature_room_id(world, creature),
                            target_ids=(str(creature.id),),
                            creature_id=str(creature.id),
                            hunger=hunger,
                            stress=stress,
                        )
                    )
                )
        return events


def _creature_room_id(world: World, creature: Entity) -> str | None:
    room = container_of(creature)
    return str(room) if room is not None and world.has_entity(room) else None


class FeedCreatureHandler:
    command_type = "feed-creature"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        creature_id = parse_entity_id(command.payload.get("creature_id"))
        store_id = parse_entity_id(command.payload.get("feed_store_id"))
        if character_id is None or creature_id is None or store_id is None:
            return rejected("invalid character, creature, or feed store id")
        if not ctx.world.has_entity(creature_id) or not ctx.world.has_entity(store_id):
            return rejected("creature or feed store does not exist")
        creature = _reachable_entity(ctx.world, character_id, creature_id)
        store = _reachable_entity(ctx.world, character_id, store_id)
        if creature is None or store is None:
            return rejected("creature or feed store is not reachable")
        if not creature.has_component(CreatureNeedComponent):
            return rejected("target is not a creature with needs")
        if not store.has_component(FeedStoreComponent):
            return rejected("target is not a feed store")
        feed_store = store.get_component(FeedStoreComponent)
        if feed_store.feed < FEED_COST:
            return rejected("feed store is empty")

        replace_component(store, replace(feed_store, feed=feed_store.feed - FEED_COST))
        need = creature.get_component(CreatureNeedComponent)
        hunger = max(0.0, need.hunger - FEED_HUNGER_RELIEF)
        replace_component(creature, replace(need, hunger=hunger, last_updated_epoch=ctx.epoch))
        return ok(
            CreatureFedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature_id), str(store_id)),
                    creature_id=str(creature_id),
                    hunger=hunger,
                )
            )
        )


class CalmCreatureHandler:
    command_type = "calm-creature"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        creature_id = parse_entity_id(command.payload.get("creature_id"))
        if character_id is None or creature_id is None:
            return rejected("invalid character or creature id")
        if not ctx.world.has_entity(creature_id):
            return rejected("creature does not exist")
        creature = _reachable_entity(ctx.world, character_id, creature_id)
        if creature is None:
            return rejected("creature is not reachable")
        if not creature.has_component(CreatureNeedComponent):
            return rejected("target is not a creature with needs")
        need = creature.get_component(CreatureNeedComponent)
        stress = max(0.0, need.stress - CALM_STRESS_RELIEF)
        replace_component(creature, replace(need, stress=stress, last_updated_epoch=ctx.epoch))
        return ok(
            CreatureCalmedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature_id),),
                    creature_id=str(creature_id),
                    stress=stress,
                )
            )
        )


class ObserveCreatureHandler:
    command_type = "observe-creature"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        creature_id = parse_entity_id(command.payload.get("creature_id"))
        if character_id is None or creature_id is None:
            return rejected("invalid character or creature id")
        if not ctx.world.has_entity(creature_id):
            return rejected("creature does not exist")
        creature = _reachable_entity(ctx.world, character_id, creature_id)
        if creature is None:
            return rejected("creature is not reachable")
        if not creature.has_component(CreatureNeedComponent):
            return rejected("target is not a creature with needs")
        need = creature.get_component(CreatureNeedComponent)
        return ok(
            CreatureObservedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature_id),),
                    creature_id=str(creature_id),
                    hunger=need.hunger,
                    stress=need.stress,
                )
            )
        )


def _consume_inventory_resource(
    character: Entity, world: World, resource_type: str, quantity: int
) -> bool:
    for edge, item_id in character.get_relationships(Contains):
        if edge.mode != ContainmentMode.INVENTORY or not world.has_entity(item_id):
            continue
        item = world.get_entity(item_id)
        if not item.has_component(ResourceStackComponent):
            continue
        stack = item.get_component(ResourceStackComponent)
        if stack.resource_type != resource_type or stack.quantity < quantity:
            continue
        replace_component(item, replace(stack, quantity=stack.quantity - quantity))
        return True
    return False


class StockFeedHandler:
    command_type = "stock-feed"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        store_id = parse_entity_id(command.payload.get("feed_store_id"))
        if store_id is None:
            store_id = container_of(ctx.entity(character_id))
        if store_id is None or not ctx.world.has_entity(store_id):
            return rejected("feed store does not exist")
        store = ctx.entity(store_id)
        if store.id not in reachable_ids(ctx.world, ctx.entity(character_id)):
            return rejected("feed store is not reachable")
        feed_store = (
            store.get_component(FeedStoreComponent)
            if store.has_component(FeedStoreComponent)
            else FeedStoreComponent()
        )
        amount = max(0.0, float(command.payload.get("amount") or 1.0))
        resource_type = str(command.payload.get("resource_type") or "").strip()
        resource_spent = int(amount)
        if resource_type and not _consume_inventory_resource(
            ctx.entity(character_id), ctx.world, resource_type, resource_spent
        ):
            return rejected("not enough feed resource")
        updated = replace(
            feed_store,
            feed=min(feed_store.capacity, feed_store.feed + amount),
        )
        replace_component(store, updated)
        return ok(
            FeedStockedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(store.id),),
                    feed_store_id=str(store.id),
                    amount=amount,
                    feed=updated.feed,
                    resource_type=resource_type,
                    resource_spent=resource_spent if resource_type else 0,
                )
            )
        )


class CollectEggHandler:
    command_type = "collect-egg"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        egg_id = parse_entity_id(command.payload.get("egg_id"))
        if character_id is None or egg_id is None:
            return rejected("invalid character or egg id")
        if not ctx.world.has_entity(egg_id):
            return rejected("egg does not exist")
        egg_entity = _reachable_entity(ctx.world, character_id, egg_id)
        if egg_entity is None:
            return rejected("egg is not reachable")
        if not egg_entity.has_component(EggComponent):
            return rejected("target is not an egg")
        egg = egg_entity.get_component(EggComponent)
        character = ctx.entity(character_id)
        _remove_from_container(ctx.world, egg_id)
        character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), egg_id)
        replace_component(
            egg_entity,
            CreatureProductComponent(
                product_type="egg",
                quantity=1.0,
                source_creature_id=egg.parent_ids[0] if egg.parent_ids else "",
                collected_at_epoch=ctx.epoch,
            ),
        )
        return ok(
            CreatureProductCollectedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(egg_id),),
                    creature_id=egg.parent_ids[0] if egg.parent_ids else "",
                    product_id=str(egg_id),
                    product_type="egg",
                    quantity=1.0,
                )
            )
        )


class HarvestProductHandler:
    command_type = "harvest-product"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        creature, error = _reachable_creature(ctx, character_id, command.payload.get("creature_id"))
        if creature is None:
            return rejected(error if error else "creature is required")
        product_type = str(command.payload.get("product_type") or "").strip().lower()
        quantity = max(1.0, float(command.payload.get("quantity") or 1.0))
        product_quantity = quantity

        if not product_type:
            if creature.has_component(CreatureMilkComponent):
                product_type = "milk"
            elif creature.has_component(ToxinComponent):
                product_type = "toxin"
            elif creature.has_component(CreatureProductComponent):
                product_type = creature.get_component(CreatureProductComponent).product_type
            elif creature.has_component(HideComponent):
                product_type = "hide"
            elif creature.has_component(BoneComponent):
                product_type = "bone"
            else:
                return rejected("creature has no harvestable product")

        if product_type == "milk":
            if not creature.has_component(CreatureMilkComponent):
                return rejected("creature has no milk")
            milk = creature.get_component(CreatureMilkComponent)
            if milk.volume <= 0.0:
                return rejected("creature has no milk available")
            product_quantity = min(quantity, milk.volume)
            replace_component(creature, replace(milk, volume=milk.volume - product_quantity))
        elif product_type == "toxin":
            if not creature.has_component(ToxinComponent):
                return rejected("creature has no toxin")
            toxin = creature.get_component(ToxinComponent)
            if toxin.quantity <= 0.0:
                return rejected("creature has no toxin available")
            product_quantity = min(quantity, toxin.quantity)
            replace_component(creature, replace(toxin, quantity=toxin.quantity - product_quantity))
        elif product_type == "hide":
            if not creature.has_component(HideComponent):
                return rejected("creature has no hide")
            hide = creature.get_component(HideComponent)
            if hide.harvested:
                return rejected("hide has already been harvested")
            product_quantity = hide.quality
            replace_component(creature, replace(hide, harvested=True))
        elif product_type == "bone":
            if not creature.has_component(BoneComponent):
                return rejected("creature has no bone")
            bone = creature.get_component(BoneComponent)
            if bone.harvested:
                return rejected("bone has already been harvested")
            product_quantity = bone.quality
            replace_component(creature, replace(bone, harvested=True))
        elif creature.has_component(CreatureProductComponent):
            product = creature.get_component(CreatureProductComponent)
            if product.product_type != product_type:
                return rejected("creature has no matching product")
            if product.quantity <= 0.0:
                return rejected("creature product is depleted")
            product_quantity = min(quantity, product.quantity)
            remaining = product.quantity - product_quantity if product.renewable else 0.0
            replace_component(creature, replace(product, quantity=remaining))
        else:
            return rejected("creature has no matching product")

        character = ctx.entity(character_id)
        product = _spawn_creature_product(
            ctx.world,
            character,
            product_type=product_type,
            quantity=product_quantity,
            source_creature_id=str(creature.id),
            epoch=ctx.epoch,
        )
        return ok(
            CreatureProductCollectedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature.id), str(product.id)),
                    creature_id=str(creature.id),
                    product_id=str(product.id),
                    product_type=product_type,
                    quantity=product_quantity,
                )
            )
        )


class AssignRanchWorkHandler:
    command_type = "assign-ranch-work"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        creature, error = _reachable_creature(ctx, character_id, command.payload.get("creature_id"))
        if creature is None:
            return rejected(error if error else "creature is required")
        work_type = str(command.payload.get("work_type") or "").strip()
        if not work_type:
            return rejected("work type is required")
        target_id = str(command.payload.get("target_id") or "")
        replace_component(
            creature,
            RanchLaborComponent(
                work_type=work_type,
                target_id=target_id,
                assigned_by_id=str(character_id),
                active=True,
            ),
        )
        return ok(
            RanchWorkAssignedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature.id),),
                    creature_id=str(creature.id),
                    work_type=work_type,
                    target_id=target_id,
                )
            )
        )


class AssignGuardHandler:
    command_type = "assign-guard"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        creature, error = _reachable_creature(ctx, character_id, command.payload.get("creature_id"))
        if creature is None:
            return rejected(error if error else "creature is required")
        location_id = parse_entity_id(command.payload.get("location_id"))
        if location_id is None:
            location_id = container_of(ctx.entity(character_id))
        if location_id is None or not ctx.world.has_entity(location_id):
            return rejected("guard location does not exist")
        replace_component(
            creature,
            GuardAnimalComponent(
                location_id=str(location_id),
                assigned_by_id=str(character_id),
                active=True,
            ),
        )
        replace_component(
            creature,
            GuardBehaviorComponent(location_id=str(location_id), active=True),
        )
        return ok(
            GuardAssignedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(creature.id), str(location_id)),
                    creature_id=str(creature.id),
                    location_id=str(location_id),
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
    ctx = ComponentPromptContext.for_entity(world, character)
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        entity_ctx = ComponentPromptContext.for_entity(
            world, entity, perspective=ctx.perspective, room=ctx.room, target=character
        )
        for component_type in (
            FossilFragmentComponent,
            FossilSurveyComponent,
            AncientSampleComponent,
            EggComponent,
            LabIncubationComponent,
            EggInspectionComponent,
            BroodingComponent,
            TrackComponent,
            TerritoryComponent,
            HerdComponent,
            NestComponent,
            CreatureNeedComponent,
            ImprintComponent,
            JuvenileCareComponent,
            WaterCreatureComponent,
            WaterStudyComponent,
            TamingComponent,
            CompanionComponent,
            TrainingComponent,
            CommandComponent,
            BaitComponent,
            CreatureAttackComponent,
            WeakPointComponent,
            ApexPredatorComponent,
            KaijuComponent,
            SettlementDamageComponent,
            ArmyResponseComponent,
            FeedStoreComponent,
            CreatureProductComponent,
            CreatureMilkComponent,
            ToxinComponent,
            HideComponent,
            BoneComponent,
            RanchLaborComponent,
            GuardAnimalComponent,
            EnclosureComponent,
            FenceComponent,
            GateComponent,
            EscapeRiskComponent,
            ContainmentPanicComponent,
        ):
            if entity.has_component(component_type):
                lines.extend(entity.get_component(component_type).prompt_fragments(entity_ctx))
    return sorted(lines)


def install_dinosim(actor) -> None:
    ensure_dinosim_policy(actor)
    actor.register_consequence(IncubationConsequence())
    actor.register_consequence(EscapeRiskConsequence())
    actor.register_consequence(CreatureNeedConsequence())
    DinoIncidentEnrichment(actor.world).subscribe(actor.bus)


__all__ = [
    "AncientSampleComponent",
    "AncientSampleExtractedEvent",
    "ApproachCreatureHandler",
    "ApexPredatorAppearedEvent",
    "ApexPredatorComponent",
    "ArmorPlateComponent",
    "ArmyCalledEvent",
    "ArmyResponseComponent",
    "AssignGuardHandler",
    "AssignRanchWorkHandler",
    "BaitComponent",
    "BaitSetEvent",
    "BoneComponent",
    "BroodEggHandler",
    "BroodingComponent",
    "BroodingStartedEvent",
    "BreachComponent",
    "BuildEnclosureHandler",
    "CalmCreatureHandler",
    "CallForHelpHandler",
    "CareForJuvenileHandler",
    "ChargeComponent",
    "CloneCandidateComponent",
    "ClonePreparedEvent",
    "CleanFossilHandler",
    "CollectEggHandler",
    "CommandComponent",
    "CommandCompanionHandler",
    "CommandTrainedEvent",
    "CompanionCommandedEvent",
    "CompanionComponent",
    "ContainmentProtocolComponent",
    "ContainmentTriggeredEvent",
    "ContainmentPanicComponent",
    "ContainmentPanicStartedEvent",
    "CreatureAttackComponent",
    "CreatureAttackedEvent",
    "CreatureCalmedEvent",
    "CreatureChargedEvent",
    "CreatureFedEvent",
    "CreatureMilkComponent",
    "CreatureNeedComponent",
    "CreatureNeedConsequence",
    "CreatureNeedsChangedEvent",
    "CreatureObservedEvent",
    "CreatureProductCollectedEvent",
    "CreatureProductComponent",
    "CreatureEscapedEvent",
    "CreatureMountedEvent",
    "CreatureRecapturedEvent",
    "CreatureRecalledEvent",
    "CreatureRoaredEvent",
    "CreatureTamedEvent",
    "CreatureTrackedEvent",
    "CreatureTranquilizedEvent",
    "CreatureTrampledEvent",
    "CreatureImprintedEvent",
    "DinosaurComponent",
    "DinoIncidentEnrichment",
    "DinosimPolicyComponent",
    "DodgeCreatureHandler",
    "DriveOffPredatorHandler",
    "EggComponent",
    "EggFertilizedEvent",
    "EggHatchedEvent",
    "EggIncubatedEvent",
    "EggInspectedEvent",
    "EggInspectionComponent",
    "EggLaidEvent",
    "EnclosureBuiltEvent",
    "EnclosureComponent",
    "EscapeRiskComponent",
    "EscapeRiskConsequence",
    "EvacuateRoomHandler",
    "ExcavateFossilHandler",
    "ExtractAncientSampleHandler",
    "FeedCreatureHandler",
    "FeedStockedEvent",
    "FeedStoreComponent",
    "FeedingPenComponent",
    "FertilityComponent",
    "FertilizeEggHandler",
    "FearComponent",
    "FenceComponent",
    "FenceRepairedEvent",
    "FightCreatureHandler",
    "FossilFragmentComponent",
    "FossilCleanedEvent",
    "FossilExcavatedEvent",
    "FossilIdentifiedEvent",
    "FossilStabilizedEvent",
    "FossilSurveyComponent",
    "FossilSurveyedEvent",
    "GateComponent",
    "GateReinforcedEvent",
    "GrappleComponent",
    "GuardAnimalComponent",
    "GuardAssignedEvent",
    "GuardBehaviorComponent",
    "HerdComponent",
    "HerdTrackedEvent",
    "HatchEggHandler",
    "HatchlingComponent",
    "HiddenFromCreatureEvent",
    "HideFromCreatureHandler",
    "HarvestProductHandler",
    "HideComponent",
    "HuntBehaviorComponent",
    "IdentifyFossilHandler",
    "ImprintComponent",
    "ImprintCreatureHandler",
    "IncubateEggHandler",
    "IncubationComponent",
    "IncubationConsequence",
    "IncubationTemperatureSetEvent",
    "InspectEggHandler",
    "JuvenileCareComponent",
    "JuvenileCareGivenEvent",
    "KaijuComponent",
    "KaijuArrivedEvent",
    "KaijuSpawnSpec",
    "LayEggHandler",
    "LabIncubateEggHandler",
    "LabIncubationComponent",
    "LabIncubationStartedEvent",
    "LockPenHandler",
    "MountComponent",
    "MountCreatureHandler",
    "MarkTerritoryHandler",
    "NestComponent",
    "NestPreparedEvent",
    "ObserveCreatureHandler",
    "OpenPenHandler",
    "PackHuntComponent",
    "PenLockedEvent",
    "PenOpenedEvent",
    "PredatorDrivenOffEvent",
    "PrepareCloneHandler",
    "PrepareNestHandler",
    "QuarantinePenComponent",
    "RecallComponent",
    "RecallCreatureHandler",
    "RecaptureCreatureHandler",
    "RanchLaborComponent",
    "RanchWorkAssignedEvent",
    "ReinforceGateHandler",
    "ReinforcementComponent",
    "RepairDamageHandler",
    "RepairFenceHandler",
    "ReptileProcreationComponent",
    "RoarComponent",
    "RoomEvacuatedEvent",
    "ScentComponent",
    "SettlementDamageRepairedEvent",
    "SettlementDamageComponent",
    "SettlementDamagedEvent",
    "SetBaitHandler",
    "SetIncubationTemperatureHandler",
    "SignalArmyHandler",
    "SpeciesComponent",
    "SpeciesIdentificationComponent",
    "StampedeComponent",
    "StampedeStartedEvent",
    "TameCreatureHandler",
    "TamingComponent",
    "TamingProgressedEvent",
    "TargetWeakPointHandler",
    "TerritoryComponent",
    "TerritoryMarkedEvent",
    "TrackComponent",
    "TrackCreatureHandler",
    "TrackHerdHandler",
    "TrainCommandHandler",
    "TrainingComponent",
    "TrampleComponent",
    "TranquilizeCreatureHandler",
    "TranquilizerComponent",
    "TriggerContainmentHandler",
    "TriggerContainmentPanicHandler",
    "TrustComponent",
    "ToxinComponent",
    "WeakPointComponent",
    "StabilizeFossilHandler",
    "StudyWaterCreatureHandler",
    "SurveyFossilHandler",
    "WaterCreatureComponent",
    "WaterCreatureStudiedEvent",
    "WaterStudyComponent",
    "dinosim_fragments",
    "ensure_dinosim_policy",
    "generate_kaiju_spawn_specs",
    "install_dinosim",
    "kaiju_difficulty_for_threat",
    "selected_kaiju_rooms",
]
