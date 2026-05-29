"""Discord front-end (spec 24). Import the bot lazily so the extra stays optional."""

from .bot import did_you_mean

__all__ = ["DiscordBot", "did_you_mean"]


def __getattr__(name: str):
    if name == "DiscordBot":
        from .bot import DiscordBot

        return DiscordBot
    raise AttributeError(name)
