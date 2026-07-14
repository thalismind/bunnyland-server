"""Void-sim sci-fi frontier mechanics (catalogue section 8).

FTL-inspired: ships and stations made of habitat modules, life support and pressure that
can fail, power that must be rerouted, ship systems that take damage and get repaired,
and docking between craft. This module owns section 8.1 (ships, stations, and habitats);
later subsections (travel, crew, hazards, contracts) build on the same components.

Following the rest of bunnyland, systems read broadly but write narrowly: the life
support consequence only touches oxygen and emits a failure event; it never reaches into
mood, health, or other packages.
"""

from __future__ import annotations

from dataclasses import replace

from pydantic.dataclasses import dataclass
from relics import Component, Edge, Entity, EntityId, World

from bunnyland.foundation.mutation.mechanics import (
    ChaosMutationPressureComponent,
    CyberneticMutationPressureComponent,
    RadiationMutationPressureComponent,
    RadiationShieldComponent,
)
from bunnyland.simpacks.barbariansim.mechanics import CorruptionComponent, CorruptionGainedEvent
from bunnyland.simpacks.colonysim.mechanics import ResourceStackComponent, TechUnlockComponent

from ...core.commands import SubmittedCommand
from ...core.components import (
    CharacterComponent,
    DeadComponent,
    IdentityComponent,
    SuspendedComponent,
)
from ...core.ecs import (
    container_of,
    contents,
    parse_entity_id,
    reachable_ids,
    replace_component,
)
from ...core.ecs import (
    entity_name as _name,
)
from ...core.ecs import (
    reachable_component as _reachable_component,
)
from ...core.ecs import (
    room_id_for as _room_id,
)
from ...core.edges import ContainmentMode, Contains
from ...core.events import DomainEvent, EventVisibility
from ...core.events import event_base as _void_event
from ...core.handlers import HandlerContext, HandlerResult, planned, rejected
from ...core.mutations import (
    AddEdge,
    AddEntity,
    EntityReference,
    MutationError,
    MutationOperation,
    MutationPlan,
    RemoveComponent,
    RemoveEdge,
    SetComponent,
    register_world_invariant,
    replace_single_edge_operations,
)
from ...prompts import ComponentPromptContext


def _payload_entity_id(command: SubmittedCommand, *keys: str):
    for key in keys:
        if key in command.payload:
            return parse_entity_id(command.payload.get(key))
    return None


SECONDS_PER_HOUR = 60 * 60
SECONDS_PER_DAY = 24 * SECONDS_PER_HOUR


def _single_edge_target(entity: Entity, edge_type: type[Edge]) -> EntityId | None:
    relationships = entity.get_relationships(edge_type)
    return relationships[0][1] if relationships else None


@dataclass(frozen=True)
class ShipComponent(Component):
    name: str
    hull_integrity: float = 100.0


@dataclass(frozen=True)
class StationComponent(Component):
    name: str


@dataclass(frozen=True)
class HabitatModuleComponent(Component):
    module_type: str
    ship_id: str | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"You are in the {self.module_type} module ({_name(ctx.entity)}).",)


@dataclass(frozen=True)
class AirlockComponent(Component):
    state: str = "sealed"  # sealed | open | cycled
    module_id: str | None = None
    exposes_vacuum: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Airlock {_name(ctx.entity)}: {self.state}.",)


@dataclass(frozen=True)
class BulkheadComponent(Component):
    sealed: bool = False


@dataclass(frozen=True)
class PressurizedComponent(Component):
    pressure: float = 1.0  # atmospheres; 0.0 == vacuum

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        state = "vacuum" if self.pressure <= 0.0 else f"{self.pressure:.1f} atm"
        return (f"Module pressure: {state}.",)


@dataclass(frozen=True)
class LifeSupportComponent(Component):
    online: bool = True
    oxygen_per_hour: float = 5.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"Life support: {'online' if self.online else 'OFFLINE'}.",)


@dataclass(frozen=True)
class ShipSystemComponent(Component):
    system_type: str
    integrity: float = 100.0
    online: bool = True

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        status = "online" if self.online else "offline"
        return (f"Ship system {self.system_type}: {self.integrity:.0f}% ({status}).",)


@dataclass(frozen=True)
class PowerGridComponent(Component):
    capacity: float = 100.0
    available: float = 100.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"Power grid: {self.available:.0f}/{self.capacity:.0f} available.",)


@dataclass(frozen=True)
class OxygenComponent(Component):
    level: float = 100.0
    maximum: float = 100.0
    failed: bool = False
    last_updated_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"Module oxygen: {self.level:.0f}/{self.maximum:.0f}.",)


@dataclass(frozen=True)
class ChaosInfluenceComponent(Component):
    """Warp/chaos pressure source.

    Void-sim treats barbarian-sim corruption as the character's chaos state. This component
    is only the environmental source that applies it.
    """

    source_type: str = "warp breach"
    corruption_per_hour: float = 1.0
    system_damage_per_hour: float = 0.0
    mutation_pressure_per_corruption: float = 1.0
    last_updated_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if ctx.room is not None and ctx.entity.id == ctx.room.id:
            return (f"Chaos influence: {self.source_type} ({self.corruption_per_hour:g}/hour).",)
        return (
            f"Chaos source {_name(ctx.entity)}: {self.source_type} "
            f"({self.corruption_per_hour:g}/hour).",
        )


@dataclass(frozen=True)
class ChaosWardComponent(Component):
    """Protection against nearby chaos influence."""

    protection_per_hour: float = 1.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Chaos ward {_name(ctx.entity)}: {self.protection_per_hour:g}/hour.",)


# --- 8.4 Technology, fabrication, and upgrades ----------------------------------------


@dataclass(frozen=True)
class FabricatorComponent(Component):
    """A module that can fabricate parts from blueprints."""

    online: bool = True

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Fabricator {_name(ctx.entity)}: {'online' if self.online else 'offline'}.",)


@dataclass(frozen=True)
class BlueprintComponent(Component):
    """A fabricable ship-system upgrade, gated on a colony-sim tech unlock.

    ``required_tech`` matches a ``TechUnlockComponent.tech_id`` produced by colony-sim
    research; an empty value means the blueprint needs no research.
    """

    name: str
    system_type: str
    required_tech: str = ""
    integrity_bonus: float = 25.0
    resource_inputs: tuple[tuple[str, int], ...] = ()

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        world = ctx._world
        ready = _tech_unlocked(world, self.required_tech) if world is not None else False
        gate = "ready" if ready else f"needs tech {self.required_tech}"
        return (f"Blueprint {self.name} ({self.system_type}): {gate}.",)


@dataclass(frozen=True)
class ShipUpgradeComponent(Component):
    """A fabricated part that upgrades a matching ship system when installed."""

    system_type: str
    integrity_bonus: float = 25.0
    installed: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        if self.installed:
            return ()
        return (f"Upgrade part ready for {self.system_type} system.",)


# --- 8.7 Contracts, salvage, cargo, and frontier economy ------------------------------


@dataclass(frozen=True)
class ContractComponent(Component):
    contract_type: str = "cargo"
    destination_id: str = ""
    reward: int = 0
    status: str = "offered"  # offered | active | completed
    accepted_by: str | None = None
    cargo_id: str | None = None
    salvage_claim_id: str | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if self.status == "offered":
            return (
                f"Available {self.contract_type} contract: {_name(ctx.entity)} "
                f"for {self.reward} credits.",
            )
        if (
            ctx.target is not None
            and self.accepted_by == str(ctx.target.id)
            and ctx.can_view_private_state
        ):
            return (f"{self.contract_type.title()} contract {_name(ctx.entity)}: {self.status}.",)
        return ()


@dataclass(frozen=True)
class CargoComponent(Component):
    cargo_type: str = "freight"
    destination_id: str = ""
    loaded_on: str | None = None
    delivered: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if self.delivered:
            return (f"Cargo delivered: {_name(ctx.entity)}.",)
        if self.loaded_on is not None:
            return (f"Cargo loaded on {self.loaded_on}: {_name(ctx.entity)}.",)
        return (f"Cargo waiting: {_name(ctx.entity)} ({self.cargo_type}).",)


@dataclass(frozen=True)
class SalvageClaimComponent(Component):
    site_id: str
    rights_contract_id: str | None = None
    resource_outputs: tuple[tuple[str, int], ...] = ()
    claimed_by: str | None = None
    claimed: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if self.claimed:
            return ()
        return (f"Salvage claim available: {_name(ctx.entity)}.",)


# --- 8.5 Alien contact, diplomacy, and xenobiology ------------------------------------


@dataclass(frozen=True)
class AlienSpeciesComponent(Component):
    name: str
    disposition: str = "unknown"

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"Alien species contact: {self.name} ({self.disposition}).",)


@dataclass(frozen=True)
class FirstContactComponent(Component):
    species_id: str
    contacted_by: tuple[str, ...] = ()
    status: str = "uncontacted"

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if (
            ctx.target is not None
            and str(ctx.target.id) in self.contacted_by
            and ctx.can_view_private_state
        ):
            return ()
        return (f"First contact opportunity: {_name(ctx.entity)}.",)


@dataclass(frozen=True)
class TranslationMatrixComponent(Component):
    species_id: str
    progress: float = 0.0
    complete: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        status = "complete" if self.complete else f"{self.progress:.0f}%"
        return (f"Translation matrix {_name(ctx.entity)}: {status}.",)


@dataclass(frozen=True)
class QuarantineComponent(Component):
    reason: str = "unknown organism"
    active: bool = True
    started_by: str | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not self.active:
            return ()
        return (f"Quarantined sample {_name(ctx.entity)}: {self.reason}.",)


@dataclass(frozen=True)
class DiplomaticMissionComponent(Component):
    species_id: str
    standing: int = 0
    last_negotiated_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Diplomatic mission {_name(ctx.entity)}: standing {self.standing}.",)


@dataclass(frozen=True)
class AlienArtifactComponent(Component):
    species_id: str = ""
    studied_by: tuple[str, ...] = ()
    insight: str = ""

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if (
            ctx.target is not None
            and str(ctx.target.id) in self.studied_by
            and ctx.can_view_private_state
        ):
            return ()
        return (f"Alien artifact ready for study: {_name(ctx.entity)}.",)


@dataclass(frozen=True)
class XenobiologySampleComponent(Component):
    species_id: str = ""
    contamination: float = 0.0
    studied_by: tuple[str, ...] = ()

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Xenobiology sample {_name(ctx.entity)}: contamination {self.contamination:g}.",)


@dataclass(frozen=True)
class TradeProtocolComponent(Component):
    species_id: str = ""
    terms: str = "cautious exchange"
    accepted: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "accepted" if self.accepted else "pending"
        return (f"Trade protocol {_name(ctx.entity)}: {state}, {self.terms}.",)


@dataclass(frozen=True)
class DroneComponent(Component):
    drone_type: str = "utility"
    assigned_task: str = ""
    active: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "active" if self.active else "idle"
        return (f"Drone {_name(ctx.entity)}: {state} {self.assigned_task}.",)


@dataclass(frozen=True)
class ShipAIComponent(Component):
    name: str = "ship AI"
    trust: int = 0
    hacked: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        state = "hacked" if self.hacked else "locked"
        return (f"Ship AI {self.name}: trust {self.trust}, {state}.",)


@dataclass(frozen=True)
class DataSalvageComponent(Component):
    data_type: str = "logs"
    encrypted: bool = True
    recovered_by: str | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "encrypted" if self.encrypted else "recovered"
        return (f"Data salvage {_name(ctx.entity)}: {self.data_type}, {state}.",)


@dataclass(frozen=True)
class AwayTeamComponent(Component):
    mission: str = "survey"
    deployed: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "deployed" if self.deployed else "standing by"
        return (f"Away team {_name(ctx.entity)}: {self.mission}, {state}.",)


@dataclass(frozen=True)
class MemberOfAwayTeam(Edge):
    pass


