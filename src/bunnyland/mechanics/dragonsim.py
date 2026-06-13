"""Dragon-sim exploration, quests, factions, law, and fixed adventure magic."""

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
    ReadableComponent,
    SleepingComponent,
    WritableComponent,
)
from ..core.ecs import (
    container_of,
    contents,
    parse_entity_id,
    reachable_ids,
    replace_component,
    spawn_entity,
)
from ..core.edges import ContainmentMode, Contains
from ..core.events import DomainEvent, EventVisibility
from ..core.handlers import HandlerContext, HandlerResult, ok, rejected
from .lifesim import SkillSetComponent, _add_skill_xp


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
class MapMarkerComponent(Component):
    label: str = ""
    marker_type: str = "landmark"
    marked_by: tuple[str, ...] = ()
    marked_at_epoch: int = 0


@dataclass(frozen=True)
class EncounterZoneComponent(Component):
    zone_type: str = "wilderness"
    danger_rating: int = 1
    active: bool = True
    last_triggered_at_epoch: int = 0


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
    tracked_by: tuple[str, ...] = ()
    branch: str = ""


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
class GuardComponent(Component):
    faction_id: str
    bribe_amount: int = 10


@dataclass(frozen=True)
class JailComponent(Component):
    faction_id: str
    release_epoch: int
    reason: str = "sentence"


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


@dataclass(frozen=True)
class LockDifficultyComponent(Component):
    difficulty: int = 1
    locked: bool = True


@dataclass(frozen=True)
class LoreBookComponent(Component):
    """Readable lore or skill book (catalogue 6: books/lore)."""

    title: str
    lore: str = ""
    skill_name: str = ""
    skill_xp: float = 0.0
    read_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class MagickaComponent(Component):
    current: int = 10
    maximum: int = 10
    regen_per_hour: int = 2
    last_updated_epoch: int = 0


@dataclass(frozen=True)
class SpellCooldownComponent(Component):
    cooldown_seconds: int = 0
    ready_at_epoch: int = 0


@dataclass(frozen=True)
class PersuasionComponent(Component):
    disposition: int = 0
    persuaded_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurrenderComponent(Component):
    surrendered_to: str | None = None
    reason: str = ""
    at_epoch: int = 0


@dataclass(frozen=True)
class SpellComponent(Component):
    name: str
    school: str = "alteration"
    magicka_cost: int = 1
    skill_name: str = "magic"
    min_skill_level: int = 0
    effect: str = ""
    magnitude: int = 1


@dataclass(frozen=True)
class PotionRecipeComponent(Component):
    name: str
    potion_name: str
    school: str = "alchemy"
    skill_name: str = "alchemy"
    min_skill_level: int = 0
    ingredient_ids: tuple[str, ...] = ()
    effect: str = ""


@dataclass(frozen=True)
class PotionComponent(Component):
    name: str
    effect: str = ""
    potency: int = 1


@dataclass(frozen=True)
class ArtifactComponent(Component):
    name: str
    effect: str = ""
    charges: int = 1
    identified_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class CarvableComponent(Component):
    remaining_space: int | None = None


@dataclass(frozen=True)
class VoiceInscriptionComponent(Component):
    word_id: str
    phrase: str = ""
    studied_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class KnowsSpell(Edge):
    learned_at_epoch: int = 0


class LocationDiscoveredEvent(DomainEvent):
    location_id: str
    location_type: str
    region: str = ""


class MapMarkerAddedEvent(DomainEvent):
    location_id: str
    label: str
    marker_type: str


class EncounterTriggeredEvent(DomainEvent):
    zone_id: str
    zone_type: str
    danger_rating: int


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


class QuestTrackedEvent(DomainEvent):
    quest_id: str
    title: str


class QuestDeclinedEvent(DomainEvent):
    quest_id: str
    title: str


class QuestBranchChosenEvent(DomainEvent):
    quest_id: str
    branch: str


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


class CrimeReportedEvent(DomainEvent):
    criminal_id: str
    faction_id: str
    reporter_id: str
    bounty: int


class BountyPaidEvent(DomainEvent):
    character_id: str
    faction_id: str
    amount: int


class FactionRankChangedEvent(DomainEvent):
    faction_id: str
    faction_name: str
    old_rank: str
    new_rank: str


class GuardBribedEvent(DomainEvent):
    guard_id: str
    faction_id: str
    amount: int


class JailSentenceServedEvent(DomainEvent):
    character_id: str
    faction_id: str


class LockPickedEvent(DomainEvent):
    lock_id: str
    difficulty: int


class LoreBookReadEvent(DomainEvent):
    book_id: str
    title: str
    skill_name: str = ""
    skill_xp_awarded: float = 0.0


class SpellLearnedEvent(DomainEvent):
    spell_id: str
    spell_name: str


class DragonSpellCastEvent(DomainEvent):
    spell_id: str
    spell_name: str
    school: str
    magicka_spent: int


class PotionBrewedEvent(DomainEvent):
    recipe_id: str
    potion_id: str
    potion_name: str


