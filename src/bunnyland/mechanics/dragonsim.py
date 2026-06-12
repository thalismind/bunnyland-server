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
from ..core.components import (
    CharacterComponent,
    DeadComponent,
    DownedComponent,
    IdentityComponent,
    PortableComponent,
    SleepingComponent,
)
from ..core.ecs import (
    container_of,
    contents,
    parse_entity_id,
    reachable_ids,
    replace_component,
)
from ..core.edges import ContainmentMode, Contains
from ..core.events import DomainEvent, EventVisibility
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected
from .lifesim import SkillSetComponent


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
class PerkComponent(Component):
    """A perk gated on a lifesim skill reaching ``min_level``."""

    name: str
    skill_name: str
    min_level: int = 2


@dataclass(frozen=True)
class MemberOf(Edge):
    rank: str = "member"
    since_epoch: int = 0


@dataclass(frozen=True)
class HasPerk(Edge):
    """character -> unlocked perk entity."""

    unlocked_at_epoch: int = 0


@dataclass(frozen=True)
class AncientBeastComponent(Component):
    """A great beast whose soul can be claimed once it is slain."""

    name: str
    soul_absorbed: bool = False


@dataclass(frozen=True)
class GreatSoulComponent(Component):
    """Count of great souls a character has absorbed from slain ancient beasts."""

    souls: int = 0


@dataclass(frozen=True)
class WordOfPowerComponent(Component):
    """A learnable word of power, gated on great souls and an optional lifesim skill."""

    name: str
    min_souls: int = 1
    skill_name: str = ""
    min_skill_level: int = 0


@dataclass(frozen=True)
class KnowsWord(Edge):
    """character -> learned word-of-power entity."""

    learned_at_epoch: int = 0


@dataclass(frozen=True)
class StealthComponent(Component):
    """Whether a character is currently sneaking (unseen by witnesses)."""

    sneaking: bool = False
    since_epoch: int = 0


@dataclass(frozen=True)
class WantedComponent(Component):
    """Outstanding bounties keyed by faction id (catalogue 6.5)."""

    amounts: dict[str, int]


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


class PerkUnlockedEvent(DomainEvent):
    perk_id: str
    perk_name: str
    skill_name: str


class GreatSoulAbsorbedEvent(DomainEvent):
    beast_id: str
    beast_name: str
    souls: int


class WordOfPowerLearnedEvent(DomainEvent):
    word_id: str
    word_name: str


class WordOfPowerSpokenEvent(DomainEvent):
    word_id: str
    word_name: str


class StealthChangedEvent(DomainEvent):
    character_id: str
    sneaking: bool


class TheftCommittedEvent(DomainEvent):
    thief_id: str
    item_id: str
    victim_id: str


class CrimeWitnessedEvent(DomainEvent):
    criminal_id: str
    faction_id: str
    faction_name: str
    bounty: int
    witness_ids: tuple[str, ...] = ()


class BountyPaidEvent(DomainEvent):
    character_id: str
    faction_id: str
    amount: int


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


def _skill_level(character: Entity, skill_name: str) -> int:
    """Read a character's lifesim skill level (0 when unknown)."""
    if not character.has_component(SkillSetComponent):
        return 0
    return character.get_component(SkillSetComponent).levels.get(skill_name, 0)


class UnlockPerkHandler:
    command_type = "unlock-perk"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        perk_id = parse_entity_id(command.payload.get("perk_id"))
        if character_id is None or perk_id is None:
            return rejected("invalid character or perk id")
        if not ctx.world.has_entity(perk_id):
            return rejected("perk does not exist")
        perk_entity = ctx.entity(perk_id)
        if not perk_entity.has_component(PerkComponent):
            return rejected("target is not a perk")
        perk = perk_entity.get_component(PerkComponent)

        character = ctx.entity(character_id)
        if character.has_relationship(HasPerk, perk_id):
            return rejected("perk already unlocked")
        if _skill_level(character, perk.skill_name) < perk.min_level:
            return rejected("skill level too low for this perk")

        character.add_relationship(HasPerk(unlocked_at_epoch=ctx.epoch), perk_id)
        return ok(
            PerkUnlockedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(perk_id),),
                    perk_id=str(perk_id),
                    perk_name=perk.name,
                    skill_name=perk.skill_name,
                )
            )
        )


