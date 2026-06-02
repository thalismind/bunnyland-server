"""Discord controller front-end (spec 24). Optional: requires the ``discord`` extra.

Discord users drive characters through the same verb surface the LLM uses. A slash command
becomes a ``SubmittedCommand`` routed to that user's character; the world lane (move, take,
say) is public, while focus actions (notes, remember) are offered over DM. The bot only
translates input and relays events — it never touches the ECS directly (spec 24.2).

Humans, like the LLM, refer to things by name; the bot resolves those names to entity ids
the same way dispatch does, and replies with a "did you mean..." hint when it can't.

The ``DiscordBot`` class is import-guarded and not exercised by the unit tests; the pure
name-resolution helpers below are.
"""

from __future__ import annotations

import asyncio
import json
import shlex
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from ..core.commands import CommandCost, Lane, OnInsufficientPoints, build_submitted_command
from ..core.controllers import DiscordControllerComponent
from ..core.events import (
    CommandExecutedEvent,
    CommandRejectedEvent,
    NotesSearchedEvent,
    WorldPauseStatusChangedEvent,
)
from ..core.world_actor import WorldActor
from ..llm_agents import DEFAULT_MODEL
from ..llm_agents.dispatch import did_you_mean, resolve_reference_args
from ..llm_agents.natural_language import parse_natural_command
from ..llm_agents.tools import (
    ToolCall,
    command_from_tool_call,
    command_type_for_tool,
    tool_arg_keys,
    tool_for_command_type,
    tool_names,
)
from .claim import (
    assign_discord_controller,
    discord_controlled_character,
    release_discord_character_to_llm,
    render_character_list,
    suspend_discord_character,
)
from .view import (
    render_action_result,
    render_help,
    render_look,
    render_notes_search_result,
    split_discord_text,
)

MOVE_RESULT_TIMEOUT_SECONDS = 120.0

#: Reaction added to a player's message once their command is accepted and queued.
QUEUED_REACTION = "\N{HOURGLASS WITH FLOWING SAND}"
PAUSED_REACTION = "\N{DOUBLE VERTICAL BAR}\N{VARIATION SELECTOR-16}"
META_COMMANDS = frozenset({"help", "claim", "characters", "look", "release", "suspend"})


@dataclass(frozen=True)
class DiscordAction:
    command_type: str
    payload: dict[str, Any]
    tool: str | None = None


def _require_discord():  # pragma: no cover - exercised only with the extra
    try:
        import discord
        from discord.ext import commands
    except ImportError as exc:
        raise RuntimeError(
            "the Discord bot requires the 'discord' extra: pip install bunnyland[discord]"
        ) from exc
    return discord, commands


