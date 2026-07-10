"""Canonical Mechanisms plugin entrypoint."""

from ...mechanics.mechanisms import install_mechanisms
from ...plugins.ids import (
    CORE_VERBS,
    MECHANISMS,
)
from ...plugins.model import (
    DependencyContribution,
    Plugin,
    PluginPlacement,
    RuntimeContribution,
)


def _mechanisms_factory(actor) -> None:
    install_mechanisms(actor)


def _definition() -> Plugin:
    return Plugin(
        id=MECHANISMS,
        name="Mechanisms",
        dependencies=DependencyContribution(requires=(CORE_VERBS,)),
        runtime=RuntimeContribution(service_factories=(_mechanisms_factory,)),
    )


def plugin() -> Plugin:
    return _definition().model_copy(update={"placement": PluginPlacement.FOUNDATION})


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "plugin"]
