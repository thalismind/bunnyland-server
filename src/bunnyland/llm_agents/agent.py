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
import re
from collections.abc import Awaitable, Iterable
from collections.abc import Mapping as MappingABC
from typing import Literal, Protocol

from .. import telemetry
from ..prompts.builder import PromptContext
from .tools import ToolCall, tool_schemas

#: Default Ollama model (https://ollama.com/library/deepseek-v4-flash).
DEFAULT_MODEL = "deepseek-v4-flash"
LEGACY_DEFAULT_MODEL = "llama3"
DEFAULT_PROVIDER_RETRIES = 2
DEFAULT_RETRY_DELAY_SECONDS = 1.0
TRANSIENT_STATUS_CODES = frozenset({408, 409, 425, 429})

logger = logging.getLogger("bunnyland.llm")


def _ollama_token_usage(response: object) -> tuple[int, int]:
    """Pull (prompt, completion) token counts from an Ollama chat response, defensively."""
    if not isinstance(response, MappingABC):
        return 0, 0
    return int(response.get("prompt_eval_count", 0) or 0), int(
        response.get("eval_count", 0) or 0
    )


def _openrouter_token_usage(response: object) -> tuple[int, int]:
    """Pull (prompt, completion) token counts from an OpenRouter response, defensively."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0
    return int(getattr(usage, "prompt_tokens", 0) or 0), int(
        getattr(usage, "completion_tokens", 0) or 0
    )


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
    """Replays a fixed sequence of tool calls.

    Yields ``None`` (wait) once the sequence is exhausted, unless ``loop`` is set, in which
    case it restarts from the beginning. An empty sequence always waits.
    """

    def __init__(self, calls: Iterable[ToolCall], *, loop: bool = False) -> None:
        self._calls = list(calls)
        self._loop = loop
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
        if not self._calls:
            return None
        if self._index >= len(self._calls):
            if not self._loop:
                return None
            self._index = 0
        call = self._calls[self._index]
        self._index += 1
        return call


_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "with",
        "your",
        "you",
        "are",
        "the",
        "and",
        "for",
        "from",
        "into",
        "that",
        "this",
        "they",
        "their",
        "them",
        "then",
        "was",
        "were",
        "will",
        "have",
        "has",
        "had",
        "goal",
        "current",
        "status",
        "memory",
        "source",
        "score",
    }
)

_DIRECTION_WORDS = (
    "north",
    "south",
    "east",
    "west",
    "up",
    "down",
    "inside",
    "outside",
    "in",
    "out",
)

BackgroundProfile = Literal["idle", "social", "timid", "aggressive", "worker"]
BACKGROUND_PROFILES: frozenset[str] = frozenset(
    {"idle", "social", "timid", "aggressive", "worker"}
)


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        token
        for token in re.findall(r"[a-z0-9']+", text.lower())
        if len(token) > 2 and token not in _STOPWORDS
    )


def _command_available(context: PromptContext, command: str) -> bool:
    command_key = command.lower()
    return any(line.lower() == command_key for line in context.commands)


def _first_unlocked_exit(context: PromptContext) -> str | None:
    for exit_ in context.exits:
        if "(locked)" not in exit_:
            return exit_.split(" ", 1)[0]
    return None


class GoalDirectedAgent:
    """Deterministic background controller driven by prompt facts.

    This agent is intentionally small and auditable: it scores visible affordances from
    goals, recall, needs, and recent context, then emits a normal tool call for dispatch
    to resolve and validate. It never reads or writes ECS state directly.
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
    ) -> ToolCall | None:
        del prompt, character_id, model, provider, tools
        signals = _AutonomySignals.from_context(context)
        if not signals.has_signal:
            return None

        item = signals.best_visible(context.visible_objects, min_score=2)
        if item is not None and _command_available(context, f"take {item}"):
            return ToolCall("take", {"item_id": item})

        character = signals.best_visible(context.visible_characters, min_score=2)
        if character is not None and _command_available(context, "say something to the room"):
            return ToolCall("say", {"text": signals.speech_for(character)})

        direction = signals.direction(context)
        if direction is not None and _command_available(context, f"move {direction}"):
            return ToolCall("move", {"direction": direction})

        if signals.should_record and _command_available(context, "take note"):
            return ToolCall("take_note", {"text": signals.note_text()})
        return None


