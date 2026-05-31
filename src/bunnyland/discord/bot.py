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

from ..core.world_actor import WorldActor
from ..llm_agents.dispatch import did_you_mean, resolve_reference_args
from ..llm_agents.tools import ToolCall, command_from_tool_call
from .claim import assign_discord_controller, discord_controlled_character, list_character_names


def _require_discord():  # pragma: no cover - exercised only with the extra
    try:
        import discord
        from discord.ext import commands
    except ImportError as exc:
        raise RuntimeError(
            "the Discord bot requires the 'discord' extra: pip install bunnyland[discord]"
        ) from exc
    return discord, commands


class DiscordBot:  # pragma: no cover - needs network + extra
    """Maps Discord slash commands to character verbs for the controlling user."""

    def __init__(self, actor: WorldActor, *, token: str) -> None:
        discord, commands = _require_discord()
        self.actor = actor
        self.token = token
        intents = discord.Intents.default()
        intents.message_content = True  # required to read "!" command text
        self.client = commands.Bot(command_prefix="!", intents=intents)
        self._register_commands()

    def _character_for_user(self, discord_user_id: int):
        """Find the character controlled by a Discord controller for this user."""
        return discord_controlled_character(self.actor, discord_user_id)

    async def _submit(self, discord_user_id: int, tool: str, arguments: dict) -> str:
        found = self._character_for_user(discord_user_id)
        if found is None:
            return "You are not controlling a character yet."
        character_id, controller_id, generation = found

        character = self.actor.world.get_entity(character_id)
        resolved, unresolved = resolve_reference_args(self.actor.world, character, arguments)
        if unresolved:
            return did_you_mean(arguments, unresolved)

        command = command_from_tool_call(
            ToolCall(name=tool, arguments=resolved),
            character_id=str(character_id),
            controller_id=str(controller_id),
            controller_generation=generation,
            submitted_at_epoch=self.actor.epoch,
        )
        await self.actor.submit(command)
        return f"Queued: {tool}."

    def _register_commands(self) -> None:
        discord, commands = _require_discord()

        @self.client.command(name="move")
        async def move(ctx, direction: str):
            await ctx.send(await self._submit(ctx.author.id, "move", {"direction": direction}))

        @self.client.command(name="say")
        async def say(ctx, *, text: str):
            await ctx.send(await self._submit(ctx.author.id, "say", {"text": text}))

        @self.client.command(name="take")
        async def take(ctx, *, item_id: str):
            await ctx.send(await self._submit(ctx.author.id, "take", {"item_id": item_id}))

        @self.client.command(name="claim")
        async def claim(ctx, *, character: str | None = None):
            if self._character_for_user(ctx.author.id) is not None:
                await ctx.send("You are already controlling a character.")
                return
            try:
                claimed = assign_discord_controller(
                    self.actor,
                    discord_user_id=ctx.author.id,
                    default_channel_id=ctx.channel.id,
                    character_name=character,
                )
            except RuntimeError as exc:
                await ctx.send(str(exc))
                return
            await ctx.send(f"You are now controlling {claimed}.")

        @self.client.command(name="characters")
        async def characters(ctx):
            names = list_character_names(self.actor)
            if not names:
                await ctx.send("There are no characters in this world.")
                return
            await ctx.send("Characters: " + ", ".join(names))

        @self.client.event
        async def on_ready():
            print(f"Discord bot connected as {self.client.user}.", flush=True)

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

        await self.client.close()


__all__ = ["DiscordBot", "assign_discord_controller", "did_you_mean"]