def _split(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _parse_scalar(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _parse_structured_payload(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return {}
    if stripped.startswith("{"):
        parsed = json.loads(stripped)
        if not isinstance(parsed, dict):
            raise ValueError("JSON command payload must be an object")
        return parsed
    words = _split(stripped)
    if words and all("=" in word for word in words):
        payload: dict[str, Any] = {}
        for word in words:
            key, value = word.split("=", 1)
            payload[key] = (
                [item for item in value.split(",") if item]
                if key == "tags"
                else _parse_scalar(value)
            )
        return payload
    return None


def _payload_from_text(text: str, arg_keys: tuple[str, ...]) -> dict[str, Any]:
    structured = _parse_structured_payload(text)
    if structured is not None:
        return structured
    if not arg_keys:
        raise ValueError("Use key=value pairs or a JSON object for this verb")
    return {arg_keys[0]: text.strip()}


def _with_discord_defaults(action: DiscordAction) -> DiscordAction:
    if action.command_type != "remember":
        return action
    payload = dict(action.payload)
    if payload.get("query") and not payload.get("mode"):
        payload["mode"] = "vector"
    return replace(action, payload=payload)


def parse_discord_action(text: str, available_commands: tuple[str, ...]) -> DiscordAction:
    """Parse a Discord ``!`` action against the live world verb set."""

    available = set(available_commands)
    words = _split(text.strip())
    if not words:
        raise ValueError("No command provided")
    typed = words[0].lower()
    rest = text.strip()[len(words[0]) :].strip()
    command_type = typed.replace("_", "-")
    tool = typed.replace("-", "_")
    structured = bool(rest) and _parse_structured_payload(rest) is not None

    if not structured:
        natural = parse_natural_command(text)
        if natural is not None:
            natural_command_type = command_type_for_tool(natural.name)
            if natural_command_type in available:
                return _with_discord_defaults(
                    DiscordAction(
                        command_type=natural_command_type,
                        payload=natural.arguments,
                        tool=natural.name,
                    )
                )

    if tool in tool_names():
        mapped = command_type_for_tool(tool)
        if mapped in available:
            return _with_discord_defaults(
                DiscordAction(mapped, _payload_from_text(rest, tool_arg_keys(tool)), tool=tool)
            )
    if command_type in available:
        mapped_tool = tool_for_command_type(command_type)
        if mapped_tool is not None:
            return _with_discord_defaults(
                DiscordAction(
                    command_type,
                    _payload_from_text(rest, tool_arg_keys(mapped_tool)),
                    tool=mapped_tool,
                )
            )
        return DiscordAction(command_type, _payload_from_text(rest, ()))

    raise ValueError(f"Unknown world verb `{typed}`. Use `!help verbs` to see available verbs.")


def discord_broadcast_channel_ids(actor: WorldActor) -> tuple[int, ...]:
    """Return unique Discord channels attached through controller defaults."""

    channel_ids: set[int] = set()
    controllers = actor.world.query().with_all([DiscordControllerComponent]).execute_entities()
    for controller in controllers:
        channel_id = controller.get_component(
            DiscordControllerComponent
        ).default_channel_id
        if channel_id:
            channel_ids.add(channel_id)
    return tuple(sorted(channel_ids))


class DiscordBot:  # pragma: no cover - needs network + extra
    """Maps Discord slash commands to character verbs for the controlling user."""

    def __init__(
        self,
        actor: WorldActor,
        *,
        token: str,
        allow_child_claims: bool = False,
        llm_provider: str = "ollama",
        character_model: str = DEFAULT_MODEL,
        pause_status: Callable[[], bool] | None = None,
    ) -> None:
        discord, commands = _require_discord()
        self.actor = actor
        self.token = token
        self.allow_child_claims = allow_child_claims
        self.llm_provider = llm_provider
        self.character_model = character_model
        self._pause_status = pause_status
        self._world_paused = pause_status() if pause_status is not None else False
        intents = discord.Intents.default()
        intents.message_content = True  # required to read "!" command text
        self.client = commands.Bot(command_prefix="!", intents=intents, help_command=None)
        self._pending: dict[str, asyncio.Future[CommandExecutedEvent | CommandRejectedEvent]] = {}
        self._paused_reactions: dict[str, Any] = {}
        self.actor.bus.subscribe(CommandExecutedEvent, self._complete_pending)
        self.actor.bus.subscribe(CommandRejectedEvent, self._complete_pending)
        self.actor.bus.subscribe(WorldPauseStatusChangedEvent, self._post_pause_status)
        self._register_commands()

    def _character_for_user(self, discord_user_id: int):
        """Find the character controlled by a Discord controller for this user."""
        return discord_controlled_character(self.actor, discord_user_id)

    def _complete_pending(self, event: CommandExecutedEvent | CommandRejectedEvent) -> None:
        future = self._pending.pop(event.command_id, None)
        self._paused_reactions.pop(event.command_id, None)
        if future is not None and not future.done():
            future.set_result(event)

    def _is_world_paused(self) -> bool:
        if self._pause_status is not None:
            return self._pause_status()
        return self._world_paused

    async def _post_pause_status(self, event: WorldPauseStatusChangedEvent) -> None:
        self._world_paused = event.paused
        if not event.paused:
            await self._replace_paused_reactions()
        for channel_id in discord_broadcast_channel_ids(self.actor):
            channel = self.client.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.client.fetch_channel(channel_id)
                except Exception as exc:
                    print(
                        f"Discord pause status post failed for channel {channel_id}: {exc!r}",
                        flush=True,
                    )
                    continue
            try:
                await channel.send(event.message)
            except Exception as exc:
                print(
                    f"Discord pause status post failed for channel {channel_id}: {exc!r}",
                    flush=True,
                )

    async def _replace_paused_reactions(self) -> None:
        for message in tuple(self._paused_reactions.values()):
            try:
                await message.remove_reaction(PAUSED_REACTION, self.client.user)
            except Exception:  # pragma: no cover - best effort, missing perms are common
                pass
            try:
                await message.add_reaction(QUEUED_REACTION)
            except Exception:  # pragma: no cover - reaction is best-effort
                pass
        self._paused_reactions.clear()

    async def _build_command(self, discord_user_id: int, action: DiscordAction):
        found = self._character_for_user(discord_user_id)
        if found is None:
            return None, "You are not controlling a character yet."
        character_id, controller_id, generation = found

        character = self.actor.world.get_entity(character_id)
        resolved, unresolved = resolve_reference_args(self.actor.world, character, action.payload)
        if unresolved:
            return None, did_you_mean(action.payload, unresolved)

        if action.tool is not None:
            command = command_from_tool_call(
                ToolCall(name=action.tool, arguments=resolved),
                character_id=str(character_id),
                controller_id=str(controller_id),
                controller_generation=generation,
                submitted_at_epoch=self.actor.epoch,
            )
        else:
            command = build_submitted_command(
                character_id=str(character_id),
                controller_id=str(controller_id),
                controller_generation=generation,
                command_type=action.command_type,
                cost=CommandCost(action=1),
                lane=Lane.WORLD,
                payload=resolved,
                submitted_at_epoch=self.actor.epoch,
            )
        return command, None

    @staticmethod
    async def _acknowledge_queued(ctx, reaction: str) -> None:
        """React to the player's message so they see their command was accepted."""
        try:
            await ctx.message.add_reaction(reaction)
        except Exception:  # pragma: no cover - reaction is best-effort (e.g. missing perms)
            pass

    async def _submit_action(self, ctx, action: DiscordAction) -> str:
        command, error = await self._build_command(ctx.author.id, action)
        if error is not None:
            return error
        command = replace(command, on_insufficient_points=OnInsufficientPoints.DENY)
        future = asyncio.get_running_loop().create_future()
        notes_future = asyncio.get_running_loop().create_future()

        def capture_notes(event: NotesSearchedEvent) -> None:
            if event.actor_id == command.character_id and not notes_future.done():
                notes_future.set_result(event)

        if command.command_type == "remember":
            self.actor.bus.subscribe(NotesSearchedEvent, capture_notes)
        self._pending[command.command_id] = future
        try:
            await self.actor.submit(command)
            if self._is_world_paused():
                await self._acknowledge_queued(ctx, PAUSED_REACTION)
                self._paused_reactions[command.command_id] = ctx.message
            else:
                await self._acknowledge_queued(ctx, QUEUED_REACTION)
            event = await asyncio.wait_for(future, timeout=MOVE_RESULT_TIMEOUT_SECONDS)
            if command.command_type == "remember" and isinstance(event, CommandExecutedEvent):
                notes = await asyncio.wait_for(notes_future, timeout=1.0)
                return render_notes_search_result(notes)
        except TimeoutError:
            self._pending.pop(command.command_id, None)
            return (
                f"{command.command_type.replace('-', ' ').capitalize()} queued, "
                "but it has not run yet."
            )
        finally:
            if command.command_type == "remember":
                self.actor.bus.unsubscribe(NotesSearchedEvent, capture_notes)
        return render_action_result(
            self.actor, ctx.author.id, action.tool or action.command_type, event
        )

    @staticmethod
    async def _reply(ctx, body: str) -> None:
        """Reply to the player and ping them so the result reaches their notifications."""
        await ctx.send(f"{ctx.author.mention} {body}")

    @staticmethod
    async def _send_help(ctx, body: str) -> None:
        """Send bounded help chunks without flooding the Discord API."""
        chunks = split_discord_text(body)
        for index, chunk in enumerate(chunks):
            await ctx.send(chunk)
            if index < len(chunks) - 1:
                await asyncio.sleep(0.25)

    def _register_commands(self) -> None:
        discord, commands = _require_discord()

        @self.client.command(name="claim")
        async def claim(ctx, *, character: str | None = None):
            if self._character_for_user(ctx.author.id) is not None:
                await self._reply(ctx, "You are already controlling a character.")
                return
            try:
                claimed = assign_discord_controller(
                    self.actor,
                    discord_user_id=ctx.author.id,
                    default_channel_id=ctx.channel.id,
                    character_name=character,
                    allow_child_claims=self.allow_child_claims,
                )
            except RuntimeError as exc:
                await self._reply(ctx, str(exc))
                return
            await self._reply(ctx, f"You are now controlling {claimed}.")

        @self.client.command(name="characters")
        async def characters(ctx):
            await self._send_help(ctx, render_character_list(self.actor))

        @self.client.command(name="release")
        async def release(ctx):
            try:
                released = release_discord_character_to_llm(
                    self.actor,
                    discord_user_id=ctx.author.id,
                    model=self.character_model,
                    provider=self.llm_provider,
                )
            except RuntimeError as exc:
                await self._reply(ctx, str(exc))
                return
            await self._reply(ctx, f"{released} is now controlled by the LLM.")

        @self.client.command(name="suspend")
        async def suspend(ctx):
            try:
                suspended = suspend_discord_character(
                    self.actor, discord_user_id=ctx.author.id
                )
            except RuntimeError as exc:
                await self._reply(ctx, str(exc))
                return
            await self._reply(ctx, f"{suspended} is suspended until someone claims them.")

        @self.client.command(name="look")
        async def look(ctx):
            await ctx.send(render_look(self.actor, ctx.author.id))

        @self.client.command(name="help")
        async def help_command(ctx, *, topic: str | None = None):
            await self._send_help(ctx, render_help(topic, self.actor))

        @self.client.event
        async def on_ready():
            print(f"Discord bot connected as {self.client.user}.", flush=True)

        @self.client.event
        async def on_message(message):
            if message.author.bot or not message.content.startswith("!"):
                return
            ctx = await self.client.get_context(message)
            head = message.content[1:].strip().split(maxsplit=1)[0].lower()
            if ctx.valid and head in META_COMMANDS:
                await self.client.process_commands(message)
                return
            try:
                action = parse_discord_action(
                    message.content[1:].strip(), self.actor.available_command_types()
                )
            except ValueError as exc:
                await self._reply(ctx, str(exc))
                return
            await self._reply(ctx, await self._submit_action(ctx, action))

        @self.client.event
        async def on_command_error(ctx, error):
            if isinstance(error, commands.CommandNotFound):
                return
            cause = error.original if isinstance(error, commands.CommandInvokeError) else error
            print(f"Discord command failed: {cause!r}", flush=True)
            await ctx.send(f"Command failed: {cause}")

    def run(self) -> None:
        self.client.run(self.token)

    async def start(self) -> None:
        """Start the Discord client inside an existing asyncio application."""

        await self.client.start(self.token)

    async def close(self) -> None:
        """Stop the Discord client when the host game loop is shutting down."""

        self.actor.bus.unsubscribe(WorldPauseStatusChangedEvent, self._post_pause_status)
        await self.client.close()


__all__ = [
    "DiscordAction",
    "DiscordBot",
    "assign_discord_controller",
    "did_you_mean",
    "discord_broadcast_channel_ids",
    "parse_discord_action",
    "release_discord_character_to_llm",
    "suspend_discord_character",
]
