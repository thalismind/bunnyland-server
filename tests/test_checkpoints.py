"""Save/reload checkpoint mechanics."""

from __future__ import annotations

import pytest

from conftest import build_scenario

from bunnyland.core import (
    CommandCost,
    ContainmentMode,
    Contains,
    DescriptionComponent,
    IdentityComponent,
    Lane,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.mechanics.checkpoints import (
    CheckpointReloadedEvent,
    CheckpointSavedEvent,
    SaveCheckpointComponent,
)
from bunnyland.persistence import WorldMeta, load_world
from bunnyland.plugins import PluginError, apply_plugins
from bunnyland.plugins.builtin import CHECKPOINTS, CORE_VERBS, checkpoints_plugin, core_verbs_plugin


def _install_checkpoints(scenario, save_path):
    plugins = [core_verbs_plugin(), checkpoints_plugin()]
    apply_plugins(plugins, scenario.actor)
    meta = WorldMeta(
        seed="checkpoint test",
        generator="test",
        plugins=(CORE_VERBS, CHECKPOINTS),
    )
    scenario.actor.configure_persistence(
        save_path=save_path,
        meta=meta,
        plugins=tuple(plugins),
        plugin_context=None,
    )
    return plugins, meta


def _checkpoint(scenario, name: str = "typewriter"):
    checkpoint = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name=name, kind="checkpoint"),
            DescriptionComponent(short=f"a {name} checkpoint"),
            SaveCheckpointComponent(),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), checkpoint.id
    )
    return checkpoint.id


def _command(scenario, command_type: str, target_id, *, command_id: str | None = None):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type=command_type,
        cost=CommandCost(),
        lane=Lane.WORLD,
        payload={"target_id": str(target_id)},
        command_id=command_id,
    )


async def test_save_checkpoint_writes_configured_save(tmp_path):
    scenario = build_scenario()
    save_path = tmp_path / "world.json"
    plugins, _meta = _install_checkpoints(scenario, save_path)
    checkpoint_id = _checkpoint(scenario)
    events: list[CheckpointSavedEvent] = []
    scenario.actor.bus.subscribe(CheckpointSavedEvent, events.append)

    await scenario.actor.submit(_command(scenario, "save-checkpoint", checkpoint_id))
    await scenario.actor.tick(0)

    assert save_path.exists()
    assert [event.checkpoint_id for event in events] == [str(checkpoint_id)]
    loaded, loaded_meta = load_world(save_path, plugins=plugins)
    assert loaded_meta.plugins == (CORE_VERBS, CHECKPOINTS)
    assert loaded.world.has_entity(checkpoint_id)


async def test_save_checkpoint_rejects_without_save_path():
    scenario = build_scenario()
    _install_checkpoints(scenario, None)
    checkpoint_id = _checkpoint(scenario)
    rejections: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejections.append)

    await scenario.actor.submit(_command(scenario, "save-checkpoint", checkpoint_id))
    await scenario.actor.tick(0)

    assert [event.reason for event in rejections] == ["server was not started with --save"]


async def test_save_checkpoint_rejects_non_checkpoint(tmp_path):
    scenario = build_scenario()
    _install_checkpoints(scenario, tmp_path / "world.json")
    prop = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="desk", kind="prop")],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), prop.id
    )
    rejections: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejections.append)

    await scenario.actor.submit(_command(scenario, "save-checkpoint", prop.id))
    await scenario.actor.tick(0)

    assert [event.reason for event in rejections] == ["target is not a checkpoint"]


async def test_reload_checkpoint_restores_saved_world_and_clears_queues(tmp_path):
    scenario = build_scenario()
    save_path = tmp_path / "world.json"
    _install_checkpoints(scenario, save_path)
    checkpoint_id = _checkpoint(scenario, "bonfire")
    reloaded: list[CheckpointReloadedEvent] = []
    scenario.actor.bus.subscribe(CheckpointReloadedEvent, reloaded.append)

    await scenario.actor.submit(_command(scenario, "save-checkpoint", checkpoint_id))
    await scenario.actor.tick(0)

    transient = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="transient rock", kind="prop")],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), transient.id
    )
    queued = _command(scenario, "save-checkpoint", checkpoint_id, command_id="queued-after-reload")

    await scenario.actor.submit(_command(scenario, "reload-checkpoint", checkpoint_id))
    await scenario.actor.submit(queued)
    await scenario.actor.tick(0)

    assert [event.checkpoint_id for event in reloaded] == [str(checkpoint_id)]
    assert scenario.actor.world.has_entity(checkpoint_id)
    assert not scenario.actor.world.has_entity(transient.id)
    assert scenario.actor.pending_submissions() == []
    assert not scenario.actor.queues.has_pending(str(scenario.character))


async def test_reload_checkpoint_rejects_missing_save_file(tmp_path):
    scenario = build_scenario()
    _install_checkpoints(scenario, tmp_path / "missing.json")
    checkpoint_id = _checkpoint(scenario, "red scroll")
    rejections: list[CommandRejectedEvent] = []
    scenario.actor.bus.subscribe(CommandRejectedEvent, rejections.append)

    await scenario.actor.submit(_command(scenario, "reload-checkpoint", checkpoint_id))
    await scenario.actor.tick(0)

    assert [event.reason for event in rejections] == ["save file does not exist"]


async def test_checkpoint_save_requires_plugin_on_reload(tmp_path):
    scenario = build_scenario()
    save_path = tmp_path / "world.json"
    _install_checkpoints(scenario, save_path)
    checkpoint_id = _checkpoint(scenario, "terminal")

    await scenario.actor.submit(_command(scenario, "save-checkpoint", checkpoint_id))
    await scenario.actor.tick(0)

    with pytest.raises(PluginError, match="saved world depends on missing plugin"):
        load_world(save_path, plugins=[core_verbs_plugin()])
