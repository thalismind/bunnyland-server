"""Colony-sim social crafting mechanics (spec 11.17, 21.4).

This v1 focuses on explicit reservations, resource gathering, and recipe crafting. It
intentionally does not include base building or hidden job automation.
"""

from __future__ import annotations

from dataclasses import field, replace
from functools import partial

from pydantic.dataclasses import dataclass
from relics import Component, Edge, Entity, EntityId, Frequency, System, World

from bunnyland.foundation.consumables.components import (
    ConsumableComponent,
    DrinkableComponent,
    FoodComponent,
)

from ...core.commands import SubmittedCommand
from ...core.components import (
    AffectComponent,
    BleedingComponent,
    CharacterComponent,
    DownedComponent,
    HealthComponent,
    IdentityComponent,
    InjuryComponent,
    PortableComponent,
    RoomComponent,
    SleepingComponent,
)
from ...core.ecs import (
    container_of,
    contents,
    entity_name,
    parse_entity_id,
    reachable_ids,
    replace_component,
    spawn_entity,
)
from ...core.ecs import (
    room_id_for as _room_id,
)
from ...core.edges import ContainmentMode, Contains, HasInjury
from ...core.events import (
    DomainEvent,
    EventVisibility,
    ItemCraftedEvent,
    ItemForbiddenEvent,
    ItemHauledEvent,
    JobAssignedEvent,
    JobCompletedEvent,
    OwnershipClaimedEvent,
    OwnershipReleasedEvent,
    ReservationCreatedEvent,
    ReservationReleasedEvent,
    ResourceGatheredEvent,
    StackMergedEvent,
    StackSplitEvent,
    StockpileCreatedEvent,
    StorageFilterChangedEvent,
    event_base,
)
from ...core.handlers import HandlerContext, HandlerResult, ok, rejected
from ...prompts import ComponentPromptContext

SECONDS_PER_DAY = 24 * 60 * 60
SECONDS_PER_HOUR = 60 * 60


@dataclass(frozen=True)
class ColonySimComponent(Component):
    enabled: bool = True


@dataclass(frozen=True)
class ResourceNodeComponent(Component):
    resource_type: str
    current: int
    maximum: int
    regen_per_day: float = 0.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"Nearby resource: {self.resource_type} ({self.current} available).",)


@dataclass(frozen=True)
class ResourceStackComponent(Component):
    resource_type: str
    quantity: int


@dataclass(frozen=True)
class StockpileComponent(Component):
    capacity: int = 20


@dataclass(frozen=True)
class StorageFilterComponent(Component):
    allowed_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class HaulableComponent(Component):
    priority: int = 0


@dataclass(frozen=True)
class ForbiddenComponent(Component):
    forbidden: bool = True

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        return (f"{entity_name(ctx.entity, 'something')} is forbidden for hauling.",)


@dataclass(frozen=True)
class WorkstationComponent(Component):
    station_type: str
    quality: float = 1.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"Nearby workstation: {self.station_type}.",)


@dataclass(frozen=True)
class RecipeComponent(Component):
    recipe_id: str
    inputs: dict[str, int]
    outputs: dict[str, int]
    required_station: str | None = None
    action_cost: int = 1
    output_entities: dict[str, dict[str, object]] = field(default_factory=dict)

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"You know the {self.recipe_id} recipe.",)


@dataclass(frozen=True)
class JobComponent(Component):
    job_type: str
    priority: int
    assigned: bool = False
    completed: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        if self.completed:
            return ()
        status = "assigned" if self.assigned else "available"
        return (f"Nearby job: {self.job_type} priority {self.priority} ({status}).",)


@dataclass(frozen=True)
class JobBillComponent(Component):
    recipe_id: str
    work_required: float
    work_done: float = 0.0
    suspended: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (
            f"Nearby job bill: {self.recipe_id} "
            f"{self.work_done:.1f}/{self.work_required:.1f} work.",
        )


@dataclass(frozen=True)
class WorkPriorityComponent(Component):
    priorities: dict[str, int] = field(default_factory=dict)

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person or not self.priorities:
            return ()
        parts = [f"{work}:{priority}" for work, priority in sorted(self.priorities.items())]
        return ("Work priorities: " + ", ".join(parts) + ".",)


@dataclass(frozen=True)
class WorkCapabilityComponent(Component):
    disabled_work: tuple[str, ...] = ()
    skill_levels: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class PawnProfileComponent(Component):
    backstory: str = ""
    passions: dict[str, int] = field(default_factory=dict)
    expectations: str = "low"

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        lines: list[str] = []
        if self.backstory:
            lines.append(f"Backstory: {self.backstory}.")
        if self.passions:
            parts = [f"{work}:{level}" for work, level in sorted(self.passions.items())]
            lines.append("Passions: " + ", ".join(parts) + ".")
        lines.append(f"Pawn expectations: {self.expectations}.")
        return tuple(lines)


@dataclass(frozen=True)
class RoomRoleComponent(Component):
    role: str = "room"


@dataclass(frozen=True)
class RoomStatComponent(Component):
    beauty: float = 0.0
    cleanliness: float = 0.0
    comfort: float = 0.0
    wealth: float = 0.0


@dataclass(frozen=True)
class RoomQualityComponent(Component):
    role: str = "room"
    beauty: float = 0.0
    cleanliness: float = 0.0
    comfort: float = 0.0
    impressiveness: float = 0.0
    updated_at_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"Room quality: {self.role}, impressiveness {self.impressiveness:.1f}.",)


@dataclass(frozen=True)
class ColonyWealthComponent(Component):
    wealth: float = 0.0
    expectations: str = "low"
    updated_at_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"Colony wealth is {self.wealth:.0f}; expectations are {self.expectations}.",)


@dataclass(frozen=True)
class PrisonerComponent(Component):
    prisoner: bool = True
    recruitment_difficulty: float = 10.0
    recruitment_progress: float = 0.0
    policy: str = "hold"

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        return (
            f"Prisoner policy: {self.policy}, recruitment "
            f"{self.recruitment_progress:.1f}/{self.recruitment_difficulty:.1f}.",
        )


@dataclass(frozen=True)
class ResearchProjectComponent(Component):
    project_id: str
    work_required: float
    work_done: float = 0.0
    unlocked: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        state = "unlocked" if self.unlocked else f"{self.work_done:.1f}/{self.work_required:.1f}"
        return (f"Research project: {self.project_id} ({state}).",)


@dataclass(frozen=True)
class TechUnlockComponent(Component):
    tech_id: str
    unlocked_at_epoch: int = 0


@dataclass(frozen=True)
class ColonyIncidentComponent(Component):
    incident_type: str
    severity: int = 1
    resolved: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        if self.resolved:
            return ()
        return (f"Colony incident: {self.incident_type} severity {self.severity}.",)


@dataclass(frozen=True)
class FactionRelationComponent(Component):
    faction_id: str
    goodwill: float = 0.0


@dataclass(frozen=True)
class TradeOfferComponent(Component):
    faction_id: str
    gives: dict[str, int] = field(default_factory=dict)
    wants: dict[str, int] = field(default_factory=dict)
    goodwill_delta: float = 0.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        gives = ", ".join(f"{qty} {kind}" for kind, qty in sorted(self.gives.items()))
        wants = ", ".join(f"{qty} {kind}" for kind, qty in sorted(self.wants.items()))
        return (f"Trade offer from {self.faction_id}: gives {gives}; wants {wants}.",)


@dataclass(frozen=True)
class CaravanComponent(Component):
    destination: str
    cargo: dict[str, int] = field(default_factory=dict)
    departed_at_epoch: int = 0
    returned: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        if self.returned:
            return ()
        return (f"Caravan bound for {self.destination}.",)


@dataclass(frozen=True)
class MedicineComponent(Component):
    quality: float = 1.0
    uses: int = 1

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"Nearby medicine: quality {self.quality:.2f}, uses {self.uses}.",)


@dataclass(frozen=True)
class MedicalBedComponent(Component):
    quality: float = 1.0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return ("Nearby medical bed is available.",)


@dataclass(frozen=True)
class BedRestComponent(Component):
    started_at_epoch: int
    bed_id: str | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        return ("You are on medical bed rest.",)


@dataclass(frozen=True)
class InfectionComponent(Component):
    severity: float = 0.0
    immunity: float = 0.0
    last_updated_epoch: int = 0

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person:
            return ()
        return (f"Infection: severity {self.severity:.2f}, immunity {self.immunity:.2f}.",)


