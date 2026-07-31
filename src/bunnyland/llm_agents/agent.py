"""Agents decide a character's next action (spec 25).

A ``CharacterAgent`` is given a rendered prompt plus the structured context and returns a
single ``ToolCall``, an ``InvalidAgentResponse``, or ``None`` for deterministic controller
hold behavior. Provider-backed agents must use the explicit ``wait`` tool instead of
returning ``None``. The dispatch layer turns calls into validated commands; the agent never
touches the ECS and cannot bypass costs or policy (spec 25.3).

``ScriptedAgent`` replays preset decisions and drives the deterministic tests.
``OllamaAgent`` calls Ollama Cloud with the verb tool schemas (optional ``llm`` extra).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, Iterable
from collections.abc import Mapping as MappingABC
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import JsonValue, TypeAdapter

from .. import telemetry
from ..prompts.builder import PromptContext
from .tools import ToolCall, tool_schemas

#: Default Ollama model (https://ollama.com/library/deepseek-v4-flash).
DEFAULT_MODEL = "deepseek-v4-flash"
LEGACY_DEFAULT_MODEL = "llama3"
DEFAULT_PROVIDER_RETRIES = 2
EMPTY_RESPONSE_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY_SECONDS = 1.0
TRANSIENT_STATUS_CODES = frozenset({408, 409, 425, 429})
CHARACTER_SYSTEM_PROMPT = (
    "You are an autonomous character in Bunnyland, an asynchronous social sandbox. "
    "Choose exactly one available structured tool call that fits your prompt context. "
    "Call the wait tool when you intentionally want to wait. Never describe a tool call "
    "only in prose or write it as <invoke>, DSML, XML, JSON, or other message text."
)
TEXT_TOOL_CALL_CORRECTION_PROMPT = (
    "Your previous response wrote a tool invocation as message text. That response was "
    "rejected. Respond again using exactly one native structured tool call from the "
    "available tools. Do not write <invoke>, DSML, <tool_call>, <function_call>, XML, or "
    "JSON tool-call syntax in message content."
)
TEXT_REPLY_CORRECTION_PROMPT = (
    "Your previous response wrote a tool invocation as message text. That response was "
    "rejected. Respond again with either one native structured tool call from the available "
    "tools or normal prose without tool-call tags. Do not write <invoke>, DSML, "
    "<tool_call>, <function_call>, XML, or JSON tool-call syntax in message content."
)
PROSE_REPLY_CORRECTION_PROMPT = (
    "Your previous response wrote a tool invocation as message text. That response was "
    "rejected. No tools are available for this response. Answer using normal prose without "
    "<invoke>, DSML, <tool_call>, <function_call>, XML, JSON tool-call syntax, or other "
    "tool-call tags."
)
TEXT_TOOL_CALL_TAG = re.compile(
    r"<\s*/?\s*(?:invoke\b|[|｜]\s*dsml\s*[|｜]|tool_call\b|function_call\b)",
    re.IGNORECASE,
)

logger = logging.getLogger("bunnyland.llm")
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


def contains_text_tool_call(content: str) -> bool:
    """Return whether assistant prose contains a known textual tool-call tag."""

    return bool(TEXT_TOOL_CALL_TAG.search(content))


def _text_tool_retry_messages(
    messages: list[dict],
    content: str,
    *,
    tools_available: bool,
    require_tool: bool,
) -> list[dict]:
    if require_tool:
        correction = TEXT_TOOL_CALL_CORRECTION_PROMPT
    elif tools_available:
        correction = TEXT_REPLY_CORRECTION_PROMPT
    else:
        correction = PROSE_REPLY_CORRECTION_PROMPT
    return [
        *messages,
        {"role": "assistant", "content": content},
        {"role": "user", "content": correction},
    ]


async def _validated_chat_reply(
    request_reply: Callable[[list[dict]], Awaitable[ChatAgentReply | None]],
    messages: list[dict],
    *,
    tools_available: bool,
    reject_text_tool_calls: bool,
) -> ChatAgentReply:
    reply = await request_reply(messages)
    if reply is None:
        return ChatAgentReply()
    if not reject_text_tool_calls or not contains_text_tool_call(reply.content):
        return reply
    telemetry.set_span_attributes({"llm.text_tool_call.rejected": True})
    if reply.tool_call is not None:
        return ChatAgentReply(tool_call=reply.tool_call)
    corrected = await request_reply(
        _text_tool_retry_messages(
            messages,
            reply.content,
            tools_available=tools_available,
            require_tool=False,
        )
    )
    if corrected is None:
        return ChatAgentReply()
    if not contains_text_tool_call(corrected.content):
        return corrected
    if corrected.tool_call is not None:
        return ChatAgentReply(tool_call=corrected.tool_call)
    return ChatAgentReply()


@dataclass(frozen=True)
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0

    @property
    def tokens_available(self) -> bool:
        return bool(self.prompt_tokens or self.completion_tokens or self.total_tokens)

    @property
    def cost_available(self) -> bool:
        return bool(self.cost)


@dataclass(frozen=True)
class ChatAgentReply:
    content: str = ""
    tool_call: ToolCall | None = None


@dataclass(frozen=True)
class InvalidAgentResponse:
    """A provider response that cannot select a character action."""

    reason: str
    feedback: str


AgentDecision = ToolCall | InvalidAgentResponse | None


ProviderResponseObserver = Callable[[dict[str, JsonValue]], None]
OllamaResponseObserver = ProviderResponseObserver


def _ollama_response_json(
    response: object, *, include_thinking: bool
) -> dict[str, JsonValue]:
    model_dump = getattr(response, "model_dump", None)
    raw = model_dump(mode="json") if callable(model_dump) else response
    value = _JSON_OBJECT.validate_python(raw)
    if include_thinking:
        return value
    value.pop("thinking", None)
    message = value.get("message")
    if isinstance(message, dict):
        message.pop("thinking", None)
    return value


def _openrouter_response_json(
    response: object, *, include_thinking: bool
) -> dict[str, JsonValue]:
    model_dump = getattr(response, "model_dump", None)
    raw = model_dump(mode="json") if callable(model_dump) else response
    value = _JSON_OBJECT.validate_python(raw)
    if include_thinking:
        return value
    for key in ("thinking", "reasoning", "reasoning_details"):
        value.pop(key, None)
    choices = value.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            for key in ("thinking", "reasoning", "reasoning_details"):
                message.pop(key, None)
    return value


def _int_field(source: object, *names: str) -> int:
    for name in names:
        if isinstance(source, MappingABC):
            value = source.get(name)
        else:
            value = getattr(source, name, None)
        if value is not None:
            return int(value or 0)
    return 0


def _float_field(source: object, *names: str) -> float:
    for name in names:
        if isinstance(source, MappingABC):
            value = source.get(name)
        else:
            value = getattr(source, name, None)
        if value is not None:
            return float(value or 0.0)
    return 0.0


def _usage_total(prompt_tokens: int, completion_tokens: int, explicit_total: int) -> int:
    if explicit_total:
        return explicit_total
    if prompt_tokens or completion_tokens:
        return prompt_tokens + completion_tokens
    return 0


def _ollama_usage(response: object) -> LLMUsage:
    """Pull token counts from an Ollama chat response, defensively."""
    prompt_tokens = _int_field(response, "prompt_eval_count", "prompt_tokens")
    completion_tokens = _int_field(response, "eval_count", "completion_tokens")
    total_tokens = _usage_total(
        prompt_tokens, completion_tokens, _int_field(response, "total_tokens")
    )
    return LLMUsage(prompt_tokens, completion_tokens, total_tokens)


def _openrouter_usage(response: object) -> LLMUsage:
    """Pull token and provider-reported cost fields from an OpenRouter response."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return LLMUsage()
    prompt_tokens = _int_field(usage, "prompt_tokens")
    completion_tokens = _int_field(usage, "completion_tokens")
    total_tokens = _usage_total(prompt_tokens, completion_tokens, _int_field(usage, "total_tokens"))
    cost = _float_field(usage, "cost", "total_cost", "estimated_cost")
    return LLMUsage(prompt_tokens, completion_tokens, total_tokens, cost)