class ArtifactUsedEvent(DomainEvent):
    artifact_id: str
    artifact_name: str
    remaining_charges: int


class ArtifactIdentifiedEvent(DomainEvent):
    artifact_id: str
    artifact_name: str


class MagickaRecoveredEvent(DomainEvent):
    character_id: str
    current: int
    maximum: int


class PersuasionAttemptedEvent(DomainEvent):
    target_id: str
    disposition: int


class SurrenderedEvent(DomainEvent):
    character_id: str
    surrendered_to: str


class AncientBeastAppeasedEvent(DomainEvent):
    beast_id: str
    beast_name: str
    method: str


class VoicePhraseInscribedEvent(DomainEvent):
    target_id: str
    word_id: str
    phrase: str


class VoiceInscriptionStudiedEvent(DomainEvent):
    target_id: str
    word_id: str


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


class MarkMapHandler:
    command_type = "mark-map"

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
            return rejected("target is not a mappable location")

        poi = location.get_component(PointOfInterestComponent)
        marker = (
            location.get_component(MapMarkerComponent)
            if location.has_component(MapMarkerComponent)
            else MapMarkerComponent(
                label=str(command.payload.get("label") or _name(location)),
                marker_type=poi.location_type,
            )
        )
        if str(character_id) in marker.marked_by:
            return rejected("location is already marked")
        marked_by = tuple((*marker.marked_by, str(character_id)))
        label = str(command.payload.get("label") or marker.label or _name(location))
        updated = replace(
            marker,
            label=label,
            marker_type=marker.marker_type or poi.location_type,
            marked_by=marked_by,
            marked_at_epoch=ctx.epoch,
        )
        replace_component(location, updated)
        return ok(
            MapMarkerAddedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(location_id),),
                    location_id=str(location_id),
                    label=updated.label,
                    marker_type=updated.marker_type,
                )
            )
        )


class TriggerEncounterHandler:
    command_type = "trigger-encounter"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        zone_id = parse_entity_id(command.payload.get("zone_id"))
        if character_id is None or zone_id is None:
            return rejected("invalid character or encounter zone id")
        if not ctx.world.has_entity(zone_id):
            return rejected("encounter zone does not exist")
        character = ctx.entity(character_id)
        if zone_id not in reachable_ids(ctx.world, character):
            return rejected("encounter zone is not reachable")
        zone_entity = ctx.entity(zone_id)
        if not zone_entity.has_component(EncounterZoneComponent):
            return rejected("target is not an encounter zone")
        zone = zone_entity.get_component(EncounterZoneComponent)
        if not zone.active:
            return rejected("encounter zone is inactive")

        replace_component(zone_entity, replace(zone, last_triggered_at_epoch=ctx.epoch))
        return ok(
            EncounterTriggeredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(zone_id),),
                    zone_id=str(zone_id),
                    zone_type=zone.zone_type,
                    danger_rating=zone.danger_rating,
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


class TrackQuestHandler:
    command_type = "track-quest"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        quest_key = str(command.payload.get("quest_id", "")).strip()
        if character_id is None or not quest_key:
            return rejected("invalid character or quest id")
        result = _quest_by_key(ctx.world, quest_key)
        if result is None:
            return rejected("quest does not exist")
        quest_id, quest_entity = result
        quest = quest_entity.get_component(QuestComponent)
        if not _accepted_by(quest, character_id):
            return rejected("quest is not accepted")
        stages = [
            entity
            for entity in ctx.world.query().with_all([QuestStageComponent]).execute_entities()
            if entity.get_component(QuestStageComponent).quest_id == quest.quest_id
        ]
        stage_entity = stages[0] if stages else quest_entity
        stage = (
            stage_entity.get_component(QuestStageComponent)
            if stage_entity.has_component(QuestStageComponent)
            else QuestStageComponent(quest_id=quest.quest_id)
        )
        tracked_by = tuple(sorted((*stage.tracked_by, str(character_id))))
        replace_component(stage_entity, replace(stage, tracked_by=tracked_by))
        return ok(
            QuestTrackedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(quest_id),),
                    quest_id=str(quest_id),
                    title=quest.title,
                )
            )
        )


class DeclineQuestHandler:
    command_type = "decline-quest"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        quest_key = str(command.payload.get("quest_id", "")).strip()
        if character_id is None or not quest_key:
            return rejected("invalid character or quest id")
        result = _quest_by_key(ctx.world, quest_key)
        if result is None:
            return rejected("quest does not exist")
        quest_id, quest_entity = result
        quest = quest_entity.get_component(QuestComponent)
        if quest.status == "completed":
            return rejected("quest is already complete")
        if _accepted_by(quest, character_id):
            return rejected("accepted quest cannot be declined")
        replace_component(quest_entity, replace(quest, status="declined"))
        return ok(
            QuestDeclinedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(quest_id),),
                    quest_id=str(quest_id),
                    title=quest.title,
                )
            )
        )


