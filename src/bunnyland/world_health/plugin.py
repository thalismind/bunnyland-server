"""Canonical optional world-health metrics plugin entrypoint."""

from __future__ import annotations

from .. import telemetry
from ..core import WorldActor
from ..plugins.ids import WORLD_HEALTH
from ..plugins.model import Plugin, PluginPlacement, RuntimeContribution
from .metrics import collect_world_health_issues


def install_world_health_metrics(actor: WorldActor) -> None:
    """Register the collection-time audit when telemetry is active."""

    telemetry.register_world_health_gauge(actor, collect_world_health_issues)


def plugin() -> Plugin:
    return Plugin(
        id=WORLD_HEALTH,
        name="World Health Metrics",
        placement=PluginPlacement.ADDON,
        default_enabled=False,
        runtime=RuntimeContribution(service_factories=(install_world_health_metrics,)),
    )


def bunnyland_plugins() -> list[Plugin]:
    return [plugin()]


__all__ = ["bunnyland_plugins", "install_world_health_metrics", "plugin"]