async def _openrouter_enriched_usage(client: object, response: object) -> LLMUsage:
    usage = _openrouter_usage(response)
    if usage.cost:
        return usage
    generation_id = getattr(response, "id", None)
    generations = getattr(client, "generations", None)
    get_generation = getattr(generations, "get_generation_async", None)
    if not generation_id or get_generation is None:
        return usage

    async def lookup(attempt: int) -> LLMUsage:
        try:
            with telemetry.span(
                "llm.provider.usage",
                {
                    "provider": "openrouter",
                    "llm.generation.id": generation_id,
                    "llm.attempt": attempt,
                },
            ):
                generation = await get_generation(id=generation_id)
            data = getattr(generation, "data", None)
            if data is None:
                return usage
            prompt_tokens = usage.prompt_tokens or _int_field(data, "tokens_prompt")
            completion_tokens = usage.completion_tokens or _int_field(data, "tokens_completion")
            total_tokens = _usage_total(prompt_tokens, completion_tokens, usage.total_tokens)
            cost = _float_field(data, "total_cost", "usage", "upstream_inference_cost")
            return LLMUsage(prompt_tokens, completion_tokens, total_tokens, cost)
        except Exception as exc:
            if attempt >= 2:
                logger.debug(
                    "OpenRouter generation usage lookup failed for %s: %s",
                    generation_id,
                    exc,
                )
                return usage
            await asyncio.sleep(0.25)
            return await lookup(attempt + 1)

    return await lookup(0)


