"""Canonical Mcp plugin entrypoint."""

from ...core.controllers import MCPControllerComponent
from ...plugins.ids import MCP
from ...plugins.model import (
    EcsContribution,
    Plugin,
    PluginPlacement,
)


def _definition() -> Plugin:
    return Plugin(
        id=MCP,
        name="MCP Server",
        default_enabled=False,
        ecs=EcsContribution(components=(MCPControllerComponent,)),
    )


def plugin() -> Plugin:
    return _definition().model_copy(update={"placement": PluginPlacement.FOUNDATION})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