@dataclass(frozen=True)
class MoraleComponent(Component):
    value: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        return (f"Crew morale: {self.value}.",)


@dataclass(frozen=True)
class MutinyComponent(Component):
    active: bool = False
    ringleader_id: str | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person or not self.active:
            return ()
        return ("Mutiny is active.",)


@dataclass(frozen=True)
class EmergencyComponent(Component):
    emergency_type: str = "decompression"
    resolved: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "resolved" if self.resolved else "active"
        return (f"Emergency {_name(ctx.entity)}: {self.emergency_type}, {state}.",)


@dataclass(frozen=True)
class ReactorComponent(Component):
    stability: float = 100.0
    online: bool = True

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Reactor {_name(ctx.entity)}: stability {self.stability:g}.",)


@dataclass(frozen=True)
class GravityComponent(Component):
    enabled: bool = True
    strength: float = 1.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "enabled" if self.enabled else "disabled"
        return (f"Gravity {_name(ctx.entity)}: {state} {self.strength:g}g.",)


@dataclass(frozen=True)
class BoardingThreatComponent(Component):
    threat_level: int = 1
    repelled: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "repelled" if self.repelled else "boarding"
        return (f"Boarding threat {_name(ctx.entity)}: level {self.threat_level}, {state}.",)


@dataclass(frozen=True)
class PassengerComponent(Component):
    destination_id: str = ""
    delivered: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "delivered" if self.delivered else "aboard"
        return (f"Passenger {_name(ctx.entity)}: {state}.",)


@dataclass(frozen=True)
class SurveySiteComponent(Component):
    resource: str = ""
    surveyed_by: tuple[str, ...] = ()

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Survey site {_name(ctx.entity)}: {self.resource}.",)


@dataclass(frozen=True)
class MiningSiteComponent(Component):
    resource_type: str = "ore"
    remaining: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Mining site {_name(ctx.entity)}: {self.remaining} {self.resource_type}.",)


@dataclass(frozen=True)
class CustomsHoldComponent(Component):
    inspected: bool = False
    contraband_found: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "inspected" if self.inspected else "pending"
        return (f"Customs hold {_name(ctx.entity)}: {state}.",)


@dataclass(frozen=True)
class SmugglingCompartmentComponent(Component):
    hidden: bool = True
    discovered: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "discovered" if self.discovered else "hidden"
        return (f"Smuggling compartment {_name(ctx.entity)}: {state}.",)


@dataclass(frozen=True)
class InsurancePolicyComponent(Component):
    insured_entity_id: str = ""
    premium: int = 0
    claimed: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        state = "claimed" if self.claimed else "active"
        return (f"Insurance policy {_name(ctx.entity)}: {state}.",)


@dataclass(frozen=True)
class MortgageComponent(Component):
    principal: int = 0
    balance: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Mortgage {_name(ctx.entity)}: balance {self.balance}.",)


# --- 8.2 Space travel, orbits, and navigation -----------------------------------------


@dataclass(frozen=True)
class StarSystemComponent(Component):
    name: str

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"Current system: {self.name}.",)


@dataclass(frozen=True)
class OrbitalBodyComponent(Component):
    body_type: str  # planet | moon | asteroid-belt | station
    landable: bool = True

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"Orbital body nearby: {_name(ctx.entity)} ({self.body_type}).",)


@dataclass(frozen=True)
class OrbitComponent(Component):
    altitude: str = "orbit"  # orbit | surface

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        world = ctx._world
        body_id = _single_edge_target(ctx.entity, OrbitsBody)
        if world is None or body_id is None:
            return ()
        where = "landed on" if self.altitude == "surface" else "in orbit of"
        return (f"{_name(ctx.entity)} is {where} {_name(world.get_entity(body_id))}.",)


@dataclass(frozen=True)
class NavigationRouteComponent(Component):
    destination_key: str = ""
    fuel_cost: float = 0.0
    hazard: str = "none"
    jump_seconds: float = 0.0
    status: str = "plotted"  # plotted | jumping
    arrive_at_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"{_name(ctx.entity)} course: {self.status} (hazard: {self.hazard}).",)


@dataclass(frozen=True)
class OrbitsBody(Edge):
    pass


@dataclass(frozen=True)
class NavigatesTo(Edge):
    pass


@dataclass(frozen=True)
class JumpDriveComponent(Component):
    charged: bool = True
    jump_seconds: float = 3600.0


@dataclass(frozen=True)
class FuelComponent(Component):
    level: float = 100.0
    maximum: float = 100.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"{_name(ctx.entity)} fuel: {self.level:.0f}/{self.maximum:.0f}.",)


@dataclass(frozen=True)
class SensorComponent(Component):
    scan_range: float = 1.0


@dataclass(frozen=True)
class DistressSignalComponent(Component):
    text: str
    source_site_id: str | None = None
    detected: bool = False
    answered: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        if not self.detected or self.answered:
            return ()
        return (f"Distress signal: {self.text}",)


@dataclass(frozen=True)
class AstrogationComponent(Component):
    skill: int = 0


@dataclass(frozen=True)
class DockedTo(Edge):
    port: str = "main"


@dataclass(frozen=True)
class JumpRoute(Edge):
    fuel_cost: float = 10.0
    hazard: str = "none"
    jump_seconds: float = 3600.0
    label: str = ""


class AirlockCycledEvent(DomainEvent):
    airlock_id: str
    state: str


class PressureChangedEvent(DomainEvent):
    module_id: str
    pressure: float


class LifeSupportFailedEvent(DomainEvent):
    module_id: str


class PowerReroutedEvent(DomainEvent):
    system_id: str
    amount: float


class ShipSystemDamagedEvent(DomainEvent):
    system_id: str
    system_type: str
    integrity: float


class ShipSystemRepairedEvent(DomainEvent):
    system_id: str
    system_type: str


class ShipSystemInspectedEvent(DomainEvent):
    system_id: str
    system_type: str
    integrity: float
    online: bool


class ItemFabricatedEvent(DomainEvent):
    fabricator_id: str
    blueprint_id: str
    item_id: str
    name: str
    system_type: str
    resource_inputs: tuple[tuple[str, int], ...] = ()


class UpgradeInstalledEvent(DomainEvent):
    upgrade_id: str
    system_id: str
    system_type: str
    integrity: float


class ContractAcceptedEvent(DomainEvent):
    contract_id: str
    contract_type: str


class ContractCompletedEvent(DomainEvent):
    contract_id: str
    reward: int = 0


class CargoLoadedEvent(DomainEvent):
    cargo_id: str
    ship_id: str
    contract_id: str | None = None


class CargoDeliveredEvent(DomainEvent):
    cargo_id: str
    destination_id: str
    contract_id: str | None = None


class SalvageClaimedEvent(DomainEvent):
    claim_id: str
    site_id: str
    contract_id: str | None = None
    output_ids: tuple[str, ...] = ()


class FirstContactEvent(DomainEvent):
    contact_id: str
    species_id: str
    status: str


class TranslationProgressedEvent(DomainEvent):
    matrix_id: str
    species_id: str
    progress: float
    complete: bool


class QuarantineStartedEvent(DomainEvent):
    target_id: str
    reason: str


class DiplomacyChangedEvent(DomainEvent):
    mission_id: str
    species_id: str
    standing: int


class AlienArtifactStudiedEvent(DomainEvent):
    artifact_id: str
    species_id: str
    insight: str


class DockingCompletedEvent(DomainEvent):
    ship_id: str
    station_id: str
    docked: bool


class ModuleEvacuatedEvent(DomainEvent):
    module_id: str
    evacuee_ids: tuple[str, ...] = ()


class CoursePlottedEvent(DomainEvent):
    ship_id: str
    destination_id: str
    fuel_cost: float


class JumpStartedEvent(DomainEvent):
    ship_id: str
    destination_id: str
    arrive_at_epoch: int


class JumpCompletedEvent(DomainEvent):
    ship_id: str
    destination_id: str


class FuelChangedEvent(DomainEvent):
    ship_id: str
    level: float
    maximum: float


class SignalDetectedEvent(DomainEvent):
    signal_id: str
    text: str


class NavigationHazardEncounteredEvent(DomainEvent):
    ship_id: str
    hazard: str


class OrbitEnteredEvent(DomainEvent):
    ship_id: str
    body_id: str


class LandingCompletedEvent(DomainEvent):
    ship_id: str
    body_id: str


class ChaosInfluenceAppliedEvent(DomainEvent):
    character_id: str
    source_id: str
    source_type: str
    amount: float
    corruption: float
    mutation_pressure: float


class OpenAirlockHandler:
    command_type = "open-airlock"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        airlock, error = _reachable_component(
            ctx.world, character_id, command.payload.get("airlock_id"), AirlockComponent
        )
        if airlock is None:
            return rejected(error if error else "target is not an airlock")

        state = airlock.get_component(AirlockComponent)
        if state.state == "open":
            return rejected("airlock is already open")
        operations: list[MutationOperation] = [
            SetComponent(airlock.id, replace(state, state="open"))
        ]

        events: list[DomainEvent] = [
            AirlockCycledEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(airlock.id),),
                    airlock_id=str(airlock.id),
                    state="open",
                )
            )
        ]
        module_id = parse_entity_id(state.module_id)
        if state.exposes_vacuum and module_id is not None and ctx.world.has_entity(module_id):
            module = ctx.entity(module_id)
            if module.has_component(PressurizedComponent):
                pressurized = module.get_component(PressurizedComponent)
                if pressurized.pressure > 0.0:
                    operations.append(SetComponent(module.id, replace(pressurized, pressure=0.0)))
                    events.append(
                        PressureChangedEvent(
                            **ctx.event_base(
                                visibility=EventVisibility.ROOM,
                                actor_id=str(character_id),
                                room_id=str(module_id),
                                target_ids=(str(module_id),),
                                module_id=str(module_id),
                                pressure=0.0,
                            )
                        )
                    )
        return planned(MutationPlan(tuple(operations)), *events)


class CycleAirlockHandler:
    command_type = "cycle-airlock"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        airlock, error = _reachable_component(
            ctx.world, character_id, command.payload.get("airlock_id"), AirlockComponent
        )
        if airlock is None:
            return rejected(error if error else "target is not an airlock")

        state = airlock.get_component(AirlockComponent)
        return planned(
            MutationPlan((SetComponent(airlock.id, replace(state, state="sealed")),)),
            AirlockCycledEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(airlock.id),),
                    airlock_id=str(airlock.id),
                    state="cycled",
                )
            ),
        )


class SealBulkheadHandler:
    command_type = "seal-bulkhead"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        bulkhead, error = _reachable_component(
            ctx.world, character_id, command.payload.get("bulkhead_id"), BulkheadComponent
        )
        if bulkhead is None:
            return rejected(error if error else "target is not a bulkhead")

        state = bulkhead.get_component(BulkheadComponent)
        if state.sealed:
            return rejected("bulkhead is already sealed")
        return planned(MutationPlan((SetComponent(bulkhead.id, replace(state, sealed=True)),)))


class RepairSystemHandler:
    command_type = "repair-system"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        system, error = _reachable_component(
            ctx.world, character_id, command.payload.get("system_id"), ShipSystemComponent
        )
        if system is None:
            return rejected(error if error else "target is not a ship system")

        state = system.get_component(ShipSystemComponent)
        if state.integrity >= 100.0 and state.online:
            return rejected("system is not damaged")
        return planned(
            MutationPlan((SetComponent(system.id, replace(state, integrity=100.0, online=True)),)),
            ShipSystemRepairedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(system.id),),
                    system_id=str(system.id),
                    system_type=state.system_type,
                )
            ),
        )


