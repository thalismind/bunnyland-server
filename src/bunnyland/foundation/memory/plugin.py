"""Canonical Memory plugin entrypoint."""

from ...memory import install_memory
from ...plugins.ids import (
    CORE_VERBS,
    MEMORY,
)
from ...plugins.model import (
    CommandContribution,
    DependencyContribution,
    Plugin,
    PluginPlacement,
    RuntimeContribution,
)
from .actions import ACTION_DEFINITIONS


def _memory_factory(actor) -> None:
    install_memory(actor)


def _definition() -> Plugin:
    return Plugin(
        id=MEMORY,
        name="Memory",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        commands=CommandContribution(action_definitions=ACTION_DEFINITIONS),
        runtime=RuntimeContribution(service_factories=(_memory_factory,)),
    )


def plugin() -> Plugin:
    return _definition().model_copy(update={"placement": PluginPlacement.FOUNDATION})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
