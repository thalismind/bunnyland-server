"""Optional collection-time world-health metrics."""

from .metrics import HEALTH_CHECKS, collect_world_health_issues
from .plugin import bunnyland_plugins, plugin

__all__ = [
    "HEALTH_CHECKS",
    "bunnyland_plugins",
    "collect_world_health_issues",
    "plugin",
]
