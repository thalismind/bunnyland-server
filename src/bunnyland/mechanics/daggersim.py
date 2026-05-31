"""Dagger-sim procedural RPG realm mechanics.

This package owns the gameplay reasons for expanding civic RPG content. Worldgen may
propose the actual rooms and entities later; dagger-sim tracks when a stub location has
become real enough for play to reference.
"""

from __future__ import annotations

from dataclasses import replace

from pydantic.dataclasses import dataclass
from relics import Component, Edge, Entity, EntityId, World

from ..core.commands import SubmittedCommand
from ..core.components import HealthComponent, IdentityComponent
from ..core.ecs import container_of, parse_entity_id, reachable_ids, replace_component
from ..core.edges import ContainmentMode, Contains
from ..core.events import DomainEvent, EventVisibility
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected


@dataclass(frozen=True)
class ProceduralSiteComponent(Component):
    site_type: str
    seed: str
    generated: bool = False
    generator_id: str | None = None


@dataclass(frozen=True)
class UnrealizedLocationComponent(Component):
    summary: str
    region_id: str
    detail_level: str = "stub"


@dataclass(frozen=True)
class ExpansionHookComponent(Component):
    trigger: str
    generator_plugin_id: str
    priority: int = 0


@dataclass(frozen=True)
class RumorComponent(Component):
    text: str
    heard_by: tuple[str, ...] = ()
    state: str = "unverified"


@dataclass(frozen=True)
class RumorSourceComponent(Component):
    source_id: str | None = None


@dataclass(frozen=True)
class RumorReliabilityComponent(Component):
    score: float = 1.0


@dataclass(frozen=True)
class RumorTargetComponent(Component):
    target_id: str


@dataclass(frozen=True)
class TravelHubComponent(Component):
    name: str
    region_id: str = ""


@dataclass(frozen=True)
class TravelModeComponent(Component):
    mode: str = "foot"
    speed_multiplier: float = 1.0


@dataclass(frozen=True)
class TravelPlanComponent(Component):
    destination_id: str
    started_at_epoch: int
    arrive_at_epoch: int
    mode: str = "foot"
    route_label: str = ""


@dataclass(frozen=True)
class TravelRoute(Edge):
    travel_seconds: int
    label: str = ""


@dataclass(frozen=True)
class InstitutionComponent(Component):
    name: str
    institution_type: str = "guild"


@dataclass(frozen=True)
class InstitutionServiceComponent(Component):
    service_name: str
    required_rank: str = "member"
    output_item_name: str | None = None


@dataclass(frozen=True)
class MemberOfInstitution(Edge):
    rank: str = "member"
    since_epoch: int = 0


@dataclass(frozen=True)
class QuestTemplateComponent(Component):
    title: str
    objective: str
    reward_item_name: str
    duration_seconds: int = 24 * 60 * 60


@dataclass(frozen=True)
class GeneratedQuestComponent(Component):
    title: str
    objective: str
    status: str = "offered"
    accepted_by: str | None = None


@dataclass(frozen=True)
class QuestDeadlineComponent(Component):
    due_at_epoch: int


@dataclass(frozen=True)
class DaggerQuestRewardComponent(Component):
    item_name: str
    claimed: bool = False
    claimed_by: str | None = None


@dataclass(frozen=True)
class BankComponent(Component):
    name: str
    region_id: str = ""


@dataclass(frozen=True)
class BankAccountComponent(Component):
    bank_id: str
    owner_id: str
    balance: int = 0


@dataclass(frozen=True)
class LoanComponent(Component):
    bank_id: str
    borrower_id: str
    principal: int
    balance: int
    due_at_epoch: int
    status: str = "active"


@dataclass(frozen=True)
class DebtComponent(Component):
    amount: int
    defaulted_at_epoch: int


@dataclass(frozen=True)
class LawRegionComponent(Component):
    region_id: str
    fines: dict[str, int]


@dataclass(frozen=True)
class CrimeRecordComponent(Component):
    crime_type: str
    region_id: str
    fine: int
    status: str = "open"


@dataclass(frozen=True)
class BountyComponent(Component):
    amount: int
    region_id: str


@dataclass(frozen=True)
class ClassTemplateComponent(Component):
    class_name: str
    primary_skills: tuple[str, ...] = ()
    major_skills: tuple[str, ...] = ()
    minor_skills: tuple[str, ...] = ()
    advantages: tuple[str, ...] = ()
    disadvantages: tuple[str, ...] = ()


@dataclass(frozen=True)
class CustomClassComponent(Component):
    class_name: str
    primary_skills: tuple[str, ...] = ()
    major_skills: tuple[str, ...] = ()
    minor_skills: tuple[str, ...] = ()
    advantages: tuple[str, ...] = ()
    disadvantages: tuple[str, ...] = ()
    finalized_at_epoch: int = 0


@dataclass(frozen=True)
class SpellTemplateComponent(Component):
    spell_name: str
    effect_type: str
    magnitude: float
    cost: int = 1


@dataclass(frozen=True)
class CustomSpellComponent(Component):
    spell_name: str
    effect_type: str
    magnitude: float
    cost: int = 1
    creator_id: str | None = None


@dataclass(frozen=True)
class LanguageSkillComponent(Component):
    languages: dict[str, int]


@dataclass(frozen=True)
class CreatureLanguageComponent(Component):
    language: str
    pacification_difficulty: int = 1


@dataclass(frozen=True)
class HostilityComponent(Component):
    hostile: bool = True


@dataclass(frozen=True)
class PacifiedComponent(Component):
    pacified_by: str
    language: str
    pacified_at_epoch: int


class ExpansionRequestedEvent(DomainEvent):
    site_id: str
    site_type: str
    trigger: str
    generator_plugin_id: str | None = None


class GeneratedSiteInstantiatedEvent(DomainEvent):
    site_id: str
    site_type: str
    detail_level: str
    generator_plugin_id: str | None = None


class RumorHeardEvent(DomainEvent):
    rumor_id: str
    text: str


class RumorVerifiedEvent(DomainEvent):
    rumor_id: str
    text: str


class RumorDisprovenEvent(DomainEvent):
    rumor_id: str
    text: str


class RumorBecameExpansionEvent(DomainEvent):
    rumor_id: str
    site_id: str