def _ollama_token_usage(response: object) -> tuple[int, int]:
    """Pull (prompt, completion) token counts from an Ollama chat response, defensively."""
    usage = _ollama_usage(response)
    return usage.prompt_tokens, usage.completion_tokens


def _openrouter_token_usage(response: object) -> tuple[int, int]:
    """Pull (prompt, completion) token counts from an OpenRouter response, defensively."""
    usage = _openrouter_usage(response)
    return usage.prompt_tokens, usage.completion_tokens


def _record_llm_usage(provider: str, model: str, usage: LLMUsage) -> None:
    telemetry.record_llm_usage(
        provider,
        model,
        usage.prompt_tokens,
        usage.completion_tokens,
        total_tokens=usage.total_tokens,
        cost=usage.cost,
    )
    attrs = {
        "llm.tokens.available": usage.tokens_available,
        "llm.tokens.prompt": usage.prompt_tokens,
        "llm.tokens.completion": usage.completion_tokens,
        "llm.tokens.total": usage.total_tokens,
        "llm.cost.available": usage.cost_available,
    }
    if usage.cost:
        attrs["llm.cost"] = usage.cost
    telemetry.set_span_attributes(attrs)


def normalize_model(model: str | None) -> str:
    """Map legacy saved defaults to the current character-controller default."""

    if not model or model == LEGACY_DEFAULT_MODEL:
        return DEFAULT_MODEL
    return model


class CharacterAgent(Protocol):
    """Chooses the next action for a character.

    ``character_id`` identifies which character is deciding so stateful agents can keep
    per-character conversation history across turns. Provider-backed agents return an
    ``InvalidAgentResponse`` when the provider does not emit a structured tool call.
    Deterministic controllers may return ``None`` to hold for a turn.
    """

    async def decide(
        self,
        prompt: str,
        context: PromptContext,
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
        tools: list[dict] | None = None,
    ) -> AgentDecision: ...


