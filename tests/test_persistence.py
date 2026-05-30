"""Tests for world persistence (spec 26): save, reload, autosave, and provenance."""

from __future__ import annotations

import json

from bunnyland.core import WorldActor, container_of
from bunnyland.core.components import IdentityComponent
from bunnyland.core.ecs import contents
from bunnyland.engine import GameLoop
from bunnyland.llm_agents import ControllerDispatch, ScriptedAgent, ToolCall
from bunnyland.mechanics.needs import HungerComponent
from bunnyland.persistence import WorldMeta, load_world, save_world, type_registries
from bunnyland.plugins import apply_plugins, bunnyland_plugins
from bunnyland.prompts.builder import PromptBuilder
from bunnyland.worldgen import StubWorldBuilder, instantiate


async def _build_and_play():
    """A fully wired stub world after a couple of in-place actions (no movement)."""
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    result = await instantiate(actor, StubWorldBuilder().propose("a quiet marsh"))
    # Hazel eats and takes the paper but stays in the burrow.
    agent = ScriptedAgent(
        [
            ToolCall("eat", {"item_id": "three berries"}),
            ToolCall("take", {"item_id": "a scrap of paper"}),
        ]
    )
    dispatch = ControllerDispatch(actor, PromptBuilder(actor.world), agent)
    await GameLoop(actor, dispatch).run(max_ticks=3)
    return actor, result


def _inventory(actor, character_id):
    return sorted(
        actor.world.get_entity(c).get_component(IdentityComponent).name
        for c in contents(actor.world.get_entity(character_id))
    )


async def test_save_reload_preserves_world(tmp_path):
    actor, result = await _build_and_play()
    hazel = result.characters["hazel"]
    before_room = container_of(actor.world.get_entity(hazel))
    before_inventory = _inventory(actor, hazel)
    before_epoch = actor.epoch
    before_hunger = actor.world.get_entity(hazel).get_component(HungerComponent).meter.value

    path = tmp_path / "world.json"
    save_world(actor, path, meta=WorldMeta(seed="a quiet marsh", prompt="p", generator="oneshot"))
    actor2, meta = load_world(path, plugins=bunnyland_plugins())

    # Topology, containment, the clock, and nested value objects all survive.
    assert container_of(actor2.world.get_entity(hazel)) == before_room
    assert _inventory(actor2, hazel) == before_inventory
    assert "a scrap of paper" in before_inventory
    assert actor2.epoch == before_epoch
    hunger = actor2.world.get_entity(hazel).get_component(HungerComponent)
    assert hunger.meter.value == before_hunger  # Meter is a nested value object

    # Provenance is restored.
    assert (meta.seed, meta.prompt, meta.generator) == ("a quiet marsh", "p", "oneshot")
    assert meta.saved_at_epoch == before_epoch


async def test_reloaded_world_keeps_playing(tmp_path):
    actor, result = await _build_and_play()
    hazel = result.characters["hazel"]
    path = tmp_path / "world.json"
    save_world(actor, path, meta=WorldMeta(seed="s"))

    actor2, _meta = load_world(path, plugins=bunnyland_plugins())
    # The controller edge (and its generation) survived, so dispatch can drive Hazel.
    agent = ScriptedAgent([ToolCall("move", {"direction": "north"})])
    dispatch = ControllerDispatch(actor2, PromptBuilder(actor2.world), agent)
    await GameLoop(actor2, dispatch).run(max_ticks=2)

    assert container_of(actor2.world.get_entity(hazel)) == result.rooms["tunnel"]


async def test_save_file_embeds_ecs_and_provenance(tmp_path):
    actor, _result = await _build_and_play()
    path = tmp_path / "world.json"
    save_world(actor, path, meta=WorldMeta(seed="marsh", prompt="p", generator="recursive"))

    data = json.loads(path.read_text())
    # One file holds both the Relics ECS sections and the bunnyland provenance.
    assert {"components", "entities", "relationships", "bunnyland"} <= set(data)
    assert data["bunnyland"]["seed"] == "marsh"
    assert data["bunnyland"]["generator"] == "recursive"


async def test_reload_starts_with_empty_command_queues(tmp_path):
    actor, _result = await _build_and_play()
    path = tmp_path / "world.json"
    save_world(actor, path, meta=WorldMeta())
    actor2, _meta = load_world(path, plugins=bunnyland_plugins())

    # Volatile queues are never persisted (spec 26): a reload resumes with empty queues.
    assert actor2.queues.characters_with_pending() == []
    assert actor2._inbox.empty()


async def test_game_loop_autosaves_every_n_ticks(tmp_path):
    actor = WorldActor()
    apply_plugins(bunnyland_plugins(), actor)
    await instantiate(actor, StubWorldBuilder().propose("seed"))
    path = tmp_path / "auto.json"

    saved_at: list[int] = []

    def autosave(ticks: int) -> None:
        saved_at.append(ticks)
        save_world(actor, path, meta=WorldMeta(seed="seed"))

    dispatch = ControllerDispatch(actor, PromptBuilder(actor.world), ScriptedAgent([]))
    loop = GameLoop(actor, dispatch, autosave=autosave, autosave_every=2)
    await loop.run(max_ticks=5)

    assert saved_at == [2, 4]
    assert path.exists()


def test_type_registries_cover_core_and_plugin_types():
    components, edges = type_registries(bunnyland_plugins())
    assert {"IdentityComponent", "HungerComponent", "RoomComponent"} <= set(components)
    assert {"Contains", "ExitTo", "ControlledBy"} <= set(edges)
