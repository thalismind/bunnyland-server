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
    spawn_entity,
)
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.mechanics.daggersim import (
    ExpandSiteHandler,
    ExpansionHookComponent,
    ExpansionRequestedEvent,
    GeneratedSiteInstantiatedEvent,
    ProceduralSiteComponent,
    UnrealizedLocationComponent,
    daggersim_fragments,
)

HOUR = 60 * 60


def _install(actor):
    actor.register_handler(ExpandSiteHandler())


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


def test_daggersim_fragments_show_nearby_unrealized_locations():
    scenario = build_scenario()
    _site(scenario)

    fragments = daggersim_fragments(
        scenario.actor.world, scenario.actor.world.get_entity(scenario.character)
    )

    assert any("Nearby unrealized hamlet: Rain Garden Hamlet" in line for line in fragments)
