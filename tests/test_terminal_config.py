from __future__ import annotations

import pytest
import yaml

from bunnyland.terminal_config import (
    DEFAULT_OPENROUTER_SERVER_URL,
    LOCAL_OLLAMA_HOST,
    TerminalConfig,
    TerminalConfigError,
    build_terminal_chat_agent,
    load_terminal_config,
    persisted_terminal_config,
    resolve_ignored_content_flags,
    resolve_terminal_chat_config,
    save_terminal_config,
    should_skip_world_introduction,
    terminal_config_path,
    with_skipped_world_introduction,
)


def test_terminal_config_path_honors_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert terminal_config_path() == tmp_path / "bunnyland" / "terminal.yml"


def test_missing_terminal_config_is_first_run(tmp_path):
    assert load_terminal_config(tmp_path / "missing.yml") is None


@pytest.mark.parametrize("provider", ["ollama-local", "ollama-cloud", "openrouter"])
def test_terminal_config_round_trip_all_providers(tmp_path, provider):
    path = tmp_path / "terminal.yml"
    expected = TerminalConfig(
        chat_provider=provider,
        chat_model="example/model",
        ollama_host="https://ollama.example",
        openrouter_server_url="https://router.example/v1",
        ignored_content_flags=("pvp", "adult:violence"),
    )
    assert save_terminal_config(expected, path) == path
    assert load_terminal_config(path) == expected


def test_ignored_content_flags_merge_saved_repeatable_and_comma_separated_values():
    saved = TerminalConfig(ignored_content_flags=("pvp",))
    assert resolve_ignored_content_flags(
        saved, ["adult:violence,theft", "pvp"]
    ) == ("adult:violence", "pvp", "theft")
    assert resolve_ignored_content_flags(None) == ()


def test_world_introduction_preferences_scope_to_world_server_or_all():
    initial = TerminalConfig()
    scoped = with_skipped_world_introduction(
        initial,
        server="https://one.example/api/",
        world_id="world-1",
        all_worlds=False,
    )
    assert should_skip_world_introduction(
        scoped, server="https://one.example/api", world_id="world-1"
    )
    assert not should_skip_world_introduction(
        scoped, server="https://two.example/api", world_id="world-1"
    )
    assert not should_skip_world_introduction(
        scoped, server="https://one.example/api", world_id="world-2"
    )

    global_skip = with_skipped_world_introduction(
        scoped,
        server="https://two.example/api",
        world_id="world-2",
        all_worlds=True,
    )
    assert should_skip_world_introduction(
        global_skip, server="https://three.example/api", world_id="world-3"
    )


def test_terminal_config_never_serializes_credentials(tmp_path):
    path = tmp_path / "terminal.yml"
    settings = resolve_terminal_chat_config(
        None,
        chat_provider="openrouter",
        environ={"OPENROUTER_API_KEY": "super-secret"},
    )
    save_terminal_config(persisted_terminal_config(settings), path)
    assert "super-secret" not in path.read_text(encoding="utf-8")
    assert "api_key" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("contents", "match"),
    [
        ("- not\n- a\n- mapping\n", "YAML mapping"),
        ("version: 99\n", "invalid terminal configuration"),
        ("version: [\n", "invalid terminal configuration YAML"),
        ("version: 1\nunexpected: true\n", "invalid terminal configuration"),
    ],
)
def test_malformed_terminal_config_is_clear(tmp_path, contents, match):
    path = tmp_path / "terminal.yml"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(TerminalConfigError, match=match):
        load_terminal_config(path)


def test_terminal_config_read_and_write_errors_are_clear(monkeypatch, tmp_path):
    def raise_os_error(*_args, **_kwargs):
        raise OSError("denied")

    path = tmp_path / "terminal.yml"
    path.write_text("version: 1\n", encoding="utf-8")
    monkeypatch.setattr(path.__class__, "read_text", raise_os_error)
    with pytest.raises(TerminalConfigError, match="could not read"):
        load_terminal_config(path)

    monkeypatch.undo()
    monkeypatch.setattr(path.__class__, "write_text", raise_os_error)
    with pytest.raises(TerminalConfigError, match="could not save"):
        save_terminal_config(TerminalConfig(), path)


def test_terminal_config_override_precedence():
    saved = TerminalConfig(
        chat_provider="ollama-cloud",
        chat_model="saved-model",
        ollama_host="https://saved-ollama.example",
        openrouter_server_url="https://saved-router.example",
    )
    settings = resolve_terminal_chat_config(
        saved,
        chat_provider="openrouter",
        chat_model="cli-model",
        ollama_host="https://cli-ollama.example/",
        environ={
            "OLLAMA_HOST": "https://env-ollama.example",
            "OPENROUTER_SERVER_URL": "https://env-router.example/",
            "OPENROUTER_API_KEY": "key",
        },
    )
    assert settings.provider == "openrouter"
    assert settings.model == "cli-model"
    assert settings.ollama_host == "https://cli-ollama.example"
    assert settings.openrouter_server_url == "https://env-router.example"
    assert settings.api_key == "key"