class ReroutePowerHandler:
    command_type = "reroute-power"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        grid, error = _reachable_component(
            ctx.world, character_id, command.payload.get("grid_id"), PowerGridComponent
        )
        if grid is None:
            return rejected(error if error else "target is not a power grid")
        system, error = _reachable_component(
            ctx.world, character_id, command.payload.get("system_id"), ShipSystemComponent
        )
        if system is None:
            return rejected(error if error else "target is not a ship system")

        try:
            amount = float(command.payload.get("amount", 0))
        except (TypeError, ValueError):
            return rejected("invalid power amount")
        if amount <= 0.0:
            return rejected("power amount must be positive")
        grid_state = grid.get_component(PowerGridComponent)
        if amount > grid_state.available:
            return rejected("not enough power available")

        system_state = system.get_component(ShipSystemComponent)
        return planned(
            MutationPlan(
                (
                    SetComponent(
                        grid.id, replace(grid_state, available=grid_state.available - amount)
                    ),
                    SetComponent(system.id, replace(system_state, online=True)),
                )
            ),
            PowerReroutedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(system.id),),
                    system_id=str(system.id),
                    amount=amount,
                )
            ),
        )


class InspectShipSystemHandler:
    command_type = "inspect"

    def can_handle(self, ctx: HandlerContext, command: SubmittedCommand) -> bool:
        if "system_id" in command.payload:
            return True
        system_id = _payload_entity_id(command, "system_id", "target_id")
        return (
            system_id is not None
            and ctx.world.has_entity(system_id)
            and ctx.entity(system_id).has_component(ShipSystemComponent)
        )

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        system, error = _reachable_component(
            ctx.world,
            character_id,
            _payload_entity_id(command, "system_id", "target_id"),
            ShipSystemComponent,
        )
        if system is None:
            return rejected(error if error else "target is not a ship system")
        state = system.get_component(ShipSystemComponent)
        return planned(
            MutationPlan(),
            ShipSystemInspectedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(system.id),),
                    system_id=str(system.id),
                    system_type=state.system_type,
                    integrity=state.integrity,
                    online=state.online,
                )
            ),
        )


def _tech_unlocked(world: World, tech_id: str) -> bool:
    """Whether colony-sim research has unlocked ``tech_id`` anywhere in the world."""
    if not tech_id:
        return True
    for entity in world.query().with_all([TechUnlockComponent]).execute_entities():
        if entity.get_component(TechUnlockComponent).tech_id == tech_id:
            return True
    return False


def _inventory_resource_stack(character: Entity, world: World, resource_type: str) -> Entity | None:
    for _edge, item_id in character.get_relationships(Contains):
        # Relics cascades inbound edge removal, so a related id is always live here.
        item = world.get_entity(item_id)
        if (
            item.has_component(ResourceStackComponent)
            and item.get_component(ResourceStackComponent).resource_type == resource_type
        ):
            return item
    return None


def _spend_inventory_resource_operations(
    character: Entity, world: World, inputs: tuple[tuple[str, int], ...]
) -> list[MutationOperation] | None:
    stacks: list[tuple[Entity, ResourceStackComponent, int]] = []
    for resource_type, quantity in inputs:
        needed = max(0, int(quantity))
        if needed == 0:
            continue
        stack = _inventory_resource_stack(character, world, resource_type)
        if stack is None:
            return None
        component = stack.get_component(ResourceStackComponent)
        if component.quantity < needed:
            return None
        stacks.append((stack, component, needed))
    return [
        SetComponent(stack.id, replace(component, quantity=component.quantity - needed))
        for stack, component, needed in stacks
    ]


def _spawn_inventory_resource_operations(
    character_id: EntityId, resource_type: str, quantity: int
) -> tuple[list[MutationOperation], EntityReference]:
    stack = EntityReference()
    return [
        AddEntity(
            (
                IdentityComponent(name=resource_type, kind="resource"),
                ResourceStackComponent(resource_type=resource_type, quantity=quantity),
            ),
            reference=stack,
        ),
        AddEdge(character_id, stack, Contains(mode=ContainmentMode.INVENTORY)),
    ], stack


class FabricateHandler:
    command_type = "fabricate"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        fabricator, error = _reachable_component(
            ctx.world, character_id, command.payload.get("fabricator_id"), FabricatorComponent
        )
        if fabricator is None:
            return rejected(error if error else "target is not a fabricator")
        if not fabricator.get_component(FabricatorComponent).online:
            return rejected("fabricator is offline")
        blueprint_entity, error = _reachable_component(
            ctx.world, character_id, command.payload.get("blueprint_id"), BlueprintComponent
        )
        if blueprint_entity is None:
            return rejected(error if error else "target is not a blueprint")
        blueprint = blueprint_entity.get_component(BlueprintComponent)
        if not _tech_unlocked(ctx.world, blueprint.required_tech):
            return rejected("required technology has not been researched")
        character = ctx.entity(character_id)
        operations = _spend_inventory_resource_operations(
            character, ctx.world, blueprint.resource_inputs
        )
        if operations is None:
            return rejected("not enough resources to fabricate")

        part = EntityReference()
        operations.extend(
            (
                AddEntity(
                    (
                        IdentityComponent(name=blueprint.name, kind="upgrade"),
                        ShipUpgradeComponent(
                            system_type=blueprint.system_type,
                            integrity_bonus=blueprint.integrity_bonus,
                        ),
                    ),
                    reference=part,
                ),
                AddEdge(character_id, part, Contains(mode=ContainmentMode.INVENTORY)),
            )
        )
        return planned(
            MutationPlan(tuple(operations)),
            lambda: ItemFabricatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(fabricator.id), str(blueprint_entity.id), str(part.require())),
                    fabricator_id=str(fabricator.id),
                    blueprint_id=str(blueprint_entity.id),
                    item_id=str(part.require()),
                    name=blueprint.name,
                    system_type=blueprint.system_type,
                    resource_inputs=blueprint.resource_inputs,
                )
            ),
        )


class InstallUpgradeHandler:
    command_type = "install-upgrade"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        upgrade_entity, error = _reachable_component(
            ctx.world, character_id, command.payload.get("upgrade_id"), ShipUpgradeComponent
        )
        if upgrade_entity is None:
            return rejected(error if error else "target is not an upgrade")
        upgrade = upgrade_entity.get_component(ShipUpgradeComponent)
        if upgrade.installed:
            return rejected("upgrade is already installed")
        system, error = _reachable_component(
            ctx.world, character_id, command.payload.get("system_id"), ShipSystemComponent
        )
        if system is None:
            return rejected(error if error else "target is not a ship system")
        system_state = system.get_component(ShipSystemComponent)
        if upgrade.system_type and upgrade.system_type != system_state.system_type:
            return rejected("upgrade does not fit this system")

        integrity = system_state.integrity + upgrade.integrity_bonus
        return planned(
            MutationPlan(
                (
                    SetComponent(
                        system.id, replace(system_state, integrity=integrity, online=True)
                    ),
                    SetComponent(upgrade_entity.id, replace(upgrade, installed=True)),
                )
            ),
            UpgradeInstalledEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(upgrade_entity.id), str(system.id)),
                    upgrade_id=str(upgrade_entity.id),
                    system_id=str(system.id),
                    system_type=system_state.system_type,
                    integrity=integrity,
                )
            ),
        )


def _move_entity_operations(
    world: World, entity_id: EntityId, destination_id: EntityId
) -> list[MutationOperation]:
    operations: list[MutationOperation] = []
    origin_id = container_of(world.get_entity(entity_id))
    if origin_id is not None and world.has_entity(origin_id):
        operations.append(RemoveEdge(origin_id, entity_id, Contains))
    operations.append(
        AddEdge(destination_id, entity_id, Contains(mode=ContainmentMode.ROOM_CONTENT))
    )
    return operations


class AcceptContractHandler:
    command_type = "accept-contract"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        contract, error = _reachable_component(
            ctx.world, character_id, command.payload.get("contract_id"), ContractComponent
        )
        if contract is None:
            return rejected(error if error else "target is not a contract")
        component = contract.get_component(ContractComponent)
        if component.status != "offered":
            return rejected("contract is not available")
        origin_id = container_of(contract)
        operations: list[MutationOperation] = []
        if origin_id is not None and ctx.world.has_entity(origin_id):
            operations.append(RemoveEdge(origin_id, contract.id, Contains))
        operations.extend(
            (
                AddEdge(character_id, contract.id, Contains(mode=ContainmentMode.INVENTORY)),
                SetComponent(
                    contract.id,
                    replace(component, status="active", accepted_by=str(character_id)),
                ),
            )
        )
        return planned(
            MutationPlan(tuple(operations)),
            ContractAcceptedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(contract.id),),
                    contract_id=str(contract.id),
                    contract_type=component.contract_type,
                )
            ),
        )


def _active_contract_for(
    entity: Entity, character_id: EntityId, expected_type: str | None = None
) -> ContractComponent | None:
    if not entity.has_component(ContractComponent):
        return None
    contract = entity.get_component(ContractComponent)
    if contract.status != "active" or contract.accepted_by != str(character_id):
        return None
    if expected_type is not None and contract.contract_type != expected_type:
        return None
    return contract


class LoadCargoHandler:
    command_type = "load-cargo"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        contract_entity, error = _reachable_component(
            ctx.world, character_id, command.payload.get("contract_id"), ContractComponent
        )
        if contract_entity is None:
            return rejected(error if error else "target is not a contract")
        contract = _active_contract_for(contract_entity, character_id, "cargo")
        if contract is None:
            return rejected("cargo contract is not active")
        cargo_entity, error = _reachable_component(
            ctx.world, character_id, command.payload.get("cargo_id"), CargoComponent
        )
        if cargo_entity is None:
            return rejected(error if error else "target is not cargo")
        ship, error = _reachable_component(
            ctx.world, character_id, command.payload.get("ship_id"), ShipComponent
        )
        if ship is None:
            return rejected(error if error else "target is not a ship")
        if contract.cargo_id is not None and contract.cargo_id != str(cargo_entity.id):
            return rejected("cargo does not match contract")
        cargo = cargo_entity.get_component(CargoComponent)
        if cargo.delivered:
            return rejected("cargo is already delivered")
        if cargo.loaded_on is not None:
            return rejected("cargo is already loaded")

        operations = _move_entity_operations(ctx.world, cargo_entity.id, ship.id)
        operations.append(SetComponent(cargo_entity.id, replace(cargo, loaded_on=str(ship.id))))
        return planned(
            MutationPlan(tuple(operations)),
            CargoLoadedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(cargo_entity.id), str(ship.id), str(contract_entity.id)),
                    cargo_id=str(cargo_entity.id),
                    ship_id=str(ship.id),
                    contract_id=str(contract_entity.id),
                )
            ),
        )


class DeliverCargoHandler:
    command_type = "deliver-cargo"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        contract_entity, error = _reachable_component(
            ctx.world, character_id, command.payload.get("contract_id"), ContractComponent
        )
        if contract_entity is None:
            return rejected(error if error else "target is not a contract")
        contract = _active_contract_for(contract_entity, character_id, "cargo")
        if contract is None:
            return rejected("cargo contract is not active")
        cargo_id = parse_entity_id(command.payload.get("cargo_id"))
        ship_id = parse_entity_id(command.payload.get("ship_id"))
        if cargo_id is None or ship_id is None:
            return rejected("invalid cargo or ship id")
        if not ctx.world.has_entity(cargo_id) or not ctx.world.has_entity(ship_id):
            return rejected("cargo or ship does not exist")
        cargo_entity = ctx.entity(cargo_id)
        ship = ctx.entity(ship_id)
        if not cargo_entity.has_component(CargoComponent):
            return rejected("target is not cargo")
        if not ship.has_component(ShipComponent):
            return rejected("target is not a ship")
        cargo = cargo_entity.get_component(CargoComponent)
        if cargo.loaded_on != str(ship.id):
            return rejected("cargo is not loaded on that ship")
        destination_key = contract.destination_id or cargo.destination_id
        destination_id = parse_entity_id(destination_key)
        if destination_id is None or not ctx.world.has_entity(destination_id):
            return rejected("destination does not exist")
        if container_of(ship) != destination_id:
            return rejected("ship is not at the destination")

        operations = _move_entity_operations(ctx.world, cargo_entity.id, destination_id)
        operations.extend(
            (
                SetComponent(cargo_entity.id, replace(cargo, loaded_on=None, delivered=True)),
                SetComponent(contract_entity.id, replace(contract, status="completed")),
            )
        )
        return planned(
            MutationPlan(tuple(operations)),
            CargoDeliveredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(destination_id),
                    target_ids=(str(cargo_entity.id), str(contract_entity.id)),
                    cargo_id=str(cargo_entity.id),
                    destination_id=str(destination_id),
                    contract_id=str(contract_entity.id),
                )
            ),
            ContractCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=str(destination_id),
                    target_ids=(str(contract_entity.id),),
                    contract_id=str(contract_entity.id),
                    reward=contract.reward,
                )
            ),
        )