class AbsorbGreatSoulHandler:
    command_type = "absorb-great-soul"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        beast_id = parse_entity_id(command.payload.get("beast_id"))
        if character_id is None or beast_id is None:
            return rejected("invalid character or beast id")
        if not ctx.world.has_entity(beast_id):
            return rejected("beast does not exist")
        character = ctx.entity(character_id)
        if beast_id not in reachable_ids(ctx.world, character):
            return rejected("beast is not reachable")
        beast = ctx.entity(beast_id)
        if not beast.has_component(AncientBeastComponent):
            return rejected("target is not an ancient beast")
        if not beast.has_component(DeadComponent):
            return rejected("the beast still lives")
        ancient = beast.get_component(AncientBeastComponent)
        if ancient.soul_absorbed:
            return rejected("its great soul is already claimed")

        replace_component(beast, replace(ancient, soul_absorbed=True))
        current = (
            character.get_component(GreatSoulComponent)
            if character.has_component(GreatSoulComponent)
            else GreatSoulComponent()
        )
        souls = current.souls + 1
        replace_component(character, replace(current, souls=souls))
        return ok(
            GreatSoulAbsorbedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(beast_id),),
                    beast_id=str(beast_id),
                    beast_name=ancient.name,
                    souls=souls,
                )
            )
        )


class LearnWordOfPowerHandler:
    command_type = "learn-word-of-power"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        word_id = parse_entity_id(command.payload.get("word_id"))
        if character_id is None or word_id is None:
            return rejected("invalid character or word id")
        if not ctx.world.has_entity(word_id):
            return rejected("word does not exist")
        word_entity = ctx.entity(word_id)
        if not word_entity.has_component(WordOfPowerComponent):
            return rejected("target is not a word of power")
        word = word_entity.get_component(WordOfPowerComponent)

        character = ctx.entity(character_id)
        if character.has_relationship(KnowsWord, word_id):
            return rejected("word already learned")
        souls = (
            character.get_component(GreatSoulComponent).souls
            if character.has_component(GreatSoulComponent)
            else 0
        )
        if souls < word.min_souls:
            return rejected("not enough great souls to learn this word")
        if word.skill_name and _skill_level(character, word.skill_name) < word.min_skill_level:
            return rejected("skill level too low for this word")

        character.add_relationship(KnowsWord(learned_at_epoch=ctx.epoch), word_id)
        return ok(
            WordOfPowerLearnedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(word_id),),
                    word_id=str(word_id),
                    word_name=word.name,
                )
            )
        )


class SpeakWordOfPowerHandler:
    command_type = "speak-word-of-power"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        word_id = parse_entity_id(command.payload.get("word_id"))
        if character_id is None or word_id is None:
            return rejected("invalid character or word id")
        if not ctx.world.has_entity(word_id):
            return rejected("word does not exist")
        character = ctx.entity(character_id)
        if not character.has_relationship(KnowsWord, word_id):
            return rejected("you have not learned that word")
        word_entity = ctx.entity(word_id)
        word_name = (
            word_entity.get_component(WordOfPowerComponent).name
            if word_entity.has_component(WordOfPowerComponent)
            else _name(word_entity)
        )
        return ok(
            WordOfPowerSpokenEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(word_id),),
                    word_id=str(word_id),
                    word_name=word_name,
                )
            )
        )


DEFAULT_BOUNTY = 10


def _is_sneaking(character: Entity) -> bool:
    return (
        character.has_component(StealthComponent)
        and character.get_component(StealthComponent).sneaking
    )


