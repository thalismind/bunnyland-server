"""Tests for the foundation prompt builder (spec 16)."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    AffectComponent,
    AffectVector,
    ContainmentMode,
    Contains,
    IdentityComponent,
    MemoryProfileComponent,
    PortableComponent,
    spawn_entity,
)
from bunnyland.mechanics.meter import Meter
from bunnyland.mechanics.needs import HungerComponent, ThirstComponent, need_fragments
from bunnyland.memory import InMemoryStore
from bunnyland.projections import RecentContextProjection, RoomSummaryProjection
from bunnyland.prompts import PromptBuilder, render_prompt


def add_item(scenario, room_id, name):
    item = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name=name, kind="item"), PortableComponent()],
    )
    scenario.actor.world.get_entity(room_id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), item.id
    )
    return item


def test_build_context_has_core_sections():
    scenario = build_scenario()
    add_item(scenario, scenario.room_a, "three berries")
    builder = PromptBuilder(scenario.actor.world)

    ctx = builder.build(scenario.character, epoch=scenario.actor.epoch)

    assert ctx.name == "Juniper"
    assert ctx.status.startswith("active")
    assert ctx.action == (5.0, 5.0)
    assert ctx.location_title == "Mosslit Burrow"
    assert "three berries" in ctx.visible_objects
    assert "north" in ctx.exits
    assert "move north" in ctx.commands
    assert "take note" in ctx.commands


def test_build_context_includes_needs_feelings_and_notes():
    scenario = build_scenario()
    char = scenario.actor.world.get_entity(scenario.character)
    char.add_component(HungerComponent(meter=Meter(value=75.0)))  # urgent
    char.add_component(ThirstComponent(meter=Meter(value=10.0)))  # calm -> no phrase
    char.add_component(
        AffectComponent(current=AffectVector(stress=20.0), labels=frozenset({"tense"}))
    )
    char.add_component(MemoryProfileComponent(vector_collection="juniper"))

    store = InMemoryStore()
    store.add("juniper", text="The basin water is unsafe.", created_at_epoch=1)

    builder = PromptBuilder(
        scenario.actor.world,
        memory_store=store,
        fragment_providers=[need_fragments],
    )
    ctx = builder.build(scenario.character, epoch=scenario.actor.epoch)

    assert any("hungry" in n for n in ctx.conditions)
    assert all("dry" not in n for n in ctx.conditions)  # thirst calm
    assert "tense" in ctx.feelings
    assert "The basin water is unsafe." in ctx.notes


def test_render_prompt_matches_foundation_layout():
    scenario = build_scenario()
    builder = PromptBuilder(scenario.actor.world)
    ctx = builder.build(scenario.character, epoch=scenario.actor.epoch)
    text = render_prompt(ctx)

    assert "You are Juniper, a character." in text
    assert "Location:" in text
    assert "Points:" in text
    assert "Action: 5.0/5.0" in text
    assert "Available commands:" in text


def test_recent_context_appears_in_prompt():
    scenario = build_scenario()
    recent = RecentContextProjection(scenario.actor.world)
    # seed a recent entry directly
    recent._log[str(scenario.room_a)].append("Hazel warned the water tasted strange.")
    builder = PromptBuilder(
        scenario.actor.world,
        room_summary=RoomSummaryProjection(scenario.actor.world),
        recent_context=recent,
    )
    ctx = builder.build(scenario.character, epoch=scenario.actor.epoch)
    assert "Hazel warned the water tasted strange." in ctx.recent
    assert "Recent context:" in render_prompt(ctx)
