"""Bounded conjunctive queries over the authoritative Relics world graph."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from relics import Component, Edge, EntityId, World

from .ecs import parse_entity_id

MAX_GRAPH_QUERY_TERMS = 8
MAX_GRAPH_QUERY_VARIABLES = 6
MAX_GRAPH_QUERY_RESULTS = 100
MAX_GRAPH_QUERY_EXPANSIONS = 10_000


class GraphQueryError(ValueError):
    """A graph query is invalid or exceeds its bounded execution contract."""


class ComponentTerm(BaseModel):
    """Require one variable to carry a registered component and exact field values."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["component"] = "component"
    variable: str = Field(min_length=1)
    component: str = Field(min_length=1)
    fields: dict[str, Any] = Field(default_factory=dict)


class EdgeTerm(BaseModel):
    """Require one registered directed edge between two entity variables."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["edge"] = "edge"
    source: str = Field(min_length=1)
    edge: str = Field(min_length=1)
    target: str = Field(min_length=1)


GraphQueryTerm = Annotated[ComponentTerm | EdgeTerm, Field(discriminator="kind")]


class GraphQuerySpec(BaseModel):
    """A small connected conjunctive graph query using plugin-exported type names."""

    model_config = ConfigDict(frozen=True)

    terms: tuple[GraphQueryTerm, ...] = Field(min_length=1, max_length=MAX_GRAPH_QUERY_TERMS)
    bindings: dict[str, str] = Field(default_factory=dict)
    select: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_shape(self) -> GraphQuerySpec:
        variables = set(self.bindings)
        adjacency: dict[str, set[str]] = {}
        for term in self.terms:
            if isinstance(term, ComponentTerm):
                variables.add(term.variable)
                adjacency.setdefault(term.variable, set())
            else:
                variables.update((term.source, term.target))
                adjacency.setdefault(term.source, set()).add(term.target)
                adjacency.setdefault(term.target, set()).add(term.source)
        for variable in self.bindings:
            adjacency.setdefault(variable, set())
        if len(variables) > MAX_GRAPH_QUERY_VARIABLES:
            raise ValueError(
                f"graph query has {len(variables)} variables; maximum is "
                f"{MAX_GRAPH_QUERY_VARIABLES}"
            )
        undefined = sorted(set(self.select) - variables)
        if undefined:
            raise ValueError(f"selected variable(s) are undefined: {', '.join(undefined)}")
        if len(set(self.select)) != len(self.select):
            raise ValueError("selected variables must be unique")
        reached: set[str] = set()
        stack = [min(variables)]
        while stack:
            variable = stack.pop()
            if variable in reached:
                continue
            reached.add(variable)
            stack.extend(sorted(adjacency[variable] - reached, reverse=True))
        if reached != variables:
            disconnected = ", ".join(sorted(variables - reached))
            raise ValueError(f"graph query is disconnected at variable(s): {disconnected}")
        return self


class GraphQueryExecutor:
    """Compile and evaluate ``GraphQuerySpec`` values against existing Relics indexes."""

    def __init__(self, registry: Any) -> None:
        self._components: Mapping[str, tuple[str, type[Component]]] = registry.components
        self._edges: Mapping[str, tuple[str, type[Edge]]] = registry.edges

    def execute(self, world: World, spec: GraphQuerySpec) -> list[dict[str, str]]:
        component_types: dict[int, type[Component]] = {}
        edge_types: dict[int, type[Edge]] = {}
        for index, term in enumerate(spec.terms):
            if isinstance(term, ComponentTerm):
                registered = self._components.get(term.component)
                if registered is None:
                    raise GraphQueryError(f"unknown component type {term.component!r}")
                component_types[index] = registered[1]
            else:
                registered = self._edges.get(term.edge)
                if registered is None:
                    raise GraphQueryError(f"unknown edge type {term.edge!r}")
                edge_types[index] = registered[1]

        initial: dict[str, EntityId] = {}
        for variable, raw_id in sorted(spec.bindings.items()):
            entity_id = parse_entity_id(raw_id)
            if entity_id is None or not world.has_entity(entity_id):
                raise GraphQueryError(
                    f"fixed binding {variable!r} refers to missing entity {raw_id!r}"
                )
            initial[variable] = entity_id

        expansions = 0
        rows: list[dict[str, str]] = []
        seen: set[tuple[str, ...]] = set()

        def search(bindings: dict[str, EntityId], remaining: tuple[int, ...]) -> None:
            nonlocal expansions
            if not remaining:
                key = tuple(str(bindings[variable]) for variable in spec.select)
                if key not in seen:
                    seen.add(key)
                    rows.append(dict(zip(spec.select, key, strict=True)))
                    if len(rows) > MAX_GRAPH_QUERY_RESULTS:
                        raise GraphQueryError(
                            f"graph query exceeded {MAX_GRAPH_QUERY_RESULTS} result budget"
                        )
                return

            index = min(
                remaining,
                key=lambda item: self._term_rank(spec.terms[item], bindings, item),
            )
            next_remaining = tuple(item for item in remaining if item != index)
            term = spec.terms[index]
            for additions in self._candidates(
                world,
                term,
                bindings,
                component_types.get(index),
                edge_types.get(index),
            ):
                expansions += 1
                if expansions > MAX_GRAPH_QUERY_EXPANSIONS:
                    raise GraphQueryError(
                        f"graph query exceeded {MAX_GRAPH_QUERY_EXPANSIONS} candidate expansions"
                    )
                merged = dict(bindings)
                merged.update(additions)
                search(merged, next_remaining)

        search(initial, tuple(range(len(spec.terms))))
        return sorted(rows, key=lambda row: tuple(row[name] for name in spec.select))

    @staticmethod
    def _term_rank(term: GraphQueryTerm, bindings: Mapping[str, EntityId], index: int):
        if isinstance(term, ComponentTerm):
            return (0 if term.variable in bindings else 2, index)
        bound = int(term.source in bindings) + int(term.target in bindings)
        return ({2: 0, 1: 1, 0: 3}[bound], index)

    def _candidates(
        self,
        world: World,
        term: GraphQueryTerm,
        bindings: Mapping[str, EntityId],
        component_type: type[Component] | None,
        edge_type: type[Edge] | None,
    ):
        if isinstance(term, ComponentTerm):
            assert component_type is not None
            if term.variable in bindings:
                entity = world.get_entity(bindings[term.variable])
                if self._component_matches(entity, component_type, term.fields):
                    yield {}
                return
            entities = world.query().with_all([component_type]).execute_entities()
            for entity in sorted(entities, key=lambda item: str(item.id)):
                if self._component_matches(entity, component_type, term.fields):
                    yield {term.variable: entity.id}
            return

        assert edge_type is not None
        source_id = bindings.get(term.source)
        target_id = bindings.get(term.target)
        if source_id is not None and target_id is not None:
            source = world.get_entity(source_id)
            if any(
                candidate == target_id
                for _edge, candidate in source.get_relationships(edge_type)
            ):
                yield {}
            return
        if source_id is not None:
            source = world.get_entity(source_id)
            for _edge, candidate in sorted(
                source.get_relationships(edge_type), key=lambda item: str(item[1])
            ):
                yield {term.target: candidate}
            return
        if target_id is not None:
            target = world.get_entity(target_id)
            for candidate, _edge in sorted(
                target.get_incoming_relationships(edge_type), key=lambda item: str(item[0])
            ):
                yield {term.source: candidate}
            return
        for source in sorted(world.query().execute_entities(), key=lambda item: str(item.id)):
            for _edge, candidate in sorted(
                source.get_relationships(edge_type), key=lambda item: str(item[1])
            ):
                if term.source == term.target and source.id != candidate:
                    continue
                yield {term.source: source.id, term.target: candidate}

    @staticmethod
    def _component_matches(entity, component_type: type[Component], fields: Mapping[str, Any]):
        if not entity.has_component(component_type):
            return False
        component = entity.get_component(component_type)
        return all(
            getattr(component, field, object()) == expected
            for field, expected in fields.items()
        )


__all__ = [
    "ComponentTerm",
    "EdgeTerm",
    "GraphQueryError",
    "GraphQueryExecutor",
    "GraphQuerySpec",
    "GraphQueryTerm",
    "MAX_GRAPH_QUERY_EXPANSIONS",
    "MAX_GRAPH_QUERY_RESULTS",
    "MAX_GRAPH_QUERY_TERMS",
    "MAX_GRAPH_QUERY_VARIABLES",
]
