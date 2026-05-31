"""Discord-facing text views over server projections."""

from __future__ import annotations

from ..core.ecs import container_of
from ..core.world_actor import WorldActor
from ..projections import RoomSummaryProjection
from .claim import discord_controlled_character

HELP_TEXT = "\n".join(
    [
        "Available commands:",
        "!help - show this help.",
        "!characters - list character names.",
        "!claim [character] - control a character.",
        "!look - show your current room.",
        "!move <direction> - move through an exit.",
        "!say <text> - speak in the room.",
        "!take <item> - pick up an item.",
    ]
)


def render_look(actor: WorldActor, discord_user_id: int) -> str:
    """Render the controlled character's current room via ``RoomSummaryProjection``."""

    found = discord_controlled_character(actor, discord_user_id)
    if found is None:
        return "You are not controlling a character yet."
    character_id, _controller_id, _generation = found
    room_id = container_of(actor.world.get_entity(character_id))
    if room_id is None:
        return "You are nowhere."
    summary = RoomSummaryProjection(actor.world).attach().summary(room_id, actor.epoch)
    return summary.visible_summary


__all__ = ["HELP_TEXT", "render_look"]
