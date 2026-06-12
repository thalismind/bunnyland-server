"""Life-sim relationships, family, and pregnancy mechanics (spec 20.5-20.6).

Major life-sim state transitions are explicit command handlers and typed events. Prose
may describe intent, but only these handlers create partnership, pregnancy, birth, and
family ECS state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import field, replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic.dataclasses import dataclass
from relics import Component, Edge, Entity, EntityId, World

from ..core.commands import SubmittedCommand
from ..core.components import (
    CharacterComponent,
    DeadComponent,
    DownedComponent,
    HealthComponent,
    IdentityComponent,
    RoomComponent,
    SleepingComponent,
    SuspendedComponent,
    WorldClockComponent,
)
from ..core.controllers import LLMControllerComponent
from ..core.ecs import (
    container_of,
    parse_entity_id,
    reachable_ids,
    replace_component,
    spawn_entity,
)
from ..core.edges import ContainmentMode, Contains, ControlledBy
from ..core.events import (
    AdoptionCompletedEvent,
    BirthDueEvent,
    BirthResolvedEvent,
    DomainEvent,
    EventVisibility,
    PartnershipEndedEvent,
    PartnershipStartedEvent,
    PregnancyStartedEvent,
)
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected
from .policy import BoundaryTag, PolicyGate

DEFAULT_PREGNANCY_SECONDS = 3 * 24 * 60 * 60
SECONDS_PER_DAY = 24 * 60 * 60
SECONDS_PER_YEAR = 365 * SECONDS_PER_DAY
DEFAULT_ADULT_AGE_SECONDS = 18 * SECONDS_PER_YEAR
DEFAULT_ELDER_AGE_SECONDS = 65 * SECONDS_PER_YEAR
DEFAULT_NATURAL_DEATH_AGE_SECONDS = 90 * SECONDS_PER_YEAR

# Sleeping in a room you own or claim earns a temporary "well-rested" buff (spec 20.5).
WELL_RESTED_BONUS = 0.25  # fractional boost to skill xp gains while rested
MIN_RESTFUL_SLEEP_SECONDS = 60 * 60  # must sleep at least this long at home to benefit
MAX_WELL_RESTED_SECONDS = 8 * 60 * 60  # the buff lasts at most this long after waking


@dataclass(frozen=True)
class LifeStageComponent(Component):
    stage: str = "adult"


@dataclass(frozen=True)
class AgeComponent(Component):
    born_at_epoch: int = 0


@dataclass(frozen=True)
class LifesimAgingPolicyComponent(Component):
    natural_aging: bool = False
    adult_age_seconds: int = DEFAULT_ADULT_AGE_SECONDS
    elder_age_seconds: int = DEFAULT_ELDER_AGE_SECONDS
    natural_death_age_seconds: int = DEFAULT_NATURAL_DEATH_AGE_SECONDS
    natural_death_checks: int = 1


@dataclass(frozen=True)
class AspirationComponent(Component):
    name: str
    milestones: tuple[str, ...] = ()
    completed: tuple[str, ...] = ()


@dataclass(frozen=True)
class MilestoneComponent(Component):
    name: str
    completed_at_epoch: int
    reward_item_id: str | None = None


@dataclass(frozen=True)
class HouseholdFundsComponent(Component):
    balance: int = 0


@dataclass(frozen=True)
class BillComponent(Component):
    amount: int
    reason: str
    due_epoch: int = 0
    creditor_id: str | None = None
    paid_at_epoch: int | None = None


@dataclass(frozen=True)
class CareerComponent(Component):
    title: str
    level: int = 1
    hourly_pay: int = 10
    performance: float = 0.0
    active: bool = True


@dataclass(frozen=True)
class JobScheduleComponent(Component):
    next_shift_epoch: int = 0
    shift_duration_seconds: int = 8 * 60 * 60
    shift_interval_seconds: int = 24 * 60 * 60


@dataclass(frozen=True)
class BusinessOwnerComponent(Component):
    name: str
    default_price: int = 10
    sales_count: int = 0
    promoted: bool = False


@dataclass(frozen=True)
class CustomerComponent(Component):
    budget: int = 20


@dataclass(frozen=True)
class HouseholdComponent(Component):
    household_id: str
    name: str = ""


@dataclass(frozen=True)
class HomeComponent(Component):
    owner_id: str
    household_id: str | None = None


@dataclass(frozen=True)
class RoomClaimComponent(Component):
    claimed_by_id: str
    claimed_at_epoch: int


@dataclass(frozen=True)
class HomeRestComponent(Component):
    """Marks an in-progress rest while a character sleeps in a room they own or claim.

    RestfulSleepConsequence adds it while the character sleeps at home and converts it
    into a WellRestedComponent buff once they wake (spec 20.5).
    """

    asleep_since_epoch: int
    room_id: str


@dataclass(frozen=True)
class WellRestedComponent(Component):
    """Buff from waking after a long-enough sleep in your own home (spec 20.5).

    While active (``expires_at_epoch`` still in the future) it raises skill xp gains by
    ``bonus``, a fraction of the base amount.
    """

    expires_at_epoch: int
    bonus: float = WELL_RESTED_BONUS


@dataclass(frozen=True)
class RoutineComponent(Component):
    activity: str
    interval_seconds: int = 24 * 60 * 60
    next_due_epoch: int = 0
    last_completed_epoch: int | None = None


@dataclass(frozen=True)
class ReputationComponent(Component):
    score: float = 0.0
    known_for: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillSetComponent(Component):
    levels: dict[str, int] = field(default_factory=dict)
    xp: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class CharacterProfileComponent(Component):
    traits: tuple[str, ...] = ()
    interests: tuple[str, ...] = ()
    preferred_routine: str = ""


@dataclass(frozen=True)
class WhimComponent(Component):
    want: str
    reward_xp: float = 5.0
    completed_at_epoch: int | None = None


@dataclass(frozen=True)
class HomeObjectComponent(Component):
    affordance: str
    cleanliness: float = 1.0
    condition: float = 1.0
    decor_score: float = 0.0
    upgrade_level: int = 0


@dataclass(frozen=True)
class ReproductiveComponent(Component):
    can_be_pregnant: bool = False
    can_cause_pregnancy: bool = False
    fertility: float = 1.0
    species_group: str = "bunny"
    pregnancy_blocked: bool = False


@dataclass(frozen=True)
class PregnancyComponent(Component):
    started_at_epoch: int
    due_at_epoch: int
    co_parent_ids: tuple[str, ...]
    source_event_id: str | None = None


@dataclass(frozen=True)
class BirthDueComponent(Component):
    due_since_epoch: int


@dataclass(frozen=True)
class ParentOf(Edge):
    pass


@dataclass(frozen=True)
class HasRoutine(Edge):
    pass


@dataclass(frozen=True)
class HasBill(Edge):
    pass


@dataclass(frozen=True)
class OwnsBusiness(Edge):
    pass


@dataclass(frozen=True)
class HasWhim(Edge):
    pass


@dataclass(frozen=True)
class PartnerOf(Edge):
    since_epoch: int
    status: str = "together"


@dataclass(frozen=True)
class RelationshipStatus(Edge):
    status: str
    since_epoch: int


@dataclass(frozen=True)
class JealousOf(Edge):
    partner_id: str
    intensity: float = 0.0
    triggered_at_epoch: int = 0


class AspirationChosenEvent(DomainEvent):
    aspiration: str


class MilestoneCompletedEvent(DomainEvent):
    aspiration: str
    milestone: str
    reward_item_id: str | None = None


class CareerStartedEvent(DomainEvent):
    title: str


class WorkShiftCompletedEvent(DomainEvent):
    title: str
    earned: int
    balance: int


class WagePaidEvent(DomainEvent):
    worker_id: str
    amount: int
    payer_balance: int
    worker_balance: int


class BillCreatedEvent(DomainEvent):
    bill_id: str
    amount: int
    reason: str
    due_epoch: int


class TaxAssessedEvent(DomainEvent):
    bill_id: str
    amount: int
    reason: str


class RentChargedEvent(DomainEvent):
    bill_id: str
    tenant_id: str
    amount: int
    reason: str


class BillPaidEvent(DomainEvent):
    bill_id: str
    amount: int
    balance: int


class PromotionEarnedEvent(DomainEvent):
    title: str
    level: int


class BusinessOpenedEvent(DomainEvent):
    business_name: str


class BusinessSaleEvent(DomainEvent):
    business_name: str
    item_id: str
    customer_id: str
    price: int
    balance: int


class BusinessPurchaseEvent(DomainEvent):
    business_name: str
    item_id: str
    seller_id: str
    price: int
    balance: int


class BusinessPromotedEvent(DomainEvent):
    business_name: str


class HouseholdJoinedEvent(DomainEvent):
    household_id: str
    household_name: str = ""


class HomeClaimedEvent(DomainEvent):
    room_id_claimed: str


class RoomClaimedEvent(DomainEvent):
    room_id_claimed: str


class WellRestedEvent(DomainEvent):
    room_id: str
    slept_seconds: int
    expires_at_epoch: int


class RoutineSetEvent(DomainEvent):
    activity: str
    next_due_epoch: int


class RoutineDueEvent(DomainEvent):
    activity: str
    next_due_epoch: int


class RelationshipStatusChangedEvent(DomainEvent):
    target_id: str
    status: str


class GossipSpreadEvent(DomainEvent):
    target_id: str
    text: str
    reputation_delta: float


class JealousyTriggeredEvent(DomainEvent):
    partner_id: str
    rival_id: str
    intensity: float


class SkillXPChangedEvent(DomainEvent):
    character_id: str
    skill: str
    xp: float
    level: int


class SkillLeveledEvent(DomainEvent):
    character_id: str
    skill: str
    level: int


class MentorshipCompletedEvent(DomainEvent):
    student_id: str
    skill: str
    xp: float


class ProfileUpdatedEvent(DomainEvent):
    traits: tuple[str, ...]
    interests: tuple[str, ...]


class WhimAddedEvent(DomainEvent):
    whim_id: str
    want: str


class WhimCompletedEvent(DomainEvent):
    whim_id: str
    want: str


class HomeObjectUsedEvent(DomainEvent):
    object_id: str
    affordance: str


class HomeObjectMaintainedEvent(DomainEvent):
    object_id: str
    action: str
    cleanliness: float
    condition: float
    decor_score: float
    upgrade_level: int


class InvitationSentEvent(DomainEvent):
    guest_id: str
    room_id_invited: str


class LifesimAgingPolicyChangedEvent(DomainEvent):
    natural_aging: bool
    adult_age_seconds: int
    elder_age_seconds: int
    natural_death_age_seconds: int


def _skill_threshold(level: int) -> float:
    return 100.0 * (level + 1)


def _skill_state(entity: Entity) -> SkillSetComponent:
    if entity.has_component(SkillSetComponent):
        return entity.get_component(SkillSetComponent)
    return SkillSetComponent()


def _well_rested_bonus(entity: Entity, epoch: int) -> float:
    """Active well-rested fractional bonus for ``entity``, or 0 if absent/expired."""
    if not entity.has_component(WellRestedComponent):
        return 0.0
    buff = entity.get_component(WellRestedComponent)
    return buff.bonus if buff.expires_at_epoch > epoch else 0.0


def _add_skill_xp(
    ctx: HandlerContext,
    entity: Entity,
    *,
    skill: str,
    amount: float,
    actor_id: str,
    visibility: EventVisibility = EventVisibility.PRIVATE,
    target_ids: tuple[str, ...] = (),
) -> list[DomainEvent]:
    # A character well-rested from sleeping in their own home learns faster (spec 20.5).
    amount *= 1.0 + _well_rested_bonus(entity, ctx.epoch)
    state = _skill_state(entity)
    levels = dict(state.levels)
    xp_by_skill = dict(state.xp)
    current_level = levels.get(skill, 0)
    current_xp = xp_by_skill.get(skill, 0.0) + amount
    events: list[DomainEvent] = []

    while current_level < 10 and current_xp >= _skill_threshold(current_level):
        current_xp -= _skill_threshold(current_level)
        current_level += 1
        events.append(
            SkillLeveledEvent(
                **ctx.event_base(
                    visibility=visibility,
                    actor_id=actor_id,
                    target_ids=target_ids,
                    character_id=str(entity.id),
                    skill=skill,
                    level=current_level,
                )
            )
        )

    levels[skill] = current_level
    xp_by_skill[skill] = current_xp
    replace_component(entity, SkillSetComponent(levels=levels, xp=xp_by_skill))
    events.insert(
        0,
        SkillXPChangedEvent(
            **ctx.event_base(
                visibility=visibility,
                actor_id=actor_id,
                target_ids=target_ids,
                character_id=str(entity.id),
                skill=skill,
                xp=current_xp,
                level=current_level,
            )
        ),
    )
    return events


def _participant_ids(command: SubmittedCommand, *payload_keys: str) -> list[str]:
    ids = [command.character_id]
    for key in payload_keys:
        raw = command.payload.get(key)
        if raw is not None:
            ids.append(str(raw))
    return ids


def _parse_text_tuple(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        values = raw.split(",")
    elif isinstance(raw, (list, tuple, set)):
        values = raw
    else:
        values = (raw,)
    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))


def _optional_bool(raw: object) -> bool | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _optional_int(raw: object) -> int | None:
    if raw is None:
        return None
    return int(raw)


class _ActorView:
    def __init__(self, world: World) -> None:
        self.world = world


def romance_classifier(command: SubmittedCommand):
    if command.command_type in {"start-partnership", "end-partnership"}:
        return BoundaryTag.ROMANCE, _participant_ids(command, "target_id")
    return None


def adult_classifier(command: SubmittedCommand):
    if command.command_type == "start-pregnancy":
        return BoundaryTag.ADULT, _participant_ids(command, "co_parent_id")
    return None


def pregnancy_classifier(command: SubmittedCommand):
    if command.command_type == "start-pregnancy":
        return BoundaryTag.PREGNANCY, _participant_ids(command, "co_parent_id")
    if command.command_type == "resolve-birth":
        return BoundaryTag.PREGNANCY, [command.character_id]
    return None


def _event_room(world: World, entity_id: EntityId) -> str | None:
    room_id = container_of(world.get_entity(entity_id))
    return str(room_id) if room_id is not None else None


def _room_id(world: World, entity_id: EntityId) -> str | None:
    return _event_room(world, entity_id)


def _same_room(world: World, left_id: EntityId, right_id: EntityId) -> bool:
    return container_of(world.get_entity(left_id)) == container_of(world.get_entity(right_id))


def _owns_or_claims_room(character_id: EntityId, room: Entity) -> bool:
    """True if ``room`` is the character's claimed home or a room they claim."""
    cid = str(character_id)
    if room.has_component(HomeComponent) and room.get_component(HomeComponent).owner_id == cid:
        return True
    return (
        room.has_component(RoomClaimComponent)
        and room.get_component(RoomClaimComponent).claimed_by_id == cid
    )


