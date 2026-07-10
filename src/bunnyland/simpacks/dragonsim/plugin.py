"""Canonical Dragon Sim plugin entrypoint."""

from ...plugins.builtin import dragonsim_plugin
from ...plugins.model import Plugin, PluginPlacement


def plugin() -> Plugin:
    return dragonsim_plugin().model_copy(update={"placement": PluginPlacement.OUTER})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