class ChooseQuestBranchHandler:
    command_type = "choose-quest-branch"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        quest_key = str(command.payload.get("quest_id", "")).strip()
        branch = str(command.payload.get("branch", "")).strip()
        if character_id is None or not quest_key or not branch:
            return rejected("invalid character, quest, or branch")
        result = _quest_by_key(ctx.world, quest_key)
        if result is None:
            return rejected("quest does not exist")
        quest_id, quest_entity = result
        quest = quest_entity.get_component(QuestComponent)
        if not _accepted_by(quest, character_id):
            return rejected("quest is not accepted")
        stages = [
            entity
            for entity in ctx.world.query().with_all([QuestStageComponent]).execute_entities()
            if entity.get_component(QuestStageComponent).quest_id == quest.quest_id
        ]
        stage_entity = stages[0] if stages else quest_entity
        stage = (
            stage_entity.get_component(QuestStageComponent)
            if stage_entity.has_component(QuestStageComponent)
            else QuestStageComponent(quest_id=quest.quest_id)
        )
        replace_component(stage_entity, replace(stage, branch=branch))
        return ok(
            QuestBranchChosenEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(quest_id),),
                    quest_id=str(quest_id),
                    branch=branch,
                )
            )
        )


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


class ChangeFactionRankHandler:
    command_type = "change-faction-rank"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        faction_id = parse_entity_id(command.payload.get("faction_id"))
        new_rank = str(command.payload.get("rank", "")).strip()
        if character_id is None or faction_id is None or not new_rank:
            return rejected("invalid character, faction, or rank")
        if not ctx.world.has_entity(faction_id):
            return rejected("faction does not exist")
        faction = ctx.entity(faction_id)
        if not faction.has_component(FactionComponent):
            return rejected("target is not a faction")
        character = ctx.entity(character_id)
        memberships = character.get_relationships(MemberOf)
        current = next((edge for edge, target in memberships if target == faction_id), None)
        if current is None:
            return rejected("not a faction member")

        character.remove_relationship(MemberOf, faction_id)
        character.add_relationship(
            MemberOf(rank=new_rank, since_epoch=current.since_epoch), faction_id
        )
        faction_name = faction.get_component(FactionComponent).name
        return ok(
            FactionRankChangedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(faction_id),),
                    faction_id=str(faction_id),
                    faction_name=faction_name,
                    old_rank=current.rank,
                    new_rank=new_rank,
                )
            )
        )


class BribeGuardHandler:
    command_type = "bribe-guard"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        guard_id = parse_entity_id(command.payload.get("guard_id"))
        if character_id is None or guard_id is None:
            return rejected("invalid character or guard id")
        if not ctx.world.has_entity(guard_id):
            return rejected("guard does not exist")
        character = ctx.entity(character_id)
        if guard_id not in reachable_ids(ctx.world, character):
            return rejected("guard is not reachable")
        guard = ctx.entity(guard_id)
        if not guard.has_component(GuardComponent):
            return rejected("target is not a guard")
        component = guard.get_component(GuardComponent)
        if character.has_component(WantedComponent):
            amounts = dict(character.get_component(WantedComponent).amounts)
            if component.faction_id in amounts:
                amounts[component.faction_id] = max(
                    0, amounts[component.faction_id] - component.bribe_amount
                )
                if amounts[component.faction_id] == 0:
                    amounts.pop(component.faction_id)
                replace_component(character, WantedComponent(amounts=amounts))
        return ok(
            GuardBribedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(guard_id),),
                    guard_id=str(guard_id),
                    faction_id=component.faction_id,
                    amount=component.bribe_amount,
                )
            )
        )


class ServeJailTimeHandler:
    command_type = "serve-jail-time"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        character = ctx.entity(character_id)
        if not character.has_component(JailComponent):
            return rejected("not jailed")
        sentence = character.get_component(JailComponent)
        if ctx.epoch < sentence.release_epoch:
            return rejected("sentence is not complete")
        character.remove_component(JailComponent)
        if character.has_component(WantedComponent):
            amounts = dict(character.get_component(WantedComponent).amounts)
            amounts.pop(sentence.faction_id, None)
            replace_component(character, WantedComponent(amounts=amounts))
        return ok(
            JailSentenceServedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    character_id=str(character_id),
                    faction_id=sentence.faction_id,
                )
            )
        )


class PersuadeHandler:
    command_type = "persuade"

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
        amount = int(command.payload.get("amount", 1))
        current = (
            target.get_component(PersuasionComponent)
            if target.has_component(PersuasionComponent)
            else PersuasionComponent()
        )
        updated = replace(
            current,
            disposition=current.disposition + amount,
            persuaded_by=tuple(sorted((*current.persuaded_by, str(character_id)))),
        )
        replace_component(target, updated)
        return ok(
            PersuasionAttemptedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.DIRECTED,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target_id),),
                    target_id=str(target_id),
                    disposition=updated.disposition,
                )
            )
        )


