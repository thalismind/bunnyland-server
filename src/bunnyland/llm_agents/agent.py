"""Agents decide a character's next action (spec 25).

An ``Agent`` is given a rendered prompt plus the structured context and returns a single
``ToolCall`` (or ``None`` to wait). The dispatch layer turns that into a validated command;
the agent never touches the ECS and cannot bypass costs or policy (spec 25.3).

``ScriptedAgent`` replays preset decisions and drives the deterministic tests.
``OllamaAgent`` calls Ollama Cloud with the verb tool schemas (optional ``llm`` extra).
"""

from __future__ import annotations

from collections.abc import Iterable
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


class Agent(Protocol):
    """Chooses the next action for a character, or ``None`` to wait this turn.

    ``character_id`` identifies which character is deciding so stateful agents can keep
    per-character conversation history across turns.
    """

    def decide(
        self, prompt: str, context: PromptContext, *, character_id: str, model: str | None = None
    ) -> ToolCall | None: ...


class ScriptedAgent:
    """Replays a fixed sequence of tool calls; yields ``None`` (wait) once exhausted."""

    def __init__(self, calls: Iterable[ToolCall]) -> None:
        self._calls = list(calls)
        self._index = 0

    def decide(
        self, prompt: str, context: PromptContext, *, character_id: str, model: str | None = None
    ) -> ToolCall | None:
        del prompt, context, character_id, model
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
        self._client = ollama.Client(host=host, headers=headers) if host else ollama.Client()
        self._model = model
        self._history_turns = history_turns
        # character_id -> running list of {"role", "content"/"tool_calls"} messages.
        self._history: dict[str, list[dict]] = {}

    def decide(  # pragma: no cover - needs network + extra
        self, prompt: str, context: PromptContext, *, character_id: str, model: str | None = None
    ) -> ToolCall | None:
        del context
        history = self._history.setdefault(character_id, [])
        history.append({"role": "user", "content": prompt})

        response = self._client.chat(
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


__all__ = [
    "DEFAULT_MODEL",
    "LEGACY_DEFAULT_MODEL",
    "Agent",
    "OllamaAgent",
    "ScriptedAgent",
    "normalize_model",
]
