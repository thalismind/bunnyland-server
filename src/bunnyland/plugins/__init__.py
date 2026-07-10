"""Plugin system (spec 21): loadable contribution bundles + loader."""

from .loader import (
    PluginError,
    apply_plugin,
    apply_plugins,
    collect_persona_fragments,
    collect_prompt_enhancers,
    collect_prompt_fragments,
    load_and_apply,
    load_modules,
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
    Plugin,
    PluginPlacement,
    PluginRuntimeContext,
    PolicyContribution,
    RuntimeContribution,
)
from .registry import PluginRegistry


def bunnyland_plugins():
    """Load the bundled compatibility catalogue without coupling canonical entrypoints."""
    from .builtin import bunnyland_plugins as collect

    return collect()

__all__ = [
    "CommandContribution",
    "ConfigContribution",
    "ContentContribution",
    "DependencyContribution",
    "EcsContribution",
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
    "collect_prompt_enhancers",
    "collect_prompt_fragments",
    "load_and_apply",
    "load_modules",
    "resolve_order",
    "select",
    "validate_plugin_config",
]