class SurrenderHandler:
    command_type = "surrender"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        if character_id is None:
            return rejected("invalid character id")
        character = ctx.entity(character_id)
        if target_id is not None and not ctx.world.has_entity(target_id):
            return rejected("target does not exist")
        surrendered_to = str(target_id) if target_id is not None else ""
        reason = str(command.payload.get("reason", "")).strip()
        replace_component(
            character,
            SurrenderComponent(
                surrendered_to=surrendered_to or None,
                reason=reason,
                at_epoch=ctx.epoch,
            ),
        )
        return ok(
            SurrenderedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(surrendered_to,) if surrendered_to else (),
                    character_id=str(character_id),
                    surrendered_to=surrendered_to,
                )
            )
        )


class ReportCrimeHandler:
    command_type = "report-crime"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        reporter_id = parse_entity_id(command.character_id)
        criminal_id = parse_entity_id(command.payload.get("criminal_id"))
        faction_id = parse_entity_id(command.payload.get("faction_id"))
        if reporter_id is None or criminal_id is None or faction_id is None:
            return rejected("invalid reporter, criminal, or faction id")
        if not ctx.world.has_entity(criminal_id) or not ctx.world.has_entity(faction_id):
            return rejected("criminal or faction does not exist")
        reporter = ctx.entity(reporter_id)
        if criminal_id not in reachable_ids(ctx.world, reporter):
            return rejected("criminal is not reachable")
        faction = ctx.entity(faction_id)
        if not faction.has_component(FactionComponent):
            return rejected("target is not a faction")
        bounty = int(command.payload.get("bounty", 5))
        if bounty <= 0:
            return rejected("bounty must be positive")
        criminal = ctx.entity(criminal_id)
        wanted = (
            dict(criminal.get_component(WantedComponent).amounts)
            if criminal.has_component(WantedComponent)
            else {}
        )
        wanted[str(faction_id)] = wanted.get(str(faction_id), 0) + bounty
        replace_component(criminal, WantedComponent(amounts=wanted))
        return ok(
            CrimeReportedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(reporter_id),
                    room_id=_room_id(ctx.world, reporter_id),
                    target_ids=(str(criminal_id), str(faction_id)),
                    criminal_id=str(criminal_id),
                    faction_id=str(faction_id),
                    reporter_id=str(reporter_id),
                    bounty=bounty,
                )
            )
        )


class PickLockHandler:
    command_type = "pick-lock"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        lock_id = parse_entity_id(command.payload.get("lock_id"))
        if character_id is None or lock_id is None:
            return rejected("invalid character or lock id")
        if not ctx.world.has_entity(lock_id):
            return rejected("lock does not exist")
        character = ctx.entity(character_id)
        if lock_id not in reachable_ids(ctx.world, character):
            return rejected("lock is not reachable")
        locked = ctx.entity(lock_id)
        if not locked.has_component(LockDifficultyComponent):
            return rejected("target is not locked")
        difficulty = locked.get_component(LockDifficultyComponent)
        if not difficulty.locked:
            return rejected("lock is already open")
        if _skill_level(character, "lockpicking") < difficulty.difficulty:
            return rejected("lockpicking skill too low")

        replace_component(locked, replace(difficulty, locked=False))
        events: list[DomainEvent] = [
            LockPickedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(lock_id),),
                    lock_id=str(lock_id),
                    difficulty=difficulty.difficulty,
                )
            )
        ]
        events.extend(
            _add_skill_xp(
                ctx,
                character,
                skill="lockpicking",
                amount=float(difficulty.difficulty),
                actor_id=str(character_id),
                target_ids=(str(lock_id),),
            )
        )
        return ok(*events)


class ReadLoreBookHandler:
    command_type = "read-lore-book"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        book_id = parse_entity_id(command.payload.get("book_id"))
        if character_id is None or book_id is None:
            return rejected("invalid character or book id")
        if book_id not in reachable_ids(ctx.world, ctx.entity(character_id)):
            return rejected("book is not reachable")
        book = ctx.entity(book_id)
        if not book.has_component(LoreBookComponent):
            return rejected("target is not a lore book")

        component = book.get_component(LoreBookComponent)
        read_by = set(component.read_by)
        first_read = str(character_id) not in read_by
        skill_name = component.skill_name.strip().lower()
        skill_xp_awarded = component.skill_xp if first_read and skill_name else 0.0
        if first_read:
            replace_component(
                book,
                replace(component, read_by=tuple(sorted((*component.read_by, str(character_id))))),
            )

        events: list[DomainEvent] = [
            LoreBookReadEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(book_id),),
                    book_id=str(book_id),
                    title=component.title,
                    skill_name=skill_name,
                    skill_xp_awarded=skill_xp_awarded,
                )
            )
        ]
        if skill_xp_awarded > 0:
            events.extend(
                _add_skill_xp(
                    ctx,
                    ctx.entity(character_id),
                    skill=skill_name,
                    amount=skill_xp_awarded,
                    actor_id=str(character_id),
                    target_ids=(str(book_id),),
                )
            )
        return ok(*events)