@dataclass(frozen=True)
class BodyPartHealthComponent(Component):
    part: str
    health: float = 1.0
    missing: bool = False
    prosthetic: str | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        state = "missing" if self.missing else f"health {self.health:.1f}"
        if self.prosthetic:
            state += f", prosthetic {self.prosthetic}"
        return (f"Body part {self.part}: {state}.",)


@dataclass(frozen=True)
class SurgeryBillComponent(Component):
    part: str
    operation: str
    prosthetic_item_id: str | None = None
    work_required: float = 10.0
    completed: bool = False

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        if self.completed:
            return ()
        return (f"Surgery bill: {self.operation} {self.part}.",)


@dataclass(frozen=True)
class ProstheticComponent(Component):
    part: str
    quality: float = 1.0


@dataclass(frozen=True)
class MentalStateComponent(Component):
    state: str = "stable"
    reason: str = ""
    expires_at_epoch: int | None = None

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        if not ctx.is_first_person or self.state == "stable":
            return ()
        return (f"Mental state: {self.state} ({self.reason}).",)


@dataclass(frozen=True)
class ReservedBy(Edge):
    since_epoch: int


@dataclass(frozen=True)
class AssignedTo(Edge):
    since_epoch: int


@dataclass(frozen=True)
class Owns(Edge):
    since_epoch: int


@dataclass(frozen=True)
class HasBodyPart(Edge):
    pass


@dataclass(frozen=True)
class AllowedIn(Edge):
    pass


@dataclass(frozen=True)
class MemberOfCaravan(Edge):
    pass


class WorkPrioritySetEvent(DomainEvent):
    work_type: str
    priority: int


class AllowedAreaSetEvent(DomainEvent):
    room_ids: tuple[str, ...]


class RoomQualityUpdatedEvent(DomainEvent):
    room_id_updated: str
    impressiveness: float


class ColonyWealthUpdatedEvent(DomainEvent):
    wealth: float
    expectations: str


class WoundTendedEvent(DomainEvent):
    patient_id: str
    injury_id: str
    medicine_id: str | None = None
    quality: float = 1.0


class CharacterRescuedEvent(DomainEvent):
    patient_id: str
    bed_id: str


class InfectionChangedEvent(DomainEvent):
    patient_id: str
    severity: float
    immunity: float


class MentalStateChangedEvent(DomainEvent):
    state: str
    reason: str


class PawnProfileUpdatedEvent(DomainEvent):
    backstory: str
    expectations: str


class JobBillProgressedEvent(DomainEvent):
    bill_id: str
    work_done: float
    completed: bool


class PrisonerPolicySetEvent(DomainEvent):
    prisoner_id: str
    policy: str


class RecruitmentProgressedEvent(DomainEvent):
    prisoner_id: str
    progress: float
    recruited: bool


class ResearchProgressedEvent(DomainEvent):
    project_id: str
    work_done: float
    unlocked: bool


class TechUnlockedEvent(DomainEvent):
    project_id: str
    tech_id: str


class ColonyIncidentResolvedEvent(DomainEvent):
    incident_id: str
    incident_type: str


class TradeCompletedEvent(DomainEvent):
    offer_id: str
    faction_id: str
    goodwill: float


class CaravanFormedEvent(DomainEvent):
    caravan_id: str
    destination: str


class SurgeryPerformedEvent(DomainEvent):
    patient_id: str
    surgery_id: str
    part: str
    operation: str


class ResourceRegenSystem(System):
    """Regenerate resource nodes up to their maximum from ``regen_per_day``."""

    def query(self):
        return self.q.with_all([ResourceNodeComponent])

    def frequency(self) -> Frequency:
        return Frequency.EVERY_TICK

    def process(self, entities, components, delta) -> None:
        days = delta / SECONDS_PER_DAY
        if days <= 0:
            return
        for entity in entities:
            node = entity.get_component(ResourceNodeComponent)
            if node.regen_per_day <= 0 or node.current >= node.maximum:
                continue
            recovered = int(node.regen_per_day * days)
            if recovered <= 0:
                continue
            replace_component(
                entity,
                replace(node, current=min(node.maximum, node.current + recovered)),
            )


_event_base = partial(event_base, default_visibility=EventVisibility.ROOM)


class RoomQualityConsequence:
    """Compute room quality from room role/stat components and contained fixtures."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for room in world.query().with_all([RoomComponent]).execute_entities():
            role = (
                room.get_component(RoomRoleComponent).role
                if room.has_component(RoomRoleComponent)
                else "room"
            )
            beauty = cleanliness = comfort = wealth = 0.0
            if room.has_component(RoomStatComponent):
                stats = room.get_component(RoomStatComponent)
                beauty += stats.beauty
                cleanliness += stats.cleanliness
                comfort += stats.comfort
                wealth += stats.wealth
            for item_id in contents(room):
                item = world.get_entity(item_id)
                if item.has_component(RoomStatComponent):
                    stats = item.get_component(RoomStatComponent)
                    beauty += stats.beauty
                    cleanliness += stats.cleanliness
                    comfort += stats.comfort
                    wealth += stats.wealth
            impressiveness = round(beauty + cleanliness + comfort + (wealth / 100.0), 3)
            existing = (
                room.get_component(RoomQualityComponent)
                if room.has_component(RoomQualityComponent)
                else RoomQualityComponent()
            )
            # Only react to real quality changes — comparing the whole component would also
            # see ``updated_at_epoch`` and fire (and churn the component) every single tick.
            if (
                existing.role == role
                and existing.beauty == beauty
                and existing.cleanliness == cleanliness
                and existing.comfort == comfort
                and existing.impressiveness == impressiveness
            ):
                continue
            replace_component(
                room,
                RoomQualityComponent(
                    role=role,
                    beauty=beauty,
                    cleanliness=cleanliness,
                    comfort=comfort,
                    impressiveness=impressiveness,
                    updated_at_epoch=epoch,
                ),
            )
            events.append(
                RoomQualityUpdatedEvent(
                    **_event_base(
                        epoch,
                        room_id=str(room.id),
                        target_ids=(str(room.id),),
                        room_id_updated=str(room.id),
                        impressiveness=impressiveness,
                    )
                )
            )
        return events


class ColonyWealthConsequence:
    """Bookkeep settlement wealth from resource stacks, room fixtures, and workstations."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        wealth = 0.0
        for entity in world.query().execute_entities():
            if entity.has_component(ResourceStackComponent):
                wealth += entity.get_component(ResourceStackComponent).quantity
            if entity.has_component(RoomStatComponent):
                wealth += entity.get_component(RoomStatComponent).wealth
            if entity.has_component(WorkstationComponent):
                wealth += 10.0 * entity.get_component(WorkstationComponent).quality
        expectations = "low" if wealth < 50 else "moderate" if wealth < 200 else "high"
        events: list[DomainEvent] = []
        for marker in world.query().with_all([ColonySimComponent]).execute_entities():
            existing = (
                marker.get_component(ColonyWealthComponent)
                if marker.has_component(ColonyWealthComponent)
                else ColonyWealthComponent()
            )
            updated = ColonyWealthComponent(
                wealth=round(wealth, 3),
                expectations=expectations,
                updated_at_epoch=epoch,
            )
            if existing != updated:
                replace_component(marker, updated)
                events.append(
                    ColonyWealthUpdatedEvent(
                        **_event_base(
                            epoch,
                            visibility=EventVisibility.SYSTEM,
                            wealth=updated.wealth,
                            expectations=updated.expectations,
                        )
                    )
                )
        return events


