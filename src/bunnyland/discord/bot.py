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
import logging
import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass, replace
from io import BytesIO
from typing import TYPE_CHECKING, Any

from relics import (
    OnComponentAdded,
    OnComponentRemoved,
    OnRelationshipAdded,
    OnRelationshipRemoved,
)

from ..claims import ClaimSecretRegistry
from ..core.claim_timeout import (
    normalize_claim_timeout,
)
from ..core.commands import CommandCost, Lane, OnInsufficientPoints, build_submitted_command
from ..core.components import ControllerOutboxMessageComponent, RoomComponent
from ..core.controllers import DiscordControllerComponent
from ..core.ecs import entity_name, parse_entity_id, replace_component
from ..core.edges import ContainmentMode, Contains
from ..core.events import (
    ActorMovedEvent,
    CharacterClaimedEvent,
    CommandAcceptedEvent,
    CommandCancelledEvent,
    CommandExecutedEvent,
    CommandExpiredEvent,
    CommandQueuedEvent,
    CommandRejectedEvent,
    CommandSubmittedEvent,
    DomainEvent,
    EventVisibility,
    NotesSearchedEvent,
    WorldPauseStatusChangedEvent,
)
from ..core.world_actor import WorldActor
from ..imagegen.affordance import ACK_EMOJI, DELIVER_EMOJI, FAIL_EMOJI, REQUEST_EMOJI
from ..imagegen.events import ImageGenerationCompletedEvent, ImageGenerationFailedEvent
from ..imagegen.scene import request_scene_image

if TYPE_CHECKING:
    from ..imagegen.service import ImageGenService
from ..llm_agents import DEFAULT_MODEL
from ..llm_agents.dispatch import did_you_mean, resolve_reference_args
from ..llm_agents.natural_language import parse_natural_command
from ..llm_agents.tools import (
    ToolCall,
    action_definitions,
    command_from_tool_call,
    command_type_for_tool,
    reference_arg_keys,
    tool_arg_keys,
    tool_for_command_type,
    tool_names,
)
from .claim import (
    assign_discord_controller,
    discord_controlled_character,
    release_discord_claim,
    render_character_list,
    resume_discord_claim,
    set_discord_claim_fallback,
    suspend_discord_character,
)
from .components import DiscordRoomFeedComponent
from .view import (
    render_action_result,
    render_help,
    render_look,
    render_notes_search_result,
    split_discord_text,
)

MOVE_RESULT_TIMEOUT_SECONDS = 120.0
DISCORD_THREAD_AUTO_ARCHIVE_MINUTES = 60
DISCORD_THREAD_NAME_LIMIT = 100
logger = logging.getLogger("bunnyland.discord")

#: Reaction added to a player's message once their command is accepted and queued.
QUEUED_REACTION = "\N{HOURGLASS WITH FLOWING SAND}"
PAUSED_REACTION = "\N{DOUBLE VERTICAL BAR}\N{VARIATION SELECTOR-16}"
META_COMMANDS = frozenset({"help", "claim", "characters", "fallback", "look", "release", "suspend"})
COMMAND_LIFECYCLE_EVENTS = (
    CommandAcceptedEvent,
    CommandCancelledEvent,
    CommandExecutedEvent,
    CommandExpiredEvent,
    CommandQueuedEvent,
    CommandRejectedEvent,
    CommandSubmittedEvent,
)
_CAMEL_WORD_RE = re.compile(r"(?<!^)(?=[A-Z])")


@dataclass(frozen=True)
class DiscordAction:
    command_type: str
    payload: dict[str, Any]
    tool: str | None = None


@dataclass(frozen=True)
class DiscordClaimArgs:
    character_name: str | None = None
    fallback_controller: str | None = None
    timeout_seconds: int | None = None


def _minutes_to_timeout_seconds(value: str | int | None) -> int | None:
    if value is None:
        return None
    try:
        minutes = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout minutes must be a whole number") from exc
    return normalize_claim_timeout(minutes * 60)


