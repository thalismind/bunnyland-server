"""Discord front-end (spec 24). Import the bot lazily so the extra stays optional."""

from .bot import assign_discord_controller, did_you_mean
from .view import HELP_TEXT, render_look

__all__ = ["DiscordBot", "HELP_TEXT", "assign_discord_controller", "did_you_mean", "render_look"]


def __getattr__(name: str):
    if name == "DiscordBot":
        from .bot import DiscordBot

        return DiscordBot
    raise AttributeError(name)
