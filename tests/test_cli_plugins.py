"""CLI plugin selection and metadata behavior."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from argparse import Namespace

import pytest
from conftest import install_plugin_module

import bunnyland.cli as cli
from bunnyland.claims import ClaimSecretRegistry
from bunnyland.cli import (
    assign_discord_controller,
    build_actor,
    configure_memory_backend,
    main,
    select_plugins,
)
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
    MCP,
    NUKESIM,
    VOIDSIM,
    WORLDGEN,
)
from bunnyland.prompts.builder import PromptBuilder


def test_cli_imports_in_fresh_interpreter():
    result = subprocess.run(
        [sys.executable, "-c", "from bunnyland.cli import main; print('ok')"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "ok"


def _serve_args(**overrides):
    values = {
        "admin_token": None,
        "api_host": "127.0.0.1",
        "api_port": None,
        "autosave_every": 0,
        "character_chat": False,
        "character_model": None,
        "claim_timeout_controller": None,
        "claim_timeout_seconds": 0,
        "controller_definitions": None,
        "discord": False,
        "discord_allowed_channel_id": [],
        "discord_allowed_dm_user_id": [],
        "discord_allowed_guild_id": [],
        "discord_allow_child_claims": False,
        "discord_channel_id": None,
        "discord_character": None,
        "discord_playtest": None,
        "discord_user_id": None,
        "generator": "empty",
        "lifesim_natural_aging": None,
        "llm": False,
        "llm_provider": "ollama",
        "load": None,
        "load_paused": False,
        "max_rooms": 6,
        "mcp": False,
        "memory_backend": "in-memory",
        "memory_path": None,
        "module": [],
        "ollama_model": None,
        "plugin": None,
        "save": None,
        "seed": "a quiet marsh",
        "starter_pack": None,
        "tick_seconds": 1.0,
        "ticks": 1,
        "time_scale": 3600.0,
        "worldgen_model": None,
        "worldgen_provider": None,
    }
    values.update(overrides)
    return Namespace(**values)


def test_select_plugins_records_imported_module_namespace(monkeypatch):
    install_plugin_module(monkeypatch, "module_foo", [Plugin(id="bar", name="Bar")])

    selected = select_plugins(["module_foo"], ["bar"])

    assert [plugin.id for plugin in selected] == ["module_foo.bar"]


@pytest.mark.parametrize(
    ("pack", "expected"),
    [
        ("peaceful", {CORE_VERBS, WORLDGEN, LIFESIM, COLONYSIM, GARDENSIM}),
        (
            "fantastic",
            {
                CORE_VERBS,
                WORLDGEN,
                LIFESIM,
                COLONYSIM,
                GARDENSIM,
                BARBARIANSIM,
                DRAGONSIM,
            },
        ),
        (
            "futuristic",
            {
                CORE_VERBS,
                WORLDGEN,
                LIFESIM,
                COLONYSIM,
                GARDENSIM,
                BARBARIANSIM,
                NUKESIM,
                VOIDSIM,
            },
        ),
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


def test_select_plugins_adds_extra_plugin_without_disabling_defaults():
    selected = select_plugins([], None, extra_enabled_ids=(MCP,))
    ids = {plugin.id for plugin in selected}

    assert MCP in ids
    assert WORLDGEN in ids


def test_select_plugins_ignores_extra_plugin_already_enabled_by_default():
    selected = select_plugins([], None, extra_enabled_ids=(WORLDGEN,))

    assert [plugin.id for plugin in selected].count(WORLDGEN) == 1


def test_select_plugins_adds_extra_plugin_to_explicit_selection():
    selected = select_plugins([], [WORLDGEN], extra_enabled_ids=(MCP,))

    assert [plugin.id for plugin in selected] == [WORLDGEN, MCP]


def test_build_actor_applies_requested_plugins():
    actor, applied = build_actor([], [WORLDGEN])

    assert actor is not None
    assert [plugin.id for plugin in applied] == [WORLDGEN]


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


def test_cli_autosaves_during_game_loop(tmp_path, capsys):
    path = tmp_path / "autosave-world.json"

    result = main(
        [
            "serve",
            "--generator",
            "empty",
            "--ticks",
            "1",
            "--save",
            str(path),
            "--autosave-every",
            "1",
        ]
    )

    assert result == 0
    assert "[autosave] tick 1" in capsys.readouterr().out
    assert path.exists()


def test_cli_starter_pack_can_come_from_environment(monkeypatch, tmp_path):
    path = tmp_path / "world.json"
    monkeypatch.setenv("BUNNYLAND_STARTER_PACK", "futuristic")

    result = main(
        [
            "serve",
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
    assert meta.plugins == (
        CORE_VERBS,
        WORLDGEN,
        LIFESIM,
        COLONYSIM,
        GARDENSIM,
        BARBARIANSIM,
        VOIDSIM,
        NUKESIM,
    )


def test_missing_required_plugin_logs_error_and_exits(monkeypatch, caplog):
    install_plugin_module(
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


def test_cli_discord_starts_bot_with_filters_and_closes(monkeypatch, tmp_path):
    import bunnyland.discord as discord

    calls = {}

    class FakeDiscordBot:
        def __init__(self, actor, **kwargs):
            calls["actor"] = actor
            calls["kwargs"] = kwargs
            calls["closed"] = False

        async def start(self):
            while not calls["closed"]:
                await asyncio.sleep(0)

        async def close(self):
            calls["closed"] = True

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DISCORD_TOKEN", "discord-token")
    monkeypatch.setattr(discord, "DiscordBot", FakeDiscordBot)

    result = main(
        [
            "serve",
            "--discord",
            "--discord-allowed-guild-id",
            "11",
            "--discord-allowed-channel-id",
            "22",
            "--discord-allowed-dm-user-id",
            "33",
            "--generator",
            "empty",
            "--ticks",
            "1",
            "--claim-timeout-seconds",
            "0",
        ]
    )

    filters = calls["kwargs"]["message_filters"]
    assert result == 0
    assert calls["closed"] is True
    assert calls["kwargs"]["token"] == "discord-token"
    assert calls["kwargs"]["allow_child_claims"] is False
    assert filters.guild_ids == (11,)
    assert filters.channel_ids == (22,)
    assert filters.dm_user_ids == (33,)


def test_cli_discord_startup_claim_assigns_configured_user(monkeypatch, tmp_path, capsys):
    import bunnyland.discord as discord

    calls = {}

    class FakeDiscordBot:
        def __init__(self, actor, **kwargs):
            calls["bot_actor"] = actor
            calls["bot_kwargs"] = kwargs
            calls["closed"] = False

        async def start(self):
            while not calls["closed"]:
                await asyncio.sleep(0)

        async def close(self):
            calls["closed"] = True

    def fake_assign_discord_controller(actor, **kwargs):
        calls["claim_actor"] = actor
        calls["claim_kwargs"] = kwargs
        return "Juniper"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DISCORD_TOKEN", "discord-token")
    monkeypatch.setattr(discord, "DiscordBot", FakeDiscordBot)
    monkeypatch.setattr(cli, "assign_discord_controller", fake_assign_discord_controller)

    result = main(
        [
            "serve",
            "--discord",
            "--discord-user-id",
            "123",
            "--discord-channel-id",
            "456",
            "--discord-character",
            "Juniper",
            "--discord-allow-child-claims",
            "--generator",
            "empty",
            "--ticks",
            "1",
            "--claim-timeout-seconds",
            "0",
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert calls["claim_actor"] is calls["bot_actor"]
    claim_secrets = calls["claim_kwargs"].pop("claim_secrets")
    assert isinstance(claim_secrets, ClaimSecretRegistry)
    assert calls["bot_kwargs"]["claim_secrets"] is claim_secrets
    assert calls["claim_kwargs"] == {
        "discord_user_id": 123,
        "default_channel_id": 456,
        "character_name": "Juniper",
        "allow_child_claims": True,
    }
    assert calls["closed"] is True
    assert "Assigned Discord user 123 to 'Juniper'." in output


def test_cli_rejects_incompatible_discord_playtest_modes(tmp_path):
    spec = tmp_path / "playtest.json"
    spec.write_text("{}")

    with pytest.raises(SystemExit, match="do not combine it with --discord"):
        main(["serve", "--discord", "--discord-playtest", str(spec), "--ticks", "1"])

    with pytest.raises(SystemExit, match="cannot be combined with --api-port yet"):
        main(["serve", "--discord-playtest", str(spec), "--api-port", "8080", "--ticks", "1"])


def test_cli_mcp_requires_api_port():
    with pytest.raises(SystemExit, match="--mcp mounts on the HTTP API and needs --api-port"):
        main(["serve", "--mcp", "--ticks", "1"])


def test_cli_mcp_runs_api_with_admin_token(monkeypatch, tmp_path):
    import bunnyland.server.runtime as runtime

    calls = {}

    async def fake_run_loop_with_api(loop, actor, meta, **kwargs):
        calls["loop"] = loop
        calls["actor"] = actor
        calls["meta"] = meta
        calls["kwargs"] = kwargs
        return 4

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runtime, "run_loop_with_api", fake_run_loop_with_api)

    result = main(
        [
            "serve",
            "--mcp",
            "--admin-token",
            "admin-token",
            "--api-port",
            "9876",
            "--generator",
            "empty",
            "--ticks",
            "4",
            "--claim-timeout-seconds",
            "0",
        ]
    )

    assert result == 0
    assert calls["kwargs"]["host"] == "127.0.0.1"
    assert calls["kwargs"]["port"] == 9876
    assert calls["kwargs"]["admin_token"] == "admin-token"
    assert calls["kwargs"]["max_ticks"] == 4
    assert MCP in {plugin.id for plugin in calls["kwargs"]["plugins"]}


def test_cli_api_runtime_error_exits(monkeypatch, tmp_path):
    import bunnyland.server.runtime as runtime

    async def fake_run_loop_with_api(*args, **kwargs):
        raise RuntimeError("server unavailable")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runtime, "run_loop_with_api", fake_run_loop_with_api)

    with pytest.raises(SystemExit, match="server unavailable"):
        main(
            [
                "serve",
                "--mcp",
                "--api-port",
                "9876",
                "--generator",
                "empty",
                "--ticks",
                "1",
                "--claim-timeout-seconds",
                "0",
            ]
        )


def test_cli_discord_playtest_loads_runs_and_reports(monkeypatch, tmp_path, capsys):
    import bunnyland.discord.playtest as playtest

    spec_path = tmp_path / "playtest.json"
    spec_path.write_text("{}")
    calls = {}

    class FakePlaytest:
        def resolved_ticks(self, max_ticks):
            calls["max_ticks"] = max_ticks
            return 7

    class FakeResult:
        ticks = 5
        inputs = ("input",)
        messages = ("first", "second")

    def fake_load_discord_playtest(path):
        calls["path"] = path
        return FakePlaytest()

    async def fake_run_discord_playtest(loop, spec, *, max_ticks):
        calls["loop"] = loop
        calls["spec"] = spec
        calls["run_max_ticks"] = max_ticks
        return FakeResult()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(playtest, "load_discord_playtest", fake_load_discord_playtest)
    monkeypatch.setattr(playtest, "run_discord_playtest", fake_run_discord_playtest)

    result = main(
        [
            "serve",
            "--discord-playtest",
            str(spec_path),
            "--generator",
            "empty",
            "--ticks",
            "5",
            "--claim-timeout-seconds",
            "0",
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert calls["path"] == str(spec_path)
    assert calls["max_ticks"] == 5
    assert calls["run_max_ticks"] == 5
    assert calls["spec"].__class__ is FakePlaytest
    assert "Running game loop (7 ticks)..." in output
    assert "Discord playtest passed: 1 input(s), 2 message(s)." in output


def test_cli_rejects_unknown_generator():
    with pytest.raises(SystemExit, match="unknown generator 'missing'"):
        main(["serve", "--generator", "missing", "--ticks", "1"])


def test_cli_llm_credential_validation(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OLLAMA_CLOUD_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(SystemExit, match="--llm-provider ollama needs OLLAMA_CLOUD_API_KEY"):
        main(["serve", "--llm", "--generator", "empty", "--ticks", "1"])

    with pytest.raises(SystemExit, match="--llm-provider openrouter needs OPENROUTER_API_KEY"):
        main(
            [
                "serve",
                "--llm",
                "--llm-provider",
                "openrouter",
                "--generator",
                "empty",
                "--ticks",
                "1",
            ]
        )

    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    result = main(
        [
            "serve",
            "--llm",
            "--llm-provider",
            "openrouter",
            "--generator",
            "empty",
            "--ticks",
            "1",
        ]
    )

    assert result == 0

    with pytest.raises(SystemExit, match="--worldgen-provider ollama needs OLLAMA_CLOUD_API_KEY"):
        main(
            [
                "serve",
                "--llm",
                "--llm-provider",
                "openrouter",
                "--worldgen-provider",
                "ollama",
                "--generator",
                "empty",
                "--ticks",
                "1",
            ]
        )

    monkeypatch.setenv("OLLAMA_CLOUD_API_KEY", "ollama-key")
    result = main(
        [
            "serve",
            "--llm",
            "--llm-provider",
            "openrouter",
            "--worldgen-provider",
            "ollama",
            "--generator",
            "empty",
            "--ticks",
            "1",
        ]
    )

    assert result == 0

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="--worldgen-provider openrouter needs OPENROUTER_API_KEY"):
        main(
            [
                "serve",
                "--llm",
                "--worldgen-provider",
                "openrouter",
                "--generator",
                "empty",
                "--ticks",
                "1",
            ]
        )


def test_cli_env_parsers_and_dotenv(monkeypatch, tmp_path):
    monkeypatch.delenv("BUNNYLAND_FLAG", raising=False)
    monkeypatch.delenv("BUNNYLAND_COUNT", raising=False)
    assert cli._env_bool("BUNNYLAND_FLAG") is None
    assert cli._env_int("BUNNYLAND_COUNT") is None

    monkeypatch.setenv("BUNNYLAND_FLAG", " yes ")
    monkeypatch.setenv("BUNNYLAND_COUNT", " 42 ")
    assert cli._env_bool("BUNNYLAND_FLAG") is True
    assert cli._env_int("BUNNYLAND_COUNT") == 42

    monkeypatch.setenv("BUNNYLAND_FLAG", "off")
    assert cli._env_bool("BUNNYLAND_FLAG") is False

    monkeypatch.setenv("BUNNYLAND_FLAG", "maybe")
    with pytest.raises(ValueError, match="BUNNYLAND_FLAG must be one of"):
        cli._env_bool("BUNNYLAND_FLAG")

    monkeypatch.setenv("BUNNYLAND_FROM_ENV", "existing")
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        """
# comment
BUNNYLAND_FROM_ENV=ignored
BUNNYLAND_NEW_VALUE='loaded'
bad line
""".lstrip()
    )
    cli.load_dotenv(dotenv)
    assert cli.os.environ["BUNNYLAND_FROM_ENV"] == "existing"
    assert cli.os.environ["BUNNYLAND_NEW_VALUE"] == "loaded"


def test_cli_serve_helper_models_credentials_and_env_errors(monkeypatch):
    args = _serve_args(
        character_model="character-model",
        lifesim_natural_aging=True,
        ollama_model="shared-model",
        worldgen_model="world-model",
    )

    assert cli._lifesim_natural_aging_setting(args) is True
    assert cli._serve_models(args) == cli.ServeModels(
        worldgen_model="world-model",
        character_model="character-model",
    )
    assert cli._serve_credentials(args).worldgen_provider == "ollama"

    monkeypatch.setenv("BUNNYLAND_LIFESIM_NATURAL_AGING", "maybe")
    with pytest.raises(SystemExit, match="BUNNYLAND_LIFESIM_NATURAL_AGING must be one of"):
        cli._lifesim_natural_aging_setting(_serve_args())


def test_cli_serve_credentials_reads_discord_token(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "discord-token")

    credentials = cli._serve_credentials(_serve_args(discord=True))

    assert credentials.discord_token == "discord-token"


def test_cli_character_chat_requires_api_port():
    with pytest.raises(SystemExit, match="--character-chat mounts on the HTTP API"):
        cli._validate_serve_args(_serve_args(character_chat=True, api_port=None))


def test_cli_build_character_chat_service_constructs_opt_in_service(monkeypatch, scenario):
    built = {}

    class DummyAgent:
        pass

    def fake_provider_agent(args, credentials, models):
        built["provider_args"] = (args, credentials, models)
        return DummyAgent()

    monkeypatch.setattr(cli, "_build_provider_agent", fake_provider_agent)
    service = cli._build_character_chat_service(
        _serve_args(character_chat=True),
        scenario.actor,
        PromptBuilder(scenario.actor.world),
        cli.ServeCredentials(worldgen_provider="ollama"),
        cli.ServeModels(worldgen_model="world", character_model="character"),
    )

    assert service is not None
    assert isinstance(service.agent, DummyAgent)
    assert built["provider_args"][0].character_chat is True


def test_cli_chat_command_forwards_options(monkeypatch):
    import bunnyland.chat as chat

    calls = {}

    def fake_chat_main(argv):
        calls["argv"] = argv
        return 23

    monkeypatch.setattr(chat, "main", fake_chat_main)

    result = main(["chat", "--server", "http://localhost:8765", "--character", "Juniper"])

    assert result == 23
    assert calls["argv"] == ["--server", "http://localhost:8765", "--character", "Juniper"]


def test_cli_chat_command_omits_blank_character(monkeypatch):
    import bunnyland.chat as chat

    calls = {}

    def fake_chat_main(argv):
        calls["argv"] = argv
        return 24

    monkeypatch.setattr(chat, "main", fake_chat_main)

    result = main(["chat", "--server", "http://localhost:8765"])

    assert result == 24
    assert calls["argv"] == ["--server", "http://localhost:8765"]


def test_cli_tui_command_forwards_remote_options(monkeypatch):
    import bunnyland.tui as tui

    calls = {}

    def fake_tui_main(argv):
        calls["argv"] = argv
        return 17

    monkeypatch.setattr(tui, "main", fake_tui_main)

    result = main(
        [
            "tui",
            "--server",
            "http://localhost:8765",
            "--claim-fallback",
            "llm",
            "--claim-timeout-minutes",
            "12",
            "--no-icons",
        ]
    )

    assert result == 17
    assert calls["argv"] == [
        "--server",
        "http://localhost:8765",
        "--claim-fallback",
        "llm",
        "--claim-timeout-minutes",
        "12",
        "--no-icons",
    ]


def test_cli_tui_command_forwards_local_options(monkeypatch):
    import bunnyland.tui as tui

    calls = {}

    def fake_tui_main(argv):
        calls["argv"] = argv
        return 0

    monkeypatch.setattr(tui, "main", fake_tui_main)

    result = main(["tui", "--seed", "misty den", "--generator", "empty"])

    assert result == 0
    assert calls["argv"] == ["--seed", "misty den", "--generator", "empty"]


def test_cli_without_command_prints_help(capsys):
    result = main([])

    output = capsys.readouterr().out
    assert result == 0
    assert "usage: bunnyland" in output


def test_cli_verbose_configures_logging_before_serving(monkeypatch):
    calls = {}

    class FakeLogger:
        def setLevel(self, level):
            calls["httpx_level"] = level

    def fake_run(coro):
        calls["coroutine_name"] = coro.cr_code.co_name
        coro.close()

    def fake_basic_config(**kwargs):
        calls["basic_config"] = kwargs

    original_get_logger = cli.logging.getLogger

    def fake_get_logger(name=None):
        if name is None:
            return original_get_logger()
        calls["logger_name"] = name
        return FakeLogger()

    monkeypatch.setattr(cli.asyncio, "run", fake_run)
    monkeypatch.setattr(cli.logging, "basicConfig", fake_basic_config)
    monkeypatch.setattr(cli.logging, "getLogger", fake_get_logger)

    result = main(["serve", "--verbose"])

    assert result == 0
    assert calls["basic_config"] == {
        "level": cli.logging.INFO,
        "format": "%(name)s %(message)s",
    }
    assert calls["logger_name"] == "httpx"
    assert calls["httpx_level"] == cli.logging.WARNING
    assert calls["coroutine_name"] == "_serve"


def test_configure_memory_backend_rejects_unknown_backend():
    with pytest.raises(ValueError, match="unknown memory backend 'disk'"):
        configure_memory_backend(WorldActor(), "disk")


def test_resolve_memory_path_derives_chroma_path_from_save(tmp_path):
    save_path = tmp_path / "worlds" / "main.json"

    resolved = cli._resolve_memory_path(
        _serve_args(memory_backend="chroma", save=str(save_path))
    )

    assert resolved == str(tmp_path / "worlds" / "main.memory" / "chroma")


def test_resolve_memory_path_prefers_explicit_memory_path(tmp_path):
    save_path = tmp_path / "worlds" / "main.json"
    memory_path = tmp_path / "custom-memory"

    resolved = cli._resolve_memory_path(
        _serve_args(
            memory_backend="chroma",
            memory_path=str(memory_path),
            save=str(save_path),
        )
    )

    assert resolved == str(memory_path)


def test_resolve_memory_path_keeps_chroma_ephemeral_without_save():
    assert cli._resolve_memory_path(_serve_args(memory_backend="chroma")) is None


def test_resolve_memory_path_derives_json_file_from_save(tmp_path):
    save_path = tmp_path / "worlds" / "main.json"

    resolved = cli._resolve_memory_path(
        _serve_args(memory_backend="json", save=str(save_path))
    )

    assert resolved == str(tmp_path / "worlds" / "main.memory.json")


def test_resolve_memory_path_keeps_json_unset_without_save():
    assert cli._resolve_memory_path(_serve_args(memory_backend="json")) is None


def test_configure_memory_backend_installs_json_store(tmp_path):
    actor = WorldActor()
    path = tmp_path / "world.memory.json"

    configure_memory_backend(actor, "json", str(path))

    actor.memory_store.add("juniper", text="remembered")
    assert path.exists()
    assert "take-note" in actor.available_command_types()


def test_configure_memory_backend_json_requires_path():
    with pytest.raises(RuntimeError, match="json memory backend requires"):
        configure_memory_backend(WorldActor(), "json")


async def test_run_with_optional_discord_returns_runtime_and_closes_bot():
    class FakeBot:
        def __init__(self) -> None:
            self.closed = False

        async def start(self):
            while not self.closed:
                await asyncio.sleep(0)

        async def close(self):
            self.closed = True

    bot = FakeBot()
    loop = type("Loop", (), {"stop": lambda self: None})()

    result = await cli._run_with_optional_discord(asyncio.sleep(0, result=7), loop, bot)

    assert result == 7
    assert bot.closed is True


async def test_run_with_optional_discord_stops_loop_when_bot_exits():
    class FakeLoop:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    class FakeBot:
        async def start(self):
            return None

        async def close(self):
            raise AssertionError("close is only used when runtime finishes first")

    loop = FakeLoop()

    with pytest.raises(RuntimeError, match="Discord bot stopped unexpectedly"):
        await cli._run_with_optional_discord(asyncio.sleep(60), loop, FakeBot())

    assert loop.stopped is True


async def test_run_with_optional_discord_wraps_bot_exception():
    class FakeLoop:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    class FakeBot:
        async def start(self):
            raise ValueError("discord failed")

        async def close(self):
            raise AssertionError("close is only used when runtime finishes first")

    loop = FakeLoop()

    with pytest.raises(RuntimeError, match="Discord bot stopped unexpectedly") as exc:
        await cli._run_with_optional_discord(asyncio.sleep(60), loop, FakeBot())

    assert isinstance(exc.value.__cause__, ValueError)
    assert loop.stopped is True


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


def test_configure_actor_backends_applies_lifesim_and_reports_memory_backend(
    monkeypatch,
    capsys,
    tmp_path,
):
    calls = {}

    def fake_configure_lifesim_aging(actor, *, natural_aging):
        calls["lifesim"] = (actor, natural_aging)

    def fake_configure_memory_backend(actor, backend, path):
        calls["memory"] = (actor, backend, path)

    actor = WorldActor()
    monkeypatch.setattr(cli, "configure_lifesim_aging", fake_configure_lifesim_aging)
    monkeypatch.setattr(cli, "configure_memory_backend", fake_configure_memory_backend)

    save_path = tmp_path / "worlds" / "main.json"
    cli._configure_actor_backends(
        actor, _serve_args(memory_backend="chroma", save=str(save_path)), True
    )

    assert calls["lifesim"] == (actor, True)
    expected_memory_path = str(tmp_path / "worlds" / "main.memory" / "chroma")
    assert calls["memory"] == (actor, "chroma", expected_memory_path)
    assert f"Using 'chroma' memory backend at {expected_memory_path}." in capsys.readouterr().out


def test_configure_actor_backends_converts_memory_runtime_errors(monkeypatch):
    def fake_configure_memory_backend(actor, backend, path):
        del actor, backend, path
        raise RuntimeError("memory unavailable")

    monkeypatch.setattr(cli, "configure_memory_backend", fake_configure_memory_backend)

    with pytest.raises(SystemExit, match="memory unavailable"):
        cli._configure_actor_backends(WorldActor(), _serve_args(), None)


def test_build_serve_agent_constructs_enabled_providers(monkeypatch):
    import bunnyland.llm_agents as llm_agents

    calls = {}

    class FakeOllamaAgent:
        def __init__(self, **kwargs):
            calls["ollama"] = kwargs

    class FakeOpenRouterAgent:
        def __init__(self, **kwargs):
            calls["openrouter"] = kwargs

    class FakeProviderRouterAgent:
        def __init__(self, providers, *, default_provider):
            calls["router"] = (providers, default_provider)

    monkeypatch.setattr(llm_agents, "OllamaAgent", FakeOllamaAgent)
    monkeypatch.setattr(llm_agents, "OpenRouterAgent", FakeOpenRouterAgent)
    monkeypatch.setattr(llm_agents, "ProviderRouterAgent", FakeProviderRouterAgent)

    agent = cli._build_serve_agent(
        _serve_args(llm=True, llm_provider="openrouter"),
        cli.ServeCredentials(
            worldgen_provider="openrouter",
            host="https://ollama.example",
            api_key="ollama-key",
            openrouter_api_key="openrouter-key",
            openrouter_server_url="https://openrouter.example",
        ),
        cli.ServeModels(worldgen_model="world-model", character_model="character-model"),
    )

    providers, default_provider = calls["router"]
    assert agent.__class__ is FakeProviderRouterAgent
    assert default_provider == "openrouter"
    assert set(providers) == {"ollama", "openrouter"}
    assert calls["ollama"] == {
        "model": "character-model",
        "host": "https://ollama.example",
        "api_key": "ollama-key",
    }
    assert calls["openrouter"] == {
        "model": "character-model",
        "api_key": "openrouter-key",
        "server_url": "https://openrouter.example",
    }


def test_build_serve_agent_rejects_missing_provider():
    with pytest.raises(SystemExit, match="no LLM agent configured for provider 'openrouter'"):
        cli._build_serve_agent(
            _serve_args(llm=True, llm_provider="openrouter"),
            cli.ServeCredentials(worldgen_provider="openrouter"),
            cli.ServeModels(worldgen_model="world-model", character_model="character-model"),
        )


async def test_load_or_generate_world_reports_loaded_world(tmp_path, capsys):
    path = tmp_path / "world.json"
    save_world(WorldActor(), path, meta=WorldMeta(seed="saved seed", generator="saved-gen"))

    actor, meta = await cli._load_or_generate_world(
        _serve_args(load=str(path)),
        select_plugins([], [WORLDGEN]),
        [],
        cli.ServeCredentials(worldgen_provider="ollama"),
        cli.ServeModels(worldgen_model="world-model", character_model="character-model"),
    )

    output = capsys.readouterr().out
    assert actor.epoch == 0
    assert meta.seed == "saved seed"
    assert f"Reloaded world from {str(path)!r}" in output


def test_discord_filter_ids_can_come_from_environment(monkeypatch):
    monkeypatch.setenv("BUNNYLAND_DISCORD_ALLOWED_GUILD_IDS", "11,22")
    monkeypatch.setenv("BUNNYLAND_DISCORD_ALLOWED_CHANNEL_IDS", "33")
    monkeypatch.setenv("BUNNYLAND_DISCORD_ALLOWED_DM_USER_IDS", "44, 55")

    assert cli._discord_filter_ids(_serve_args()) == ((11, 22), (33,), (44, 55))


def test_maybe_assign_startup_discord_claim_handles_errors_and_save(
    monkeypatch,
    tmp_path,
    capsys,
):
    actor = WorldActor()
    meta = WorldMeta(seed="moss", generator="empty")

    def failing_assign(actor, **kwargs):
        del actor, kwargs
        raise RuntimeError("no claimable characters")

    monkeypatch.setenv("BUNNYLAND_DISCORD_USER_ID", "123")
    monkeypatch.setenv("BUNNYLAND_DISCORD_CHANNEL_ID", "456")
    monkeypatch.setattr(cli, "assign_discord_controller", failing_assign)

    claim_secrets = ClaimSecretRegistry()
    cli._maybe_assign_startup_discord_claim(
        actor,
        _serve_args(discord=True),
        meta,
        claim_secrets,
    )
    assert "Skipped startup Discord claim for user 123" in capsys.readouterr().out

    path = tmp_path / "claimed-world.json"

    def successful_assign(actor, **kwargs):
        del actor
        assert kwargs["default_channel_id"] == 456
        assert kwargs["claim_secrets"] is claim_secrets
        return "Juniper"

    monkeypatch.setattr(cli, "assign_discord_controller", successful_assign)

    cli._maybe_assign_startup_discord_claim(
        actor,
        _serve_args(discord=True, save=str(path)),
        meta,
        claim_secrets,
    )

    assert "Assigned Discord user 123 to 'Juniper'." in capsys.readouterr().out
    assert path.exists()


async def test_run_api_runtime_without_mcp_uses_env_admin_token(monkeypatch, tmp_path, capsys):
    import bunnyland.server.runtime as runtime

    calls = {}

    async def fake_run_loop_with_api(loop, actor, meta, **kwargs):
        calls["loop"] = loop
        calls["actor"] = actor
        calls["meta"] = meta
        calls["kwargs"] = kwargs
        return 3

    actor = WorldActor()
    meta = WorldMeta(seed="moss", generator="empty")
    args = _serve_args(api_port=8765, max_rooms=9, save=str(tmp_path / "world.json"))
    loop = type("Loop", (), {"run": lambda self, *, max_ticks: asyncio.sleep(0, result=1)})()

    monkeypatch.setenv("BUNNYLAND_ADMIN_TOKEN", "env-admin")
    monkeypatch.setattr(runtime, "run_loop_with_api", fake_run_loop_with_api)

    ticks = await cli._run_api_runtime(
        loop,
        actor,
        meta,
        args,
        select_plugins([], [WORLDGEN]),
        None,
        cli.ServeCredentials(worldgen_provider="ollama", worldgen_api_key="worldgen-key"),
        cli.ServeModels(worldgen_model="world-model", character_model="character-model"),
        3,
    )

    assert ticks == 3
    assert calls["kwargs"]["admin_token"] == "env-admin"
    assert calls["kwargs"]["worldgen_options"].max_rooms == 9
    assert "Serving MCP" not in capsys.readouterr().out


def test_cli_save_records_namespaced_imported_plugin(monkeypatch, tmp_path):
    install_plugin_module(monkeypatch, "module_foo", [Plugin(id="bar", name="Bar")])
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
