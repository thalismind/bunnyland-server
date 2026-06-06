"""Discord front-end (spec 24). Import the bot lazily so the extra stays optional."""

from .bot import (
    DiscordMessageFilters,
    assign_discord_controller,
    did_you_mean,
    discord_broadcast_channel_ids,
    parse_discord_action,
    parse_discord_id_list,
    release_discord_character_to_llm,
    set_discord_claim_fallback,
    suspend_discord_character,
)
from .claim import render_character_list
from .view import (
    HELP_TEXT,
    explain_rejection,
    render_action_result,
    render_help,
    render_look,
    render_move_result,
    render_notes_search_result,
    split_discord_text,
)

__all__ = [
    "DiscordBot",
    "DiscordMessageFilters",
    "HELP_TEXT",
    "assign_discord_controller",
    "did_you_mean",
    "discord_broadcast_channel_ids",
    "explain_rejection",
    "parse_discord_action",
    "parse_discord_id_list",
    "release_discord_character_to_llm",
    "render_character_list",
    "render_action_result",
    "render_help",
    "render_look",
    "render_move_result",
    "render_notes_search_result",
    "split_discord_text",
    "set_discord_claim_fallback",
    "suspend_discord_character",
]


def __getattr__(name: str):
    if name == "DiscordBot":
        from .bot import DiscordBot

        return DiscordBot
    raise AttributeError(name)
