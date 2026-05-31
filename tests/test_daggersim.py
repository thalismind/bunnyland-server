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
    replace_component,
    spawn_entity,
)
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.mechanics.daggersim import (
    AskRumorHandler,
    ExpandSiteHandler,
    ExpansionHookComponent,
    ExpansionRequestedEvent,
    GeneratedSiteInstantiatedEvent,
    InvestigateRumorHandler,
    ProceduralSiteComponent,
    RumorBecameExpansionEvent,
    RumorComponent,
    RumorHeardEvent,
    RumorReliabilityComponent,
    RumorTargetComponent,
    RumorVerifiedEvent,
    UnrealizedLocationComponent,
    daggersim_fragments,
)

HOUR = 60 * 60


def _install(actor):
    actor.register_handler(ExpandSiteHandler())
    actor.register_handler(AskRumorHandler())
    actor.register_handler(InvestigateRumorHandler())


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
