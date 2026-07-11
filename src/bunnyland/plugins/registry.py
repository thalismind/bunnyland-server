"""Resolved, typed indexes for enabled plugin contracts."""

from __future__ import annotations

from collections.abc import Iterable
from inspect import getmembers, isclass
from types import MappingProxyType
from typing import Any

from .model import Plugin, PluginPlacement

_PLACEMENT_ORDER = {
    PluginPlacement.CORE: 0,
    PluginPlacement.FOUNDATION: 1,
    PluginPlacement.INNER: 2,
    PluginPlacement.OUTER: 3,
    PluginPlacement.ADDON: 4,
}


def placement_order(placement: PluginPlacement | str) -> int:
    """Return the stable ordering rank for a plugin placement."""

    return _PLACEMENT_ORDER[PluginPlacement(placement)]


def _public_name(value: Any) -> str:
    for attribute in ("id", "name", "command_type"):
        candidate = getattr(value, attribute, None)
        if isinstance(candidate, str) and candidate:
            return candidate
    candidate = getattr(value, "__name__", None)
    if isinstance(candidate, str) and candidate:
        return candidate
    return type(value).__name__


class PluginRegistry:
    """Runtime source of truth for contracts exported by enabled plugins."""

    def __init__(self, plugins: Iterable[Plugin] = ()) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._events: dict[tuple[str, str], type] = {}
        self._event_owners: dict[type, tuple[str, str]] = {}
        self._actions: dict[str, tuple[str, Any]] = {}
        self._generators: dict[str, tuple[str, Any]] = {}
        self._components: dict[str, tuple[str, type]] = {}
        self._edges: dict[str, tuple[str, type]] = {}
        self._capabilities: dict[str, tuple[str, Any | None]] = {}
        self._services: dict[tuple[str, str], Any] = {}
        self._projections: dict[tuple[str, str], Any] = {}
        self._incidents: dict[tuple[str, str], Any] = {}
        self._incident_resolution_rules: dict[tuple[str, str], Any] = {}
        self._integrations: dict[tuple[str, str], Any] = {}
        self._normalizers: list[tuple[str, Any]] = []
        from ..core.generation import CoreGenerationEnricher

        self._enrichers: list[tuple[str, Any]] = [("bunnyland.core", CoreGenerationEnricher())]
        self._seed_core_contracts()
        for plugin in plugins:
            self.register(plugin)

    def _seed_core_contracts(self) -> None:
        from relics import Component, Edge

        from ..core import components, controllers, edges, events
        from ..core.events import DomainEvent

        for module in (components, controllers):
            for _name, value in getmembers(module, isclass):
                if (
                    value is not Component
                    and issubclass(value, Component)
                    and value.__module__ == module.__name__
                ):
                    self._components[value.__name__] = ("bunnyland.core", value)
        for _name, value in getmembers(edges, isclass):
            if value is not Edge and issubclass(value, Edge) and value.__module__ == edges.__name__:
                self._edges[value.__name__] = ("bunnyland.core", value)
        for _name, value in getmembers(events, isclass):
            if (
                value is not DomainEvent
                and issubclass(value, DomainEvent)
                and value.__module__ == events.__name__
            ):
                key = ("bunnyland.core", value.__name__)
                self._events[key] = value
                self._event_owners[value] = key

    @property
    def plugins(self):
        return MappingProxyType(self._plugins)

    @property
    def events(self):
        return MappingProxyType(self._events)

    @property
    def actions(self):
        return MappingProxyType(self._actions)

    @property
    def generators(self):
        return MappingProxyType(self._generators)

    @property
    def components(self):
        return MappingProxyType(self._components)

    @property
    def edges(self):
        return MappingProxyType(self._edges)

    @property
    def capabilities(self):
        return MappingProxyType(self._capabilities)

    @property
    def incidents(self):
        return MappingProxyType(self._incidents)

    @property
    def incident_resolution_rules(self):
        return MappingProxyType(self._incident_resolution_rules)

    @property
    def services(self):
        return MappingProxyType(self._services)

    @property
    def projections(self):
        return MappingProxyType(self._projections)

    @property
    def integrations(self):
        return MappingProxyType(self._integrations)

    @property
    def intent_normalizers(self) -> tuple[tuple[str, Any], ...]:
        return tuple(self._normalizers)

    @property
    def generation_enrichers(self) -> tuple[tuple[str, Any], ...]:
        return tuple(self._enrichers)

    def enabled(self, plugin_id: str) -> bool:
        return plugin_id == "bunnyland.core" or plugin_id in self._plugins

    def plugin(self, plugin_id: str) -> Plugin:
        try:
            return self._plugins[plugin_id]
        except KeyError as exc:
            from .loader import PluginError

            raise PluginError(f"plugin {plugin_id!r} is not enabled") from exc

    def placement(self, plugin_id: str) -> PluginPlacement:
        if plugin_id == "bunnyland.core":
            return PluginPlacement.CORE
        return self.plugin(plugin_id).placement

    def _global(self, index: dict, name: str, plugin_id: str, value: Any, surface: str) -> None:
        previous = index.get(name)
        if previous is not None:
            owner, _old_value = previous
            from .loader import PluginError

            raise PluginError(
                f"duplicate {surface} name {name!r} exported by {owner!r} and {plugin_id!r}"
            )
        index[name] = (plugin_id, value)

    def _scoped(self, index: dict, plugin_id: str, value: Any, surface: str) -> None:
        key = (plugin_id, _public_name(value))
        if key in index:
            from .loader import PluginError

            raise PluginError(f"duplicate {surface} id {key[1]!r} in plugin {plugin_id!r}")
        index[key] = value

    def register(self, plugin: Plugin) -> None:
        if plugin.id in self._plugins:
            from .loader import PluginError

            raise PluginError(f"duplicate plugin id {plugin.id!r}")
        self._plugins[plugin.id] = plugin

        for event_type in plugin.commands.typed_events:
            if self._event_owners.get(event_type, (None,))[0] == "bunnyland.core":
                continue
            export_name = event_type.__name__
            key = (plugin.id, export_name)
            if key in self._events:
                from .loader import PluginError

                raise PluginError(f"duplicate event export {export_name!r} in {plugin.id!r}")
            previous = self._event_owners.get(event_type)
            if previous is not None:
                from .loader import PluginError

                raise PluginError(
                    f"event class {event_type!r} is already owned by plugin {previous[0]!r}"
                )
            self._events[key] = event_type
            self._event_owners[event_type] = key

        for definition in plugin.commands.action_definitions:
            self._global(
                self._actions,
                definition.command_type,
                plugin.id,
                definition,
                "action",
            )
        for generator in plugin.content.world_generators:
            self._global(self._generators, generator.name, plugin.id, generator, "generator")
        for component in plugin.ecs.components:
            if self._components.get(component.__name__) == ("bunnyland.core", component):
                continue
            self._global(
                self._components, component.__name__, plugin.id, component, "component type"
            )
        for edge in plugin.ecs.edges:
            if self._edges.get(edge.__name__) == ("bunnyland.core", edge):
                continue
            self._global(self._edges, edge.__name__, plugin.id, edge, "edge type")

        for capability in plugin.content.generation_capabilities:
            if not capability.startswith(f"{plugin.id}."):
                from .loader import PluginError

                raise PluginError(
                    f"generation capability {capability!r} must be namespaced by {plugin.id!r}"
                )
            self._global(self._capabilities, capability, plugin.id, None, "capability")
        for factory in plugin.runtime.service_factories:
            self._scoped(self._services, plugin.id, factory, "service")
        for factory in plugin.runtime.projection_factories:
            self._scoped(self._projections, plugin.id, factory, "projection")
        for incident in plugin.content.incident_definitions:
            self._scoped(self._incidents, plugin.id, incident, "incident")
        for rule in plugin.content.incident_resolution_rules:
            self._scoped(
                self._incident_resolution_rules,
                plugin.id,
                rule,
                "incident resolution rule",
            )
        for integration in plugin.runtime.integration_factories:
            self._scoped(self._integrations, plugin.id, integration, "integration")
        self._normalizers.extend(
            (plugin.id, normalizer) for normalizer in plugin.content.intent_normalizers
        )
        self._enrichers.extend(
            (plugin.id, enricher) for enricher in plugin.content.generation_enrichers
        )

    def event_key(self, event_type: type) -> str | None:
        owner = self._event_owners.get(event_type)
        return f"{owner[0]}:{owner[1]}" if owner is not None else None

    def resolve_event(self, provider_plugin_id: str, export_name: str) -> type:
        try:
            return self._events[(provider_plugin_id, export_name)]
        except KeyError as exc:
            from .loader import PluginError

            raise PluginError(
                f"plugin {provider_plugin_id!r} does not export event {export_name!r}"
            ) from exc

    def require_exported_event(
        self,
        provider_plugin_id: str,
        event_type: type,
        export_name: str | None = None,
    ) -> type:
        """Validate an optional integration's exact provider event class."""

        if provider_plugin_id != "bunnyland.core":
            self.plugin(provider_plugin_id)
        name = export_name or event_type.__name__
        exported = self.resolve_event(provider_plugin_id, name)
        if exported is not event_type:
            from .loader import PluginError

            raise PluginError(
                f"plugin {provider_plugin_id!r} exports an incompatible {name!r} event class"
            )
        return event_type


__all__ = ["PluginRegistry", "placement_order"]
