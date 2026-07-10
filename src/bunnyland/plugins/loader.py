"""Plugin loading and application (spec 21.3).

A module exposes ``bunnyland_plugins() -> list[Plugin]``. The loader imports requested
modules, selects which plugin ids to enable (explicit list or all ``default_enabled``),
orders them by dependency, and applies each to a world actor.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter, ValidationError

from ..core.actions import action_definition_for_command_type, inferred_action_definition
from .contributions import collect_content_items
from .model import Plugin, PluginRuntimeContext
from .registry import PluginRegistry

if TYPE_CHECKING:
    from ..core.world_actor import WorldActor

ENTRYPOINT = "bunnyland_plugins"
LOG = logging.getLogger(__name__)


class PluginError(RuntimeError):
    pass


def _qualify_plugin(module_name: str, plugin: Plugin) -> Plugin:
    """Namespace imported plugin ids by their source module for tracking and selection."""

    def qualify(value: str) -> str:
        return value if "." in value else f"{module_name}.{value}"

    dependencies = plugin.dependencies.model_copy(
        update={
            "requires": tuple(qualify(dep) for dep in plugin.dependencies.requires),
            "recommends": tuple(qualify(dep) for dep in plugin.dependencies.recommends),
            "integrates_with": tuple(
                qualify(dep) for dep in plugin.dependencies.integrates_with
            ),
        }
    )
    return plugin.model_copy(update={"id": qualify(plugin.id), "dependencies": dependencies})


def load_modules(module_names: Iterable[str]) -> list[Plugin]:
    """Import each module and collect the plugins it declares."""
    plugins: list[Plugin] = []
    for name in module_names:
        module = importlib.import_module(name)
        entry = getattr(module, ENTRYPOINT, None)
        if entry is None:
            raise PluginError(f"module {name!r} has no {ENTRYPOINT}() entrypoint")
        result = entry()
        plugins.extend(_qualify_plugin(name, plugin) for plugin in result)
    return plugins


def _match_plugin_id(by_id: dict[str, Plugin], requested: str) -> Plugin:
    if requested in by_id:
        return by_id[requested]
    suffix = f".{requested}"
    matches = [plugin for plugin_id, plugin in by_id.items() if plugin_id.endswith(suffix)]
    if not matches:
        raise PluginError(f"unknown plugin id {requested!r}")
    if len(matches) > 1:
        ids = ", ".join(sorted(plugin.id for plugin in matches))
        raise PluginError(f"ambiguous plugin id {requested!r}; matches: {ids}")
    return matches[0]


def select(plugins: Sequence[Plugin], enabled_ids: Sequence[str] | None) -> list[Plugin]:
    """Choose plugins by explicit id, or all ``default_enabled`` when none are given."""
    by_id = {p.id: p for p in plugins}
    if enabled_ids is None:
        return [p for p in plugins if p.default_enabled]
    chosen: list[Plugin] = []
    for plugin_id in enabled_ids:
        chosen.append(_match_plugin_id(by_id, plugin_id))
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
        for dep in plugin.dependencies.requires:
            if dep not in by_id:
                raise PluginError(f"plugin {plugin.id!r} depends on missing {dep!r}")
            visit(by_id[dep])
        for dep in plugin.dependencies.recommends:
            if dep not in by_id:
                LOG.warning("plugin %r recommends missing %r", plugin.id, dep)
        visiting.discard(plugin.id)
        done.add(plugin.id)
        ordered.append(plugin)

    for plugin in plugins:
        visit(plugin)
    return ordered


def collect_prompt_fragments(plugins: Sequence[Plugin]) -> list:
    """Gather all prompt fragment providers contributed by the given plugins (spec 16.3)."""
    return list(collect_content_items(plugins, "prompt_fragments"))


def collect_persona_fragments(plugins: Sequence[Plugin]) -> list:
    """Gather stable persona fragment providers contributed by the given plugins."""
    return list(collect_content_items(plugins, "persona_fragments"))


def collect_prompt_enhancers(plugins: Sequence[Plugin]) -> list:
    """Gather image-prompt enhancers contributed by the given plugins (spec 27)."""
    return list(collect_content_items(plugins, "prompt_enhancers"))


def _instantiate(item):
    """Allow contributions to be classes (instantiated) or ready instances."""
    return item() if isinstance(item, type) else item


def _call_runtime_factory(factory, actor: WorldActor, context: PluginRuntimeContext) -> None:
    params = list(inspect.signature(factory).parameters.values())
    positional = [
        param
        for param in params
        if param.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    context_param = next((param for param in params if param.name == "context"), None)
    if context_param is not None and context_param.kind is inspect.Parameter.KEYWORD_ONLY:
        factory(actor, context=context)
        return
    if len(positional) >= 2 or context_param is not None:
        factory(actor, context)
        return
    factory(actor)


def validate_plugin_config(
    plugins: Sequence[Plugin],
    raw_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate YAML plugin config blocks against enabled plugin schemas."""
    if not raw_config:
        return {}

    by_id = {plugin.id: plugin for plugin in plugins}
    validated: dict[str, Any] = {}
    for requested_id, value in raw_config.items():
        plugin = _match_plugin_id(by_id, requested_id)
        model = plugin.config.model
        if model is None:
            validated[plugin.id] = value
            continue
        try:
            validated[plugin.id] = TypeAdapter(model).validate_python(value)
        except ValidationError as exc:
            raise PluginError(f"invalid config for plugin {plugin.id!r}: {exc}") from exc
    return validated