def _event_base(epoch: int, **kwargs) -> dict[str, Any]:
    base = {"event_id": uuid4().hex, "world_epoch": epoch, "created_at": datetime.now(UTC)}
    base.update(kwargs)
    return base


def _active_character(entity: Entity) -> bool:
    return (
        entity.has_component(CharacterComponent)
        and not entity.has_component(SuspendedComponent)
        and not entity.has_component(DownedComponent)
        and not entity.has_component(DeadComponent)
    )


def _partner_edge(entity: Entity, target_id: EntityId) -> PartnerOf | None:
    for edge, related_id in entity.get_relationships(PartnerOf):
        if related_id == target_id:
            return edge
    return None


def _status_edge(entity: Entity, target_id: EntityId) -> RelationshipStatus | None:
    for edge, related_id in entity.get_relationships(RelationshipStatus):
        if related_id == target_id:
            return edge
    return None


def parents_of(world: World, child_id: EntityId) -> tuple[str, ...]:
    parents = []
    for parent in world.query().with_all([CharacterComponent]).execute_entities():
        if parent.has_relationship(ParentOf, child_id):
            parents.append(str(parent.id))
    return tuple(sorted(parents))


def children_of(world: World, parent_id: EntityId) -> tuple[str, ...]:
    parent = world.get_entity(parent_id)
    return tuple(sorted(str(child_id) for _edge, child_id in parent.get_relationships(ParentOf)))


def partners_of(world: World, character_id: EntityId) -> tuple[str, ...]:
    character = world.get_entity(character_id)
    return tuple(
        sorted(
            str(target_id)
            for edge, target_id in character.get_relationships(PartnerOf)
            if edge.status == "together"
        )
    )


def _lifesim_aging_policy(world: World) -> LifesimAgingPolicyComponent:
    for entity in world.query().with_all([LifesimAgingPolicyComponent]).execute_entities():
        return entity.get_component(LifesimAgingPolicyComponent)
    return LifesimAgingPolicyComponent()


def _lifesim_aging_policy_entity(world: World) -> Entity:
    for entity in world.query().with_all([LifesimAgingPolicyComponent]).execute_entities():
        return entity
    clocks = list(world.query().with_all([WorldClockComponent]).execute_entities())
    return clocks[0] if clocks else spawn_entity(world, [])


def configure_lifesim_aging(
    actor,
    *,
    natural_aging: bool | None = None,
    adult_age_seconds: int | None = None,
    elder_age_seconds: int | None = None,
    natural_death_age_seconds: int | None = None,
    natural_death_checks: int | None = None,
) -> LifesimAgingPolicyComponent:
    """Ensure the world has a lifesim ageing policy and optionally update it."""

    entity = _lifesim_aging_policy_entity(actor.world)
    policy = (
        entity.get_component(LifesimAgingPolicyComponent)
        if entity.has_component(LifesimAgingPolicyComponent)
        else LifesimAgingPolicyComponent()
    )
    updates = {}
    if natural_aging is not None:
        updates["natural_aging"] = natural_aging
    if adult_age_seconds is not None:
        updates["adult_age_seconds"] = adult_age_seconds
    if elder_age_seconds is not None:
        updates["elder_age_seconds"] = elder_age_seconds
    if natural_death_age_seconds is not None:
        updates["natural_death_age_seconds"] = natural_death_age_seconds
    if natural_death_checks is not None:
        updates["natural_death_checks"] = natural_death_checks
    updated = replace(policy, **updates)
    replace_component(entity, updated)
    return updated


def _routine_for_activity(world: World, character: Entity, activity: str) -> Entity | None:
    for _edge, routine_id in character.get_relationships(HasRoutine):
        if not world.has_entity(routine_id):
            continue
        routine = world.get_entity(routine_id)
        if routine.has_component(RoutineComponent):
            component = routine.get_component(RoutineComponent)
            if component.activity == activity:
                return routine
    return None


