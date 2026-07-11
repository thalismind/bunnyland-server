"""Discord persisted-type ownership plugin."""

from ..plugins.ids import DISCORD
from ..plugins.model import EcsContribution, Plugin, PluginPlacement
from .components import DiscordRoomFeedComponent


def plugin() -> Plugin:
    return Plugin(
        id=DISCORD,
        name="Discord",
        placement=PluginPlacement.FOUNDATION,
        ecs=EcsContribution(components=(DiscordRoomFeedComponent,)),
    )


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