class LearnSpellHandler:
    command_type = "learn-spell"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        spell_id = parse_entity_id(command.payload.get("spell_id"))
        if character_id is None or spell_id is None:
            return rejected("invalid character or spell id")
        if not ctx.world.has_entity(spell_id):
            return rejected("spell does not exist")
        character = ctx.entity(character_id)
        if spell_id not in reachable_ids(ctx.world, character):
            return rejected("spell is not reachable")
        spell_entity = ctx.entity(spell_id)
        if not spell_entity.has_component(SpellComponent):
            return rejected("target is not a spell")
        spell = spell_entity.get_component(SpellComponent)
        if character.has_relationship(KnowsSpell, spell_id):
            return rejected("spell already learned")
        if spell.skill_name and _skill_level(character, spell.skill_name) < spell.min_skill_level:
            return rejected("skill level too low for this spell")

        character.add_relationship(KnowsSpell(learned_at_epoch=ctx.epoch), spell_id)
        return ok(
            SpellLearnedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(spell_id),),
                    spell_id=str(spell_id),
                    spell_name=spell.name,
                )
            )
        )


class CastDragonSpellHandler:
    command_type = "cast-dragon-spell"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        spell_id = parse_entity_id(command.payload.get("spell_id"))
        if character_id is None or spell_id is None:
            return rejected("invalid character or spell id")
        if not ctx.world.has_entity(spell_id):
            return rejected("spell does not exist")
        character = ctx.entity(character_id)
        if not character.has_relationship(KnowsSpell, spell_id):
            return rejected("spell is not learned")
        spell_entity = ctx.entity(spell_id)
        if not spell_entity.has_component(SpellComponent):
            return rejected("target is not a spell")
        spell = spell_entity.get_component(SpellComponent)
        if spell_entity.has_component(SpellCooldownComponent):
            cooldown = spell_entity.get_component(SpellCooldownComponent)
            if cooldown.ready_at_epoch > ctx.epoch:
                return rejected("spell is on cooldown")
        magicka = (
            character.get_component(MagickaComponent)
            if character.has_component(MagickaComponent)
            else MagickaComponent()
        )
        if magicka.current < spell.magicka_cost:
            return rejected("not enough magicka")

        replace_component(character, replace(magicka, current=magicka.current - spell.magicka_cost))
        if spell_entity.has_component(SpellCooldownComponent):
            cooldown = spell_entity.get_component(SpellCooldownComponent)
            replace_component(
                spell_entity,
                replace(cooldown, ready_at_epoch=ctx.epoch + cooldown.cooldown_seconds),
            )
        events: list[DomainEvent] = [
            DragonSpellCastEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(spell_id),),
                    spell_id=str(spell_id),
                    spell_name=spell.name,
                    school=spell.school,
                    magicka_spent=spell.magicka_cost,
                )
            )
        ]
        if spell.skill_name:
            events.extend(
                _add_skill_xp(
                    ctx,
                    character,
                    skill=spell.skill_name,
                    amount=max(1.0, float(spell.magicka_cost)),
                    actor_id=str(character_id),
                    target_ids=(str(spell_id),),
                )
            )
        return ok(*events)


class BrewPotionHandler:
    command_type = "brew-potion"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        recipe_id = parse_entity_id(command.payload.get("recipe_id"))
        if character_id is None or recipe_id is None:
            return rejected("invalid character or recipe id")
        if not ctx.world.has_entity(recipe_id):
            return rejected("recipe does not exist")
        character = ctx.entity(character_id)
        if recipe_id not in reachable_ids(ctx.world, character):
            return rejected("recipe is not reachable")
        recipe_entity = ctx.entity(recipe_id)
        if not recipe_entity.has_component(PotionRecipeComponent):
            return rejected("target is not a potion recipe")
        recipe = recipe_entity.get_component(PotionRecipeComponent)
        if (
            recipe.skill_name
            and _skill_level(character, recipe.skill_name) < recipe.min_skill_level
        ):
            return rejected("skill level too low for this recipe")
        for raw_id in recipe.ingredient_ids:
            ingredient_id = parse_entity_id(raw_id)
            if (
                ingredient_id is None
                or not ctx.world.has_entity(ingredient_id)
                or container_of(ctx.world.get_entity(ingredient_id)) != character_id
            ):
                return rejected("required ingredient is not carried")

        for raw_id in recipe.ingredient_ids:
            ingredient_id = parse_entity_id(raw_id)
            if ingredient_id is not None:
                character.remove_relationship(Contains, ingredient_id)
        potion = spawn_entity(
            ctx.world,
            [
                IdentityComponent(name=recipe.potion_name, kind="potion"),
                PortableComponent(),
                PotionComponent(name=recipe.potion_name, effect=recipe.effect),
            ],
        )
        character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), potion.id)
        events: list[DomainEvent] = [
            PotionBrewedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(recipe_id), str(potion.id)),
                    recipe_id=str(recipe_id),
                    potion_id=str(potion.id),
                    potion_name=recipe.potion_name,
                )
            )
        ]
        if recipe.skill_name:
            events.extend(
                _add_skill_xp(
                    ctx,
                    character,
                    skill=recipe.skill_name,
                    amount=2.0,
                    actor_id=str(character_id),
                    target_ids=(str(recipe_id),),
                )
            )
        return ok(*events)