def _first_business(
    world: World, character: Entity, business_id: EntityId | None = None
) -> Entity | None:
    for _edge, candidate_id in character.get_relationships(OwnsBusiness):
        if business_id is not None and candidate_id != business_id:
            continue
        if not world.has_entity(candidate_id):
            continue
        business = world.get_entity(candidate_id)
        if business.has_component(BusinessOwnerComponent):
            return business
    return None


def _funds(entity: Entity) -> HouseholdFundsComponent:
    if entity.has_component(HouseholdFundsComponent):
        return entity.get_component(HouseholdFundsComponent)
    return HouseholdFundsComponent()


def _create_bill(
    ctx: HandlerContext,
    debtor: Entity,
    *,
    amount: int,
    reason: str,
    due_epoch: int,
    creditor_id: str | None = None,
) -> Entity:
    bill = spawn_entity(
        ctx.world,
        [
            BillComponent(
                amount=amount,
                reason=reason,
                due_epoch=due_epoch,
                creditor_id=creditor_id,
            )
        ],
    )
    debtor.add_relationship(HasBill(), bill.id)
    return bill


def kinship_label(world: World, source_id: EntityId, target_id: EntityId) -> str | None:
    if source_id == target_id:
        return "self"
    source_parents = set(parents_of(world, source_id))
    target_parents = set(parents_of(world, target_id))
    if str(target_id) in source_parents:
        return "parent"
    if str(source_id) in target_parents:
        return "child"
    if str(target_id) in partners_of(world, source_id):
        return "partner"
    if source_parents and source_parents == target_parents:
        return "sibling"
    return None


class ChooseAspirationHandler:
    command_type = "choose-aspiration"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        name = str(command.payload.get("name", "")).strip()
        if not name:
            return rejected("aspiration name is required")
        milestones = tuple(
            str(item).strip()
            for item in command.payload.get("milestones", ())
            if str(item).strip()
        )
        actor = ctx.entity(actor_id)
        replace_component(actor, AspirationComponent(name=name, milestones=milestones))
        return ok(
            AspirationChosenEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    aspiration=name,
                )
            )
        )


class CompleteMilestoneHandler:
    command_type = "complete-milestone"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        actor = ctx.entity(actor_id)
        if not actor.has_component(AspirationComponent):
            return rejected("no aspiration selected")
        aspiration = actor.get_component(AspirationComponent)
        milestone = str(command.payload.get("milestone", "")).strip()
        if not milestone:
            return rejected("milestone is required")
        if aspiration.milestones and milestone not in aspiration.milestones:
            return rejected("milestone is not part of aspiration")
        if milestone in aspiration.completed:
            return rejected("milestone already completed")

        reward_item_id: str | None = None
        reward_name = str(command.payload.get("reward_name", "")).strip()
        if reward_name:
            reward = spawn_entity(
                ctx.world,
                [IdentityComponent(name=reward_name, kind="item")],
            )
            actor.add_relationship(Contains(mode=ContainmentMode.INVENTORY), reward.id)
            reward_item_id = str(reward.id)

        milestone_entity = spawn_entity(
            ctx.world,
            [
                MilestoneComponent(
                    name=milestone,
                    completed_at_epoch=ctx.epoch,
                    reward_item_id=reward_item_id,
                )
            ],
        )
        del milestone_entity  # milestone entities are queryable history, not linked yet.
        replace_component(
            actor,
            AspirationComponent(
                name=aspiration.name,
                milestones=aspiration.milestones,
                completed=(*aspiration.completed, milestone),
            ),
        )
        return ok(
            MilestoneCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    aspiration=aspiration.name,
                    milestone=milestone,
                    reward_item_id=reward_item_id,
                )
            )
        )


class PracticeSkillHandler:
    command_type = "practice-skill"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        skill = str(command.payload.get("skill", "")).strip().lower()
        if not skill:
            return rejected("skill is required")
        xp = float(command.payload.get("xp", 25.0))
        if xp <= 0:
            return rejected("xp must be positive")
        return ok(
            *_add_skill_xp(
                ctx,
                ctx.entity(actor_id),
                skill=skill,
                amount=xp,
                actor_id=str(actor_id),
            )
        )


class StudySkillHandler:
    command_type = "study-skill"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        skill = str(command.payload.get("skill", "")).strip().lower()
        if not skill:
            return rejected("skill is required")
        xp = float(command.payload.get("xp", 15.0))
        if xp <= 0:
            return rejected("xp must be positive")
        return ok(
            *_add_skill_xp(
                ctx,
                ctx.entity(actor_id),
                skill=skill,
                amount=xp,
                actor_id=str(actor_id),
            )
        )


class MentorSkillHandler:
    command_type = "mentor-skill"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        student_id = parse_entity_id(command.payload.get("student_id"))
        if actor_id is None or student_id is None:
            return rejected("invalid mentor or student id")
        if not ctx.world.has_entity(student_id):
            return rejected("student does not exist")
        if not _same_room(ctx.world, actor_id, student_id):
            return rejected("student is not present")
        skill = str(command.payload.get("skill", "")).strip().lower()
        if not skill:
            return rejected("skill is required")

        mentor_level = _skill_state(ctx.entity(actor_id)).levels.get(skill, 0)
        xp = float(command.payload.get("xp", 20.0)) + mentor_level * 5.0
        if xp <= 0:
            return rejected("xp must be positive")
        events = _add_skill_xp(
            ctx,
            ctx.entity(student_id),
            skill=skill,
            amount=xp,
            actor_id=str(actor_id),
            target_ids=(str(student_id),),
        )
        events.append(
            MentorshipCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.DIRECTED,
                    actor_id=str(actor_id),
                    target_ids=(str(student_id),),
                    student_id=str(student_id),
                    skill=skill,
                    xp=xp,
                )
            )
        )
        return ok(*events)


class UpdateProfileHandler:
    command_type = "update-profile"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        traits = _parse_text_tuple(command.payload.get("traits"))
        interests = _parse_text_tuple(command.payload.get("interests"))
        preferred_routine = str(command.payload.get("preferred_routine", "")).strip()
        replace_component(
            ctx.entity(actor_id),
            CharacterProfileComponent(
                traits=traits,
                interests=interests,
                preferred_routine=preferred_routine,
            ),
        )
        return ok(
            ProfileUpdatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    traits=traits,
                    interests=interests,
                )
            )
        )


class AddWhimHandler:
    command_type = "add-whim"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        want = str(command.payload.get("want", "")).strip()
        if not want:
            return rejected("whim want is required")
        reward_xp = float(command.payload.get("reward_xp", 5.0))
        if reward_xp < 0:
            return rejected("reward xp must not be negative")
        whim = spawn_entity(ctx.world, [WhimComponent(want=want, reward_xp=reward_xp)])
        ctx.entity(actor_id).add_relationship(HasWhim(), whim.id)
        return ok(
            WhimAddedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    target_ids=(str(whim.id),),
                    whim_id=str(whim.id),
                    want=want,
                )
            )
        )


class CompleteWhimHandler:
    command_type = "complete-whim"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        whim_id = parse_entity_id(command.payload.get("whim_id"))
        if actor_id is None or whim_id is None:
            return rejected("invalid character or whim id")
        if not ctx.world.has_entity(whim_id):
            return rejected("whim does not exist")
        actor = ctx.entity(actor_id)
        if not actor.has_relationship(HasWhim, whim_id):
            return rejected("whim does not belong to you")
        whim_entity = ctx.entity(whim_id)
        if not whim_entity.has_component(WhimComponent):
            return rejected("target is not a whim")
        whim = whim_entity.get_component(WhimComponent)
        if whim.completed_at_epoch is not None:
            return rejected("whim already completed")
        replace_component(whim_entity, replace(whim, completed_at_epoch=ctx.epoch))
        events = [
            WhimCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    target_ids=(str(whim_id),),
                    whim_id=str(whim_id),
                    want=whim.want,
                )
            )
        ]
        if whim.reward_xp > 0:
            events.extend(
                _add_skill_xp(
                    ctx,
                    actor,
                    skill="life",
                    amount=whim.reward_xp,
                    actor_id=str(actor_id),
                )
            )
        return ok(*events)


class UseHomeObjectHandler:
    command_type = "use-home-object"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        object_id = parse_entity_id(command.payload.get("object_id"))
        if actor_id is None or object_id is None:
            return rejected("invalid character or object id")
        if not ctx.world.has_entity(object_id):
            return rejected("object does not exist")
        actor = ctx.entity(actor_id)
        if object_id not in reachable_ids(ctx.world, actor):
            return rejected("object is not reachable")
        home_object = ctx.entity(object_id)
        if not home_object.has_component(HomeObjectComponent):
            return rejected("target is not a home object")
        component = home_object.get_component(HomeObjectComponent)
        if component.condition <= 0:
            return rejected("home object is broken")
        replace_component(
            home_object,
            replace(component, cleanliness=max(0.0, component.cleanliness - 0.1)),
        )
        return ok(
            HomeObjectUsedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=_room_id(ctx.world, actor_id),
                    target_ids=(str(object_id),),
                    object_id=str(object_id),
                    affordance=component.affordance,
                )
            )
        )


