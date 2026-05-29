"""Tests for affect/thought: events produce decaying thoughts that shift mood + labels."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    AffectComponent,
    AffectVector,
    CharacterComponent,
    CommandCost,
    ContainmentMode,
    Contains,
    HasThought,
    IdentityComponent,
    Lane,
    SayHandler,
    SpeechIntent,
    ThoughtComponent,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.core.components import AffectDelta
from bunnyland.mechanics import install_affect, install_needs
from bunnyland.mechanics.affect import THOUGHT_TTL_SECONDS, apply_delta, labels_for
from bunnyland.mechanics.consumables import ConsumableComponent, FoodComponent

HOUR = 3600.0


def affect_scenario():
    scenario = build_scenario()
    install_affect(scenario.actor)
    char = scenario.actor.world.get_entity(scenario.character)
    char.add_component(AffectComponent(baseline=AffectVector(), current=AffectVector()))
    return scenario


# -- pure helpers -----------------------------------------------------------------------


def test_apply_delta_and_labels():
    vector = apply_delta(AffectVector(), AffectDelta(valence=-10, anger=8))
    assert vector.valence == -10
    assert vector.anger == 8
    labels = labels_for(vector)
    assert "unhappy" in labels
    assert "angry" in labels


# -- event -> thought -> affect ---------------------------------------------------------


async def test_eating_creates_a_satisfied_thought_and_lifts_mood():
    scenario = affect_scenario()
    install_needs(scenario.actor)
    from bunnyland.mechanics.meter import Meter
    from bunnyland.mechanics.needs import HungerComponent

    char = scenario.actor.world.get_entity(scenario.character)
    char.add_component(HungerComponent(meter=Meter(value=40.0)))
    berry = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="berry", kind="item"),
            FoodComponent(nutrition=5, satiety=20),
            ConsumableComponent(),
        ],
    )
    scenario.actor.world.get_entity(scenario.character).add_relationship(
        Contains(mode=ContainmentMode.INVENTORY), berry.id
    )

    eat = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="eat",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"item_id": str(berry.id)},
    )
    await scenario.actor.submit(eat)
    await scenario.actor.tick(HOUR)

    # A thought was attached and mood lifted (valence up) in the same tick.
    assert len(char.get_relationships(HasThought)) == 1
    assert char.get_component(AffectComponent).current.valence > 0


async def test_overheard_insult_makes_listener_angry():
    scenario = affect_scenario()
    scenario.actor.register_handler(SayHandler())
    # A listener with its own affect.
    listener = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Hazel", kind="character"),
            CharacterComponent(),
            AffectComponent(),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), listener.id
    )

    say = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="say",
        cost=CommandCost(action=1, focus=1),
        lane=Lane.WORLD,
        payload={"text": "You are a fool.", "intent": SpeechIntent.INSULT.value},
    )
    await scenario.actor.submit(say)
    await scenario.actor.tick(HOUR)

    assert "angry" in listener.get_component(AffectComponent).labels
    assert "unhappy" in listener.get_component(AffectComponent).labels


async def test_thoughts_decay_and_mood_returns_to_baseline():
    scenario = affect_scenario()
    char = scenario.actor.world.get_entity(scenario.character)
    # Attach a thought directly that expires soon.
    thought = spawn_entity(
        scenario.actor.world,
        [
            ThoughtComponent(
                label="annoyed",
                text="grr",
                affect_delta=AffectDelta(anger=20),
                created_at_epoch=0,
                expires_at_epoch=int(HOUR),
            )
        ],
    )
    char.add_relationship(HasThought(), thought.id)

    await scenario.actor.tick(HOUR / 2)  # before expiry: anger present
    assert "angry" in char.get_component(AffectComponent).labels

    await scenario.actor.tick(HOUR)  # now past expiry -> thought decays
    assert char.get_component(AffectComponent).labels == frozenset()
    assert len(char.get_relationships(HasThought)) == 0


def test_thought_ttl_is_positive():
    assert THOUGHT_TTL_SECONDS > 0