class ScriptedAgent:
    """Replays a fixed sequence of tool calls.

    Yields ``None`` (wait) once the sequence is exhausted, unless ``loop`` is set, in which
    case it restarts from the beginning. An empty sequence always waits.
    """

    def __init__(self, calls: Iterable[ToolCall], *, loop: bool = False) -> None:
        self._calls = list(calls)
        self._loop = loop
        self._index = 0

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
BACKGROUND_PROFILES: frozenset[str] = frozenset({"idle", "social", "timid", "aggressive", "worker"})


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
        goal_decision = await self._goal_agent.decide(
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
        think: bool | Literal["low", "medium", "high"] | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        history_turns: int = 12,
        max_retries: int = DEFAULT_PROVIDER_RETRIES,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
        request_timeout_seconds: float | None = None,
        response_observer: OllamaResponseObserver | None = None,
        log_thinking: bool = False,
        reject_text_tool_calls: bool = True,
    ) -> None:
        try:
            import ollama
        except ImportError as exc:
            raise RuntimeError(
                "OllamaAgent requires the 'llm' extra: pip install bunnyland[llm]"
            ) from exc
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        client_cls = ollama.AsyncClient
        if host and request_timeout_seconds is not None:
            self._client = client_cls(
                host=host,
                headers=headers,
                timeout=request_timeout_seconds,
            )
        elif host:
            self._client = client_cls(host=host, headers=headers)
        elif request_timeout_seconds is not None:
            self._client = client_cls(timeout=request_timeout_seconds)
        else:
            self._client = client_cls()
        self._model = model
        self._think = think
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._history_turns = history_turns
        self._max_retries = max(0, max_retries)
        self._retry_delay_seconds = max(0.0, retry_delay_seconds)
        self._response_observer = response_observer
        self._log_thinking = log_thinking
        self._reject_text_tool_calls = reject_text_tool_calls
        # character_id -> running provider-native user/assistant/tool message history.
        self._history: dict[str, list[dict]] = {}
        # The authoritative visible result is available in PromptContext on the next turn.
        self._pending_tool_results: dict[str, str] = {}

    async def decide(
        self,
        prompt: str,
        context: PromptContext,
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
        tools: list[dict] | None = None,
    ) -> AgentDecision:
        del provider
        history = self._history.setdefault(character_id, [])
        pending_tool = self._pending_tool_results.pop(character_id, None)
        if pending_tool is not None:
            history.append(_ollama_tool_result_history(pending_tool, context))
        user_message = {"role": "user", "content": prompt}
        messages = [_character_system_message(), *history, user_message]
        resolved_model = normalize_model(model or self._model)
        resolved_tools = tools or tool_schemas()
        request_attrs = _llm_request_attrs(
            "character",
            resolved_model,
            messages,
            resolved_tools,
            system_prompt=CHARACTER_SYSTEM_PROMPT,
        )
        empty_responses = 0
        last_empty_response: object | None = None

        async def request():
            nonlocal empty_responses, last_empty_response
            response = await self._client.chat(
                model=resolved_model,
                messages=messages,
                tools=resolved_tools,
                **self._request_options(),
            )
            message = response["message"]
            if _provider_message_is_empty(message):
                empty_responses += 1
                last_empty_response = response
                raise _EmptyProviderResponseError("Ollama returned an empty assistant message")
            return response

        response = await _call_provider_with_retries(
            "ollama",
            request,
            max_retries=self._max_retries,
            empty_response_retries=EMPTY_RESPONSE_MAX_RETRIES,
            retry_delay_seconds=self._retry_delay_seconds,
            attributes=request_attrs,
        )
        if response is None:
            empty_attempts = EMPTY_RESPONSE_MAX_RETRIES + 1
            if empty_responses == empty_attempts:
                assert last_empty_response is not None
                self._observe_response(last_empty_response)
                return _empty_response_rejection("Ollama", empty_attempts)
            attempts = self._max_retries + 1
            return InvalidAgentResponse(
                reason="provider returned no response after retries",
                feedback=(
                    f"Invalid action response: Ollama returned no response after {attempts} "
                    "attempt(s), so no action was submitted. Return exactly one structured "
                    "tool call on this turn."
                ),
            )
        self._observe_response(response)
        _record_llm_usage("ollama", resolved_model, _ollama_usage(response))
        message = response["message"]
        tool_calls = message.get("tool_calls") or []
        content = str(message.get("content") or "").strip()
        if (
            self._reject_text_tool_calls
            and not tool_calls
            and contains_text_tool_call(content)
        ):
            telemetry.set_span_attributes({"llm.text_tool_call.rejected": True})
            messages = _text_tool_retry_messages(
                messages,
                content,
                tools_available=bool(resolved_tools),
                require_tool=True,
            )
            corrected_response = await _call_provider_with_retries(
                "ollama",
                request,
                max_retries=self._max_retries,
                empty_response_retries=EMPTY_RESPONSE_MAX_RETRIES,
                retry_delay_seconds=self._retry_delay_seconds,
                attributes=request_attrs,
            )
            if corrected_response is not None:
                self._observe_response(corrected_response)
                _record_llm_usage(
                    "ollama",
                    resolved_model,
                    _ollama_usage(corrected_response),
                )
                message = corrected_response["message"]
                tool_calls = message.get("tool_calls") or []
                content = str(message.get("content") or "").strip()
        history.append(user_message)
        history_message = _ollama_message_to_history(message)
        if contains_text_tool_call(content):
            history_message["content"] = ""
        history.append(history_message)
        if tool_calls:
            self._pending_tool_results[character_id] = str(
                tool_calls[0]["function"].get("name", "unknown")
            )
        self._trim(history)

        if not tool_calls:
            return _invalid_agent_response(message)
        call = tool_calls[0]["function"]
        return ToolCall(name=call["name"], arguments=dict(call.get("arguments", {})))

    async def chat(
        self,
        messages: list[dict],
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
        tools: list[dict] | None = None,
    ) -> ChatAgentReply:
        del character_id, provider
        resolved_model = normalize_model(model or self._model)
        resolved_tools = tools or []

        async def request_reply(
            request_messages: list[dict],
        ) -> ChatAgentReply | None:
            request_attrs = _llm_request_attrs(
                "character_chat",
                resolved_model,
                request_messages,
                resolved_tools,
                system_prompt=(
                    str(request_messages[0].get("content", ""))
                    if request_messages
                    else ""
                ),
            )

            async def request():
                return await self._client.chat(
                    model=resolved_model,
                    messages=request_messages,
                    tools=resolved_tools,
                    **self._request_options(),
                )

            response = await _call_provider_with_retries(
                "ollama",
                request,
                max_retries=self._max_retries,
                retry_delay_seconds=self._retry_delay_seconds,
                attributes=request_attrs,
            )
            if response is None:
                return None
            self._observe_response(response)
            _record_llm_usage("ollama", resolved_model, _ollama_usage(response))
            message = response["message"]
            content = str(message.get("content") or "").strip()
            tool_calls = message.get("tool_calls") or []
            tool_call = None
            if tool_calls:
                call = tool_calls[0]["function"]
                tool_call = ToolCall(
                    name=call["name"],
                    arguments=dict(call.get("arguments", {})),
                )
            return ChatAgentReply(content=content, tool_call=tool_call)

        return await _validated_chat_reply(
            request_reply,
            messages,
            tools_available=bool(resolved_tools),
            reject_text_tool_calls=self._reject_text_tool_calls,
        )

    def _request_options(self) -> dict[str, object]:
        options: dict[str, object] = {}
        if self._think is not None:
            options["think"] = self._think
        sampling_options: dict[str, float | int] = {}
        if self._temperature is not None:
            sampling_options["temperature"] = self._temperature
        if self._max_output_tokens is not None:
            sampling_options["num_predict"] = self._max_output_tokens
        if sampling_options:
            options["options"] = sampling_options
        return options

    async def close(self) -> None:
        """Release the provider client and any pending HTTP connection resources."""

        await self._client.close()

    def _observe_response(self, response: object) -> None:
        if self._response_observer is not None:
            self._response_observer(
                _ollama_response_json(response, include_thinking=self._log_thinking)
            )

    def _trim(self, history: list[dict]) -> None:
        _trim_history(history, self._history_turns)