class ClaimSalvageHandler:
    command_type = "claim-salvage"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        claim, error = _reachable_component(
            ctx.world, character_id, command.payload.get("claim_id"), SalvageClaimComponent
        )
        if claim is None:
            return rejected(error if error else "target is not a salvage claim")
        component = claim.get_component(SalvageClaimComponent)
        if component.claimed:
            return rejected("salvage is already claimed")
        contract_id = parse_entity_id(command.payload.get("contract_id"))
        if component.rights_contract_id is not None:
            contract_id = parse_entity_id(component.rights_contract_id)
        if contract_id is not None:
            if not ctx.world.has_entity(contract_id):
                return rejected("salvage contract does not exist")
            contract_entity = ctx.entity(contract_id)
            contract = _active_contract_for(contract_entity, character_id, "salvage")
            if contract is None and (
                not contract_entity.has_component(ContractComponent)
                or contract_entity.get_component(ContractComponent).accepted_by != str(character_id)
            ):
                return rejected("salvage rights are not held")
        operations: list[MutationOperation] = []
        outputs: list[EntityReference] = []
        for resource_type, quantity in component.resource_outputs:
            if quantity > 0:
                output_operations, output = _spawn_inventory_resource_operations(
                    character_id, resource_type, quantity
                )
                operations.extend(output_operations)
                outputs.append(output)
        operations.append(
            SetComponent(claim.id, replace(component, claimed=True, claimed_by=str(character_id)))
        )
        return planned(
            MutationPlan(tuple(operations)),
            lambda: SalvageClaimedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(claim.id),),
                    claim_id=str(claim.id),
                    site_id=component.site_id,
                    contract_id=str(contract_id) if contract_id is not None else None,
                    output_ids=tuple(str(output.require()) for output in outputs),
                )
            ),
        )


class InitiateContactHandler:
    command_type = "initiate-contact"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        contact, error = _reachable_component(
            ctx.world, character_id, command.payload.get("contact_id"), FirstContactComponent
        )
        if contact is None:
            return rejected(error if error else "target is not a contact")
        component = contact.get_component(FirstContactComponent)
        if str(character_id) in component.contacted_by:
            return rejected("contact already initiated")
        updated = replace(
            component,
            contacted_by=tuple(sorted((*component.contacted_by, str(character_id)))),
            status="contacted",
        )
        return planned(
            MutationPlan((SetComponent(contact.id, updated),)),
            FirstContactEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(contact.id), component.species_id),
                    contact_id=str(contact.id),
                    species_id=component.species_id,
                    status=updated.status,
                )
            ),
        )


class AttemptTranslationHandler:
    command_type = "attempt-translation"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        matrix, error = _reachable_component(
            ctx.world, character_id, command.payload.get("matrix_id"), TranslationMatrixComponent
        )
        if matrix is None:
            return rejected(error if error else "target is not a translation matrix")
        amount = float(command.payload.get("progress", 25.0))
        component = matrix.get_component(TranslationMatrixComponent)
        if component.complete:
            return rejected("translation is already complete")
        progress = min(100.0, component.progress + max(0.0, amount))
        updated = replace(component, progress=progress, complete=progress >= 100.0)
        return planned(
            MutationPlan((SetComponent(matrix.id, updated),)),
            TranslationProgressedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(matrix.id), component.species_id),
                    matrix_id=str(matrix.id),
                    species_id=component.species_id,
                    progress=updated.progress,
                    complete=updated.complete,
                )
            ),
        )


class QuarantineSampleHandler:
    command_type = "quarantine-sample"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if character_id is None or target_id is None:
            return rejected("invalid character or target id")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")
        character = ctx.entity(character_id)
        if target_id not in reachable_ids(ctx.world, character):
            return rejected("target is not reachable")
        target = ctx.entity(target_id)
        reason = str(command.payload.get("reason", "unknown organism")).strip()
        reason = reason or "unknown organism"
        return planned(
            MutationPlan(
                (
                    SetComponent(
                        target.id,
                        QuarantineComponent(
                            reason=reason, active=True, started_by=str(character_id)
                        ),
                    ),
                )
            ),
            QuarantineStartedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                    reason=reason,
                )
            ),
        )


class NegotiateAlienHandler:
    command_type = "negotiate-alien"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        mission, error = _reachable_component(
            ctx.world, character_id, command.payload.get("mission_id"), DiplomaticMissionComponent
        )
        if mission is None:
            return rejected(error if error else "target is not a diplomatic mission")
        delta = int(command.payload.get("standing_delta", 1))
        component = mission.get_component(DiplomaticMissionComponent)
        updated = replace(
            component,
            standing=component.standing + delta,
            last_negotiated_epoch=ctx.epoch,
        )
        return planned(
            MutationPlan((SetComponent(mission.id, updated),)),
            DiplomacyChangedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(mission.id), component.species_id),
                    mission_id=str(mission.id),
                    species_id=component.species_id,
                    standing=updated.standing,
                )
            ),
        )


class StudyAlienArtifactHandler:
    command_type = "study-alien-artifact"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        artifact, error = _reachable_component(
            ctx.world, character_id, command.payload.get("artifact_id"), AlienArtifactComponent
        )
        if artifact is None:
            return rejected(error if error else "target is not an alien artifact")
        component = artifact.get_component(AlienArtifactComponent)
        if str(character_id) in component.studied_by:
            return rejected("artifact already studied")
        updated = replace(
            component,
            studied_by=tuple(sorted((*component.studied_by, str(character_id)))),
        )
        return planned(
            MutationPlan((SetComponent(artifact.id, updated),)),
            AlienArtifactStudiedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(artifact.id),),
                    artifact_id=str(artifact.id),
                    species_id=component.species_id,
                    insight=component.insight,
                )
            ),
        )


class DockHandler:
    command_type = "dock"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx.world, character_id, command.payload.get("ship_id"), ShipComponent
        )
        if ship is None:
            return rejected(error if error else "target is not a ship")
        station, error = _reachable_component(
            ctx.world, character_id, command.payload.get("station_id"), StationComponent
        )
        if station is None:
            return rejected(error if error else "target is not a station")
        if _docked(ship, station.id):
            return rejected("ship is already docked here")

        port = str(command.payload.get("port", "main"))
        return planned(
            MutationPlan((AddEdge(ship.id, station.id, DockedTo(port=port)),)),
            DockingCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(ship.id), str(station.id)),
                    ship_id=str(ship.id),
                    station_id=str(station.id),
                    docked=True,
                )
            ),
        )


class UndockHandler:
    command_type = "undock"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx.world, character_id, command.payload.get("ship_id"), ShipComponent
        )
        if ship is None:
            return rejected(error if error else "target is not a ship")
        station, error = _reachable_component(
            ctx.world, character_id, command.payload.get("station_id"), StationComponent
        )
        if station is None:
            return rejected(error if error else "target is not a station")
        if not _docked(ship, station.id):
            return rejected("ship is not docked here")

        return planned(
            MutationPlan((RemoveEdge(ship.id, station.id, DockedTo),)),
            DockingCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(ship.id), str(station.id)),
                    ship_id=str(ship.id),
                    station_id=str(station.id),
                    docked=False,
                )
            ),
        )


class EvacuateModuleHandler:
    command_type = "evacuate-module"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        module, error = _reachable_component(
            ctx.world, character_id, command.payload.get("module_id"), HabitatModuleComponent
        )
        if module is None:
            return rejected(error if error else "target is not a habitat module")
        destination_id = parse_entity_id(command.payload.get("destination_id"))
        if destination_id is None or not ctx.world.has_entity(destination_id):
            return rejected("destination does not exist")
        if destination_id == module.id:
            return rejected("destination is the module being evacuated")

        evacuees: list[str] = []
        operations: list[MutationOperation] = []
        for occupant_id in list(contents(module)):
            occupant = ctx.entity(occupant_id)
            if not occupant.has_component(CharacterComponent):
                continue
            operations.extend(
                (
                    RemoveEdge(module.id, occupant_id, Contains),
                    AddEdge(
                        destination_id, occupant_id, Contains(mode=ContainmentMode.ROOM_CONTENT)
                    ),
                )
            )
            evacuees.append(str(occupant_id))
        if not evacuees:
            return rejected("no one to evacuate")
        return planned(
            MutationPlan(tuple(operations)),
            ModuleEvacuatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(destination_id),
                    target_ids=(str(module.id),),
                    module_id=str(module.id),
                    evacuee_ids=tuple(evacuees),
                )
            ),
        )


def _docked(ship: Entity, station_id: EntityId) -> bool:
    return any(target_id == station_id for _edge, target_id in ship.get_relationships(DockedTo))


#: Astrogation skill at or above which a pilot avoids a hazardous jump's complications.
_HAZARD_SKILL_THRESHOLD = 3


def _jump_route(origin: Entity, destination_id: EntityId) -> JumpRoute | None:
    for edge, target_id in origin.get_relationships(JumpRoute):
        if target_id == destination_id:
            return edge
    return None


class PlotCourseHandler:
    command_type = "plot-course"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx.world, character_id, command.payload.get("ship_id"), ShipComponent
        )
        if ship is None:
            return rejected(error if error else "target is not a ship")
        destination_id = parse_entity_id(command.payload.get("destination_id"))
        if destination_id is None or not ctx.world.has_entity(destination_id):
            return rejected("destination does not exist")
        if not ctx.entity(destination_id).has_component(StarSystemComponent):
            return rejected("destination is not a star system")
        origin_id = container_of(ship)
        if origin_id is None or not ctx.world.has_entity(origin_id):
            return rejected("ship is not in a star system")
        route = _jump_route(ctx.entity(origin_id), destination_id)
        if route is None:
            return rejected("no jump route to destination")

        return planned(
            MutationPlan(
                (
                    SetComponent(
                        ship.id,
                        NavigationRouteComponent(
                            fuel_cost=route.fuel_cost,
                            hazard=route.hazard,
                            jump_seconds=route.jump_seconds,
                            status="plotted",
                        ),
                    ),
                    *replace_single_edge_operations(ship, destination_id, NavigatesTo()),
                )
            ),
            CoursePlottedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(ship.id), str(destination_id)),
                    ship_id=str(ship.id),
                    destination_id=str(destination_id),
                    fuel_cost=route.fuel_cost,
                )
            ),
        )


