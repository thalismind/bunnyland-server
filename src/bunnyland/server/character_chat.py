"""Opt-in character chat over the normal LLM and ECS action pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any

from relics import EntityId

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
from .models import (
    CharacterChatActionResult,
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
    "manage notes through normal game actions."
)
ACTION_RESULT_TIMEOUT_SECONDS = 1.5


class CharacterChatService:
    def __init__(
        self,
        actor: WorldActor,
        builder: PromptBuilder,
        agent,
        *,
        result_timeout_seconds: float = ACTION_RESULT_TIMEOUT_SECONDS,
    ) -> None:
        self.actor = actor
        self.builder = builder
        self.agent = agent
        self.result_timeout_seconds = max(0.0, result_timeout_seconds)

    @property
    def allowed_tools(self) -> list[str]:
        return sorted(definition.name for definition in self._allowed_definitions())

    async def chat(self, character_id: str, request: CharacterChatRequest) -> CharacterChatResponse:
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

        context = self.builder.build(parsed, epoch=self.actor.epoch)
        messages = self._messages(render_prompt(context), request)
        reply = await self._call_agent(
            messages,
            character_id=character_id,
            model=component.model,
            provider=component.provider,
            tools=self._allowed_tool_schemas(),
        )
        if reply.tool_call is None:
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
            )
            final = final_reply.content or final
        if not final:
            final = self._fallback_reply(action)
        return CharacterChatResponse(
            world_epoch=self.actor.epoch,
            character_id=character_id,
            reply=final,
            action=action,
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
                return controller_id, edge.generation, controller.get_component(
                    LLMControllerComponent
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
    ) -> ChatAgentReply:
        chat = getattr(self.agent, "chat", None)
        if chat is None:
            raise RuntimeError("configured LLM agent does not support character chat")
        result = chat(
            messages,
            character_id=character_id,
            model=model,
            provider=provider,
            tools=tools,
        )
        if isinstance(result, Awaitable):
            return await result
        return result

    async def _submit_tool(
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


__all__ = [
    "ALLOWED_CHAT_TOOLS",
    "CHAT_SYSTEM_PROMPT",
    "CharacterChatService",
    "build_character_chat_service",
]