class MaintainHomeObjectHandler:
    command_type = "maintain-home-object"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        object_id = parse_entity_id(command.payload.get("object_id"))
        action = str(command.payload.get("action", "")).strip().lower()
        if actor_id is None or object_id is None:
            return rejected("invalid character or object id")
        if action not in {"clean", "repair", "upgrade", "decorate"}:
            return rejected("maintenance action is required")
        if not ctx.world.has_entity(object_id):
            return rejected("object does not exist")
        actor = ctx.entity(actor_id)
        if object_id not in reachable_ids(ctx.world, actor):
            return rejected("object is not reachable")
        home_object = ctx.entity(object_id)
        if not home_object.has_component(HomeObjectComponent):
            return rejected("target is not a home object")
        component = home_object.get_component(HomeObjectComponent)
        updates: dict[str, object] = {}
        if action == "clean":
            updates["cleanliness"] = 1.0
        elif action == "repair":
            updates["condition"] = 1.0
        elif action == "upgrade":
            updates["upgrade_level"] = component.upgrade_level + 1
            updates["condition"] = min(1.0, component.condition + 0.25)
        else:
            updates["decor_score"] = component.decor_score + 1.0
        updated = replace(component, **updates)
        replace_component(home_object, updated)
        return ok(
            HomeObjectMaintainedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=_room_id(ctx.world, actor_id),
                    target_ids=(str(object_id),),
                    object_id=str(object_id),
                    action=action,
                    cleanliness=updated.cleanliness,
                    condition=updated.condition,
                    decor_score=updated.decor_score,
                    upgrade_level=updated.upgrade_level,
                )
            )
        )


class InviteOverHandler:
    command_type = "invite-over"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        guest_id = parse_entity_id(command.payload.get("guest_id"))
        room_id = parse_entity_id(command.payload.get("room_id"))
        if actor_id is None or guest_id is None:
            return rejected("invalid character or guest id")
        if not ctx.world.has_entity(guest_id):
            return rejected("guest does not exist")
        if room_id is None:
            room_id = container_of(ctx.entity(actor_id))
        if room_id is None or not ctx.world.has_entity(room_id):
            return rejected("invitation room does not exist")
        room = ctx.entity(room_id)
        if not room.has_component(RoomComponent):
            return rejected("invitation target is not a room")
        if not (
            _owns_or_claims_room(actor_id, room)
            or container_of(ctx.entity(actor_id)) == room_id
        ):
            return rejected("you cannot invite guests there")
        return ok(
            InvitationSentEvent(
                **ctx.event_base(
                    visibility=EventVisibility.DIRECTED,
                    actor_id=str(actor_id),
                    room_id=str(room_id),
                    target_ids=(str(guest_id), str(room_id)),
                    guest_id=str(guest_id),
                    room_id_invited=str(room_id),
                )
            )
        )


class ConfigureAgingHandler:
    command_type = "configure-aging"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        policy = configure_lifesim_aging(
            _ActorView(ctx.world),
            natural_aging=_optional_bool(command.payload.get("natural_aging")),
            adult_age_seconds=_optional_int(command.payload.get("adult_age_seconds")),
            elder_age_seconds=_optional_int(command.payload.get("elder_age_seconds")),
            natural_death_age_seconds=_optional_int(
                command.payload.get("natural_death_age_seconds")
            ),
            natural_death_checks=_optional_int(command.payload.get("natural_death_checks")),
        )
        return ok(
            LifesimAgingPolicyChangedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.SYSTEM,
                    actor_id=str(actor_id),
                    natural_aging=policy.natural_aging,
                    adult_age_seconds=policy.adult_age_seconds,
                    elder_age_seconds=policy.elder_age_seconds,
                    natural_death_age_seconds=policy.natural_death_age_seconds,
                )
            )
        )


class FindJobHandler:
    command_type = "find-job"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        title = str(command.payload.get("title", "")).strip()
        if not title:
            return rejected("job title is required")
        hourly_pay = int(command.payload.get("hourly_pay", 10))
        if hourly_pay <= 0:
            return rejected("hourly pay must be positive")
        actor = ctx.entity(actor_id)
        replace_component(actor, CareerComponent(title=title, hourly_pay=hourly_pay))
        replace_component(
            actor,
            JobScheduleComponent(
                next_shift_epoch=int(command.payload.get("next_shift_epoch", ctx.epoch)),
                shift_duration_seconds=int(
                    command.payload.get("shift_duration_seconds", 8 * 60 * 60)
                ),
                shift_interval_seconds=int(
                    command.payload.get("shift_interval_seconds", 24 * 60 * 60)
                ),
            ),
        )
        if not actor.has_component(HouseholdFundsComponent):
            actor.add_component(HouseholdFundsComponent())
        return ok(
            CareerStartedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    title=title,
                )
            )
        )


class GoToWorkHandler:
    command_type = "go-to-work"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        actor = ctx.entity(actor_id)
        if not actor.has_component(CareerComponent) or not actor.has_component(
            JobScheduleComponent
        ):
            return rejected("character has no job")
        career = actor.get_component(CareerComponent)
        schedule = actor.get_component(JobScheduleComponent)
        if not career.active:
            return rejected("career is inactive")
        if ctx.epoch < schedule.next_shift_epoch:
            return rejected("shift is not scheduled yet")
        hours = max(1, schedule.shift_duration_seconds // 3600)
        earned = career.hourly_pay * hours
        funds = (
            actor.get_component(HouseholdFundsComponent)
            if actor.has_component(HouseholdFundsComponent)
            else HouseholdFundsComponent()
        )
        updated_funds = HouseholdFundsComponent(balance=funds.balance + earned)
        replace_component(actor, updated_funds)
        performance = career.performance + float(command.payload.get("performance_gain", 0.5))
        promoted = performance >= 1.0
        if promoted:
            updated_career = CareerComponent(
                title=career.title,
                level=career.level + 1,
                hourly_pay=career.hourly_pay + 5,
                performance=performance - 1.0,
                active=career.active,
            )
        else:
            updated_career = CareerComponent(
                title=career.title,
                level=career.level,
                hourly_pay=career.hourly_pay,
                performance=performance,
                active=career.active,
            )
        replace_component(actor, updated_career)
        replace_component(
            actor,
            JobScheduleComponent(
                next_shift_epoch=ctx.epoch + schedule.shift_interval_seconds,
                shift_duration_seconds=schedule.shift_duration_seconds,
                shift_interval_seconds=schedule.shift_interval_seconds,
            ),
        )
        events = [
            WorkShiftCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    title=career.title,
                    earned=earned,
                    balance=updated_funds.balance,
                )
            )
        ]
        if promoted:
            events.append(
                PromotionEarnedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(actor_id),
                        title=career.title,
                        level=updated_career.level,
                    )
                )
            )
        return ok(*events)


class QuitJobHandler:
    command_type = "quit-job"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        actor = ctx.entity(actor_id)
        if not actor.has_component(CareerComponent):
            return rejected("character has no job")
        career = actor.get_component(CareerComponent)
        replace_component(actor, replace(career, active=False))
        return ok()


class PayWageHandler:
    command_type = "pay-wage"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payer_id = parse_entity_id(command.character_id)
        worker_id = parse_entity_id(command.payload.get("worker_id"))
        if payer_id is None or worker_id is None:
            return rejected("invalid payer or worker id")
        if not ctx.world.has_entity(worker_id):
            return rejected("worker does not exist")
        payer = ctx.entity(payer_id)
        worker = ctx.entity(worker_id)
        if not _same_room(ctx.world, payer_id, worker_id):
            return rejected("worker is not present")
        amount = int(command.payload.get("amount", 0))
        if amount <= 0:
            return rejected("wage amount must be positive")
        payer_funds = _funds(payer)
        if payer_funds.balance < amount:
            return rejected("insufficient household funds")
        worker_funds = _funds(worker)
        updated_payer = HouseholdFundsComponent(balance=payer_funds.balance - amount)
        updated_worker = HouseholdFundsComponent(balance=worker_funds.balance + amount)
        replace_component(payer, updated_payer)
        replace_component(worker, updated_worker)
        return ok(
            WagePaidEvent(
                **ctx.event_base(
                    visibility=EventVisibility.DIRECTED,
                    actor_id=str(payer_id),
                    target_ids=(str(worker_id),),
                    worker_id=str(worker_id),
                    amount=amount,
                    payer_balance=updated_payer.balance,
                    worker_balance=updated_worker.balance,
                )
            )
        )


class AssessTaxHandler:
    command_type = "assess-tax"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        amount = int(command.payload.get("amount", 0))
        if amount <= 0:
            return rejected("tax amount must be positive")
        reason = str(command.payload.get("reason", "taxes")).strip() or "taxes"
        due_epoch = int(command.payload.get("due_epoch", ctx.epoch))
        actor = ctx.entity(actor_id)
        bill = _create_bill(ctx, actor, amount=amount, reason=reason, due_epoch=due_epoch)
        return ok(
            TaxAssessedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    target_ids=(str(bill.id),),
                    bill_id=str(bill.id),
                    amount=amount,
                    reason=reason,
                )
            ),
            BillCreatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    target_ids=(str(bill.id),),
                    bill_id=str(bill.id),
                    amount=amount,
                    reason=reason,
                    due_epoch=due_epoch,
                )
            ),
        )


