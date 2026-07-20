"""User-scoped configuration for Bunnyland terminal chat clients."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .cli_defaults import OLLAMA_CLOUD_HOST
from .llm_agents import DEFAULT_MODEL

TERMINAL_CONFIG_VERSION = 1
LOCAL_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_OPENROUTER_SERVER_URL = "https://openrouter.ai/api/v1"

ChatProvider = Literal["ollama-local", "ollama-cloud", "openrouter"]


class TerminalConfigError(ValueError):
    """A terminal configuration file is present but cannot be used."""


class TerminalConfig(BaseModel):
    """Persisted terminal preferences. Provider secrets are intentionally absent."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = TERMINAL_CONFIG_VERSION
    chat_enabled: bool = True
    chat_provider: ChatProvider = "ollama-local"
    chat_model: str = Field(default=DEFAULT_MODEL, min_length=1)
    ollama_host: str | None = None
    openrouter_server_url: str | None = None


@dataclass(frozen=True)
class ResolvedTerminalChatConfig:
    """Effective chat settings after CLI, environment, file, and defaults merge."""

    enabled: bool
    provider: ChatProvider
    model: str
    ollama_host: str
    openrouter_server_url: str
    api_key: str = ""

    def validate_credentials(self) -> None:
        if not self.enabled:
            return
        if self.provider == "ollama-cloud" and not self.api_key:
            raise TerminalConfigError(
                "ollama-cloud chat needs OLLAMA_CLOUD_API_KEY in the environment"
            )
        if self.provider == "openrouter" and not self.api_key:
            raise TerminalConfigError("openrouter chat needs OPENROUTER_API_KEY in the environment")


def terminal_config_path(environ: Mapping[str, str] | None = None) -> Path:
    values = os.environ if environ is None else environ
    base = Path(values.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "bunnyland" / "terminal.yml"


def load_terminal_config(path: Path | None = None) -> TerminalConfig | None:
    """Load a saved configuration, returning ``None`` only when it does not exist."""

    config_path = path or terminal_config_path()
    try:
        raw = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise TerminalConfigError(f"could not read terminal configuration: {exc}") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise TerminalConfigError(f"invalid terminal configuration YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise TerminalConfigError("terminal configuration must be a YAML mapping")
    try:
        return TerminalConfig.model_validate(data)
    except ValidationError as exc:
        raise TerminalConfigError(f"invalid terminal configuration: {exc}") from exc


def save_terminal_config(config: TerminalConfig, path: Path | None = None) -> Path:
    """Persist non-secret preferences in the versioned user configuration file."""

    config_path = path or terminal_config_path()
    data = config.model_dump(mode="json", exclude_none=True)
    # Defense in depth if the model grows: credentials must never reach disk.
    data = {key: value for key, value in data.items() if "key" not in key and "secret" not in key}
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    except OSError as exc:
        raise TerminalConfigError(f"could not save terminal configuration: {exc}") from exc
    return config_path


def resolve_terminal_chat_config(
    saved: TerminalConfig | None,
    *,
    chat_provider: str | None = None,
    chat_model: str | None = None,
    ollama_host: str | None = None,
    openrouter_server_url: str | None = None,
    no_chat: bool = False,
    environ: Mapping[str, str] | None = None,
) -> ResolvedTerminalChatConfig:
    """Resolve CLI -> environment endpoint -> saved value -> default precedence."""

    values = os.environ if environ is None else environ
    provider = chat_provider or (saved.chat_provider if saved else "ollama-local")
    if provider not in {"ollama-local", "ollama-cloud", "openrouter"}:
        raise TerminalConfigError(f"unknown terminal chat provider: {provider!r}")
    model = chat_model or (saved.chat_model if saved else DEFAULT_MODEL)
    if not model.strip():
        raise TerminalConfigError("terminal chat model cannot be empty")

    resolved_ollama_host = (
        ollama_host
        or values.get("OLLAMA_HOST")
        or (saved.ollama_host if saved else None)
        or (OLLAMA_CLOUD_HOST if provider == "ollama-cloud" else LOCAL_OLLAMA_HOST)
    )
    resolved_openrouter_url = (
        openrouter_server_url
        or values.get("OPENROUTER_SERVER_URL")
        or (saved.openrouter_server_url if saved else None)
        or DEFAULT_OPENROUTER_SERVER_URL
    )
    enabled = False if no_chat else (saved.chat_enabled if saved else True)
    api_key = ""
    if provider == "ollama-cloud":
        api_key = values.get("OLLAMA_CLOUD_API_KEY", "")
    elif provider == "openrouter":
        api_key = values.get("OPENROUTER_API_KEY", "")
    return ResolvedTerminalChatConfig(
        enabled=enabled,
        provider=provider,
        model=model.strip(),
        ollama_host=resolved_ollama_host.rstrip("/"),
        openrouter_server_url=resolved_openrouter_url.rstrip("/"),
        api_key=api_key,
    )


def persisted_terminal_config(settings: ResolvedTerminalChatConfig) -> TerminalConfig:
    """Convert effective settings back to the secret-free persisted form."""

    return TerminalConfig(
        chat_enabled=settings.enabled,
        chat_provider=settings.provider,
        chat_model=settings.model,
        ollama_host=settings.ollama_host,
        openrouter_server_url=settings.openrouter_server_url,
    )


def build_terminal_chat_agent(settings: ResolvedTerminalChatConfig):
    """Create the provider used only by direct terminal character chat."""

    settings.validate_credentials()
    if not settings.enabled:
        return None
    from .llm_agents import OllamaAgent, OpenRouterAgent

    if settings.provider in {"ollama-local", "ollama-cloud"}:
        agent = OllamaAgent(
            model=settings.model,
            host=settings.ollama_host,
            api_key=settings.api_key or None,
        )
    else:
        agent = OpenRouterAgent(
            model=settings.model,
            api_key=settings.api_key,
            server_url=settings.openrouter_server_url,
        )
    return _ConfiguredChatAgent(agent, settings)


class _ConfiguredChatAgent:
    """Keep terminal chat on its selected provider/model despite controller metadata."""

    def __init__(self, agent, settings: ResolvedTerminalChatConfig) -> None:
        self._agent = agent
        self._settings = settings

    async def chat(
        self,
        messages: list[dict],
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
        tools: list[dict] | None = None,
    ):
        del model, provider
        return await self._agent.chat(
            messages,
            character_id=character_id,
            model=self._settings.model,
            provider=self._settings.provider,
            tools=tools,
        )


__all__ = [
    "ChatProvider",
    "DEFAULT_OPENROUTER_SERVER_URL",
    "LOCAL_OLLAMA_HOST",
    "ResolvedTerminalChatConfig",
    "TERMINAL_CONFIG_VERSION",
    "TerminalConfig",
    "TerminalConfigError",
    "build_terminal_chat_agent",
    "load_terminal_config",
    "persisted_terminal_config",
    "resolve_terminal_chat_config",
    "save_terminal_config",
    "terminal_config_path",
]
