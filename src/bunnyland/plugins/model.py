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
    #: Named ``WorldGenerator`` strategies, selectable at runtime by name.
    world_generators: tuple[Any, ...] = ()


class PolicyContribution(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    boundary_tags: frozenset[str] = Field(default_factory=frozenset)
    world_defaults: dict[str, Any] = Field(default_factory=dict)
    config_schema: type | None = None


class Plugin(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    id: str
    name: str
    version: str = "0.1.0"

    dependencies: tuple[str, ...] = ()
    default_enabled: bool = True

    ecs: EcsContribution = Field(default_factory=EcsContribution)
    commands: CommandContribution = Field(default_factory=CommandContribution)
    runtime: RuntimeContribution = Field(default_factory=RuntimeContribution)
    content: ContentContribution = Field(default_factory=ContentContribution)
    policy: PolicyContribution = Field(default_factory=PolicyContribution)


__all__ = [
    "CommandContribution",
    "ContentContribution",
    "EcsContribution",
    "Plugin",
    "PolicyContribution",
    "RuntimeContribution",
]