def _parse_discord_claim_args(text: str | None) -> DiscordClaimArgs:
    tokens = shlex.split(text or "")
    name_parts: list[str] = []
    fallback = None
    timeout_seconds = None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in {"--fallback", "--fallback-controller"}:
            index += 1
            if index >= len(tokens):
                raise ValueError("--fallback requires suspend or llm")
            fallback = tokens[index]
        elif token.startswith("--fallback="):
            fallback = token.split("=", 1)[1]
        elif token in {"--timeout", "--timeout-minutes", "--claim-timeout"}:
            index += 1
            if index >= len(tokens):
                raise ValueError("--timeout requires minutes")
            timeout_seconds = _minutes_to_timeout_seconds(tokens[index])
        elif token.startswith("--timeout="):
            timeout_seconds = _minutes_to_timeout_seconds(token.split("=", 1)[1])
        elif token.startswith("--timeout-minutes="):
            timeout_seconds = _minutes_to_timeout_seconds(token.split("=", 1)[1])
        else:
            name_parts.append(token)
        index += 1
    return DiscordClaimArgs(
        character_name=" ".join(name_parts) or None,
        fallback_controller=fallback,
        timeout_seconds=timeout_seconds,
    )


@dataclass(frozen=True)
class DiscordMessageFilters:
    """Allowlist for inbound Discord messages."""

    guild_ids: tuple[int, ...] = ()
    channel_ids: tuple[int, ...] = ()
    dm_user_ids: tuple[int, ...] = ()
    allowed_bot_user_ids: tuple[int, ...] = ()

    def allows(self, message) -> bool:
        if not self.guild_ids and not self.channel_ids and not self.dm_user_ids:
            return True

        author = getattr(message, "author", None)
        guild = getattr(message, "guild", None)
        if guild is None:
            return getattr(author, "id", None) in self.dm_user_ids

        if not self.guild_ids and not self.channel_ids:
            return False
        if self.guild_ids and getattr(guild, "id", None) not in self.guild_ids:
            return False

        channel = getattr(message, "channel", None)
        channel_id = getattr(channel, "id", None)
        parent_channel_id = getattr(getattr(channel, "parent", None), "id", None)
        if (
            self.channel_ids
            and channel_id not in self.channel_ids
            and parent_channel_id not in self.channel_ids
        ):
            return False
        return True


def _require_discord():
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


def parse_discord_id_list(value: str | None) -> tuple[int, ...]:
    """Parse comma-separated Discord snowflake ids from env/config text."""

    if value is None or value.strip() == "":
        return ()
    return tuple(int(part.strip()) for part in value.split(",") if part.strip())


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


