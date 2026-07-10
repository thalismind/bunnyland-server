"""Canonical Garden Sim plugin entrypoint."""

from ...plugins.builtin import gardensim_plugin
from ...plugins.model import Plugin, PluginPlacement


def plugin() -> Plugin:
    return gardensim_plugin().model_copy(update={"placement": PluginPlacement.INNER})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
