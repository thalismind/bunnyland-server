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
from ..core.components import IdentityComponent
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


__all__ = [
    "AskRumorHandler",
    "AcceptGeneratedQuestHandler",
    "AskForWorkHandler",
    "CompleteGeneratedQuestHandler",
    "DaggerQuestRewardComponent",
    "ExpandSiteHandler",
    "ExpansionHookComponent",
    "ExpansionRequestedEvent",
    "GeneratedSiteInstantiatedEvent",
    "InvestigateRumorHandler",
    "InstitutionComponent",
    "InstitutionJoinedEvent",
    "InstitutionServiceComponent",
    "InstitutionServiceUsedEvent",
    "JoinInstitutionHandler",
    "MemberOfInstitution",
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
    "RumorBecameExpansionEvent",
    "RumorComponent",
    "RumorDisprovenEvent",
    "RumorHeardEvent",
    "RumorReliabilityComponent",
    "RumorSourceComponent",
    "RumorTargetComponent",
    "RumorVerifiedEvent",
    "TravelCompletedEvent",
    "TravelCompletionConsequence",
    "TravelHubComponent",
    "TravelModeComponent",
    "TravelPlanComponent",
    "TravelRoute",
    "TravelStartedEvent",
    "UnrealizedLocationComponent",
    "UseInstitutionServiceHandler",
    "daggersim_fragments",
    "install_daggersim",
]