class OpenRouterAgent:
    """Asks an OpenRouter model to pick one character action."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        server_url: str | None = None,
        reasoning: Literal["low", "medium", "high"] | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        history_turns: int = 12,
        max_retries: int = DEFAULT_PROVIDER_RETRIES,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
        response_observer: ProviderResponseObserver | None = None,
        log_thinking: bool = False,
        reject_text_tool_calls: bool = True,
    ) -> None:
        try:
            from openrouter import OpenRouter
        except ImportError as exc:
            raise RuntimeError(
                "OpenRouterAgent requires the 'llm' extra: pip install bunnyland[llm]"
            ) from exc
        kwargs = {"api_key": api_key}
        if server_url:
            kwargs["server_url"] = server_url
        self._client = OpenRouter(**kwargs)
        self._model = model
        self._reasoning = reasoning
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._history_turns = history_turns
        self._max_retries = max(0, max_retries)
        self._retry_delay_seconds = max(0.0, retry_delay_seconds)
        self._response_observer = response_observer
        self._log_thinking = log_thinking
        self._reject_text_tool_calls = reject_text_tool_calls
        self._history: dict[str, list[dict]] = {}
        self._pending_tool_results: dict[str, str] = {}

    async def decide(
        self,
        prompt: str,
        context: PromptContext,
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
        tools: list[dict] | None = None,
    ) -> AgentDecision:
        del provider
        history = self._history.setdefault(character_id, [])
        pending_tool_call_id = self._pending_tool_results.pop(character_id, None)
        if pending_tool_call_id is not None:
            history.append(_openrouter_tool_result_history(pending_tool_call_id, context))
        user_message = {"role": "user", "content": prompt}
        messages = [_character_system_message(), *history, user_message]
        resolved_model = normalize_model(model or self._model)
        resolved_tools = tools or tool_schemas()
        request_attrs = _llm_request_attrs(
            "character",
            resolved_model,
            messages,
            resolved_tools,
            system_prompt=CHARACTER_SYSTEM_PROMPT,
        )
        empty_responses = 0
        last_empty_response: object | None = None

        async def request():
            nonlocal empty_responses, last_empty_response
            response = await self._client.chat.send_async(
                model=resolved_model,
                messages=messages,
                tools=resolved_tools,
                **self._request_options(),
            )
            message = response.choices[0].message
            if _provider_message_is_empty(message):
                empty_responses += 1
                last_empty_response = response
                raise _EmptyProviderResponseError(
                    "OpenRouter returned an empty assistant message"
                )
            return response

        response = await _call_provider_with_retries(
            "openrouter",
            request,
            max_retries=self._max_retries,
            empty_response_retries=EMPTY_RESPONSE_MAX_RETRIES,
            retry_delay_seconds=self._retry_delay_seconds,
            attributes=request_attrs,
        )
        if response is None:
            empty_attempts = EMPTY_RESPONSE_MAX_RETRIES + 1
            if empty_responses == empty_attempts:
                assert last_empty_response is not None
                self._observe_response(last_empty_response)
                return _empty_response_rejection("OpenRouter", empty_attempts)
            attempts = self._max_retries + 1
            return InvalidAgentResponse(
                reason="provider returned no response after retries",
                feedback=(
                    f"Invalid action response: OpenRouter returned no response after {attempts} "
                    "attempt(s), so no action was submitted. Return exactly one structured "
                    "tool call on this turn."
                ),
            )
        self._observe_response(response)
        _record_llm_usage(
            "openrouter",
            resolved_model,
            await _openrouter_enriched_usage(self._client, response),
        )
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        content = str(getattr(message, "content", "") or "").strip()
        if (
            self._reject_text_tool_calls
            and not tool_calls
            and contains_text_tool_call(content)
        ):
            telemetry.set_span_attributes({"llm.text_tool_call.rejected": True})
            messages = _text_tool_retry_messages(
                messages,
                content,
                tools_available=bool(resolved_tools),
                require_tool=True,
            )
            corrected_response = await _call_provider_with_retries(
                "openrouter",
                request,
                max_retries=self._max_retries,
                empty_response_retries=EMPTY_RESPONSE_MAX_RETRIES,
                retry_delay_seconds=self._retry_delay_seconds,
                attributes=request_attrs,
            )
            if corrected_response is not None:
                self._observe_response(corrected_response)
                _record_llm_usage(
                    "openrouter",
                    resolved_model,
                    await _openrouter_enriched_usage(
                        self._client,
                        corrected_response,
                    ),
                )
                message = corrected_response.choices[0].message
                tool_calls = getattr(message, "tool_calls", None) or []
                content = str(getattr(message, "content", "") or "").strip()
        history.append(user_message)
        history_message = _message_to_history(message)
        if contains_text_tool_call(content):
            history_message["content"] = ""
        history.append(history_message)
        if tool_calls:
            tool_call_id = str(getattr(tool_calls[0], "id", "") or "")
            if not tool_call_id:
                invalid = InvalidAgentResponse(
                    reason="provider tool call contained no tool call id",
                    feedback=(
                        "Invalid action response: the structured tool call had no tool-call "
                        "id, so its authoritative result cannot be correlated. Return exactly "
                        "one complete structured tool call."
                    ),
                )
                self._trim(history)
                return invalid
            self._pending_tool_results[character_id] = tool_call_id
        self._trim(history)

        if not tool_calls:
            return _invalid_agent_response(message)
        function = tool_calls[0].function
        arguments = _openrouter_arguments(getattr(function, "arguments", {}))
        return ToolCall(name=function.name, arguments=arguments)

    async def chat(
        self,
        messages: list[dict],
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
        tools: list[dict] | None = None,
    ) -> ChatAgentReply:
        del character_id, provider
        resolved_model = normalize_model(model or self._model)
        resolved_tools = tools or []

        async def request_reply(
            request_messages: list[dict],
        ) -> ChatAgentReply | None:
            request_attrs = _llm_request_attrs(
                "character_chat",
                resolved_model,
                request_messages,
                resolved_tools,
                system_prompt=(
                    str(request_messages[0].get("content", ""))
                    if request_messages
                    else ""
                ),
            )

            async def request():
                return await self._client.chat.send_async(
                    model=resolved_model,
                    messages=request_messages,
                    tools=resolved_tools,
                    **self._request_options(),
                )

            response = await _call_provider_with_retries(
                "openrouter",
                request,
                max_retries=self._max_retries,
                retry_delay_seconds=self._retry_delay_seconds,
                attributes=request_attrs,
            )
            if response is None:
                return None
            self._observe_response(response)
            _record_llm_usage(
                "openrouter",
                resolved_model,
                await _openrouter_enriched_usage(self._client, response),
            )
            message = response.choices[0].message
            content = str(getattr(message, "content", "") or "").strip()
            tool_calls = getattr(message, "tool_calls", None) or []
            tool_call = None
            if tool_calls:
                function = tool_calls[0].function
                tool_call = ToolCall(
                    name=function.name,
                    arguments=_openrouter_arguments(
                        getattr(function, "arguments", {})
                    ),
                )
            return ChatAgentReply(content=content, tool_call=tool_call)

        return await _validated_chat_reply(
            request_reply,
            messages,
            tools_available=bool(resolved_tools),
            reject_text_tool_calls=self._reject_text_tool_calls,
        )

    def _request_options(self) -> dict[str, object]:
        options: dict[str, object] = {}
        if self._reasoning is not None:
            options["reasoning"] = {"effort": self._reasoning}
        if self._temperature is not None:
            options["temperature"] = self._temperature
        if self._max_output_tokens is not None:
            options["max_completion_tokens"] = self._max_output_tokens
        return options

    async def close(self) -> None:
        """Release the SDK's synchronous and asynchronous HTTP clients."""

        self._client.sdk_configuration.client.close()
        await self._client.sdk_configuration.async_client.aclose()

    def _observe_response(self, response: object) -> None:
        if self._response_observer is not None:
            self._response_observer(
                _openrouter_response_json(
                    response,
                    include_thinking=self._log_thinking,
                )
            )

    def _trim(self, history: list[dict]) -> None:
        _trim_history(history, self._history_turns)


