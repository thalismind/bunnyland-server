"""Tests for persona: traits, preferences, and goals in the prompt (spec 11.12)."""

from __future__ import annotations

from bunnyland.core import WorldActor, spawn_entity
from bunnyland.mechanics.persona import (
    GoalComponent,
    PersonaProfileComponent,
    PreferenceComponent,
    TraitSetComponent,
    persona_fragments,
)
from bunnyland.plugins import apply_plugins, bunnyland_plugins
from bunnyland.prompts import ComponentPromptContext, PromptPerspective
from bunnyland.worldgen import StubWorldBuilder, instantiate


def test_persona_fragments_describe_traits_preferences_and_goals():
    world = WorldActor().world
    character = spawn_entity(
        world,
        [
            TraitSetComponent(traits=("curious", "talkative")),
            PersonaProfileComponent(voice="warm and direct", role="forager"),
            PreferenceComponent(likes=("berries",), dislikes=("storms",)),
            GoalComponent(active_goals=("find the elder",)),
        ],
    )
    lines = persona_fragments(world, character)
    assert "Your voice: warm and direct." in lines
    assert "Your current role: forager." in lines
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


def test_persona_component_fragments_support_perspective_styles():
    world = WorldActor().world
    character = spawn_entity(world, [])
    first = ComponentPromptContext.for_entity(
        world,
        character,
        perspective=PromptPerspective(viewer=character, perspective="first-person"),
    )
    third = ComponentPromptContext.for_entity(
        world,
        character,
        perspective=PromptPerspective(viewer=character, perspective="third-person"),
    )

    assert TraitSetComponent(traits=("brave",)).prompt_fragments(first) == ("I am brave.",)
    assert PreferenceComponent(likes=("tea",), dislikes=("rain",)).prompt_fragments(third) == (
        "They like tea.",
        "They dislike rain.",
    )
    assert GoalComponent(active_goals=("find shelter",)).prompt_fragments(first) == (
        "My goal: find shelter.",
    )
    assert PersonaProfileComponent(voice="soft", role="guide").prompt_fragments(first) == (
        "Your voice: soft.",
        "Your current role: guide.",
    )


def test_persona_component_fragments_are_self_view_only():
    world = WorldActor().world
    viewer = spawn_entity(world, [])
    character = spawn_entity(world, [])
    ctx = ComponentPromptContext.for_entity(
        world,
        character,
        perspective=PromptPerspective(viewer=viewer),
    )

    assert TraitSetComponent(traits=("secretive",)).prompt_fragments(ctx) == ()
    assert PersonaProfileComponent(voice="secretive").prompt_fragments(ctx) == ()
    assert PreferenceComponent(likes=("moonlight",)).prompt_fragments(ctx) == ()
    assert GoalComponent(active_goals=("hide the map",)).prompt_fragments(ctx) == ()


async def test_generated_characters_carry_their_persona():
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    result = await instantiate(actor, await StubWorldBuilder().propose("a quiet marsh"))

    hazel = actor.world.get_entity(result.characters["hazel"])
    assert hazel.has_component(TraitSetComponent)
    assert "curious" in hazel.get_component(TraitSetComponent).traits
    assert hazel.has_component(GoalComponent)
    assert persona_fragments(actor.world, hazel)  # surfaces in the prompt