class TravelStartedEvent(DomainEvent):
    destination_id: str
    arrive_at_epoch: int
    mode: str


class TravelCompletedEvent(DomainEvent):
    destination_id: str
    mode: str


class InstitutionJoinedEvent(DomainEvent):
    institution_id: str
    institution_name: str
    rank: str


class InstitutionServiceUsedEvent(DomainEvent):
    institution_id: str
    service_id: str
    service_name: str
    output_item_id: str | None = None


class QuestGeneratedEvent(DomainEvent):
    quest_id: str
    title: str
    due_at_epoch: int


class QuestAcceptedEvent(DomainEvent):
    quest_id: str
    title: str


class QuestCompletedEvent(DomainEvent):
    quest_id: str
    title: str
    reward_item_id: str


class QuestFailedEvent(DomainEvent):
    quest_id: str
    title: str


class AccountOpenedEvent(DomainEvent):
    bank_id: str
    account_id: str
    balance: int


class DepositMadeEvent(DomainEvent):
    account_id: str
    amount: int
    balance: int


class WithdrawalMadeEvent(DomainEvent):
    account_id: str
    amount: int
    balance: int


class LoanIssuedEvent(DomainEvent):
    bank_id: str
    loan_id: str
    amount: int
    due_at_epoch: int


class LoanRepaidEvent(DomainEvent):
    loan_id: str
    amount: int
    balance: int


class LoanDefaultedEvent(DomainEvent):
    loan_id: str
    amount: int


class CrimeCommittedEvent(DomainEvent):
    crime_id: str
    crime_type: str
    fine: int


class BountyPostedEvent(DomainEvent):
    crime_id: str
    amount: int


class FinePaidEvent(DomainEvent):
    crime_id: str
    amount: int


class CustomClassCreatedEvent(DomainEvent):
    class_name: str
    primary_skills: tuple[str, ...] = ()
    major_skills: tuple[str, ...] = ()
    minor_skills: tuple[str, ...] = ()


class SpellCreatedEvent(DomainEvent):
    spell_id: str
    spell_name: str
    effect_type: str
    magnitude: float


class SpellCastEvent(DomainEvent):
    spell_id: str
    spell_name: str
    target_id: str
    effect_type: str
    magnitude: float
    target_health: float | None = None


class PacificationAttemptedEvent(DomainEvent):
    target_id: str
    language: str
    skill: int
    difficulty: int
    succeeded: bool


class CreaturePacifiedEvent(DomainEvent):
    target_id: str
    language: str


def _room_id(world: World, character_id: EntityId) -> str | None:
    raw = container_of(world.get_entity(character_id))
    return str(raw) if raw is not None else None


def _name(entity: Entity) -> str:
    if entity.has_component(IdentityComponent):
        return entity.get_component(IdentityComponent).name
    return str(entity.id)


class ExpandSiteHandler:
    command_type = "expand-site"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        site_id = parse_entity_id(command.payload.get("site_id"))
        if character_id is None or site_id is None:
            return rejected("invalid character or site id")
        if not ctx.world.has_entity(site_id):
            return rejected("site does not exist")

        character = ctx.entity(character_id)
        if site_id not in reachable_ids(ctx.world, character):
            return rejected("site is not reachable")
        site = ctx.entity(site_id)
        if not site.has_component(ProceduralSiteComponent):
            return rejected("target is not a procedural site")
        if not site.has_component(UnrealizedLocationComponent):
            return rejected("target is already realized")

        procedural = site.get_component(ProceduralSiteComponent)
        unrealized = site.get_component(UnrealizedLocationComponent)
        if procedural.generated or unrealized.detail_level == "instantiated":
            return rejected("site is already instantiated")

        hook = (
            site.get_component(ExpansionHookComponent)
            if site.has_component(ExpansionHookComponent)
            else None
        )
        generator_id = str(
            command.payload.get(
                "generator_id",
                hook.generator_plugin_id if hook is not None else procedural.generator_id or "",
            )
        ).strip() or None
        trigger = str(
            command.payload.get("trigger", hook.trigger if hook is not None else "manual")
        )

        replace_component(
            site,
            replace(procedural, generated=True, generator_id=generator_id),
        )
        replace_component(site, replace(unrealized, detail_level="instantiated"))
        return ok(
            ExpansionRequestedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(site_id),),
                    site_id=str(site_id),
                    site_type=procedural.site_type,
                    trigger=trigger,
                    generator_plugin_id=generator_id,
                )
            ),
            GeneratedSiteInstantiatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(site_id),),
                    site_id=str(site_id),
                    site_type=procedural.site_type,
                    detail_level="instantiated",
                    generator_plugin_id=generator_id,
                )
            ),
        )


class AskRumorHandler:
    command_type = "ask-rumor"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        rumor_id = _selected_rumor_id(ctx, character_id, command.payload.get("rumor_id"))
        if rumor_id is None:
            return rejected("rumor does not exist")

        character = ctx.entity(character_id)
        if rumor_id not in reachable_ids(ctx.world, character):
            return rejected("rumor is not reachable")
        rumor_entity = ctx.entity(rumor_id)
        if not rumor_entity.has_component(RumorComponent):
            return rejected("target is not a rumor")

        rumor = rumor_entity.get_component(RumorComponent)
        if str(character_id) in rumor.heard_by:
            return rejected("rumor already heard")

        heard_by = tuple((*rumor.heard_by, str(character_id)))
        replace_component(rumor_entity, replace(rumor, heard_by=heard_by))
        return ok(
            RumorHeardEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(rumor_id),),
                    rumor_id=str(rumor_id),
                    text=rumor.text,
                )
            )
        )


