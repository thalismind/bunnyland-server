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

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from ..core.action_overrides import EntityActionCallbackDefinition
from .policy import BoundaryScope


class EcsContribution(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    components: tuple[type, ...] = ()
    edges: tuple[type, ...] = ()
    systems: tuple[object, ...] = ()
    observers: tuple[object, ...] = ()


class CommandContribution(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    command_types: tuple[type, ...] = ()
    action_handlers: tuple[object, ...] = ()
    action_definitions: tuple[object, ...] = ()
    typed_events: tuple[type, ...] = ()
    action_callbacks: tuple[EntityActionCallbackDefinition, ...] = ()


class RuntimeContribution(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    controller_factories: tuple[object, ...] = ()
    generator_factories: tuple[object, ...] = ()
    service_factories: tuple[object, ...] = ()
    projection_factories: tuple[object, ...] = ()
    integration_factories: tuple[object, ...] = ()
    #: Explicitly zoned HTTP contributions. Registrars receive only their zone router.
    http: tuple[HttpContribution, ...] = ()
    #: Cross-cutting MCP registrars. Each registered capability must declare its own policy.
    mcp: tuple[McpContribution, ...] = ()
    perspective_queries: tuple[object, ...] = ()

    def all_factories(self) -> tuple[object, ...]:
        return (
            self.controller_factories
            + self.generator_factories
            + self.service_factories
            + self.projection_factories
            + self.integration_factories
        )


class ContentContribution(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    prefabs: tuple[object, ...] = ()
    prompt_parts: tuple[object, ...] = ()
    #: Script definitions or paths contributed by the plugin.
    scripts: tuple[object, ...] = ()
    #: Named ``WorldGenerator`` strategies, selectable at runtime by name.
    world_generators: tuple[object, ...] = ()
    #: Prompt fact providers ``(world, character) -> Sequence[PromptFact]`` (spec 16.3).
    prompt_fragments: tuple[object, ...] = ()
    #: Stable persona fragment providers for identity, role, bonds, and boundaries.
    persona_fragments: tuple[object, ...] = ()
    #: Async post-render text filters contributed by plugins.
    prompt_filters: tuple[object, ...] = ()
    #: Image-prompt enhancers (``PromptEnhancer`` instances) for image generation (spec 27).
    prompt_enhancers: tuple[object, ...] = ()
    #: Named image-generator factories. Factories receive global and owner plugin config.
    image_generators: tuple[object, ...] = ()
    #: Namespaced capabilities this plugin can satisfy during generation.
    generation_capabilities: tuple[str, ...] = ()
    #: Pure request normalizers run before generation enrichers.
    intent_normalizers: tuple[object, ...] = ()
    #: Declarative generation enrichers contributed by this plugin.
    generation_enrichers: tuple[object, ...] = ()
    #: Storyteller incident definitions contributed by this plugin.
    incident_definitions: tuple[object, ...] = ()
    #: Plugin-owned completion predicates for spawned incident requirements.
    incident_resolution_rules: tuple[object, ...] = ()


class PolicyContribution(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    boundary_tags: frozenset[BoundaryScope] = Field(default_factory=frozenset)
    world_defaults: dict[str, JsonValue] = Field(default_factory=dict)
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


class HttpZone(StrEnum):
    PUBLIC = "public"
    PLAY = "play"
    ADMIN = "admin"


class HttpContribution(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    zone: HttpZone
    registrars: tuple[object, ...]


class McpContribution(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    registrars: tuple[object, ...]


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

    plugin_config: dict[str, object] = Field(default_factory=dict)
    addon_config: dict[str, object] = Field(default_factory=dict)
    plugins: object | None = None

    def config_for(self, plugin_id: str, default: object = None) -> object:
        return self.plugin_config.get(plugin_id, default)


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
    "PluginPlacement",
    "PluginRuntimeContext",
    "PolicyContribution",
    "RuntimeContribution",
]