class ChargeRentHandler:
    command_type = "charge-rent"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        landlord_id = parse_entity_id(command.character_id)
        tenant_id = parse_entity_id(command.payload.get("tenant_id"))
        if landlord_id is None or tenant_id is None:
            return rejected("invalid landlord or tenant id")
        if not ctx.world.has_entity(tenant_id):
            return rejected("tenant does not exist")
        if not _same_room(ctx.world, landlord_id, tenant_id):
            return rejected("tenant is not present")
        amount = int(command.payload.get("amount", 0))
        if amount <= 0:
            return rejected("rent amount must be positive")
        reason = str(command.payload.get("reason", "rent")).strip() or "rent"
        due_epoch = int(command.payload.get("due_epoch", ctx.epoch))
        tenant = ctx.entity(tenant_id)
        bill = _create_bill(
            ctx,
            tenant,
            amount=amount,
            reason=reason,
            due_epoch=due_epoch,
            creditor_id=str(landlord_id),
        )
        return ok(
            RentChargedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.DIRECTED,
                    actor_id=str(landlord_id),
                    target_ids=(str(tenant_id), str(bill.id)),
                    bill_id=str(bill.id),
                    tenant_id=str(tenant_id),
                    amount=amount,
                    reason=reason,
                )
            ),
            BillCreatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.DIRECTED,
                    actor_id=str(landlord_id),
                    target_ids=(str(tenant_id), str(bill.id)),
                    bill_id=str(bill.id),
                    amount=amount,
                    reason=reason,
                    due_epoch=due_epoch,
                )
            ),
        )


class PayBillHandler:
    command_type = "pay-bill"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        bill_id = parse_entity_id(command.payload.get("bill_id"))
        if actor_id is None:
            return rejected("invalid character id")
        actor = ctx.entity(actor_id)
        if bill_id is None:
            for _edge, candidate_id in actor.get_relationships(HasBill):
                if not ctx.world.has_entity(candidate_id):
                    continue
                candidate = ctx.entity(candidate_id)
                if not candidate.has_component(BillComponent):
                    continue
                if candidate.get_component(BillComponent).paid_at_epoch is None:
                    bill_id = candidate_id
                    break
            if bill_id is None:
                return rejected("no unpaid bills")
        if not ctx.world.has_entity(bill_id):
            return rejected("bill does not exist")
        if not actor.has_relationship(HasBill, bill_id):
            return rejected("bill does not belong to character")
        bill_entity = ctx.entity(bill_id)
        if not bill_entity.has_component(BillComponent):
            return rejected("target is not a bill")
        bill = bill_entity.get_component(BillComponent)
        if bill.paid_at_epoch is not None:
            return rejected("bill is already paid")
        funds = _funds(actor)
        if funds.balance < bill.amount:
            return rejected("insufficient household funds")
        updated_funds = HouseholdFundsComponent(balance=funds.balance - bill.amount)
        replace_component(actor, updated_funds)
        if bill.creditor_id is not None:
            creditor_id = parse_entity_id(bill.creditor_id)
            if creditor_id is not None and ctx.world.has_entity(creditor_id):
                creditor = ctx.entity(creditor_id)
                creditor_funds = _funds(creditor)
                replace_component(
                    creditor,
                    HouseholdFundsComponent(balance=creditor_funds.balance + bill.amount),
                )
        replace_component(bill_entity, replace(bill, paid_at_epoch=ctx.epoch))
        return ok(
            BillPaidEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    target_ids=(str(bill_id),),
                    bill_id=str(bill_id),
                    amount=bill.amount,
                    balance=updated_funds.balance,
                )
            )
        )


class OpenBusinessHandler:
    command_type = "open-business"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        name = str(command.payload.get("name", "")).strip()
        if not name:
            return rejected("business name is required")
        price = int(command.payload.get("default_price", 10))
        if price <= 0:
            return rejected("default price must be positive")
        actor = ctx.entity(actor_id)
        business = spawn_entity(
            ctx.world,
            [BusinessOwnerComponent(name=name, default_price=price)],
        )
        actor.add_relationship(OwnsBusiness(), business.id)
        if not actor.has_component(HouseholdFundsComponent):
            actor.add_component(HouseholdFundsComponent())
        return ok(
            BusinessOpenedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    target_ids=(str(business.id),),
                    business_name=name,
                )
            )
        )


class SellItemHandler:
    command_type = "sell-item"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        item_id = parse_entity_id(command.payload.get("item_id"))
        customer_id = parse_entity_id(command.payload.get("customer_id"))
        if actor_id is None or item_id is None or customer_id is None:
            return rejected("invalid seller, item, or customer id")
        if not ctx.world.has_entity(item_id) or not ctx.world.has_entity(customer_id):
            return rejected("item or customer does not exist")
        actor = ctx.entity(actor_id)
        business_id = parse_entity_id(command.payload.get("business_id"))
        business_entity = _first_business(ctx.world, actor, business_id)
        if business_entity is None:
            return rejected("character has no business")
        if not actor.has_relationship(Contains, item_id):
            return rejected("item is not in inventory")
        customer = ctx.entity(customer_id)
        if not customer.has_component(CustomerComponent):
            return rejected("target is not a customer")
        business = business_entity.get_component(BusinessOwnerComponent)
        price = int(command.payload.get("price", business.default_price))
        if price <= 0:
            return rejected("price must be positive")
        if customer.get_component(CustomerComponent).budget < price:
            return rejected("customer cannot afford item")
        actor.remove_relationship(Contains, item_id)
        funds = (
            actor.get_component(HouseholdFundsComponent)
            if actor.has_component(HouseholdFundsComponent)
            else HouseholdFundsComponent()
        )
        updated_funds = HouseholdFundsComponent(balance=funds.balance + price)
        replace_component(actor, updated_funds)
        replace_component(
            business_entity,
            replace(business, sales_count=business.sales_count + 1),
        )
        customer_budget = customer.get_component(CustomerComponent)
        replace_component(customer, replace(customer_budget, budget=customer_budget.budget - price))
        return ok(
            BusinessSaleEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    target_ids=(str(customer_id), str(item_id)),
                    business_name=business.name,
                    item_id=str(item_id),
                    customer_id=str(customer_id),
                    price=price,
                    balance=updated_funds.balance,
                )
            )
        )


class BuyItemHandler:
    command_type = "buy-item"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        seller_id = parse_entity_id(command.payload.get("seller_id"))
        item_id = parse_entity_id(command.payload.get("item_id"))
        if actor_id is None or seller_id is None or item_id is None:
            return rejected("invalid buyer, seller, or item id")
        if not ctx.world.has_entity(seller_id) or not ctx.world.has_entity(item_id):
            return rejected("seller or item does not exist")
        buyer = ctx.entity(actor_id)
        seller = ctx.entity(seller_id)
        if seller_id not in reachable_ids(ctx.world, buyer):
            return rejected("seller is not reachable")
        if not seller.has_relationship(Contains, item_id):
            return rejected("item is not for sale")

        business_id = parse_entity_id(command.payload.get("business_id"))
        business_entity = _first_business(ctx.world, seller, business_id)
        business = (
            business_entity.get_component(BusinessOwnerComponent)
            if business_entity is not None
            else None
        )
        price = int(command.payload.get("price", business.default_price if business else 0))
        if price <= 0:
            return rejected("price must be positive")
        buyer_funds = _funds(buyer)
        if buyer_funds.balance < price:
            return rejected("insufficient household funds")

        seller.remove_relationship(Contains, item_id)
        buyer.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item_id)
        updated_buyer_funds = HouseholdFundsComponent(balance=buyer_funds.balance - price)
        replace_component(buyer, updated_buyer_funds)
        seller_funds = _funds(seller)
        replace_component(seller, HouseholdFundsComponent(balance=seller_funds.balance + price))
        if business_entity is not None and business is not None:
            replace_component(
                business_entity,
                replace(business, sales_count=business.sales_count + 1),
            )
        return ok(
            BusinessPurchaseEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    target_ids=(str(seller_id), str(item_id)),
                    business_name=business.name if business is not None else "",
                    item_id=str(item_id),
                    seller_id=str(seller_id),
                    price=price,
                    balance=updated_buyer_funds.balance,
                )
            )
        )


class PromoteBusinessHandler:
    command_type = "promote-business"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        actor = ctx.entity(actor_id)
        business_id = parse_entity_id(command.payload.get("business_id"))
        business_entity = _first_business(ctx.world, actor, business_id)
        if business_entity is None:
            return rejected("character has no business")
        business = business_entity.get_component(BusinessOwnerComponent)
        replace_component(business_entity, replace(business, promoted=True))
        return ok(
            BusinessPromotedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    business_name=business.name,
                )
            )
        )


class JoinHouseholdHandler:
    command_type = "join-household"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        household_id = str(command.payload.get("household_id", "")).strip()
        if not household_id:
            return rejected("household id is required")
        household_name = str(command.payload.get("name", "")).strip()
        actor = ctx.entity(actor_id)
        replace_component(
            actor, HouseholdComponent(household_id=household_id, name=household_name)
        )
        return ok(
            HouseholdJoinedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    household_id=household_id,
                    household_name=household_name,
                )
            )
        )


class ClaimHomeHandler:
    command_type = "claim-home"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        room_id = parse_entity_id(command.payload.get("room_id"))
        if actor_id is None:
            return rejected("invalid character id")
        if room_id is None:
            room_id = container_of(ctx.entity(actor_id))
        if room_id is None or not ctx.world.has_entity(room_id):
            return rejected("room does not exist")
        actor = ctx.entity(actor_id)
        household_id = (
            actor.get_component(HouseholdComponent).household_id
            if actor.has_component(HouseholdComponent)
            else None
        )
        room = ctx.entity(room_id)
        replace_component(room, HomeComponent(owner_id=str(actor_id), household_id=household_id))
        return ok(
            HomeClaimedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    room_id=str(room_id),
                    room_id_claimed=str(room_id),
                )
            )
        )