def _subscribe_worldgen_hook(actor: WorldActor, hook) -> None:
    """Register a generation hook contributed by plugin content."""

    instance = _instantiate(hook)
    legacy_handlers = tuple(
        getattr(instance, name, None)
        for name in ("_on_room", "_on_object", "_on_character", "_on_entity", "_on_site")
    )
    if any(callable(handler) for handler in legacy_handlers):
        # Transitional adapter: generation entry points invoke these before publishing the
        # finalized event, rather than using the event as a mutation trigger.
        instance.actor = actor
        actor._worldgen_hooks.append(instance)
        return
    subscribe = getattr(instance, "subscribe", None)
    if subscribe is not None:
        params = list(inspect.signature(subscribe).parameters)
        if params and params[0] == "actor":
            subscribe(actor)
        else:
            subscribe(actor.bus)
        return
    if callable(instance):
        actor._worldgen_hooks.append(instance)
        return
    raise PluginError(f"worldgen hook {hook!r} is not callable and has no subscribe()")


def apply_plugin(
    plugin: Plugin,
    actor: WorldActor,
    context: PluginRuntimeContext | None = None,
) -> None:
    """Wire a single plugin's contributions into the actor."""
    context = context or PluginRuntimeContext()
    registration = actor.bus.begin_registration(plugin.id, plugin.placement.value)
    try:
        for system in plugin.ecs.systems:
            actor.world.register_system(_instantiate(system))
        for observer in plugin.ecs.observers:
            actor.world.observe(_instantiate(observer))
        for definition in plugin.commands.action_definitions:
            actor.register_action_definition(_instantiate(definition))
        for handler in plugin.commands.action_handlers:
            instance = _instantiate(handler)
            actor.register_handler(instance)
            if not any(
                definition.command_type == instance.command_type
                for definition in actor.action_definitions()
            ):
                actor.register_action_definition(
                    action_definition_for_command_type(instance.command_type)
                    or inferred_action_definition(instance.command_type)
                )
        for hook in plugin.content.worldgen_hooks:
            _subscribe_worldgen_hook(actor, hook)
        for factory in (
            plugin.runtime.controller_factories
            + plugin.runtime.generator_factories
            + plugin.runtime.service_factories
            + plugin.runtime.projection_factories
        ):
            _call_runtime_factory(factory, actor, context)
    finally:
        actor.bus.end_registration(registration)


def apply_plugins(
    plugins: Sequence[Plugin],
    actor: WorldActor,
    context: PluginRuntimeContext | None = None,
) -> list[Plugin]:
    """Resolve order and apply each plugin. Returns the applied order."""
    ordered = resolve_order(plugins)
    registry = PluginRegistry(ordered)
    actor.plugins = registry
    context = context or PluginRuntimeContext()
    context.plugins = registry
    for plugin in ordered:
        apply_plugin(plugin, actor, context)
    # Optional integrations are deliberately installed only after every enabled plugin's
    # ordinary contracts and mechanics are registered.
    for plugin in ordered:
        for factory in plugin.runtime.integration_factories:
            registration = actor.bus.begin_registration(plugin.id, plugin.placement.value)
            try:
                _call_runtime_factory(factory, actor, context)
            finally:
                actor.bus.end_registration(registration)
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
    "collect_persona_fragments",
    "collect_prompt_enhancers",
    "collect_prompt_fragments",
    "load_and_apply",
    "load_modules",
    "resolve_order",
    "select",
    "validate_plugin_config",
]