class InvestigateRumorHandler:
    command_type = "investigate-rumor"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        rumor_id = parse_entity_id(command.payload.get("rumor_id"))
        if character_id is None or rumor_id is None:
            return rejected("invalid character or rumor id")
        if not ctx.world.has_entity(rumor_id):
            return rejected("rumor does not exist")

        character = ctx.entity(character_id)
        if rumor_id not in reachable_ids(ctx.world, character):
            return rejected("rumor is not reachable")
        rumor_entity = ctx.entity(rumor_id)
        if not rumor_entity.has_component(RumorComponent):
            return rejected("target is not a rumor")

        rumor = rumor_entity.get_component(RumorComponent)
        if str(character_id) not in rumor.heard_by:
            return rejected("rumor has not been heard")
        if rumor.state != "unverified":
            return rejected("rumor is already resolved")

        reliability = (
            rumor_entity.get_component(RumorReliabilityComponent).score
            if rumor_entity.has_component(RumorReliabilityComponent)
            else 1.0
        )
        verified = reliability >= 0.5
        state = "verified" if verified else "disproven"
        replace_component(rumor_entity, replace(rumor, state=state))

        events: list[DomainEvent] = []
        event_type = RumorVerifiedEvent if verified else RumorDisprovenEvent
        events.append(
            event_type(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(rumor_id),),
                    rumor_id=str(rumor_id),
                    text=rumor.text,
                )
            )
        )
        if verified and rumor_entity.has_component(RumorTargetComponent):
            target_id = parse_entity_id(rumor_entity.get_component(RumorTargetComponent).target_id)
            if target_id is not None and ctx.world.has_entity(target_id):
                target = ctx.entity(target_id)
                if target.has_component(ProceduralSiteComponent):
                    site = target.get_component(ProceduralSiteComponent)
                    hook = (
                        target.get_component(ExpansionHookComponent)
                        if target.has_component(ExpansionHookComponent)
                        else None
                    )
                    generator_id = (
                        hook.generator_plugin_id if hook is not None else site.generator_id
                    )
                    events.append(
                        RumorBecameExpansionEvent(
                            **ctx.event_base(
                                visibility=EventVisibility.PRIVATE,
                                actor_id=str(character_id),
                                room_id=_room_id(ctx.world, character_id),
                                target_ids=(str(rumor_id), str(target_id)),
                                rumor_id=str(rumor_id),
                                site_id=str(target_id),
                            )
                        )
                    )
                    events.append(
                        ExpansionRequestedEvent(
                            **ctx.event_base(
                                visibility=EventVisibility.PRIVATE,
                                actor_id=str(character_id),
                                room_id=_room_id(ctx.world, character_id),
                                target_ids=(str(target_id),),
                                site_id=str(target_id),
                                site_type=site.site_type,
                                trigger="rumor",
                                generator_plugin_id=generator_id,
                            )
                        )
                    )
        return ok(*events)


class PlanTravelHandler:
    command_type = "plan-travel"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        destination_id = parse_entity_id(command.payload.get("destination_id"))
        if character_id is None or destination_id is None:
            return rejected("invalid character or destination id")
        if not ctx.world.has_entity(destination_id):
            return rejected("destination does not exist")

        character = ctx.entity(character_id)
        if character.has_component(TravelPlanComponent):
            return rejected("character is already traveling")
        origin_id = container_of(character)
        if origin_id is None or not ctx.world.has_entity(origin_id):
            return rejected("character is not at a travel hub")
        origin = ctx.entity(origin_id)
        destination = ctx.entity(destination_id)
        if not origin.has_component(TravelHubComponent):
            return rejected("origin is not a travel hub")
        if not destination.has_component(TravelHubComponent):
            return rejected("destination is not a travel hub")

        route = _route_between(origin, destination_id)
        if route is None:
            return rejected("no travel route to destination")
        mode = (
            character.get_component(TravelModeComponent)
            if character.has_component(TravelModeComponent)
            else TravelModeComponent()
        )
        travel_seconds = max(1, int(route.travel_seconds / max(0.1, mode.speed_multiplier)))
        arrive_at = ctx.epoch + travel_seconds
        replace_component(
            character,
            TravelPlanComponent(
                destination_id=str(destination_id),
                started_at_epoch=ctx.epoch,
                arrive_at_epoch=arrive_at,
                mode=mode.mode,
                route_label=route.label,
            ),
        )
        return ok(
            TravelStartedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=str(origin_id),
                    target_ids=(str(destination_id),),
                    destination_id=str(destination_id),
                    arrive_at_epoch=arrive_at,
                    mode=mode.mode,
                )
            )
        )


class TravelCompletionConsequence:
    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for character in world.query().with_all([TravelPlanComponent]).execute_entities():
            plan = character.get_component(TravelPlanComponent)
            if epoch < plan.arrive_at_epoch:
                continue
            destination_id = parse_entity_id(plan.destination_id)
            if destination_id is None or not world.has_entity(destination_id):
                continue
            origin_id = container_of(character)
            if origin_id is not None and world.has_entity(origin_id):
                world.get_entity(origin_id).remove_relationship(Contains, character.id)
            world.get_entity(destination_id).add_relationship(
                Contains(mode=ContainmentMode.ROOM_CONTENT), character.id
            )
            character.remove_component(TravelPlanComponent)
            events.append(
                TravelCompletedEvent(
                    **_travel_event_base(
                        epoch,
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(character.id),
                        room_id=str(destination_id),
                        target_ids=(str(destination_id),),
                        destination_id=str(destination_id),
                        mode=plan.mode,
                    )
                )
            )
        return events


def _route_between(origin: Entity, destination_id: EntityId) -> TravelRoute | None:
    for edge, target_id in origin.get_relationships(TravelRoute):
        if target_id == destination_id:
            return edge
    return None


def _travel_event_base(epoch: int, **kwargs) -> dict:
    from datetime import UTC, datetime
    from uuid import uuid4

    base = {"event_id": uuid4().hex, "world_epoch": epoch, "created_at": datetime.now(UTC)}
    base.update(kwargs)
    return base


class JoinInstitutionHandler:
    command_type = "join-institution"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        institution_id = parse_entity_id(command.payload.get("institution_id"))
        rank = str(command.payload.get("rank", "member")).strip() or "member"
        if character_id is None or institution_id is None:
            return rejected("invalid character or institution id")
        if not ctx.world.has_entity(institution_id):
            return rejected("institution does not exist")

        character = ctx.entity(character_id)
        if institution_id not in reachable_ids(ctx.world, character):
            return rejected("institution is not reachable")
        institution = ctx.entity(institution_id)
        if not institution.has_component(InstitutionComponent):
            return rejected("target is not an institution")
        if character.has_relationship(MemberOfInstitution, institution_id):
            return rejected("already an institution member")

        character.add_relationship(
            MemberOfInstitution(rank=rank, since_epoch=ctx.epoch), institution_id
        )
        component = institution.get_component(InstitutionComponent)
        return ok(
            InstitutionJoinedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(institution_id),),
                    institution_id=str(institution_id),
                    institution_name=component.name,
                    rank=rank,
                )
            )
        )


