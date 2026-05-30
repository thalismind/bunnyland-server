"""Life-sim relationships, family, and pregnancy mechanics (spec 20.5-20.6).

Major life-sim state transitions are explicit command handlers and typed events. Prose
may describe intent, but only these handlers create partnership, pregnancy, birth, and
family ECS state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
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
    IdentityComponent,
    SuspendedComponent,
)
from ..core.controllers import LLMControllerComponent
from ..core.ecs import container_of, parse_entity_id, replace_component, spawn_entity
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


@dataclass(frozen=True)
class LifeStageComponent(Component):
    stage: str = "adult"


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
class RoutineComponent(Component):
    activity: str
    interval_seconds: int = 24 * 60 * 60
    next_due_epoch: int = 0
    last_completed_epoch: int | None = None


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
class PartnerOf(Edge):
    since_epoch: int
    status: str = "together"


@dataclass(frozen=True)
class RelationshipStatus(Edge):
    status: str
    since_epoch: int


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


class BusinessPromotedEvent(DomainEvent):
    business_name: str


class HouseholdJoinedEvent(DomainEvent):
    household_id: str
    household_name: str = ""


class HomeClaimedEvent(DomainEvent):
    room_id_claimed: str


class RoomClaimedEvent(DomainEvent):
    room_id_claimed: str


class RoutineSetEvent(DomainEvent):
    activity: str
    next_due_epoch: int


class RoutineDueEvent(DomainEvent):
    activity: str
    next_due_epoch: int


class RelationshipStatusChangedEvent(DomainEvent):
    target_id: str
    status: str

def _participant_ids(command: SubmittedCommand, *payload_keys: str) -> list[str]:
    ids = [command.character_id]
    for key in payload_keys:
        raw = command.payload.get(key)
        if raw is not None:
            ids.append(str(raw))
    return ids


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


def _same_room(world: World, left_id: EntityId, right_id: EntityId) -> bool:
    return container_of(world.get_entity(left_id)) == container_of(world.get_entity(right_id))


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
        replace_component(actor, BusinessOwnerComponent(name=name, default_price=price))
        if not actor.has_component(HouseholdFundsComponent):
            actor.add_component(HouseholdFundsComponent())
        return ok(
            BusinessOpenedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
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
        if not actor.has_component(BusinessOwnerComponent):
            return rejected("character has no business")
        if not actor.has_relationship(Contains, item_id):
            return rejected("item is not in inventory")
        customer = ctx.entity(customer_id)
        if not customer.has_component(CustomerComponent):
            return rejected("target is not a customer")
        business = actor.get_component(BusinessOwnerComponent)
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
            actor,
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


class PromoteBusinessHandler:
    command_type = "promote-business"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        actor_id = parse_entity_id(command.character_id)
        if actor_id is None:
            return rejected("invalid character id")
        actor = ctx.entity(actor_id)
        if not actor.has_component(BusinessOwnerComponent):
            return rejected("character has no business")
        business = actor.get_component(BusinessOwnerComponent)
        replace_component(actor, replace(business, promoted=True))
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
        replace_component(
            actor,
            RoutineComponent(
                activity=activity,
                interval_seconds=interval,
                next_due_epoch=next_due,
            ),
        )
        return ok(
            RoutineSetEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(actor_id),
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


class RoutineDueConsequence:
    """Emit routine reminders without submitting autonomous commands."""

    def process(self, world: World, epoch: int):
        events = []
        for entity in (
            world.query()
            .with_all([RoutineComponent, CharacterComponent])
            .with_none([DeadComponent])
            .execute_entities()
        ):
            routine = entity.get_component(RoutineComponent)
            if routine.next_due_epoch > epoch:
                continue
            updated = replace(
                routine,
                last_completed_epoch=epoch,
                next_due_epoch=epoch + routine.interval_seconds,
            )
            replace_component(entity, updated)
            events.append(
                RoutineDueEvent(
                    **_event_base(
                        epoch,
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(entity.id),
                        activity=routine.activity,
                        next_due_epoch=updated.next_due_epoch,
                    )
                )
            )
        return events


def lifesim_fragments(world: World, character: Entity) -> list[str]:
    lines: list[str] = []
    if character.has_component(LifeStageComponent):
        lines.append(f"Your life stage is {character.get_component(LifeStageComponent).stage}.")
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
    if character.has_component(BusinessOwnerComponent):
        business = character.get_component(BusinessOwnerComponent)
        lines.append(f"You own {business.name}; {business.sales_count} sales.")
    if character.has_component(HouseholdComponent):
        household = character.get_component(HouseholdComponent)
        label = household.name or household.household_id
        lines.append(f"Your household is {label}.")
    if character.has_component(RoutineComponent):
        routine = character.get_component(RoutineComponent)
        lines.append(f"Routine: {routine.activity} due at epoch {routine.next_due_epoch}.")
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
    return sorted(lines)


def install_lifesim(actor) -> None:
    actor.register_consequence(PregnancyDueConsequence())
    actor.register_consequence(RoutineDueConsequence())
    actor.register_gate(PolicyGate((romance_classifier, adult_classifier, pregnancy_classifier)))


__all__ = [
    "AspirationChosenEvent",
    "AspirationComponent",
    "BirthDueComponent",
    "AdoptChildHandler",
    "BusinessOpenedEvent",
    "BusinessOwnerComponent",
    "BusinessPromotedEvent",
    "BusinessSaleEvent",
    "CareerComponent",
    "CareerStartedEvent",
    "ChooseAspirationHandler",
    "ClaimHomeHandler",
    "ClaimRoomHandler",
    "CompleteMilestoneHandler",
    "CustomerComponent",
    "EndPartnershipHandler",
    "FindJobHandler",
    "GoToWorkHandler",
    "HomeClaimedEvent",
    "HomeComponent",
    "HouseholdComponent",
    "HouseholdFundsComponent",
    "HouseholdJoinedEvent",
    "JoinHouseholdHandler",
    "JobScheduleComponent",
    "LifeStageComponent",
    "MilestoneCompletedEvent",
    "MilestoneComponent",
    "OpenBusinessHandler",
    "ParentOf",
    "PartnerOf",
    "PregnancyComponent",
    "PregnancyDueConsequence",
    "PromotionEarnedEvent",
    "PromoteBusinessHandler",
    "QuitJobHandler",
    "ReproductiveComponent",
    "ResolveBirthHandler",
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
    "StartPartnershipHandler",
    "StartPregnancyHandler",
    "SellItemHandler",
    "WorkShiftCompletedEvent",
    "adult_classifier",
    "install_lifesim",
    "lifesim_fragments",
    "pregnancy_classifier",
    "romance_classifier",
]