class JumpHandler:
    command_type = "jump"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx.world, character_id, command.payload.get("ship_id"), ShipComponent
        )
        if ship is None:
            return rejected(error if error else "target is not a ship")
        if not ship.has_component(NavigationRouteComponent):
            return rejected("no course plotted")
        route = ship.get_component(NavigationRouteComponent)
        destination_id = _single_edge_target(ship, NavigatesTo)
        if destination_id is None:
            return rejected("course destination no longer exists")
        if route.status == "jumping":
            return rejected("ship is already jumping")
        if (
            not ship.has_component(JumpDriveComponent)
            or not ship.get_component(JumpDriveComponent).charged
        ):
            return rejected("jump drive is not charged")
        if not ship.has_component(FuelComponent):
            return rejected("ship has no fuel tank")
        fuel = ship.get_component(FuelComponent)
        if fuel.level < route.fuel_cost:
            return rejected("not enough fuel to jump")

        new_fuel = replace(fuel, level=fuel.level - route.fuel_cost)
        arrive_at = ctx.epoch + int(route.jump_seconds)

        events: list[DomainEvent] = [
            FuelChangedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(ship.id),),
                    ship_id=str(ship.id),
                    level=new_fuel.level,
                    maximum=new_fuel.maximum,
                )
            ),
            JumpStartedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(ship.id),),
                    ship_id=str(ship.id),
                    destination_id=str(destination_id),
                    arrive_at_epoch=arrive_at,
                )
            ),
        ]
        if route.hazard and route.hazard != "none":
            character = ctx.entity(character_id)
            skill = (
                character.get_component(AstrogationComponent).skill
                if character.has_component(AstrogationComponent)
                else 0
            )
            if skill < _HAZARD_SKILL_THRESHOLD:
                events.append(
                    NavigationHazardEncounteredEvent(
                        **ctx.event_base(
                            visibility=EventVisibility.ROOM,
                            actor_id=str(character_id),
                            room_id=_room_id(ctx.world, character_id),
                            target_ids=(str(ship.id),),
                            ship_id=str(ship.id),
                            hazard=route.hazard,
                        )
                    )
                )
        return planned(
            MutationPlan(
                (
                    SetComponent(ship.id, new_fuel),
                    SetComponent(
                        ship.id, replace(route, status="jumping", arrive_at_epoch=arrive_at)
                    ),
                )
            ),
            *events,
        )


class ScanHandler:
    command_type = "scan"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx.world, character_id, command.payload.get("ship_id"), SensorComponent
        )
        if ship is None:
            return rejected(error if error else "no sensor to scan with")
        origin_id = container_of(ship)
        if origin_id is None or not ctx.world.has_entity(origin_id):
            return rejected("ship is not in a star system")

        events: list[DomainEvent] = []
        operations: list[MutationOperation] = []
        for content_id in contents(ctx.entity(origin_id)):
            signal_entity = ctx.entity(content_id)
            if not signal_entity.has_component(DistressSignalComponent):
                continue
            signal = signal_entity.get_component(DistressSignalComponent)
            if signal.detected:
                continue
            operations.append(SetComponent(signal_entity.id, replace(signal, detected=True)))
            events.append(
                SignalDetectedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(character_id),
                        room_id=_room_id(ctx.world, character_id),
                        target_ids=(str(content_id),),
                        signal_id=str(content_id),
                        text=signal.text,
                    )
                )
            )
        if not events:
            return rejected("scan finds nothing")
        return planned(MutationPlan(tuple(operations)), *events)


class AnswerDistressSignalHandler:
    command_type = "answer-distress-signal"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        signal_entity, error = _reachable_component(
            ctx.world, character_id, command.payload.get("signal_id"), DistressSignalComponent
        )
        if signal_entity is None:
            return rejected(error if error else "target is not a distress signal")
        signal = signal_entity.get_component(DistressSignalComponent)
        if not signal.detected:
            return rejected("signal has not been detected")
        if signal.answered:
            return rejected("signal already answered")
        return planned(
            MutationPlan((SetComponent(signal_entity.id, replace(signal, answered=True)),))
        )


class RefuelHandler:
    command_type = "refuel"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx.world, character_id, command.payload.get("ship_id"), FuelComponent
        )
        if ship is None:
            return rejected(error if error else "ship has no fuel tank")
        fuel = ship.get_component(FuelComponent)
        if fuel.level >= fuel.maximum:
            return rejected("fuel tank is already full")

        raw_amount = command.payload.get("amount")
        if raw_amount is None:
            new_level = fuel.maximum
        else:
            try:
                new_level = min(fuel.maximum, fuel.level + float(raw_amount))
            except (TypeError, ValueError):
                return rejected("invalid fuel amount")
        return planned(
            MutationPlan((SetComponent(ship.id, replace(fuel, level=new_level)),)),
            FuelChangedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(ship.id),),
                    ship_id=str(ship.id),
                    level=new_level,
                    maximum=fuel.maximum,
                )
            ),
        )


class EnterOrbitHandler:
    command_type = "enter-orbit"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx.world, character_id, command.payload.get("ship_id"), ShipComponent
        )
        if ship is None:
            return rejected(error if error else "target is not a ship")
        body, error = _reachable_component(
            ctx.world, character_id, command.payload.get("body_id"), OrbitalBodyComponent
        )
        if body is None:
            return rejected(error if error else "target is not an orbital body")

        return planned(
            MutationPlan(
                (
                    SetComponent(ship.id, OrbitComponent(altitude="orbit")),
                    *replace_single_edge_operations(ship, body.id, OrbitsBody()),
                )
            ),
            OrbitEnteredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(ship.id), str(body.id)),
                    ship_id=str(ship.id),
                    body_id=str(body.id),
                )
            ),
        )


class LeaveOrbitHandler:
    command_type = "leave-orbit"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx.world, character_id, command.payload.get("ship_id"), ShipComponent
        )
        if ship is None:
            return rejected(error if error else "target is not a ship")
        if not ship.has_component(OrbitComponent):
            return rejected("ship is not in orbit")
        body_id = _single_edge_target(ship, OrbitsBody)
        operations: list[MutationOperation] = [RemoveComponent(ship.id, OrbitComponent)]
        if body_id is not None:
            operations.append(RemoveEdge(ship.id, body_id, OrbitsBody))
        return planned(MutationPlan(tuple(operations)))


class LandHandler:
    command_type = "land"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx.world, character_id, command.payload.get("ship_id"), ShipComponent
        )
        if ship is None:
            return rejected(error if error else "target is not a ship")
        if not ship.has_component(OrbitComponent):
            return rejected("ship must be in orbit to land")
        orbit = ship.get_component(OrbitComponent)
        if orbit.altitude == "surface":
            return rejected("ship is already landed")
        body_id = _single_edge_target(ship, OrbitsBody)
        if body_id is None:
            return rejected("orbital body no longer exists")
        body = ctx.entity(body_id)
        if (
            body.has_component(OrbitalBodyComponent)
            and not body.get_component(OrbitalBodyComponent).landable
        ):
            return rejected("body cannot be landed on")

        return planned(
            MutationPlan((SetComponent(ship.id, replace(orbit, altitude="surface")),)),
            LandingCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(ship.id), str(body_id)),
                    ship_id=str(ship.id),
                    body_id=str(body_id),
                )
            ),
        )


class LaunchHandler:
    command_type = "launch"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ship, error = _reachable_component(
            ctx.world, character_id, command.payload.get("ship_id"), ShipComponent
        )
        if ship is None:
            return rejected(error if error else "target is not a ship")
        if not ship.has_component(OrbitComponent):
            return rejected("ship is not landed")
        orbit = ship.get_component(OrbitComponent)
        if orbit.altitude != "surface":
            return rejected("ship is not on a surface")
        return planned(MutationPlan((SetComponent(ship.id, replace(orbit, altitude="orbit")),)))


class JumpTravelConsequence:
    """Complete in-progress jumps: move the ship to its destination system."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        query = world.query().with_all([ShipComponent, NavigationRouteComponent])
        for ship in query.execute_entities():
            route = ship.get_component(NavigationRouteComponent)
            if route.status != "jumping" or epoch < route.arrive_at_epoch:
                continue
            destination_id = _single_edge_target(ship, NavigatesTo)
            if destination_id is None:
                continue
            origin_id = container_of(ship)
            if origin_id is not None and world.has_entity(origin_id):
                world.get_entity(origin_id).remove_relationship(Contains, ship.id)
            world.get_entity(destination_id).add_relationship(
                Contains(mode=ContainmentMode.ROOM_CONTENT), ship.id
            )
            ship.remove_component(NavigationRouteComponent)
            ship.remove_relationship(NavigatesTo, destination_id)
            events.append(
                JumpCompletedEvent(
                    **_void_event(
                        epoch,
                        visibility=EventVisibility.ROOM,
                        room_id=str(destination_id),
                        target_ids=(str(ship.id), str(destination_id)),
                        ship_id=str(ship.id),
                        destination_id=str(destination_id),
                    )
                )
            )
        return events


class LifeSupportConsequence:
    """Drain or replenish module oxygen based on life support, and flag failures."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for module in world.query().with_all([OxygenComponent]).execute_entities():
            oxygen = module.get_component(OxygenComponent)
            elapsed = max(0, epoch - oxygen.last_updated_epoch)
            if elapsed <= 0:
                continue
            hours = elapsed / 3600.0
            online = True
            rate = 5.0
            if module.has_component(LifeSupportComponent):
                support = module.get_component(LifeSupportComponent)
                online = support.online
                rate = support.oxygen_per_hour
            if online:
                level = min(oxygen.maximum, oxygen.level + rate * hours)
            else:
                level = max(0.0, oxygen.level - rate * hours)
            failed = level <= 0.0
            replace_component(
                module,
                replace(oxygen, level=level, failed=failed, last_updated_epoch=epoch),
            )
            if failed and not oxygen.failed:
                events.append(
                    LifeSupportFailedEvent(
                        **_void_event(
                            epoch,
                            visibility=EventVisibility.ROOM,
                            room_id=str(module.id),
                            target_ids=(str(module.id),),
                            module_id=str(module.id),
                        )
                    )
                )
        return events


def _reachable_chaos_warding(world: World, character: Entity) -> float:
    protection = 0.0
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        if entity.has_component(ChaosWardComponent):
            protection += max(0.0, entity.get_component(ChaosWardComponent).protection_per_hour)
        if entity.has_component(RadiationShieldComponent):
            protection += max(0.0, entity.get_component(RadiationShieldComponent).strength) / 100.0
    return protection


def _chaos_targets_for_source(world: World, source_id: EntityId) -> list[Entity]:
    targets: list[Entity] = []
    for character in (
        world.query()
        .with_all([CharacterComponent])
        .with_none([DeadComponent, SuspendedComponent])
        .execute_entities()
    ):
        if source_id in reachable_ids(world, character):
            targets.append(character)
    return targets


def _ship_systems_near_source(world: World, source: Entity) -> list[Entity]:
    parent_id = container_of(source)
    if parent_id is None or not world.has_entity(parent_id):
        return []
    nearby_ids = {parent_id, *contents(world.get_entity(parent_id))}
    return [
        world.get_entity(entity_id)
        for entity_id in nearby_ids
        if world.has_entity(entity_id)
        and world.get_entity(entity_id).has_component(ShipSystemComponent)
    ]