def parse_discord_action(
    text: str,
    available_commands: tuple[str, ...],
    definitions=(),
) -> DiscordAction:
    """Parse a Discord ``!`` action against the live world verb set."""

    available = set(available_commands)
    action_defs = action_definitions(tuple(definitions))
    words = _split(text.strip())
    if not words:
        raise ValueError("No command provided")
    typed = words[0].lower()
    rest = text.strip()[len(words[0]) :].strip()
    command_type = typed.replace("_", "-")
    tool = typed.replace("-", "_")
    structured = bool(rest) and _parse_structured_payload(rest) is not None

    if not structured:
        natural = parse_natural_command(text, action_defs)
        if natural is not None:
            natural_command_type = command_type_for_tool(natural.name, action_defs)
            if natural_command_type in available:
                return _with_discord_defaults(
                    DiscordAction(
                        command_type=natural_command_type,
                        payload=natural.arguments,
                        tool=natural.name,
                    )
                )

    if tool in tool_names(action_defs):
        mapped = command_type_for_tool(tool, action_defs)
        if mapped in available:
            return _with_discord_defaults(
                DiscordAction(
                    mapped,
                    _payload_from_text(rest, tool_arg_keys(tool, action_defs)),
                    tool=tool,
                )
            )
    if command_type in available:
        mapped_tool = tool_for_command_type(command_type, action_defs)
        if mapped_tool is not None:
            return _with_discord_defaults(
                DiscordAction(
                    command_type,
                    _payload_from_text(rest, tool_arg_keys(mapped_tool, action_defs)),
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
        channel_id = controller.get_component(DiscordControllerComponent).default_channel_id
        if channel_id:
            channel_ids.add(channel_id)
    return tuple(sorted(channel_ids))


def _room_feed_component_observer(bot: DiscordBot, *, removed: bool):
    if removed:

        class _Observer(OnComponentRemoved):
            component_type = DiscordRoomFeedComponent

            def on_component_removed(self, entity, component) -> None:
                del component
                bot._remove_room_feed(str(entity.id))

    else:

        class _Observer(OnComponentAdded):
            component_type = DiscordRoomFeedComponent

            def on_component_added(self, entity, component) -> None:
                bot._set_room_feed(str(entity.id), component.channel_id)

    return _Observer()


def _contains_observer(bot: DiscordBot, *, removed: bool):
    if removed:

        class _Observer(OnRelationshipRemoved):
            edge_type = Contains

            def on_relationship_removed(self, source, edge, target) -> None:
                bot._record_containment_change(source, edge, target, removed=True)

    else:

        class _Observer(OnRelationshipAdded):
            edge_type = Contains

            def on_relationship_added(self, source, edge, target) -> None:
                bot._record_containment_change(source, edge, target, removed=False)

    return _Observer()


def _feed_entity_name(actor: WorldActor | None, raw_id: str | None) -> str | None:
    if actor is None or raw_id is None:
        return raw_id
    entity_id = parse_entity_id(raw_id)
    if entity_id is None or not actor.world.has_entity(entity_id):
        return raw_id
    entity = actor.world.get_entity(entity_id)
    if entity.has_component(RoomComponent):
        return entity.get_component(RoomComponent).title
    return entity_name(entity)


def render_room_feed_event(event: DomainEvent, actor: WorldActor | None = None) -> str:
    """Render a room-feed event; callers only invoke this after a feed match."""

    title = _CAMEL_WORD_RE.sub(" ", type(event).__name__).removesuffix(" Event")
    if isinstance(event, ActorMovedEvent):
        actor_name = _feed_entity_name(actor, event.actor_id) or "Someone"
        from_room = _feed_entity_name(actor, event.from_room_id) or event.from_room_id
        to_room = _feed_entity_name(actor, event.to_room_id) or event.to_room_id
        direction = f" {event.direction}" if event.direction else ""
        summary = f" {event.arrival_summary}" if event.arrival_summary else ""
        return f"**{title}**: {actor_name} moved{direction} from {from_room} to {to_room}.{summary}"

    base_fields = {
        "event_id",
        "world_epoch",
        "created_at",
        "visibility",
        "actor_id",
        "room_id",
        "target_ids",
        "causation_id",
        "correlation_id",
    }
    details = [
        f"{key}={value}"
        for key, value in event.model_dump(mode="json").items()
        if key not in base_fields and value not in (None, "", [], ())
    ]
    actor_name = _feed_entity_name(actor, event.actor_id)
    room_name = _feed_entity_name(actor, event.room_id)
    actor_text = f" actor={actor_name}" if actor_name else ""
    room = f" room={room_name}" if room_name else ""
    suffix = f": {', '.join(details[:6])}" if details else ""
    return f"**{title}**{actor_text}{room}{suffix}"


class DiscordBot:
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
        message_filters: DiscordMessageFilters | None = None,
        imagegen: ImageGenService | None = None,
        claim_secrets: ClaimSecretRegistry | None = None,
    ) -> None:
        discord, commands = _require_discord()
        self.actor = actor
        self.token = token
        self.allow_child_claims = allow_child_claims
        self.llm_provider = llm_provider
        self.character_model = character_model
        self.message_filters = message_filters or DiscordMessageFilters()
        self.imagegen = imagegen
        self.claim_secrets = claim_secrets
        self._pause_status = pause_status
        self._world_paused = pause_status() if pause_status is not None else False
        intents = discord.Intents.default()
        intents.message_content = True  # required to read "!" command text
        intents.reactions = True  # required to receive the 📷 image-request reaction
        self.client = commands.Bot(command_prefix="!", intents=intents, help_command=None)
        self._pending: dict[str, asyncio.Future[CommandExecutedEvent | CommandRejectedEvent]] = {}
        self._paused_reactions: dict[str, Any] = {}
        # record entity id -> the Discord message that requested an image for it.
        self._image_messages: dict[str, Any] = {}
        self._room_feed_channels: dict[str, tuple[int, ...]] = {}
        self._actor_rooms: dict[str, str] = {}
        self._delivered_room_feed_events: set[tuple[str, int]] = set()
        self._room_feed_observers_attached = False
        self._build_room_feed_index()
        self._attach_room_feed_observers()
        self.actor.bus.subscribe(CommandExecutedEvent, self._complete_pending)
        self.actor.bus.subscribe(CommandRejectedEvent, self._complete_pending)
        self.actor.bus.subscribe(WorldPauseStatusChangedEvent, self._post_pause_status)
        self.actor.bus.subscribe(DomainEvent, self._post_room_feed_event)
        if imagegen is not None:
            self.actor.bus.subscribe(ImageGenerationCompletedEvent, self._deliver_image)
            self.actor.bus.subscribe(ImageGenerationFailedEvent, self._image_failed)
        self._register_commands()

    def _character_for_user(self, discord_user_id: int):
        """Find the character controlled by a Discord controller for this user."""
        return discord_controlled_character(self.actor, discord_user_id)

    def _complete_pending(self, event: CommandExecutedEvent | CommandRejectedEvent) -> None:
        future = self._pending.pop(event.command_id, None)
        self._paused_reactions.pop(event.command_id, None)
        if future is not None and not future.done():
            future.set_result(event)

    def _build_room_feed_index(self) -> None:
        self._room_feed_channels = {}
        self._actor_rooms = {}
        rooms = self.actor.world.query().with_all([RoomComponent]).execute_entities()
        for room in rooms:
            if room.has_component(DiscordRoomFeedComponent):
                component = room.get_component(DiscordRoomFeedComponent)
                self._set_room_feed(str(room.id), component.channel_id)
            for edge, target_id in room.get_relationships(Contains):
                if edge.mode == ContainmentMode.ROOM_CONTENT:
                    self._actor_rooms[str(target_id)] = str(room.id)

    def _attach_room_feed_observers(self) -> None:
        if getattr(self, "_room_feed_observers_attached", False):
            return
        self.actor.world.observe(_room_feed_component_observer(self, removed=False))
        self.actor.world.observe(_room_feed_component_observer(self, removed=True))
        self.actor.world.observe(_contains_observer(self, removed=False))
        self.actor.world.observe(_contains_observer(self, removed=True))
        self._room_feed_observers_attached = True

    def _process_room_feed_observers(self) -> None:
        process = getattr(self.actor.world, "_process_observer_queue", None)
        if callable(process):
            process()

    def _set_room_feed(self, room_id: str, channel_id: int) -> None:
        if channel_id:
            self._room_feed_channels[room_id] = (int(channel_id),)
        else:
            self._room_feed_channels.pop(room_id, None)

    def _remove_room_feed(self, room_id: str) -> None:
        self._room_feed_channels.pop(room_id, None)

    def _record_containment_change(self, source, edge, target, *, removed: bool) -> None:
        if edge.mode != ContainmentMode.ROOM_CONTENT:
            return
        if not source.has_component(RoomComponent):
            return
        actor_id = str(target)
        room_id = str(source.id)
        if removed:
            if self._actor_rooms.get(actor_id) == room_id:
                self._actor_rooms.pop(actor_id, None)
            return
        self._actor_rooms[actor_id] = room_id

    def _room_ids_for_event(self, event: DomainEvent) -> tuple[str, ...]:
        room_ids: list[str] = []
        for attr in ("room_id", "from_room_id", "to_room_id"):
            value = getattr(event, attr, None)
            if value:
                room_ids.append(str(value))
        if not room_ids and event.actor_id:
            room_id = self._actor_rooms.get(event.actor_id)
            if room_id:
                room_ids.append(room_id)
        return tuple(dict.fromkeys(room_ids))

    async def _post_room_feed_event(self, event: DomainEvent) -> None:
        if isinstance(event, COMMAND_LIFECYCLE_EVENTS):
            return
        if event.visibility in {EventVisibility.SYSTEM, EventVisibility.PRIVATE}:
            return
        self._process_room_feed_observers()
        room_ids = self._room_ids_for_event(event)
        if not room_ids:
            self._update_actor_room_from_event(event)
            return

        channel_ids: list[int] = []
        for room_id in room_ids:
            channel_ids.extend(self._room_feed_channels.get(room_id, ()))
        if not channel_ids:
            self._update_actor_room_from_event(event)
            return

        message = render_room_feed_event(event, self.actor)
        for channel_id in dict.fromkeys(channel_ids):
            key = (event.event_id, channel_id)
            if key in self._delivered_room_feed_events:
                continue
            self._delivered_room_feed_events.add(key)
            await self._send_room_feed_message(channel_id, message)
        self._update_actor_room_from_event(event)

    def _update_actor_room_from_event(self, event: DomainEvent) -> None:
        if isinstance(event, ActorMovedEvent) and event.actor_id:
            self._actor_rooms[event.actor_id] = event.to_room_id

    async def _send_room_feed_message(self, channel_id: int, message: str) -> None:
        channel = self.client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.client.fetch_channel(channel_id)
            except Exception as exc:
                print(
                    f"Discord room feed post failed for channel {channel_id}: {exc!r}",
                    flush=True,
                )
                return
        for chunk in split_discord_text(message):
            try:
                await channel.send(chunk)
            except Exception as exc:
                print(
                    f"Discord room feed post failed for channel {channel_id}: {exc!r}",
                    flush=True,
                )
                return

    def _is_world_paused(self) -> bool:
        if self._pause_status is not None:
            return self._pause_status()
        return self._world_paused

    def _should_handle_message(self, message) -> bool:
        author = getattr(message, "author", None)
        if getattr(author, "bot", False):
            if getattr(author, "id", None) not in self.message_filters.allowed_bot_user_ids:
                return False
            if not (
                self.message_filters.guild_ids
                or self.message_filters.channel_ids
                or self.message_filters.dm_user_ids
            ):
                return False
        content = getattr(message, "content", "")
        if not content.startswith("!"):
            return False
        return self.message_filters.allows(message)

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
            except Exception:
                pass
            try:
                await message.add_reaction(QUEUED_REACTION)
            except Exception:
                pass
        self._paused_reactions.clear()

    async def _on_image_reaction(self, reaction, user) -> None:
        """Handle the 📷 image-request reaction: illustrate the reactor's current scene."""
        if self.imagegen is None:
            return
        if getattr(user, "bot", False):
            return
        if str(getattr(reaction, "emoji", "")) != REQUEST_EMOJI:
            return
        try:
            await self._request_scene_image(reaction.message, user)
        except Exception:
            logger.warning("Discord image request failed.", exc_info=True)

    async def _request_scene_image(self, message, user) -> None:
        found = self._character_for_user(user.id)
        if found is None:
            return
        job = await request_scene_image(
            self.actor, self.imagegen, character_id=found[0], requested_by=str(user.id)
        )
        if job is None:  # the character is not in a room to illustrate
            return
        if job.status == "skipped" and job.url:
            # The scene already has an image: deliver it immediately.
            await self._post_image(message, job.url)
            await message.add_reaction(DELIVER_EMOJI)
            return
        self._image_messages[job.entity_id] = message
        await message.add_reaction(ACK_EMOJI)

    async def _deliver_image(self, event: ImageGenerationCompletedEvent) -> None:
        message = self._image_messages.pop(event.entity_id, None)
        if message is None:
            return
        await self._post_image(message, event.url)
        await message.add_reaction(DELIVER_EMOJI)

    async def _image_failed(self, event: ImageGenerationFailedEvent) -> None:
        message = self._image_messages.pop(event.entity_id, None)
        if message is None:
            return
        await message.add_reaction(FAIL_EMOJI)

    async def _post_image(self, message, url: str) -> None:
        discord, _ = _require_discord()
        parts = url.strip("/").split("/")
        data = self.imagegen.media.read(parts[1], parts[2])
        await message.reply(file=discord.File(BytesIO(data), filename=parts[2]))

    async def _build_command(
        self,
        discord_user_id: int,
        action: DiscordAction,
        *,
        default_channel_id: int = 0,
    ):
        found = resume_discord_claim(
            self.actor,
            discord_user_id=discord_user_id,
            default_channel_id=default_channel_id,
        )
        if found is None:
            return None, "You are not controlling a character yet."
        character, controller_id, generation = found

        resolved, unresolved = resolve_reference_args(
            self.actor.world,
            character,
            action.payload,
            keys=reference_arg_keys(self.actor.action_definitions()),
        )
        if unresolved:
            return None, did_you_mean(action.payload, unresolved)

        if action.tool is not None:
            command = command_from_tool_call(
                ToolCall(name=action.tool, arguments=resolved),
                character_id=str(character.id),
                controller_id=str(controller_id),
                controller_generation=generation,
                submitted_at_epoch=self.actor.epoch,
                definitions=self.actor.action_definitions(),
            )
        else:
            command = build_submitted_command(
                character_id=str(character.id),
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
        except Exception:
            pass

    async def _submit_action(self, ctx, action: DiscordAction) -> str:
        command, error = await self._build_command(
            ctx.author.id,
            action,
            default_channel_id=getattr(ctx.channel, "id", 0),
        )
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
        reply = getattr(ctx, "reply", None)
        if callable(reply):
            try:
                await reply(body, mention_author=True)
                return
            except TypeError:
                await reply(body)
                return
            except Exception:
                logger.warning("Discord context reply failed; falling back.", exc_info=True)

        message_reply = getattr(getattr(ctx, "message", None), "reply", None)
        if callable(message_reply):
            try:
                await message_reply(body, mention_author=True)
                return
            except TypeError:
                await message_reply(body)
                return
            except Exception:
                logger.warning("Discord message reply failed; falling back.", exc_info=True)

        mention = getattr(getattr(ctx, "author", None), "mention", "")
        prefix = f"{mention} " if mention else ""
        await ctx.send(f"{prefix}{body}")

    @staticmethod
    async def _send_help(ctx, body: str) -> None:
        """Send bounded help chunks without flooding the Discord API."""
        chunks = split_discord_text(body)
        for index, chunk in enumerate(chunks):
            await ctx.send(chunk)
            if index < len(chunks) - 1:
                await asyncio.sleep(0.25)

    @staticmethod
    def _is_thread_channel(channel) -> bool:
        """Detect Discord thread channels without importing the optional discord extra."""
        if channel is None:
            return False
        channel_type = str(getattr(channel, "type", "")).lower()
        if "thread" in channel_type:
            return True
        if channel.__class__.__name__ == "Thread":
            return True
        return hasattr(channel, "owner_id") and hasattr(channel, "parent")

    @staticmethod
    def _can_start_thread(ctx) -> bool:
        guild = getattr(ctx, "guild", None) or getattr(getattr(ctx, "message", None), "guild", None)
        if guild is None:
            return False

        channel = getattr(ctx, "channel", None)
        permissions_for = getattr(channel, "permissions_for", None)
        me = getattr(ctx, "me", None) or getattr(guild, "me", None)
        if not callable(permissions_for) or me is None:
            return True

        permissions = permissions_for(me)
        can_create = bool(getattr(permissions, "create_public_threads", False))
        can_post = bool(getattr(permissions, "send_messages_in_threads", False))
        return can_create and can_post

    @staticmethod
    def _thread_name(title: str, topic: str | None = None) -> str:
        clean_title = " ".join(title.split()) or "Bunnyland"
        normalized_topic = " ".join((topic or "").split())
        name = f"{clean_title}: {normalized_topic}" if normalized_topic else clean_title
        return name[:DISCORD_THREAD_NAME_LIMIT]

    @classmethod
    async def _reply_thread(cls, ctx, *, title: str, topic: str | None = None):
        channel = getattr(ctx, "channel", None)
        if cls._is_thread_channel(channel):
            return channel
        if not cls._can_start_thread(ctx):
            return None

        create_thread = getattr(getattr(ctx, "message", None), "create_thread", None)
        if not callable(create_thread):
            return None

        try:
            return await create_thread(
                name=cls._thread_name(title, topic),
                auto_archive_duration=DISCORD_THREAD_AUTO_ARCHIVE_MINUTES,
            )
        except TypeError:
            try:
                return await create_thread(name=cls._thread_name(title, topic))
            except Exception:
                logger.warning("Discord thread creation failed; falling back.", exc_info=True)
                return None
        except Exception:
            logger.warning("Discord thread creation failed; falling back.", exc_info=True)
            return None

    @classmethod
    async def _send_threaded_or_reply(
        cls, ctx, body: str, *, title: str, topic: str | None = None
    ) -> None:
        """Send chunks in a Discord thread when possible, falling back to replies."""
        chunks = split_discord_text(body)
        thread = await cls._reply_thread(ctx, title=title, topic=topic)
        sent_chunks = 0
        if thread is not None:
            try:
                for index, chunk in enumerate(chunks):
                    await thread.send(chunk)
                    sent_chunks = index + 1
                    if index < len(chunks) - 1:
                        await asyncio.sleep(0.25)
                return
            except Exception:
                logger.warning("Discord thread send failed; falling back.", exc_info=True)

        for index, chunk in enumerate(chunks[sent_chunks:]):
            await cls._reply(ctx, chunk)
            if index < len(chunks) - sent_chunks - 1:
                await asyncio.sleep(0.25)

    async def _handle_meta_command(self, ctx, head: str, rest: str) -> bool:
        if head == "claim":
            if self._character_for_user(ctx.author.id) is not None:
                await self._reply(ctx, "You are already controlling a character.")
                return True
            try:
                claim_args = _parse_discord_claim_args(rest)
                claimed = assign_discord_controller(
                    self.actor,
                    claim_secrets=self.claim_secrets,
                    discord_user_id=ctx.author.id,
                    default_channel_id=ctx.channel.id,
                    character_name=claim_args.character_name,
                    allow_child_claims=self.allow_child_claims,
                    fallback_controller=claim_args.fallback_controller,
                    timeout_seconds=claim_args.timeout_seconds,
                    llm_model=self.character_model,
                    llm_provider=self.llm_provider,
                )
            except (RuntimeError, ValueError) as exc:
                await self._reply(ctx, str(exc))
                return True
            await self._publish_claimed(ctx.author.id)
            await self._reply(ctx, f"You are now controlling {claimed}.")
            await self._drain_controller_outbox(ctx, ctx.author.id)
            return True

        if head == "fallback":
            fallback, _, minutes = rest.partition(" ")
            if not fallback:
                await self._reply(
                    ctx,
                    "Usage: !fallback suspend|llm [minutes between 5 and 60]",
                )
                return True
            try:
                timeout_seconds = _minutes_to_timeout_seconds(minutes.strip() or None)
                name, normalized = set_discord_claim_fallback(
                    self.actor,
                    discord_user_id=ctx.author.id,
                    fallback_controller=fallback,
                    timeout_seconds=timeout_seconds,
                    model=self.character_model,
                    provider=self.llm_provider,
                )
            except (RuntimeError, ValueError) as exc:
                await self._reply(ctx, str(exc))
                return True
            timeout_note = (
                "" if timeout_seconds is None else f" after {timeout_seconds // 60} minutes"
            )
            await self._reply(ctx, f"{name} will fall back to {normalized}{timeout_note}.")
            return True

        if head == "characters":
            await self._send_help(ctx, render_character_list(self.actor))
            return True

        if head == "release":
            try:
                released = release_discord_claim(
                    self.actor,
                    claim_secrets=self.claim_secrets,
                    discord_user_id=ctx.author.id,
                )
            except RuntimeError as exc:
                await self._reply(ctx, str(exc))
                return True
            await self._reply(ctx, f"Released your claim on {released}.")
            return True

        if head == "suspend":
            try:
                suspended = suspend_discord_character(self.actor, discord_user_id=ctx.author.id)
            except RuntimeError as exc:
                await self._reply(ctx, str(exc))
                return True
            await self._reply(ctx, f"{suspended} is idle until you resume with another command.")
            return True

        if head == "look":
            resume_discord_claim(
                self.actor,
                discord_user_id=ctx.author.id,
                default_channel_id=getattr(ctx.channel, "id", 0),
            )
            await ctx.send(render_look(self.actor, ctx.author.id))
            return True

        if head == "help":
            await self._send_threaded_or_reply(
                ctx,
                render_help(rest or None, self.actor),
                title="Bunnyland help",
                topic=rest or None,
            )
            return True

        return False

    async def _publish_claimed(self, discord_user_id: int) -> None:
        found = self._character_for_user(discord_user_id)
        if found is None:
            return
        character_id, controller_id, generation = found
        await self.actor.bus.publish(
            CharacterClaimedEvent(
                **self.actor._event_base(
                    actor_id=str(character_id),
                    character_id=str(character_id),
                    controller_id=str(controller_id),
                    generation=generation,
                )
            )
        )

    async def _drain_controller_outbox(self, ctx, discord_user_id: int) -> None:
        found = self._character_for_user(discord_user_id)
        if found is None:
            return
        _character_id, controller_id, _generation = found
        messages = sorted(
            self.actor.world.query()
            .with_all([ControllerOutboxMessageComponent])
            .execute_entities(),
            key=lambda entity: str(entity.id),
        )
        for entity in messages:
            message = entity.get_component(ControllerOutboxMessageComponent)
            already_delivered = message.delivered_at_epoch is not None
            if message.controller_id != str(controller_id) or already_delivered:
                continue
            await self._reply(ctx, message.text)
            replace_component(
                entity,
                replace(message, delivered_at_epoch=self.actor.epoch),
            )

    async def handle_text_command(self, ctx, text: str) -> None:
        """Handle one Discord command body after the leading ``!`` has been removed."""
        stripped = text.strip()
        if not stripped:
            return
        head, _, rest = stripped.partition(" ")
        head = head.lower()
        rest = rest.strip()
        if head in META_COMMANDS and await self._handle_meta_command(ctx, head, rest):
            return
        try:
            action = parse_discord_action(
                stripped,
                self.actor.available_command_types(),
                self.actor.action_definitions(),
            )
        except ValueError as exc:
            await self._reply(ctx, str(exc))
            return
        await self._reply(ctx, await self._submit_action(ctx, action))

    def _register_commands(self) -> None:
        discord, commands = _require_discord()

        @self.client.command(name="claim")
        async def claim(ctx, *, character: str | None = None):
            if self._character_for_user(ctx.author.id) is not None:
                await self._reply(ctx, "You are already controlling a character.")
                return
            try:
                claim_args = _parse_discord_claim_args(character)
                claimed = assign_discord_controller(
                    self.actor,
                    claim_secrets=self.claim_secrets,
                    discord_user_id=ctx.author.id,
                    default_channel_id=ctx.channel.id,
                    character_name=claim_args.character_name,
                    allow_child_claims=self.allow_child_claims,
                    fallback_controller=claim_args.fallback_controller,
                    timeout_seconds=claim_args.timeout_seconds,
                    llm_model=self.character_model,
                    llm_provider=self.llm_provider,
                )
            except (RuntimeError, ValueError) as exc:
                await self._reply(ctx, str(exc))
                return
            await self._publish_claimed(ctx.author.id)
            await self._reply(ctx, f"You are now controlling {claimed}.")
            await self._drain_controller_outbox(ctx, ctx.author.id)

        @self.client.command(name="fallback")
        async def fallback(ctx, fallback_controller: str | None = None, minutes: int | None = None):
            if not fallback_controller:
                await self._reply(
                    ctx,
                    "Usage: !fallback suspend|llm [minutes between 5 and 60]",
                )
                return
            try:
                timeout_seconds = _minutes_to_timeout_seconds(minutes)
                name, normalized = set_discord_claim_fallback(
                    self.actor,
                    discord_user_id=ctx.author.id,
                    fallback_controller=fallback_controller,
                    timeout_seconds=timeout_seconds,
                    model=self.character_model,
                    provider=self.llm_provider,
                )
            except (RuntimeError, ValueError) as exc:
                await self._reply(ctx, str(exc))
                return
            timeout_note = (
                "" if timeout_seconds is None else f" after {timeout_seconds // 60} minutes"
            )
            await self._reply(ctx, f"{name} will fall back to {normalized}{timeout_note}.")

        @self.client.command(name="characters")
        async def characters(ctx):
            await self._send_help(ctx, render_character_list(self.actor))

        @self.client.command(name="release")
        async def release(ctx):
            try:
                released = release_discord_claim(
                    self.actor,
                    claim_secrets=self.claim_secrets,
                    discord_user_id=ctx.author.id,
                )
            except RuntimeError as exc:
                await self._reply(ctx, str(exc))
                return
            await self._reply(ctx, f"Released your claim on {released}.")

        @self.client.command(name="suspend")
        async def suspend(ctx):
            try:
                suspended = suspend_discord_character(self.actor, discord_user_id=ctx.author.id)
            except RuntimeError as exc:
                await self._reply(ctx, str(exc))
                return
            await self._reply(ctx, f"{suspended} is idle until you resume with another command.")

        @self.client.command(name="look")
        async def look(ctx):
            resume_discord_claim(
                self.actor,
                discord_user_id=ctx.author.id,
                default_channel_id=getattr(ctx.channel, "id", 0),
            )
            await ctx.send(render_look(self.actor, ctx.author.id))

        @self.client.command(name="help")
        async def help_command(ctx, *, topic: str | None = None):
            await self._send_threaded_or_reply(
                ctx, render_help(topic, self.actor), title="Bunnyland help", topic=topic
            )

        @self.client.event
        async def on_ready():
            print(f"Discord bot connected as {self.client.user}.", flush=True)

        @self.client.event
        async def on_message(message):
            if not self._should_handle_message(message):
                return
            ctx = await self.client.get_context(message)
            await self.handle_text_command(ctx, message.content[1:])

        @self.client.event
        async def on_reaction_add(reaction, user):
            await self._on_image_reaction(reaction, user)

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
        self.actor.bus.unsubscribe(DomainEvent, self._post_room_feed_event)
        if self.imagegen is not None:
            self.actor.bus.unsubscribe(ImageGenerationCompletedEvent, self._deliver_image)
            self.actor.bus.unsubscribe(ImageGenerationFailedEvent, self._image_failed)
        await self.client.close()


__all__ = [
    "DiscordAction",
    "DiscordBot",
    "DiscordMessageFilters",
    "DiscordRoomFeedComponent",
    "assign_discord_controller",
    "did_you_mean",
    "discord_broadcast_channel_ids",
    "render_room_feed_event",
    "parse_discord_action",
    "parse_discord_id_list",
    "release_discord_claim",
    "set_discord_claim_fallback",
    "suspend_discord_character",
]
