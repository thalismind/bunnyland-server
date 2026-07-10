"""Plugin-neutral contracts for cooperative entity generation."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Protocol
from uuid import uuid4

from relics import Component, Edge


class GenerationError(RuntimeError):
    """A generation request could not be compiled into one valid atomic plan."""


@dataclass(frozen=True)
class GenerationRequest:
    """Normalized intent shared by every generation entry point."""

    entity_kind: str
    description: str = ""
    capabilities: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    source_seed: str = ""
    source_key: str = ""
    request_id: str = field(default_factory=lambda: uuid4().hex)
    parent_request_id: str | None = None
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationEdge:
    edge: Edge
    target_id: Any


@dataclass(frozen=True)
class GenerationDelta:
    """Declarative additions returned by one plugin enricher."""

    components: tuple[Component, ...] = ()
    edges: tuple[GenerationEdge, ...] = ()
    children: tuple[GenerationRequest, ...] = ()
    satisfies: tuple[str, ...] = ()


@dataclass(frozen=True)
class GenerationPlan:
    request: GenerationRequest
    components: tuple[Component, ...] = ()
    edges: tuple[GenerationEdge, ...] = ()
    children: tuple[GenerationRequest, ...] = ()
    unmet_capabilities: tuple[str, ...] = ()


class GenerationEnricher(Protocol):
    capabilities: tuple[str, ...]

    def enrich(self, request: GenerationRequest) -> GenerationDelta: ...


class CoreGenerationEnricher:
    """Plugin-neutral enrichment for components owned by Core itself."""

    capabilities: tuple[str, ...] = ()

    def enrich(self, request: GenerationRequest) -> GenerationDelta:
        from .components import KeyComponent

        text = " ".join((request.entity_kind, request.description, *request.tags)).casefold()
        wants_key = "key" in {value.casefold() for value in request.capabilities}
        has_key = any(
            isinstance(component, KeyComponent)
            for component in request.context.get("base_components", ())
        )
        if not has_key and (wants_key or "key" in text.split()):
            return GenerationDelta(components=(KeyComponent(key_name=request.description),))
        return GenerationDelta()


def _dedupe(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


class GenerationPipeline:
    """Normalize intent and merge every applicable enabled-plugin enrichment."""

    def __init__(self, registry: Any | None) -> None:
        self.registry = registry

    def normalize(self, request: GenerationRequest) -> GenerationRequest:
        aliases = self.registry.aliases if self.registry is not None else {}
        capabilities = [aliases.get(value, value) for value in request.capabilities]
        normalized = replace(request, capabilities=_dedupe(capabilities))
        if self.registry is None:
            return normalized
        for _plugin_id, normalizer in self.registry.intent_normalizers:
            callable_ = getattr(normalizer, "normalize", normalizer)
            result = callable_(normalized)
            if isinstance(result, GenerationRequest):
                normalized = result
            elif result is not None:
                normalized = replace(
                    normalized,
                    capabilities=_dedupe((*normalized.capabilities, *tuple(result))),
                )
        return normalized

    def _validate_component(self, plugin_id: str, component: Component) -> None:
        registered = self.registry.components.get(type(component).__name__)
        if registered is None:
            raise GenerationError(
                f"plugin {plugin_id!r} provides unregistered component {type(component).__name__!r}"
            )
        if registered is not None and registered != (plugin_id, type(component)):
            raise GenerationError(
                f"plugin {plugin_id!r} cannot provide component {type(component).__name__!r}; "
                f"it is owned by {registered[0]!r}"
            )

    def _validate_edge(self, plugin_id: str, edge: Edge) -> None:
        registered = self.registry.edges.get(type(edge).__name__)
        if registered is None:
            raise GenerationError(
                f"plugin {plugin_id!r} provides unregistered edge {type(edge).__name__!r}"
            )
        if registered is not None and registered != (plugin_id, type(edge)):
            raise GenerationError(
                f"plugin {plugin_id!r} cannot provide edge {type(edge).__name__!r}; "
                f"it is owned by {registered[0]!r}"
            )

    async def compile(
        self,
        request: GenerationRequest,
        *,
        base_components: tuple[Component, ...] = (),
    ) -> GenerationPlan:
        normalized = self.normalize(request)
        components = list(base_components)
        component_types = {type(component) for component in components}
        if len(component_types) != len(components):
            raise GenerationError("base generation contains duplicate singleton components")
        edges: list[GenerationEdge] = []
        children: list[GenerationRequest] = []
        satisfied: set[str] = set()

        if self.registry is not None:
            for plugin_id, enricher in self.registry.generation_enrichers:
                instance = enricher() if isinstance(enricher, type) else enricher
                capabilities = tuple(getattr(instance, "capabilities", ()))
                if capabilities and not set(capabilities).intersection(normalized.capabilities):
                    continue
                applies = getattr(instance, "applies", None)
                if applies is not None and not applies(normalized):
                    continue
                callable_ = getattr(instance, "enrich", instance)
                try:
                    delta = callable_(normalized)
                    if inspect.isawaitable(delta):
                        delta = await delta
                except Exception as exc:
                    raise GenerationError(
                        f"generation enricher from {plugin_id!r} failed: {exc}"
                    ) from exc
                if delta is None:
                    continue
                if not isinstance(delta, GenerationDelta):
                    raise GenerationError(
                        f"generation enricher from {plugin_id!r} returned {type(delta).__name__}, "
                        "expected GenerationDelta"
                    )
                for component in delta.components:
                    self._validate_component(plugin_id, component)
                    component_type = type(component)
                    if component_type in component_types:
                        raise GenerationError(
                            f"conflicting singleton component {component_type.__name__!r}"
                        )
                    component_types.add(component_type)
                    components.append(component)
                for edge_delta in delta.edges:
                    self._validate_edge(plugin_id, edge_delta.edge)
                    edges.append(edge_delta)
                children.extend(
                    replace(child, parent_request_id=normalized.request_id)
                    if child.parent_request_id is None
                    else child
                    for child in delta.children
                )
                satisfied.update(delta.satisfies or capabilities)

        available = set(self.registry.capabilities) if self.registry is not None else set()
        unmet = tuple(
            capability
            for capability in normalized.capabilities
            if "." in capability and (capability not in available or capability not in satisfied)
        )
        return GenerationPlan(
            request=normalized,
            components=tuple(components),
            edges=tuple(edges),
            children=tuple(children),
            unmet_capabilities=unmet,
        )


__all__ = [
    "GenerationDelta",
    "GenerationEdge",
    "GenerationEnricher",
    "GenerationError",
    "GenerationPipeline",
    "GenerationPlan",
    "GenerationRequest",
    "CoreGenerationEnricher",
]
