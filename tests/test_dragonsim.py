"""Tests for dragon-sim discovery, quests, and factions."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CommandCost,
    ContainmentMode,
    Contains,
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
    AcceptQuestHandler,
    CompleteObjectiveHandler,
    DiscoverLocationHandler,
    DiscoveryComponent,
    FactionComponent,
    FactionJoinedEvent,
    FactionLeftEvent,
    HasPerk,
    JoinFactionHandler,
    LeaveFactionHandler,
    LocationDiscoveredEvent,
    MemberOf,
    PerkComponent,
    PerkUnlockedEvent,
    PointOfInterestComponent,
    QuestAcceptedEvent,
    QuestCompletedEvent,
    QuestComponent,
    QuestObjectiveCompletedEvent,
    QuestObjectiveComponent,
    QuestRewardComponent,
    UnlockPerkHandler,
    dragonsim_fragments,
)
from bunnyland.mechanics.lifesim import SkillSetComponent

HOUR = 60 * 60


def _install(actor):
    actor.register_handler(DiscoverLocationHandler())
    actor.register_handler(AcceptQuestHandler())
    actor.register_handler(CompleteObjectiveHandler())
    actor.register_handler(UnlockPerkHandler())
    actor.register_handler(JoinFactionHandler())
    actor.register_handler(LeaveFactionHandler())


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