class MedicalRecoveryConsequence:
    """Advance bed-rest recovery and infection progress."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for patient in world.query().with_all([CharacterComponent]).execute_entities():
            if patient.has_component(BedRestComponent) and patient.has_component(HealthComponent):
                rest = patient.get_component(BedRestComponent)
                health = patient.get_component(HealthComponent)
                elapsed_hours = max(0, epoch - rest.started_at_epoch) / SECONDS_PER_HOUR
                if elapsed_hours > 0 and health.current < health.maximum:
                    bed_quality = 1.0
                    bed_id = parse_entity_id(rest.bed_id)
                    if bed_id is not None and world.has_entity(bed_id):
                        bed = world.get_entity(bed_id)
                        if bed.has_component(MedicalBedComponent):
                            bed_quality = bed.get_component(MedicalBedComponent).quality
                    healed = min(health.maximum, health.current + elapsed_hours * bed_quality)
                    replace_component(patient, replace(health, current=healed))
                    replace_component(patient, replace(rest, started_at_epoch=epoch))
            if not patient.has_component(InfectionComponent):
                continue
            infection = patient.get_component(InfectionComponent)
            elapsed_hours = max(0, epoch - infection.last_updated_epoch) / SECONDS_PER_HOUR
            if elapsed_hours <= 0:
                continue
            resting = patient.has_component(BedRestComponent)
            immunity = min(1.0, infection.immunity + elapsed_hours * (0.04 if resting else 0.02))
            severity = max(0.0, infection.severity + elapsed_hours * 0.01 - immunity * 0.02)
            updated = InfectionComponent(
                severity=round(severity, 3),
                immunity=round(immunity, 3),
                last_updated_epoch=epoch,
            )
            replace_component(patient, updated)
            events.append(
                InfectionChangedEvent(
                    **_event_base(
                        epoch,
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(patient.id),
                        target_ids=(str(patient.id),),
                        patient_id=str(patient.id),
                        severity=updated.severity,
                        immunity=updated.immunity,
                    )
                )
            )
        return events


class MentalStateConsequence:
    """Trigger mild breaks from severe need/mood pressure and inspirations from high mood."""

    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        from bunnyland.foundation.meters.mechanics import band
        from bunnyland.foundation.needs.mechanics import (
            ComfortNeedComponent,
            FatigueComponent,
            FunNeedComponent,
            HygieneComponent,
            PrivacyNeedComponent,
            SafetyNeedComponent,
            SocialNeedComponent,
        )

        events: list[DomainEvent] = []
        need_types = (
            FatigueComponent,
            HygieneComponent,
            ComfortNeedComponent,
            FunNeedComponent,
            SocialNeedComponent,
            PrivacyNeedComponent,
            SafetyNeedComponent,
        )
        for character in world.query().with_all([CharacterComponent]).execute_entities():
            existing = (
                character.get_component(MentalStateComponent)
                if character.has_component(MentalStateComponent)
                else MentalStateComponent()
            )
            if existing.expires_at_epoch is not None and epoch >= existing.expires_at_epoch:
                updated = MentalStateComponent()
            else:
                updated = existing
            crisis_needs = [
                component_type.__name__.removesuffix("Component")
                for component_type in need_types
                if character.has_component(component_type)
                and band(character.get_component(component_type).meter) == "crisis"
            ]
            if crisis_needs and existing.state != "mental_break":
                updated = MentalStateComponent(
                    state="mental_break",
                    reason="low " + ", ".join(sorted(crisis_needs)),
                    expires_at_epoch=epoch + 2 * SECONDS_PER_HOUR,
                )
            elif (
                not crisis_needs
                and character.has_component(AffectComponent)
                and character.get_component(AffectComponent).current.valence >= 15
                and existing.state == "stable"
            ):
                updated = MentalStateComponent(
                    state="inspired",
                    reason="high mood",
                    expires_at_epoch=epoch + 4 * SECONDS_PER_HOUR,
                )
            if updated != existing:
                replace_component(character, updated)
                events.append(
                    MentalStateChangedEvent(
                        **_event_base(
                            epoch,
                            visibility=EventVisibility.PRIVATE,
                            actor_id=str(character.id),
                            target_ids=(str(character.id),),
                            state=updated.state,
                            reason=updated.reason,
                        )
                    )
                )
        return events


def ensure_colonysim_marker(actor) -> ColonySimComponent:
    for entity in actor.world.query().with_all([ColonySimComponent]).execute_entities():
        return entity.get_component(ColonySimComponent)
    entity = spawn_entity(actor.world, [ColonySimComponent()])
    return entity.get_component(ColonySimComponent)


def install_colonysim(actor) -> None:
    ensure_colonysim_marker(actor)
    actor.register_consequence(RoomQualityConsequence())
    actor.register_consequence(ColonyWealthConsequence())
    actor.register_consequence(MedicalRecoveryConsequence())
    actor.register_consequence(MentalStateConsequence())


def _reservation_holder(entity: Entity) -> EntityId | None:
    reservations = entity.get_relationships(ReservedBy)
    return reservations[0][1] if reservations else None


def _assignment_holder(entity: Entity) -> EntityId | None:
    assignments = entity.get_relationships(AssignedTo)
    return assignments[0][1] if assignments else None


def _reserved_by_other(entity: Entity, character_id: EntityId) -> bool:
    holder = _reservation_holder(entity)
    return holder is not None and holder != character_id


def _assigned_by_other(entity: Entity, character_id: EntityId) -> bool:
    holder = _assignment_holder(entity)
    return holder is not None and holder != character_id


def _owner(entity: Entity) -> EntityId | None:
    owners = entity.get_incoming_relationships(Owns)
    return owners[0][0] if owners else None


def _same_room_or_self(world: World, left_id: EntityId, right_id: EntityId) -> bool:
    return left_id == right_id or container_of(world.get_entity(left_id)) == container_of(
        world.get_entity(right_id)
    )


def _resource_name(resource_type: str, quantity: int) -> str:
    return f"{resource_type} x{quantity}"


def _parse_types(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        values = raw.split(",")
    elif isinstance(raw, (list, tuple, set)):
        values = raw
    else:
        values = (raw,)
    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))


def _stack_in_inventory(character: Entity, world: World, resource_type: str) -> Entity | None:
    for item_id in contents(character):
        item = world.get_entity(item_id)
        if (
            item.has_component(ResourceStackComponent)
            and item.get_component(ResourceStackComponent).resource_type == resource_type
        ):
            return item
    return None


def _add_resource_stack(character: Entity, world: World, resource_type: str, quantity: int) -> str:
    existing = _stack_in_inventory(character, world, resource_type)
    if existing is not None:
        stack = existing.get_component(ResourceStackComponent)
        updated = replace(stack, quantity=stack.quantity + quantity)
        replace_component(existing, updated)
        replace_component(
            existing,
            IdentityComponent(
                name=_resource_name(resource_type, updated.quantity),
                kind="resource",
            ),
        )
        return str(existing.id)

    item = spawn_entity(
        world,
        [
            IdentityComponent(name=_resource_name(resource_type, quantity), kind="resource"),
            ResourceStackComponent(resource_type=resource_type, quantity=quantity),
            PortableComponent(can_pick_up=True),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)
    return str(item.id)


def _consume_resource_stack(
    character: Entity, world: World, resource_type: str, quantity: int
) -> bool:
    item = _stack_in_inventory(character, world, resource_type)
    if item is None:
        return False
    stack = item.get_component(ResourceStackComponent)
    if stack.quantity < quantity:
        return False
    remaining = stack.quantity - quantity
    if remaining == 0:
        character.remove_relationship(Contains, item.id)
    else:
        replace_component(item, replace(stack, quantity=remaining))
        replace_component(
            item,
            IdentityComponent(name=_resource_name(resource_type, remaining), kind="resource"),
        )
    return True


def _consume_medicine_use(ctx: HandlerContext, medicine_id: EntityId) -> None:
    medicine_entity = ctx.entity(medicine_id)
    medicine = medicine_entity.get_component(MedicineComponent)
    remaining = medicine.uses - 1
    if remaining <= 0:
        holder = container_of(medicine_entity)
        if holder is not None:
            ctx.entity(holder).remove_relationship(Contains, medicine_id)
        ctx.world.remove(medicine_id)
    else:
        replace_component(medicine_entity, replace(medicine, uses=remaining))


def _move_entity(world: World, entity_id: EntityId, target_id: EntityId) -> None:
    current_container_id = container_of(world.get_entity(entity_id))
    if current_container_id is not None:
        world.get_entity(current_container_id).remove_relationship(Contains, entity_id)
    world.get_entity(target_id).add_relationship(
        Contains(mode=ContainmentMode.CONTAINER), entity_id
    )


def _stockpile_load(world: World, stockpile: Entity) -> int:
    load = 0
    for item_id in contents(stockpile):
        item = world.get_entity(item_id)
        if item.has_component(ResourceStackComponent):
            load += item.get_component(ResourceStackComponent).quantity
        else:
            load += 1
    return load


def _stockpile_accepts(stockpile: Entity, item: Entity) -> bool:
    if not stockpile.has_component(StorageFilterComponent):
        return True
    allowed = stockpile.get_component(StorageFilterComponent).allowed_types
    if not allowed:
        return True
    if not item.has_component(ResourceStackComponent):
        return False
    return item.get_component(ResourceStackComponent).resource_type in allowed


def _find_recipe(world: World, recipe_id: str) -> tuple[EntityId, RecipeComponent] | None:
    for entity in world.query().with_all([RecipeComponent]).execute_entities():
        recipe = entity.get_component(RecipeComponent)
        if recipe.recipe_id == recipe_id:
            return entity.id, recipe
    return None


def _faction_relation(world: World, faction_id: str) -> Entity:
    for entity in world.query().with_all([FactionRelationComponent]).execute_entities():
        relation = entity.get_component(FactionRelationComponent)
        if relation.faction_id == faction_id:
            return entity
    return spawn_entity(world, [FactionRelationComponent(faction_id=faction_id)])


def _body_part_entity(world: World, patient: Entity, part_name: str) -> Entity | None:
    for _edge, part_id in patient.get_relationships(HasBodyPart):
        # Relics cascades inbound edge removal, so a related id is always live here.
        body_part = world.get_entity(part_id)
        if (
            body_part.has_component(BodyPartHealthComponent)
            and body_part.get_component(BodyPartHealthComponent).part == part_name
        ):
            return body_part
    return None


def _has_station(world: World, character: Entity, station_type: str) -> bool:
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        if (
            entity.has_component(WorkstationComponent)
            and entity.get_component(WorkstationComponent).station_type == station_type
        ):
            return True
    return False


def _spawn_recipe_entity(
    character: Entity,
    world: World,
    resource_type: str,
    quantity: int,
    metadata: dict[str, object],
) -> str:
    display_name = str(metadata.get("display_name") or _resource_name(resource_type, quantity))
    kind = str(metadata.get("entity_kind") or metadata.get("kind") or "item")
    portable = bool(metadata.get("portable", True))
    uses = int(metadata.get("uses", quantity))
    components: list[Component] = [
        IdentityComponent(name=display_name, kind=kind, tags=(resource_type,)),
        ResourceStackComponent(resource_type=resource_type, quantity=quantity),
    ]
    if portable:
        components.append(PortableComponent(can_pick_up=True))
    if "satiety" in metadata or "nutrition" in metadata:
        components.append(
            FoodComponent(
                nutrition=float(metadata.get("nutrition", 0.0)),
                satiety=float(metadata.get("satiety", 0.0)),
                raw=bool(metadata.get("raw", False)),
                spoiled=bool(metadata.get("spoiled", False)),
            )
        )
    if "hydration" in metadata:
        components.append(
            DrinkableComponent(
                hydration=float(metadata.get("hydration", 0.0)),
                purity=float(metadata.get("purity", 1.0)),
            )
        )
    if uses > 0:
        components.append(ConsumableComponent(current_uses=uses, max_uses=uses))
    item = spawn_entity(world, components)
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)
    return str(item.id)


def _create_recipe_outputs(
    character: Entity, world: World, recipe: RecipeComponent
) -> tuple[str, ...]:
    output_ids: list[str] = []
    for resource_type, quantity in recipe.outputs.items():
        metadata = recipe.output_entities.get(resource_type)
        if metadata:
            output_ids.append(
                _spawn_recipe_entity(character, world, resource_type, quantity, metadata)
            )
        else:
            output_ids.append(_add_resource_stack(character, world, resource_type, quantity))
    return tuple(output_ids)


class SetWorkPriorityHandler:
    command_type = "set-work-priority"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        work_type = str(command.payload.get("work_type", "")).strip()
        priority = int(command.payload.get("priority", 0))
        if character_id is None:
            return rejected("invalid character id")
        if not work_type:
            return rejected("missing work type")
        if priority < 0 or priority > 4:
            return rejected("priority must be between 0 and 4")
        character = ctx.entity(character_id)
        existing = (
            character.get_component(WorkPriorityComponent)
            if character.has_component(WorkPriorityComponent)
            else WorkPriorityComponent()
        )
        priorities = dict(existing.priorities)
        if priority == 0:
            priorities.pop(work_type, None)
        else:
            priorities[work_type] = priority
        replace_component(character, WorkPriorityComponent(priorities=priorities))
        return ok(
            WorkPrioritySetEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    work_type=work_type,
                    priority=priority,
                )
            )
        )


class SetAllowedAreaHandler:
    command_type = "set-allowed-area"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        raw = command.payload.get("room_ids")
        room_ids = _parse_types(raw)
        for room_id_str in room_ids:
            room_id = parse_entity_id(room_id_str)
            if room_id is None or not ctx.world.has_entity(room_id):
                return rejected("room does not exist")
            if not ctx.entity(room_id).has_component(RoomComponent):
                return rejected("target is not a room")
        character = ctx.entity(character_id)
        for _edge, room_id in character.get_relationships(AllowedIn):
            character.remove_relationship(AllowedIn, room_id)
        for room_id_str in room_ids:
            room_id = parse_entity_id(room_id_str)
            assert room_id is not None
            character.add_relationship(AllowedIn(), room_id)
        return ok(
            AllowedAreaSetEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_ids=room_ids,
                )
            )
        )


class TendWoundHandler:
    command_type = "tend-wound"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        doctor_id = parse_entity_id(command.character_id)
        patient_id = parse_entity_id(command.payload.get("patient_id"))
        injury_id = parse_entity_id(command.payload.get("injury_id"))
        medicine_id = parse_entity_id(command.payload.get("medicine_id"))
        if doctor_id is None or patient_id is None or injury_id is None:
            return rejected("invalid doctor, patient, or injury id")
        if not ctx.world.has_entity(patient_id) or not ctx.world.has_entity(injury_id):
            return rejected("patient or injury does not exist")
        doctor = ctx.entity(doctor_id)
        if patient_id not in reachable_ids(ctx.world, doctor) and patient_id != doctor_id:
            return rejected("patient is not reachable")
        patient = ctx.entity(patient_id)
        if not patient.has_relationship(HasInjury, injury_id):
            return rejected("injury does not belong to patient")
        injury_entity = ctx.entity(injury_id)
        if not injury_entity.has_component(InjuryComponent):
            return rejected("target is not an injury")
        quality = 0.5
        if medicine_id is not None:
            if not ctx.world.has_entity(medicine_id):
                return rejected("medicine does not exist")
            if medicine_id not in reachable_ids(ctx.world, doctor):
                return rejected("medicine is not reachable")
            medicine_entity = ctx.entity(medicine_id)
            if not medicine_entity.has_component(MedicineComponent):
                return rejected("target is not medicine")
            quality = medicine_entity.get_component(MedicineComponent).quality
        injury = injury_entity.get_component(InjuryComponent)
        replace_component(
            injury_entity,
            replace(
                injury,
                treated=True,
                pain=max(0.0, injury.pain * (1.0 - min(1.0, quality))),
                bleeding_rate=max(0.0, injury.bleeding_rate * (1.0 - min(1.0, quality))),
            ),
        )
        if medicine_id is not None:
            _consume_medicine_use(ctx, medicine_id)
        if patient.has_component(BleedingComponent):
            bleeding = patient.get_component(BleedingComponent)
            replace_component(patient, replace(bleeding, rate=0.0, last_updated_epoch=ctx.epoch))
        return ok(
            WoundTendedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(doctor_id),
                    room_id=_room_id(ctx.world, doctor_id),
                    target_ids=(str(patient_id), str(injury_id)),
                    patient_id=str(patient_id),
                    injury_id=str(injury_id),
                    medicine_id=str(medicine_id) if medicine_id is not None else None,
                    quality=quality,
                )
            )
        )


class RescueToBedHandler:
    command_type = "rescue-to-bed"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        rescuer_id = parse_entity_id(command.character_id)
        patient_id = parse_entity_id(command.payload.get("patient_id"))
        bed_id = parse_entity_id(command.payload.get("bed_id"))
        if rescuer_id is None or patient_id is None or bed_id is None:
            return rejected("invalid rescuer, patient, or bed id")
        if not ctx.world.has_entity(patient_id) or not ctx.world.has_entity(bed_id):
            return rejected("patient or bed does not exist")
        rescuer = ctx.entity(rescuer_id)
        reachable = reachable_ids(ctx.world, rescuer)
        if patient_id not in reachable:
            return rejected("patient is not reachable")
        if bed_id not in reachable:
            return rejected("bed is not reachable")
        patient = ctx.entity(patient_id)
        bed = ctx.entity(bed_id)
        if not patient.has_component(CharacterComponent):
            return rejected("patient is not a character")
        if not patient.has_component(DownedComponent):
            return rejected("patient does not need rescue")
        if not bed.has_component(MedicalBedComponent):
            return rejected("target is not a medical bed")
        # A reachable bed is always inventory- or room-contained.
        bed_room = container_of(bed)
        # A reachable patient is always inventory- or room-contained.
        old_room = container_of(patient)
        ctx.entity(old_room).remove_relationship(Contains, patient_id)
        ctx.entity(bed_room).add_relationship(
            Contains(mode=ContainmentMode.ROOM_CONTENT), patient_id
        )
        replace_component(patient, BedRestComponent(started_at_epoch=ctx.epoch, bed_id=str(bed_id)))
        if not patient.has_component(SleepingComponent):
            patient.add_component(SleepingComponent(started_at_epoch=ctx.epoch))
        return ok(
            CharacterRescuedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(rescuer_id),
                    room_id=str(bed_room),
                    target_ids=(str(patient_id), str(bed_id)),
                    patient_id=str(patient_id),
                    bed_id=str(bed_id),
                )
            )
        )


class CreateStockpileHandler:
    command_type = "create-stockpile"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        character = ctx.entity(character_id)
        room_id = container_of(character)
        if room_id is None:
            return rejected("character is not in a room")
        name = str(command.payload.get("name", "Stockpile")).strip() or "Stockpile"
        capacity = int(command.payload.get("capacity", 20))
        if capacity <= 0:
            return rejected("capacity must be positive")
        stockpile = spawn_entity(
            ctx.world,
            [
                IdentityComponent(name=name, kind="stockpile"),
                StockpileComponent(capacity=capacity),
                StorageFilterComponent(
                    allowed_types=_parse_types(command.payload.get("allowed_types"))
                ),
            ],
        )
        ctx.entity(room_id).add_relationship(
            Contains(mode=ContainmentMode.ROOM_CONTENT), stockpile.id
        )
        return ok(
            StockpileCreatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=str(room_id),
                    target_ids=(str(stockpile.id),),
                    stockpile_id=str(stockpile.id),
                    capacity=capacity,
                )
            )
        )


class SetStorageFilterHandler:
    command_type = "set-storage-filter"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        stockpile_id = parse_entity_id(command.payload.get("stockpile_id"))
        if character_id is None or stockpile_id is None:
            return rejected("invalid character or stockpile id")
        if not ctx.world.has_entity(stockpile_id):
            return rejected("stockpile does not exist")
        character = ctx.entity(character_id)
        if stockpile_id not in reachable_ids(ctx.world, character):
            return rejected("stockpile is not reachable")
        stockpile = ctx.entity(stockpile_id)
        if not stockpile.has_component(StockpileComponent):
            return rejected("target is not a stockpile")
        allowed_types = _parse_types(command.payload.get("allowed_types"))
        replace_component(stockpile, StorageFilterComponent(allowed_types=allowed_types))
        return ok(
            StorageFilterChangedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(stockpile_id),),
                    stockpile_id=str(stockpile_id),
                    allowed_types=allowed_types,
                )
            )
        )


class ForbidItemHandler:
    command_type = "forbid-item"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        item_id = parse_entity_id(command.payload.get("item_id"))
        if character_id is None or item_id is None:
            return rejected("invalid character or item id")
        if not ctx.world.has_entity(item_id):
            return rejected("item does not exist")
        character = ctx.entity(character_id)
        if item_id not in reachable_ids(ctx.world, character):
            return rejected("item is not reachable")
        item = ctx.entity(item_id)
        replace_component(item, ForbiddenComponent(forbidden=True))
        return ok(
            ItemForbiddenEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(item_id),),
                    item_id=str(item_id),
                    forbidden=True,
                )
            )
        )


class AllowItemHandler:
    command_type = "allow-item"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        item_id = parse_entity_id(command.payload.get("item_id"))
        if character_id is None or item_id is None:
            return rejected("invalid character or item id")
        if not ctx.world.has_entity(item_id):
            return rejected("item does not exist")
        character = ctx.entity(character_id)
        if item_id not in reachable_ids(ctx.world, character):
            return rejected("item is not reachable")
        item = ctx.entity(item_id)
        if not item.has_component(ForbiddenComponent):
            return rejected("item is not forbidden")
        item.remove_component(ForbiddenComponent)
        return ok(
            ItemForbiddenEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(item_id),),
                    item_id=str(item_id),
                    forbidden=False,
                )
            )
        )


class HaulItemHandler:
    command_type = "haul-item"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        item_id = parse_entity_id(command.payload.get("item_id"))
        target_id = parse_entity_id(command.payload.get("target_container_id"))
        if character_id is None or item_id is None or target_id is None:
            return rejected("invalid character, item, or target container id")
        if not ctx.world.has_entity(item_id):
            return rejected("item does not exist")
        if not ctx.world.has_entity(target_id):
            return rejected("target container does not exist")
        character = ctx.entity(character_id)
        reachable = reachable_ids(ctx.world, character)
        if item_id not in reachable:
            return rejected("item is not reachable")
        if target_id not in reachable:
            return rejected("target container is not reachable")
        if item_id == target_id:
            return rejected("item cannot contain itself")
        item = ctx.entity(item_id)
        if item.has_component(ForbiddenComponent):
            return rejected("item is forbidden")
        target = ctx.entity(target_id)
        if target.has_component(StockpileComponent):
            stockpile = target.get_component(StockpileComponent)
            if not _stockpile_accepts(target, item):
                return rejected("item does not match storage filter")
            item_load = (
                item.get_component(ResourceStackComponent).quantity
                if item.has_component(ResourceStackComponent)
                else 1
            )
            if _stockpile_load(ctx.world, target) + item_load > stockpile.capacity:
                return rejected("stockpile is full")
        _move_entity(ctx.world, item_id, target_id)
        return ok(
            ItemHauledEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(item_id), str(target_id)),
                    item_id=str(item_id),
                    target_container_id=str(target_id),
                )
            )
        )


class SplitStackHandler:
    command_type = "split-stack"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        item_id = parse_entity_id(command.payload.get("item_id"))
        quantity = int(command.payload.get("quantity", 1))
        if character_id is None or item_id is None:
            return rejected("invalid character or item id")
        if quantity <= 0:
            return rejected("quantity must be positive")
        if not ctx.world.has_entity(item_id):
            return rejected("stack does not exist")
        character = ctx.entity(character_id)
        if item_id not in reachable_ids(ctx.world, character):
            return rejected("stack is not reachable")
        item = ctx.entity(item_id)
        if not item.has_component(ResourceStackComponent):
            return rejected("target is not a resource stack")
        stack = item.get_component(ResourceStackComponent)
        if stack.quantity <= quantity:
            return rejected("quantity must be smaller than stack")
        remaining = stack.quantity - quantity
        replace_component(item, replace(stack, quantity=remaining))
        replace_component(
            item,
            IdentityComponent(name=_resource_name(stack.resource_type, remaining), kind="resource"),
        )
        new_stack = spawn_entity(
            ctx.world,
            [
                IdentityComponent(
                    name=_resource_name(stack.resource_type, quantity), kind="resource"
                ),
                ResourceStackComponent(resource_type=stack.resource_type, quantity=quantity),
                PortableComponent(can_pick_up=True),
                HaulableComponent(),
            ],
        )
        # A reachable, validated stack is always inventory- or room-contained.
        container_id = container_of(item)
        ctx.entity(container_id).add_relationship(
            Contains(mode=ContainmentMode.CONTAINER), new_stack.id
        )
        return ok(
            StackSplitEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(item_id), str(new_stack.id)),
                    source_stack_id=str(item_id),
                    new_stack_id=str(new_stack.id),
                    quantity=quantity,
                )
            )
        )


class MergeStackHandler:
    command_type = "merge-stack"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        source_id = parse_entity_id(command.payload.get("source_id"))
        target_id = parse_entity_id(command.payload.get("target_id"))
        if character_id is None or source_id is None or target_id is None:
            return rejected("invalid character, source, or target id")
        if source_id == target_id:
            return rejected("source and target must differ")
        if not ctx.world.has_entity(source_id):
            return rejected("source stack does not exist")
        if not ctx.world.has_entity(target_id):
            return rejected("target stack does not exist")
        character = ctx.entity(character_id)
        reachable = reachable_ids(ctx.world, character)
        if source_id not in reachable or target_id not in reachable:
            return rejected("stacks are not reachable")
        source = ctx.entity(source_id)
        target = ctx.entity(target_id)
        if not source.has_component(ResourceStackComponent) or not target.has_component(
            ResourceStackComponent
        ):
            return rejected("both targets must be resource stacks")
        source_stack = source.get_component(ResourceStackComponent)
        target_stack = target.get_component(ResourceStackComponent)
        if source_stack.resource_type != target_stack.resource_type:
            return rejected("resource types do not match")
        merged_quantity = target_stack.quantity + source_stack.quantity
        replace_component(target, replace(target_stack, quantity=merged_quantity))
        replace_component(
            target,
            IdentityComponent(
                name=_resource_name(target_stack.resource_type, merged_quantity),
                kind="resource",
            ),
        )
        # A reachable, validated source stack is always inventory- or room-contained.
        container_id = container_of(source)
        ctx.entity(container_id).remove_relationship(Contains, source_id)
        return ok(
            StackMergedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(source_id), str(target_id)),
                    source_stack_id=str(source_id),
                    target_stack_id=str(target_id),
                    quantity=source_stack.quantity,
                )
            )
        )


class ReserveHandler:
    command_type = "reserve"

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
        if _reserved_by_other(target, character_id):
            return rejected("target is reserved")
        if target.has_relationship(ReservedBy, character_id):
            return rejected("already reserved")

        target.add_relationship(ReservedBy(since_epoch=ctx.epoch), character_id)
        return ok(
            ReservationCreatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                )
            )
        )


class ReleaseReservationHandler:
    command_type = "release-reservation"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if character_id is None or target_id is None:
            return rejected("invalid character or target id")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")

        target = ctx.entity(target_id)
        if not target.has_relationship(ReservedBy, character_id):
            return rejected("not reserved by you")
        target.remove_relationship(ReservedBy, character_id)
        return ok(
            ReservationReleasedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                )
            )
        )


class GatherResourceHandler:
    command_type = "gather-resource"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        node_id = parse_entity_id(command.payload.get("node_id"))
        quantity = int(command.payload.get("quantity", 1))
        if character_id is None or node_id is None:
            return rejected("invalid character or resource node id")
        if quantity <= 0:
            return rejected("quantity must be positive")
        if not ctx.world.has_entity(node_id):
            return rejected("resource node does not exist")

        character = ctx.entity(character_id)
        if node_id not in reachable_ids(ctx.world, character):
            return rejected("resource node is not reachable")
        node = ctx.entity(node_id)
        if not node.has_component(ResourceNodeComponent):
            return rejected("target is not a resource node")
        if _reserved_by_other(node, character_id):
            return rejected("resource node is reserved")

        resource = node.get_component(ResourceNodeComponent)
        if resource.current < quantity:
            return rejected("not enough resource")
        replace_component(node, replace(resource, current=resource.current - quantity))
        stack_id = _add_resource_stack(character, ctx.world, resource.resource_type, quantity)
        return ok(
            ResourceGatheredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(node_id), stack_id),
                    node_id=str(node_id),
                    resource_type=resource.resource_type,
                    quantity=quantity,
                    stack_id=stack_id,
                )
            )
        )


class CraftHandler:
    command_type = "craft"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        recipe_id = str(command.payload.get("recipe_id", "")).strip()
        if character_id is None:
            return rejected("invalid character id")
        if not recipe_id:
            return rejected("missing recipe id")

        recipe_result = _find_recipe(ctx.world, recipe_id)
        if recipe_result is None:
            return rejected("recipe does not exist")
        _recipe_entity_id, recipe = recipe_result
        character = ctx.entity(character_id)
        if recipe.required_station and not _has_station(
            ctx.world, character, recipe.required_station
        ):
            return rejected("required workstation is not reachable")
        for resource_type, quantity in recipe.inputs.items():
            stack = _stack_in_inventory(character, ctx.world, resource_type)
            if stack is None or stack.get_component(ResourceStackComponent).quantity < quantity:
                return rejected("missing recipe inputs")

        for resource_type, quantity in recipe.inputs.items():
            _consume_resource_stack(character, ctx.world, resource_type, quantity)
        output_ids = _create_recipe_outputs(character, ctx.world, recipe)
        return ok(
            ItemCraftedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=output_ids,
                    recipe_id=recipe.recipe_id,
                    output_ids=output_ids,
                )
            )
        )


class BakeHandler(CraftHandler):
    command_type = "bake"


class AssignJobHandler:
    command_type = "assign-job"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        job_id = parse_entity_id(command.payload.get("job_id"))
        if character_id is None or job_id is None:
            return rejected("invalid character or job id")
        if not ctx.world.has_entity(job_id):
            return rejected("job does not exist")

        character = ctx.entity(character_id)
        job_entity = ctx.entity(job_id)
        if job_id not in reachable_ids(ctx.world, character):
            return rejected("job is not reachable")
        if not job_entity.has_component(JobComponent):
            return rejected("target is not a job")
        job = job_entity.get_component(JobComponent)
        if job.completed:
            return rejected("job is already complete")
        if _assigned_by_other(job_entity, character_id):
            return rejected("job is assigned")
        if job_entity.has_relationship(AssignedTo, character_id):
            return rejected("job already assigned to you")

        replace_component(job_entity, replace(job, assigned=True))
        job_entity.add_relationship(AssignedTo(since_epoch=ctx.epoch), character_id)
        return ok(
            JobAssignedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(job_id),),
                    job_id=str(job_id),
                )
            )
        )


class CompleteJobHandler:
    command_type = "complete-job"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        job_id = parse_entity_id(command.payload.get("job_id"))
        if character_id is None or job_id is None:
            return rejected("invalid character or job id")
        if not ctx.world.has_entity(job_id):
            return rejected("job does not exist")

        job_entity = ctx.entity(job_id)
        if not job_entity.has_component(JobComponent):
            return rejected("target is not a job")
        if not job_entity.has_relationship(AssignedTo, character_id):
            return rejected("job is not assigned to you")

        job = job_entity.get_component(JobComponent)
        replace_component(job_entity, replace(job, assigned=False, completed=True))
        job_entity.remove_relationship(AssignedTo, character_id)
        return ok(
            JobCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(job_id),),
                    job_id=str(job_id),
                )
            )
        )


class UpdatePawnProfileHandler:
    command_type = "update-pawn-profile"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        raw_passions = command.payload.get("passions", {})
        if not isinstance(raw_passions, dict):
            return rejected("passions must be a mapping")
        passions = {str(key): int(value) for key, value in raw_passions.items()}
        backstory = str(command.payload.get("backstory", "")).strip()
        expectations = str(command.payload.get("expectations", "low")).strip() or "low"
        replace_component(
            ctx.entity(character_id),
            PawnProfileComponent(
                backstory=backstory,
                passions=passions,
                expectations=expectations,
            ),
        )
        return ok(
            PawnProfileUpdatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    backstory=backstory,
                    expectations=expectations,
                )
            )
        )


class ProgressJobBillHandler:
    command_type = "progress-job-bill"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        bill_id = parse_entity_id(command.payload.get("bill_id"))
        work = float(command.payload.get("work", 1.0))
        if character_id is None or bill_id is None:
            return rejected("invalid character or bill id")
        if work <= 0:
            return rejected("work must be positive")
        if not ctx.world.has_entity(bill_id):
            return rejected("job bill does not exist")
        character = ctx.entity(character_id)
        if bill_id not in reachable_ids(ctx.world, character):
            return rejected("job bill is not reachable")
        bill_entity = ctx.entity(bill_id)
        if not bill_entity.has_component(JobBillComponent):
            return rejected("target is not a job bill")
        bill = bill_entity.get_component(JobBillComponent)
        if bill.suspended:
            return rejected("job bill is suspended")
        if bill.work_done >= bill.work_required:
            return rejected("job bill is already complete")
        done = min(bill.work_required, bill.work_done + work)
        completed = done >= bill.work_required
        replace_component(bill_entity, replace(bill, work_done=done))
        if completed and bill_entity.has_component(JobComponent):
            job = bill_entity.get_component(JobComponent)
            replace_component(bill_entity, replace(job, completed=True, assigned=False))
        return ok(
            JobBillProgressedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(bill_id),),
                    bill_id=str(bill_id),
                    work_done=done,
                    completed=completed,
                )
            )
        )


class SetPrisonerPolicyHandler:
    command_type = "set-prisoner-policy"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        prisoner_id = parse_entity_id(command.payload.get("prisoner_id"))
        policy = str(command.payload.get("policy", "")).strip().lower()
        if character_id is None or prisoner_id is None:
            return rejected("invalid character or prisoner id")
        if policy not in {"hold", "recruit", "release"}:
            return rejected("prisoner policy is required")
        if not ctx.world.has_entity(prisoner_id):
            return rejected("prisoner does not exist")
        prisoner = ctx.entity(prisoner_id)
        if not prisoner.has_component(PrisonerComponent):
            return rejected("target is not a prisoner")
        component = prisoner.get_component(PrisonerComponent)
        replace_component(prisoner, replace(component, policy=policy))
        return ok(
            PrisonerPolicySetEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    target_ids=(str(prisoner_id),),
                    prisoner_id=str(prisoner_id),
                    policy=policy,
                )
            )
        )


class RecruitPrisonerHandler:
    command_type = "recruit-prisoner"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        prisoner_id = parse_entity_id(command.payload.get("prisoner_id"))
        progress = float(command.payload.get("progress", 1.0))
        if character_id is None or prisoner_id is None:
            return rejected("invalid character or prisoner id")
        if progress <= 0:
            return rejected("progress must be positive")
        if not ctx.world.has_entity(prisoner_id):
            return rejected("prisoner does not exist")
        if not _same_room_or_self(ctx.world, character_id, prisoner_id):
            return rejected("prisoner is not present")
        prisoner = ctx.entity(prisoner_id)
        if not prisoner.has_component(PrisonerComponent):
            return rejected("target is not a prisoner")
        component = prisoner.get_component(PrisonerComponent)
        if component.policy != "recruit":
            return rejected("prisoner is not set for recruitment")
        total = component.recruitment_progress + progress
        recruited = total >= component.recruitment_difficulty
        if recruited:
            prisoner.remove_component(PrisonerComponent)
        else:
            replace_component(prisoner, replace(component, recruitment_progress=total))
        return ok(
            RecruitmentProgressedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(prisoner_id),),
                    prisoner_id=str(prisoner_id),
                    progress=total,
                    recruited=recruited,
                )
            )
        )


class ResearchProjectHandler:
    command_type = "research-project"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        project_id = parse_entity_id(command.payload.get("project_id"))
        work = float(command.payload.get("work", 1.0))
        if character_id is None or project_id is None:
            return rejected("invalid character or research project id")
        if work <= 0:
            return rejected("work must be positive")
        if not ctx.world.has_entity(project_id):
            return rejected("research project does not exist")
        project_entity = ctx.entity(project_id)
        if not project_entity.has_component(ResearchProjectComponent):
            return rejected("target is not a research project")
        project = project_entity.get_component(ResearchProjectComponent)
        if project.unlocked:
            return rejected("research project is already unlocked")
        done = min(project.work_required, project.work_done + work)
        unlocked = done >= project.work_required
        replace_component(project_entity, replace(project, work_done=done, unlocked=unlocked))
        events: list[DomainEvent] = [
            ResearchProgressedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    target_ids=(str(project_id),),
                    project_id=project.project_id,
                    work_done=done,
                    unlocked=unlocked,
                )
            )
        ]
        if unlocked:
            replace_component(
                project_entity,
                TechUnlockComponent(tech_id=project.project_id, unlocked_at_epoch=ctx.epoch),
            )
            events.append(
                TechUnlockedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.SYSTEM,
                        actor_id=str(character_id),
                        target_ids=(str(project_id),),
                        project_id=project.project_id,
                        tech_id=project.project_id,
                    )
                )
            )
        return ok(*events)


class ResolveColonyIncidentHandler:
    command_type = "resolve-colony-incident"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        incident_id = parse_entity_id(command.payload.get("incident_id"))
        if character_id is None or incident_id is None:
            return rejected("invalid character or incident id")
        if not ctx.world.has_entity(incident_id):
            return rejected("incident does not exist")
        incident_entity = ctx.entity(incident_id)
        if not incident_entity.has_component(ColonyIncidentComponent):
            return rejected("target is not an incident")
        incident = incident_entity.get_component(ColonyIncidentComponent)
        if incident.resolved:
            return rejected("incident is already resolved")
        replace_component(incident_entity, replace(incident, resolved=True))
        return ok(
            ColonyIncidentResolvedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.SYSTEM,
                    actor_id=str(character_id),
                    target_ids=(str(incident_id),),
                    incident_id=str(incident_id),
                    incident_type=incident.incident_type,
                )
            )
        )


class CompleteTradeHandler:
    command_type = "complete-trade"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        offer_id = parse_entity_id(command.payload.get("offer_id"))
        if character_id is None or offer_id is None:
            return rejected("invalid character or trade offer id")
        if not ctx.world.has_entity(offer_id):
            return rejected("trade offer does not exist")
        character = ctx.entity(character_id)
        offer_entity = ctx.entity(offer_id)
        if not offer_entity.has_component(TradeOfferComponent):
            return rejected("target is not a trade offer")
        offer = offer_entity.get_component(TradeOfferComponent)
        for resource_type, quantity in offer.wants.items():
            stack = _stack_in_inventory(character, ctx.world, resource_type)
            if stack is None or stack.get_component(ResourceStackComponent).quantity < quantity:
                return rejected("missing trade goods")
        for resource_type, quantity in offer.wants.items():
            _consume_resource_stack(character, ctx.world, resource_type, quantity)
        for resource_type, quantity in offer.gives.items():
            _add_resource_stack(character, ctx.world, resource_type, quantity)
        relation = _faction_relation(ctx.world, offer.faction_id)
        goodwill = relation.get_component(FactionRelationComponent).goodwill + offer.goodwill_delta
        replace_component(
            relation,
            FactionRelationComponent(faction_id=offer.faction_id, goodwill=goodwill),
        )
        return ok(
            TradeCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(offer_id),),
                    offer_id=str(offer_id),
                    faction_id=offer.faction_id,
                    goodwill=goodwill,
                )
            )
        )


class FormCaravanHandler:
    command_type = "form-caravan"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        destination = str(command.payload.get("destination", "")).strip()
        if not destination:
            return rejected("destination is required")
        raw_cargo = command.payload.get("cargo", {})
        if not isinstance(raw_cargo, dict):
            return rejected("cargo must be a mapping")
        character = ctx.entity(character_id)
        cargo = {str(key): int(value) for key, value in raw_cargo.items()}
        for resource_type, quantity in cargo.items():
            if quantity < 0:
                return rejected("cargo quantities must not be negative")
            stack = _stack_in_inventory(character, ctx.world, resource_type)
            if quantity and (
                stack is None or stack.get_component(ResourceStackComponent).quantity < quantity
            ):
                return rejected("missing caravan cargo")
        for resource_type, quantity in cargo.items():
            if quantity:
                _consume_resource_stack(character, ctx.world, resource_type, quantity)
        member_ids = tuple(
            sorted({str(character_id), *_parse_types(command.payload.get("member_ids"))})
        )
        parsed_member_ids: list[EntityId] = []
        for member_id in member_ids:
            parsed = parse_entity_id(member_id)
            if parsed is None or not ctx.world.has_entity(parsed):
                return rejected("caravan member does not exist")
            parsed_member_ids.append(parsed)
        caravan = spawn_entity(
            ctx.world,
            [
                IdentityComponent(name=f"caravan to {destination}", kind="caravan"),
                CaravanComponent(
                    destination=destination,
                    cargo=cargo,
                    departed_at_epoch=ctx.epoch,
                ),
            ],
        )
        for member_id in parsed_member_ids:
            ctx.entity(member_id).add_relationship(MemberOfCaravan(), caravan.id)
        return ok(
            CaravanFormedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.SYSTEM,
                    actor_id=str(character_id),
                    target_ids=(str(caravan.id),),
                    caravan_id=str(caravan.id),
                    destination=destination,
                )
            )
        )


class PerformSurgeryHandler:
    command_type = "perform-surgery"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        doctor_id = parse_entity_id(command.character_id)
        patient_id = parse_entity_id(command.payload.get("patient_id"))
        surgery_id = parse_entity_id(command.payload.get("surgery_id"))
        if doctor_id is None or patient_id is None or surgery_id is None:
            return rejected("invalid doctor, patient, or surgery id")
        if not ctx.world.has_entity(patient_id) or not ctx.world.has_entity(surgery_id):
            return rejected("patient or surgery does not exist")
        doctor = ctx.entity(doctor_id)
        if patient_id not in reachable_ids(ctx.world, doctor) and patient_id != doctor_id:
            return rejected("patient is not reachable")
        surgery_entity = ctx.entity(surgery_id)
        if not surgery_entity.has_component(SurgeryBillComponent):
            return rejected("target is not a surgery bill")
        surgery = surgery_entity.get_component(SurgeryBillComponent)
        if surgery.completed:
            return rejected("surgery is already complete")
        patient = ctx.entity(patient_id)
        body_part = _body_part_entity(ctx.world, patient, surgery.part)
        prosthetic_name = None
        prosthetic_id = parse_entity_id(surgery.prosthetic_item_id)
        if prosthetic_id is not None:
            if not ctx.world.has_entity(prosthetic_id):
                return rejected("prosthetic does not exist")
            prosthetic = ctx.entity(prosthetic_id)
            if not prosthetic.has_component(ProstheticComponent):
                return rejected("target prosthetic is not usable")
            prosthetic_name = prosthetic.get_component(ProstheticComponent).part
            _move_entity(ctx.world, prosthetic_id, patient_id)
        if body_part is None:
            body_part = spawn_entity(
                ctx.world,
                [
                    IdentityComponent(name=surgery.part, kind="body-part"),
                    BodyPartHealthComponent(part=surgery.part),
                ],
            )
            patient.add_relationship(HasBodyPart(), body_part.id)
        part = body_part.get_component(BodyPartHealthComponent)
        if surgery.operation == "amputate":
            updated_part = replace(part, health=0.0, missing=True, prosthetic=None)
        elif surgery.operation == "install-prosthetic":
            updated_part = replace(part, health=1.0, missing=False, prosthetic=prosthetic_name)
        else:
            updated_part = replace(part, health=1.0, missing=False)
        replace_component(body_part, updated_part)
        replace_component(surgery_entity, replace(surgery, completed=True))
        return ok(
            SurgeryPerformedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(doctor_id),
                    target_ids=(str(patient_id), str(surgery_id), str(body_part.id)),
                    patient_id=str(patient_id),
                    surgery_id=str(surgery_id),
                    part=surgery.part,
                    operation=surgery.operation,
                )
            )
        )


class ClaimOwnershipHandler:
    command_type = "claim-ownership"

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
        owner_id = _owner(target)
        if owner_id == character_id:
            return rejected("already owned by you")
        if owner_id is not None:
            return rejected("target is already owned")

        character.add_relationship(Owns(since_epoch=ctx.epoch), target_id)
        return ok(
            OwnershipClaimedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                )
            )
        )


class ReleaseOwnershipHandler:
    command_type = "release-ownership"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if character_id is None or target_id is None:
            return rejected("invalid character or target id")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")

        character = ctx.entity(character_id)
        if not character.has_relationship(Owns, target_id):
            return rejected("not owned by you")

        character.remove_relationship(Owns, target_id)
        return ok(
            OwnershipReleasedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                )
            )
        )


def colonysim_fragments(world: World, character: Entity) -> list[str]:
    lines: list[str] = []
    ctx = ComponentPromptContext.for_entity(world, character)
    inventory = []
    for item in ctx.inventory_items(ResourceStackComponent):
        stack = item.get_component(ResourceStackComponent)
        inventory.append(f"{stack.quantity} {stack.resource_type}")
    if inventory:
        lines.append("You have resources: " + ", ".join(sorted(inventory)) + ".")
    for component_type in (
        WorkPriorityComponent,
        PawnProfileComponent,
        PrisonerComponent,
        BedRestComponent,
        InfectionComponent,
        MentalStateComponent,
    ):
        if character.has_component(component_type):
            lines.extend(character.get_component(component_type).prompt_fragments(ctx))
    allowed_rooms = [str(room_id) for _edge, room_id in character.get_relationships(AllowedIn)]
    if allowed_rooms:
        lines.append("Allowed work area rooms: " + ", ".join(sorted(allowed_rooms)) + ".")
    for entity in world.query().with_all([RecipeComponent]).execute_entities():
        recipe_ctx = ComponentPromptContext.for_entity(
            world, entity, perspective=ctx.perspective, target=character
        )
        lines.extend(entity.get_component(RecipeComponent).prompt_fragments(recipe_ctx))
    for marker in world.query().with_all([ColonySimComponent]).execute_entities():
        if marker.has_component(ColonyWealthComponent):
            marker_ctx = ComponentPromptContext.for_entity(
                world, marker, perspective=ctx.perspective, target=character
            )
            lines.extend(marker.get_component(ColonyWealthComponent).prompt_fragments(marker_ctx))
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        entity_ctx = ComponentPromptContext.for_entity(
            world, entity, perspective=ctx.perspective, room=ctx.room, target=character
        )
        for component_type in (
            ResourceNodeComponent,
            WorkstationComponent,
            MedicalBedComponent,
            MedicineComponent,
            RoomQualityComponent,
            ForbiddenComponent,
            JobComponent,
            JobBillComponent,
            ResearchProjectComponent,
            ColonyIncidentComponent,
            TradeOfferComponent,
            SurgeryBillComponent,
            CaravanComponent,
        ):
            if entity.has_component(component_type):
                lines.extend(entity.get_component(component_type).prompt_fragments(entity_ctx))
        if entity.has_component(StockpileComponent):
            stockpile = entity.get_component(StockpileComponent)
            load = _stockpile_load(world, entity)
            allowed = (
                entity.get_component(StorageFilterComponent).allowed_types
                if entity.has_component(StorageFilterComponent)
                else ()
            )
            filter_text = ", ".join(allowed) if allowed else "anything"
            lines.append(
                f"Nearby stockpile: {load}/{stockpile.capacity} stored, accepts {filter_text}."
            )
        if character.has_relationship(Owns, entity_id) and entity_id != character.id:
            lines.append(f"You own {entity_name(entity, 'something')}.")
    for _edge, part_id in character.get_relationships(HasBodyPart):
        # Relics cascades inbound edge removal, so a related id is always live here.
        part_entity = world.get_entity(part_id)
        if part_entity.has_component(BodyPartHealthComponent):
            part_ctx = ComponentPromptContext.for_entity(
                world, part_entity, perspective=ctx.perspective, target=character
            )
            lines.extend(
                part_entity.get_component(BodyPartHealthComponent).prompt_fragments(part_ctx)
            )
    return sorted(lines)


__all__ = [
    "AllowItemHandler",
    "AllowedIn",
    "AllowedAreaSetEvent",
    "AssignedTo",
    "AssignJobHandler",
    "BakeHandler",
    "BedRestComponent",
    "BodyPartHealthComponent",
    "CaravanComponent",
    "MemberOfCaravan",
    "CaravanFormedEvent",
    "CharacterRescuedEvent",
    "ClaimOwnershipHandler",
    "ColonySimComponent",
    "ColonyWealthComponent",
    "ColonyWealthConsequence",
    "ColonyWealthUpdatedEvent",
    "CompleteJobHandler",
    "CompleteTradeHandler",
    "CreateStockpileHandler",
    "CraftHandler",
    "FactionRelationComponent",
    "FormCaravanHandler",
    "ForbiddenComponent",
    "ForbidItemHandler",
    "GatherResourceHandler",
    "HasBodyPart",
    "HaulItemHandler",
    "HaulableComponent",
    "InfectionChangedEvent",
    "InfectionComponent",
    "ColonyIncidentComponent",
    "ColonyIncidentResolvedEvent",
    "JobComponent",
    "JobBillComponent",
    "JobBillProgressedEvent",
    "MedicalBedComponent",
    "MedicalRecoveryConsequence",
    "MedicineComponent",
    "MentalStateChangedEvent",
    "MentalStateComponent",
    "MentalStateConsequence",
    "MergeStackHandler",
    "Owns",
    "PawnProfileComponent",
    "PawnProfileUpdatedEvent",
    "PerformSurgeryHandler",
    "PrisonerComponent",
    "PrisonerPolicySetEvent",
    "ProgressJobBillHandler",
    "ProstheticComponent",
    "RecipeComponent",
    "RecruitPrisonerHandler",
    "RecruitmentProgressedEvent",
    "ReleaseOwnershipHandler",
    "ReleaseReservationHandler",
    "ResearchProgressedEvent",
    "ResearchProjectComponent",
    "ResearchProjectHandler",
    "ReserveHandler",
    "ReservedBy",
    "RescueToBedHandler",
    "ResourceNodeComponent",
    "ResourceRegenSystem",
    "ResourceStackComponent",
    "RoomQualityComponent",
    "RoomQualityConsequence",
    "RoomQualityUpdatedEvent",
    "RoomRoleComponent",
    "RoomStatComponent",
    "SetAllowedAreaHandler",
    "SetPrisonerPolicyHandler",
    "SetStorageFilterHandler",
    "SetWorkPriorityHandler",
    "SplitStackHandler",
    "StockpileComponent",
    "StorageFilterComponent",
    "SurgeryBillComponent",
    "SurgeryPerformedEvent",
    "TendWoundHandler",
    "TechUnlockComponent",
    "TechUnlockedEvent",
    "TradeCompletedEvent",
    "TradeOfferComponent",
    "UpdatePawnProfileHandler",
    "WorkCapabilityComponent",
    "WorkPriorityComponent",
    "WorkPrioritySetEvent",
    "WorkstationComponent",
    "WoundTendedEvent",
    "colonysim_fragments",
    "ensure_colonysim_marker",
    "install_colonysim",
]
