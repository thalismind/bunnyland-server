"""Tests for the plugin system: loading, dependency ordering, and application."""

from __future__ import annotations

import pytest
from conftest import build_scenario

from bunnyland.core import (
    CommandCost,
    Lane,
    MemoryProfileComponent,
    WorldActor,
    build_submitted_command,
)
from bunnyland.core.events import NoteTakenEvent
from bunnyland.plugins import (
    EcsContribution,
    Plugin,
    PluginError,
    apply_plugins,
    bunnyland_plugins,
    resolve_order,
    select,
)
from bunnyland.plugins.builtin import (
    BARBARIANSIM,
    COLONYSIM,
    CORE_VERBS,
    ENVIRONMENT,
    LIFESIM,
    MECHANISMS,
    MEMORY,
    PERSONA,
    POLICY,
    SOCIAL,
    WORLDGEN,
)


def test_builtin_plugins_declared():
    ids = {p.id for p in bunnyland_plugins()}
    assert ids == {
        BARBARIANSIM, COLONYSIM, CORE_VERBS, LIFESIM, MEMORY, WORLDGEN, ENVIRONMENT,
        MECHANISMS, SOCIAL, POLICY, PERSONA,
    }


def test_select_defaults_to_default_enabled():
    plugins = bunnyland_plugins()
    assert len(select(plugins, None)) == 11
    assert [p.id for p in select(plugins, [MEMORY])] == [MEMORY]


def test_collect_prompt_fragments_gathers_providers():
    from bunnyland.plugins import collect_prompt_fragments

    providers = collect_prompt_fragments(bunnyland_plugins())
    # needs, environment, and social each contribute one.
    assert len(providers) >= 3
    assert all(callable(p) for p in providers)


def test_worldgen_plugin_contributes_named_generators():
    from bunnyland.worldgen import collect_generators

    registry = collect_generators(bunnyland_plugins())
    assert {"oneshot", "recursive"} <= set(registry)
    # generators are selected by name and disappear if the plugin is dropped
    without = collect_generators([p for p in bunnyland_plugins() if p.id != WORLDGEN])
    assert without == {}


def test_select_unknown_id_raises():
    with pytest.raises(PluginError):
        select(bunnyland_plugins(), ["nope"])


def test_resolve_order_places_dependencies_first():
    ordered = resolve_order(bunnyland_plugins())
    ids = [p.id for p in ordered]
    assert ids.index(CORE_VERBS) < ids.index(LIFESIM)
    assert ids.index(CORE_VERBS) < ids.index(MEMORY)


def test_missing_dependency_raises():
    orphan = Plugin(id="x", name="X", dependencies=("does.not.exist",))
    with pytest.raises(PluginError):
        resolve_order([orphan])


def test_dependency_cycle_raises():
    a = Plugin(id="a", name="A", dependencies=("b",))
    b = Plugin(id="b", name="B", dependencies=("a",))
    with pytest.raises(PluginError):
        resolve_order([a, b])


async def test_applying_core_verbs_enables_move():
    # An actor with no plugins cannot move; applying core_verbs registers the handler.
    scenario = _bare_scenario()
    apply_plugins([p for p in bunnyland_plugins() if p.id == CORE_VERBS], scenario.actor)

    await scenario.actor.submit(_move(scenario))
    await scenario.actor.tick(3600.0)
    assert scenario.character_room() == scenario.room_b


async def test_applying_memory_plugin_enables_notes():
    scenario = _bare_scenario()
    apply_plugins(
        [p for p in bunnyland_plugins() if p.id in (CORE_VERBS, MEMORY)], scenario.actor
    )
    char = scenario.actor.world.get_entity(scenario.character)
    char.add_component(MemoryProfileComponent(vector_collection="c"))

    notes = []
    scenario.actor.bus.subscribe(NoteTakenEvent, notes.append)
    note = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="take-note",
        cost=CommandCost(focus=1),
        lane=Lane.FOCUS,
        payload={"text": "a private thought"},
    )
    await scenario.actor.submit(note)
    await scenario.actor.tick(0.0)
    assert len(notes) == 1


async def test_disabled_plugin_leaves_its_verbs_unhandled():
    # Without the memory plugin, take-note has no handler and is rejected.
    scenario = _bare_scenario()
    apply_plugins([p for p in bunnyland_plugins() if p.id == CORE_VERBS], scenario.actor)
    from bunnyland.core import OnInsufficientPoints
    from bunnyland.core.events import CommandRejectedEvent

    rejects = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejects.append)
    note = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="take-note",
        cost=CommandCost(focus=1),
        lane=Lane.FOCUS,
        on_insufficient_points=OnInsufficientPoints.DENY,
        payload={"text": "x"},
    )
    await scenario.actor.submit(note)
    await scenario.actor.tick(0.0)
    assert any("no handler for take-note" in r.reason for r in rejects)


def test_ecs_systems_can_be_instances_or_classes():
    # apply should accept a system instance as well as a class.
    from bunnyland.mechanics.needs import HungerSystem

    actor = WorldActor()
    plugin = Plugin(id="t", name="T", ecs=EcsContribution(systems=(HungerSystem(),)))
    apply_plugins([plugin], actor)  # must not raise


# -- helpers ----------------------------------------------------------------------------


def _bare_scenario():
    # build_scenario registers MoveHandler already; use a fresh actor with no handlers
    # by clearing the registry so we can prove plugins add them.
    scenario = build_scenario()
    scenario.actor._handlers.clear()
    return scenario


def _move(scenario):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="move",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"direction": "north"},
    )