class ChaosInfluenceConsequence:
    """Apply void-sim warp/chaos pressure as barbarian-sim corruption."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for source in world.query().with_all([ChaosInfluenceComponent]).execute_entities():
            influence = source.get_component(ChaosInfluenceComponent)
            elapsed = max(0, epoch - influence.last_updated_epoch)
            replace_component(source, replace(influence, last_updated_epoch=epoch))
            if elapsed <= 0:
                continue
            hours = elapsed / 3600.0

            for character in _chaos_targets_for_source(world, source.id):
                warding = _reachable_chaos_warding(world, character)
                rate = max(0.0, influence.corruption_per_hour - warding)
                amount = rate * hours
                if amount <= 0.0:
                    continue

                current = (
                    character.get_component(CorruptionComponent)
                    if character.has_component(CorruptionComponent)
                    else CorruptionComponent()
                )
                updated_corruption = replace(
                    current,
                    amount=current.amount + amount,
                    last_updated_epoch=epoch,
                )
                replace_component(character, updated_corruption)

                pressure = (
                    character.get_component(ChaosMutationPressureComponent)
                    if character.has_component(ChaosMutationPressureComponent)
                    else ChaosMutationPressureComponent()
                )
                mutation_delta = amount * max(0.0, influence.mutation_pressure_per_corruption)
                replace_component(
                    character,
                    replace(
                        pressure,
                        amount=pressure.amount + mutation_delta,
                        last_updated_epoch=epoch,
                    ),
                )
                events.append(
                    CorruptionGainedEvent(
                        **_void_event(
                            epoch,
                            visibility=EventVisibility.PRIVATE,
                            actor_id=str(character.id),
                            room_id=_room_id(world, character.id),
                            character_id=str(character.id),
                            amount=updated_corruption.amount,
                        )
                    )
                )
                events.append(
                    ChaosInfluenceAppliedEvent(
                        **_void_event(
                            epoch,
                            visibility=EventVisibility.PRIVATE,
                            actor_id=str(character.id),
                            room_id=_room_id(world, character.id),
                            target_ids=(str(character.id), str(source.id)),
                            character_id=str(character.id),
                            source_id=str(source.id),
                            source_type=influence.source_type,
                            amount=amount,
                            corruption=updated_corruption.amount,
                            mutation_pressure=pressure.amount + mutation_delta,
                        )
                    )
                )

            system_damage = max(0.0, influence.system_damage_per_hour) * hours
            if system_damage <= 0.0:
                continue
            for system_entity in _ship_systems_near_source(world, source):
                system = system_entity.get_component(ShipSystemComponent)
                integrity = max(0.0, system.integrity - system_damage)
                online = system.online and integrity > 0.0
                if integrity == system.integrity and online == system.online:
                    continue
                replace_component(
                    system_entity,
                    replace(system, integrity=integrity, online=online),
                )
                events.append(
                    ShipSystemDamagedEvent(
                        **_void_event(
                            epoch,
                            visibility=EventVisibility.ROOM,
                            room_id=str(container_of(system_entity) or source.id),
                            target_ids=(str(system_entity.id), str(source.id)),
                            system_id=str(system_entity.id),
                            system_type=system.system_type,
                            integrity=integrity,
                        )
                    )
                )
        return events


# --- Crew duty shifts (catalogue 8.3) -------------------------------------------------


@dataclass(frozen=True)
class DutyShiftComponent(Component):
    """A watch rotation: a time slot plus the role and tasks it covers."""

    name: str
    start_hour: int = 0
    end_hour: int = 8
    role: str = ""
    tasks: tuple[str, ...] = ()


@dataclass(frozen=True)
class CrewDutyStatusComponent(Component):
    """Cached on/off-duty flag so prompt fragments can read it without the clock."""

    on_duty: bool = False
    last_changed_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person or not self.on_duty:
            return ()
        return ("You are currently on duty.",)


@dataclass(frozen=True)
class WorksShift(Edge):
    """crew -> duty-shift entity; ``station`` is the post this crew covers."""

    station: str = ""


class CrewShiftAssignedEvent(DomainEvent):
    character_id: str
    shift_id: str
    shift_name: str
    station: str = ""


class CrewShiftRelievedEvent(DomainEvent):
    character_id: str
    shift_id: str
    shift_name: str


class CrewDutyChangedEvent(DomainEvent):
    character_id: str
    shift_id: str
    shift_name: str
    on_duty: bool


class AwayTeamDeployedEvent(DomainEvent):
    team_id: str
    mission: str


class MoraleChangedEvent(DomainEvent):
    character_id: str
    value: int


class MutinyStartedEvent(DomainEvent):
    character_id: str


class DroneCommandedEvent(DomainEvent):
    drone_id: str
    task: str


class ShipAIHackedEvent(DomainEvent):
    ai_id: str
    trust: int


class DataSalvagedEvent(DomainEvent):
    data_id: str
    data_type: str


class XenobiologyStudiedEvent(DomainEvent):
    sample_id: str
    contamination: float


class TradeProtocolAcceptedEvent(DomainEvent):
    protocol_id: str
    terms: str


class EmergencyResolvedEvent(DomainEvent):
    emergency_id: str
    emergency_type: str


class ReactorStabilizedEvent(DomainEvent):
    reactor_id: str
    stability: float


class GravityAdjustedEvent(DomainEvent):
    gravity_id: str
    enabled: bool
    strength: float


class BoardingRepelledEvent(DomainEvent):
    threat_id: str
    threat_level: int


class PassengerDeliveredEvent(DomainEvent):
    passenger_id: str


class SurveyCompletedEvent(DomainEvent):
    site_id: str
    resource: str


class MiningCompletedEvent(DomainEvent):
    site_id: str
    resource_type: str
    quantity: int


class CustomsInspectedEvent(DomainEvent):
    hold_id: str
    contraband_found: bool


class SmugglingCompartmentSearchedEvent(DomainEvent):
    compartment_id: str
    discovered: bool


class InsuranceClaimedEvent(DomainEvent):
    policy_id: str


class MortgagePaidEvent(DomainEvent):
    mortgage_id: str
    balance: int


def _hour_of_day(epoch: int) -> int:
    return (epoch % SECONDS_PER_DAY) // SECONDS_PER_HOUR


def _shift_covers_hour(shift: DutyShiftComponent, hour: int) -> bool:
    if shift.start_hour == shift.end_hour:
        return True  # a round-the-clock watch
    if shift.start_hour < shift.end_hour:
        return shift.start_hour <= hour < shift.end_hour
    # the watch wraps past midnight, e.g. 22:00 -> 06:00
    return hour >= shift.start_hour or hour < shift.end_hour


class AssignCrewShiftHandler:
    command_type = "assign-crew-shift"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        shift_id = parse_entity_id(command.payload.get("shift_id"))
        if character_id is None or shift_id is None:
            return rejected("invalid crew or shift id")
        if not ctx.world.has_entity(shift_id):
            return rejected("shift does not exist")
        shift_entity = ctx.entity(shift_id)
        if not shift_entity.has_component(DutyShiftComponent):
            return rejected("target is not a duty shift")
        character = ctx.entity(character_id)
        if character.has_relationship(WorksShift, shift_id):
            return rejected("already assigned to this shift")

        station = str(command.payload.get("station", "")).strip()
        shift = shift_entity.get_component(DutyShiftComponent)
        room_id = container_of(character)
        return planned(
            MutationPlan((AddEdge(character_id, shift_id, WorksShift(station=station)),)),
            CrewShiftAssignedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(room_id) if room_id is not None else None,
                    target_ids=(str(shift_id),),
                    character_id=str(character_id),
                    shift_id=str(shift_id),
                    shift_name=shift.name,
                    station=station,
                )
            ),
        )


class RelieveCrewShiftHandler:
    command_type = "relieve-crew-shift"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        shift_id = parse_entity_id(command.payload.get("shift_id"))
        if character_id is None or shift_id is None:
            return rejected("invalid crew or shift id")
        if not ctx.world.has_entity(shift_id):
            return rejected("shift does not exist")
        character = ctx.entity(character_id)
        if not character.has_relationship(WorksShift, shift_id):
            return rejected("not assigned to this shift")

        shift_entity = ctx.entity(shift_id)
        shift_name = (
            shift_entity.get_component(DutyShiftComponent).name
            if shift_entity.has_component(DutyShiftComponent)
            else _name(shift_entity)
        )
        room_id = container_of(character)
        return planned(
            MutationPlan((RemoveEdge(character_id, shift_id, WorksShift),)),
            CrewShiftRelievedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(room_id) if room_id is not None else None,
                    target_ids=(str(shift_id),),
                    character_id=str(character_id),
                    shift_id=str(shift_id),
                    shift_name=shift_name,
                )
            ),
        )


def _reachable_entity_with(ctx: HandlerContext, character_id: EntityId, raw_id, component):
    target_id = parse_entity_id(raw_id)
    if target_id is None:
        return None, rejected("invalid target id")
    if not ctx.world.has_entity(character_id):
        return None, rejected("character does not exist")
    if not ctx.world.has_entity(target_id):
        return None, rejected("target does not exist")
    character = ctx.entity(character_id)
    if target_id not in reachable_ids(ctx.world, character):
        return None, rejected("target is not reachable")
    entity = ctx.entity(target_id)
    if not entity.has_component(component):
        return None, rejected("target has wrong component")
    return entity, None


class DeployAwayTeamHandler:
    command_type = "deploy-away-team"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        team, error = _reachable_entity_with(
            ctx, character_id, command.payload.get("team_id"), AwayTeamComponent
        )
        if error is not None:
            return error
        component = team.get_component(AwayTeamComponent)
        if component.deployed:
            return rejected("away team already deployed")
        updated = replace(component, deployed=True)
        return planned(
            MutationPlan((SetComponent(team.id, updated),)),
            AwayTeamDeployedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(container_of(ctx.entity(character_id)))
                    if container_of(ctx.entity(character_id))
                    else None,
                    target_ids=(str(team.id),),
                    team_id=str(team.id),
                    mission=updated.mission,
                )
            ),
        )


class BoostMoraleHandler:
    command_type = "boost-morale"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        character = ctx.entity(character_id)
        amount = int(command.payload.get("amount", 1))
        current = (
            character.get_component(MoraleComponent)
            if character.has_component(MoraleComponent)
            else MoraleComponent()
        )
        updated = replace(current, value=current.value + amount)
        return planned(
            MutationPlan((SetComponent(character_id, updated),)),
            MoraleChangedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=str(container_of(character)) if container_of(character) else None,
                    target_ids=(str(character_id),),
                    character_id=str(character_id),
                    value=updated.value,
                )
            ),
        )


class StartMutinyHandler:
    command_type = "start-mutiny"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        character = ctx.entity(character_id)
        return planned(
            MutationPlan(
                (
                    SetComponent(
                        character_id, MutinyComponent(active=True, ringleader_id=str(character_id))
                    ),
                )
            ),
            MutinyStartedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(container_of(character)) if container_of(character) else None,
                    target_ids=(str(character_id),),
                    character_id=str(character_id),
                )
            ),
        )


class CommandDroneHandler:
    command_type = "command"

    def can_handle(self, ctx: HandlerContext, command: SubmittedCommand) -> bool:
        target_id = parse_entity_id(command.payload.get("target_id"))
        return (
            target_id is not None
            and ctx.world.has_entity(target_id)
            and ctx.entity(target_id).has_component(DroneComponent)
        )

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        drone, error = _reachable_entity_with(
            ctx, character_id, command.payload.get("target_id"), DroneComponent
        )
        if error is not None:
            return error
        task = str(command.payload.get("instruction", "assist")).strip() or "assist"
        updated = replace(drone.get_component(DroneComponent), assigned_task=task, active=True)
        return planned(
            MutationPlan((SetComponent(drone.id, updated),)),
            DroneCommandedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(container_of(ctx.entity(character_id)))
                    if container_of(ctx.entity(character_id))
                    else None,
                    target_ids=(str(drone.id),),
                    drone_id=str(drone.id),
                    task=task,
                )
            ),
        )


class HackShipAIHandler:
    command_type = "hack-ship-ai"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        ai, error = _reachable_entity_with(
            ctx, character_id, command.payload.get("ai_id"), ShipAIComponent
        )
        if error is not None:
            return error
        ai_state = ai.get_component(ShipAIComponent)
        updated = replace(ai_state, hacked=True, trust=ai_state.trust + 1)
        return planned(
            MutationPlan((SetComponent(ai.id, updated),)),
            ShipAIHackedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=str(container_of(ctx.entity(character_id)))
                    if container_of(ctx.entity(character_id))
                    else None,
                    target_ids=(str(ai.id),),
                    ai_id=str(ai.id),
                    trust=updated.trust,
                )
            ),
        )


class SalvageDataHandler:
    command_type = "salvage-data"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        data, error = _reachable_entity_with(
            ctx, character_id, command.payload.get("data_id"), DataSalvageComponent
        )
        if error is not None:
            return error
        component = data.get_component(DataSalvageComponent)
        return planned(
            MutationPlan(
                (
                    SetComponent(
                        data.id, replace(component, encrypted=False, recovered_by=str(character_id))
                    ),
                )
            ),
            DataSalvagedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=str(container_of(ctx.entity(character_id)))
                    if container_of(ctx.entity(character_id))
                    else None,
                    target_ids=(str(data.id),),
                    data_id=str(data.id),
                    data_type=component.data_type,
                )
            ),
        )


class StudyXenobiologyHandler:
    command_type = "study-xenobiology"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        sample, error = _reachable_entity_with(
            ctx, character_id, command.payload.get("sample_id"), XenobiologySampleComponent
        )
        if error is not None:
            return error
        component = sample.get_component(XenobiologySampleComponent)
        updated = replace(
            component,
            studied_by=tuple(sorted((*component.studied_by, str(character_id)))),
        )
        return planned(
            MutationPlan((SetComponent(sample.id, updated),)),
            XenobiologyStudiedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=str(container_of(ctx.entity(character_id)))
                    if container_of(ctx.entity(character_id))
                    else None,
                    target_ids=(str(sample.id),),
                    sample_id=str(sample.id),
                    contamination=updated.contamination,
                )
            ),
        )


class AcceptTradeProtocolHandler:
    command_type = "accept-trade-protocol"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        protocol, error = _reachable_entity_with(
            ctx, character_id, command.payload.get("protocol_id"), TradeProtocolComponent
        )
        if error is not None:
            return error
        component = protocol.get_component(TradeProtocolComponent)
        return planned(
            MutationPlan((SetComponent(protocol.id, replace(component, accepted=True)),)),
            TradeProtocolAcceptedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(container_of(ctx.entity(character_id)))
                    if container_of(ctx.entity(character_id))
                    else None,
                    target_ids=(str(protocol.id),),
                    protocol_id=str(protocol.id),
                    terms=component.terms,
                )
            ),
        )


class ResolveEmergencyHandler:
    command_type = "resolve-emergency"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        emergency, error = _reachable_entity_with(
            ctx, character_id, command.payload.get("emergency_id"), EmergencyComponent
        )
        if error is not None:
            return error
        component = emergency.get_component(EmergencyComponent)
        return planned(
            MutationPlan((SetComponent(emergency.id, replace(component, resolved=True)),)),
            EmergencyResolvedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(container_of(ctx.entity(character_id)))
                    if container_of(ctx.entity(character_id))
                    else None,
                    target_ids=(str(emergency.id),),
                    emergency_id=str(emergency.id),
                    emergency_type=component.emergency_type,
                )
            ),
        )


class StabilizeReactorHandler:
    command_type = "stabilize-reactor"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        reactor, error = _reachable_entity_with(
            ctx, character_id, command.payload.get("reactor_id"), ReactorComponent
        )
        if error is not None:
            return error
        component = reactor.get_component(ReactorComponent)
        amount = float(command.payload.get("amount", 10.0))
        updated = replace(
            component, stability=min(100.0, component.stability + amount), online=True
        )
        return planned(
            MutationPlan((SetComponent(reactor.id, updated),)),
            ReactorStabilizedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(container_of(ctx.entity(character_id)))
                    if container_of(ctx.entity(character_id))
                    else None,
                    target_ids=(str(reactor.id),),
                    reactor_id=str(reactor.id),
                    stability=updated.stability,
                )
            ),
        )


class AdjustGravityHandler:
    command_type = "adjust-gravity"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        gravity, error = _reachable_entity_with(
            ctx, character_id, command.payload.get("gravity_id"), GravityComponent
        )
        if error is not None:
            return error
        enabled = bool(command.payload.get("enabled", True))
        strength = float(command.payload.get("strength", 1.0))
        updated = replace(
            gravity.get_component(GravityComponent), enabled=enabled, strength=strength
        )
        return planned(
            MutationPlan((SetComponent(gravity.id, updated),)),
            GravityAdjustedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(container_of(ctx.entity(character_id)))
                    if container_of(ctx.entity(character_id))
                    else None,
                    target_ids=(str(gravity.id),),
                    gravity_id=str(gravity.id),
                    enabled=enabled,
                    strength=strength,
                )
            ),
        )


class RepelBoardersHandler:
    command_type = "repel-boarders"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        threat, error = _reachable_entity_with(
            ctx, character_id, command.payload.get("threat_id"), BoardingThreatComponent
        )
        if error is not None:
            return error
        component = threat.get_component(BoardingThreatComponent)
        return planned(
            MutationPlan((SetComponent(threat.id, replace(component, repelled=True)),)),
            BoardingRepelledEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(container_of(ctx.entity(character_id)))
                    if container_of(ctx.entity(character_id))
                    else None,
                    target_ids=(str(threat.id),),
                    threat_id=str(threat.id),
                    threat_level=component.threat_level,
                )
            ),
        )


class DeliverPassengerHandler:
    command_type = "deliver-passenger"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        passenger, error = _reachable_entity_with(
            ctx, character_id, command.payload.get("passenger_id"), PassengerComponent
        )
        if error is not None:
            return error
        component = passenger.get_component(PassengerComponent)
        return planned(
            MutationPlan((SetComponent(passenger.id, replace(component, delivered=True)),)),
            PassengerDeliveredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=str(container_of(ctx.entity(character_id)))
                    if container_of(ctx.entity(character_id))
                    else None,
                    target_ids=(str(passenger.id),),
                    passenger_id=str(passenger.id),
                )
            ),
        )


class SurveySiteHandler:
    command_type = "survey-site"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        site, error = _reachable_entity_with(
            ctx, character_id, command.payload.get("site_id"), SurveySiteComponent
        )
        if error is not None:
            return error
        component = site.get_component(SurveySiteComponent)
        return planned(
            MutationPlan(
                (
                    SetComponent(
                        site.id,
                        replace(
                            component,
                            surveyed_by=tuple(sorted((*component.surveyed_by, str(character_id)))),
                        ),
                    ),
                )
            ),
            SurveyCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=str(container_of(ctx.entity(character_id)))
                    if container_of(ctx.entity(character_id))
                    else None,
                    target_ids=(str(site.id),),
                    site_id=str(site.id),
                    resource=component.resource,
                )
            ),
        )


class MineAsteroidHandler:
    command_type = "mine-asteroid"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        site, error = _reachable_entity_with(
            ctx, character_id, command.payload.get("site_id"), MiningSiteComponent
        )
        if error is not None:
            return error
        component = site.get_component(MiningSiteComponent)
        if component.remaining <= 0:
            return rejected("mining site is depleted")
        quantity = min(int(command.payload.get("quantity", 1)), component.remaining)
        operations, output = _spawn_inventory_resource_operations(
            character_id, component.resource_type, quantity
        )
        operations.insert(
            0,
            SetComponent(site.id, replace(component, remaining=component.remaining - quantity)),
        )
        return planned(
            MutationPlan(tuple(operations)),
            lambda: MiningCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=str(container_of(ctx.entity(character_id)))
                    if container_of(ctx.entity(character_id))
                    else None,
                    target_ids=(str(site.id), str(output.require())),
                    site_id=str(site.id),
                    resource_type=component.resource_type,
                    quantity=quantity,
                )
            ),
        )


class InspectCustomsHandler:
    command_type = "inspect"

    def can_handle(self, ctx: HandlerContext, command: SubmittedCommand) -> bool:
        if "hold_id" in command.payload:
            return True
        hold_id = _payload_entity_id(command, "hold_id", "target_id")
        return (
            hold_id is not None
            and ctx.world.has_entity(hold_id)
            and ctx.entity(hold_id).has_component(CustomsHoldComponent)
        )

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        hold, error = _reachable_entity_with(
            ctx,
            character_id,
            _payload_entity_id(command, "hold_id", "target_id"),
            CustomsHoldComponent,
        )
        if error is not None:
            return error
        contraband = bool(command.payload.get("contraband_found", False))
        return planned(
            MutationPlan(
                (
                    SetComponent(
                        hold.id,
                        replace(
                            hold.get_component(CustomsHoldComponent),
                            inspected=True,
                            contraband_found=contraband,
                        ),
                    ),
                )
            ),
            CustomsInspectedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(container_of(ctx.entity(character_id)))
                    if container_of(ctx.entity(character_id))
                    else None,
                    target_ids=(str(hold.id),),
                    hold_id=str(hold.id),
                    contraband_found=contraband,
                )
            ),
        )


class SearchSmugglingCompartmentHandler:
    command_type = "search-smuggling-compartment"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        compartment, error = _reachable_entity_with(
            ctx, character_id, command.payload.get("compartment_id"), SmugglingCompartmentComponent
        )
        if error is not None:
            return error
        component = compartment.get_component(SmugglingCompartmentComponent)
        discovered = component.hidden
        return planned(
            MutationPlan(
                (SetComponent(compartment.id, replace(component, discovered=discovered)),)
            ),
            SmugglingCompartmentSearchedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(container_of(ctx.entity(character_id)))
                    if container_of(ctx.entity(character_id))
                    else None,
                    target_ids=(str(compartment.id),),
                    compartment_id=str(compartment.id),
                    discovered=discovered,
                )
            ),
        )


class ClaimInsuranceHandler:
    command_type = "claim-insurance"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        policy, error = _reachable_entity_with(
            ctx, character_id, command.payload.get("policy_id"), InsurancePolicyComponent
        )
        if error is not None:
            return error
        component = policy.get_component(InsurancePolicyComponent)
        if component.claimed:
            return rejected("insurance already claimed")
        return planned(
            MutationPlan((SetComponent(policy.id, replace(component, claimed=True)),)),
            InsuranceClaimedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=str(container_of(ctx.entity(character_id)))
                    if container_of(ctx.entity(character_id))
                    else None,
                    target_ids=(str(policy.id),),
                    policy_id=str(policy.id),
                )
            ),
        )


class PayMortgageHandler:
    command_type = "pay-mortgage"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        mortgage, error = _reachable_entity_with(
            ctx, character_id, command.payload.get("mortgage_id"), MortgageComponent
        )
        if error is not None:
            return error
        amount = int(command.payload.get("amount", 0))
        if amount <= 0:
            return rejected("mortgage payment must be positive")
        component = mortgage.get_component(MortgageComponent)
        updated = replace(component, balance=max(0, component.balance - amount))
        return planned(
            MutationPlan((SetComponent(mortgage.id, updated),)),
            MortgagePaidEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=str(container_of(ctx.entity(character_id)))
                    if container_of(ctx.entity(character_id))
                    else None,
                    target_ids=(str(mortgage.id),),
                    mortgage_id=str(mortgage.id),
                    balance=updated.balance,
                )
            ),
        )


class CrewDutyConsequence:
    """Flip crew on and off duty as the ship clock enters and leaves their watch."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        hour = _hour_of_day(epoch)
        query = (
            world.query()
            .with_all([CharacterComponent])
            .with_none([DeadComponent, SuspendedComponent])
        )
        for crew in query.execute_entities():
            shifts = [
                shift_id
                for _edge, shift_id in crew.get_relationships(WorksShift)
                if world.has_entity(shift_id)
            ]
            had_status = crew.has_component(CrewDutyStatusComponent)
            if not shifts and not had_status:
                continue

            on_duty = False
            active_id: EntityId | None = None
            active_name = ""
            for shift_id in shifts:
                shift = world.get_entity(shift_id)
                if shift.has_component(DutyShiftComponent) and _shift_covers_hour(
                    shift.get_component(DutyShiftComponent), hour
                ):
                    on_duty = True
                    active_id = shift_id
                    active_name = shift.get_component(DutyShiftComponent).name
                    break

            prev = crew.get_component(CrewDutyStatusComponent).on_duty if had_status else False
            if had_status and on_duty == prev:
                continue
            replace_component(
                crew,
                CrewDutyStatusComponent(on_duty=on_duty, last_changed_epoch=epoch),
            )
            if on_duty != prev:
                events.append(
                    CrewDutyChangedEvent(
                        **_void_event(
                            epoch,
                            visibility=EventVisibility.PRIVATE,
                            actor_id=str(crew.id),
                            target_ids=(str(active_id),) if active_id is not None else (),
                            character_id=str(crew.id),
                            shift_id=str(active_id) if active_id is not None else "",
                            shift_name=active_name,
                            on_duty=on_duty,
                        )
                    )
                )
        return events


