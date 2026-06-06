"""CLI plugin selection and metadata behavior."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

from bunnyland.cli import assign_discord_controller, configure_memory_backend, main, select_plugins
from bunnyland.core import (
    CharacterComponent,
    ControlledBy,
    DiscordControllerComponent,
    IdentityComponent,
    SuspendedComponent,
    WorldActor,
    spawn_entity,
)
from bunnyland.discord.claim import discord_controlled_character, list_character_names
from bunnyland.mechanics.lifesim import LifeStageComponent
from bunnyland.persistence import WorldMeta, load_world, save_world
from bunnyland.plugins import DependencyContribution, Plugin, PluginError, bunnyland_plugins
from bunnyland.plugins.builtin import (
    BARBARIANSIM,
    COLONYSIM,
    CORE_VERBS,
    DRAGONSIM,
    GARDENSIM,
    LIFESIM,
    NUKESIM,
    VOIDSIM,
    WORLDGEN,
)


def _install_module(monkeypatch, name: str, plugins: list[Plugin]) -> None:
    module = ModuleType(name)
    module.bunnyland_plugins = lambda: plugins
    monkeypatch.setitem(sys.modules, name, module)


def test_select_plugins_records_imported_module_namespace(monkeypatch):
    _install_module(monkeypatch, "module_foo", [Plugin(id="bar", name="Bar")])

    selected = select_plugins(["module_foo"], ["bar"])

    assert [plugin.id for plugin in selected] == ["module_foo.bar"]


@pytest.mark.parametrize(
    ("pack", "expected"),
    [
        ("peaceful", {CORE_VERBS, WORLDGEN, LIFESIM, COLONYSIM, GARDENSIM}),
        ("fantastic", {CORE_VERBS, WORLDGEN, LIFESIM, BARBARIANSIM, DRAGONSIM}),
        ("futuristic", {CORE_VERBS, WORLDGEN, LIFESIM, NUKESIM, VOIDSIM}),
    ],
)
def test_select_plugins_expands_starter_pack(pack, expected):
    selected = select_plugins([], None, starter_pack=pack)

    assert {plugin.id for plugin in selected} == expected


def test_select_plugins_combines_starter_pack_with_explicit_plugins():
    selected = select_plugins([], [CORE_VERBS], starter_pack="peaceful")

    assert [plugin.id for plugin in selected] == [
        CORE_VERBS,
        WORLDGEN,
        LIFESIM,
        COLONYSIM,
        GARDENSIM,
    ]


def test_unknown_starter_pack_raises_plugin_error():
    with pytest.raises(PluginError, match="unknown starter pack"):
        select_plugins([], None, starter_pack="cozy")


def test_cli_starter_pack_records_loaded_plugins(tmp_path):
    path = tmp_path / "world.json"

    result = main(
        [
            "serve",
            "--starter-pack",
            "peaceful",
            "--generator",
            "empty",
            "--ticks",
            "1",
            "--save",
            str(path),
        ]
    )

    assert result == 0
    _actor, meta = load_world(path)
    assert meta.plugins == (CORE_VERBS, WORLDGEN, LIFESIM, COLONYSIM, GARDENSIM)


def test_missing_required_plugin_logs_error_and_exits(monkeypatch, caplog):
    _install_module(
        monkeypatch,
        "module_foo",
        [
            Plugin(
                id="bar",
                name="Bar",
                dependencies=DependencyContribution(requires=("missing",)),
            )
        ],
    )

    with pytest.raises(SystemExit) as exc:
        main(["serve", "--import", "module_foo", "--plugin", "bar"])

    assert exc.value.code == 2
    assert "plugin loading failed" in caplog.text
    assert "module_foo.missing" in caplog.text


def test_cli_discord_requires_token(monkeypatch, tmp_path):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit, match="--discord needs DISCORD_TOKEN"):
        main(["serve", "--discord", "--ticks", "1"])


def test_assign_discord_controller_claims_suspended_character():
    actor = WorldActor()
    character = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )

    claimed = assign_discord_controller(
        actor, discord_user_id=123, default_channel_id=456, character_name="Juniper"
    )

    assert claimed == "Juniper"
    assert not character.has_component(SuspendedComponent)
    controller_id = character.get_relationships(ControlledBy)[0][1]
    controller = actor.world.get_entity(controller_id)
    discord = controller.get_component(DiscordControllerComponent)
    assert discord.discord_user_id == 123
    assert discord.default_channel_id == 456
    assert discord_controlled_character(actor, 123) == (character.id, controller_id, 0)
    assert list_character_names(actor) == ["Juniper"]


def test_assign_discord_controller_accepts_unique_prefix():
    actor = WorldActor()
    character = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Thistle the Innkeeper", kind="character"),
            CharacterComponent(species="bunny"),
        ],
    )

    claimed = assign_discord_controller(actor, discord_user_id=123, character_name="Thistle")

    assert claimed == "Thistle the Innkeeper"
    assert discord_controlled_character(actor, 123)[0] == character.id


def test_assign_discord_controller_rejects_child_character_by_default():
    actor = WorldActor()
    child = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Clover", kind="character"),
            CharacterComponent(species="bunny"),
            LifeStageComponent(stage="child"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )

    with pytest.raises(RuntimeError, match="child character"):
        assign_discord_controller(actor, discord_user_id=123, character_name="Clover")

    assert child.has_component(SuspendedComponent)
    assert discord_controlled_character(actor, 123) is None


def test_assign_discord_controller_allows_child_character_when_enabled():
    actor = WorldActor()
    child = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Clover", kind="character"),
            CharacterComponent(species="bunny"),
            LifeStageComponent(stage="child"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )

    claimed = assign_discord_controller(
        actor,
        discord_user_id=123,
        character_name="Clover",
        allow_child_claims=True,
    )

    assert claimed == "Clover"
    assert not child.has_component(SuspendedComponent)
    assert discord_controlled_character(actor, 123)[0] == child.id


def test_assign_discord_controller_skips_child_character_for_default_claim():
    actor = WorldActor()
    child = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Clover", kind="character"),
            CharacterComponent(species="bunny"),
            LifeStageComponent(stage="child"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )
    adult = spawn_entity(
        actor.world,
        [
            IdentityComponent(name="Juniper", kind="character"),
            CharacterComponent(species="bunny"),
            LifeStageComponent(stage="adult"),
            SuspendedComponent(reason="unclaimed"),
        ],
    )

    claimed = assign_discord_controller(actor, discord_user_id=123)

    assert claimed == "Juniper"
    assert child.has_component(SuspendedComponent)
    assert not adult.has_component(SuspendedComponent)
    assert discord_controlled_character(actor, 123)[0] == adult.id


def test_world_meta_can_record_loaded_plugin_ids():
    meta = WorldMeta(plugins=(CORE_VERBS, "module_foo.bar"))

    assert meta.plugins == (CORE_VERBS, "module_foo.bar")


def test_configure_memory_backend_can_install_chroma(monkeypatch, tmp_path):
    calls = []

    class FakeChroma:
        @staticmethod
        def PersistentClient(path: str):
            calls.append(path)
            return object()

    monkeypatch.setitem(sys.modules, "chromadb", FakeChroma)
    actor = WorldActor()

    configure_memory_backend(actor, "chroma", str(tmp_path / "memory"))

    assert calls == [str(tmp_path / "memory")]
    assert "take-note" in actor.available_command_types()
    assert "remember" in actor.available_command_types()
    assert "forget" in actor.available_command_types()


def test_cli_save_records_namespaced_imported_plugin(monkeypatch, tmp_path):
    _install_module(monkeypatch, "module_foo", [Plugin(id="bar", name="Bar")])
    path = tmp_path / "world.json"

    result = main(
        [
            "serve",
            "--import",
            "module_foo",
            "--plugin",
            WORLDGEN,
            "--plugin",
            "bar",
            "--ticks",
            "1",
            "--save",
            str(path),
        ]
    )

    assert result == 0
    _actor, meta = load_world(path)
    assert meta.plugins == (WORLDGEN, "module_foo.bar")


def test_load_rejects_saved_plugin_that_is_no_longer_available(tmp_path):
    path = tmp_path / "world.json"
    save_world(
        WorldActor(),
        path,
        meta=WorldMeta(plugins=(WORLDGEN, "module_foo.bar")),
    )
    plugins = [plugin for plugin in bunnyland_plugins() if plugin.id == WORLDGEN]

    with pytest.raises(PluginError, match="module_foo.bar"):
        load_world(path, plugins=plugins)


def test_cli_load_missing_saved_plugin_logs_error_and_exits(tmp_path, caplog):
    path = tmp_path / "world.json"
    save_world(
        WorldActor(),
        path,
        meta=WorldMeta(plugins=(WORLDGEN, "module_foo.bar")),
    )

    with pytest.raises(SystemExit) as exc:
        main(["serve", "--load", str(path), "--plugin", WORLDGEN, "--ticks", "1"])

    assert exc.value.code == 2
    assert "plugin loading failed" in caplog.text
    assert "module_foo.bar" in caplog.text