class BehaviorProfileAgent:
    """Cheap deterministic controller profiles for background characters.

    Goal-directed choices run first. When goals and recall do not point to a clear action,
    the selected profile provides a small model-free fallback so background characters can
    feel occupied without requiring a live LLM call every tick.
    """

    def __init__(
        self,
        profile: BackgroundProfile = "idle",
        *,
        goal_agent: CharacterAgent | None = None,
    ) -> None:
        if profile not in BACKGROUND_PROFILES:
            available = ", ".join(sorted(BACKGROUND_PROFILES))
            raise ValueError(f"unknown background profile {profile!r}; choose one of {available}")
        self.profile = profile
        self._goal_agent = goal_agent or GoalDirectedAgent()

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
        goal_decision = self._goal_agent.decide(
            prompt,
            context,
            character_id=character_id,
            model=model,
            provider=provider,
            tools=tools,
        )
        if goal_decision is not None:
            return goal_decision

        if self.profile == "idle":
            return None
        relationship_decision = self._relationship(context)
        if relationship_decision is not None:
            return relationship_decision
        if self.profile == "social":
            return self._social(context)
        if self.profile == "timid":
            return self._timid(context)
        if self.profile == "aggressive":
            return self._aggressive(context)
        return self._worker(context)

    @staticmethod
    def _target(context: PromptContext) -> str | None:
        return context.visible_characters[0] if context.visible_characters else None

    def _relationship(self, context: PromptContext) -> ToolCall | None:
        for target in context.visible_characters:
            target_key = target.lower()
            for line in context.persona:
                line_key = line.lower()
                if target_key not in line_key:
                    continue
                if line_key == f"you fear {target_key}.":
                    direction = _first_unlocked_exit(context)
                    if direction is not None and _command_available(context, f"move {direction}"):
                        return ToolCall("move", {"direction": direction})
                    if _command_available(context, "say something to the room"):
                        return ToolCall(
                            "say",
                            {
                                "text": f"{target}, I need space.",
                                "intent": "request",
                                "approach": "cautious",
                            },
                        )
                if line_key == f"you are fond of {target_key}.":
                    if _command_available(context, "say something to the room"):
                        return ToolCall(
                            "say",
                            {
                                "text": f"{target}, I am glad you are here.",
                                "intent": "praise",
                                "approach": "warm",
                            },
                        )
                if line_key in {
                    f"you resent {target_key}.",
                    f"you dislike {target_key}.",
                }:
                    if _command_available(context, "say something to the room"):
                        return ToolCall(
                            "say",
                            {
                                "text": f"{target}, keep your distance.",
                                "intent": "threat",
                                "approach": "cold",
                            },
                        )
        return None

    def _social(self, context: PromptContext) -> ToolCall | None:
        target = self._target(context)
        if target is None or not _command_available(context, "say something to the room"):
            return None
        return ToolCall(
            "say",
            {
                "text": f"{target}, good to see you.",
                "intent": "praise",
                "approach": "friendly",
            },
        )

    def _timid(self, context: PromptContext) -> ToolCall | None:
        if not context.visible_characters:
            return None
        direction = _first_unlocked_exit(context)
        if direction is not None and _command_available(context, f"move {direction}"):
            return ToolCall("move", {"direction": direction})
        return None

    def _aggressive(self, context: PromptContext) -> ToolCall | None:
        target = self._target(context)
        if target is None or not _command_available(context, "say something to the room"):
            return None
        return ToolCall(
            "say",
            {
                "text": f"{target}, back away.",
                "intent": "threat",
                "approach": "confrontational",
            },
        )

    def _worker(self, context: PromptContext) -> ToolCall | None:
        for item in context.visible_objects:
            if _command_available(context, f"take {item}"):
                return ToolCall("take", {"item_id": item})
        direction = _first_unlocked_exit(context)
        if direction is not None and _command_available(context, f"move {direction}"):
            return ToolCall("move", {"direction": direction})
        return None


