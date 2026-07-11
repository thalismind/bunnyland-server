"""Plugin-neutral contracts for cooperative entity generation."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

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
    request_id: str = ""
    parent_request_id: str | None = None
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationEdge:
    edge: Edge
    target_id: Any


@dataclass(frozen=True)
class GenerationTarget:
    """Symbolic reference to another entity in the same generation batch."""

    source_key: str


@dataclass(frozen=True)
class GenerationChild:
    """A child entity request and its explicit relationship from the parent."""

    request: GenerationRequest
    parent_edge: Edge
    additional_parent_edges: tuple[Edge, ...] = ()
    components: tuple[Component, ...] = ()
    singleton_key: str | None = None


@dataclass(frozen=True)
class GenerationDelta:
    """Declarative additions returned by one plugin enricher."""

    components: tuple[Component, ...] = ()
    edges: tuple[GenerationEdge, ...] = ()
    children: tuple[GenerationChild, ...] = ()
    satisfies: tuple[str, ...] = ()


@dataclass(frozen=True)
class GenerationPlan:
    request: GenerationRequest
    components: tuple[Component, ...] = ()
    edges: tuple[GenerationEdge, ...] = ()
    children: tuple[GenerationChild, ...] = ()
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


def _request_id(request: GenerationRequest, *, suffix: str = "") -> str:
    material = "|".join(
        (
            request.source_seed,
            request.source_key,
            request.entity_kind,
            request.description,
            suffix,
        )
    )
    return uuid5(NAMESPACE_URL, f"bunnyland:generation:{material}").hex


class GenerationPipeline:
    """Normalize intent and merge every applicable enabled-plugin enrichment."""

    def __init__(self, registry: Any | None) -> None:
        self.registry = registry

    def normalize(self, request: GenerationRequest) -> GenerationRequest:
        normalized = replace(
            request,
            capabilities=_dedupe(request.capabilities),
            request_id=request.request_id or _request_id(request),
        )
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
        children: list[GenerationChild] = []
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
                for child in delta.children:
                    if not isinstance(child, GenerationChild):
                        raise GenerationError(
                            f"generation child from {plugin_id!r} must be GenerationChild"
                        )
                    parent_edge_types: set[type] = set()
                    for parent_edge in (
                        child.parent_edge,
                        *child.additional_parent_edges,
                    ):
                        registered_edge = self.registry.edges.get(type(parent_edge).__name__)
                        if registered_edge is None:
                            raise GenerationError(
                                f"generation child uses unregistered parent edge "
                                f"{type(parent_edge).__name__!r}"
                            )
                        if registered_edge[0] not in {"bunnyland.core", plugin_id}:
                            raise GenerationError(
                                f"plugin {plugin_id!r} cannot use parent edge "
                                f"{type(parent_edge).__name__!r}; it is owned by "
                                f"{registered_edge[0]!r}"
                            )
                        if type(parent_edge) in parent_edge_types:
                            raise GenerationError(
                                f"generation child contains duplicate parent edge "
                                f"{type(parent_edge).__name__!r}"
                            )
                        parent_edge_types.add(type(parent_edge))
                    component_types: set[type] = set()
                    for component in child.components:
                        registered_component = self.registry.components.get(
                            type(component).__name__
                        )
                        if registered_component is None:
                            raise GenerationError(
                                f"generation child provides unregistered component "
                                f"{type(component).__name__!r}"
                            )
                        if registered_component[0] not in {"bunnyland.core", plugin_id}:
                            raise GenerationError(
                                f"plugin {plugin_id!r} cannot provide child component "
                                f"{type(component).__name__!r}; it is owned by "
                                f"{registered_component[0]!r}"
                            )
                        if type(component) in component_types:
                            raise GenerationError(
                                f"generation child contains duplicate component "
                                f"{type(component).__name__!r}"
                            )
                        component_types.add(type(component))
                    request = child.request
                    if not request.request_id:
                        request = replace(
                            request,
                            request_id=_request_id(
                                request,
                                suffix=f"{normalized.request_id}:{plugin_id}:{len(children)}",
                            ),
                        )
                    if request.parent_request_id is None:
                        request = replace(request, parent_request_id=normalized.request_id)
                    elif request.parent_request_id != normalized.request_id:
                        raise GenerationError(
                            f"generation child {request.request_id!r} names a different parent"
                        )
                    children.append(replace(child, request=request))
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
    "GenerationChild",
    "GenerationEdge",
    "GenerationEnricher",
    "GenerationError",
    "GenerationPipeline",
    "GenerationPlan",
    "GenerationRequest",
    "GenerationTarget",
    "CoreGenerationEnricher",
]
