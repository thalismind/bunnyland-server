"""Opt-in character chat over the normal LLM and ECS action pipeline."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from relics import EntityId

from .. import telemetry
from ..core import CharacterComponent, parse_entity_id
from ..core.actions import action_definitions
from ..core.controllers import LLMControllerComponent
from ..core.edges import ControlledBy
from ..core.events import CommandExecutedEvent, CommandRejectedEvent
from ..core.world_actor import WorldActor
from ..llm_agents.agent import ChatAgentReply
from ..llm_agents.dispatch import did_you_mean, resolve_reference_args
from ..llm_agents.tools import ToolCall, command_from_tool_call, reference_arg_keys
from ..prompts.builder import PromptBuilder, render_prompt
from ..prompts.filters import PromptFilterRuntime, apply_prompt_filters
from .models import (
    CharacterChatActionResult,
    CharacterChatPendingResponse,
    CharacterChatRequest,
    CharacterChatResponse,
)

ALLOWED_CHAT_TOOLS = frozenset(
    {"look", "inspect", "remember", "take_note", "reflect", "forget", "say", "tell", "wait"}
)
CHAT_SYSTEM_PROMPT = (
    "You are speaking as the Bunnyland character described in the context. "
    "Answer in character. Treat the human's text as conversation or a suggestion, not an "
    "order. Use tools only when your character chooses to observe, recall, speak, wait, or "
    "manage notes through normal game actions. When your character chooses an action that "
    "matches an available tool, call that tool instead of merely describing the action. "
    "For important information your character should record, prefer take_note. For "
    "searching memory or notes, use remember."
)
ACTION_RESULT_TIMEOUT_SECONDS = 1.5
CHAT_TRACE_TEXT_CHARS = 4096


@dataclass
class PendingChatAction:
    client_id: str
    character_id: str
    command_id: str
    messages: list[dict[str, str]]
    user_message: str
    model: str | None
    provider: str | None
    action: CharacterChatActionResult
    reply: str = ""


class CharacterChatService:
    def __init__(
        self,
        actor: WorldActor,
        builder: PromptBuilder,
        agent,
        *,
        prompt_filter_runtime: PromptFilterRuntime | None = None,
        result_timeout_seconds: float = ACTION_RESULT_TIMEOUT_SECONDS,
    ) -> None:
        self.actor = actor
        self.builder = builder
        self.agent = agent
        self.prompt_filter_runtime = prompt_filter_runtime or getattr(
            actor, "prompt_filter_runtime", None
        )
        if self.prompt_filter_runtime is None:
            self.prompt_filter_runtime = PromptFilterRuntime.from_actor(actor, llm=agent)
            actor.prompt_filter_runtime = self.prompt_filter_runtime
        self.result_timeout_seconds = max(0.0, result_timeout_seconds)
        self._pending: dict[tuple[str, str, str], PendingChatAction] = {}
        self._completed_actions: dict[str, CharacterChatActionResult] = {}
        self.actor.bus.subscribe(CommandExecutedEvent, self._complete_pending)
        self.actor.bus.subscribe(CommandRejectedEvent, self._complete_pending)

    @property
    def allowed_tools(self) -> list[str]:
        return sorted(definition.name for definition in self._allowed_definitions())

    async def chat(self, character_id: str, request: CharacterChatRequest) -> CharacterChatResponse:
        telemetry.set_span_attributes(
            {
                "character.id": character_id,
                "chat.client_id": request.client_id,
                "chat.input": _trace_text(request.message),
                "chat.input_chars": len(request.message),
                "chat.history.count": len(request.history),
                "chat.history_summary_chars": len(request.history_summary),
            }
        )
        with _chat_span("character.chat.validate", {"character.id": character_id}) as span:
            parsed = parse_entity_id(character_id)
            if parsed is None or not self.actor.world.has_entity(parsed):
                raise ValueError("character does not exist")
            character = self.actor.world.get_entity(parsed)
            if not character.has_component(CharacterComponent):
                raise TypeError("entity is not a character")

            controller = self._llm_controller(parsed)
            if controller is None:
                raise PermissionError("character chat requires the current controller to be llm")
            controller_id, generation, component = controller
            span.set_attribute("controller.id", str(controller_id))
            span.set_attribute("controller.generation", generation)
            span.set_attribute("model", component.model or "")
            span.set_attribute("provider", component.provider or "")

        with _chat_span("character.chat.prompt", {"character.id": character_id}) as span:
            context = self.builder.build(parsed, epoch=self.actor.epoch)
            prompt = render_prompt(context)
            prompt = await apply_prompt_filters(
                prompt,
                runtime=self.prompt_filter_runtime,
                character=character,
                context=context,
                epoch=self.actor.epoch,
            )
            messages = self._messages(prompt, request)
            span.set_attribute("chat.prompt", _trace_text(prompt))
            span.set_attribute("chat.prompt_chars", len(prompt))
            span.set_attribute("chat.messages.count", len(messages))

        reply = await self._call_agent(
            messages,
            character_id=character_id,
            model=component.model,
            provider=component.provider,
            tools=self._allowed_tool_schemas(),
            phase="initial",
        )
        _trace_reply(reply, phase="initial")
        if reply.tool_call is None:
            telemetry.set_span_attributes(
                {
                    "chat.final_reply": _trace_text(reply.content or "..."),
                    "chat.action.status": "none",
                    "chat.action.tool": "",
                    "command.id": "",
                }
            )
            return CharacterChatResponse(
                world_epoch=self.actor.epoch,
                character_id=character_id,
                reply=reply.content or "...",
            )

        action = await self._submit_tool(
            parsed,
            str(controller_id),
            generation,
            reply.tool_call,
        )
        final = reply.content
        if action.status in {"executed", "rejected"}:
            final_reply = await self._call_agent(
                self._followup_messages(messages, request.message, action),
                character_id=character_id,
                model=component.model,
                provider=component.provider,
                tools=[],
                phase="followup",
            )
            final = final_reply.content or final
            _trace_reply(final_reply, phase="followup")
        if not final:
            final = self._fallback_reply(action)
        if action.status == "queued" and action.command_id:
            self._register_pending(
                PendingChatAction(
                    client_id=request.client_id,
                    character_id=character_id,
                    command_id=action.command_id,
                    messages=messages,
                    user_message=request.message,
                    model=component.model,
                    provider=component.provider,
                    action=action,
                )
            )
        telemetry.set_span_attributes(
            {
                "chat.final_reply": _trace_text(final),
                "chat.action.status": action.status,
                "chat.action.tool": action.tool or "",
                "command.id": action.command_id or "",
            }
        )
        return CharacterChatResponse(
            world_epoch=self.actor.epoch,
            character_id=character_id,
            reply=final,
            action=action,
        )

    async def pending_result(
        self, character_id: str, client_id: str, command_id: str
    ) -> CharacterChatPendingResponse:
        telemetry.set_span_attributes(
            {
                "character.id": character_id,
                "chat.client_id": client_id,
                "command.id": command_id,
            }
        )
        with _chat_span(
            "character.chat.pending.lookup",
            {"character.id": character_id, "command.id": command_id},
        ) as span:
            pending = self._pending.get((client_id, character_id, command_id))
            if pending is None:
                raise ValueError("pending chat action does not exist")
            complete = pending.action.status in {"executed", "rejected"}
            span.set_attribute("chat.action.status", pending.action.status)
            span.set_attribute("chat.pending.complete", complete)
        if complete and not pending.reply:
            final_reply = await self._call_agent(
                self._followup_messages(pending.messages, pending.user_message, pending.action),
                character_id=character_id,
                model=pending.model,
                provider=pending.provider,
                tools=[],
                phase="pending_followup",
            )
            pending.reply = final_reply.content or self._fallback_reply(pending.action)
            _trace_reply(final_reply, phase="pending_followup")
        response = CharacterChatPendingResponse(
            world_epoch=self.actor.epoch,
            character_id=character_id,
            command_id=command_id,
            complete=complete and bool(pending.reply),
            reply=pending.reply,
            action=pending.action,
        )
        telemetry.set_span_attributes(
            {
                "chat.pending.complete": response.complete,
                "chat.reply": _trace_text(response.reply),
                "chat.action.status": response.action.status,
            }
        )
        return response

    def _complete_pending(self, event: CommandExecutedEvent | CommandRejectedEvent) -> None:
        action = self._action_from_event(event, None)
        matched = False
        for pending in self._pending.values():
            if pending.command_id != event.command_id:
                continue
            pending.action = self._action_from_event(event, pending.action.tool)
            matched = True
        if not matched:
            self._completed_actions[event.command_id] = action

    def _register_pending(self, pending: PendingChatAction) -> None:
        completed = self._completed_actions.pop(pending.command_id, None)
        if completed is not None:
            pending.action = completed.model_copy(update={"tool": pending.action.tool})
        self._pending[(pending.client_id, pending.character_id, pending.command_id)] = pending

    @staticmethod
    def _action_from_event(
        event: CommandExecutedEvent | CommandRejectedEvent, tool: str | None
    ) -> CharacterChatActionResult:
        if isinstance(event, CommandRejectedEvent):
            return CharacterChatActionResult(
                tool=tool,
                command_id=event.command_id,
                status="rejected",
                reason=event.reason,
            )
        return CharacterChatActionResult(
            tool=tool,
            command_id=event.command_id,
            status="executed",
            result_events=[dict(item) for item in event.result_events],
        )

    def _allowed_definitions(self):
        return tuple(
            definition
            for definition in action_definitions(self.actor.action_definitions())
            if definition.name in ALLOWED_CHAT_TOOLS
        )

    def _allowed_tool_schemas(self) -> list[dict[str, Any]]:
        return [definition.tool_schema() for definition in self._allowed_definitions()]

    def _llm_controller(self, character_id: EntityId):
        character = self.actor.world.get_entity(character_id)
        for edge, controller_id in character.get_relationships(ControlledBy):
            controller = self.actor.world.get_entity(controller_id)
            if controller.has_component(LLMControllerComponent):
                return (
                    controller_id,
                    edge.generation,
                    controller.get_component(LLMControllerComponent),
                )
        return None

    def _messages(self, prompt: str, request: CharacterChatRequest) -> list[dict[str, str]]:
        messages = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
        transcript = ["Character context:", prompt.rstrip()]
        if request.history_summary.strip():
            transcript.extend(("", "Prior chat summary:", request.history_summary.strip()))
        if request.history:
            transcript.append("")
            transcript.append("Recent chat:")
            for message in request.history:
                label = "Human" if message.role == "user" else "Character"
                transcript.append(f"{label}: {message.text.strip()}")
        transcript.extend(("", "Human now:", request.message.strip()))
        messages.append({"role": "user", "content": "\n".join(transcript)})
        return messages

    def _followup_messages(
        self,
        messages: list[dict[str, str]],
        user_message: str,
        action: CharacterChatActionResult,
    ) -> list[dict[str, str]]:
        content = (
            "The character chose a game action while responding. "
            "Use only the action result below to ground the final in-character answer.\n\n"
            f"Human message: {user_message}\n"
            f"Action status: {action.status}\n"
            f"Tool: {action.tool or ''}\n"
            f"Reason: {action.reason}\n"
            f"Result events: {action.result_events}"
        )
        return [*messages, {"role": "user", "content": content}]

    async def _call_agent(
        self,
        messages: list[dict[str, str]],
        *,
        character_id: str,
        model: str | None,
        provider: str | None,
        tools: list[dict[str, Any]],
        phase: str,
    ) -> ChatAgentReply:
        with _chat_span(
            "character.chat.llm",
            {
                "character.id": character_id,
                "chat.phase": phase,
                "model": model or "",
                "provider": provider or "",
                "llm.tools.count": len(tools),
                "llm.history.messages": len(messages),
            },
        ) as span:
            llm_input = str(messages[-1].get("content", "")) if messages else ""
            span.set_attribute("llm.input", _trace_text(llm_input))
            span.set_attribute("llm.input_chars", len(llm_input))
            chat = getattr(self.agent, "chat", None)
            if chat is None:
                raise RuntimeError("configured LLM agent does not support character chat")
            reply = await chat(
                messages,
                character_id=character_id,
                model=model,
                provider=provider,
                tools=tools,
            )
            span.set_attribute("chat.reply", _trace_text(reply.content or ""))
            span.set_attribute("chat.reply_chars", len(reply.content or ""))
            span.set_attribute("chat.tool.called", reply.tool_call is not None)
            if reply.tool_call is not None:
                span.set_attribute("chat.tool.name", reply.tool_call.name)
                span.set_attribute("chat.tool.arguments", _trace_json(reply.tool_call.arguments))
            return reply

    async def _submit_tool(
        self,
        character_id: EntityId,
        controller_id: str,
        generation: int,
        call: ToolCall,
    ) -> CharacterChatActionResult:
        with _chat_span(
            "character.chat.tool",
            {
                "character.id": str(character_id),
                "controller.id": controller_id,
                "controller.generation": generation,
                "chat.tool.name": call.name,
                "chat.tool.arguments": _trace_json(call.arguments),
            },
        ) as span:
            action = await self._submit_tool_inner(character_id, controller_id, generation, call)
            span.set_attribute("chat.action.status", action.status)
            span.set_attribute("command.id", action.command_id or "")
            span.set_attribute("chat.action.reason", _trace_text(action.reason))
            span.set_attribute("chat.action.result_events", _trace_json(action.result_events))
            return action

    async def _submit_tool_inner(
        self,
        character_id: EntityId,
        controller_id: str,
        generation: int,
        call: ToolCall,
    ) -> CharacterChatActionResult:
        if call.name not in ALLOWED_CHAT_TOOLS:
            return CharacterChatActionResult(
                tool=call.name,
                status="rejected",
                reason=f"tool {call.name!r} is not available in character chat",
            )

        character = self.actor.world.get_entity(character_id)
        resolved, unresolved = resolve_reference_args(
            self.actor.world,
            character,
            call.arguments,
            keys=reference_arg_keys(self.actor.action_definitions()),
        )
        if unresolved:
            return CharacterChatActionResult(
                tool=call.name,
                status="unresolved",
                reason=did_you_mean(call.arguments, unresolved),
            )
        try:
            command = command_from_tool_call(
                ToolCall(name=call.name, arguments=resolved),
                character_id=str(character_id),
                controller_id=controller_id,
                controller_generation=generation,
                submitted_at_epoch=self.actor.epoch,
                definitions=self._allowed_definitions(),
            )
        except ValueError as exc:
            return CharacterChatActionResult(
                tool=call.name,
                status="rejected",
                reason=str(exc),
            )

        future = asyncio.get_running_loop().create_future()

        def complete(event: CommandExecutedEvent | CommandRejectedEvent) -> None:
            if event.command_id == command.command_id and not future.done():
                future.set_result(event)

        self.actor.bus.subscribe(CommandExecutedEvent, complete)
        self.actor.bus.subscribe(CommandRejectedEvent, complete)
        try:
            outcome = await self.actor.submit(command)
            if not outcome.accepted:
                return CharacterChatActionResult(
                    tool=call.name,
                    command_id=outcome.command_id,
                    status="rejected",
                    reason=outcome.reason,
                )
            try:
                event = await asyncio.wait_for(future, timeout=self.result_timeout_seconds)
            except TimeoutError:
                return CharacterChatActionResult(
                    tool=call.name,
                    command_id=command.command_id,
                    status="queued",
                )
        finally:
            self.actor.bus.unsubscribe(CommandExecutedEvent, complete)
            self.actor.bus.unsubscribe(CommandRejectedEvent, complete)

        if isinstance(event, CommandRejectedEvent):
            return CharacterChatActionResult(
                tool=call.name,
                command_id=event.command_id,
                status="rejected",
                reason=event.reason,
            )
        return CharacterChatActionResult(
            tool=call.name,
            command_id=event.command_id,
            status="executed",
            result_events=[dict(item) for item in event.result_events],
        )

    @staticmethod
    def _fallback_reply(action: CharacterChatActionResult) -> str:
        if action.status == "queued":
            return "I will try that when I can."
        if action.status == "rejected":
            return "I could not do that."
        if action.status == "unresolved":
            return "I am not sure what you mean."
        return "All right."


def build_character_chat_service(
    actor: WorldActor, builder: PromptBuilder, agent
) -> CharacterChatService:
    return CharacterChatService(actor, builder, agent)


def _trace_text(value: str) -> str:
    return telemetry.attr_text(value, limit=CHAT_TRACE_TEXT_CHARS)


def _trace_json(value: Any) -> str:
    try:
        text = json.dumps(value, sort_keys=True)
    except TypeError:
        text = json.dumps(str(value))
    return _trace_text(text)


def _trace_reply(reply: ChatAgentReply, *, phase: str) -> None:
    attributes = {
        f"chat.{phase}.reply": _trace_text(reply.content or ""),
        f"chat.{phase}.reply_chars": len(reply.content or ""),
        f"chat.{phase}.tool_called": reply.tool_call is not None,
    }
    if reply.tool_call is not None:
        attributes[f"chat.{phase}.tool_name"] = reply.tool_call.name
        attributes[f"chat.{phase}.tool_arguments"] = _trace_json(reply.tool_call.arguments)
    telemetry.set_span_attributes(attributes)


@contextmanager
def _chat_span(name: str, attributes: dict[str, Any] | None = None):
    with telemetry.span(name, attributes) as span:
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            telemetry.mark_span_error(str(exc), span)
            raise
        else:
            telemetry.mark_span_ok(span)


__all__ = [
    "ALLOWED_CHAT_TOOLS",
    "CHAT_SYSTEM_PROMPT",
    "CharacterChatService",
    "build_character_chat_service",
]