class _AutonomySignals:
    def __init__(
        self,
        *,
        goals: tuple[str, ...],
        recall: tuple[str, ...],
        conditions: tuple[str, ...],
        recent: tuple[str, ...],
        notes: tuple[str, ...],
    ) -> None:
        self.goals = goals
        self.recall = recall
        self.conditions = conditions
        self.recent = recent
        self.notes = notes
        weighted: list[tuple[str, int]] = []
        weighted.extend((line, 5) for line in goals)
        weighted.extend((line, 4) for line in recall)
        weighted.extend((line, 3) for line in conditions)
        weighted.extend((line, 2) for line in recent)
        weighted.extend((line, 1) for line in notes)
        self._weighted = tuple(weighted)

    @classmethod
    def from_context(cls, context: PromptContext) -> _AutonomySignals:
        goals = tuple(
            line
            for line in context.persona
            if line.startswith(("Your goal:", "My goal:", "Their goal:"))
        )
        return cls(
            goals=goals,
            recall=context.recall,
            conditions=context.conditions,
            recent=context.recent,
            notes=context.notes,
        )

    @property
    def has_signal(self) -> bool:
        return bool(self._weighted)

    @property
    def should_record(self) -> bool:
        text = self._joined_signal_text()
        return any(word in text for word in ("remember", "record", "note", "journal"))

    def best_visible(self, candidates: tuple[str, ...], *, min_score: int) -> str | None:
        scored = [(self._score(candidate), candidate) for candidate in candidates]
        scored = [(score, candidate) for score, candidate in scored if score >= min_score]
        if not scored:
            return None
        return max(scored, key=lambda item: (item[0], -len(item[1]), item[1].lower()))[1]

    def direction(self, context: PromptContext) -> str | None:
        signal_text = self._joined_signal_text()
        for direction in _DIRECTION_WORDS:
            if re.search(rf"\b{re.escape(direction)}\b", signal_text):
                return direction
        if any(word in signal_text for word in ("explore", "search", "seek", "find", "scout")):
            return _first_unlocked_exit(context)
        return None

    def speech_for(self, name: str) -> str:
        recalled = self._line_mentioning(self.recall, name)
        if recalled is not None:
            return f"{name}, I remember {self._clean_memory_line(recalled)}"
        goal = self._line_mentioning(self.goals, name) or (self.goals[0] if self.goals else "")
        if goal:
            return f"{name}, I am working on {self._clean_goal(goal)}"
        return f"{name}, I need to talk with you."

    def note_text(self) -> str:
        if self.recall:
            return f"Recall matters: {self._clean_memory_line(self.recall[0])}"
        if self.goals:
            return f"Goal matters: {self._clean_goal(self.goals[0])}"
        return "Something nearby may matter."

    def _score(self, candidate: str) -> int:
        candidate_key = candidate.lower()
        candidate_tokens = _tokens(candidate)
        score = 0
        for line, weight in self._weighted:
            line_key = line.lower()
            line_tokens = _tokens(line)
            overlap = candidate_tokens & line_tokens
            if overlap:
                score += len(overlap) * weight
            if candidate_key in line_key:
                score += weight * 2
        return score

    def _joined_signal_text(self) -> str:
        return " ".join(line.lower() for line, _weight in self._weighted)

    @staticmethod
    def _line_mentioning(lines: tuple[str, ...], name: str) -> str | None:
        name_key = name.lower()
        for line in lines:
            if name_key in line.lower():
                return line
        return None

    @staticmethod
    def _clean_goal(line: str) -> str:
        return line.split(":", 1)[-1].strip(" .")

    @staticmethod
    def _clean_memory_line(line: str) -> str:
        return re.sub(r"\s*\[memory:[^\]]+\]\s*$", "", line).strip(" .")


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

    async def decide(
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
        prompt_tokens, completion_tokens = _ollama_token_usage(response)
        telemetry.record_llm_tokens(
            "ollama", normalize_model(model or self._model), prompt_tokens, completion_tokens
        )
        telemetry.set_span_attributes(
            {
                "llm.tokens.prompt": prompt_tokens,
                "llm.tokens.completion": completion_tokens,
            }
        )
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

    def _trim(self, history: list[dict]) -> None:
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

    async def decide(
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
        prompt_tokens, completion_tokens = _openrouter_token_usage(response)
        telemetry.record_llm_tokens(
            "openrouter", normalize_model(model or self._model), prompt_tokens, completion_tokens
        )
        telemetry.set_span_attributes(
            {
                "llm.tokens.prompt": prompt_tokens,
                "llm.tokens.completion": completion_tokens,
            }
        )
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

    def _trim(self, history: list[dict]) -> None:
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
            with telemetry.span(
                "llm.provider.attempt", {"provider": provider, "llm.attempt": attempt}
            ):
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
    # Unreachable: ``range(max_retries + 1)`` always has >=1 element (max_retries is clamped
    # to >=0), and the final iteration always returns or raises.


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
    "BACKGROUND_PROFILES",
    "BackgroundProfile",
    "BehaviorProfileAgent",
    "CharacterAgent",
    "GoalDirectedAgent",
    "OpenRouterAgent",
    "OllamaAgent",
    "ProviderRouterAgent",
    "ScriptedAgent",
    "normalize_model",
]