def _awake_witnesses(world: World, room_id: EntityId, thief_id: EntityId) -> list[EntityId]:
    """Awake, conscious characters sharing the room who could see a crime."""
    witnesses: list[EntityId] = []
    for entity_id in contents(world.get_entity(room_id)):
        if entity_id == thief_id:
            continue
        entity = world.get_entity(entity_id)
        if not entity.has_component(CharacterComponent):
            continue
        if (
            entity.has_component(SleepingComponent)
            or entity.has_component(DownedComponent)
            or entity.has_component(DeadComponent)
        ):
            continue
        witnesses.append(entity_id)
    return witnesses


class SneakHandler:
    command_type = "sneak"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        character = ctx.entity(character_id)
        sneaking = not _is_sneaking(character)
        if character.has_component(StealthComponent):
            replace_component(
                character,
                replace(
                    character.get_component(StealthComponent),
                    sneaking=sneaking,
                    since_epoch=ctx.epoch,
                ),
            )
        else:
            character.add_component(StealthComponent(sneaking=sneaking, since_epoch=ctx.epoch))
        return ok(
            StealthChangedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    character_id=str(character_id),
                    sneaking=sneaking,
                )
            )
        )


class StealHandler:
    command_type = "steal"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        thief_id = parse_entity_id(command.character_id)
        victim_id = parse_entity_id(command.payload.get("target_id"))
        item_id = parse_entity_id(command.payload.get("item_id"))
        if thief_id is None or victim_id is None or item_id is None:
            return rejected("invalid thief, target, or item id")
        if not ctx.world.has_entity(victim_id) or not ctx.world.has_entity(item_id):
            return rejected("target or item does not exist")
        thief = ctx.entity(thief_id)
        victim = ctx.entity(victim_id)
        item = ctx.entity(item_id)
        room_id = container_of(thief)
        if room_id is None or container_of(victim) != room_id:
            return rejected("target is not present")
        if container_of(item) != victim_id:
            return rejected("item is not carried by the target")
        if (
            not item.has_component(PortableComponent)
            or not item.get_component(PortableComponent).can_pick_up
        ):
            return rejected("item cannot be taken")

        victim.remove_relationship(Contains, item_id)
        thief.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item_id)
        events: list[DomainEvent] = [
            TheftCommittedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(thief_id),
                    room_id=str(room_id),
                    target_ids=(str(victim_id), str(item_id)),
                    thief_id=str(thief_id),
                    item_id=str(item_id),
                    victim_id=str(victim_id),
                )
            )
        ]
        events.extend(self._witness_bounties(ctx, thief, thief_id, room_id))
        return ok(*events)

    def _witness_bounties(
        self, ctx: HandlerContext, thief: Entity, thief_id: EntityId, room_id: EntityId
    ) -> list[DomainEvent]:
        if _is_sneaking(thief):
            return []
        faction_witnesses: dict[EntityId, list[str]] = {}
        for witness_id in _awake_witnesses(ctx.world, room_id, thief_id):
            for _edge, faction_id in ctx.world.get_entity(witness_id).get_relationships(MemberOf):
                faction_witnesses.setdefault(faction_id, []).append(str(witness_id))
        if not faction_witnesses:
            return []

        amounts = (
            dict(thief.get_component(WantedComponent).amounts)
            if thief.has_component(WantedComponent)
            else {}
        )
        events: list[DomainEvent] = []
        for faction_id, witness_ids in faction_witnesses.items():
            key = str(faction_id)
            amounts[key] = amounts.get(key, 0) + DEFAULT_BOUNTY
            faction = ctx.world.get_entity(faction_id)
            faction_name = (
                faction.get_component(FactionComponent).name
                if faction.has_component(FactionComponent)
                else _name(faction)
            )
            events.append(
                CrimeWitnessedEvent(
                    **ctx.event_base(
                        visibility=EventVisibility.ROOM,
                        actor_id=str(thief_id),
                        room_id=str(room_id),
                        target_ids=tuple(witness_ids),
                        criminal_id=str(thief_id),
                        faction_id=key,
                        faction_name=faction_name,
                        bounty=amounts[key],
                        witness_ids=tuple(witness_ids),
                    )
                )
            )
        if thief.has_component(WantedComponent):
            replace_component(thief, WantedComponent(amounts=amounts))
        else:
            thief.add_component(WantedComponent(amounts=amounts))
        return events


