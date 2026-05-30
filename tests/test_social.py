"""Tests for social bonds: speech grows relationships, surfaced in the prompt (spec 11.15)."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    SayHandler,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.mechanics.social import (
    SocialBond,
    adjust_bond,
    bond_between,
    install_social,
    relationship_fragments,
)

HOUR = 3600.0


def _scenario_with_listener():
    scenario = build_scenario()
    scenario.actor.register_handler(SayHandler())
    install_social(scenario.actor)
    hazel = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), hazel.id
    )
    return scenario, hazel.id


def _say(scenario, text, intent):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="say",
        cost=CommandCost(action=1, focus=1),
        lane=Lane.WORLD,
        payload={"text": text, "intent": intent},
    )


async def test_saying_builds_familiarity_both_ways():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    juniper = scenario.character

    await scenario.actor.submit(_say(scenario, "Hello there.", "neutral"))
    await scenario.actor.tick(HOUR)

    assert bond_between(world, juniper, hazel).familiarity > 0
    assert bond_between(world, hazel, juniper).familiarity > 0


async def test_praise_warms_the_bond_and_threat_frightens_the_listener():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    juniper = scenario.character

    await scenario.actor.submit(_say(scenario, "You are wonderful.", "praise"))
    await scenario.actor.tick(HOUR)
    assert bond_between(world, juniper, hazel).affinity > 0
    assert bond_between(world, hazel, juniper).affinity > 0

    await scenario.actor.submit(_say(scenario, "I will get you.", "threat"))
    await scenario.actor.tick(HOUR)
    # The listener now fears the speaker.
    assert bond_between(world, hazel, juniper).fear > 0


async def test_repeated_speech_accumulates_familiarity():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    juniper = scenario.character

    await scenario.actor.submit(_say(scenario, "One.", "neutral"))
    await scenario.actor.tick(HOUR)
    first = bond_between(world, juniper, hazel).familiarity

    await scenario.actor.submit(_say(scenario, "Two.", "neutral"))
    await scenario.actor.tick(HOUR)
    second = bond_between(world, juniper, hazel).familiarity

    assert second > first  # the edge updates in place, not resets


def test_adjust_bond_creates_clamps_and_accumulates():
    scenario = build_scenario()
    world = scenario.actor.world
    a, b = scenario.character, scenario.room_b  # any two entities suffice for the edge

    adjust_bond(world, a, b, {"affinity": 0.6})
    adjust_bond(world, a, b, {"affinity": 0.9})  # 1.5 -> clamps to 1.0
    bond = bond_between(world, a, b)
    assert bond.affinity == 1.0
    adjust_bond(world, a, b, {"fear": -5.0})  # clamps to -1.0
    assert bond_between(world, a, b).fear == -1.0


def test_relationship_fragment_describes_strong_bonds():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    juniper = world.get_entity(scenario.character)

    adjust_bond(world, scenario.character, hazel, {"affinity": 0.5})
    fragments = relationship_fragments(world, juniper)
    assert any("fond of Hazel" in line for line in fragments)

    adjust_bond(world, scenario.character, hazel, {"fear": 0.6})  # fear dominates
    assert any("fear Hazel" in line for line in relationship_fragments(world, juniper))


def test_no_fragment_for_a_faint_bond():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    adjust_bond(world, scenario.character, hazel, {"familiarity": 0.1})  # below threshold
    assert relationship_fragments(world, world.get_entity(scenario.character)) == []


def test_social_bond_defaults_are_neutral():
    assert SocialBond().affinity == 0.0
    assert SocialBond().familiarity == 0.0
