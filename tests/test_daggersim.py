"""Tests for dagger-sim procedural RPG realm mechanics."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CommandCost,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    build_submitted_command,
    container_of,
    parse_entity_id,
    replace_component,
    spawn_entity,
)
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.mechanics.daggersim import (
    AcceptGeneratedQuestHandler,
    AskForWorkHandler,
    AskRumorHandler,
    CompleteGeneratedQuestHandler,
    DaggerQuestRewardComponent,
    ExpandSiteHandler,
    ExpansionHookComponent,
    ExpansionRequestedEvent,
    GeneratedQuestComponent,
    GeneratedSiteInstantiatedEvent,
    InstitutionComponent,
    InstitutionJoinedEvent,
    InstitutionServiceComponent,
    InstitutionServiceUsedEvent,
    InvestigateRumorHandler,
    JoinInstitutionHandler,
    MemberOfInstitution,
    PlanTravelHandler,
    ProceduralSiteComponent,
    QuestAcceptedEvent,
    QuestCompletedEvent,
    QuestDeadlineComponent,
    QuestDeadlineConsequence,
    QuestFailedEvent,
    QuestGeneratedEvent,
    QuestTemplateComponent,
    RumorBecameExpansionEvent,
    RumorComponent,
    RumorHeardEvent,
    RumorReliabilityComponent,
    RumorTargetComponent,
    RumorVerifiedEvent,
    TravelCompletedEvent,
    TravelCompletionConsequence,
    TravelHubComponent,
    TravelModeComponent,
    TravelPlanComponent,
    TravelRoute,
    TravelStartedEvent,
    UnrealizedLocationComponent,
    UseInstitutionServiceHandler,
    daggersim_fragments,
)

HOUR = 60 * 60


def _install(actor):
    actor.register_handler(ExpandSiteHandler())
    actor.register_handler(AskRumorHandler())
    actor.register_handler(InvestigateRumorHandler())
    actor.register_handler(PlanTravelHandler())
    actor.register_handler(JoinInstitutionHandler())
    actor.register_handler(UseInstitutionServiceHandler())
    actor.register_handler(AskForWorkHandler())
    actor.register_handler(AcceptGeneratedQuestHandler())
    actor.register_handler(CompleteGeneratedQuestHandler())
    actor.register_consequence(TravelCompletionConsequence())
    actor.register_consequence(QuestDeadlineConsequence())


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


def _site(scenario):
    site = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Rain Garden Hamlet", kind="settlement"),
            ProceduralSiteComponent(site_type="hamlet", seed="rain-garden"),
            UnrealizedLocationComponent(
                summary="a damp trading stop at the edge of the moss road",
                region_id="moss-road",
            ),
            ExpansionHookComponent(trigger="rumor", generator_plugin_id="worldgen.recursive"),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), site.id
    )
    return site.id


def _rumor(scenario, site_id, *, reliability=1.0):
    rumor = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="carrot vault rumor", kind="rumor"),
            RumorComponent(text="The old carrot vault beneath Rain Garden still exists."),
            RumorReliabilityComponent(score=reliability),
            RumorTargetComponent(target_id=str(site_id)),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), rumor.id
    )
    return rumor.id


def _travel_route(scenario, *, travel_seconds=2 * HOUR):
    origin = scenario.actor.world.get_entity(scenario.room_a)
    destination = scenario.actor.world.get_entity(scenario.room_b)
    origin.add_component(TravelHubComponent(name="Mosslit Burrow", region_id="moss-road"))
    destination.add_component(TravelHubComponent(name="North Tunnel", region_id="moss-road"))
    origin.add_relationship(
        TravelRoute(travel_seconds=travel_seconds, label="moss road"),
        scenario.room_b,
    )


def _institution(scenario, *, required_rank="member"):
    institution = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Burrow Cartographers", kind="institution"),
            InstitutionComponent(name="Burrow Cartographers", institution_type="guild"),
        ],
    )
    service = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="local map service", kind="service"),
            InstitutionServiceComponent(
                service_name="local map",
                required_rank=required_rank,
                output_item_name="moss road map",
            ),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), institution.id
    )
    institution.add_relationship(Contains(mode=ContainmentMode.CONTAINER), service.id)
    return institution.id, service.id


def _quest_template(scenario, *, duration_seconds=10 * HOUR):
    template = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="ratcatcher errand", kind="quest-template"),
            QuestTemplateComponent(
                title="Clear the North Tunnel",
                objective="Drive the rats away from the old milestone.",
                reward_item_name="guild writ",
                duration_seconds=duration_seconds,
            ),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), template.id
    )
    return template.id


async def test_expand_site_instantiates_unrealized_location():
    scenario = build_scenario()
    _install(scenario.actor)
    site_id = _site(scenario)
    requested: list[ExpansionRequestedEvent] = []
    instantiated: list[GeneratedSiteInstantiatedEvent] = []
    scenario.actor.bus.subscribe(ExpansionRequestedEvent, requested.append)
    scenario.actor.bus.subscribe(GeneratedSiteInstantiatedEvent, instantiated.append)

    await scenario.actor.submit(_cmd(scenario, "expand-site", site_id=str(site_id)))
    await scenario.actor.tick(HOUR)

    site = scenario.actor.world.get_entity(site_id)
    procedural = site.get_component(ProceduralSiteComponent)
    unrealized = site.get_component(UnrealizedLocationComponent)
    assert procedural.generated is True
    assert procedural.generator_id == "worldgen.recursive"
    assert unrealized.detail_level == "instantiated"
    assert requested[0].trigger == "rumor"
    assert instantiated[0].site_type == "hamlet"


async def test_expand_site_rejects_already_instantiated_location():
    scenario = build_scenario()
    _install(scenario.actor)
    site_id = _site(scenario)
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(_cmd(scenario, "expand-site", site_id=str(site_id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(_cmd(scenario, "expand-site", site_id=str(site_id)))
    await scenario.actor.tick(HOUR)

    assert any(event.reason == "site is already instantiated" for event in rejects)


async def test_heard_rumor_can_be_verified_into_expansion_request():
    scenario = build_scenario()
    _install(scenario.actor)
    site_id = _site(scenario)
    rumor_id = _rumor(scenario, site_id)
    heard: list[RumorHeardEvent] = []
    verified: list[RumorVerifiedEvent] = []
    seeded: list[RumorBecameExpansionEvent] = []
    requested: list[ExpansionRequestedEvent] = []
    scenario.actor.bus.subscribe(RumorHeardEvent, heard.append)
    scenario.actor.bus.subscribe(RumorVerifiedEvent, verified.append)
    scenario.actor.bus.subscribe(RumorBecameExpansionEvent, seeded.append)
    scenario.actor.bus.subscribe(ExpansionRequestedEvent, requested.append)

    await scenario.actor.submit(_cmd(scenario, "ask-rumor", rumor_id=str(rumor_id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "investigate-rumor", rumor_id=str(rumor_id))
    )
    await scenario.actor.tick(HOUR)

    rumor = scenario.actor.world.get_entity(rumor_id).get_component(RumorComponent)
    assert str(scenario.character) in rumor.heard_by
    assert rumor.state == "verified"
    assert heard[0].text.startswith("The old carrot vault")
    assert verified[0].rumor_id == str(rumor_id)
    assert seeded[0].site_id == str(site_id)
    assert requested[-1].trigger == "rumor"
    assert requested[-1].site_id == str(site_id)


async def test_false_rumor_is_disproven_without_expansion_request():
    scenario = build_scenario()
    _install(scenario.actor)
    site_id = _site(scenario)
    rumor_id = _rumor(scenario, site_id, reliability=0.0)
    requested: list[ExpansionRequestedEvent] = []
    scenario.actor.bus.subscribe(ExpansionRequestedEvent, requested.append)

    await scenario.actor.submit(_cmd(scenario, "ask-rumor", rumor_id=str(rumor_id)))
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "investigate-rumor", rumor_id=str(rumor_id))
    )
    await scenario.actor.tick(HOUR)

    rumor = scenario.actor.world.get_entity(rumor_id).get_component(RumorComponent)
    assert rumor.state == "disproven"
    assert requested == []


async def test_plan_travel_moves_character_after_route_time():
    scenario = build_scenario()
    _install(scenario.actor)
    _travel_route(scenario)
    started: list[TravelStartedEvent] = []
    completed: list[TravelCompletedEvent] = []
    scenario.actor.bus.subscribe(TravelStartedEvent, started.append)
    scenario.actor.bus.subscribe(TravelCompletedEvent, completed.append)

    await scenario.actor.submit(
        _cmd(scenario, "plan-travel", destination_id=str(scenario.room_b))
    )
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert scenario.character_room() == scenario.room_a
    assert character.has_component(TravelPlanComponent)
    assert started[0].destination_id == str(scenario.room_b)

    await scenario.actor.tick(HOUR)
    assert scenario.character_room() == scenario.room_a

    await scenario.actor.tick(HOUR)
    assert scenario.character_room() == scenario.room_b
    assert not character.has_component(TravelPlanComponent)
    assert completed[0].destination_id == str(scenario.room_b)


async def test_travel_mode_speed_shortens_route_time():
    scenario = build_scenario()
    _install(scenario.actor)
    _travel_route(scenario)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(TravelModeComponent(mode="cart", speed_multiplier=2.0))

    await scenario.actor.submit(
        _cmd(scenario, "plan-travel", destination_id=str(scenario.room_b))
    )
    await scenario.actor.tick(HOUR)

    assert scenario.character_room() == scenario.room_a
    await scenario.actor.tick(HOUR)

    assert scenario.character_room() == scenario.room_b
    assert not character.has_component(TravelPlanComponent)


async def test_join_institution_and_use_member_service_grants_output_item():
    scenario = build_scenario()
    _install(scenario.actor)
    institution_id, service_id = _institution(scenario)
    joined: list[InstitutionJoinedEvent] = []
    used: list[InstitutionServiceUsedEvent] = []
    scenario.actor.bus.subscribe(InstitutionJoinedEvent, joined.append)
    scenario.actor.bus.subscribe(InstitutionServiceUsedEvent, used.append)

    await scenario.actor.submit(
        _cmd(scenario, "join-institution", institution_id=str(institution_id))
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "use-institution-service", service_id=str(service_id))
    )
    await scenario.actor.tick(HOUR)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.has_relationship(MemberOfInstitution, institution_id)
    assert joined[0].institution_name == "Burrow Cartographers"
    output_id = parse_entity_id(used[0].output_item_id)
    assert output_id is not None
    output = scenario.actor.world.get_entity(output_id)
    assert output.get_component(IdentityComponent).name == "moss road map"
    assert container_of(output) == scenario.character


async def test_institution_service_rejects_insufficient_rank():
    scenario = build_scenario()
    _install(scenario.actor)
    institution_id, service_id = _institution(scenario, required_rank="officer")
    rejects: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)

    await scenario.actor.submit(
        _cmd(scenario, "join-institution", institution_id=str(institution_id))
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "use-institution-service", service_id=str(service_id))
    )
    await scenario.actor.tick(HOUR)

    assert any(event.reason == "institution rank is too low" for event in rejects)


async def test_generated_quest_can_be_accepted_completed_and_rewarded():
    scenario = build_scenario()
    _install(scenario.actor)
    template_id = _quest_template(scenario)
    generated: list[QuestGeneratedEvent] = []
    accepted: list[QuestAcceptedEvent] = []
    completed: list[QuestCompletedEvent] = []
    scenario.actor.bus.subscribe(QuestGeneratedEvent, generated.append)
    scenario.actor.bus.subscribe(QuestAcceptedEvent, accepted.append)
    scenario.actor.bus.subscribe(QuestCompletedEvent, completed.append)

    await scenario.actor.submit(_cmd(scenario, "ask-for-work", template_id=str(template_id)))
    await scenario.actor.tick(HOUR)
    quest_id = parse_entity_id(generated[0].quest_id)
    assert quest_id is not None

    await scenario.actor.submit(
        _cmd(scenario, "accept-generated-quest", quest_id=str(quest_id))
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.submit(
        _cmd(scenario, "complete-generated-quest", quest_id=str(quest_id))
    )
    await scenario.actor.tick(HOUR)

    quest = scenario.actor.world.get_entity(quest_id)
    assert quest.get_component(GeneratedQuestComponent).status == "completed"
    assert quest.get_component(DaggerQuestRewardComponent).claimed is True
    assert accepted[0].quest_id == str(quest_id)
    reward_id = parse_entity_id(completed[0].reward_item_id)
    assert reward_id is not None
    reward = scenario.actor.world.get_entity(reward_id)
    assert reward.get_component(IdentityComponent).name == "guild writ"
    assert container_of(reward) == scenario.character


async def test_generated_quest_fails_after_deadline():
    scenario = build_scenario()
    _install(scenario.actor)
    template_id = _quest_template(scenario, duration_seconds=HOUR)
    generated: list[QuestGeneratedEvent] = []
    failed: list[QuestFailedEvent] = []
    scenario.actor.bus.subscribe(QuestGeneratedEvent, generated.append)
    scenario.actor.bus.subscribe(QuestFailedEvent, failed.append)

    await scenario.actor.submit(_cmd(scenario, "ask-for-work", template_id=str(template_id)))
    await scenario.actor.tick(HOUR)
    quest_id = parse_entity_id(generated[0].quest_id)
    assert quest_id is not None

    await scenario.actor.submit(
        _cmd(scenario, "accept-generated-quest", quest_id=str(quest_id))
    )
    await scenario.actor.tick(HOUR)
    await scenario.actor.tick(1)

    quest = scenario.actor.world.get_entity(quest_id)
    assert quest.get_component(GeneratedQuestComponent).status == "failed"
    assert quest.get_component(QuestDeadlineComponent).due_at_epoch < scenario.actor.epoch
    assert failed[0].quest_id == str(quest_id)


def test_daggersim_fragments_show_nearby_unrealized_locations():
    scenario = build_scenario()
    _site(scenario)

    fragments = daggersim_fragments(
        scenario.actor.world, scenario.actor.world.get_entity(scenario.character)
    )

    assert any("Nearby unrealized hamlet: Rain Garden Hamlet" in line for line in fragments)


def test_daggersim_fragments_show_heard_rumors():
    scenario = build_scenario()
    site_id = _site(scenario)
    rumor_id = _rumor(scenario, site_id)
    rumor_entity = scenario.actor.world.get_entity(rumor_id)
    rumor = rumor_entity.get_component(RumorComponent)
    replace_component(
        rumor_entity,
        RumorComponent(text=rumor.text, heard_by=(str(scenario.character),)),
    )

    fragments = daggersim_fragments(
        scenario.actor.world, scenario.actor.world.get_entity(scenario.character)
    )

    assert any("Rumor: The old carrot vault" in line for line in fragments)


def test_daggersim_fragments_show_travel_plan():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(
        TravelPlanComponent(
            destination_id=str(scenario.room_b),
            started_at_epoch=0,
            arrive_at_epoch=HOUR,
        )
    )

    fragments = daggersim_fragments(scenario.actor.world, character)

    assert any("Traveling by foot" in line for line in fragments)


def test_daggersim_fragments_show_institutions_and_memberships():
    scenario = build_scenario()
    institution_id, _service_id = _institution(scenario)
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_relationship(MemberOfInstitution(rank="member"), institution_id)

    fragments = daggersim_fragments(scenario.actor.world, character)

    assert any("Institution nearby: Burrow Cartographers" in line for line in fragments)
    assert any("Institution membership: Burrow Cartographers" in line for line in fragments)
