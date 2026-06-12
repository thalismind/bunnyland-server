"""Tests for storyteller incident budgeting and resolution."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    AdminComponent,
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
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.mechanics import storyteller as story
from bunnyland.mechanics.colonysim import PrisonerComponent
from bunnyland.mechanics.daggersim import GeneratedQuestComponent, PacifiedComponent
from bunnyland.mechanics.dinosim import (
    ApexPredatorComponent,
    CompanionComponent,
    EnclosureComponent,
    GateComponent,
    KaijuComponent,
    SettlementDamageComponent,
    TamingComponent,
)
from bunnyland.mechanics.dragonsim import QuestComponent
from bunnyland.mechanics.storyteller import (
    IncidentAutoResolutionConsequence,
    IncidentBudgetComponent,
    IncidentComponent,
    IncidentGeneratedEvent,
    IncidentHistoryComponent,
    IncidentProposedEvent,
    IncidentResolvedEvent,
    IncidentSpawned,
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
    generated: list[IncidentGeneratedEvent] = []
    started: list[IncidentStartedEvent] = []
    resolved: list[IncidentResolvedEvent] = []
    scenario.actor.bus.subscribe(IncidentProposedEvent, proposed.append)
    scenario.actor.bus.subscribe(IncidentGeneratedEvent, generated.append)
    scenario.actor.bus.subscribe(IncidentStartedEvent, started.append)
    scenario.actor.bus.subscribe(IncidentResolvedEvent, resolved.append)

    await scenario.actor.tick(HOUR)

    assert proposed[0].kind == "resource_drop"
    assert generated[0].kind == "resource_drop"
    assert generated[0].wants == ("loot", "claimable-reward")
    assert "supply" in generated[0].tags
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

    scenario.actor.world.get_entity(scenario.controller).add_component(AdminComponent())
    await scenario.actor.submit(_cmd(scenario, "resolve-incident", incident_id=incident_id))
    await scenario.actor.tick(HOUR)

    assert incident.get_component(IncidentComponent).resolved_at_epoch == scenario.actor.epoch
    assert resolved[0].incident_id == incident_id


async def test_resolve_incident_requires_admin_character_or_controller():
    scenario = build_scenario()
    _install(scenario.actor)
    _storyteller(scenario, points=4.0)
    rejects: list[CommandRejectedEvent] = []
    resolved: list[IncidentResolvedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)
    scenario.actor.bus.subscribe(IncidentResolvedEvent, resolved.append)

    await scenario.actor.tick(HOUR)

    incident = next(
        entity
        for entity in scenario.actor.world.query().with_all([IncidentComponent]).execute_entities()
    )
    await scenario.actor.submit(
        _cmd(scenario, "resolve-incident", incident_id=str(incident.id))
    )
    await scenario.actor.tick(HOUR)

    assert rejects[-1].reason == "admin privileges required"
    assert resolved == []

    scenario.actor.world.get_entity(scenario.character).add_component(AdminComponent())
    await scenario.actor.submit(
        _cmd(scenario, "resolve-incident", incident_id=str(incident.id))
    )
    await scenario.actor.tick(HOUR)

    assert incident.get_component(IncidentComponent).resolved_at_epoch == scenario.actor.epoch
    assert resolved[-1].incident_id == str(incident.id)


async def test_incident_auto_resolves_after_spawned_loot_is_claimed():
    scenario = build_scenario()
    _install(scenario.actor)
    _storyteller(scenario, points=4.0)
    resolved: list[IncidentResolvedEvent] = []
    scenario.actor.bus.subscribe(IncidentResolvedEvent, resolved.append)

    await scenario.actor.tick(HOUR)

    incident = next(
        entity
        for entity in scenario.actor.world.query().with_all([IncidentComponent]).execute_entities()
    )
    spawned = incident.get_relationships(IncidentSpawned)
    supply_id = spawned[0][1]
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.remove_relationship(Contains, supply_id)
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), supply_id
    )

    await scenario.actor.tick(HOUR)

    assert incident.get_component(IncidentComponent).resolved_at_epoch == scenario.actor.epoch
    assert resolved[-1].incident_id == str(incident.id)


async def test_incident_auto_resolves_after_spawned_monster_is_killed():
    scenario = build_scenario()
    _install(scenario.actor)
    _storyteller(scenario, points=10.0)
    resolved: list[IncidentResolvedEvent] = []
    scenario.actor.bus.subscribe(IncidentResolvedEvent, resolved.append)

    await scenario.actor.tick(HOUR)

    incident = next(
        entity
        for entity in scenario.actor.world.query().with_all([IncidentComponent]).execute_entities()
    )
    spawned = incident.get_relationships(IncidentSpawned)
    monster_id = spawned[0][1]
    monster = scenario.actor.world.get_entity(monster_id)
    monster.add_component(DeadComponent(died_at_epoch=int(scenario.actor.epoch), cause="test"))

    await scenario.actor.tick(HOUR)

    assert incident.get_component(IncidentComponent).resolved_at_epoch == scenario.actor.epoch
    assert resolved[-1].incident_id == str(incident.id)


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
    assert any(
        isinstance(consequence, IncidentAutoResolutionConsequence)
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


def test_storyteller_auto_resolution_predicates_cover_cross_pack_states(scenario):
    world = scenario.actor.world
    room_id = str(scenario.room_a)
    incident = IncidentComponent(kind="test", budget_spent=1, started_at_epoch=0, room_id=room_id)

    unclaimed = spawn_entity(world, [IdentityComponent(name="crate", kind="item")])
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), unclaimed.id
    )
    assert story._spawned_requirement_done(world, incident, "loot", unclaimed.id) is False
    assert story._spawned_requirement_done(world, incident, "missing", unclaimed.id) is True
    assert story._spawned_requirement_done(world, incident, "loot", scenario.room_b) is True
    assert (
        story._spawned_requirement_done(
            world,
            IncidentComponent(kind="test", budget_spent=1, started_at_epoch=0),
            "loot",
            unclaimed.id,
        )
        is False
    )

    active_monster = spawn_entity(
        world,
        [IdentityComponent(name="active raider", kind="character"), CharacterComponent()],
    )
    assert story._spawned_requirement_done(world, incident, "monster", active_monster.id) is False

    pacified = spawn_entity(
        world,
            [
                IdentityComponent(name="pacified raider", kind="character"),
                CharacterComponent(),
                PacifiedComponent(
                    pacified_by=str(scenario.character),
                    language="common",
                    pacified_at_epoch=0,
                ),
        ],
    )
    prisoner = spawn_entity(
        world,
        [
            IdentityComponent(name="captured raider", kind="character"),
            CharacterComponent(),
            PrisonerComponent(),
        ],
    )
    companion = spawn_entity(
        world,
        [
            IdentityComponent(name="companion beast", kind="character"),
            CharacterComponent(),
            CompanionComponent(owner_id=str(scenario.character)),
        ],
    )
    tamed = spawn_entity(
        world,
        [
            IdentityComponent(name="tamed beast", kind="character"),
            CharacterComponent(),
            TamingComponent(tamer_id=str(scenario.character), tamed=True),
        ],
    )
    for entity in (pacified, prisoner, companion, tamed):
        assert story._spawned_requirement_done(world, incident, "monster", entity.id) is True

    pen = spawn_entity(world, [EnclosureComponent(), GateComponent(locked=True)])
    contained = spawn_entity(
        world,
        [IdentityComponent(name="contained beast", kind="character"), CharacterComponent()],
    )
    pen.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), contained.id)
    assert story._spawned_requirement_done(world, incident, "monster", contained.id) is True

    kaiju = spawn_entity(
        world,
        [IdentityComponent(name="spent kaiju", kind="kaiju"), KaijuComponent(threat_level=0)],
    )
    apex = spawn_entity(
        world,
        [
            IdentityComponent(name="spent apex", kind="character"),
            CharacterComponent(),
            ApexPredatorComponent(threat_level=0),
        ],
    )
    for entity in (kaiju, apex):
        assert story._spawned_requirement_done(world, incident, "monster", entity.id) is True

    dragon_quest = spawn_entity(
        world,
        [QuestComponent(quest_id="dragon", title="Dragon Quest", status="completed")],
    )
    dagger_quest = spawn_entity(
        world,
        [GeneratedQuestComponent(title="Dagger Quest", objective="finish", status="completed")],
    )
    for quest in (dragon_quest, dagger_quest):
        assert story._spawned_requirement_done(world, incident, "quest", quest.id) is True

    unrepaired = spawn_entity(world, [SettlementDamageComponent(severity=1)])
    repaired = spawn_entity(world, [SettlementDamageComponent(severity=0, repaired=True)])
    no_damage = spawn_entity(world, [IdentityComponent(name="plain", kind="prop")])
    assert story._spawned_requirement_done(world, incident, "damage", unrepaired.id) is False
    assert story._spawned_requirement_done(world, incident, "damage", repaired.id) is True
    assert story._spawned_requirement_done(world, incident, "damage", no_damage.id) is True


def test_incident_ready_and_resolve_handler_cover_error_paths_directly(scenario):
    world = scenario.actor.world
    ctx = story.HandlerContext(world, scenario.actor.epoch)
    admin = world.get_entity(scenario.character)
    admin.add_component(AdminComponent())

    empty_incident = spawn_entity(
        world,
        [IncidentComponent(kind="empty", budget_spent=0, started_at_epoch=0)],
    )
    assert story._incident_ready_to_resolve(world, empty_incident) is False

    result = ResolveIncidentHandler().execute(
        ctx,
        _cmd(scenario, "resolve-incident", incident_id="not-an-id"),
    )
    assert result.ok is False
    assert result.reason == "invalid character or incident id"

    result = ResolveIncidentHandler().execute(
        ctx,
        _cmd(scenario, "resolve-incident", incident_id="entity_999999"),
    )
    assert result.ok is False
    assert result.reason == "incident does not exist"

    wrong_kind = spawn_entity(world, [IdentityComponent(name="not incident", kind="prop")])
    result = ResolveIncidentHandler().execute(
        ctx,
        _cmd(scenario, "resolve-incident", incident_id=str(wrong_kind.id)),
    )
    assert result.ok is False
    assert result.reason == "target is not an incident"

    resolved = spawn_entity(
        world,
        [IncidentComponent(kind="done", budget_spent=0, started_at_epoch=0, resolved_at_epoch=1)],
    )
    result = ResolveIncidentHandler().execute(
        ctx,
        _cmd(scenario, "resolve-incident", incident_id=str(resolved.id)),
    )
    assert result.ok is False
    assert result.reason == "incident is already resolved"


def test_storyteller_fragments_ignore_missing_room_contents_and_resolved_incidents(scenario):
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    assert storyteller_fragments(type(world)(), character) == []

    room = world.get_entity(scenario.room_a)
    resolved = spawn_entity(
        world,
        [
            IdentityComponent(name="done incident", kind="incident"),
            IncidentComponent(kind="done", budget_spent=0, started_at_epoch=0, resolved_at_epoch=1),
        ],
    )
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), resolved.id)
    assert storyteller_fragments(world, character) == []