class UseArtifactHandler:
    command_type = "use-artifact"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        artifact_id = parse_entity_id(command.payload.get("artifact_id"))
        if character_id is None or artifact_id is None:
            return rejected("invalid character or artifact id")
        if not ctx.world.has_entity(artifact_id):
            return rejected("artifact does not exist")
        character = ctx.entity(character_id)
        if artifact_id not in reachable_ids(ctx.world, character):
            return rejected("artifact is not reachable")
        artifact_entity = ctx.entity(artifact_id)
        if not artifact_entity.has_component(ArtifactComponent):
            return rejected("target is not an artifact")
        artifact = artifact_entity.get_component(ArtifactComponent)
        if artifact.charges <= 0:
            return rejected("artifact has no charges")
        identified_by = tuple(sorted((*artifact.identified_by, str(character_id))))
        updated = replace(artifact, charges=artifact.charges - 1, identified_by=identified_by)
        replace_component(artifact_entity, updated)
        return ok(
            ArtifactUsedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(artifact_id),),
                    artifact_id=str(artifact_id),
                    artifact_name=artifact.name,
                    remaining_charges=updated.charges,
                )
            )
        )


class RecoverMagickaHandler:
    command_type = "recover-magicka"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")
        character = ctx.entity(character_id)
        magicka = (
            character.get_component(MagickaComponent)
            if character.has_component(MagickaComponent)
            else MagickaComponent()
        )
        amount = int(command.payload.get("amount", magicka.regen_per_hour))
        if amount <= 0:
            return rejected("recovery amount must be positive")
        updated = replace(
            magicka,
            current=min(magicka.maximum, magicka.current + amount),
            last_updated_epoch=ctx.epoch,
        )
        replace_component(character, updated)
        return ok(
            MagickaRecoveredEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(character_id),),
                    character_id=str(character_id),
                    current=updated.current,
                    maximum=updated.maximum,
                )
            )
        )


class IdentifyArtifactHandler:
    command_type = "identify-artifact"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        artifact_id = parse_entity_id(command.payload.get("artifact_id"))
        if character_id is None or artifact_id is None:
            return rejected("invalid character or artifact id")
        if not ctx.world.has_entity(artifact_id):
            return rejected("artifact does not exist")
        character = ctx.entity(character_id)
        if artifact_id not in reachable_ids(ctx.world, character):
            return rejected("artifact is not reachable")
        artifact_entity = ctx.entity(artifact_id)
        if not artifact_entity.has_component(ArtifactComponent):
            return rejected("target is not an artifact")
        artifact = artifact_entity.get_component(ArtifactComponent)
        if str(character_id) in artifact.identified_by:
            return rejected("artifact already identified")
        updated = replace(
            artifact,
            identified_by=tuple(sorted((*artifact.identified_by, str(character_id)))),
        )
        replace_component(artifact_entity, updated)
        return ok(
            ArtifactIdentifiedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(artifact_id),),
                    artifact_id=str(artifact_id),
                    artifact_name=artifact.name,
                )
            )
        )


class AppeaseAncientBeastHandler:
    command_type = "appease-ancient-beast"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        beast_id = parse_entity_id(command.payload.get("beast_id"))
        if character_id is None or beast_id is None:
            return rejected("invalid character or beast id")
        if not ctx.world.has_entity(beast_id):
            return rejected("ancient beast does not exist")
        character = ctx.entity(character_id)
        if beast_id not in reachable_ids(ctx.world, character):
            return rejected("ancient beast is not reachable")
        beast_entity = ctx.entity(beast_id)
        if not beast_entity.has_component(AncientBeastComponent):
            return rejected("target is not an ancient beast")
        beast = beast_entity.get_component(AncientBeastComponent)
        method = str(command.payload.get("method", "parley")).strip() or "parley"
        return ok(
            AncientBeastAppeasedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(beast_id),),
                    beast_id=str(beast_id),
                    beast_name=beast.name,
                    method=method,
                )
            )
        )


