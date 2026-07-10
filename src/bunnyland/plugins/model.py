"""Plugin contribution models (spec 21.2).

A plugin is a loadable bundle of contributions, not necessarily a single mechanic. The
models mirror the spec; the loader (``loader.py``) applies them to a world actor.

Pragmatic conventions for MVP:
- ``ecs.systems`` and ``commands.action_handlers`` may be zero-arg classes (instantiated
  at apply time) or ready instances.
- ``runtime.*_factories`` are callables ``factory(actor) -> None`` that perform stateful
  wiring (stores, consequences, projections, controllers, integrations).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EcsContribution(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    components: tuple[type, ...] = ()
    edges: tuple[type, ...] = ()
    systems: tuple[Any, ...] = ()
    observers: tuple[Any, ...] = ()


class CommandContribution(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    command_types: tuple[type, ...] = ()
    action_handlers: tuple[Any, ...] = ()
    action_definitions: tuple[Any, ...] = ()
    typed_events: tuple[type, ...] = ()


class RuntimeContribution(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    controller_factories: tuple[Any, ...] = ()
    generator_factories: tuple[Any, ...] = ()
    service_factories: tuple[Any, ...] = ()
    projection_factories: tuple[Any, ...] = ()
    integration_factories: tuple[Any, ...] = ()
    #: HTTP router factories called by the FastAPI app factory after built-in middleware is
    #: installed. A factory receives ``(app, actor, **context)`` and may include routers.
    server_routers: tuple[Any, ...] = ()

    def all_factories(self) -> tuple[Any, ...]:
        return (
            self.controller_factories
            + self.generator_factories
            + self.service_factories
            + self.projection_factories
            + self.integration_factories
        )


class ContentContribution(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    prefabs: tuple[Any, ...] = ()
    prompt_parts: tuple[Any, ...] = ()
    worldgen_hooks: tuple[Any, ...] = ()
    #: Script definitions or paths contributed by the plugin.
    scripts: tuple[Any, ...] = ()
    #: Named ``WorldGenerator`` strategies, selectable at runtime by name.
    world_generators: tuple[Any, ...] = ()
    #: Prompt fragment providers ``(world, character) -> list[str]`` (spec 16.3).
    prompt_fragments: tuple[Any, ...] = ()
    #: Stable persona fragment providers for identity, role, bonds, and boundaries.
    persona_fragments: tuple[Any, ...] = ()
    #: Image-prompt enhancers (``PromptEnhancer`` instances) for image generation (spec 27).
    prompt_enhancers: tuple[Any, ...] = ()
    #: Namespaced capabilities this plugin can satisfy during generation.
    generation_capabilities: tuple[str, ...] = ()
    #: Legacy intent names mapped to a namespaced generation capability.
    generation_aliases: dict[str, str] = Field(default_factory=dict)
    #: Pure request normalizers run before generation enrichers.
    intent_normalizers: tuple[Any, ...] = ()
    #: Declarative generation enrichers contributed by this plugin.
    generation_enrichers: tuple[Any, ...] = ()
    #: Storyteller incident definitions contributed by this plugin.
    incident_definitions: tuple[Any, ...] = ()


class PolicyContribution(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    boundary_tags: frozenset[str] = Field(default_factory=frozenset)
    world_defaults: dict[str, Any] = Field(default_factory=dict)
    config_schema: type | None = None


class ConfigContribution(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    model: type | None = None


class DependencyContribution(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    requires: tuple[str, ...] = ()
    recommends: tuple[str, ...] = ()
    integrates_with: tuple[str, ...] = ()


class PluginPlacement(StrEnum):
    """Architectural ring used for deterministic registration and reaction ordering."""

    CORE = "core"
    FOUNDATION = "foundation"
    INNER = "inner"
    OUTER = "outer"
    ADDON = "addon"


class Plugin(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    id: str
    name: str
    version: str = "0.1.0"
    placement: PluginPlacement = PluginPlacement.OUTER

    dependencies: DependencyContribution = Field(default_factory=DependencyContribution)
    default_enabled: bool = True

    ecs: EcsContribution = Field(default_factory=EcsContribution)
    commands: CommandContribution = Field(default_factory=CommandContribution)
    runtime: RuntimeContribution = Field(default_factory=RuntimeContribution)
    content: ContentContribution = Field(default_factory=ContentContribution)
    policy: PolicyContribution = Field(default_factory=PolicyContribution)
    config: ConfigContribution = Field(default_factory=ConfigContribution)


class PluginRuntimeContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    plugin_config: dict[str, Any] = Field(default_factory=dict)
    addon_config: dict[str, Any] = Field(default_factory=dict)
    plugins: Any | None = None

    def config_for(self, plugin_id: str, default: Any = None) -> Any:
        return self.plugin_config.get(plugin_id, default)


__all__ = [
    "CommandContribution",
    "ConfigContribution",
    "ContentContribution",
    "DependencyContribution",
    "EcsContribution",
    "Plugin",
    "PluginPlacement",
    "PluginRuntimeContext",
    "PolicyContribution",
    "RuntimeContribution",
]