class ProviderRouterAgent:
    """Routes decisions to the concrete agent named by a controller's provider."""

    def __init__(
        self, providers: MappingABC[str, CharacterAgent], *, default_provider: str = "ollama"
    ):
        self._providers = dict(providers)
        self._default_provider = default_provider

    async def decide(
        self,
        prompt: str,
        context: PromptContext,
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
        tools: list[dict] | None = None,
    ) -> AgentDecision:
        selected = provider or self._default_provider
        agent = self._providers.get(selected)
        if agent is None:
            available = ", ".join(sorted(self._providers)) or "(none)"
            raise RuntimeError(
                f"no LLM agent configured for provider {selected!r}; available: {available}"
            )
        return await agent.decide(
            prompt,
            context,
            character_id=character_id,
            model=model,
            provider=provider,
            tools=tools,
        )

    async def chat(
        self,
        messages: list[dict],
        *,
        character_id: str,
        model: str | None = None,
        provider: str | None = None,
        tools: list[dict] | None = None,
    ) -> ChatAgentReply:
        selected = provider or self._default_provider
        agent = self._providers.get(selected)
        if agent is None:
            available = ", ".join(sorted(self._providers)) or "(none)"
            raise RuntimeError(
                f"no LLM agent configured for provider {selected!r}; available: {available}"
            )
        chat = getattr(agent, "chat", None)
        if chat is None:
            raise RuntimeError(f"provider {selected!r} does not support character chat")
        return await chat(
            messages,
            character_id=character_id,
            model=model,
            provider=provider,
            tools=tools,
        )


