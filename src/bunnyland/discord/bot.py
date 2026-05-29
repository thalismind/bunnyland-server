"""Discord controller front-end (spec 24). Optional: requires the ``discord`` extra.

Discord users drive characters through the same verb surface the LLM uses. A slash command
becomes a ``SubmittedCommand`` routed to that user's character; the world lane (move, take,
say) is public, while focus actions (notes, remember) are offered over DM. The bot only
translates input and relays events — it never touches the ECS directly (spec 24.2).

This module is structural: it is import-guarded and not exercised by the unit tests.
"""

from __future__ import annotations

from ..core.controllers import DiscordControllerComponent
from ..core.edges import ControlledBy
from ..core.world_actor import WorldActor
from ..llm_agents.tools import ToolCall, command_from_tool_call


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
        self.client = commands.Bot(command_prefix="!", intents=intents)
        self._register_commands()

    def _character_for_user(self, discord_user_id: int):
        """Find the character controlled by a Discord controller for this user."""
        for entity in self.actor.world.query().with_all([DiscordControllerComponent]):
            if entity.get_component(DiscordControllerComponent).discord_user_id == discord_user_id:
                controller_id = entity.id
                for character in self.actor.world.query().with_all([]):
                    for edge, target in character.get_relationships(ControlledBy):
                        if target == controller_id:
                            return character.id, controller_id, edge.generation
        return None

    async def _submit(self, discord_user_id: int, tool: str, arguments: dict) -> str:
        found = self._character_for_user(discord_user_id)
        if found is None:
            return "You are not controlling a character yet."
        character_id, controller_id, generation = found
        command = command_from_tool_call(
            ToolCall(name=tool, arguments=arguments),
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

    def run(self) -> None:
        self.client.run(self.token)


__all__ = ["DiscordBot"]