def voidsim_fragments(world: World, character: Entity) -> list[str]:
    lines: list[str] = []
    ctx = ComponentPromptContext.for_entity(world, character)
    module_id = container_of(character)
    if module_id is not None and world.has_entity(module_id):
        module = world.get_entity(module_id)
        module_ctx = ComponentPromptContext.for_entity(
            world, module, perspective=ctx.perspective, room=module
        )
        for component_type in (
            HabitatModuleComponent,
            PressurizedComponent,
            OxygenComponent,
            LifeSupportComponent,
            ChaosInfluenceComponent,
        ):
            if module.has_component(component_type):
                lines.extend(module.get_component(component_type).prompt_fragments(module_ctx))
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        entity_ctx = ComponentPromptContext.for_entity(
            world, entity, perspective=ctx.perspective, room=ctx.room, target=character
        )
        for component_type in (
            ChaosInfluenceComponent,
            ChaosWardComponent,
            ShipSystemComponent,
            FabricatorComponent,
            BlueprintComponent,
            ShipUpgradeComponent,
            ContractComponent,
            CargoComponent,
            SalvageClaimComponent,
            AlienSpeciesComponent,
            FirstContactComponent,
            TranslationMatrixComponent,
            QuarantineComponent,
            DiplomaticMissionComponent,
            AlienArtifactComponent,
            XenobiologySampleComponent,
            TradeProtocolComponent,
            DroneComponent,
            ShipAIComponent,
            DataSalvageComponent,
            AwayTeamComponent,
            EmergencyComponent,
            ReactorComponent,
            GravityComponent,
            BoardingThreatComponent,
            PassengerComponent,
            SurveySiteComponent,
            MiningSiteComponent,
            CustomsHoldComponent,
            SmugglingCompartmentComponent,
            InsurancePolicyComponent,
            MortgageComponent,
            AirlockComponent,
            PowerGridComponent,
            FuelComponent,
            OrbitComponent,
            NavigationRouteComponent,
            DistressSignalComponent,
            OrbitalBodyComponent,
        ):
            if entity.has_component(component_type):
                lines.extend(entity.get_component(component_type).prompt_fragments(entity_ctx))
        if entity.has_component(ShipComponent):
            for _edge, station_id in entity.get_relationships(DockedTo):
                if world.has_entity(station_id):
                    lines.append(
                        f"{_name(entity)} is docked at {_name(world.get_entity(station_id))}."
                    )
    if module_id is not None and world.has_entity(module_id):
        current = world.get_entity(module_id)
        if current.has_component(StarSystemComponent):
            current_ctx = ComponentPromptContext.for_entity(
                world, current, perspective=ctx.perspective, room=current
            )
            lines.extend(current.get_component(StarSystemComponent).prompt_fragments(current_ctx))
    if character.has_component(CorruptionComponent):
        corruption = character.get_component(CorruptionComponent)
        lines.append(f"Chaos corruption: {corruption.amount:g}.")
    for component_type in (
        ChaosMutationPressureComponent,
        RadiationMutationPressureComponent,
        CyberneticMutationPressureComponent,
        MoraleComponent,
        MutinyComponent,
    ):
        if character.has_component(component_type):
            lines.extend(character.get_component(component_type).prompt_fragments(ctx))
    for edge, shift_id in character.get_relationships(WorksShift):
        # Relics cascades inbound edge removal, so a related id is always live here.
        shift_entity = world.get_entity(shift_id)
        if shift_entity.has_component(DutyShiftComponent):
            shift = shift_entity.get_component(DutyShiftComponent)
            station = f", station {edge.station}" if edge.station else ""
            lines.append(
                f"Duty shift: {shift.name} watch "
                f"({shift.start_hour:02d}:00-{shift.end_hour:02d}:00) "
                f"as {shift.role or 'crew'}{station}."
            )
    if character.has_component(CrewDutyStatusComponent):
        lines.extend(character.get_component(CrewDutyStatusComponent).prompt_fragments(ctx))
    return sorted(lines)


