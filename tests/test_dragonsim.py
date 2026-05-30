"""Tests for dragon-sim discovery, quests, and factions."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CommandCost,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.mechanics.dragonsim import (
    AcceptQuestHandler,
    CompleteObjectiveHandler,
    DiscoverLocationHandler,
    DiscoveryComponent,
    FactionComponent,
    FactionJoinedEvent,
    FactionLeftEvent,
    JoinFactionHandler,
    LeaveFactionHandler,
    LocationDiscoveredEvent,
    MemberOf,
    PointOfInterestComponent,
    QuestAcceptedEvent,
    QuestCompletedEvent,
    QuestComponent,
    QuestObjectiveCompletedEvent,
    QuestObjectiveComponent,
    dragonsim_fragments,
)

HOUR = 60 * 60


def _install(actor):
    actor.register_handler(DiscoverLocationHandler())
    actor.register_handler(AcceptQuestHandler())
    actor.register_handler(CompleteObjectiveHandler())
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


async def test_accept_and_complete_quest_objective_completes_quest():
    scenario = build_scenario()
    _install(scenario.actor)
    quest, objective = _quest(scenario)
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