class ClaimRoomHandler:
    command_type = "claim-room"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        room_id = parse_entity_id(command.payload.get("room_id"))
        if actor_id is None:
            return rejected("invalid character id")
        if room_id is None:
            room_id = container_of(ctx.entity(actor_id))
        if room_id is None or not ctx.world.has_entity(room_id):
            return rejected("room does not exist")
        room = ctx.entity(room_id)
        replace_component(
            room,
            RoomClaimComponent(claimed_by_id=str(actor_id), claimed_at_epoch=ctx.epoch),
        )
        return ok(
            RoomClaimedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    room_id=str(room_id),
                    room_id_claimed=str(room_id),
                )
            )
        )


class SetRoutineHandler:
    command_type = "set-routine"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        activity = str(command.payload.get("activity", "")).strip()
        if not activity:
            return rejected("activity is required")
        interval = int(command.payload.get("interval_seconds", 24 * 60 * 60))
        if interval <= 0:
            return rejected("routine interval must be positive")
        next_due = int(command.payload.get("next_due_epoch", ctx.epoch + interval))
        actor = ctx.entity(actor_id)
        existing = _routine_for_activity(ctx.world, actor, activity)
        routine = existing or spawn_entity(ctx.world)
        replace_component(
            routine,
            RoutineComponent(
                activity=activity,
                interval_seconds=interval,
                next_due_epoch=next_due,
            ),
        )
        if existing is None:
            actor.add_relationship(HasRoutine(), routine.id)
        return ok(
            RoutineSetEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    target_ids=(str(routine.id),),
                    activity=activity,
                    next_due_epoch=next_due,
                )
            )
        )


class SetRelationshipStatusHandler:
    command_type = "set-relationship-status"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if actor_id is None or target_id is None:
            return rejected("invalid character or target id")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")
        status = str(command.payload.get("status", "")).strip()
        if status not in {"friend", "rival", "romance", "acquaintance"}:
            return rejected("unsupported relationship status")
        actor = ctx.entity(actor_id)
        target = ctx.entity(target_id)
        if not _active_character(target):
            return rejected("target cannot participate")
        if not _same_room(ctx.world, actor_id, target_id):
            return rejected("target is not present")
        current = _status_edge(actor, target_id)
        if current is not None:
            actor.remove_relationship(RelationshipStatus, target_id)
        actor.add_relationship(RelationshipStatus(status=status, since_epoch=ctx.epoch), target_id)
        return ok(
            RelationshipStatusChangedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=_event_room(ctx.world, actor_id),
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                    status=status,
                )
            )
        )


class SpreadGossipHandler:
    command_type = "spread-gossip"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if actor_id is None or target_id is None:
            return rejected("invalid character or target id")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")
        if not _same_room(ctx.world, actor_id, target_id):
            return rejected("target is not present")
        text = str(command.payload.get("text", "")).strip()
        if not text:
            return rejected("gossip text is required")
        delta = float(command.payload.get("reputation_delta", 0.0))
        target = ctx.entity(target_id)
        current = (
            target.get_component(ReputationComponent)
            if target.has_component(ReputationComponent)
            else ReputationComponent()
        )
        known_for = current.known_for
        if text not in known_for:
            known_for = (*known_for, text)
        replace_component(
            target,
            ReputationComponent(score=current.score + delta, known_for=known_for),
        )
        return ok(
            GossipSpreadEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=_event_room(ctx.world, actor_id),
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                    text=text,
                    reputation_delta=delta,
                )
            )
        )


class WitnessRomanceHandler:
    command_type = "witness-romance"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        partner_id = parse_entity_id(command.payload.get("partner_id"))
        rival_id = parse_entity_id(command.payload.get("rival_id"))
        if actor_id is None or partner_id is None or rival_id is None:
            return rejected("invalid witness, partner, or rival id")
        if not ctx.world.has_entity(partner_id) or not ctx.world.has_entity(rival_id):
            return rejected("partner or rival does not exist")
        actor = ctx.entity(actor_id)
        if _partner_edge(actor, partner_id) is None:
            return rejected("witness is not partners with partner")
        if not _same_room(ctx.world, actor_id, partner_id) or not _same_room(
            ctx.world, actor_id, rival_id
        ):
            return rejected("participants are not present")
        intensity = float(command.payload.get("intensity", 0.5))
        actor.add_relationship(
            JealousOf(
                partner_id=str(partner_id),
                intensity=intensity,
                triggered_at_epoch=ctx.epoch,
            ),
            rival_id,
        )
        return ok(
            JealousyTriggeredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
                    target_ids=(str(partner_id), str(rival_id)),
                    partner_id=str(partner_id),
                    rival_id=str(rival_id),
                    intensity=intensity,
                )
            )
        )


class StartPartnershipHandler:
    command_type = "start-partnership"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if actor_id is None or target_id is None:
            return rejected("invalid character or target id")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")

        actor = ctx.entity(actor_id)
        target = ctx.entity(target_id)
        if not _active_character(target):
            return rejected("target cannot participate")
        if not _same_room(ctx.world, actor_id, target_id):
            return rejected("target is not present")
        if _partner_edge(actor, target_id) is not None:
            return rejected("already partners")

        edge = PartnerOf(since_epoch=ctx.epoch)
        actor.add_relationship(edge, target_id)
        target.add_relationship(edge, actor_id)
        return ok(
            PartnershipStartedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=_event_room(ctx.world, actor_id),
                    target_ids=(str(target_id),),
                    partner_id=str(target_id),
                )
            )
        )


class EndPartnershipHandler:
    command_type = "end-partnership"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if actor_id is None or target_id is None:
            return rejected("invalid character or target id")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")

        actor = ctx.entity(actor_id)
        target = ctx.entity(target_id)
        if _partner_edge(actor, target_id) is None:
            return rejected("not partners")

        actor.remove_relationship(PartnerOf, target_id)
        if target.has_relationship(PartnerOf, actor_id):
            target.remove_relationship(PartnerOf, actor_id)
        return ok(
            PartnershipEndedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=_event_room(ctx.world, actor_id),
                    target_ids=(str(target_id),),
                    partner_id=str(target_id),
                )
            )
        )


class StartPregnancyHandler:
    command_type = "start-pregnancy"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
        actor_id = parse_entity_id(command.character_id)
        co_parent_id = parse_entity_id(payload.get("co_parent_id"))
        if actor_id is None or co_parent_id is None:
            return rejected("invalid character or co-parent id")
        if not ctx.world.has_entity(co_parent_id):
            return rejected("co-parent does not exist")

        actor = ctx.entity(actor_id)
        co_parent = ctx.entity(co_parent_id)
        if not _active_character(actor) or not _active_character(co_parent):
            return rejected("participant cannot participate")
        if not _same_room(ctx.world, actor_id, co_parent_id):
            return rejected("co-parent is not present")
        if actor.has_component(PregnancyComponent) or actor.has_component(BirthDueComponent):
            return rejected("already pregnant")

        pregnant = (
            actor.get_component(ReproductiveComponent)
            if actor.has_component(ReproductiveComponent)
            else None
        )
        causing = (
            co_parent.get_component(ReproductiveComponent)
            if co_parent.has_component(ReproductiveComponent)
            else None
        )
        if pregnant is None or not pregnant.can_be_pregnant or pregnant.pregnancy_blocked:
            return rejected("character cannot become pregnant")
        if causing is None or not causing.can_cause_pregnancy or causing.pregnancy_blocked:
            return rejected("co-parent cannot cause pregnancy")
        if pregnant.species_group != causing.species_group:
            return rejected("participants are not reproductively compatible")
        if pregnant.fertility <= 0 or causing.fertility <= 0:
            return rejected("fertility prevents pregnancy")

        due_in = int(payload.get("due_in_seconds", DEFAULT_PREGNANCY_SECONDS))
        if due_in <= 0:
            return rejected("due time must be in the future")
        pregnancy = PregnancyComponent(
            started_at_epoch=ctx.epoch,
            due_at_epoch=ctx.epoch + due_in,
            co_parent_ids=(str(co_parent_id),),
            source_event_id=command.command_id,
        )
        replace_component(actor, pregnancy)
        return ok(
            PregnancyStartedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.DIRECTED,
                    actor_id=str(actor_id),
                    room_id=_event_room(ctx.world, actor_id),
                    target_ids=(str(co_parent_id),),
                    pregnant_id=str(actor_id),
                    co_parent_ids=(str(co_parent_id),),
                    due_at_epoch=pregnancy.due_at_epoch,
                )
            )
        )


class ResolveBirthHandler:
    command_type = "resolve-birth"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        actor = ctx.entity(actor_id)
        if not actor.has_component(PregnancyComponent) or not actor.has_component(
            BirthDueComponent
        ):
            return rejected("birth is not due")

        child_name = str(command.payload.get("child_name", "Child")).strip() or "Child"
        child = spawn_entity(
            ctx.world,
            [
                IdentityComponent(name=child_name, kind="character"),
                CharacterComponent(species=actor.get_component(CharacterComponent).species),
                AgeComponent(born_at_epoch=ctx.epoch),
                LifeStageComponent(stage="child"),
            ],
        )
        controller = spawn_entity(
            ctx.world,
            [LLMControllerComponent(profile_name="default", model="claude")],
        )
        child.add_relationship(ControlledBy(generation=0, since_epoch=ctx.epoch), controller.id)
        room_id = container_of(actor)
        if room_id is not None:
            ctx.entity(room_id).add_relationship(
                Contains(mode=ContainmentMode.ROOM_CONTENT), child.id
            )

        pregnancy = actor.get_component(PregnancyComponent)
        actor.add_relationship(ParentOf(), child.id)
        for raw_id in pregnancy.co_parent_ids:
            co_parent_id = parse_entity_id(raw_id)
            if co_parent_id is not None and ctx.world.has_entity(co_parent_id):
                ctx.entity(co_parent_id).add_relationship(ParentOf(), child.id)

        actor.remove_component(PregnancyComponent)
        actor.remove_component(BirthDueComponent)
        return ok(
            BirthResolvedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=str(room_id) if room_id is not None else None,
                    target_ids=(str(child.id), *pregnancy.co_parent_ids),
                    child_id=str(child.id),
                    parent_ids=(str(actor_id), *pregnancy.co_parent_ids),
                )
            )
        )