class UseInstitutionServiceHandler:
    command_type = "use-institution-service"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        service_id = parse_entity_id(command.payload.get("service_id"))
        if character_id is None or service_id is None:
            return rejected("invalid character or service id")
        if not ctx.world.has_entity(service_id):
            return rejected("service does not exist")

        character = ctx.entity(character_id)
        reachable = reachable_ids(ctx.world, character)
        service_parent_id = container_of(ctx.entity(service_id))
        if service_id not in reachable and service_parent_id not in reachable:
            return rejected("service is not reachable")
        service_entity = ctx.entity(service_id)
        if not service_entity.has_component(InstitutionServiceComponent):
            return rejected("target is not an institution service")

        institution_id = _service_institution(ctx.world, service_entity)
        if institution_id is None:
            return rejected("service is not attached to an institution")
        institution = ctx.entity(institution_id)
        if not institution.has_component(InstitutionComponent):
            return rejected("service institution is invalid")
        membership = _institution_membership(character, institution_id)
        if membership is None:
            return rejected("not an institution member")

        service = service_entity.get_component(InstitutionServiceComponent)
        if not _rank_allows(membership.rank, service.required_rank):
            return rejected("institution rank is too low")

        output_item_id: str | None = None
        if service.output_item_name:
            output = _spawn_inventory_item(
                ctx.world, character, service.output_item_name, kind="service-output"
            )
            output_item_id = str(output.id)
        return ok(
            InstitutionServiceUsedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(institution_id), str(service_id)),
                    institution_id=str(institution_id),
                    service_id=str(service_id),
                    service_name=service.service_name,
                    output_item_id=output_item_id,
                )
            )
        )


class AskForWorkHandler:
    command_type = "ask-for-work"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        template_id = parse_entity_id(command.payload.get("template_id"))
        if character_id is None or template_id is None:
            return rejected("invalid character or template id")
        if not ctx.world.has_entity(template_id):
            return rejected("quest template does not exist")

        character = ctx.entity(character_id)
        if template_id not in reachable_ids(ctx.world, character):
            return rejected("quest template is not reachable")
        template_entity = ctx.entity(template_id)
        if not template_entity.has_component(QuestTemplateComponent):
            return rejected("target is not a quest template")

        from ..core.ecs import spawn_entity

        template = template_entity.get_component(QuestTemplateComponent)
        due_at = ctx.epoch + template.duration_seconds
        quest = spawn_entity(
            ctx.world,
            [
                IdentityComponent(name=template.title, kind="quest"),
                GeneratedQuestComponent(title=template.title, objective=template.objective),
                QuestDeadlineComponent(due_at_epoch=due_at),
                DaggerQuestRewardComponent(item_name=template.reward_item_name),
            ],
        )
        character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), quest.id)
        return ok(
            QuestGeneratedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(quest.id),),
                    quest_id=str(quest.id),
                    title=template.title,
                    due_at_epoch=due_at,
                )
            )
        )


class AcceptGeneratedQuestHandler:
    command_type = "accept-generated-quest"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        quest_id = parse_entity_id(command.payload.get("quest_id"))
        if character_id is None or quest_id is None:
            return rejected("invalid character or quest id")
        if not ctx.world.has_entity(quest_id):
            return rejected("quest does not exist")

        character = ctx.entity(character_id)
        if quest_id not in reachable_ids(ctx.world, character):
            return rejected("quest is not reachable")
        quest = ctx.entity(quest_id)
        if not quest.has_component(GeneratedQuestComponent):
            return rejected("target is not a generated quest")
        component = quest.get_component(GeneratedQuestComponent)
        if component.status != "offered":
            return rejected("quest is not offered")

        replace_component(
            quest,
            replace(component, status="active", accepted_by=str(character_id)),
        )
        return ok(
            QuestAcceptedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(quest_id),),
                    quest_id=str(quest_id),
                    title=component.title,
                )
            )
        )


class CompleteGeneratedQuestHandler:
    command_type = "complete-generated-quest"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        quest_id = parse_entity_id(command.payload.get("quest_id"))
        if character_id is None or quest_id is None:
            return rejected("invalid character or quest id")
        if not ctx.world.has_entity(quest_id):
            return rejected("quest does not exist")

        character = ctx.entity(character_id)
        if quest_id not in reachable_ids(ctx.world, character):
            return rejected("quest is not reachable")
        quest = ctx.entity(quest_id)
        if not quest.has_component(GeneratedQuestComponent):
            return rejected("target is not a generated quest")
        component = quest.get_component(GeneratedQuestComponent)
        if component.status != "active":
            return rejected("quest is not active")
        if component.accepted_by != str(character_id):
            return rejected("quest is not accepted by character")
        if quest.has_component(QuestDeadlineComponent):
            deadline = quest.get_component(QuestDeadlineComponent)
            if ctx.epoch > deadline.due_at_epoch:
                return rejected("quest deadline has passed")
        if not quest.has_component(DaggerQuestRewardComponent):
            return rejected("quest has no reward")

        reward = quest.get_component(DaggerQuestRewardComponent)
        item = _spawn_inventory_item(ctx.world, character, reward.item_name, kind="quest-reward")
        replace_component(quest, replace(component, status="completed"))
        replace_component(
            quest,
            replace(reward, claimed=True, claimed_by=str(character_id)),
        )
        return ok(
            QuestCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(quest_id), str(item.id)),
                    quest_id=str(quest_id),
                    title=component.title,
                    reward_item_id=str(item.id),
                )
            )
        )


class QuestDeadlineConsequence:
    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        query = world.query().with_all([GeneratedQuestComponent, QuestDeadlineComponent])
        for quest in query.execute_entities():
            component = quest.get_component(GeneratedQuestComponent)
            deadline = quest.get_component(QuestDeadlineComponent)
            if component.status != "active" or epoch <= deadline.due_at_epoch:
                continue
            replace_component(quest, replace(component, status="failed"))
            events.append(
                QuestFailedEvent(
                    **_travel_event_base(
                        epoch,
                        visibility=EventVisibility.PRIVATE,
                        actor_id=component.accepted_by,
                        target_ids=(str(quest.id),),
                        quest_id=str(quest.id),
                        title=component.title,
                    )
                )
            )
        return events


