"""Plugin system (spec 21): loadable contribution bundles + loader."""

from .builtin import bunnyland_plugins
from .loader import (
    PluginError,
    apply_plugin,
    apply_plugins,
    collect_persona_fragments,
    collect_prompt_fragments,
    load_and_apply,
    load_modules,
    resolve_order,
    select,
)
from .model import (
    CommandContribution,
    ContentContribution,
    DependencyContribution,
    EcsContribution,
    Plugin,
    PolicyContribution,
    RuntimeContribution,
)

__all__ = [
    "CommandContribution",
    "ContentContribution",
    "DependencyContribution",
    "EcsContribution",
    "Plugin",
    "PluginError",
    "PolicyContribution",
    "RuntimeContribution",
    "apply_plugin",
    "apply_plugins",
    "bunnyland_plugins",
    "collect_persona_fragments",
    "collect_prompt_fragments",
    "load_and_apply",
    "load_modules",
    "resolve_order",
    "select",
]
