"""Plugin system (spec 21): loadable contribution bundles + loader."""

from .loader import (
    PluginError,
    apply_plugin,
    apply_plugins,
    collect_image_generators,
    collect_persona_fragments,
    collect_prompt_enhancers,
    collect_prompt_filters,
    collect_prompt_fragments,
    discover_plugins,
    resolve_order,
    select,
    validate_plugin_config,
)
from .model import (
    CommandContribution,
    ConfigContribution,
    ContentContribution,
    DependencyContribution,
    EcsContribution,
    HttpContribution,
    HttpZone,
    McpContribution,
    Plugin,
    PluginPlacement,
    PluginRuntimeContext,
    PolicyContribution,
    RuntimeContribution,
)
from .registry import PluginRegistry


def bunnyland_plugins():
    """Discover installed bundled and external plugins."""
    return discover_plugins()


__all__ = [
    "CommandContribution",
    "ConfigContribution",
    "ContentContribution",
    "DependencyContribution",
    "EcsContribution",
    "HttpContribution",
    "HttpZone",
    "McpContribution",
    "Plugin",
    "PluginError",
    "PluginPlacement",
    "PluginRegistry",
    "PluginRuntimeContext",
    "PolicyContribution",
    "RuntimeContribution",
    "apply_plugin",
    "apply_plugins",
    "bunnyland_plugins",
    "collect_persona_fragments",
    "collect_image_generators",
    "collect_prompt_enhancers",
    "collect_prompt_filters",
    "collect_prompt_fragments",
    "discover_plugins",
    "resolve_order",
    "select",
    "validate_plugin_config",
]