class OpenBankAccountHandler:
    command_type = "open-bank-account"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        bank_id = parse_entity_id(command.payload.get("bank_id"))
        if character_id is None or bank_id is None:
            return rejected("invalid character or bank id")
        if not ctx.world.has_entity(bank_id):
            return rejected("bank does not exist")
        character = ctx.entity(character_id)
        if bank_id not in reachable_ids(ctx.world, character):
            return rejected("bank is not reachable")
        bank = ctx.entity(bank_id)
        if not bank.has_component(BankComponent):
            return rejected("target is not a bank")
        if _bank_account(ctx.world, character_id, bank_id) is not None:
            return rejected("bank account already exists")

        from ..core.ecs import spawn_entity

        account = spawn_entity(
            ctx.world,
            [
                IdentityComponent(
                    name=f"{bank.get_component(BankComponent).name} account",
                    kind="bank-account",
                ),
                BankAccountComponent(bank_id=str(bank_id), owner_id=str(character_id)),
            ],
        )
        bank.add_relationship(Contains(mode=ContainmentMode.CONTAINER), account.id)
        return ok(
            AccountOpenedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(bank_id), str(account.id)),
                    bank_id=str(bank_id),
                    account_id=str(account.id),
                    balance=0,
                )
            )
        )


class DepositHandler:
    command_type = "deposit"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        bank_id = parse_entity_id(command.payload.get("bank_id"))
        amount = int(command.payload.get("amount", 0))
        if character_id is None or bank_id is None:
            return rejected("invalid character or bank id")
        if amount <= 0:
            return rejected("deposit amount must be positive")
        account = _bank_account(ctx.world, character_id, bank_id)
        if account is None:
            return rejected("bank account does not exist")
        account_component = account.get_component(BankAccountComponent)
        updated = replace(account_component, balance=account_component.balance + amount)
        replace_component(account, updated)
        return ok(
            DepositMadeEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(account.id),),
                    account_id=str(account.id),
                    amount=amount,
                    balance=updated.balance,
                )
            )
        )


class WithdrawHandler:
    command_type = "withdraw"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        bank_id = parse_entity_id(command.payload.get("bank_id"))
        amount = int(command.payload.get("amount", 0))
        if character_id is None or bank_id is None:
            return rejected("invalid character or bank id")
        if amount <= 0:
            return rejected("withdrawal amount must be positive")
        account = _bank_account(ctx.world, character_id, bank_id)
        if account is None:
            return rejected("bank account does not exist")
        account_component = account.get_component(BankAccountComponent)
        if account_component.balance < amount:
            return rejected("insufficient bank balance")
        updated = replace(account_component, balance=account_component.balance - amount)
        replace_component(account, updated)
        return ok(
            WithdrawalMadeEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(account.id),),
                    account_id=str(account.id),
                    amount=amount,
                    balance=updated.balance,
                )
            )
        )


class TakeLoanHandler:
    command_type = "take-loan"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        bank_id = parse_entity_id(command.payload.get("bank_id"))
        amount = int(command.payload.get("amount", 0))
        duration_seconds = int(command.payload.get("duration_seconds", 7 * 24 * 60 * 60))
        if character_id is None or bank_id is None:
            return rejected("invalid character or bank id")
        if amount <= 0:
            return rejected("loan amount must be positive")
        account = _bank_account(ctx.world, character_id, bank_id)
        if account is None:
            return rejected("bank account does not exist")

        from ..core.ecs import spawn_entity

        account_component = account.get_component(BankAccountComponent)
        replace_component(
            account, replace(account_component, balance=account_component.balance + amount)
        )
        due_at = ctx.epoch + duration_seconds
        loan = spawn_entity(
            ctx.world,
            [
                IdentityComponent(name="bank loan", kind="loan"),
                LoanComponent(
                    bank_id=str(bank_id),
                    borrower_id=str(character_id),
                    principal=amount,
                    balance=amount,
                    due_at_epoch=due_at,
                ),
            ],
        )
        ctx.entity(character_id).add_relationship(Contains(mode=ContainmentMode.INVENTORY), loan.id)
        return ok(
            LoanIssuedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(bank_id), str(loan.id), str(account.id)),
                    bank_id=str(bank_id),
                    loan_id=str(loan.id),
                    amount=amount,
                    due_at_epoch=due_at,
                )
            )
        )


class RepayLoanHandler:
    command_type = "repay-loan"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        loan_id = parse_entity_id(command.payload.get("loan_id"))
        amount = int(command.payload.get("amount", 0))
        if character_id is None or loan_id is None:
            return rejected("invalid character or loan id")
        if amount <= 0:
            return rejected("repayment amount must be positive")
        if not ctx.world.has_entity(loan_id):
            return rejected("loan does not exist")
        loan_entity = ctx.entity(loan_id)
        if not loan_entity.has_component(LoanComponent):
            return rejected("target is not a loan")
        loan = loan_entity.get_component(LoanComponent)
        if loan.borrower_id != str(character_id):
            return rejected("loan is not borrowed by character")
        if loan.status != "active":
            return rejected("loan is not active")
        bank_id = parse_entity_id(loan.bank_id)
        if bank_id is None:
            return rejected("loan bank is invalid")
        account = _bank_account(ctx.world, character_id, bank_id)
        if account is None:
            return rejected("bank account does not exist")
        account_component = account.get_component(BankAccountComponent)
        payment = min(amount, loan.balance)
        if account_component.balance < payment:
            return rejected("insufficient bank balance")

        replace_component(
            account, replace(account_component, balance=account_component.balance - payment)
        )
        next_balance = loan.balance - payment
        status = "repaid" if next_balance == 0 else loan.status
        replace_component(loan_entity, replace(loan, balance=next_balance, status=status))
        return ok(
            LoanRepaidEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(loan_id), str(account.id)),
                    loan_id=str(loan_id),
                    amount=payment,
                    balance=next_balance,
                )
            )
        )


