"""Dragon-sim exploration, quests, and faction foundations.

This first slice intentionally avoids combat, magic, dragons, and radiant generation. It
adds explicit state for discoverable locations, quest logs, objectives, and faction
membership so later systems have stable entities and events to build on.
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
class PointOfInterestComponent(Component):
    location_type: str = "landmark"
    region: str = ""
    discovered: bool = False


@dataclass(frozen=True)
class DiscoveryComponent(Component):
    discovered_by: tuple[str, ...] = ()
    first_discovered_at_epoch: int | None = None


@dataclass(frozen=True)
class QuestComponent(Component):
    quest_id: str
    title: str
    status: str = "offered"
    accepted_by: tuple[str, ...] = ()
    completed_at_epoch: int | None = None


@dataclass(frozen=True)
class QuestStageComponent(Component):
    quest_id: str
    stage: int = 0


@dataclass(frozen=True)
class QuestObjectiveComponent(Component):
    quest_id: str
    description: str
    completed: bool = False
    completed_by: str | None = None


@dataclass(frozen=True)
class QuestRewardComponent(Component):
    quest_id: str
    description: str
    item_ids: tuple[str, ...] = ()
    claimed: bool = False
    claimed_by: str | None = None


@dataclass(frozen=True)
class FactionComponent(Component):
    name: str
    ideology: str = ""


@dataclass(frozen=True)
class FactionReputationComponent(Component):
    scores: dict[str, int]


@dataclass(frozen=True)
class MemberOf(Edge):
    rank: str = "member"
    since_epoch: int = 0


class LocationDiscoveredEvent(DomainEvent):
    location_id: str
    location_type: str
    region: str = ""


class QuestAcceptedEvent(DomainEvent):
    quest_id: str
    quest_key: str
    title: str


class QuestObjectiveCompletedEvent(DomainEvent):
    quest_id: str
    objective_id: str
    description: str


class QuestCompletedEvent(DomainEvent):
    quest_id: str
    quest_key: str
    title: str


class FactionJoinedEvent(DomainEvent):
    faction_id: str
    faction_name: str
    rank: str = "member"


class FactionLeftEvent(DomainEvent):
    faction_id: str
    faction_name: str


def _room_id(world: World, character_id: EntityId) -> str | None:
    raw = container_of(world.get_entity(character_id))
    return str(raw) if raw is not None else None


def _name(entity: Entity) -> str:
    if entity.has_component(IdentityComponent):
        return entity.get_component(IdentityComponent).name
    return str(entity.id)


def _quest_by_key(world: World, quest_key: str) -> tuple[EntityId, Entity] | None:
    parsed = parse_entity_id(quest_key)
    if parsed is not None and world.has_entity(parsed):
        return parsed, world.get_entity(parsed)
    for entity in world.query().with_all([QuestComponent]).execute_entities():
        if entity.get_component(QuestComponent).quest_id == quest_key:
            return entity.id, entity
    return None


def _objective_by_key(world: World, objective_key: str) -> tuple[EntityId, Entity] | None:
    parsed = parse_entity_id(objective_key)
    if parsed is not None and world.has_entity(parsed):
        return parsed, world.get_entity(parsed)
    for entity in world.query().with_all([QuestObjectiveComponent]).execute_entities():
        objective = entity.get_component(QuestObjectiveComponent)
        if objective.description == objective_key:
            return entity.id, entity
    return None


def _quest_objectives(world: World, quest_id: str) -> list[Entity]:
    return [
        entity
        for entity in world.query().with_all([QuestObjectiveComponent]).execute_entities()
        if entity.get_component(QuestObjectiveComponent).quest_id == quest_id
    ]


def _quest_rewards(world: World, quest_id: str) -> list[Entity]:
    return [
        entity
        for entity in world.query().with_all([QuestRewardComponent]).execute_entities()
        if entity.get_component(QuestRewardComponent).quest_id == quest_id
    ]


def _accepted_by(quest: QuestComponent, character_id: EntityId) -> bool:
    return str(character_id) in quest.accepted_by


def _contained_item(world: World, raw_item_id: str) -> tuple[EntityId, Entity] | None:
    item_id = parse_entity_id(raw_item_id)
    if item_id is None or not world.has_entity(item_id):
        return None
    return item_id, world.get_entity(item_id)


class DiscoverLocationHandler:
    command_type = "discover-location"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        location_id = parse_entity_id(command.payload.get("location_id"))
        if character_id is None or location_id is None:
            return rejected("invalid character or location id")
        if not ctx.world.has_entity(location_id):
            return rejected("location does not exist")

        character = ctx.entity(character_id)
        if location_id not in reachable_ids(ctx.world, character):
            return rejected("location is not reachable")
        location = ctx.entity(location_id)
        if not location.has_component(PointOfInterestComponent):
            return rejected("target is not discoverable")
        poi = location.get_component(PointOfInterestComponent)
        discovery = (
            location.get_component(DiscoveryComponent)
            if location.has_component(DiscoveryComponent)
            else DiscoveryComponent()
        )
        if str(character_id) in discovery.discovered_by:
            return rejected("location already discovered")

        discovered_by = tuple((*discovery.discovered_by, str(character_id)))
        replace_component(location, replace(poi, discovered=True))
        replace_component(
            location,
            replace(
                discovery,
                discovered_by=discovered_by,
                first_discovered_at_epoch=discovery.first_discovered_at_epoch or ctx.epoch,
            ),
        )
        return ok(
            LocationDiscoveredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(location_id),),
                    location_id=str(location_id),
                    location_type=poi.location_type,
                    region=poi.region,
                )
            )
        )


class AcceptQuestHandler:
    command_type = "accept-quest"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        quest_key = str(command.payload.get("quest_id", "")).strip()
        if character_id is None or not quest_key:
            return rejected("invalid character or quest id")
        result = _quest_by_key(ctx.world, quest_key)
        if result is None:
            return rejected("quest does not exist")
        quest_entity_id, quest_entity = result
        if not quest_entity.has_component(QuestComponent):
            return rejected("target is not a quest")

        quest = quest_entity.get_component(QuestComponent)
        if quest.status == "completed":
            return rejected("quest is already complete")
        if _accepted_by(quest, character_id):
            return rejected("quest already accepted")

        accepted_by = tuple((*quest.accepted_by, str(character_id)))
        replace_component(quest_entity, replace(quest, status="active", accepted_by=accepted_by))
        return ok(
            QuestAcceptedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(quest_entity_id),),
                    quest_id=str(quest_entity_id),
                    quest_key=quest.quest_id,
                    title=quest.title,
                )
            )
        )


class CompleteObjectiveHandler:
    command_type = "complete-objective"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        objective_key = str(command.payload.get("objective_id", "")).strip()
        if character_id is None or not objective_key:
            return rejected("invalid character or objective id")
        objective_result = _objective_by_key(ctx.world, objective_key)
        if objective_result is None:
            return rejected("objective does not exist")
        objective_id, objective_entity = objective_result
        if not objective_entity.has_component(QuestObjectiveComponent):
            return rejected("target is not a quest objective")
        objective = objective_entity.get_component(QuestObjectiveComponent)
        if objective.completed:
            return rejected("objective is already complete")

        quest_result = _quest_by_key(ctx.world, objective.quest_id)
        if quest_result is None:
            return rejected("quest does not exist")
        quest_entity_id, quest_entity = quest_result
        quest = quest_entity.get_component(QuestComponent)
        if not _accepted_by(quest, character_id):
            return rejected("quest is not accepted")

        objectives = _quest_objectives(ctx.world, quest.quest_id)
        will_complete_quest = bool(objectives) and all(
            item.id == objective_id or item.get_component(QuestObjectiveComponent).completed
            for item in objectives
        )
        rewards: list[Entity] = []
        reward_items: list[tuple[EntityId, Entity]] = []
        if will_complete_quest:
            rewards = [
                reward
                for reward in _quest_rewards(ctx.world, quest.quest_id)
                if not reward.get_component(QuestRewardComponent).claimed
            ]
            for reward in rewards:
                for raw_item_id in reward.get_component(QuestRewardComponent).item_ids:
                    item = _contained_item(ctx.world, raw_item_id)
                    if item is None:
                        return rejected("quest reward item does not exist")
                    reward_items.append(item)

        replace_component(
            objective_entity,
            replace(objective, completed=True, completed_by=str(character_id)),
        )
        events: list[DomainEvent] = [
            QuestObjectiveCompletedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(quest_entity_id), str(objective_id)),
                    quest_id=str(quest_entity_id),
                    objective_id=str(objective_id),
                    description=objective.description,
                )
            )
        ]
        if will_complete_quest:
            replace_component(
                quest_entity,
                replace(quest, status="completed", completed_at_epoch=ctx.epoch),
            )
            character = ctx.entity(character_id)
            for item_id, item in reward_items:
                source_id = container_of(item)
                if source_id is not None:
                    ctx.entity(source_id).remove_relationship(Contains, item_id)
                character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item_id)
            for reward in rewards:
                component = reward.get_component(QuestRewardComponent)
                replace_component(
                    reward,
                    replace(component, claimed=True, claimed_by=str(character_id)),
                )
            events.append(
                QuestCompletedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.PRIVATE,
                        actor_id=str(character_id),
                        room_id=_room_id(ctx.world, character_id),
                        target_ids=(str(quest_entity_id),),
                        quest_id=str(quest_entity_id),
                        quest_key=quest.quest_id,
                        title=quest.title,
                    )
                )
            )
        return ok(*events)


class JoinFactionHandler:
    command_type = "join-faction"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        faction_id = parse_entity_id(command.payload.get("faction_id"))
        rank = str(command.payload.get("rank", "member")).strip() or "member"
        if character_id is None or faction_id is None:
            return rejected("invalid character or faction id")
        if not ctx.world.has_entity(faction_id):
            return rejected("faction does not exist")
        character = ctx.entity(character_id)
        faction = ctx.entity(faction_id)
        if not faction.has_component(FactionComponent):
            return rejected("target is not a faction")
        if character.has_relationship(MemberOf, faction_id):
            return rejected("already a faction member")

        character.add_relationship(MemberOf(rank=rank, since_epoch=ctx.epoch), faction_id)
        faction_name = faction.get_component(FactionComponent).name
        return ok(
            FactionJoinedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(faction_id),),
                    faction_id=str(faction_id),
                    faction_name=faction_name,
                    rank=rank,
                )
            )
        )


class LeaveFactionHandler:
    command_type = "leave-faction"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        faction_id = parse_entity_id(command.payload.get("faction_id"))
        if character_id is None or faction_id is None:
            return rejected("invalid character or faction id")
        if not ctx.world.has_entity(faction_id):
            return rejected("faction does not exist")
        character = ctx.entity(character_id)
        faction = ctx.entity(faction_id)
        if not faction.has_component(FactionComponent):
            return rejected("target is not a faction")
        if not character.has_relationship(MemberOf, faction_id):
            return rejected("not a faction member")

        character.remove_relationship(MemberOf, faction_id)
        faction_name = faction.get_component(FactionComponent).name
        return ok(
            FactionLeftEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(faction_id),),
                    faction_id=str(faction_id),
                    faction_name=faction_name,
                )
            )
        )


def dragonsim_fragments(world: World, character: Entity) -> list[str]:
    lines: list[str] = []
    for edge, faction_id in character.get_relationships(MemberOf):
        faction = world.get_entity(faction_id)
        faction_name = (
            faction.get_component(FactionComponent).name
            if faction.has_component(FactionComponent)
            else _name(faction)
        )
        lines.append(f"You are a {edge.rank} of {faction_name}.")

    for quest in world.query().with_all([QuestComponent]).execute_entities():
        component = quest.get_component(QuestComponent)
        if component.status == "active" and str(character.id) in component.accepted_by:
            lines.append(f"Active quest: {component.title}.")

    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        if entity.has_component(PointOfInterestComponent):
            poi = entity.get_component(PointOfInterestComponent)
            if not poi.discovered:
                lines.append(f"Nearby undiscovered {poi.location_type}: {_name(entity)}.")
    return sorted(lines)


__all__ = [
    "AcceptQuestHandler",
    "CompleteObjectiveHandler",
    "DiscoverLocationHandler",
    "DiscoveryComponent",
    "FactionComponent",
    "FactionJoinedEvent",
    "FactionLeftEvent",
    "FactionReputationComponent",
    "JoinFactionHandler",
    "LeaveFactionHandler",
    "LocationDiscoveredEvent",
    "MemberOf",
    "PointOfInterestComponent",
    "QuestAcceptedEvent",
    "QuestComponent",
    "QuestCompletedEvent",
    "QuestObjectiveCompletedEvent",
    "QuestObjectiveComponent",
    "QuestRewardComponent",
    "QuestStageComponent",
    "dragonsim_fragments",
]
