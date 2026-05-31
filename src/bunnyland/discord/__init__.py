"""Discord front-end (spec 24). Import the bot lazily so the extra stays optional."""

from .bot import assign_discord_controller, did_you_mean
from .view import (
    HELP_TEXT,
    explain_rejection,
    render_action_result,
    render_look,
    render_move_result,
)

__all__ = [
    "DiscordBot",
    "HELP_TEXT",
    "assign_discord_controller",
    "did_you_mean",
    "explain_rejection",
    "render_action_result",
    "render_look",
    "render_move_result",
]


def __getattr__(name: str):
    if name == "DiscordBot":
        from .bot import DiscordBot

        return DiscordBot
    raise AttributeError(name)