class LoanDueConsequence:
    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for loan_entity in world.query().with_all([LoanComponent]).execute_entities():
            loan = loan_entity.get_component(LoanComponent)
            if loan.status != "active" or epoch <= loan.due_at_epoch:
                continue
            replace_component(loan_entity, replace(loan, status="defaulted"))
            replace_component(
                loan_entity,
                DebtComponent(amount=loan.balance, defaulted_at_epoch=epoch),
            )
            events.append(
                LoanDefaultedEvent(
                    **_travel_event_base(
                        epoch,
                        visibility=EventVisibility.PRIVATE,
                        actor_id=loan.borrower_id,
                        target_ids=(str(loan_entity.id),),
                        loan_id=str(loan_entity.id),
                        amount=loan.balance,
                    )
                )
            )
        return events


def _bank_account(world: World, owner_id: EntityId, bank_id: EntityId) -> Entity | None:
    for account in world.query().with_all([BankAccountComponent]).execute_entities():
        component = account.get_component(BankAccountComponent)
        if component.owner_id == str(owner_id) and component.bank_id == str(bank_id):
            return account
    return None


class CommitCrimeHandler:
    command_type = "commit-crime"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        crime_type = str(command.payload.get("crime_type", "")).strip()
        if character_id is None or not crime_type:
            return rejected("invalid character or crime type")
        character = ctx.entity(character_id)
        law_region = _current_law_region(ctx.world, character)
        if law_region is None:
            return rejected("no law region applies")
        region_id, law = law_region
        fine = int(law.fines.get(crime_type, law.fines.get("default", 0)))
        if fine <= 0:
            return rejected("crime is not fineable")

        from ..core.ecs import spawn_entity

        crime = spawn_entity(
            ctx.world,
            [
                IdentityComponent(name=f"{crime_type} charge", kind="crime-record"),
                CrimeRecordComponent(
                    crime_type=crime_type,
                    region_id=law.region_id,
                    fine=fine,
                ),
                BountyComponent(amount=fine, region_id=law.region_id),
            ],
        )
        character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), crime.id)
        return ok(
            CrimeCommittedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=str(region_id),
                    target_ids=(str(crime.id),),
                    crime_id=str(crime.id),
                    crime_type=crime_type,
                    fine=fine,
                )
            ),
            BountyPostedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=str(region_id),
                    target_ids=(str(crime.id),),
                    crime_id=str(crime.id),
                    amount=fine,
                )
            ),
        )


class PayFineHandler:
    command_type = "pay-fine"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        crime_id = parse_entity_id(command.payload.get("crime_id"))
        if character_id is None or crime_id is None:
            return rejected("invalid character or crime id")
        if not ctx.world.has_entity(crime_id):
            return rejected("crime record does not exist")
        character = ctx.entity(character_id)
        if crime_id not in reachable_ids(ctx.world, character):
            return rejected("crime record is not reachable")
        crime_entity = ctx.entity(crime_id)
        if not crime_entity.has_component(CrimeRecordComponent):
            return rejected("target is not a crime record")
        crime = crime_entity.get_component(CrimeRecordComponent)
        if crime.status != "open":
            return rejected("crime record is not open")
        account = _any_bank_account(ctx.world, character_id)
        if account is None:
            return rejected("bank account does not exist")
        account_component = account.get_component(BankAccountComponent)
        if account_component.balance < crime.fine:
            return rejected("insufficient bank balance")

        replace_component(
            account,
            replace(account_component, balance=account_component.balance - crime.fine),
        )
        replace_component(crime_entity, replace(crime, status="paid"))
        if crime_entity.has_component(BountyComponent):
            crime_entity.remove_component(BountyComponent)
        return ok(
            FinePaidEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(crime_id), str(account.id)),
                    crime_id=str(crime_id),
                    amount=crime.fine,
                )
            )
        )


class CreateCustomClassHandler:
    command_type = "create-custom-class"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        template_id = parse_entity_id(command.payload.get("template_id"))
        if character_id is None or template_id is None:
            return rejected("invalid character or class template id")
        if not ctx.world.has_entity(template_id):
            return rejected("class template does not exist")

        character = ctx.entity(character_id)
        if template_id not in reachable_ids(ctx.world, character):
            return rejected("class template is not reachable")
        template_entity = ctx.entity(template_id)
        if not template_entity.has_component(ClassTemplateComponent):
            return rejected("target is not a class template")
        if character.has_component(CustomClassComponent):
            return rejected("character already has a custom class")

        template = template_entity.get_component(ClassTemplateComponent)
        class_name = str(command.payload.get("class_name", template.class_name)).strip()
        custom_class = CustomClassComponent(
            class_name=class_name or template.class_name,
            primary_skills=_string_tuple(
                command.payload.get("primary_skills"), template.primary_skills
            ),
            major_skills=_string_tuple(
                command.payload.get("major_skills"), template.major_skills
            ),
            minor_skills=_string_tuple(
                command.payload.get("minor_skills"), template.minor_skills
            ),
            advantages=_string_tuple(command.payload.get("advantages"), template.advantages),
            disadvantages=_string_tuple(
                command.payload.get("disadvantages"), template.disadvantages
            ),
            finalized_at_epoch=ctx.epoch,
        )
        replace_component(character, custom_class)
        return ok(
            CustomClassCreatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(template_id),),
                    class_name=custom_class.class_name,
                    primary_skills=custom_class.primary_skills,
                    major_skills=custom_class.major_skills,
                    minor_skills=custom_class.minor_skills,
                )
            )
        )


class CreateSpellHandler:
    command_type = "create-spell"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        template_id = parse_entity_id(command.payload.get("template_id"))
        if character_id is None or template_id is None:
            return rejected("invalid character or spell template id")
        if not ctx.world.has_entity(template_id):
            return rejected("spell template does not exist")

        character = ctx.entity(character_id)
        if template_id not in reachable_ids(ctx.world, character):
            return rejected("spell template is not reachable")
        template_entity = ctx.entity(template_id)
        if not template_entity.has_component(SpellTemplateComponent):
            return rejected("target is not a spell template")

        from ..core.ecs import spawn_entity

        template = template_entity.get_component(SpellTemplateComponent)
        spell_name = str(command.payload.get("spell_name", template.spell_name)).strip()
        spell = CustomSpellComponent(
            spell_name=spell_name or template.spell_name,
            effect_type=template.effect_type,
            magnitude=template.magnitude,
            cost=template.cost,
            creator_id=str(character_id),
        )
        spell_entity = spawn_entity(
            ctx.world,
            [
                IdentityComponent(name=spell.spell_name, kind="spell"),
                spell,
            ],
        )
        character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), spell_entity.id)
        return ok(
            SpellCreatedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(spell_entity.id),),
                    spell_id=str(spell_entity.id),
                    spell_name=spell.spell_name,
                    effect_type=spell.effect_type,
                    magnitude=spell.magnitude,
                )
            )
        )


