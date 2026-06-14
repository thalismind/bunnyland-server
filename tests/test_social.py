"""Tests for social bonds: speech grows relationships, surfaced in the prompt (spec 11.15)."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    AffectComponent,
    AffectVector,
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    IdentityComponent,
    Lane,
    SayHandler,
    build_submitted_command,
    parse_entity_id,
    spawn_entity,
)
from bunnyland.core.events import EventVisibility, SpeechToldEvent
from bunnyland.mechanics.meter import Meter
from bunnyland.mechanics.needs import SocialNeedComponent
from bunnyland.mechanics.social import (
    RelationshipReactor,
    SocialBond,
    adjust_bond,
    bond_between,
    install_social,
    interpret_speech_for_listener,
    relationship_fragments,
)
from bunnyland.prompts import ComponentPromptContext, PromptPerspective

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


async def test_speech_satisfies_social_need_for_speaker_and_listener():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    speaker = world.get_entity(scenario.character)
    listener = world.get_entity(hazel)
    speaker.add_component(SocialNeedComponent(meter=Meter(value=50.0)))
    listener.add_component(SocialNeedComponent(meter=Meter(value=50.0)))

    await scenario.actor.submit(_say(scenario, "Hello there.", "neutral"))
    await scenario.actor.tick(HOUR)

    assert speaker.get_component(SocialNeedComponent).meter.value < 50.0
    assert listener.get_component(SocialNeedComponent).meter.value < 50.0


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


async def test_speech_interpretation_depends_on_listener_mood_and_relationship():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    juniper = scenario.character
    clover = spawn_entity(
        world,
        [
            IdentityComponent(name="Clover", kind="character"),
            CharacterComponent(),
            AffectComponent(current=AffectVector(anger=10.0), labels=("angry",)),
        ],
    )
    world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), clover.id
    )
    adjust_bond(world, clover.id, juniper, {"resentment": 0.6})

    await scenario.actor.submit(_say(scenario, "That was excellent work.", "praise"))
    await scenario.actor.tick(HOUR)

    warm = bond_between(world, hazel, juniper)
    hostile = bond_between(world, clover.id, juniper)
    assert warm.affinity > 0
    assert hostile.resentment > 0.6
    assert hostile.affinity < 0


def test_interpret_speech_can_soften_a_trusted_threat():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    adjust_bond(world, hazel, scenario.character, {"trust": 0.6})

    interpretation = interpret_speech_for_listener(
        world,
        scenario.character,
        hazel,
        "threat",
    )

    assert interpretation.base_interpretation == "threat"
    assert interpretation.final_interpretation == "joke"
    assert interpretation.relationship_tags == ("trusting",)


def test_interpret_speech_handles_missing_listener_and_suspicious_apology():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    wary = world.get_entity(hazel)
    wary.add_component(
        AffectComponent(current=AffectVector(fear=10.0, stress=10.0), labels=())
    )
    adjust_bond(world, hazel, scenario.character, {"resentment": 0.6})

    missing_interpretation = interpret_speech_for_listener(
        world,
        scenario.character,
        parse_entity_id("entity_999"),
        "praise",
    )
    apology = interpret_speech_for_listener(
        world,
        scenario.character,
        hazel,
        "apology",
    )

    assert missing_interpretation.final_interpretation == "praise"
    assert apology.final_interpretation == "neutral"
    assert apology.relationship_tags == ("hostile",)
    assert "afraid" in apology.mood_tags
    assert "tense" in apology.mood_tags


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


def test_social_bond_prompt_fragments_use_context_target_and_perspective():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    target = spawn_entity(
        world,
        [IdentityComponent(name="Hazel", kind="character"), CharacterComponent()],
    )
    first = ComponentPromptContext.for_entity(
        world,
        character,
        perspective=PromptPerspective(viewer=character, perspective="first-person"),
        target=target,
    )
    third = ComponentPromptContext.for_entity(
        world,
        character,
        perspective=PromptPerspective(viewer=character, perspective="third-person"),
        target=target,
    )
    observer = spawn_entity(world, [CharacterComponent()])
    observer_ctx = ComponentPromptContext.for_entity(
        world,
        character,
        perspective=PromptPerspective(viewer=observer),
        target=target,
    )

    assert SocialBond(affinity=0.5).prompt_fragments(first) == ("I am fond of Hazel.",)
    assert SocialBond(familiarity=0.5).prompt_fragments(third) == ("They know Hazel.",)
    assert SocialBond(affinity=0.5).prompt_fragments(observer_ctx) == ()
    assert SocialBond(affinity=0.1).prompt_fragments(first) == ()


def test_relationship_fragments_cover_negative_and_familiar_bonds():
    scenario = build_scenario()
    world = scenario.actor.world
    juniper = world.get_entity(scenario.character)
    rival = spawn_entity(
        world,
        [IdentityComponent(name="Rival", kind="character"), CharacterComponent()],
    )
    acquaintance = spawn_entity(
        world,
        [IdentityComponent(name="Acquaintance", kind="character"), CharacterComponent()],
    )
    mystery = spawn_entity(world, [CharacterComponent()])

    adjust_bond(world, scenario.character, rival.id, {"resentment": 0.4})
    adjust_bond(world, scenario.character, acquaintance.id, {"familiarity": 0.4})
    adjust_bond(world, scenario.character, mystery.id, {"affinity": -0.4})

    fragments = relationship_fragments(world, juniper)

    assert any("resent Rival" in line for line in fragments)
    assert any("know Acquaintance" in line for line in fragments)
    assert any("dislike someone" in line for line in fragments)


def test_relationship_fragments_skip_dangling_targets():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    target = spawn_entity(world, [CharacterComponent()])
    character.add_relationship(SocialBond(familiarity=0.5), target.id)
    world.remove(target.id)

    assert relationship_fragments(world, character) == []


def test_relationship_reactor_handles_tell_events_and_ignores_invalid_targets():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    speaker = world.get_entity(scenario.character)
    listener = world.get_entity(hazel)
    speaker.add_component(SocialNeedComponent(meter=Meter(value=40.0)))
    listener.add_component(SocialNeedComponent(meter=Meter(value=40.0)))
    reactor = RelationshipReactor(world)

    reactor._on_speech(
        SpeechToldEvent(
            event_id="missing-speaker",
            world_epoch=0,
            created_at="2026-01-01T00:00:00Z",
            visibility=EventVisibility.PRIVATE,
            actor_id="entity_999",
            target_ids=(str(hazel),),
            text="hello",
        )
    )
    reactor._on_speech(
        SpeechToldEvent(
            event_id="tell",
            world_epoch=1,
            created_at="2026-01-01T00:00:00Z",
            visibility=EventVisibility.PRIVATE,
            actor_id=str(scenario.character),
            target_ids=("not-an-id", str(scenario.character), str(hazel)),
            text="hello",
            final_interpretation="apology",
        )
    )

    assert speaker.get_component(SocialNeedComponent).meter.value < 40.0
    assert listener.get_component(SocialNeedComponent).meter.value < 40.0
    assert bond_between(world, scenario.character, hazel).familiarity > 0


def test_no_fragment_for_a_faint_bond():
    scenario, hazel = _scenario_with_listener()
    world = scenario.actor.world
    adjust_bond(world, scenario.character, hazel, {"familiarity": 0.1})  # below threshold
    assert relationship_fragments(world, world.get_entity(scenario.character)) == []


def test_social_bond_defaults_are_neutral():
    assert SocialBond().affinity == 0.0
    assert SocialBond().familiarity == 0.0
