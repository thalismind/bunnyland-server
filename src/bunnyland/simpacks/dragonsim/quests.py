"""Canonical Dragon Sim generated-quest contracts and lifecycle."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from pydantic.dataclasses import dataclass
from relics import Component, Entity, World

from ...core.commands import SubmittedCommand
from ...core.components import IdentityComponent, PortableComponent
from ...core.ecs import (
    parse_entity_id,
    reachable_ids,
    replace_component,
)
from ...core.ecs import (
    room_id_for as _room_id,
)
from ...core.edges import ContainmentMode, Contains
from ...core.events import DomainEvent, EventVisibility
from ...core.handlers import HandlerContext, HandlerResult, planned, rejected
from ...core.mutations import (
    AddEdge,
    AddEntity,
    EntityReference,
    MutationPlan,
    SetComponent,
)
from ...prompts import ComponentPromptContext
from .mechanics import (
    QuestAcceptedBy,
    QuestAcceptedEvent,
    QuestCompletedEvent,
    QuestComponent,
    QuestHasObjective,
    QuestHasReward,
    QuestObjectiveComponent,
    QuestProvenanceComponent,
    QuestRewardComponent,
    QuestStateComponent,
)


@dataclass(frozen=True)
class QuestTemplateComponent(Component):
    title: str
    objective: str
    reward_item_name: str
    duration_seconds: int = 24 * 60 * 60

    def prompt_fragments(self, ctx: ComponentPromptContext) -> tuple[str, ...]:
        del ctx
        return (f"Work available: {self.title}.",)


class QuestGeneratedEvent(DomainEvent):
    quest_id: str
    title: str
    due_at_epoch: int


class QuestFailedEvent(DomainEvent):
    quest_id: str
    title: str


class QuestRefusedEvent(DomainEvent):
    quest_id: str
    title: str


class QuestAbandonedEvent(DomainEvent):
    quest_id: str
    title: str


class QuestExtendedEvent(DomainEvent):
    quest_id: str
    due_at_epoch: int


class QuestLieToldEvent(DomainEvent):
    quest_id: str
    lie: str


def generated_quest_fragments(world: World, character: Entity) -> list[str]:
    lines: list[str] = []
    ctx = ComponentPromptContext.for_entity(world, character)
    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        if entity.has_component(QuestTemplateComponent):
            template_ctx = ComponentPromptContext.for_entity(
                world, entity, perspective=ctx.perspective, target=character
            )
            lines.extend(
                entity.get_component(QuestTemplateComponent).prompt_fragments(template_ctx)
            )
    return sorted(lines)


def _travel_event_base(epoch: int, **kwargs) -> dict:
    base = {"event_id": uuid4().hex, "world_epoch": epoch, "created_at": datetime.now(UTC)}
    base.update(kwargs)
    return base


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

        template = template_entity.get_component(QuestTemplateComponent)
        due_at = ctx.epoch + template.duration_seconds
        quest = EntityReference()
        objective = EntityReference()
        reward = EntityReference()

        def generated_event() -> DomainEvent:
            quest_id = str(quest.require())
            return QuestGeneratedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(quest_id,),
                    quest_id=quest_id,
                    title=template.title,
                    due_at_epoch=due_at,
                )
            )

        return planned(
            MutationPlan(
                (
                    AddEntity(
                        (
                            IdentityComponent(name=template.title, kind="quest"),
                            QuestComponent(
                                quest_id=f"generated:{template_id}",
                                title=template.title,
                                description=template.objective,
                            ),
                            QuestStateComponent(due_at_epoch=due_at),
                            QuestProvenanceComponent(
                                generator="bunnyland.dragonsim",
                                source_id=str(template_id),
                                generated_at_epoch=ctx.epoch,
                            ),
                        ),
                        reference=quest,
                    ),
                    AddEntity(
                        (QuestObjectiveComponent(description=template.objective),),
                        reference=objective,
                    ),
                    AddEntity(
                        (QuestRewardComponent(description=template.reward_item_name),),
                        reference=reward,
                    ),
                    AddEdge(quest, objective, QuestHasObjective()),
                    AddEdge(quest, reward, QuestHasReward()),
                    AddEdge(character_id, quest, Contains(mode=ContainmentMode.INVENTORY)),
                ),
            ),
            generated_event,
            ctx=ctx,
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
        if not quest.has_component(QuestProvenanceComponent):
            return rejected("target is not a generated quest")
        component = quest.get_component(QuestComponent)
        state = quest.get_component(QuestStateComponent)
        if state.status != "offered":
            return rejected("quest is not offered")

        return planned(
            MutationPlan(
                (
                    AddEdge(
                        quest_id,
                        character_id,
                        QuestAcceptedBy(accepted_at_epoch=ctx.epoch),
                    ),
                    SetComponent(
                        quest_id,
                        replace(state, status="active", accepted_at_epoch=ctx.epoch),
                    ),
                )
            ),
            QuestAcceptedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(quest_id),),
                    quest_id=str(quest_id),
                    title=component.title,
                )
            ),
            ctx=ctx,
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
        if not quest.has_component(QuestProvenanceComponent):
            return rejected("target is not a generated quest")
        component = quest.get_component(QuestComponent)
        state = quest.get_component(QuestStateComponent)
        if state.status != "active":
            return rejected("quest is not active")
        if not quest.has_relationship(QuestAcceptedBy, character_id):
            return rejected("quest is not accepted by character")
        if state.due_at_epoch is not None and ctx.epoch > state.due_at_epoch:
            return rejected("quest deadline has passed")
        rewards = [
            ctx.world.get_entity(reward_id)
            for _edge, reward_id in quest.get_relationships(QuestHasReward)
            if ctx.world.has_entity(reward_id)
        ]
        if not rewards:
            return rejected("quest has no reward")

        reward_entity = rewards[0]
        reward = reward_entity.get_component(QuestRewardComponent)
        item = EntityReference()

        def completed_event() -> DomainEvent:
            item_id = str(item.require())
            return QuestCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(quest_id), item_id),
                    quest_id=str(quest_id),
                    title=component.title,
                    reward_item_id=item_id,
                )
            )

        return planned(
            MutationPlan(
                (
                    AddEntity(
                        (
                            IdentityComponent(name=reward.description, kind="quest-reward"),
                            PortableComponent(),
                        ),
                        reference=item,
                    ),
                    AddEdge(character_id, item, Contains(mode=ContainmentMode.INVENTORY)),
                    SetComponent(
                        quest_id,
                        replace(state, status="completed", completed_at_epoch=ctx.epoch),
                    ),
                    SetComponent(
                        reward_entity.id,
                        replace(
                            reward,
                            claimed=True,
                            claimed_by=str(character_id),
                            claimed_at_epoch=ctx.epoch,
                        ),
                    ),
                )
            ),
            completed_event,
            ctx=ctx,
        )


class RefuseGeneratedQuestHandler:
    command_type = "refuse-generated-quest"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        quest_id = parse_entity_id(command.payload.get("quest_id"))
        if character_id is None or quest_id is None:
            return rejected("invalid character or quest id")
        if not ctx.world.has_entity(quest_id):
            return rejected("quest does not exist")
        quest = ctx.entity(quest_id)
        if not quest.has_component(QuestProvenanceComponent):
            return rejected("target is not a generated quest")
        component = quest.get_component(QuestComponent)
        state = quest.get_component(QuestStateComponent)
        if state.status != "offered":
            return rejected("quest is not offered")
        return planned(
            MutationPlan((SetComponent(quest_id, replace(state, status="refused")),)),
            QuestRefusedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(quest_id),),
                    quest_id=str(quest_id),
                    title=component.title,
                )
            ),
            ctx=ctx,
        )


class AbandonGeneratedQuestHandler:
    command_type = "abandon-generated-quest"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        quest_id = parse_entity_id(command.payload.get("quest_id"))
        if character_id is None or quest_id is None:
            return rejected("invalid character or quest id")
        if not ctx.world.has_entity(quest_id):
            return rejected("quest does not exist")
        quest = ctx.entity(quest_id)
        if not quest.has_component(QuestProvenanceComponent):
            return rejected("target is not a generated quest")
        component = quest.get_component(QuestComponent)
        state = quest.get_component(QuestStateComponent)
        if state.status != "active" or not quest.has_relationship(QuestAcceptedBy, character_id):
            return rejected("quest is not active for character")
        return planned(
            MutationPlan((SetComponent(quest_id, replace(state, status="abandoned")),)),
            QuestAbandonedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(quest_id),),
                    quest_id=str(quest_id),
                    title=component.title,
                )
            ),
            ctx=ctx,
        )


class ExtendGeneratedQuestHandler:
    command_type = "extend-generated-quest"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        quest_id = parse_entity_id(command.payload.get("quest_id"))
        seconds = int(command.payload.get("seconds", 24 * 60 * 60))
        if character_id is None or quest_id is None:
            return rejected("invalid character or quest id")
        if seconds <= 0:
            return rejected("extension must be positive")
        if not ctx.world.has_entity(quest_id):
            return rejected("quest does not exist")
        quest = ctx.entity(quest_id)
        if not quest.has_component(QuestProvenanceComponent):
            return rejected("target is not a generated quest")
        state = quest.get_component(QuestStateComponent)
        if state.due_at_epoch is None:
            return rejected("quest has no deadline")
        updated = replace(state, due_at_epoch=state.due_at_epoch + seconds)
        return planned(
            MutationPlan((SetComponent(quest_id, updated),)),
            QuestExtendedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(quest_id),),
                    quest_id=str(quest_id),
                    due_at_epoch=updated.due_at_epoch,
                )
            ),
            ctx=ctx,
        )


class LieAboutQuestHandler:
    command_type = "lie-about-quest"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        quest_id = parse_entity_id(command.payload.get("quest_id"))
        lie = str(command.payload.get("lie", "")).strip()
        if character_id is None or quest_id is None or not lie:
            return rejected("invalid character, quest, or lie")
        if not ctx.world.has_entity(quest_id):
            return rejected("quest does not exist")
        quest = ctx.entity(quest_id)
        if not quest.has_component(QuestProvenanceComponent):
            return rejected("target is not a generated quest")
        return planned(
            MutationPlan(
                (
                    SetComponent(
                        quest_id,
                        replace(quest.get_component(QuestStateComponent), status="lied"),
                    ),
                )
            ),
            QuestLieToldEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(quest_id),),
                    quest_id=str(quest_id),
                    lie=lie,
                )
            ),
            ctx=ctx,
        )


class QuestDeadlineConsequence:
    def process(self, world: World, epoch: int) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        query = world.query().with_all(
            [QuestComponent, QuestStateComponent, QuestProvenanceComponent]
        )
        for quest in query.execute_entities():
            component = quest.get_component(QuestComponent)
            state = quest.get_component(QuestStateComponent)
            if (
                state.status != "active"
                or state.due_at_epoch is None
                or epoch <= state.due_at_epoch
            ):
                continue
            accepted = quest.get_relationships(QuestAcceptedBy)
            actor_id = str(accepted[0][1]) if accepted else None
            replace_component(
                quest,
                replace(state, status="failed", failed_at_epoch=epoch),
            )
            events.append(
                QuestFailedEvent(
                    **_travel_event_base(
                        epoch,
                        visibility=EventVisibility.PRIVATE,
                        actor_id=actor_id,
                        target_ids=(str(quest.id),),
                        quest_id=str(quest.id),
                        title=component.title,
                    )
                )
            )
        return events


__all__ = [
    "AbandonGeneratedQuestHandler",
    "AcceptGeneratedQuestHandler",
    "AskForWorkHandler",
    "CompleteGeneratedQuestHandler",
    "ExtendGeneratedQuestHandler",
    "LieAboutQuestHandler",
    "QuestAbandonedEvent",
    "QuestDeadlineConsequence",
    "QuestExtendedEvent",
    "QuestFailedEvent",
    "QuestGeneratedEvent",
    "QuestLieToldEvent",
    "QuestRefusedEvent",
    "QuestTemplateComponent",
    "RefuseGeneratedQuestHandler",
    "generated_quest_fragments",
]