class _EmptyProviderResponseError(RuntimeError):
    """A provider returned an assistant message with no content or tool call."""


def _provider_message_is_empty(message: object) -> bool:
    if isinstance(message, MappingABC):
        content = message.get("content")
        tool_calls = message.get("tool_calls")
    else:
        content = getattr(message, "content", None)
        tool_calls = getattr(message, "tool_calls", None)
    return not str(content or "").strip() and not tool_calls


def _empty_response_rejection(provider: str, attempts: int) -> InvalidAgentResponse:
    return InvalidAgentResponse(
        reason="provider returned empty response after retries",
        feedback=(
            f"Invalid action response: {provider} returned an empty assistant message on "
            f"{attempts} consecutive attempt(s), so no action was submitted. Return exactly "
            "one structured tool call using an available tool; call the wait tool to wait."
        ),
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
    if isinstance(exc, _EmptyProviderResponseError):
        return True
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
    empty_response_retries: int = 0,
    retry_delay_seconds: float,
    attributes: MappingABC[str, object] | None = None,
):
    last_exc: Exception | None = None
    base_attrs = {"provider": provider, **dict(attributes or {})}
    model_value = base_attrs.get("model")
    model = model_value if isinstance(model_value, str) else "unknown"
    attempts_made = 0
    attempt = 0
    while True:
        attempts_made = attempt + 1
        attempt_started = time.perf_counter()
        try:
            with telemetry.span(
                "llm.provider.attempt", {**base_attrs, "llm.attempt": attempt}
            ) as span:
                try:
                    result = await request()
                except Exception as exc:
                    telemetry.record_llm_request(
                        time.perf_counter() - attempt_started,
                        provider=provider,
                        model=model,
                        outcome="error",
                    )
                    span.record_exception(exc)
                    telemetry.mark_span_error(str(exc), span)
                    raise
                telemetry.mark_span_ok(span)
                telemetry.record_llm_request(
                    time.perf_counter() - attempt_started,
                    provider=provider,
                    model=model,
                    outcome="success",
                )
                return result
        except Exception as exc:
            if not _is_transient_provider_error(exc):
                raise
            last_exc = exc
            retry_limit = (
                empty_response_retries
                if isinstance(exc, _EmptyProviderResponseError)
                else max_retries
            )
            if attempt < retry_limit:
                logger.warning(
                    "%s provider transient error on attempt %s/%s; retrying: %s",
                    provider,
                    attempt + 1,
                    retry_limit + 1,
                    exc,
                )
                if retry_delay_seconds > 0:
                    await asyncio.sleep(retry_delay_seconds)
                attempt += 1
            else:
                break
    logger.warning(
        "%s provider failed after %s attempt%s; no response is available: %s",
        provider,
        attempts_made,
        "" if attempts_made == 1 else "s",
        last_exc,
    )
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


