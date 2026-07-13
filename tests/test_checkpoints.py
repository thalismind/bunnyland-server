"""Save/reload checkpoint mechanics."""

from __future__ import annotations

import pytest
from conftest import build_scenario, execute_handler

from bunnyland.core import (
    CommandCost,
    ContainmentMode,
    Contains,
    DescriptionComponent,
    HandlerContext,
    IdentityComponent,
    Lane,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.core.events import CommandRejectedEvent
from bunnyland.foundation.checkpoints.mechanics import (
    CheckpointReloadedEvent,
    CheckpointReloadService,
    CheckpointSavedEvent,
    ReloadCheckpointHandler,
    SaveCheckpointComponent,
    SaveCheckpointHandler,
    _PendingReload,
    checkpoint_action_definitions,
)
from bunnyland.foundation.checkpoints.plugin import plugin as checkpoints_plugin
from bunnyland.foundation.core_verbs.plugin import plugin as core_verbs_plugin
from bunnyland.persistence import WorldMeta, load_world
from bunnyland.plugins import PluginError, PluginRegistry, apply_plugins
from bunnyland.plugins.ids import CHECKPOINTS, CORE_VERBS
from bunnyland.prompts import ComponentPromptContext


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
    loaded, loaded_meta = load_world(save_path, registry=PluginRegistry(plugins))
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


async def test_save_checkpoint_creates_default_meta_when_missing(tmp_path):
    scenario = build_scenario()
    save_path = tmp_path / "world.json"
    _install_checkpoints(scenario, save_path)
    scenario.actor.persistence.meta = None
    checkpoint_id = _checkpoint(scenario)

    await scenario.actor.submit(_command(scenario, "save-checkpoint", checkpoint_id))
    await scenario.actor.tick(0)

    assert scenario.actor.persistence.meta is not None
    assert save_path.exists()


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


def test_checkpoint_component_prompt_names_identity_room_and_id():
    scenario = build_scenario()
    world = scenario.actor.world
    checkpoint = world.get_entity(_checkpoint(scenario, "terminal"))
    room = world.get_entity(scenario.room_a)
    room.add_component(SaveCheckpointComponent())
    nameless = spawn_entity(world, [SaveCheckpointComponent()])

    assert checkpoint.get_component(SaveCheckpointComponent).prompt_fragments(
        ComponentPromptContext.for_entity(world, checkpoint)
    ) == ("Checkpoint terminal: save and reload available.",)
    assert room.get_component(SaveCheckpointComponent).prompt_fragments(
        ComponentPromptContext.for_entity(world, room)
    ) == ("Checkpoint Mosslit Burrow: save and reload available.",)
    assert nameless.get_component(SaveCheckpointComponent).prompt_fragments(
        ComponentPromptContext.for_entity(world, nameless)
    ) == (f"Checkpoint {nameless.id}: save and reload available.",)


def test_checkpoint_action_definitions_cover_save_and_reload():
    save_action, reload_action = checkpoint_action_definitions()

    assert save_action.command_type == "save-checkpoint"
    assert save_action.tool_name == "save_checkpoint"
    assert save_action.arguments["target_id"].title == "Checkpoint"
    assert [pattern.text for pattern in save_action.natural_patterns] == [
        "save at {target_id}",
        "save checkpoint {target_id}",
    ]
    assert reload_action.command_type == "reload-checkpoint"
    assert reload_action.tool_name == "reload_checkpoint"
    assert reload_action.arguments["target_id"] is save_action.arguments["target_id"]
    assert reload_action.examples[0].text == "reload from bonfire"


def test_checkpoint_handlers_reject_invalid_missing_and_unreachable_targets(tmp_path):
    scenario = build_scenario()
    _install_checkpoints(scenario, tmp_path / "world.json")
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch, actor=scenario.actor)
    save_handler = SaveCheckpointHandler()
    reload_handler = ReloadCheckpointHandler(CheckpointReloadService())
    checkpoint_id = _checkpoint(scenario)
    remote_checkpoint = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="far scroll", kind="checkpoint"),
            SaveCheckpointComponent(),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), remote_checkpoint.id
    )

    invalid_character = _command(scenario, "save-checkpoint", checkpoint_id)
    object.__setattr__(invalid_character, "character_id", "not-an-id")
    removed_character = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="gone", kind="character")],
    )
    scenario.actor.world.remove(removed_character.id)
    missing_character = _command(scenario, "save-checkpoint", checkpoint_id)
    object.__setattr__(missing_character, "character_id", str(removed_character.id))
    invalid_target = _command(scenario, "save-checkpoint", "not-an-id")
    removed_checkpoint = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="gone checkpoint", kind="checkpoint"),
            SaveCheckpointComponent(),
        ],
    )
    scenario.actor.world.remove(removed_checkpoint.id)
    missing_target = _command(scenario, "save-checkpoint", removed_checkpoint.id)
    unreachable = _command(scenario, "save-checkpoint", remote_checkpoint.id)

    assert execute_handler(save_handler, ctx, invalid_character).reason == "invalid character id"
    assert (
        execute_handler(save_handler, ctx, missing_character).reason == "character does not exist"
    )
    assert execute_handler(save_handler, ctx, invalid_target).reason == "invalid checkpoint id"
    assert execute_handler(save_handler, ctx, missing_target).reason == "checkpoint does not exist"
    assert execute_handler(save_handler, ctx, unreachable).reason == "checkpoint is not reachable"

    no_save_path = execute_handler(
        ReloadCheckpointHandler(CheckpointReloadService()),
        HandlerContext(scenario.actor.world, scenario.actor.epoch, actor=None),
        _command(scenario, "reload-checkpoint", checkpoint_id),
    )
    assert no_save_path.reason == "server was not started with --save"
    assert (
        execute_handler(reload_handler, ctx, missing_target).reason == "checkpoint does not exist"
    )


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


async def test_checkpoint_reload_service_ignores_empty_duplicate_and_failed_reload(
    tmp_path, monkeypatch
):
    scenario = build_scenario()
    save_path = tmp_path / "world.json"
    _install_checkpoints(scenario, save_path)
    checkpoint_id = _checkpoint(scenario)
    service = CheckpointReloadService()
    pending = _PendingReload(str(scenario.character), str(checkpoint_id), str(save_path))

    await service.after_tick(scenario.actor)
    assert service.pending is None

    service.request(pending)
    service.request(_PendingReload("other-character", "other-checkpoint", str(save_path)))
    assert service.pending == pending

    def fail_reload(*args, **kwargs):
        raise RuntimeError("reload failed")

    monkeypatch.setattr("bunnyland.persistence.reload_world", fail_reload)
    await service.after_tick(scenario.actor)

    assert service.pending is None


async def test_checkpoint_save_requires_plugin_on_reload(tmp_path):
    scenario = build_scenario()
    save_path = tmp_path / "world.json"
    _install_checkpoints(scenario, save_path)
    checkpoint_id = _checkpoint(scenario, "terminal")

    await scenario.actor.submit(_command(scenario, "save-checkpoint", checkpoint_id))
    await scenario.actor.tick(0)

    with pytest.raises(PluginError, match="saved world depends on missing plugin"):
        load_world(save_path, registry=PluginRegistry([core_verbs_plugin()]))