class AdoptChildHandler:
    command_type = "adopt-child"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        child_id = parse_entity_id(command.payload.get("child_id"))
        if actor_id is None or child_id is None:
            return rejected("invalid parent or child id")
        if not ctx.world.has_entity(child_id):
            return rejected("child does not exist")

        actor = ctx.entity(actor_id)
        child = ctx.entity(child_id)
        if not _active_character(actor) or not _active_character(child):
            return rejected("participant cannot participate")
        if not _same_room(ctx.world, actor_id, child_id):
            return rejected("child is not present")
        if not child.has_component(LifeStageComponent) or child.get_component(
            LifeStageComponent
        ).stage != "child":
            return rejected("target is not a child")
        if actor.has_relationship(ParentOf, child_id):
            return rejected("already parent of child")

        actor.add_relationship(ParentOf(), child_id)
        return ok(
            AdoptionCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(actor_id),
                    room_id=_event_room(ctx.world, actor_id),
                    target_ids=(str(child_id),),
                    child_id=str(child_id),
                    parent_id=str(actor_id),
                )
            )
        )


class PregnancyDueConsequence:
    """Mark due pregnancies without resolving birth, including while suspended."""

    def process(self, world: World, epoch: int):
        events = []
        query = (
            world.query()
            .with_all([PregnancyComponent, CharacterComponent])
            .with_none([BirthDueComponent, DeadComponent])
        )
        for entity in query.execute_entities():
            pregnancy = entity.get_component(PregnancyComponent)
            if pregnancy.due_at_epoch > epoch:
                continue
            entity.add_component(BirthDueComponent(due_since_epoch=epoch))
            events.append(
                BirthDueEvent(
                    **_event_base(
                        epoch,
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(entity.id),
                        target_ids=pregnancy.co_parent_ids,
                        pregnant_id=str(entity.id),
                        due_since_epoch=epoch,
                    )
                )
            )
        return events


class AgingConsequence:
    """Advance lifesim age stages and hand terminal ageing to the core death lifecycle."""

    def process(self, world: World, epoch: int):
        policy = _lifesim_aging_policy(world)
        if not policy.natural_aging:
            return []

        query = (
            world.query()
            .with_all([AgeComponent, CharacterComponent])
            .with_none([SuspendedComponent, DeadComponent])
        )
        for entity in query.execute_entities():
            age = max(0, epoch - entity.get_component(AgeComponent).born_at_epoch)
            if entity.has_component(LifeStageComponent):
                stage = entity.get_component(LifeStageComponent)
            else:
                stage = LifeStageComponent()

            next_stage = stage.stage
            if age >= policy.elder_age_seconds:
                next_stage = "elder"
            elif age >= policy.adult_age_seconds:
                next_stage = "adult"

            if next_stage != stage.stage:
                replace_component(entity, replace(stage, stage=next_stage))

            if (
                age >= policy.natural_death_age_seconds
                and not entity.has_component(DownedComponent)
            ):
                if entity.has_component(HealthComponent):
                    health = entity.get_component(HealthComponent)
                    replace_component(entity, replace(health, current=0.0))
                else:
                    replace_component(entity, HealthComponent(current=0.0, maximum=100.0))
                replace_component(
                    entity,
                    DownedComponent(
                        downed_at_epoch=epoch,
                        cause="natural causes",
                        checks_remaining=max(1, policy.natural_death_checks),
                    ),
                )
        return []


class RoutineDueConsequence:
    """Emit routine reminders without submitting autonomous commands."""

    def process(self, world: World, epoch: int):
        events = []
        for routine_entity in world.query().with_all([RoutineComponent]).execute_entities():
            routine = routine_entity.get_component(RoutineComponent)
            if routine.next_due_epoch > epoch:
                continue
            owners = [
                source_id
                for source_id, _edge in routine_entity.get_incoming_relationships(HasRoutine)
                if world.has_entity(source_id)
                and not world.get_entity(source_id).has_component(DeadComponent)
            ]
            if not owners:
                continue
            updated = replace(
                routine,
                last_completed_epoch=epoch,
                next_due_epoch=epoch + routine.interval_seconds,
            )
            replace_component(routine_entity, updated)
            for owner_id in owners:
                events.append(
                    RoutineDueEvent(
                        **_event_base(
                            epoch,
                            visibility=EventVisibility.PRIVATE,
                            actor_id=str(owner_id),
                            target_ids=(str(routine_entity.id),),
                            activity=routine.activity,
                            next_due_epoch=updated.next_due_epoch,
                        )
                    )
                )
        return events


class RestfulSleepConsequence:
    """Reward sleeping in a room you own or claim with a temporary well-rested buff.

    While a character sleeps in their own home or a claimed room, a HomeRestComponent
    tracks the rest in progress. On waking, a long-enough rest becomes a
    WellRestedComponent buff that boosts skill learning; the marker is cleared. Sleeping
    elsewhere grants nothing, and expired buffs are removed (spec 20.5).
    """

    def process(self, world: World, epoch: int):
        events = []
        # Track in-progress home rest for characters currently asleep at home.
        sleeping = (
            world.query()
            .with_all([SleepingComponent, CharacterComponent])
            .with_none([SuspendedComponent, DeadComponent, DownedComponent])
        )
        for entity in sleeping.execute_entities():
            room_id = container_of(entity)
            at_home = (
                room_id is not None
                and world.has_entity(room_id)
                and _owns_or_claims_room(entity.id, world.get_entity(room_id))
            )
            if at_home and not entity.has_component(HomeRestComponent):
                started = entity.get_component(SleepingComponent).started_at_epoch
                entity.add_component(
                    HomeRestComponent(asleep_since_epoch=started, room_id=str(room_id))
                )
            elif not at_home and entity.has_component(HomeRestComponent):
                # Moved out of their home while asleep: the rest no longer counts.
                entity.remove_component(HomeRestComponent)

        # Convert finished home rest into a buff for characters who have since woken.
        for entity in world.query().with_all([HomeRestComponent]).execute_entities():
            if entity.has_component(SleepingComponent):
                continue
            rest = entity.get_component(HomeRestComponent)
            entity.remove_component(HomeRestComponent)
            slept = epoch - rest.asleep_since_epoch
            if slept < MIN_RESTFUL_SLEEP_SECONDS:
                continue
            expires = epoch + min(slept, MAX_WELL_RESTED_SECONDS)
            replace_component(entity, WellRestedComponent(expires_at_epoch=expires))
            events.append(
                WellRestedEvent(
                    **_event_base(
                        epoch,
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(entity.id),
                        room_id=rest.room_id,
                        slept_seconds=int(slept),
                        expires_at_epoch=expires,
                    )
                )
            )

        # Drop buffs whose window has elapsed.
        for entity in world.query().with_all([WellRestedComponent]).execute_entities():
            if entity.get_component(WellRestedComponent).expires_at_epoch <= epoch:
                entity.remove_component(WellRestedComponent)

        return events


