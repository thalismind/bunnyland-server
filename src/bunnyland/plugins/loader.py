"""Plugin loading and application (spec 21.3).

A module exposes ``bunnyland_plugins() -> list[Plugin]``. The loader imports requested
modules, selects which plugin ids to enable (explicit list or all ``default_enabled``),
orders them by dependency, and applies each to a world actor.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from .model import Plugin

if TYPE_CHECKING:
    from ..core.world_actor import WorldActor

ENTRYPOINT = "bunnyland_plugins"


class PluginError(RuntimeError):
    pass


def load_modules(module_names: Iterable[str]) -> list[Plugin]:
    """Import each module and collect the plugins it declares."""
    plugins: list[Plugin] = []
    for name in module_names:
        module = importlib.import_module(name)
        entry = getattr(module, ENTRYPOINT, None)
        if entry is None:
            raise PluginError(f"module {name!r} has no {ENTRYPOINT}() entrypoint")
        result = entry()
        plugins.extend(result)
    return plugins


def select(plugins: Sequence[Plugin], enabled_ids: Sequence[str] | None) -> list[Plugin]:
    """Choose plugins by explicit id, or all ``default_enabled`` when none are given."""
    by_id = {p.id: p for p in plugins}
    if enabled_ids is None:
        return [p for p in plugins if p.default_enabled]
    chosen: list[Plugin] = []
    for plugin_id in enabled_ids:
        if plugin_id not in by_id:
            raise PluginError(f"unknown plugin id {plugin_id!r}")
        chosen.append(by_id[plugin_id])
    return chosen


def resolve_order(plugins: Sequence[Plugin]) -> list[Plugin]:
    """Topologically sort plugins so dependencies are applied first."""
    by_id = {p.id: p for p in plugins}
    ordered: list[Plugin] = []
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(plugin: Plugin) -> None:
        if plugin.id in done:
            return
        if plugin.id in visiting:
            raise PluginError(f"dependency cycle involving {plugin.id!r}")
        visiting.add(plugin.id)
        for dep in plugin.dependencies:
            if dep not in by_id:
                raise PluginError(f"plugin {plugin.id!r} depends on missing {dep!r}")
            visit(by_id[dep])
        visiting.discard(plugin.id)
        done.add(plugin.id)
        ordered.append(plugin)

    for plugin in plugins:
        visit(plugin)
    return ordered


def _instantiate(item):
    """Allow contributions to be classes (instantiated) or ready instances."""
    return item() if isinstance(item, type) else item


def apply_plugin(plugin: Plugin, actor: WorldActor) -> None:
    """Wire a single plugin's contributions into the actor."""
    for system in plugin.ecs.systems:
        actor.world.register_system(_instantiate(system))
    for observer in plugin.ecs.observers:
        actor.world.observe(_instantiate(observer))
    for handler in plugin.commands.action_handlers:
        actor.register_handler(_instantiate(handler))
    for factory in plugin.runtime.all_factories():
        factory(actor)


def apply_plugins(plugins: Sequence[Plugin], actor: WorldActor) -> list[Plugin]:
    """Resolve order and apply each plugin. Returns the applied order."""
    ordered = resolve_order(plugins)
    for plugin in ordered:
        apply_plugin(plugin, actor)
    return ordered


def load_and_apply(
    actor: WorldActor,
    *,
    modules: Sequence[str] = (),
    enabled_ids: Sequence[str] | None = None,
) -> list[Plugin]:
    """Load plugins from modules, select + order + apply them to the actor."""
    plugins = load_modules(modules)
    chosen = select(plugins, enabled_ids)
    return apply_plugins(chosen, actor)


__all__ = [
    "PluginError",
    "apply_plugin",
    "apply_plugins",
    "load_and_apply",
    "load_modules",
    "resolve_order",
    "select",
]