class CastSpellHandler:
    command_type = "cast-spell"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        spell_id = parse_entity_id(command.payload.get("spell_id"))
        target_id = parse_entity_id(command.payload.get("target_id")) or character_id
        if character_id is None or spell_id is None or target_id is None:
            return rejected("invalid character, spell, or target id")
        if not ctx.world.has_entity(spell_id) or not ctx.world.has_entity(target_id):
            return rejected("spell or target does not exist")

        character = ctx.entity(character_id)
        if spell_id not in reachable_ids(ctx.world, character):
            return rejected("spell is not reachable")
        spell_entity = ctx.entity(spell_id)
        if not spell_entity.has_component(CustomSpellComponent):
            return rejected("target spell is not custom")
        target = ctx.entity(target_id)
        spell = spell_entity.get_component(CustomSpellComponent)
        target_health = _apply_spell_effect(target, spell)
        return ok(
            SpellCastEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(spell_id), str(target_id)),
                    spell_id=str(spell_id),
                    spell_name=spell.spell_name,
                    target_id=str(target_id),
                    effect_type=spell.effect_type,
                    magnitude=spell.magnitude,
                    target_health=target_health,
                )
            )
        )


def _apply_spell_effect(target: Entity, spell: CustomSpellComponent) -> float | None:
    if not target.has_component(HealthComponent):
        return None
    health = target.get_component(HealthComponent)
    if spell.effect_type == "heal":
        current = min(health.maximum, health.current + spell.magnitude)
    elif spell.effect_type == "harm":
        current = max(0.0, health.current - spell.magnitude)
    else:
        return health.current
    replace_component(target, replace(health, current=current))
    return current


class AttemptPacifyHandler:
    command_type = "attempt-pacify"

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
        if not target.has_component(CreatureLanguageComponent):
            return rejected("target has no creature language")
        if not character.has_component(LanguageSkillComponent):
            return rejected("character knows no creature languages")

        creature_language = target.get_component(CreatureLanguageComponent)
        requested = str(command.payload.get("language", creature_language.language))
        skills = character.get_component(LanguageSkillComponent).languages
        skill = int(skills.get(requested, 0))
        succeeded = requested == creature_language.language and (
            skill >= creature_language.pacification_difficulty
        )
        events: list[DomainEvent] = [
            PacificationAttemptedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                    language=requested,
                    skill=skill,
                    difficulty=creature_language.pacification_difficulty,
                    succeeded=succeeded,
                )
            )
        ]
        if succeeded:
            if target.has_component(HostilityComponent):
                replace_component(
                    target,
                    replace(target.get_component(HostilityComponent), hostile=False),
                )
            replace_component(
                target,
                PacifiedComponent(
                    pacified_by=str(character_id),
                    language=requested,
                    pacified_at_epoch=ctx.epoch,
                ),
            )
            events.append(
                CreaturePacifiedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.ROOM,
                        actor_id=str(character_id),
                        room_id=_room_id(ctx.world, character_id),
                        target_ids=(str(target_id),),
                        target_id=str(target_id),
                        language=requested,
                    )
                )
            )
        return ok(*events)


def _string_tuple(raw: object, default: tuple[str, ...]) -> tuple[str, ...]:
    if raw is None:
        return default
    if isinstance(raw, str):
        return tuple(part.strip() for part in raw.split(",") if part.strip())
    if isinstance(raw, list | tuple):
        return tuple(str(part).strip() for part in raw if str(part).strip())
    return default


def _current_law_region(
    world: World, character: Entity
) -> tuple[EntityId, LawRegionComponent] | None:
    room_id = container_of(character)
    if room_id is not None and world.has_entity(room_id):
        room = world.get_entity(room_id)
        if room.has_component(LawRegionComponent):
            return room_id, room.get_component(LawRegionComponent)
    return None


def _any_bank_account(world: World, owner_id: EntityId) -> Entity | None:
    for account in world.query().with_all([BankAccountComponent]).execute_entities():
        component = account.get_component(BankAccountComponent)
        if component.owner_id == str(owner_id):
            return account
    return None


def _service_institution(world: World, service: Entity) -> EntityId | None:
    parent_id = container_of(service)
    if parent_id is not None:
        return parent_id
    return None


def _institution_membership(
    character: Entity, institution_id: EntityId
) -> MemberOfInstitution | None:
    for edge, target_id in character.get_relationships(MemberOfInstitution):
        if target_id == institution_id:
            return edge
    return None


def _rank_allows(actual: str, required: str) -> bool:
    ranks = {"guest": 0, "member": 1, "adept": 2, "officer": 3, "master": 4}
    if actual in ranks and required in ranks:
        return ranks[actual] >= ranks[required]
    return actual == required


def _spawn_inventory_item(world: World, character: Entity, name: str, *, kind: str) -> Entity:
    from ..core.components import PortableComponent
    from ..core.ecs import spawn_entity

    output = spawn_entity(
        world,
        [IdentityComponent(name=name, kind=kind), PortableComponent()],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), output.id)
    return output


def _selected_rumor_id(
    ctx: HandlerContext, character_id: EntityId, requested_id: object
) -> EntityId | None:
    parsed = parse_entity_id(requested_id)
    if parsed is not None:
        return parsed
    character = ctx.entity(character_id)
    for entity_id in reachable_ids(ctx.world, character):
        entity = ctx.entity(entity_id)
        if not entity.has_component(RumorComponent):
            continue
        rumor = entity.get_component(RumorComponent)
        if str(character_id) not in rumor.heard_by:
            return entity_id
    return None


