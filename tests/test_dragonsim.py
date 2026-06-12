"""Tests for dragon-sim discovery, quests, and factions."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    DeadComponent,
    IdentityComponent,
    Lane,
    PortableComponent,
    build_submitted_command,
    container_of,
    spawn_entity,
)
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.core.handlers import HandlerContext
from bunnyland.mechanics.dragonsim import (
    AbsorbGreatSoulHandler,
    AcceptQuestHandler,
    AncientBeastComponent,
    BountyPaidEvent,
    CompleteObjectiveHandler,
    CrimeWitnessedEvent,
    DiscoverLocationHandler,
    DiscoveryComponent,
    FactionComponent,
    FactionJoinedEvent,
    FactionLeftEvent,
    GreatSoulAbsorbedEvent,
    GreatSoulComponent,
    HasPerk,
    JoinFactionHandler,
    KnowsWord,
    LearnWordOfPowerHandler,
    LeaveFactionHandler,
    LocationDiscoveredEvent,
    MemberOf,
    PayBountyHandler,
    PerkComponent,
    PerkUnlockedEvent,
    PointOfInterestComponent,
    QuestAcceptedEvent,
    QuestCompletedEvent,
    QuestComponent,
    QuestObjectiveCompletedEvent,
    QuestObjectiveComponent,
    QuestRewardComponent,
    SneakHandler,
    SpeakWordOfPowerHandler,
    StealHandler,
    StealthChangedEvent,
    StealthComponent,
    TheftCommittedEvent,
    UnlockPerkHandler,
    WantedComponent,
    WordOfPowerComponent,
    WordOfPowerLearnedEvent,
    WordOfPowerSpokenEvent,
    dragonsim_fragments,
)
from bunnyland.mechanics.lifesim import SkillSetComponent

HOUR = 60 * 60


def _install(actor):
    actor.register_handler(DiscoverLocationHandler())
    actor.register_handler(AcceptQuestHandler())
    actor.register_handler(CompleteObjectiveHandler())
    actor.register_handler(UnlockPerkHandler())
    actor.register_handler(AbsorbGreatSoulHandler())
    actor.register_handler(LearnWordOfPowerHandler())
    actor.register_handler(SpeakWordOfPowerHandler())
    actor.register_handler(JoinFactionHandler())
    actor.register_handler(LeaveFactionHandler())
    actor.register_handler(SneakHandler())
    actor.register_handler(StealHandler())
    actor.register_handler(PayBountyHandler())


def _cmd(scenario, command_type, **payload):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
    )


def _handler_cmd(scenario, command_type, *, character_id=None, **payload):
    return build_submitted_command(
        character_id=str(scenario.character) if character_id is None else character_id,
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload=payload,
    )


def _poi(scenario):
    poi = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="old watchtower", kind="location"),
            PointOfInterestComponent(location_type="ruin", region="north meadow"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), poi.id
    )
    return poi.id


def _quest(scenario):
    quest = spawn_entity(
        scenario.actor.world,
        [QuestComponent(quest_id="lost-ring", title="Find the Lost Ring")],
    )
    objective = spawn_entity(
        scenario.actor.world,
        [
            QuestObjectiveComponent(
                quest_id="lost-ring", description="Recover the ring from the watchtower"
            )
        ],
    )
    return quest.id, objective.id


def _quest_reward(scenario, quest_id="lost-ring"):
    item = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="silver carrot", kind="item"),
            PortableComponent(),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), item.id
    )
    reward = spawn_entity(
        scenario.actor.world,
        [
            QuestRewardComponent(
                quest_id=quest_id,
                description="A silver carrot",
                item_ids=(str(item.id),),
            )
        ],
    )
    return reward.id, item.id


def _faction(scenario):
    faction = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Moss Wardens", kind="faction"),
            FactionComponent(name="Moss Wardens", ideology="protect the burrow"),
        ],
    )
    return faction.id


async def test_discover_location_marks_poi_and_records_discovery():
    scenario = build_scenario()
    _install(scenario.actor)
    poi = _poi(scenario)
    discovered: list[LocationDiscoveredEvent] = []
    scenario.actor.bus.subscribe(LocationDiscoveredEvent, discovered.append)

    await scenario.actor.submit(_cmd(scenario, "discover-location", location_id=str(poi)))
    await scenario.actor.tick(HOUR)

    entity = scenario.actor.world.get_entity(poi)
    assert entity.get_component(PointOfInterestComponent).discovered is True
    assert str(scenario.character) in entity.get_component(DiscoveryComponent).discovered_by
    assert discovered[0].location_type == "ruin"


async def test_accept_and_complete_quest_objective_completes_quest_and_grants_reward():
    scenario = build_scenario()
    _install(scenario.actor)
    quest, objective = _quest(scenario)
    reward, item = _quest_reward(scenario)
    accepted: list[QuestAcceptedEvent] = []
    completed_objectives: list[QuestObjectiveCompletedEvent] = []
    completed_quests: list[QuestCompletedEvent] = []
    scenario.actor.bus.subscribe(QuestAcceptedEvent, accepted.append)
    scenario.actor.bus.subscribe(QuestObjectiveCompletedEvent, completed_objectives.append)
    scenario.actor.bus.subscribe(QuestCompletedEvent, completed_quests.append)

    await scenario.actor.submit(_cmd(scenario, "accept-quest", quest_id=str(quest)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "complete-objective", objective_id=str(objective))
    )
    await scenario.actor.tick(HOUR)

    quest_component = scenario.actor.world.get_entity(quest).get_component(QuestComponent)
    objective_component = scenario.actor.world.get_entity(objective).get_component(
        QuestObjectiveComponent
    )
    assert accepted[0].title == "Find the Lost Ring"
    assert objective_component.completed is True
    assert completed_objectives[0].objective_id == str(objective)
    assert quest_component.status == "completed"
    assert completed_quests[0].quest_key == "lost-ring"
    assert container_of(scenario.actor.world.get_entity(item)) == scenario.character
    reward_component = scenario.actor.world.get_entity(reward).get_component(
        QuestRewardComponent
    )
    assert reward_component.claimed is True
    assert reward_component.claimed_by == str(scenario.character)


async def test_complete_final_objective_rejects_missing_reward_item_without_completion():
    scenario = build_scenario()
    _install(scenario.actor)
    quest, objective = _quest(scenario)
    reward = spawn_entity(
        scenario.actor.world,
        [
            QuestRewardComponent(
                quest_id="lost-ring",
                description="A vanished prize",
                item_ids=("missing_999",),
            )
        ],
    ).id
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "accept-quest", quest_id=str(quest)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "complete-objective", objective_id=str(objective))
    )
    await scenario.actor.tick(HOUR)

    quest_component = scenario.actor.world.get_entity(quest).get_component(QuestComponent)
    objective_component = scenario.actor.world.get_entity(objective).get_component(
        QuestObjectiveComponent
    )
    reward_component = scenario.actor.world.get_entity(reward).get_component(
        QuestRewardComponent
    )
    assert quest_component.status == "active"
    assert objective_component.completed is False
    assert reward_component.claimed is False
    assert any(event.reason == "quest reward item does not exist" for event in rejects)


def test_dragonsim_handlers_reject_invalid_targets_and_states_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    room = scenario.actor.world.get_entity(scenario.room_a)
    wrong_kind = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="plain stone", kind="prop")],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), wrong_kind.id)
    distant_poi = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far watchtower", kind="location"),
            PointOfInterestComponent(location_type="ruin", region="north meadow"),
        ],
    )
    discovered_poi = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="known watchtower", kind="location"),
            PointOfInterestComponent(location_type="ruin", region="north meadow"),
            DiscoveryComponent(discovered_by=(str(scenario.character),)),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), discovered_poi.id)
    spawn_entity(
        scenario.actor.world,
        [QuestComponent(quest_id="guard-duty", title="Guard Duty")],
    )
    active_quest = spawn_entity(
        scenario.actor.world,
        [
            QuestComponent(
                quest_id="active-duty",
                title="Active Duty",
                status="active",
                accepted_by=(str(scenario.character),),
            )
        ],
    )
    completed_quest = spawn_entity(
        scenario.actor.world,
        [
            QuestComponent(
                quest_id="done-duty",
                title="Done Duty",
                status="completed",
            )
        ],
    )
    objective = spawn_entity(
        scenario.actor.world,
        [QuestObjectiveComponent(quest_id="guard-duty", description="Stand watch")],
    )
    completed_objective = spawn_entity(
        scenario.actor.world,
        [
            QuestObjectiveComponent(
                quest_id="guard-duty",
                description="Already stood watch",
                completed=True,
            )
        ],
    )
    orphan_objective = spawn_entity(
        scenario.actor.world,
        [QuestObjectiveComponent(quest_id="missing-quest", description="No quest")],
    )
    faction = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Moss Wardens", kind="faction"),
            FactionComponent(name="Moss Wardens", ideology="protect the burrow"),
        ],
    )

    cases = [
        (
            DiscoverLocationHandler(),
            _handler_cmd(
                scenario,
                "discover-location",
                character_id="not-an-id",
                location_id=str(distant_poi.id),
            ),
            "invalid character or location id",
        ),
        (
            DiscoverLocationHandler(),
            _handler_cmd(scenario, "discover-location", location_id="entity_999"),
            "location does not exist",
        ),
        (
            DiscoverLocationHandler(),
            _handler_cmd(
                scenario,
                "discover-location",
                location_id=str(distant_poi.id),
            ),
            "location is not reachable",
        ),
        (
            DiscoverLocationHandler(),
            _handler_cmd(scenario, "discover-location", location_id=str(wrong_kind.id)),
            "target is not discoverable",
        ),
        (
            DiscoverLocationHandler(),
            _handler_cmd(
                scenario,
                "discover-location",
                location_id=str(discovered_poi.id),
            ),
            "location already discovered",
        ),
        (
            AcceptQuestHandler(),
            _handler_cmd(scenario, "accept-quest", character_id="not-an-id", quest_id="x"),
            "invalid character or quest id",
        ),
        (
            AcceptQuestHandler(),
            _handler_cmd(scenario, "accept-quest", quest_id="missing"),
            "quest does not exist",
        ),
        (
            AcceptQuestHandler(),
            _handler_cmd(scenario, "accept-quest", quest_id=str(completed_quest.id)),
            "quest is already complete",
        ),
        (
            AcceptQuestHandler(),
            _handler_cmd(scenario, "accept-quest", quest_id=str(active_quest.id)),
            "quest already accepted",
        ),
        (
            CompleteObjectiveHandler(),
            _handler_cmd(
                scenario,
                "complete-objective",
                character_id="not-an-id",
                objective_id=str(objective.id),
            ),
            "invalid character or objective id",
        ),
        (
            CompleteObjectiveHandler(),
            _handler_cmd(scenario, "complete-objective", objective_id="missing"),
            "objective does not exist",
        ),
        (
            CompleteObjectiveHandler(),
            _handler_cmd(
                scenario,
                "complete-objective",
                objective_id=str(completed_objective.id),
            ),
            "objective is already complete",
        ),
        (
            CompleteObjectiveHandler(),
            _handler_cmd(
                scenario,
                "complete-objective",
                objective_id=str(orphan_objective.id),
            ),
            "quest does not exist",
        ),
        (
            CompleteObjectiveHandler(),
            _handler_cmd(scenario, "complete-objective", objective_id=str(objective.id)),
            "quest is not accepted",
        ),
        (
            JoinFactionHandler(),
            _handler_cmd(
                scenario,
                "join-faction",
                character_id="not-an-id",
                faction_id=str(faction.id),
            ),
            "invalid character or faction id",
        ),
        (
            JoinFactionHandler(),
            _handler_cmd(scenario, "join-faction", faction_id="entity_999"),
            "faction does not exist",
        ),
        (
            JoinFactionHandler(),
            _handler_cmd(scenario, "join-faction", faction_id=str(wrong_kind.id)),
            "target is not a faction",
        ),
        (
            LeaveFactionHandler(),
            _handler_cmd(
                scenario,
                "leave-faction",
                character_id="not-an-id",
                faction_id=str(faction.id),
            ),
            "invalid character or faction id",
        ),
        (
            LeaveFactionHandler(),
            _handler_cmd(scenario, "leave-faction", faction_id="entity_999"),
            "faction does not exist",
        ),
        (
            LeaveFactionHandler(),
            _handler_cmd(scenario, "leave-faction", faction_id=str(wrong_kind.id)),
            "target is not a faction",
        ),
        (
            LeaveFactionHandler(),
            _handler_cmd(scenario, "leave-faction", faction_id=str(faction.id)),
            "not a faction member",
        ),
    ]

    for handler, command, reason in cases:
        result = handler.execute(ctx, command)
        assert result.ok is False
        assert result.reason == reason

    character = scenario.actor.world.get_entity(scenario.character)
    character.add_relationship(MemberOf(rank="member", since_epoch=0), faction.id)
    result = JoinFactionHandler().execute(
        ctx,
        _handler_cmd(scenario, "join-faction", faction_id=str(faction.id)),
    )
    assert result.ok is False
    assert result.reason == "already a faction member"


async def test_complete_objective_rejects_unaccepted_quest():
    scenario = build_scenario()
    _install(scenario.actor)
    _quest_id, objective = _quest(scenario)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(
        _cmd(scenario, "complete-objective", objective_id=str(objective))
    )
    await scenario.actor.tick(HOUR)

    assert any(event.reason == "quest is not accepted" for event in rejects)


async def test_join_and_leave_faction_updates_membership_edge():
    scenario = build_scenario()
    _install(scenario.actor)
    faction = _faction(scenario)
    joined: list[FactionJoinedEvent] = []
    left: list[FactionLeftEvent] = []
    scenario.actor.bus.subscribe(FactionJoinedEvent, joined.append)
    scenario.actor.bus.subscribe(FactionLeftEvent, left.append)

    await scenario.actor.submit(
        _cmd(scenario, "join-faction", faction_id=str(faction), rank="scout")
    )
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.has_relationship(MemberOf, faction)
    assert joined[0].rank == "scout"

    await scenario.actor.submit(_cmd(scenario, "leave-faction", faction_id=str(faction)))
    await scenario.actor.tick(HOUR)

    assert not character.has_relationship(MemberOf, faction)
    assert left[0].faction_name == "Moss Wardens"


def test_dragonsim_fragments_show_quests_factions_and_nearby_locations():
    scenario = build_scenario()
    poi = _poi(scenario)
    faction = _faction(scenario)
    quest, _objective = _quest(scenario)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_relationship(MemberOf(rank="scout", since_epoch=0), faction)
    quest_entity = scenario.actor.world.get_entity(quest)
    quest_entity.remove_component(QuestComponent)
    quest_entity.add_component(
        QuestComponent(
            quest_id="lost-ring",
            title="Find the Lost Ring",
            status="active",
            accepted_by=(str(scenario.character),),
        )
    )

    fragments = dragonsim_fragments(scenario.actor.world, character)

    assert scenario.actor.world.get_entity(poi).has_component(PointOfInterestComponent)
    assert any("Moss Wardens" in line for line in fragments)
    assert any("Active quest: Find the Lost Ring" in line for line in fragments)
    assert any("old watchtower" in line for line in fragments)


def _set_skill_level(scenario, skill_name, level):
    """Set a lifesim skill level directly (lifesim owns skill-by-use progression)."""
    character = scenario.actor.world.get_entity(scenario.character)
    state = (
        character.get_component(SkillSetComponent)
        if character.has_component(SkillSetComponent)
        else SkillSetComponent()
    )
    levels = dict(state.levels)
    levels[skill_name] = level
    if character.has_component(SkillSetComponent):
        character.remove_component(SkillSetComponent)
    character.add_component(SkillSetComponent(levels=levels, xp=dict(state.xp)))


async def test_unlock_perk_gates_on_lifesim_skill_level():
    scenario = build_scenario()
    _install(scenario.actor)
    perk = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Power Attack", kind="perk"),
            PerkComponent(name="Power Attack", skill_name="blade", min_level=2),
        ],
    )
    rejects: list[CommandRejectedEvent] = []
    unlocked: list[PerkUnlockedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)
    scenario.actor.bus.subscribe(PerkUnlockedEvent, unlocked.append)

    # Skill not yet high enough.
    _set_skill_level(scenario, "blade", 1)
    await scenario.actor.submit(_cmd(scenario, "unlock-perk", perk_id=str(perk.id)))
    await scenario.actor.tick(HOUR)
    assert any("skill level too low" in event.reason for event in rejects)
    assert unlocked == []

    # Reach the gating level and unlock.
    _set_skill_level(scenario, "blade", 2)
    await scenario.actor.submit(_cmd(scenario, "unlock-perk", perk_id=str(perk.id)))
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.has_relationship(HasPerk, perk.id)
    assert unlocked[0].perk_name == "Power Attack"
    fragments = dragonsim_fragments(scenario.actor.world, character)
    assert any("Perk unlocked: Power Attack" in line for line in fragments)


def test_unlock_perk_rejects_invalid_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    wrong_kind = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="not a perk", kind="prop")],
    )
    perk = spawn_entity(
        scenario.actor.world,
        [PerkComponent(name="Power Attack", skill_name="blade", min_level=2)],
    )

    unlock = UnlockPerkHandler()
    rejections = {
        unlock.execute(
            ctx, _handler_cmd(scenario, "unlock-perk", character_id="not-an-id", perk_id="x")
        ).reason,
        unlock.execute(ctx, _handler_cmd(scenario, "unlock-perk", perk_id="entity_999")).reason,
        unlock.execute(
            ctx, _handler_cmd(scenario, "unlock-perk", perk_id=str(wrong_kind.id))
        ).reason,
        # No SkillSetComponent at all -> treated as level 0.
        unlock.execute(
            ctx, _handler_cmd(scenario, "unlock-perk", perk_id=str(perk.id))
        ).reason,
    }
    assert "invalid character or perk id" in rejections
    assert "perk does not exist" in rejections
    assert "target is not a perk" in rejections
    assert "skill level too low for this perk" in rejections

    # Once the gating skill is high enough, unlocking succeeds; a second unlock is rejected.
    _set_skill_level(scenario, "blade", 2)
    assert unlock.execute(
        ctx, _handler_cmd(scenario, "unlock-perk", perk_id=str(perk.id))
    ).ok
    assert (
        unlock.execute(
            ctx, _handler_cmd(scenario, "unlock-perk", perk_id=str(perk.id))
        ).reason
        == "perk already unlocked"
    )


def _dead_beast(scenario, name="Ancient Wyrm"):
    beast = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=name, kind="character"),
            AncientBeastComponent(name=name),
            DeadComponent(died_at_epoch=0, cause="slain"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), beast.id
    )
    return beast.id


def _word(scenario, *, name="Unrelenting Force", min_souls=1, skill_name="", min_skill_level=0):
    return spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=name, kind="word"),
            WordOfPowerComponent(
                name=name,
                min_souls=min_souls,
                skill_name=skill_name,
                min_skill_level=min_skill_level,
            ),
        ],
    ).id


async def test_absorb_great_soul_then_learn_and_speak_word():
    scenario = build_scenario()
    _install(scenario.actor)
    beast = _dead_beast(scenario)
    word = _word(scenario, skill_name="voice", min_skill_level=2)
    _set_skill_level(scenario, "voice", 2)
    absorbed: list[GreatSoulAbsorbedEvent] = []
    learned: list[WordOfPowerLearnedEvent] = []
    spoken: list[WordOfPowerSpokenEvent] = []
    scenario.actor.bus.subscribe(GreatSoulAbsorbedEvent, absorbed.append)
    scenario.actor.bus.subscribe(WordOfPowerLearnedEvent, learned.append)
    scenario.actor.bus.subscribe(WordOfPowerSpokenEvent, spoken.append)

    await scenario.actor.submit(_cmd(scenario, "absorb-great-soul", beast_id=str(beast)))
    await scenario.actor.tick(HOUR)
    assert absorbed[0].souls == 1
    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(GreatSoulComponent).souls == 1
    assert scenario.actor.world.get_entity(beast).get_component(AncientBeastComponent).soul_absorbed

    await scenario.actor.submit(_cmd(scenario, "learn-word-of-power", word_id=str(word)))
    await scenario.actor.tick(HOUR)
    assert character.has_relationship(KnowsWord, word)
    assert learned[0].word_name == "Unrelenting Force"

    await scenario.actor.submit(_cmd(scenario, "speak-word-of-power", word_id=str(word)))
    await scenario.actor.tick(HOUR)
    assert spoken[0].word_name == "Unrelenting Force"

    fragments = dragonsim_fragments(scenario.actor.world, character)
    assert any("Great souls absorbed: 1" in line for line in fragments)
    assert any("Word of power known: Unrelenting Force" in line for line in fragments)


def test_soul_and_word_handlers_reject_invalid_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    living_beast = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Live Wyrm", kind="character"),
            AncientBeastComponent(name="Live Wyrm"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), living_beast.id
    )
    not_a_beast = spawn_entity(scenario.actor.world, [IdentityComponent(name="stump", kind="prop")])
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), not_a_beast.id
    )
    word = _word(scenario, min_souls=2, skill_name="voice", min_skill_level=2)

    absorb = AbsorbGreatSoulHandler()
    learn = LearnWordOfPowerHandler()
    speak = SpeakWordOfPowerHandler()

    assert absorb.execute(
        ctx, _handler_cmd(scenario, "absorb-great-soul", character_id="x", beast_id="y")
    ).reason == "invalid character or beast id"
    assert absorb.execute(
        ctx, _handler_cmd(scenario, "absorb-great-soul", beast_id="entity_999")
    ).reason == "beast does not exist"
    assert absorb.execute(
        ctx, _handler_cmd(scenario, "absorb-great-soul", beast_id=str(not_a_beast.id))
    ).reason == "target is not an ancient beast"
    assert absorb.execute(
        ctx, _handler_cmd(scenario, "absorb-great-soul", beast_id=str(living_beast.id))
    ).reason == "the beast still lives"
    unreachable = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Distant Wyrm", kind="character"),
            AncientBeastComponent(name="Distant Wyrm"),
            DeadComponent(died_at_epoch=0, cause="slain"),
        ],
    )
    assert absorb.execute(
        ctx, _handler_cmd(scenario, "absorb-great-soul", beast_id=str(unreachable.id))
    ).reason == "beast is not reachable"

    # Word handler validation paths.
    assert learn.execute(
        ctx, _handler_cmd(scenario, "learn-word-of-power", character_id="x", word_id="y")
    ).reason == "invalid character or word id"
    assert learn.execute(
        ctx, _handler_cmd(scenario, "learn-word-of-power", word_id="entity_999")
    ).reason == "word does not exist"
    assert learn.execute(
        ctx, _handler_cmd(scenario, "learn-word-of-power", word_id=str(not_a_beast.id))
    ).reason == "target is not a word of power"
    assert speak.execute(
        ctx, _handler_cmd(scenario, "speak-word-of-power", character_id="x", word_id="y")
    ).reason == "invalid character or word id"
    assert speak.execute(
        ctx, _handler_cmd(scenario, "speak-word-of-power", word_id="entity_999")
    ).reason == "word does not exist"

    # Learning is gated on souls, then on skill level.
    assert speak.execute(
        ctx, _handler_cmd(scenario, "speak-word-of-power", word_id=str(word))
    ).reason == "you have not learned that word"
    assert learn.execute(
        ctx, _handler_cmd(scenario, "learn-word-of-power", word_id=str(word))
    ).reason == "not enough great souls to learn this word"

    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(GreatSoulComponent(souls=2))
    assert learn.execute(
        ctx, _handler_cmd(scenario, "learn-word-of-power", word_id=str(word))
    ).reason == "skill level too low for this word"

    _set_skill_level(scenario, "voice", 2)
    assert learn.execute(ctx, _handler_cmd(scenario, "learn-word-of-power", word_id=str(word))).ok
    assert learn.execute(
        ctx, _handler_cmd(scenario, "learn-word-of-power", word_id=str(word))
    ).reason == "word already learned"

    # Re-absorbing a claimed soul is rejected.
    dead = _dead_beast(scenario, name="Claimed Wyrm")
    assert absorb.execute(ctx, _handler_cmd(scenario, "absorb-great-soul", beast_id=str(dead))).ok
    assert absorb.execute(
        ctx, _handler_cmd(scenario, "absorb-great-soul", beast_id=str(dead))
    ).reason == "its great soul is already claimed"


def _victim_with_item(scenario, *, faction_id=None, room=None, name="Mara"):
    world = scenario.actor.world
    room = room if room is not None else scenario.room_a
    victim = spawn_entity(
        world,
        [IdentityComponent(name=name, kind="character"), CharacterComponent(species="bunny")],
    )
    world.get_entity(room).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), victim.id
    )
    if faction_id is not None:
        victim.add_relationship(MemberOf(rank="member"), faction_id)
    item = spawn_entity(
        world,
        [IdentityComponent(name="ruby ring", kind="item"), PortableComponent(can_pick_up=True)],
    )
    victim.add_relationship(Contains(mode=ContainmentMode.INVENTORY), item.id)
    return victim.id, item.id


async def test_sneak_toggles_stealth_state():
    scenario = build_scenario()
    _install(scenario.actor)
    changes: list[StealthChangedEvent] = []
    scenario.actor.bus.subscribe(StealthChangedEvent, changes.append)

    await scenario.actor.submit(_cmd(scenario, "sneak"))
    await scenario.actor.tick(HOUR)
    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(StealthComponent).sneaking is True

    await scenario.actor.submit(_cmd(scenario, "sneak"))
    await scenario.actor.tick(HOUR)
    assert character.get_component(StealthComponent).sneaking is False
    assert [event.sneaking for event in changes] == [True, False]


async def test_witnessed_theft_takes_item_and_raises_faction_bounty():
    scenario = build_scenario()
    _install(scenario.actor)
    faction = _faction(scenario)
    victim, item = _victim_with_item(scenario, faction_id=faction)
    thefts: list[TheftCommittedEvent] = []
    crimes: list[CrimeWitnessedEvent] = []
    scenario.actor.bus.subscribe(TheftCommittedEvent, thefts.append)
    scenario.actor.bus.subscribe(CrimeWitnessedEvent, crimes.append)

    await scenario.actor.submit(
        _cmd(scenario, "steal", target_id=str(victim), item_id=str(item))
    )
    await scenario.actor.tick(HOUR)

    world = scenario.actor.world
    assert container_of(world.get_entity(item)) == scenario.character
    assert thefts and thefts[0].victim_id == str(victim)
    assert crimes and crimes[0].faction_id == str(faction)
    bounty = world.get_entity(scenario.character).get_component(WantedComponent)
    assert bounty.amounts[str(faction)] == 10


async def test_sneaking_thief_is_not_witnessed():
    scenario = build_scenario()
    _install(scenario.actor)
    faction = _faction(scenario)
    victim, item = _victim_with_item(scenario, faction_id=faction)
    crimes: list[CrimeWitnessedEvent] = []
    scenario.actor.bus.subscribe(CrimeWitnessedEvent, crimes.append)

    await scenario.actor.submit(_cmd(scenario, "sneak"))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "steal", target_id=str(victim), item_id=str(item))
    )
    await scenario.actor.tick(HOUR)

    world = scenario.actor.world
    assert container_of(world.get_entity(item)) == scenario.character
    assert not crimes
    assert not world.get_entity(scenario.character).has_component(WantedComponent)


async def test_pay_bounty_clears_a_faction_bounty():
    scenario = build_scenario()
    _install(scenario.actor)
    faction = _faction(scenario)
    scenario.actor.world.get_entity(scenario.character).add_component(
        WantedComponent(amounts={str(faction): 30})
    )
    paid: list[BountyPaidEvent] = []
    scenario.actor.bus.subscribe(BountyPaidEvent, paid.append)

    await scenario.actor.submit(_cmd(scenario, "pay-bounty", faction_id=str(faction)))
    await scenario.actor.tick(HOUR)

    bounty = scenario.actor.world.get_entity(scenario.character).get_component(WantedComponent)
    assert str(faction) not in bounty.amounts
    assert paid and paid[0].amount == 30


def test_crime_handlers_reject_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    faction = _faction(scenario)
    victim, item = _victim_with_item(scenario, faction_id=faction)
    stuck = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="anvil", kind="item"), PortableComponent(can_pick_up=False)],
    )
    scenario.actor.world.get_entity(victim).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), stuck.id
    )

    cases = [
        (StealHandler(), _handler_cmd(scenario, "steal", character_id="x"), "invalid thief"),
        (
            StealHandler(),
            _handler_cmd(scenario, "steal", target_id="ghost_1", item_id=str(item)),
            "does not exist",
        ),
        (
            StealHandler(),
            _handler_cmd(scenario, "steal", target_id=str(victim), item_id=str(stuck.id)),
            "cannot be taken",
        ),
        (
            PayBountyHandler(),
            _handler_cmd(scenario, "pay-bounty", faction_id="x"),
            "invalid character",
        ),
        (
            PayBountyHandler(),
            _handler_cmd(scenario, "pay-bounty", faction_id=str(faction)),
            "no bounties",
        ),
    ]
    for handler, command, expected in cases:
        result = handler.execute(ctx, command)
        assert not result.ok, expected
        assert expected in result.reason, (expected, result.reason)


def test_dragonsim_fragments_show_sneaking_and_bounty():
    scenario = build_scenario()
    _install(scenario.actor)
    faction = _faction(scenario)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(StealthComponent(sneaking=True))
    character.add_component(WantedComponent(amounts={str(faction): 25}))

    lines = dragonsim_fragments(scenario.actor.world, character)
    assert any("sneaking" in line for line in lines)
    assert any("Bounty of 25" in line and "Moss Wardens" in line for line in lines)


async def test_theft_without_faction_witnesses_raises_no_bounty():
    scenario = build_scenario()
    _install(scenario.actor)
    victim, item = _victim_with_item(scenario)  # victim belongs to no faction
    crimes: list[CrimeWitnessedEvent] = []
    scenario.actor.bus.subscribe(CrimeWitnessedEvent, crimes.append)

    await scenario.actor.submit(
        _cmd(scenario, "steal", target_id=str(victim), item_id=str(item))
    )
    await scenario.actor.tick(HOUR)

    world = scenario.actor.world
    assert container_of(world.get_entity(item)) == scenario.character
    assert not crimes
    assert not world.get_entity(scenario.character).has_component(WantedComponent)


def test_steal_and_sneak_reject_more_bad_state_directly():
    scenario = build_scenario()
    _install(scenario.actor)
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    faction = _faction(scenario)
    far_victim, far_item = _victim_with_item(scenario, room=scenario.room_b, name="Bryn")
    near_victim, _near_item = _victim_with_item(scenario, faction_id=faction)
    loose = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="loose coin", kind="item"), PortableComponent(can_pick_up=True)],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), loose.id
    )
    scenario.actor.world.get_entity(scenario.character).add_component(
        WantedComponent(amounts={str(faction): 10})
    )

    cases = [
        (SneakHandler(), _handler_cmd(scenario, "sneak", character_id="x"), "invalid character"),
        (
            StealHandler(),
            _handler_cmd(scenario, "steal", target_id=str(far_victim), item_id=str(far_item)),
            "not present",
        ),
        (
            StealHandler(),
            _handler_cmd(scenario, "steal", target_id=str(near_victim), item_id=str(loose.id)),
            "not carried",
        ),
        (
            PayBountyHandler(),
            _handler_cmd(scenario, "pay-bounty", faction_id="other_77"),
            "no bounty with that faction",
        ),
    ]
    for handler, command, expected in cases:
        result = handler.execute(ctx, command)
        assert not result.ok, expected
        assert expected in result.reason, (expected, result.reason)


def test_fragments_show_bounty_for_unknown_faction_key():
    scenario = build_scenario()
    _install(scenario.actor)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(WantedComponent(amounts={"lost_77": 5}))

    lines = dragonsim_fragments(scenario.actor.world, character)
    assert any("Bounty of 5 with lost_77" in line for line in lines)
