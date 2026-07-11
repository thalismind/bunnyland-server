"""Tests for persona: traits, preferences, and goals in the prompt (spec 11.12)."""

from __future__ import annotations

from bunnyland.core import WorldActor, spawn_entity
from bunnyland.core.generation import GenerationRequest
from bunnyland.foundation.persona.mechanics import (
    GoalComponent,
    PersonaProfileComponent,
    PreferenceComponent,
    TraitSetComponent,
    persona_fragments,
)
from bunnyland.foundation.persona.plugin import (
    GOALS_CAPABILITY,
    GOALS_CONTEXT,
    PersonaGenerationEnricher,
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


def test_persona_component_fragments_skip_empty_fields():
    world = WorldActor().world
    character = spawn_entity(world, [])
    ctx = ComponentPromptContext.for_entity(
        world,
        character,
        perspective=PromptPerspective(viewer=character, perspective="first-person"),
    )

    # voice empty / role set -> only role line (30->32, 32->34)
    assert PersonaProfileComponent(role="scout").prompt_fragments(ctx) == (
        "Your current role: scout.",
    )
    # voice set / role empty -> only voice line
    assert PersonaProfileComponent(voice="gruff").prompt_fragments(ctx) == ("Your voice: gruff.",)
    # empty traits -> no fragments (45)
    assert TraitSetComponent().prompt_fragments(ctx) == ()
    # dislikes only, no likes (65->74)
    assert PreferenceComponent(dislikes=("noise",)).prompt_fragments(ctx) == ("I dislike noise.",)
    # likes only, no dislikes (74->83)
    assert PreferenceComponent(likes=("sun",)).prompt_fragments(ctx) == ("I like sun.",)
    # empty goals -> no fragments (94)
    assert GoalComponent().prompt_fragments(ctx) == ()


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


def test_persona_generation_enricher_materializes_owned_goals():
    enricher = PersonaGenerationEnricher()
    ignored = enricher.enrich(GenerationRequest(entity_kind="item"))
    assert ignored.components == ()

    request = GenerationRequest(
        entity_kind="character",
        capabilities=(GOALS_CAPABILITY,),
        context={GOALS_CONTEXT: ("explore", "explore", "help")},
    )
    component = enricher.enrich(request).components[0]
    assert component.active_goals == ("explore", "help")

    existing = GoalComponent(active_goals=("existing",))
    assert (
        enricher.enrich(
            GenerationRequest(
                entity_kind="character",
                context={GOALS_CONTEXT: ("new",), "base_components": (existing,)},
            )
        ).components
        == ()
    )