def test_saved_endpoints_precede_defaults_and_environment_precedes_saved():
    saved = TerminalConfig(
        ollama_host="https://saved-ollama.example",
        openrouter_server_url="https://saved-router.example",
    )
    from_saved = resolve_terminal_chat_config(saved, environ={})
    assert from_saved.ollama_host == "https://saved-ollama.example"
    assert from_saved.openrouter_server_url == "https://saved-router.example"
    from_environment = resolve_terminal_chat_config(
        saved,
        environ={
            "OLLAMA_HOST": "https://env-ollama.example",
            "OPENROUTER_SERVER_URL": "https://env-router.example",
        },
    )
    assert from_environment.ollama_host == "https://env-ollama.example"
    assert from_environment.openrouter_server_url == "https://env-router.example"


def test_terminal_chat_defaults_and_no_chat():
    settings = resolve_terminal_chat_config(None, environ={})
    assert settings.enabled is True
    assert settings.provider == "ollama-local"
    assert settings.ollama_host == LOCAL_OLLAMA_HOST
    assert settings.openrouter_server_url == DEFAULT_OPENROUTER_SERVER_URL
    assert resolve_terminal_chat_config(None, no_chat=True, environ={}).enabled is False


def test_terminal_chat_rejects_unknown_provider_and_blank_model():
    with pytest.raises(TerminalConfigError, match="unknown"):
        resolve_terminal_chat_config(None, chat_provider="unknown", environ={})
    with pytest.raises(TerminalConfigError, match="cannot be empty"):
        resolve_terminal_chat_config(None, chat_model="   ", environ={})


@pytest.mark.parametrize(
    ("provider", "variable"),
    [
        ("ollama-cloud", "OLLAMA_CLOUD_API_KEY"),
        ("openrouter", "OPENROUTER_API_KEY"),
    ],
)
def test_cloud_terminal_chat_requires_environment_credentials(provider, variable):
    settings = resolve_terminal_chat_config(None, chat_provider=provider, environ={})
    with pytest.raises(TerminalConfigError, match=variable):
        settings.validate_credentials()


def test_disabled_terminal_chat_does_not_require_credentials():
    settings = resolve_terminal_chat_config(
        TerminalConfig(chat_enabled=False, chat_provider="openrouter"), environ={}
    )
    settings.validate_credentials()
    assert build_terminal_chat_agent(settings) is None


def test_terminal_chat_config_rejects_conflicting_raw_and_file_credentials(tmp_path):
    secret = tmp_path / "openrouter-token"
    secret.write_text("file-token\n", encoding="utf-8")
    secret.chmod(0o600)

    with pytest.raises(TerminalConfigError, match="OPENROUTER_API_KEY and OPENROUTER_API_KEY_FILE"):
        resolve_terminal_chat_config(
            None,
            chat_provider="openrouter",
            environ={
                "OPENROUTER_API_KEY": "raw-token",
                "OPENROUTER_API_KEY_FILE": str(secret),
            },
        )


@pytest.mark.asyncio
async def test_terminal_agent_forces_selected_model_and_provider(monkeypatch):
    calls = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            calls["init"] = kwargs

        async def chat(self, messages, **kwargs):
            calls["chat"] = (messages, kwargs)
            return "reply"

        async def decide(self, prompt, context, **kwargs):
            calls["decide"] = (prompt, context, kwargs)
            return "decision"

    import bunnyland.llm_agents as agents

    monkeypatch.setattr(agents, "OllamaAgent", FakeAgent)
    settings = resolve_terminal_chat_config(
        None,
        chat_provider="ollama-local",
        chat_model="selected-model",
        environ={},
    )
    agent = build_terminal_chat_agent(settings)
    result = await agent.chat(
        [{"role": "user", "content": "hello"}],
        character_id="c",
        model="controller-model",
        provider="controller-provider",
        tools=[],
    )
    assert result == "reply"
    assert calls["init"] == {
        "model": "selected-model",
        "host": LOCAL_OLLAMA_HOST,
        "api_key": None,
    }
    assert calls["chat"][1]["model"] == "selected-model"
    assert calls["chat"][1]["provider"] == "ollama-local"
    context = object()
    decision = await agent.decide(
        "prompt",
        context,
        character_id="c",
        model="controller-model",
        provider="controller-provider",
        tools=[],
    )
    assert decision == "decision"
    assert calls["decide"][1] is context
    assert calls["decide"][2]["model"] == "selected-model"
    assert calls["decide"][2]["provider"] == "ollama-local"


def test_terminal_agent_builds_openrouter(monkeypatch):
    calls = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            calls.update(kwargs)

    import bunnyland.llm_agents as agents

    monkeypatch.setattr(agents, "OpenRouterAgent", FakeAgent)
    settings = resolve_terminal_chat_config(
        None,
        chat_provider="openrouter",
        chat_model="openai/example",
        environ={"OPENROUTER_API_KEY": "key"},
    )
    assert build_terminal_chat_agent(settings) is not None
    assert calls == {
        "model": "openai/example",
        "api_key": "key",
        "server_url": DEFAULT_OPENROUTER_SERVER_URL,
    }


def test_saved_yaml_has_explicit_version(tmp_path):
    path = save_terminal_config(TerminalConfig(chat_enabled=False), tmp_path / "terminal.yml")
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["version"] == 1