class InscribeVoicePhraseHandler:
    command_type = "inscribe-voice-phrase"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id = parse_entity_id(command.character_id)
        target_id = parse_entity_id(command.payload.get("target_id"))
        word_id = parse_entity_id(command.payload.get("word_id"))
        phrase = str(command.payload.get("phrase", "")).strip()
        if character_id is None or target_id is None or word_id is None:
            return rejected("invalid character, target, or word id")
        if not phrase:
            return rejected("nothing to inscribe")
        if not ctx.world.has_entity(target_id):
            return rejected("target does not exist")
        if not ctx.world.has_entity(word_id):
            return rejected("word does not exist")
        character = ctx.entity(character_id)
        if target_id not in reachable_ids(ctx.world, character):
            return rejected("target is not reachable")
        target = ctx.entity(target_id)
        writable = (
            target.get_component(WritableComponent)
            if target.has_component(WritableComponent)
            else None
        )
        carvable = (
            target.get_component(CarvableComponent)
            if target.has_component(CarvableComponent)
            else None
        )
        if writable is None and carvable is None:
            return rejected("target is not writable or carvable")
        remaining = writable.remaining_space if writable is not None else carvable.remaining_space
        if remaining is not None and len(phrase) > remaining:
            return rejected("not enough room to inscribe that")
        word = ctx.entity(word_id)
        if not word.has_component(WordOfPowerComponent):
            return rejected("target word is not a word of power")

        existing = (
            target.get_component(ReadableComponent)
            if target.has_component(ReadableComponent)
            else ReadableComponent()
        )
        new_text = phrase if not existing.text else f"{existing.text}\n{phrase}"
        replace_component(target, replace(existing, text=new_text))
        if writable is not None and writable.remaining_space is not None:
            replace_component(
                target,
                replace(writable, remaining_space=writable.remaining_space - len(phrase)),
            )
        if carvable is not None and carvable.remaining_space is not None:
            replace_component(
                target,
                replace(carvable, remaining_space=carvable.remaining_space - len(phrase)),
            )
        replace_component(
            target,
            VoiceInscriptionComponent(word_id=str(word_id), phrase=phrase),
        )
        return ok(
            VoicePhraseInscribedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.ROOM,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target_id), str(word_id)),
                    target_id=str(target_id),
                    word_id=str(word_id),
                    phrase=phrase,
                )
            )
        )


