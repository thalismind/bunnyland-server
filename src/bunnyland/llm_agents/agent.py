"""Agents decide a character's next action (spec 25).

A ``CharacterAgent`` is given a rendered prompt plus the structured context and returns a
single ``ToolCall`` (or ``None`` to wait). The dispatch layer turns that into a validated
command; the agent never touches the ECS and cannot bypass costs or policy (spec 25.3).

``ScriptedAgent`` replays preset decisions and drives the deterministic tests.
``OllamaAgent`` calls Ollama Cloud with the verb tool schemas (optional ``llm`` extra).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Iterable
from collections.abc import Mapping as MappingABC
from typing import Protocol

from ..prompts.builder import PromptContext
from .tools import ToolCall, tool_schemas

#: Default Ollama model (https://ollama.com/library/deepseek-v4-flash).
DEFAULT_MODEL = "deepseek-v4-flash"
LEGACY_DEFAULT_MODEL = "llama3"
DEFAULT_PROVIDER_RETRIES = 2
DEFAULT_RETRY_DELAY_SECONDS = 1.0
TRANSIENT_STATUS_CODES = frozenset({408, 409, 425, 429})

logger = logging.getLogger("bunnyland.llm")


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
        tools: list[dict] | None = None,
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
        tools: list[dict] | None = None,
    ) -> ToolCall | None:
        del prompt, context, character_id, model, provider, tools
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
        max_retries: int = DEFAULT_PROVIDER_RETRIES,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
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
        self._max_retries = max(0, max_retries)
        self._retry_delay_seconds = max(0.0, retry_delay_seconds)
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
        tools: list[dict] | None = None,
    ) -> ToolCall | None:
        del context, provider
        history = self._history.setdefault(character_id, [])
        user_message = {"role": "user", "content": prompt}
        messages = [*history, user_message]

        async def request():
            return await self._client.chat(
                model=normalize_model(model or self._model),
                messages=messages,
                tools=tools or tool_schemas(),
            )

        response = await _call_provider_with_retries(
            "ollama",
            request,
            max_retries=self._max_retries,
            retry_delay_seconds=self._retry_delay_seconds,
        )
        if response is None:
            return None
        message = response["message"]
        tool_calls = message.get("tool_calls") or []
        history.append(user_message)
        if tool_calls:
            history.append(_tool_call_history(tool_calls[0]["function"]))
        else:
            history.append(dict(message))
        self._trim(history)

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
        max_retries: int = DEFAULT_PROVIDER_RETRIES,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
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
        self._max_retries = max(0, max_retries)
        self._retry_delay_seconds = max(0.0, retry_delay_seconds)
        self._history: dict[str, list[dict]] = {}

    async def decide(  # pragma: no cover - needs network + extra
        self,
        prompt: str,
        context: PromptContext,
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
        tools: list[dict] | None = None,
    ) -> ToolCall | None:
        del context, provider
        history = self._history.setdefault(character_id, [])
        user_message = {"role": "user", "content": prompt}
        messages = [*history, user_message]

        async def request():
            return await self._client.chat.send_async(
                model=normalize_model(model or self._model),
                messages=messages,
                tools=tools or tool_schemas(),
            )

        response = await _call_provider_with_retries(
            "openrouter",
            request,
            max_retries=self._max_retries,
            retry_delay_seconds=self._retry_delay_seconds,
        )
        if response is None:
            return None
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        history.append(user_message)
        if tool_calls:
            function = tool_calls[0].function
            history.append(
                _tool_call_history(
                    {
                        "name": function.name,
                        "arguments": _openrouter_arguments(
                            getattr(function, "arguments", {})
                        ),
                    }
                )
            )
        else:
            history.append(_message_to_history(message))
        self._trim(history)

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
        tools: list[dict] | None = None,
    ) -> ToolCall | None | Awaitable[ToolCall | None]:
        selected = provider or self._default_provider
        agent = self._providers.get(selected)
        if agent is None:
            available = ", ".join(sorted(self._providers)) or "(none)"
            raise RuntimeError(
                f"no LLM agent configured for provider {selected!r}; available: {available}"
            )
        return agent.decide(
            prompt,
            context,
            character_id=character_id,
            model=model,
            provider=provider,
            tools=tools,
        )


def _provider_status_code(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status
    return None


def _is_transient_provider_error(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    status = _provider_status_code(exc)
    if status is not None:
        return status in TRANSIENT_STATUS_CODES or status >= 500
    module = type(exc).__module__.split(".", 1)[0]
    return module in {"httpcore", "httpx", "ollama", "openrouter"}


async def _call_provider_with_retries(
    provider: str,
    request,
    *,
    max_retries: int,
    retry_delay_seconds: float,
):
    for attempt in range(max_retries + 1):
        try:
            return await request()
        except Exception as exc:
            if not _is_transient_provider_error(exc):
                raise
            if attempt >= max_retries:
                logger.warning(
                    "%s provider failed after %s attempt%s; character will wait: %s",
                    provider,
                    attempt + 1,
                    "" if attempt == 0 else "s",
                    exc,
                )
                return None
            logger.warning(
                "%s provider transient error on attempt %s/%s; retrying: %s",
                provider,
                attempt + 1,
                max_retries + 1,
                exc,
            )
            if retry_delay_seconds > 0:
                await asyncio.sleep(retry_delay_seconds)
    return None


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


def _tool_call_history(function: MappingABC[str, object]) -> dict:
    name = str(function.get("name", "unknown"))
    arguments = function.get("arguments", {})
    try:
        encoded = json.dumps(arguments, sort_keys=True)
    except TypeError:
        encoded = json.dumps(str(arguments))
    return {
        "role": "assistant",
        "content": f"Selected tool {name} with arguments {encoded}.",
    }


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
