"""Tests for storyteller incident budgeting and resolution."""

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
    RoomComponent,
    SuspendedComponent,
    build_submitted_command,
    parse_entity_id,
    spawn_entity,
)
from bunnyland.mechanics.storyteller import (
    IncidentBudgetComponent,
    IncidentComponent,
    IncidentHistoryComponent,
    IncidentProposedEvent,
    IncidentResolvedEvent,
    IncidentStartedEvent,
    ResolveIncidentHandler,
    StorytellerComponent,
    StorytellerConsequence,
    ThreatPointsComponent,
    _target_room,
    install_storyteller,
    storyteller_fragments,
)

HOUR = 3600.0


def _install(actor):
    install_storyteller(actor)
    actor.register_handler(ResolveIncidentHandler())


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


def _storyteller(scenario, *, points=4.0, threat=0.0):
    components = [
        IdentityComponent(name="steady storyteller", kind="controller"),
        StorytellerComponent(interval_seconds=int(HOUR), next_incident_epoch=int(HOUR)),
        IncidentBudgetComponent(points=points, points_per_day=0.0),
    ]
    if threat:
        components.append(ThreatPointsComponent(points=threat))
    return spawn_entity(scenario.actor.world, components)


async def test_storyteller_budget_starts_resource_drop_and_resolves_incident():
    scenario = build_scenario()
    _install(scenario.actor)
    storyteller = _storyteller(scenario, points=4.0)
    proposed: list[IncidentProposedEvent] = []
    started: list[IncidentStartedEvent] = []
    resolved: list[IncidentResolvedEvent] = []
    scenario.actor.bus.subscribe(IncidentProposedEvent, proposed.append)
    scenario.actor.bus.subscribe(IncidentStartedEvent, started.append)
    scenario.actor.bus.subscribe(IncidentResolvedEvent, resolved.append)

    await scenario.actor.tick(HOUR)

    assert proposed[0].kind == "resource_drop"
    assert started[0].room_id_started == str(scenario.room_a)
    incident_id = proposed[0].incident_id
    incident = scenario.actor.world.get_entity(parse_entity_id(incident_id))
    assert incident.get_component(IncidentComponent).budget_spent == 2.0
    assert storyteller.get_component(IncidentBudgetComponent).points == 2.0
    assert storyteller.get_component(StorytellerComponent).next_incident_epoch == 2 * HOUR
    assert storyteller.get_component(IncidentHistoryComponent).incident_ids == (incident_id,)
    room = scenario.actor.world.get_entity(scenario.room_a)
    room_contents = [
        scenario.actor.world.get_entity(item_id)
        for _edge, item_id in room.get_relationships(Contains)
    ]
    assert any(
        entity.has_component(IdentityComponent)
        and entity.get_component(IdentityComponent).name == "supply bundle"
        for entity in room_contents
    )
    fragments = storyteller_fragments(
        scenario.actor.world, scenario.actor.world.get_entity(scenario.character)
    )
    assert any("resource drop" in line for line in fragments)

    await scenario.actor.submit(_cmd(scenario, "resolve-incident", incident_id=incident_id))
    await scenario.actor.tick(HOUR)

    assert incident.get_component(IncidentComponent).resolved_at_epoch == scenario.actor.epoch
    assert resolved[0].incident_id == incident_id


async def test_threat_points_select_hostile_encounter():
    scenario = build_scenario()
    _install(scenario.actor)
    _storyteller(scenario, points=4.0, threat=6.0)

    await scenario.actor.tick(HOUR)

    incident = next(
        entity
        for entity in scenario.actor.world.query().with_all([IncidentComponent]).execute_entities()
    )
    assert incident.get_component(IncidentComponent).kind == "hostile_encounter"


def test_storyteller_install_registers_consequence():
    scenario = build_scenario()
    install_storyteller(scenario.actor)
    assert any(
        isinstance(consequence, StorytellerConsequence)
        for consequence in scenario.actor._consequences
    )


def test_target_room_skips_inactive_characters_and_falls_back_to_rooms(scenario):
    world = scenario.actor.world
    active = world.get_entity(scenario.character)
    active.add_component(SuspendedComponent())

    dead = spawn_entity(
        world,
            [
                IdentityComponent(name="Gone", kind="character"),
                CharacterComponent(species="bunny"),
                DeadComponent(died_at_epoch=0, cause="test"),
            ],
        )
    suspended = spawn_entity(
        world,
        [
            IdentityComponent(name="Waiting", kind="character"),
            CharacterComponent(species="bunny"),
            SuspendedComponent(),
        ],
    )
    world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), dead.id
    )
    world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), suspended.id
    )

    assert _target_room(world).has_component(RoomComponent)

    bare_world = type(world)()
    room = spawn_entity(bare_world, [RoomComponent(title="Empty")])
    assert _target_room(bare_world) == room

    empty_world = type(world)()
    assert _target_room(empty_world) is None