def lifesim_fragments(world: World, character: Entity) -> list[str]:
    lines: list[str] = []
    if character.has_component(LifeStageComponent):
        lines.append(f"Your life stage is {character.get_component(LifeStageComponent).stage}.")
    if character.has_component(CharacterProfileComponent):
        profile = character.get_component(CharacterProfileComponent)
        if profile.traits:
            lines.append("Your traits: " + ", ".join(profile.traits) + ".")
        if profile.interests:
            lines.append("Your interests: " + ", ".join(profile.interests) + ".")
        if profile.preferred_routine:
            lines.append(f"Your preferred routine is {profile.preferred_routine}.")
    if character.has_component(AspirationComponent):
        aspiration = character.get_component(AspirationComponent)
        if aspiration.completed:
            done = ", ".join(aspiration.completed)
            lines.append(f"Your aspiration is {aspiration.name}; completed: {done}.")
        else:
            lines.append(f"Your aspiration is {aspiration.name}.")
    if character.has_component(CareerComponent):
        career = character.get_component(CareerComponent)
        if career.active:
            lines.append(f"Your career is {career.title}, level {career.level}.")
    if character.has_component(HouseholdFundsComponent):
        funds = character.get_component(HouseholdFundsComponent)
        lines.append(f"Household funds: {funds.balance}.")
    unpaid_bills = []
    for _edge, bill_id in character.get_relationships(HasBill):
        if not world.has_entity(bill_id):
            continue
        bill_entity = world.get_entity(bill_id)
        if not bill_entity.has_component(BillComponent):
            continue
        bill = bill_entity.get_component(BillComponent)
        if bill.paid_at_epoch is None:
            unpaid_bills.append(f"{bill.reason} ({bill.amount})")
    if unpaid_bills:
        lines.append("Unpaid bills: " + ", ".join(sorted(unpaid_bills)) + ".")
    for _edge, business_id in character.get_relationships(OwnsBusiness):
        if not world.has_entity(business_id):
            continue
        business_entity = world.get_entity(business_id)
        if business_entity.has_component(BusinessOwnerComponent):
            business = business_entity.get_component(BusinessOwnerComponent)
            lines.append(f"You own {business.name}; {business.sales_count} sales.")
    if character.has_component(HouseholdComponent):
        household = character.get_component(HouseholdComponent)
        label = household.name or household.household_id
        lines.append(f"Your household is {label}.")
    for room in world.query().with_all([HomeComponent, RoomComponent]).execute_entities():
        home = room.get_component(HomeComponent)
        if home.owner_id == str(character.id):
            title = room.get_component(RoomComponent).title
            lines.append(f"Your home is {title}.")
    claimed_rooms = []
    for room in world.query().with_all([RoomClaimComponent, RoomComponent]).execute_entities():
        claim = room.get_component(RoomClaimComponent)
        if claim.claimed_by_id == str(character.id):
            claimed_rooms.append(room.get_component(RoomComponent).title)
    if claimed_rooms:
        lines.append("Rooms you claim: " + ", ".join(sorted(claimed_rooms)) + ".")
    if character.has_component(WellRestedComponent):
        lines.append("You are well-rested after sleeping in your own home.")
    for _edge, whim_id in character.get_relationships(HasWhim):
        if not world.has_entity(whim_id):
            continue
        whim_entity = world.get_entity(whim_id)
        if not whim_entity.has_component(WhimComponent):
            continue
        whim = whim_entity.get_component(WhimComponent)
        if whim.completed_at_epoch is None:
            lines.append(f"Current whim: {whim.want}.")
    for _edge, routine_id in character.get_relationships(HasRoutine):
        if not world.has_entity(routine_id):
            continue
        routine_entity = world.get_entity(routine_id)
        if routine_entity.has_component(RoutineComponent):
            routine = routine_entity.get_component(RoutineComponent)
            lines.append(f"Routine: {routine.activity} due at epoch {routine.next_due_epoch}.")
    if character.has_component(ReputationComponent):
        reputation = character.get_component(ReputationComponent)
        if reputation.known_for:
            lines.append("You are known for: " + ", ".join(reputation.known_for) + ".")
    if character.has_component(SkillSetComponent):
        skills = character.get_component(SkillSetComponent)
        for skill, level in sorted(skills.levels.items()):
            xp = skills.xp.get(skill, 0.0)
            lines.append(f"Skill {skill}: level {level}, {xp:g} xp.")
    for edge, rival_id in character.get_relationships(JealousOf):
        rival_name = "someone"
        partner_name = "someone"
        if world.has_entity(rival_id):
            rival = world.get_entity(rival_id)
            if rival.has_component(IdentityComponent):
                rival_name = rival.get_component(IdentityComponent).name
        partner_id = parse_entity_id(edge.partner_id)
        if partner_id is not None and world.has_entity(partner_id):
            partner = world.get_entity(partner_id)
            if partner.has_component(IdentityComponent):
                partner_name = partner.get_component(IdentityComponent).name
        lines.append(f"You feel jealous of {rival_name} over {partner_name}.")
    if character.has_component(PregnancyComponent):
        pregnancy = character.get_component(PregnancyComponent)
        due = (
            "due now"
            if character.has_component(BirthDueComponent)
            else f"due at epoch {pregnancy.due_at_epoch}"
        )
        lines.append(f"You are pregnant ({due}).")
    for edge, target_id in character.get_relationships(PartnerOf):
        if not world.has_entity(target_id) or edge.status != "together":
            continue
        target = world.get_entity(target_id)
        name = (
            target.get_component(IdentityComponent).name
            if target.has_component(IdentityComponent)
            else "someone"
        )
        lines.append(f"You are partners with {name}.")
    for edge, target_id in character.get_relationships(RelationshipStatus):
        if not world.has_entity(target_id):
            continue
        target = world.get_entity(target_id)
        name = (
            target.get_component(IdentityComponent).name
            if target.has_component(IdentityComponent)
            else "someone"
        )
        lines.append(f"{name} is your {edge.status}.")
    children = [
        world.get_entity(child_id).get_component(IdentityComponent).name
        if world.has_entity(child_id)
        and world.get_entity(child_id).has_component(IdentityComponent)
        else "someone"
        for _edge, child_id in character.get_relationships(ParentOf)
        if world.has_entity(child_id)
    ]
    if children:
        lines.append("Your children: " + ", ".join(sorted(children)) + ".")
    parents = []
    for parent in world.query().with_all([CharacterComponent]).execute_entities():
        if parent.has_relationship(ParentOf, character.id):
            name = (
                parent.get_component(IdentityComponent).name
                if parent.has_component(IdentityComponent)
                else "someone"
            )
            parents.append(name)
    if parents:
        lines.append("Your parents: " + ", ".join(sorted(parents)) + ".")
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        if entity.has_component(HomeObjectComponent):
            home_object = entity.get_component(HomeObjectComponent)
            name = (
                entity.get_component(IdentityComponent).name
                if entity.has_component(IdentityComponent)
                else "home object"
            )
            lines.append(
                f"Nearby home object: {name} offers {home_object.affordance}, "
                f"condition {home_object.condition:.1f}, clean {home_object.cleanliness:.1f}."
            )
    policy = _lifesim_aging_policy(world)
    lines.append("Natural aging is on." if policy.natural_aging else "Natural aging is off.")
    return sorted(lines)


def install_lifesim(actor, *, natural_aging: bool | None = None) -> None:
    configure_lifesim_aging(actor, natural_aging=natural_aging)
    actor.register_consequence(AgingConsequence())
    actor.register_consequence(PregnancyDueConsequence())
    actor.register_consequence(RoutineDueConsequence())
    actor.register_consequence(RestfulSleepConsequence())
    actor.register_gate(PolicyGate((romance_classifier, adult_classifier, pregnancy_classifier)))


__all__ = [
    "AspirationChosenEvent",
    "AspirationComponent",
    "AssessTaxHandler",
    "BillComponent",
    "BillCreatedEvent",
    "BillPaidEvent",
    "BirthDueComponent",
    "AdoptChildHandler",
    "BusinessOpenedEvent",
    "BusinessOwnerComponent",
    "BusinessPromotedEvent",
    "BusinessPurchaseEvent",
    "BusinessSaleEvent",
    "BuyItemHandler",
    "CareerComponent",
    "CareerStartedEvent",
    "CharacterProfileComponent",
    "ChargeRentHandler",
    "ChooseAspirationHandler",
    "ClaimHomeHandler",
    "ClaimRoomHandler",
    "AddWhimHandler",
    "CompleteWhimHandler",
    "CompleteMilestoneHandler",
    "ConfigureAgingHandler",
    "CustomerComponent",
    "EndPartnershipHandler",
    "FindJobHandler",
    "GoToWorkHandler",
    "GossipSpreadEvent",
    "HasBill",
    "HasRoutine",
    "HasWhim",
    "HomeClaimedEvent",
    "HomeComponent",
    "HomeObjectComponent",
    "HomeObjectMaintainedEvent",
    "HomeObjectUsedEvent",
    "HomeRestComponent",
    "HouseholdComponent",
    "HouseholdFundsComponent",
    "HouseholdJoinedEvent",
    "InvitationSentEvent",
    "InviteOverHandler",
    "JoinHouseholdHandler",
    "JobScheduleComponent",
    "JealousOf",
    "JealousyTriggeredEvent",
    "AgeComponent",
    "AgingConsequence",
    "LifeStageComponent",
    "LifesimAgingPolicyChangedEvent",
    "LifesimAgingPolicyComponent",
    "MentorSkillHandler",
    "MentorshipCompletedEvent",
    "MilestoneCompletedEvent",
    "MilestoneComponent",
    "OpenBusinessHandler",
    "OwnsBusiness",
    "ParentOf",
    "PartnerOf",
    "PayBillHandler",
    "PayWageHandler",
    "PracticeSkillHandler",
    "PregnancyComponent",
    "PregnancyDueConsequence",
    "PromotionEarnedEvent",
    "PromoteBusinessHandler",
    "QuitJobHandler",
    "ReproductiveComponent",
    "ReputationComponent",
    "RentChargedEvent",
    "ResolveBirthHandler",
    "RestfulSleepConsequence",
    "RoomClaimComponent",
    "RoomClaimedEvent",
    "RoutineComponent",
    "RoutineDueConsequence",
    "RoutineDueEvent",
    "RoutineSetEvent",
    "RelationshipStatus",
    "RelationshipStatusChangedEvent",
    "SetRoutineHandler",
    "SetRelationshipStatusHandler",
    "SkillLeveledEvent",
    "SkillSetComponent",
    "SkillXPChangedEvent",
    "SpreadGossipHandler",
    "StartPartnershipHandler",
    "StartPregnancyHandler",
    "StudySkillHandler",
    "SellItemHandler",
    "TaxAssessedEvent",
    "WagePaidEvent",
    "WellRestedComponent",
    "WellRestedEvent",
    "WhimAddedEvent",
    "WhimCompletedEvent",
    "WhimComponent",
    "WorkShiftCompletedEvent",
    "MaintainHomeObjectHandler",
    "ProfileUpdatedEvent",
    "UpdateProfileHandler",
    "WitnessRomanceHandler",
    "adult_classifier",
    "children_of",
    "configure_lifesim_aging",
    "install_lifesim",
    "kinship_label",
    "lifesim_fragments",
    "parents_of",
    "partners_of",
    "pregnancy_classifier",
    "romance_classifier",
]