def validate_voidsim_relationships(world: World) -> None:
    for ship in world.query().execute_entities():
        has_orbit = ship.has_component(OrbitComponent)
        has_route = ship.has_component(NavigationRouteComponent)
        orbits = ship.get_relationships(OrbitsBody)
        routes = ship.get_relationships(NavigatesTo)
        if not (has_orbit or has_route or orbits or routes):
            continue
        if not ship.has_component(ShipComponent):
            raise MutationError(f"navigation state source {ship.id} is not a ship")
        if len(orbits) > 1:
            raise MutationError(f"ship {ship.id} has more than one OrbitsBody edge")
        if len(routes) > 1:
            raise MutationError(f"ship {ship.id} has more than one NavigatesTo edge")
        if has_orbit != bool(orbits):
            raise MutationError(
                f"ship {ship.id} must pair OrbitComponent with exactly one OrbitsBody edge"
            )
        if has_route:
            component = ship.get_component(NavigationRouteComponent)
            valid_destination = not routes if component.destination_key else len(routes) == 1
        else:
            valid_destination = not routes
        if not valid_destination:
            raise MutationError(
                f"ship {ship.id} must pair NavigationRouteComponent with exactly one "
                "NavigatesTo edge or a semantic destination_key"
            )
        if orbits and not world.get_entity(orbits[0][1]).has_component(OrbitalBodyComponent):
            raise MutationError(f"OrbitsBody target {orbits[0][1]} is not an orbital body")
        if routes and not world.get_entity(routes[0][1]).has_component(StarSystemComponent):
            raise MutationError(f"NavigatesTo target {routes[0][1]} is not a star system")


def install_voidsim(actor) -> None:
    register_world_invariant(actor.world, validate_voidsim_relationships)
    actor.register_consequence(LifeSupportConsequence())
    actor.register_consequence(JumpTravelConsequence())
    actor.register_consequence(ChaosInfluenceConsequence())
    actor.register_consequence(CrewDutyConsequence())


__all__ = [
    "AirlockComponent",
    "AirlockCycledEvent",
    "AlienArtifactComponent",
    "AlienArtifactStudiedEvent",
    "AlienSpeciesComponent",
    "AcceptTradeProtocolHandler",
    "AnswerDistressSignalHandler",
    "AttemptTranslationHandler",
    "AssignCrewShiftHandler",
    "AstrogationComponent",
    "AwayTeamComponent",
    "MemberOfAwayTeam",
    "AwayTeamDeployedEvent",
    "BlueprintComponent",
    "BoardingRepelledEvent",
    "BoardingThreatComponent",
    "BulkheadComponent",
    "AcceptContractHandler",
    "CargoComponent",
    "CargoDeliveredEvent",
    "CargoLoadedEvent",
    "ChaosInfluenceAppliedEvent",
    "ChaosInfluenceComponent",
    "ChaosInfluenceConsequence",
    "ChaosMutationPressureComponent",
    "ChaosWardComponent",
    "ClaimSalvageHandler",
    "ContractAcceptedEvent",
    "ContractCompletedEvent",
    "ContractComponent",
    "CoursePlottedEvent",
    "CrewDutyChangedEvent",
    "CrewDutyConsequence",
    "CrewDutyStatusComponent",
    "CrewShiftAssignedEvent",
    "CrewShiftRelievedEvent",
    "CommandDroneHandler",
    "CustomsHoldComponent",
    "CustomsInspectedEvent",
    "CycleAirlockHandler",
    "DataSalvageComponent",
    "DataSalvagedEvent",
    "DeliverCargoHandler",
    "DeliverPassengerHandler",
    "DeployAwayTeamHandler",
    "DistressSignalComponent",
    "DiplomacyChangedEvent",
    "DiplomaticMissionComponent",
    "DutyShiftComponent",
    "DockHandler",
    "DockedTo",
    "DockingCompletedEvent",
    "EnterOrbitHandler",
    "EmergencyComponent",
    "EmergencyResolvedEvent",
    "EvacuateModuleHandler",
    "FabricateHandler",
    "FabricatorComponent",
    "FuelChangedEvent",
    "FuelComponent",
    "FirstContactComponent",
    "FirstContactEvent",
    "GravityAdjustedEvent",
    "GravityComponent",
    "HabitatModuleComponent",
    "HackShipAIHandler",
    "InsuranceClaimedEvent",
    "InsurancePolicyComponent",
    "InspectShipSystemHandler",
    "InspectCustomsHandler",
    "InstallUpgradeHandler",
    "InitiateContactHandler",
    "ItemFabricatedEvent",
    "JumpCompletedEvent",
    "JumpDriveComponent",
    "JumpHandler",
    "JumpRoute",
    "JumpStartedEvent",
    "JumpTravelConsequence",
    "LandHandler",
    "LandingCompletedEvent",
    "LaunchHandler",
    "LeaveOrbitHandler",
    "LifeSupportComponent",
    "LifeSupportConsequence",
    "LifeSupportFailedEvent",
    "LoadCargoHandler",
    "ModuleEvacuatedEvent",
    "MortgageComponent",
    "MortgagePaidEvent",
    "MoraleChangedEvent",
    "MoraleComponent",
    "MutinyComponent",
    "MutinyStartedEvent",
    "CyberneticMutationPressureComponent",
    "NegotiateAlienHandler",
    "NavigationHazardEncounteredEvent",
    "NavigationRouteComponent",
    "NavigatesTo",
    "OpenAirlockHandler",
    "OrbitComponent",
    "OrbitsBody",
    "OrbitEnteredEvent",
    "OrbitalBodyComponent",
    "OxygenComponent",
    "PlotCourseHandler",
    "PowerGridComponent",
    "PowerReroutedEvent",
    "PressureChangedEvent",
    "PressurizedComponent",
    "PassengerComponent",
    "PassengerDeliveredEvent",
    "PayMortgageHandler",
    "QuarantineComponent",
    "QuarantineSampleHandler",
    "QuarantineStartedEvent",
    "RadiationShieldComponent",
    "RadiationMutationPressureComponent",
    "RefuelHandler",
    "RelieveCrewShiftHandler",
    "RepairSystemHandler",
    "ReactorComponent",
    "ReactorStabilizedEvent",
    "RepelBoardersHandler",
    "ResolveEmergencyHandler",
    "ReroutePowerHandler",
    "SalvageDataHandler",
    "ScanHandler",
    "SealBulkheadHandler",
    "SensorComponent",
    "SalvageClaimComponent",
    "SalvageClaimedEvent",
    "SearchSmugglingCompartmentHandler",
    "ShipComponent",
    "ShipAIComponent",
    "ShipAIHackedEvent",
    "ShipSystemComponent",
    "ShipSystemDamagedEvent",
    "ShipSystemRepairedEvent",
    "ShipUpgradeComponent",
    "SignalDetectedEvent",
    "SmugglingCompartmentComponent",
    "SmugglingCompartmentSearchedEvent",
    "StarSystemComponent",
    "StationComponent",
    "StabilizeReactorHandler",
    "StudyAlienArtifactHandler",
    "StudyXenobiologyHandler",
    "SurveyCompletedEvent",
    "SurveySiteComponent",
    "SurveySiteHandler",
    "MineAsteroidHandler",
    "MiningCompletedEvent",
    "MiningSiteComponent",
    "TranslationMatrixComponent",
    "TranslationProgressedEvent",
    "TradeProtocolAcceptedEvent",
    "TradeProtocolComponent",
    "UndockHandler",
    "UpgradeInstalledEvent",
    "WorksShift",
    "XenobiologySampleComponent",
    "XenobiologyStudiedEvent",
    "install_voidsim",
    "voidsim_fragments",
    "validate_voidsim_relationships",
]
