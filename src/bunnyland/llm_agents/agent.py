"""Agents decide a character's next action (spec 25).

A ``CharacterAgent`` is given a rendered prompt plus the structured context and returns a
single ``ToolCall`` (or ``None`` to wait). The dispatch layer turns that into a validated
command; the agent never touches the ECS and cannot bypass costs or policy (spec 25.3).

``ScriptedAgent`` replays preset decisions and drives the deterministic tests.
``OllamaAgent`` calls Ollama Cloud with the verb tool schemas (optional ``llm`` extra).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Iterable
from collections.abc import Mapping as MappingABC
from typing import Protocol

from ..prompts.builder import PromptContext
from .tools import ToolCall, tool_schemas

#: Default Ollama model (https://ollama.com/library/deepseek-v4-flash).
DEFAULT_MODEL = "deepseek-v4-flash"
LEGACY_DEFAULT_MODEL = "llama3"


def normalize_model(model: str | None) -> str:
    """Map legacy saved defaults to the current character-controller default."""

    if not model or model == LEGACY_DEFAULT_MODEL:
        return DEFAULT_MODEL
    return model


class CharacterAgent(Protocol):
    """Chooses the next action for a character, or ``None`` to wait this turn.

    ``character_id`` identifies which character is deciding so stateful agents can keep
    per-character conversation history across turns.
    """

    def decide(
        self,
        prompt: str,
        context: PromptContext,
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
    ) -> ToolCall | None | Awaitable[ToolCall | None]: ...


class ScriptedAgent:
    """Replays a fixed sequence of tool calls; yields ``None`` (wait) once exhausted."""

    def __init__(self, calls: Iterable[ToolCall]) -> None:
        self._calls = list(calls)
        self._index = 0

    def decide(
        self,
        prompt: str,
        context: PromptContext,
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
    ) -> ToolCall | None:
        del prompt, context, character_id, model, provider
        if self._index >= len(self._calls):
            return None
        call = self._calls[self._index]
        self._index += 1
        return call


class OllamaAgent:
    """Asks an Ollama model to pick one character action. ``ollama`` is imported lazily.

    Per character, the prior turns' prompts and the model's own replies are retained and
    resent each turn so the model has conversational context (spec 25). History is capped
    at ``history_turns`` exchanges to bound the prompt size.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        host: str | None = None,
        api_key: str | None = None,
        history_turns: int = 12,
    ) -> None:
        try:
            import ollama
        except ImportError as exc:  # pragma: no cover - exercised only without extra
            raise RuntimeError(
                "OllamaAgent requires the 'llm' extra: pip install bunnyland[llm]"
            ) from exc
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        client_cls = ollama.AsyncClient
        self._client = client_cls(host=host, headers=headers) if host else client_cls()
        self._model = model
        self._history_turns = history_turns
        # character_id -> running list of {"role", "content"/"tool_calls"} messages.
        self._history: dict[str, list[dict]] = {}

    async def decide(  # pragma: no cover - needs network + extra
        self,
        prompt: str,
        context: PromptContext,
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
    ) -> ToolCall | None:
        del context, provider
        history = self._history.setdefault(character_id, [])
        history.append({"role": "user", "content": prompt})

        response = await self._client.chat(
            model=normalize_model(model or self._model),
            messages=history,
            tools=tool_schemas(),
        )
        message = response["message"]
        # Persist the model's reply (including any tool_calls) for the next turn.
        history.append(dict(message))
        self._trim(history)

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return None
        call = tool_calls[0]["function"]
        return ToolCall(name=call["name"], arguments=dict(call.get("arguments", {})))

    def _trim(self, history: list[dict]) -> None:  # pragma: no cover - needs network + extra
        # Keep the last N exchanges (user + assistant per turn).
        limit = self._history_turns * 2
        if len(history) > limit:
            del history[: len(history) - limit]


class OpenRouterAgent:
    """Asks an OpenRouter model to pick one character action."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        server_url: str | None = None,
        history_turns: int = 12,
    ) -> None:
        try:
            from openrouter import OpenRouter
        except ImportError as exc:  # pragma: no cover - exercised only without extra
            raise RuntimeError(
                "OpenRouterAgent requires the 'llm' extra: pip install bunnyland[llm]"
            ) from exc
        kwargs = {"api_key": api_key}
        if server_url:
            kwargs["server_url"] = server_url
        self._client = OpenRouter(**kwargs)
        self._model = model
        self._history_turns = history_turns
        self._history: dict[str, list[dict]] = {}

    async def decide(  # pragma: no cover - needs network + extra
        self,
        prompt: str,
        context: PromptContext,
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
    ) -> ToolCall | None:
        del context, provider
        history = self._history.setdefault(character_id, [])
        history.append({"role": "user", "content": prompt})

        response = await self._client.chat.send_async(
            model=normalize_model(model or self._model),
            messages=history,
            tools=tool_schemas(),
        )
        message = response.choices[0].message
        history.append(_message_to_history(message))
        self._trim(history)

        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            return None
        function = tool_calls[0].function
        arguments = _openrouter_arguments(getattr(function, "arguments", {}))
        return ToolCall(name=function.name, arguments=arguments)

    def _trim(self, history: list[dict]) -> None:  # pragma: no cover - needs network + extra
        limit = self._history_turns * 2
        if len(history) > limit:
            del history[: len(history) - limit]


class ProviderRouterAgent:
    """Routes decisions to the concrete agent named by a controller's provider."""

    def __init__(
        self, providers: MappingABC[str, CharacterAgent], *, default_provider: str = "ollama"
    ):
        self._providers = dict(providers)
        self._default_provider = default_provider

    def decide(
        self,
        prompt: str,
        context: PromptContext,
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
    ) -> ToolCall | None | Awaitable[ToolCall | None]:
        selected = provider or self._default_provider
        agent = self._providers.get(selected)
        if agent is None:
            available = ", ".join(sorted(self._providers)) or "(none)"
            raise RuntimeError(
                f"no LLM agent configured for provider {selected!r}; available: {available}"
            )
        return agent.decide(prompt, context, character_id=character_id, model=model)


def _message_to_history(message) -> dict:
    if hasattr(message, "model_dump"):
        return message.model_dump(mode="json", exclude_none=True)
    result = {"role": getattr(message, "role", "assistant")}
    content = getattr(message, "content", None)
    if content is not None:
        result["content"] = content
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        result["tool_calls"] = tool_calls
    return result


def _openrouter_arguments(arguments: object) -> dict:
    if isinstance(arguments, str):
        return dict(json.loads(arguments or "{}"))
    if isinstance(arguments, MappingABC):
        return dict(arguments)
    return {}


Agent = CharacterAgent


__all__ = [
    "DEFAULT_MODEL",
    "LEGACY_DEFAULT_MODEL",
    "Agent",
    "CharacterAgent",
    "OpenRouterAgent",
    "OllamaAgent",
    "ProviderRouterAgent",
    "ScriptedAgent",
    "normalize_model",
]
