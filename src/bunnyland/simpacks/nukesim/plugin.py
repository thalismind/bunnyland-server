"""Canonical Nuke Sim plugin entrypoint."""

from ...plugins.builtin import nukesim_plugin
from ...plugins.model import Plugin, PluginPlacement


def plugin() -> Plugin:
    return nukesim_plugin().model_copy(update={"placement": PluginPlacement.OUTER})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
