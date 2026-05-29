"""Discord front-end (spec 24). Import the bot lazily so the extra stays optional."""

__all__ = ["DiscordBot"]


def __getattr__(name: str):
    if name == "DiscordBot":
        from .bot import DiscordBot

        return DiscordBot
    raise AttributeError(name)
