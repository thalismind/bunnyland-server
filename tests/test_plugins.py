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
    DependencyContribution,
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
    DAGGERSIM,
    DRAGONSIM,
    ENVIRONMENT,
    GARDENSIM,
    LIFESIM,
    MCP,
    MECHANISMS,
    MEMORY,
    PERSONA,
    POLICY,
    SOCIAL,
    STORYTELLER,
    VOIDSIM,
    WORLDGEN,
)


def test_builtin_plugins_declared():
    ids = {p.id for p in bunnyland_plugins()}
    assert ids == {
        BARBARIANSIM, COLONYSIM, CORE_VERBS, LIFESIM, MEMORY, WORLDGEN, ENVIRONMENT,
        MECHANISMS, SOCIAL, POLICY, PERSONA, GARDENSIM, DRAGONSIM, DAGGERSIM, MCP,
        VOIDSIM, STORYTELLER,
    }


def test_select_defaults_to_default_enabled():
    plugins = bunnyland_plugins()
    assert len(select(plugins, None)) == 16
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
    assert {"empty", "oneshot", "recursive"} <= set(registry)
    # generators are selected by name and disappear if their plugin is dropped
    without = collect_generators([p for p in bunnyland_plugins() if p.id != WORLDGEN])
    assert "empty" not in without and "oneshot" not in without and "recursive" not in without
    # each sim plugin also contributes its own example world, tied to that plugin
    assert "voidsim-demo" in registry
    assert registry["empty"].uses_seed is False
    assert registry["recursive"].uses_seed is True
    assert registry["voidsim-demo"].uses_seed is False
    without_void = collect_generators([p for p in bunnyland_plugins() if p.id != VOIDSIM])
    assert "voidsim-demo" not in without_void


def test_select_unknown_id_raises():
    with pytest.raises(PluginError):
        select(bunnyland_plugins(), ["nope"])


def test_resolve_order_places_dependencies_first():
    ordered = resolve_order(bunnyland_plugins())
    ids = [p.id for p in ordered]
    assert ids.index(CORE_VERBS) < ids.index(LIFESIM)
    assert ids.index(CORE_VERBS) < ids.index(MEMORY)


def test_missing_dependency_raises():
    orphan = Plugin(
        id="x",
        name="X",
        dependencies=DependencyContribution(requires=("does.not.exist",)),
    )
    with pytest.raises(PluginError):
        resolve_order([orphan])


def test_dependency_cycle_raises():
    a = Plugin(id="a", name="A", dependencies=DependencyContribution(requires=("b",)))
    b = Plugin(id="b", name="B", dependencies=DependencyContribution(requires=("a",)))
    with pytest.raises(PluginError):
        resolve_order([a, b])


def test_missing_recommendation_warns_but_continues(caplog):
    plugin = Plugin(
        id="a",
        name="A",
        dependencies=DependencyContribution(recommends=("missing",)),
    )

    assert resolve_order([plugin]) == [plugin]
    assert "recommends missing" in caplog.text


def test_imported_plugin_ids_are_namespaced_and_selectable_by_short_id(monkeypatch):
    import sys
    from types import ModuleType

    from bunnyland.plugins import load_modules

    module = ModuleType("module_foo")
    module.bunnyland_plugins = lambda: [Plugin(id="bar", name="Bar")]
    monkeypatch.setitem(sys.modules, "module_foo", module)

    plugins = load_modules(["module_foo"])

    assert [p.id for p in plugins] == ["module_foo.bar"]
    assert [p.id for p in select(plugins, ["bar"])] == ["module_foo.bar"]


def test_imported_plugin_dependencies_are_namespaced(monkeypatch):
    import sys
    from types import ModuleType

    from bunnyland.plugins import load_modules

    module = ModuleType("module_foo")
    module.bunnyland_plugins = lambda: [
        Plugin(id="base", name="Base"),
        Plugin(
            id="bar",
            name="Bar",
            dependencies=DependencyContribution(requires=("base",), recommends=("extra",)),
        ),
    ]
    monkeypatch.setitem(sys.modules, "module_foo", module)

    plugins = load_modules(["module_foo"])
    bar = next(plugin for plugin in plugins if plugin.id == "module_foo.bar")

    assert bar.dependencies.requires == ("module_foo.base",)
    assert bar.dependencies.recommends == ("module_foo.extra",)


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


async def test_applying_lifesim_plugin_enables_skill_progression():
    scenario = _bare_scenario()
    apply_plugins(
        [p for p in bunnyland_plugins() if p.id in (CORE_VERBS, LIFESIM)],
        scenario.actor,
    )
    from bunnyland.mechanics.lifesim import SkillSetComponent

    command = build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="practice-skill",
        cost=CommandCost(action=1),
        lane=Lane.WORLD,
        payload={"skill": "cooking", "xp": 100},
    )
    await scenario.actor.submit(command)
    await scenario.actor.tick(3600.0)

    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(SkillSetComponent).levels["cooking"] == 1


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