def _ollama_message_to_history(message: object) -> dict:
    if isinstance(message, MappingABC):
        return _JSON_OBJECT.validate_python(dict(message))
    return _JSON_OBJECT.validate_python(_message_to_history(message))


def _tool_result_content(context: PromptContext | None) -> str:
    perceived_events = context.perceived_events if context is not None else ()
    events: list[JsonValue] = [
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "world_epoch": event.world_epoch,
            "summary": event.summary,
        }
        for event in perceived_events
    ]
    payload: dict[str, JsonValue] = {
        "events": events,
        "omitted_event_count": context.omitted_perceived_events if context is not None else 0,
        "warnings": list(context.warnings) if context is not None else [],
    }
    if context is not None and context.omitted_event_epoch_range is not None:
        payload["omitted_event_epoch_range"] = list(context.omitted_event_epoch_range)
    return json.dumps(payload, sort_keys=True)


def _ollama_tool_result_history(tool_name: str, context: PromptContext | None) -> dict:
    return {
        "role": "tool",
        "tool_name": tool_name,
        "content": _tool_result_content(context),
    }


def _openrouter_tool_result_history(tool_call_id: str, context: PromptContext | None) -> dict:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": _tool_result_content(context),
    }


def _invalid_agent_response(message: object) -> InvalidAgentResponse:
    history = _ollama_message_to_history(message)
    content = str(history.get("content") or "").strip()
    excerpt = content[:1_000]
    if len(content) > len(excerpt):
        excerpt = f"{excerpt}..."
    detail = json.dumps(excerpt or "<empty>")
    if contains_text_tool_call(content):
        reason = "provider response wrote a tool call as message text"
        feedback = (
            f"Invalid action response: {reason}. The assistant content was {detail}. "
            "Tagged text does not execute an action. Return exactly one native structured "
            "tool call using an available tool; call the wait tool to wait."
        )
    else:
        reason = "provider response contained no structured tool call"
        feedback = (
            f"Invalid action response: {reason}. The assistant content was {detail}. "
            "Prose such as 'Selected tool ...' does not execute an action. Return exactly "
            "one structured tool call using an available tool; call the wait tool to wait."
        )
    return InvalidAgentResponse(reason=reason, feedback=feedback)


def _trim_history(history: list[dict], history_turns: int) -> None:
    user_indexes = [
        index for index, message in enumerate(history) if message.get("role") == "user"
    ]
    if len(user_indexes) <= history_turns:
        return
    del history[: user_indexes[-history_turns]]


def _character_system_message() -> dict:
    return {"role": "system", "content": CHARACTER_SYSTEM_PROMPT}


def _llm_request_attrs(
    request_kind: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    *,
    system_prompt: str,
) -> dict[str, object]:
    return {
        "model": model,
        "llm.request.kind": request_kind,
        "llm.tools.count": len(tools or []),
        "llm.history.messages": len(messages),
        "llm.system_prompt_chars": len(system_prompt),
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
    "CHARACTER_SYSTEM_PROMPT",
    "Agent",
    "AgentDecision",
    "BACKGROUND_PROFILES",
    "BackgroundProfile",
    "ChatAgentReply",
    "BehaviorProfileAgent",
    "CharacterAgent",
    "GoalDirectedAgent",
    "InvalidAgentResponse",
    "OpenRouterAgent",
    "OllamaAgent",
    "ProviderRouterAgent",
    "ScriptedAgent",
    "normalize_model",
]