def daggersim_fragments(world: World, character: Entity) -> list[str]:
    lines: list[str] = []
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        if entity.has_component(UnrealizedLocationComponent):
            unrealized = entity.get_component(UnrealizedLocationComponent)
            if unrealized.detail_level != "instantiated":
                site_type = (
                    entity.get_component(ProceduralSiteComponent).site_type
                    if entity.has_component(ProceduralSiteComponent)
                    else "site"
                )
                lines.append(
                    f"Nearby unrealized {site_type}: {_name(entity)} ({unrealized.summary})."
                )
        if entity.has_component(RumorComponent):
            rumor = entity.get_component(RumorComponent)
            if str(character.id) in rumor.heard_by:
                lines.append(f"Rumor: {rumor.text} ({rumor.state}).")
        if entity.id != character.id and entity.has_component(TravelHubComponent):
            hub = entity.get_component(TravelHubComponent)
            lines.append(f"Travel destination: {hub.name}.")
        if entity.has_component(InstitutionComponent):
            institution = entity.get_component(InstitutionComponent)
            lines.append(
                f"Institution nearby: {institution.name} ({institution.institution_type})."
            )
        if entity.has_component(GeneratedQuestComponent):
            quest = entity.get_component(GeneratedQuestComponent)
            lines.append(f"Generated quest: {quest.title} ({quest.status}).")
        if entity.has_component(QuestTemplateComponent):
            template = entity.get_component(QuestTemplateComponent)
            lines.append(f"Work available: {template.title}.")
        if entity.has_component(BankComponent):
            lines.append(f"Bank nearby: {entity.get_component(BankComponent).name}.")
        if entity.has_component(LoanComponent):
            loan = entity.get_component(LoanComponent)
            lines.append(
                f"Loan: {loan.balance} due at epoch {loan.due_at_epoch} ({loan.status})."
            )
        if entity.has_component(CrimeRecordComponent):
            crime = entity.get_component(CrimeRecordComponent)
            lines.append(f"Crime record: {crime.crime_type} ({crime.status}).")
        if entity.has_component(ClassTemplateComponent):
            template = entity.get_component(ClassTemplateComponent)
            lines.append(f"Class template available: {template.class_name}.")
        if entity.has_component(SpellTemplateComponent):
            template = entity.get_component(SpellTemplateComponent)
            lines.append(f"Spell formula available: {template.spell_name}.")
        if entity.has_component(CustomSpellComponent):
            spell = entity.get_component(CustomSpellComponent)
            lines.append(f"Known custom spell: {spell.spell_name} ({spell.effect_type}).")
        if entity.has_component(CreatureLanguageComponent):
            language = entity.get_component(CreatureLanguageComponent).language
            state = "hostile"
            if entity.has_component(HostilityComponent):
                state = "hostile" if entity.get_component(HostilityComponent).hostile else "calm"
            lines.append(f"Creature language nearby: {language} ({state}).")
    if character.has_component(CustomClassComponent):
        custom_class = character.get_component(CustomClassComponent)
        lines.append(f"Custom class: {custom_class.class_name}.")
    if character.has_component(TravelPlanComponent):
        plan = character.get_component(TravelPlanComponent)
        lines.append(
            f"Traveling by {plan.mode}; arrival due at epoch {plan.arrive_at_epoch}."
        )
    for edge, institution_id in character.get_relationships(MemberOfInstitution):
        if world.has_entity(institution_id):
            institution = world.get_entity(institution_id)
            if institution.has_component(InstitutionComponent):
                lines.append(
                    f"Institution membership: "
                    f"{institution.get_component(InstitutionComponent).name} ({edge.rank})."
                )
    return sorted(lines)


def install_daggersim(actor) -> None:
    actor.register_consequence(TravelCompletionConsequence())
    actor.register_consequence(QuestDeadlineConsequence())
    actor.register_consequence(LoanDueConsequence())


__all__ = [
    "AskRumorHandler",
    "AcceptGeneratedQuestHandler",
    "AccountOpenedEvent",
    "AskForWorkHandler",
    "BankAccountComponent",
    "BankComponent",
    "BountyComponent",
    "BountyPostedEvent",
    "AttemptPacifyHandler",
    "CompleteGeneratedQuestHandler",
    "CommitCrimeHandler",
    "CastSpellHandler",
    "ClassTemplateComponent",
    "CreateCustomClassHandler",
    "CreateSpellHandler",
    "CreatureLanguageComponent",
    "CreaturePacifiedEvent",
    "CrimeCommittedEvent",
    "CrimeRecordComponent",
    "CustomClassComponent",
    "CustomClassCreatedEvent",
    "CustomSpellComponent",
    "DaggerQuestRewardComponent",
    "DebtComponent",
    "DepositHandler",
    "DepositMadeEvent",
    "ExpandSiteHandler",
    "ExpansionHookComponent",
    "ExpansionRequestedEvent",
    "FinePaidEvent",
    "GeneratedSiteInstantiatedEvent",
    "HostilityComponent",
    "InvestigateRumorHandler",
    "InstitutionComponent",
    "InstitutionJoinedEvent",
    "InstitutionServiceComponent",
    "InstitutionServiceUsedEvent",
    "JoinInstitutionHandler",
    "LawRegionComponent",
    "LanguageSkillComponent",
    "LoanComponent",
    "LoanDefaultedEvent",
    "LoanDueConsequence",
    "LoanIssuedEvent",
    "LoanRepaidEvent",
    "MemberOfInstitution",
    "OpenBankAccountHandler",
    "PayFineHandler",
    "PacificationAttemptedEvent",
    "PacifiedComponent",
    "PlanTravelHandler",
    "ProceduralSiteComponent",
    "GeneratedQuestComponent",
    "QuestAcceptedEvent",
    "QuestCompletedEvent",
    "QuestDeadlineComponent",
    "QuestDeadlineConsequence",
    "QuestFailedEvent",
    "QuestGeneratedEvent",
    "QuestTemplateComponent",
    "RepayLoanHandler",
    "RumorBecameExpansionEvent",
    "RumorComponent",
    "RumorDisprovenEvent",
    "RumorHeardEvent",
    "RumorReliabilityComponent",
    "RumorSourceComponent",
    "RumorTargetComponent",
    "RumorVerifiedEvent",
    "SpellCastEvent",
    "SpellCreatedEvent",
    "SpellTemplateComponent",
    "TravelCompletedEvent",
    "TravelCompletionConsequence",
    "TravelHubComponent",
    "TravelModeComponent",
    "TravelPlanComponent",
    "TravelRoute",
    "TravelStartedEvent",
    "TakeLoanHandler",
    "UnrealizedLocationComponent",
    "UseInstitutionServiceHandler",
    "WithdrawalMadeEvent",
    "WithdrawHandler",
    "daggersim_fragments",
    "install_daggersim",
]
