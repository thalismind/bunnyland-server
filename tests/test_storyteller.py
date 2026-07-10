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
from bunnyland.mechanics.barbariansim import BarbarianSimPolicyComponent
from bunnyland.mechanics.colonysim import ColonySimComponent, PrisonerComponent
from bunnyland.mechanics.daggersim import GeneratedQuestComponent, PacifiedComponent
from bunnyland.mechanics.dinosim import (
    ApexPredatorComponent,
    CompanionComponent,
    DinosimPolicyComponent,
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
from bunnyland.prompts import ComponentPromptContext

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


def test_incident_generated_event_exposes_generation_properties():
    generation = story.GenerationIntentComponent(
        description="a custom incident",
        tags=("incident", "custom"),
        wants=("loot",),
        needs=("dinosim",),
        source_key="custom",
        entity_kind="incident",
    )
    event = IncidentGeneratedEvent(
        **story._event_base(
            0,
            seed="custom:0:1",
            incident_id="entity_1",
            incident_key="custom",
            kind="custom",
            budget_spent=1.0,
            generation=generation,
        )
    )
    assert event.intent == "a custom incident"  # 117
    assert event.tags == ("incident", "custom")
    assert event.wants == ("loot",)
    assert event.needs == ("dinosim",)  # 129


def test_choose_incident_selects_kaiju_attack_when_colony_and_dino_enabled(scenario):
    world = scenario.actor.world
    spawn_entity(world, [ColonySimComponent(enabled=True)])
    spawn_entity(world, [DinosimPolicyComponent(kaiju_storyteller_incidents=True)])
    kind, spent = story._choose_incident(world, 16.0)  # 147-155, 172
    assert kind == "kaiju_attack"
    assert spent == 15.0
    generation = story._incident_generation("kaiju_attack", 15.0)  # line 200
    assert "kaiju" in generation.tags
    assert generation.needs == ("dinosim",)


def test_choose_incident_selects_barbarian_raid_when_colony_and_barbarian_enabled(scenario):
    world = scenario.actor.world
    spawn_entity(world, [ColonySimComponent(enabled=True)])
    spawn_entity(world, [BarbarianSimPolicyComponent(raid_storyteller_incidents=True)])
    kind, spent = story._choose_incident(world, 13.0)  # 159-167, 174
    assert kind == "barbarian_raid"
    assert spent == 12.0
    generation = story._incident_generation("barbarian_raid", 12.0)  # line 212
    assert "raid" in generation.tags
    assert generation.needs == ("barbariansim",)


def test_disabled_storyteller_accrues_points_without_spawning(scenario):
    world = scenario.actor.world
    teller = spawn_entity(
        world,
        [
            IdentityComponent(name="idle storyteller", kind="controller"),
            StorytellerComponent(enabled=False, interval_seconds=int(HOUR)),
            IncidentBudgetComponent(points=4.0, points_per_day=6.0),
        ],
    )
    events = StorytellerConsequence().process(world, story.SECONDS_PER_DAY)  # 421-422
    assert events == []
    budget = teller.get_component(IncidentBudgetComponent)
    assert budget.points > 4.0  # points accrued
    assert not list(world.query().with_all([IncidentComponent]).execute_entities())


def test_enrichment_spawns_hostile_for_hostile_encounter(scenario):
    world = scenario.actor.world
    enrichment = story.StorytellerIncidentEnrichment(world)
    incident = story._spawn_incident(
        world, 0, world.get_entity(scenario.room_a), "hostile_encounter", 10.0
    )
    generation = incident.get_component(story.GenerationIntentComponent)
    event = IncidentGeneratedEvent(
        **story._event_base(
            0,
            room_id=str(scenario.room_a),
            seed="hostile_encounter:0:10",
            incident_id=str(incident.id),
            incident_key="hostile_encounter",
            kind="hostile_encounter",
            budget_spent=10.0,
            generation=generation,
        )
    )
    enrichment._on_incident(event)  # 282->exit (elif branch taken)
    spawned = list(incident.get_relationships(IncidentSpawned))
    assert spawned and spawned[0][0].kind == "monster"


def test_enrichment_ignores_kinds_without_builtin_handling(scenario):
    world = scenario.actor.world
    enrichment = story.StorytellerIncidentEnrichment(world)
    incident = story._spawn_incident(
        world, 0, world.get_entity(scenario.room_a), "trader_arrival", 5.0
    )
    generation = incident.get_component(story.GenerationIntentComponent)
    event = IncidentGeneratedEvent(
        **story._event_base(
            0,
            room_id=str(scenario.room_a),
            seed="trader_arrival:0:5",
            incident_id=str(incident.id),
            incident_key="trader_arrival",
            kind="trader_arrival",  # neither resource_drop nor hostile -> 282->exit
            budget_spent=5.0,
            generation=generation,
        )
    )
    enrichment._on_incident(event)
    assert not list(incident.get_relationships(IncidentSpawned))


def test_choose_incident_selects_trader_arrival_at_mid_budget(scenario):
    # 5 <= points < 10 with no special sims -> trader arrival (line 178)
    kind, spent = story._choose_incident(scenario.actor.world, 6.0)
    assert kind == "trader_arrival"
    assert spent == 5.0


def test_incident_generation_falls_back_to_generic_intent():
    generation = story._incident_generation("trader_arrival", 5.0)  # line 223
    assert generation.description == "a trader arrival incident"
    assert generation.tags == ("incident", "trader_arrival")
    assert generation.source_key == "trader_arrival"


def test_plugin_incident_definitions_select_deterministically_and_fall_back(scenario):
    assert story._enabled_component(scenario.actor.world, "MissingComponent", "enabled") is False
    eligible = story.IncidentDefinition(id="rain", cost=3.0, priority=5)
    higher = story.IncidentDefinition(id="storm", cost=3.0, priority=10)
    disabled = story.IncidentDefinition(
        id="meteor", cost=1.0, priority=100, eligible=lambda world: False
    )

    selected, spent = story._choose_incident_definition(
        scenario.actor.world, 4.0, (eligible, higher, disabled)
    )
    assert selected is higher
    assert spent == 3.0

    fallback, spent = story._choose_incident_definition(
        scenario.actor.world, 1.0, (eligible,)
    )
    assert fallback.id == "resource_drop"
    assert spent == 1.0


def test_storyteller_consequence_uses_plugin_incident_generation(scenario):
    _storyteller(scenario, points=4.0)
    plain = story.IncidentDefinition(id="rain", cost=1.0, priority=10)
    events = story.StorytellerConsequence((plain,)).process(
        scenario.actor.world, int(HOUR)
    )
    generated = next(event for event in events if isinstance(event, IncidentGeneratedEvent))
    assert generated.kind == "rain"
    assert generated.intent == "a rain incident"

    _storyteller(scenario, points=4.0)
    custom = story.IncidentDefinition(
        id="storm",
        cost=1.0,
        priority=10,
        generation=lambda spent: story.GenerationIntentComponent(
            description=f"custom storm {spent:g}", entity_kind="incident"
        ),
    )
    events = story.StorytellerConsequence((custom,)).process(
        scenario.actor.world, int(HOUR)
    )
    generated = next(
        event
        for event in events
        if isinstance(event, IncidentGeneratedEvent) and event.kind == "storm"
    )
    assert generated.intent == "custom storm 1"


def test_target_room_skips_character_without_valid_room(scenario):
    world = scenario.actor.world
    # the only character is not contained in any room -> the loop body continues (140->136)
    loose = spawn_entity(
        world,
        [IdentityComponent(name="Drifter", kind="character"), CharacterComponent()],
    )
    detached_world = type(world)()
    spawn_entity(
        detached_world,
        [IdentityComponent(name="Floater", kind="character"), CharacterComponent()],
    )
    room = spawn_entity(detached_world, [RoomComponent(title="Hall")])
    # character has no container, so _target_room falls through to the first room
    assert _target_room(detached_world) == room
    assert loose is not None


def test_spawn_incident_without_room_leaves_room_id_unset(scenario):
    world = scenario.actor.world
    incident = story._spawn_incident(world, 0, None, "resource_drop", 2.0)  # 246->248
    assert incident.get_component(IncidentComponent).room_id is None


def test_incident_enrichment_ignores_events_with_missing_entities(scenario):
    world = scenario.actor.world
    enrichment = story.StorytellerIncidentEnrichment(world)
    generation = story._incident_generation("resource_drop", 2.0)
    event = IncidentGeneratedEvent(
        **story._event_base(
            0,
            room_id="entity_999999",  # missing room -> early return (line 269)
            seed="resource_drop:0:2",
            incident_id="entity_999999",
            incident_key="resource_drop",
            kind="resource_drop",
            budget_spent=2.0,
            generation=generation,
        )
    )
    # should simply return without raising or spawning anything
    enrichment._on_incident(event)


def test_monster_neutralized_with_unlocked_enclosure_gate_is_not_done(scenario):
    world = scenario.actor.world
    incident = IncidentComponent(kind="test", budget_spent=1, started_at_epoch=0)
    pen = spawn_entity(world, [EnclosureComponent(), GateComponent(locked=False)])
    beast = spawn_entity(
        world,
        [IdentityComponent(name="loose beast", kind="character"), CharacterComponent()],
    )
    pen.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), beast.id)
    # gate unlocked -> not neutralized by containment (331->333)
    assert story._spawned_requirement_done(world, incident, "monster", beast.id) is False


def test_quest_done_false_without_quest_components(scenario):
    world = scenario.actor.world
    plain = spawn_entity(world, [IdentityComponent(name="not a quest", kind="prop")])
    assert story._quest_done(world, plain) is False


def test_spawned_requirement_done_true_when_target_missing(scenario):
    world = scenario.actor.world
    incident = IncidentComponent(kind="test", budget_spent=1, started_at_epoch=0)
    missing_id = parse_entity_id("entity_999999")
    # absent target counts as handled (line 365)
    assert story._spawned_requirement_done(world, incident, "loot", missing_id) is True


def test_incident_component_prompt_fragments_describe_active_incidents(scenario):
    world = scenario.actor.world
    incident = spawn_entity(
        world,
        [IncidentComponent(kind="resource_drop", budget_spent=2, started_at_epoch=0)],
    )
    ctx = ComponentPromptContext.for_entity(world, incident)

    assert incident.get_component(IncidentComponent).prompt_fragments(ctx) == (
        "Active incident: resource drop.",
    )
    assert (
        IncidentComponent(
            kind="done", budget_spent=0, started_at_epoch=0, resolved_at_epoch=1
        ).prompt_fragments(ctx)
        == ()
    )
