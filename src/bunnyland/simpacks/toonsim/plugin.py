"""Canonical Toon Sim plugin entrypoint."""

from ...plugins.builtin import toonsim_plugin
from ...plugins.model import Plugin, PluginPlacement


def plugin() -> Plugin:
    return toonsim_plugin().model_copy(update={"placement": PluginPlacement.OUTER})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