class PayBountyHandler:
    command_type = "pay-bounty"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        faction_id = parse_entity_id(command.payload.get("faction_id"))
        if character_id is None or faction_id is None:
            return rejected("invalid character or faction id")
        character = ctx.entity(character_id)
        if not character.has_component(WantedComponent):
            return rejected("you have no bounties")
        amounts = dict(character.get_component(WantedComponent).amounts)
        key = str(faction_id)
        if key not in amounts:
            return rejected("you have no bounty with that faction")
        paid = amounts.pop(key)
        replace_component(character, WantedComponent(amounts=amounts))
        return ok(
            BountyPaidEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(key,),
                    character_id=str(character_id),
                    faction_id=key,
                    amount=paid,
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

    for _perk_edge, perk_id in character.get_relationships(HasPerk):
        if not world.has_entity(perk_id):
            continue
        perk = world.get_entity(perk_id)
        if perk.has_component(PerkComponent):
            lines.append(f"Perk unlocked: {perk.get_component(PerkComponent).name}.")

    if character.has_component(GreatSoulComponent):
        souls = character.get_component(GreatSoulComponent).souls
        if souls > 0:
            lines.append(f"Great souls absorbed: {souls}.")
    for _word_edge, word_id in character.get_relationships(KnowsWord):
        if not world.has_entity(word_id):
            continue
        word = world.get_entity(word_id)
        if word.has_component(WordOfPowerComponent):
            lines.append(f"Word of power known: {word.get_component(WordOfPowerComponent).name}.")

    if _is_sneaking(character):
        lines.append("You are sneaking.")
    if character.has_component(WantedComponent):
        for faction_key, amount in character.get_component(WantedComponent).amounts.items():
            faction_name = faction_key
            parsed = parse_entity_id(faction_key)
            if parsed is not None and world.has_entity(parsed):
                faction = world.get_entity(parsed)
                if faction.has_component(FactionComponent):
                    faction_name = faction.get_component(FactionComponent).name
            lines.append(f"Bounty of {amount} with {faction_name}.")

    for entity_id in reachable_ids(world, character):
        entity = world.get_entity(entity_id)
        if entity.has_component(PointOfInterestComponent):
            poi = entity.get_component(PointOfInterestComponent)
            if not poi.discovered:
                lines.append(f"Nearby undiscovered {poi.location_type}: {_name(entity)}.")
    return sorted(lines)


__all__ = [
    "AbsorbGreatSoulHandler",
    "AcceptQuestHandler",
    "AncientBeastComponent",
    "WantedComponent",
    "BountyPaidEvent",
    "CompleteObjectiveHandler",
    "CrimeWitnessedEvent",
    "DiscoverLocationHandler",
    "DiscoveryComponent",
    "FactionComponent",
    "FactionJoinedEvent",
    "FactionLeftEvent",
    "FactionReputationComponent",
    "GreatSoulAbsorbedEvent",
    "GreatSoulComponent",
    "HasPerk",
    "JoinFactionHandler",
    "KnowsWord",
    "LearnWordOfPowerHandler",
    "LeaveFactionHandler",
    "LocationDiscoveredEvent",
    "MemberOf",
    "PayBountyHandler",
    "PerkComponent",
    "PerkUnlockedEvent",
    "PointOfInterestComponent",
    "QuestAcceptedEvent",
    "QuestComponent",
    "QuestCompletedEvent",
    "QuestObjectiveCompletedEvent",
    "QuestObjectiveComponent",
    "QuestRewardComponent",
    "QuestStageComponent",
    "SneakHandler",
    "SpeakWordOfPowerHandler",
    "StealHandler",
    "StealthChangedEvent",
    "StealthComponent",
    "TheftCommittedEvent",
    "UnlockPerkHandler",
    "WordOfPowerComponent",
    "WordOfPowerLearnedEvent",
    "WordOfPowerSpokenEvent",
    "dragonsim_fragments",
]
