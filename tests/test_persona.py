"""Tests for persona: traits, preferences, and goals in the prompt (spec 11.12)."""

from __future__ import annotations

from bunnyland.core import WorldActor, spawn_entity
from bunnyland.mechanics.persona import (
    GoalComponent,
    PreferenceComponent,
    TraitSetComponent,
    persona_fragments,
)
from bunnyland.plugins import apply_plugins, bunnyland_plugins
from bunnyland.worldgen import StubWorldBuilder, instantiate


def test_persona_fragments_describe_traits_preferences_and_goals():
    world = WorldActor().world
    character = spawn_entity(
        world,
        [
            TraitSetComponent(traits=("curious", "talkative")),
            PreferenceComponent(likes=("berries",), dislikes=("storms",)),
            GoalComponent(active_goals=("find the elder",)),
        ],
    )
    lines = persona_fragments(world, character)
    assert "You are curious and talkative." in lines
    assert "You like berries." in lines
    assert "You dislike storms." in lines
    assert "Your goal: find the elder." in lines


def test_persona_fragments_empty_when_unset():
    world = WorldActor().world
    character = spawn_entity(world, [])
    assert persona_fragments(world, character) == []


def test_single_trait_has_no_conjunction():
    world = WorldActor().world
    character = spawn_entity(world, [TraitSetComponent(traits=("brave",))])
    assert persona_fragments(world, character) == ["You are brave."]


async def test_generated_characters_carry_their_persona():
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    result = await instantiate(actor, StubWorldBuilder().propose("a quiet marsh"))

    hazel = actor.world.get_entity(result.characters["hazel"])
    assert hazel.has_component(TraitSetComponent)
    assert "curious" in hazel.get_component(TraitSetComponent).traits
    assert hazel.has_component(GoalComponent)
    assert persona_fragments(actor.world, hazel)  # surfaces in the prompt