class StudyVoiceInscriptionHandler:
    command_type = "study-voice-inscription"

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
        if not target.has_component(VoiceInscriptionComponent):
            return rejected("target has no voice inscription")
        inscription = target.get_component(VoiceInscriptionComponent)
        word_id = parse_entity_id(inscription.word_id)
        if word_id is None or not ctx.world.has_entity(word_id):
            return rejected("voice inscription has no valid word")
        if str(character_id) in inscription.studied_by:
            return rejected("voice inscription already studied")

        replace_component(
            target,
            replace(
                inscription,
                studied_by=tuple(sorted((*inscription.studied_by, str(character_id)))),
            ),
        )
        if not character.has_relationship(KnowsWord, word_id):
            character.add_relationship(KnowsWord(learned_at_epoch=ctx.epoch), word_id)
        return ok(
            VoiceInscriptionStudiedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                    room_id=_room_id(ctx.world, character_id),
                    target_ids=(str(target_id), str(word_id)),
                    target_id=str(target_id),
                    word_id=str(word_id),
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
        if component.status == "declined":
            lines.append(f"Declined quest: {component.title}.")

    for stage_entity in world.query().with_all([QuestStageComponent]).execute_entities():
        stage = stage_entity.get_component(QuestStageComponent)
        if str(character.id) in stage.tracked_by:
            branch = f", branch {stage.branch}" if stage.branch else ""
            lines.append(f"Tracked quest stage {stage.stage} for {stage.quest_id}{branch}.")

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
    for _spell_edge, spell_id in character.get_relationships(KnowsSpell):
        if not world.has_entity(spell_id):
            continue
        spell = world.get_entity(spell_id)
        if spell.has_component(SpellComponent):
            lines.append(f"Spell learned: {spell.get_component(SpellComponent).name}.")
    if character.has_component(MagickaComponent):
        magicka = character.get_component(MagickaComponent)
        lines.append(f"Magicka: {magicka.current}/{magicka.maximum}.")
    if character.has_component(SurrenderComponent):
        surrender = character.get_component(SurrenderComponent)
        target = surrender.surrendered_to or "no one"
        lines.append(f"Surrendered to {target}.")
    if character.has_component(JailComponent):
        sentence = character.get_component(JailComponent)
        lines.append(f"Serving jail time for {sentence.faction_id} until {sentence.release_epoch}.")

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
        if entity.has_component(MapMarkerComponent):
            marker = entity.get_component(MapMarkerComponent)
            if str(character.id) in marker.marked_by:
                lines.append(f"Map marker: {marker.label} ({marker.marker_type}).")
        if entity.has_component(EncounterZoneComponent):
            zone = entity.get_component(EncounterZoneComponent)
            if zone.active:
                lines.append(
                    f"Encounter zone nearby: {zone.zone_type} (danger {zone.danger_rating})."
                )
        if entity.has_component(LoreBookComponent):
            book = entity.get_component(LoreBookComponent)
            if str(character.id) not in book.read_by:
                if book.skill_name:
                    lines.append(f"Unread skill book nearby: {book.title} ({book.skill_name}).")
                else:
                    lines.append(f"Unread lore book nearby: {book.title}.")
        if entity.has_component(LockDifficultyComponent):
            lock = entity.get_component(LockDifficultyComponent)
            if lock.locked:
                lines.append(
                    f"Locked target nearby: {_name(entity)} (difficulty {lock.difficulty})."
                )
        if entity.has_component(SpellComponent) and not character.has_relationship(
            KnowsSpell, entity_id
        ):
            lines.append(f"Learnable spell nearby: {entity.get_component(SpellComponent).name}.")
        if entity.has_component(PotionRecipeComponent):
            lines.append(
                f"Potion recipe nearby: {entity.get_component(PotionRecipeComponent).name}."
            )
        if entity.has_component(ArtifactComponent):
            artifact = entity.get_component(ArtifactComponent)
            state = "identified" if str(character.id) in artifact.identified_by else "unidentified"
            lines.append(f"Artifact nearby: {artifact.name} ({artifact.charges} charges, {state}).")
        if entity.has_component(SpellCooldownComponent):
            cooldown = entity.get_component(SpellCooldownComponent)
            if cooldown.ready_at_epoch > 0:
                lines.append(f"Spell cooldown nearby: ready at epoch {cooldown.ready_at_epoch}.")
        if entity.has_component(AncientBeastComponent):
            beast = entity.get_component(AncientBeastComponent)
            state = "soul absorbed" if beast.soul_absorbed else "active"
            lines.append(f"Ancient beast nearby: {beast.name} ({state}).")
        if entity.has_component(PersuasionComponent):
            persuasion = entity.get_component(PersuasionComponent)
            lines.append(f"{_name(entity)} disposition: {persuasion.disposition}.")
        if entity.has_component(VoiceInscriptionComponent):
            inscription = entity.get_component(VoiceInscriptionComponent)
            if str(character.id) not in inscription.studied_by:
                lines.append(f"Voice inscription nearby: {_name(entity)}.")
    return sorted(lines)


__all__ = [
    "AbsorbGreatSoulHandler",
    "AcceptQuestHandler",
    "AncientBeastComponent",
    "AncientBeastAppeasedEvent",
    "AppeaseAncientBeastHandler",
    "ArtifactComponent",
    "ArtifactIdentifiedEvent",
    "IdentifyArtifactHandler",
    "ArtifactUsedEvent",
    "BrewPotionHandler",
    "BribeGuardHandler",
    "WantedComponent",
    "BountyPaidEvent",
    "CastDragonSpellHandler",
    "ChangeFactionRankHandler",
    "ChooseQuestBranchHandler",
    "CompleteObjectiveHandler",
    "CrimeReportedEvent",
    "CrimeWitnessedEvent",
    "DeclineQuestHandler",
    "DiscoverLocationHandler",
    "DiscoveryComponent",
    "DragonSpellCastEvent",
    "EncounterTriggeredEvent",
    "EncounterZoneComponent",
    "FactionComponent",
    "FactionJoinedEvent",
    "FactionLeftEvent",
    "FactionRankChangedEvent",
    "FactionReputationComponent",
    "GuardBribedEvent",
    "GuardComponent",
    "GreatSoulAbsorbedEvent",
    "GreatSoulComponent",
    "HasPerk",
    "JoinFactionHandler",
    "JailComponent",
    "JailSentenceServedEvent",
    "KnowsWord",
    "KnowsSpell",
    "LearnWordOfPowerHandler",
    "LearnSpellHandler",
    "LeaveFactionHandler",
    "LockDifficultyComponent",
    "LockPickedEvent",
    "LoreBookComponent",
    "LoreBookReadEvent",
    "MagickaComponent",
    "MagickaRecoveredEvent",
    "LocationDiscoveredEvent",
    "MapMarkerAddedEvent",
    "MapMarkerComponent",
    "MarkMapHandler",
    "MemberOf",
    "PayBountyHandler",
    "PerkComponent",
    "PerkUnlockedEvent",
    "PersuadeHandler",
    "PersuasionAttemptedEvent",
    "PersuasionComponent",
    "PickLockHandler",
    "PointOfInterestComponent",
    "PotionBrewedEvent",
    "PotionComponent",
    "PotionRecipeComponent",
    "QuestAcceptedEvent",
    "QuestBranchChosenEvent",
    "QuestComponent",
    "QuestCompletedEvent",
    "QuestDeclinedEvent",
    "QuestObjectiveCompletedEvent",
    "QuestObjectiveComponent",
    "QuestRewardComponent",
    "QuestStageComponent",
    "QuestTrackedEvent",
    "ReadLoreBookHandler",
    "RecoverMagickaHandler",
    "ReportCrimeHandler",
    "SneakHandler",
    "SpellCooldownComponent",
    "SpeakWordOfPowerHandler",
    "SpellComponent",
    "SpellLearnedEvent",
    "SurrenderComponent",
    "SurrenderedEvent",
    "SurrenderHandler",
    "StealHandler",
    "StealthChangedEvent",
    "StealthComponent",
    "CarvableComponent",
    "InscribeVoicePhraseHandler",
    "StudyVoiceInscriptionHandler",
    "TheftCommittedEvent",
    "TrackQuestHandler",
    "TriggerEncounterHandler",
    "UnlockPerkHandler",
    "UseArtifactHandler",
    "WordOfPowerComponent",
    "WordOfPowerLearnedEvent",
    "WordOfPowerSpokenEvent",
    "VoiceInscriptionComponent",
    "VoiceInscriptionStudiedEvent",
    "VoicePhraseInscribedEvent",
    "dragonsim_fragments",
]
