"""Cooperative plugin registry, reaction, and generation architecture tests."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module

import pytest
from relics import Component, Edge

from bunnyland.core import (
    GenerationDelta,
    GenerationEdge,
    GenerationError,
    GenerationPipeline,
    GenerationRequest,
    WorldActor,
)
from bunnyland.core.events import DomainEvent, EventBus, ReactionCascadeLimitedEvent, event_base
from bunnyland.plugins import (
    CommandContribution,
    ContentContribution,
    DependencyContribution,
    EcsContribution,
    Plugin,
    PluginError,
    PluginPlacement,
    PluginRegistry,
    RuntimeContribution,
    apply_plugins,
    resolve_order,
)
from bunnyland.plugins.builtin import bunnyland_plugins
from bunnyland.plugins.registry import placement_order
from bunnyland.worldgen import collect_generators


class FirstSharedEvent(DomainEvent):
    pass


class SecondSharedEvent(DomainEvent):
    pass


SecondSharedEvent.__name__ = FirstSharedEvent.__name__


@dataclass(frozen=True)
class MarkerComponent(Component):
    value: str = "marker"


@dataclass(frozen=True)
class OtherComponent(Component):
    value: str = "other"


@dataclass(frozen=True)
class MarkerEdge(Edge):
    kind: str = "marker"


@dataclass(frozen=True)
class NamedContribution:
    name: str


@dataclass(frozen=True)
class Incident:
    id: str


class SourceEvent(DomainEvent):
    pass


class DerivedEvent(DomainEvent):
    pass


class CascadeEvent(DomainEvent):
    generation: int = 0


def _event(event_type, event_id: str = "root"):
    return event_type(**event_base(0, event_id=event_id))


def test_registry_namespaces_same_named_event_classes_and_uses_exact_identity():
    registry = PluginRegistry(
        [
            Plugin(
                id="pack.one",
                name="One",
                commands=CommandContribution(typed_events=(FirstSharedEvent,)),
            ),
            Plugin(
                id="pack.two",
                name="Two",
                commands=CommandContribution(typed_events=(SecondSharedEvent,)),
            ),
        ]
    )

    assert registry.resolve_event("pack.one", "FirstSharedEvent") is FirstSharedEvent
    assert registry.resolve_event("pack.two", "FirstSharedEvent") is SecondSharedEvent
    assert registry.event_key(FirstSharedEvent) == "pack.one:FirstSharedEvent"
    assert registry.require_exported_event("pack.one", FirstSharedEvent) is FirstSharedEvent


def test_dragonsim_is_the_single_owner_of_shared_quest_lifecycle_events():
    from bunnyland.mechanics.daggersim import QuestCompletedEvent as DaggerQuestCompletedEvent
    from bunnyland.simpacks.dragonsim.events import QuestCompletedEvent

    registry = PluginRegistry(bunnyland_plugins())

    assert DaggerQuestCompletedEvent is QuestCompletedEvent
    assert registry.event_key(QuestCompletedEvent) == "bunnyland.dragonsim:QuestCompletedEvent"


def test_registry_rejects_duplicate_event_ownership_and_incompatible_expectations():
    with pytest.raises(PluginError, match="already owned"):
        PluginRegistry(
            [
                Plugin(
                    id="pack.one",
                    name="One",
                    commands=CommandContribution(typed_events=(FirstSharedEvent,)),
                ),
                Plugin(
                    id="pack.two",
                    name="Two",
                    commands=CommandContribution(typed_events=(FirstSharedEvent,)),
                ),
            ]
        )

    registry = PluginRegistry(
        [
            Plugin(
                id="pack.one",
                name="One",
                commands=CommandContribution(typed_events=(FirstSharedEvent,)),
            )
        ]
    )
    with pytest.raises(PluginError, match="incompatible"):
        registry.require_exported_event("pack.one", SecondSharedEvent, "FirstSharedEvent")
    with pytest.raises(PluginError, match="does not export"):
        registry.resolve_event("pack.one", "MissingEvent")
    with pytest.raises(PluginError, match="not enabled"):
        registry.require_exported_event("pack.missing", FirstSharedEvent)


def test_registry_enforces_global_and_plugin_scoped_collision_rules():
    same_name_component = type("MarkerComponent", (Component,), {})
    with pytest.raises(PluginError, match="component type"):
        PluginRegistry(
            [
                Plugin(
                    id="pack.one",
                    name="One",
                    ecs=EcsContribution(components=(MarkerComponent,)),
                ),
                Plugin(
                    id="pack.two",
                    name="Two",
                    ecs=EcsContribution(components=(same_name_component,)),
                ),
            ]
        )

    with pytest.raises(PluginError, match="duplicate incident"):
        PluginRegistry(
            [
                Plugin(
                    id="pack.one",
                    name="One",
                    content=ContentContribution(
                        incident_definitions=(Incident("storm"), Incident("storm"))
                    ),
                )
            ]
        )

    with pytest.raises(PluginError, match="duplicate plugin id"):
        PluginRegistry([Plugin(id="same", name="One"), Plugin(id="same", name="Two")])

    with pytest.raises(PluginError, match="duplicate event export"):
        PluginRegistry(
            [
                Plugin(
                    id="pack.events",
                    name="Events",
                    commands=CommandContribution(
                        typed_events=(FirstSharedEvent, SecondSharedEvent)
                    ),
                )
            ]
        )


def test_registry_validates_capability_namespaces_aliases_and_indexes():
    plugin = Plugin(
        id="pack.fire",
        name="Fire",
        placement=PluginPlacement.FOUNDATION,
        ecs=EcsContribution(components=(MarkerComponent,), edges=(MarkerEdge,)),
        content=ContentContribution(
            generation_capabilities=("pack.fire.flammable",),
            generation_aliases={"flammable": "pack.fire.flammable"},
            world_generators=(NamedContribution("demo"),),
            incident_definitions=(Incident("spark"),),
        ),
        runtime=RuntimeContribution(
            service_factories=(NamedContribution("clock"),),
            projection_factories=(NamedContribution("view"),),
            integration_factories=(NamedContribution("weather"),),
        ),
    )
    registry = PluginRegistry([plugin])

    assert registry.enabled(plugin.id)
    assert registry.plugins[plugin.id] is plugin
    assert registry.plugin(plugin.id) is plugin
    assert registry.placement(plugin.id) is PluginPlacement.FOUNDATION
    assert registry.components["MarkerComponent"] == (plugin.id, MarkerComponent)
    assert registry.edges["MarkerEdge"] == (plugin.id, MarkerEdge)
    assert registry.generators["demo"][0] == plugin.id
    assert registry.capabilities["pack.fire.flammable"][0] == plugin.id
    assert registry.aliases["flammable"] == "pack.fire.flammable"
    assert registry.incidents[(plugin.id, "spark")].id == "spark"
    assert registry.services[(plugin.id, "clock")].name == "clock"
    assert registry.projections[(plugin.id, "view")].name == "view"
    assert registry.integrations[(plugin.id, "weather")].name == "weather"
    assert registry.events
    assert registry.actions == {}
    assert registry.worldgen_hooks == ()
    assert registry.enabled("bunnyland.core")
    assert registry.placement("bunnyland.core") is PluginPlacement.CORE
    assert placement_order("inner") < placement_order("outer")
    assert registry.event_key(type("Unknown", (), {})) is None
    from bunnyland.core.events import ActorMovedEvent

    assert registry.require_exported_event("bunnyland.core", ActorMovedEvent) is ActorMovedEvent

    with pytest.raises(PluginError, match="must be namespaced"):
        PluginRegistry(
            [
                Plugin(
                    id="pack.bad",
                    name="Bad",
                    content=ContentContribution(generation_capabilities=("bare",)),
                )
            ]
        )


def test_canonical_builtin_package_entrypoints_are_independently_importable():
    expected = {
        "bunnyland.simpacks.lifesim": "bunnyland.lifesim",
        "bunnyland.simpacks.colonysim": "bunnyland.colonysim",
        "bunnyland.simpacks.gardensim": "bunnyland.gardensim",
        "bunnyland.simpacks.barbariansim": "bunnyland.barbariansim",
        "bunnyland.simpacks.dinosim": "bunnyland.dinosim",
        "bunnyland.simpacks.dragonsim": "bunnyland.dragonsim",
        "bunnyland.simpacks.daggersim": "bunnyland.daggersim",
        "bunnyland.simpacks.neonsim": "bunnyland.neonsim",
        "bunnyland.simpacks.nukesim": "bunnyland.nukesim",
        "bunnyland.simpacks.toonsim": "bunnyland.toonsim",
        "bunnyland.simpacks.voidsim": "bunnyland.voidsim",
        "bunnyland.foundation.storyteller": "bunnyland.storyteller",
    }
    for module_name, plugin_id in expected.items():
        module = import_module(module_name)
        assert module.plugin().id == plugin_id
        assert [plugin.id for plugin in module.bunnyland_plugins()] == [plugin_id]


def test_registry_backed_generator_collection_and_runtime_factory_flattening():
    from bunnyland.plugins import RuntimeContribution

    registry = PluginRegistry(bunnyland_plugins())
    assert collect_generators(registry) == {
        name: generator for name, (_owner, generator) in registry.generators.items()
    }
    factories = tuple(object() for _index in range(5))
    contribution = RuntimeContribution(
        controller_factories=(factories[0],),
        generator_factories=(factories[1],),
        service_factories=(factories[2],),
        projection_factories=(factories[3],),
        integration_factories=(factories[4],),
    )
    assert contribution.all_factories() == factories
    with pytest.raises(PluginError, match="unowned capability"):
        PluginRegistry(
            [
                Plugin(
                    id="pack.bad",
                    name="Bad",
                    content=ContentContribution(
                        generation_aliases={"old": "pack.bad.missing"}
                    ),
                )
            ]
        )

    with pytest.raises(PluginError, match="maps to both"):
        PluginRegistry(
            [
                Plugin(
                    id="pack.one",
                    name="One",
                    content=ContentContribution(
                        generation_capabilities=("pack.one.value",),
                        generation_aliases={"legacy": "pack.one.value"},
                    ),
                ),
                Plugin(
                    id="pack.two",
                    name="Two",
                    content=ContentContribution(
                        generation_capabilities=("pack.two.value",),
                        generation_aliases={"legacy": "pack.two.value"},
                    ),
                ),
            ]
        )

    anonymous = object()
    anonymous_registry = PluginRegistry(
        [
            Plugin(
                id="pack.anonymous",
                name="Anonymous",
                runtime=RuntimeContribution(integration_factories=(anonymous,)),
            )
        ]
    )
    assert anonymous_registry.integrations[("pack.anonymous", "object")] is anonymous


def test_optional_awareness_may_be_cyclic_and_installs_after_all_contracts():
    calls: list[str] = []

    def install_service(actor, context):
        assert context.plugins.enabled("pack.two")
        calls.append("service")

    def install_integration(actor, context):
        assert context.plugins.enabled("pack.two")
        assert calls == ["service"]
        calls.append("integration")

    one = Plugin(
        id="pack.one",
        name="One",
        dependencies=DependencyContribution(integrates_with=("pack.two",)),
        runtime=RuntimeContribution(
            service_factories=(install_service,), integration_factories=(install_integration,)
        ),
    )
    two = Plugin(
        id="pack.two",
        name="Two",
        dependencies=DependencyContribution(integrates_with=("pack.one",)),
    )
    actor = WorldActor()

    assert resolve_order([one, two]) == [one, two]
    assert apply_plugins([one, two], actor) == [one, two]
    assert actor.plugins.enabled("pack.one")
    assert calls == ["service", "integration"]


def test_storyteller_installation_uses_incidents_from_the_complete_registry():
    from bunnyland.mechanics.storyteller import IncidentDefinition, StorytellerConsequence
    from bunnyland.plugins.builtin import CORE_VERBS, STORYTELLER

    custom = Plugin(
        id="pack.weather",
        name="Weather",
        content=ContentContribution(
            incident_definitions=(IncidentDefinition(id="squall", cost=1.0, priority=100),)
        ),
    )
    selected = [
        plugin
        for plugin in bunnyland_plugins()
        if plugin.id in {CORE_VERBS, STORYTELLER}
    ]
    actor = WorldActor()
    apply_plugins([*selected, custom], actor)

    consequence = next(
        item for item in actor._consequences if isinstance(item, StorytellerConsequence)
    )
    assert "squall" in {incident.id for incident in consequence.incidents}


async def test_reactions_are_deterministic_additive_and_once_per_source_event():
    bus = EventBus()
    seen: list[str] = []

    def handler(label):
        def react(event):
            seen.append(label)

        return react

    duplicate = handler("once")
    bus.subscribe(SourceEvent, handler("outer"), reaction_id="z", plugin_id="z", placement="outer")
    bus.subscribe(SourceEvent, handler("inner"), reaction_id="a", plugin_id="b", placement="inner")
    bus.subscribe(
        SourceEvent,
        handler("foundation"),
        reaction_id="b",
        plugin_id="a",
        placement="foundation",
    )
    bus.subscribe(SourceEvent, duplicate, reaction_id="same")
    bus.subscribe(DomainEvent, duplicate, reaction_id="same")
    bus.subscribe(
        SourceEvent,
        handler("other-plugin"),
        reaction_id="same",
        plugin_id="other.plugin",
    )

    await bus.publish(_event(SourceEvent))

    assert seen == ["once", "other-plugin", "foundation", "inner", "outer"]


async def test_reactions_are_breadth_first_and_propagate_causality():
    bus = EventBus()
    seen: list[tuple[str, DomainEvent]] = []

    async def first(event):
        seen.append(("source-first", event))
        await bus.publish(_event(DerivedEvent, "derived"))

    def second(event):
        seen.append(("source-second", event))

    def derived(event):
        seen.append(("derived", event))

    bus.subscribe(SourceEvent, first, reaction_id="first")
    bus.subscribe(SourceEvent, second, reaction_id="second")
    bus.subscribe(DerivedEvent, derived, reaction_id="derived")
    await bus.publish(_event(SourceEvent))

    assert [label for label, _event_ in seen] == ["source-first", "source-second", "derived"]
    derived_event = seen[-1][1]
    assert derived_event.causation_id == "root"
    assert derived_event.correlation_id == "root"


async def test_reaction_limits_defer_deliveries_and_stop_causal_loops():
    bus = EventBus(max_deliveries=1, max_causal_hops=2)
    seen: list[str] = []
    bus.subscribe(SourceEvent, lambda event: seen.append("one"), reaction_id="one")
    bus.subscribe(SourceEvent, lambda event: seen.append("two"), reaction_id="two")

    bus.begin_transaction()
    await bus.publish(_event(SourceEvent))
    assert seen == ["one"]
    await bus.end_transaction()
    bus.begin_transaction()
    await bus.drain()
    await bus.end_transaction()
    assert seen == ["one", "two"]

    cascade = EventBus(max_causal_hops=2)

    async def continue_cascade(event: CascadeEvent):
        await cascade.publish(
            CascadeEvent(**event_base(0, generation=event.generation + 1))
        )

    cascade.subscribe(CascadeEvent, continue_cascade, reaction_id="loop")
    diagnostics: list[ReactionCascadeLimitedEvent] = []
    cascade.subscribe(ReactionCascadeLimitedEvent, diagnostics.append, reaction_id="diagnostic")
    await cascade.publish(_event(CascadeEvent))

    assert diagnostics[0].hops == 3
    assert cascade.diagnostics == diagnostics


async def test_external_sinks_run_after_the_actor_transaction():
    bus = EventBus()
    seen: list[str] = []
    bus.subscribe(SourceEvent, lambda event: seen.append("domain"), reaction_id="domain")
    bus.subscribe(
        SourceEvent,
        lambda event: seen.append("external"),
        reaction_id="external",
        external=True,
    )

    bus.begin_transaction()
    await bus.publish(_event(SourceEvent))
    assert seen == ["domain"]
    await bus.end_transaction()
    assert seen == ["domain", "external"]


async def test_event_bus_registration_unsubscribe_and_reentrant_guard_paths():
    bus = EventBus()
    seen: list[str] = []

    def handler(event):
        seen.append("handler")

    bus.unsubscribe(SourceEvent, handler)
    bus.subscribe(SourceEvent, handler)
    bus.unsubscribe(SourceEvent, lambda event: None)
    registration = bus.begin_registration("pack.test", "inner")
    bus.subscribe(SourceEvent, lambda event: seen.append("scoped"))
    bus.end_registration(registration)
    bus.unsubscribe(SourceEvent, handler)
    await bus.end_transaction()

    async def reentrant(event):
        await bus.drain()

    async def external(event):
        seen.append("external")
        await bus.flush_external()

    bus.subscribe(SourceEvent, reentrant, reaction_id="reentrant")
    bus.subscribe(SourceEvent, external, reaction_id="external", external=True)
    bus.subscribe(DomainEvent, external, reaction_id="external", external=True)
    bus.begin_transaction()
    bus.begin_transaction()
    await bus.publish(_event(SourceEvent))
    await bus.end_transaction()
    assert seen == ["scoped"]
    await bus.end_transaction()
    assert seen == ["scoped", "external"]

    # No subscribers is a valid delivery, and pre-correlated derived events are preserved.
    await bus.publish(_event(DerivedEvent, "unobserved"))
    source = _event(SourceEvent, "correlated")

    async def preserve_correlation(event):
        await bus.publish(
            DerivedEvent(
                **event_base(0, causation_id="existing-cause", correlation_id="existing-root")
            )
        )

    captured: list[DerivedEvent] = []
    bus.subscribe(SourceEvent, preserve_correlation, reaction_id="preserve")
    bus.subscribe(DerivedEvent, captured.append, reaction_id="capture")
    await bus.publish(source)
    assert captured[-1].causation_id == "existing-cause"
    assert captured[-1].correlation_id == "existing-root"


class FireEnricher:
    capabilities = ("pack.fire.flammable",)

    def enrich(self, request):
        return GenerationDelta(
            components=(MarkerComponent(request.entity_kind),),
            satisfies=self.capabilities,
        )


def add_fire_capability(request):
    return ("pack.fire.flammable",) if "hot" in request.description else ()


async def test_generation_pipeline_normalizes_aliases_and_merges_applicable_enrichers():
    plugin = Plugin(
        id="pack.fire",
        name="Fire",
        ecs=EcsContribution(components=(MarkerComponent,)),
        content=ContentContribution(
            generation_capabilities=("pack.fire.flammable",),
            generation_aliases={"fire": "pack.fire.flammable"},
            intent_normalizers=(add_fire_capability,),
            generation_enrichers=(FireEnricher,),
        ),
    )
    pipeline = GenerationPipeline(PluginRegistry([plugin]))

    plan = await pipeline.compile(
        GenerationRequest(entity_kind="room", description="hot room", capabilities=("fire",))
    )

    assert plan.request.capabilities == ("pack.fire.flammable",)
    assert plan.components == (MarkerComponent("room"),)
    assert plan.unmet_capabilities == ()


async def test_generation_pipeline_records_degradation_and_rejects_invalid_deltas():
    empty = await GenerationPipeline(None).compile(
        GenerationRequest(entity_kind="item", capabilities=("pack.missing.magic",)),
        base_components=(OtherComponent(),),
    )
    assert empty.components == (OtherComponent(),)
    assert empty.unmet_capabilities == ("pack.missing.magic",)

    with pytest.raises(GenerationError, match="duplicate singleton"):
        await GenerationPipeline(None).compile(
            GenerationRequest(entity_kind="item"),
            base_components=(OtherComponent(), OtherComponent()),
        )

    class BadReturn:
        capabilities = ("pack.bad.value",)

        def enrich(self, request):
            return "bad"

    bad_plugin = Plugin(
        id="pack.bad",
        name="Bad",
        content=ContentContribution(
            generation_capabilities=("pack.bad.value",),
            generation_enrichers=(BadReturn,),
        ),
    )
    with pytest.raises(GenerationError, match="expected GenerationDelta"):
        await GenerationPipeline(PluginRegistry([bad_plugin])).compile(
            GenerationRequest(entity_kind="item", capabilities=("pack.bad.value",))
        )


async def test_generation_pipeline_normalizer_and_applicability_noop_paths():
    def no_change(request):
        return None

    def replace_request(request):
        return GenerationRequest(
            entity_kind=request.entity_kind,
            description="normalized",
            capabilities=request.capabilities,
        )

    class Skipped:
        capabilities = ("pack.noop.other",)

        def enrich(self, request):
            raise AssertionError("capability-filtered enricher ran")

    class NotApplicable:
        capabilities = ("pack.noop.value",)

        def applies(self, request):
            return False

        def enrich(self, request):
            raise AssertionError("inapplicable enricher ran")

    class Empty:
        capabilities = ("pack.noop.value",)

        def enrich(self, request):
            return None

    plugin = Plugin(
        id="pack.noop",
        name="Noop",
        content=ContentContribution(
            generation_capabilities=("pack.noop.value", "pack.noop.other"),
            intent_normalizers=(no_change, replace_request),
            generation_enrichers=(Skipped, NotApplicable, Empty),
        ),
    )
    plan = await GenerationPipeline(PluginRegistry([plugin])).compile(
        GenerationRequest(entity_kind="item", capabilities=("pack.noop.value",))
    )
    assert plan.request.description == "normalized"
    assert plan.unmet_capabilities == ("pack.noop.value",)


async def test_generation_pipeline_rejects_unregistered_and_foreign_edges():
    class UnregisteredComponentEnricher:
        capabilities = ("pack.bad.value",)

        def enrich(self, request):
            return GenerationDelta(components=(OtherComponent(),))

    plugin = Plugin(
        id="pack.bad",
        name="Bad",
        content=ContentContribution(
            generation_capabilities=("pack.bad.value",),
            generation_enrichers=(UnregisteredComponentEnricher,),
        ),
    )
    with pytest.raises(GenerationError, match="unregistered component"):
        await GenerationPipeline(PluginRegistry([plugin])).compile(
            GenerationRequest(entity_kind="item", capabilities=("pack.bad.value",))
        )

    class UnregisteredEdgeEnricher:
        capabilities = ("pack.bad.value",)

        def enrich(self, request):
            return GenerationDelta(edges=(GenerationEdge(MarkerEdge(), "entity_1"),))

    plugin = plugin.model_copy(
        update={
            "content": plugin.content.model_copy(
                update={"generation_enrichers": (UnregisteredEdgeEnricher,)}
            )
        }
    )
    with pytest.raises(GenerationError, match="unregistered edge"):
        await GenerationPipeline(PluginRegistry([plugin])).compile(
            GenerationRequest(entity_kind="item", capabilities=("pack.bad.value",))
        )

    owner = Plugin(
        id="pack.owner", name="Owner", ecs=EcsContribution(edges=(MarkerEdge,))
    )
    with pytest.raises(GenerationError, match="cannot provide edge"):
        await GenerationPipeline(PluginRegistry([owner, plugin])).compile(
            GenerationRequest(entity_kind="item", capabilities=("pack.bad.value",))
        )


async def test_generation_pipeline_rejects_conflicts_failures_and_wrong_owners():
    class First:
        capabilities = ("pack.one.marker",)

        def enrich(self, request):
            return GenerationDelta(components=(MarkerComponent("one"),))

    class Second:
        capabilities = ("pack.one.marker",)

        def enrich(self, request):
            return GenerationDelta(components=(MarkerComponent("two"),))

    conflict_plugin = Plugin(
        id="pack.one",
        name="One",
        ecs=EcsContribution(components=(MarkerComponent,)),
        content=ContentContribution(
            generation_capabilities=("pack.one.marker",),
            generation_enrichers=(First, Second),
        ),
    )
    with pytest.raises(GenerationError, match="conflicting singleton"):
        await GenerationPipeline(PluginRegistry([conflict_plugin])).compile(
            GenerationRequest(entity_kind="item", capabilities=("pack.one.marker",))
        )

    class Failure:
        capabilities = ("pack.one.marker",)

        def enrich(self, request):
            raise ValueError("boom")

    failure_plugin = conflict_plugin.model_copy(
        update={
            "content": conflict_plugin.content.model_copy(
                update={"generation_enrichers": (Failure,)}
            )
        }
    )
    with pytest.raises(GenerationError, match="failed: boom"):
        await GenerationPipeline(PluginRegistry([failure_plugin])).compile(
            GenerationRequest(entity_kind="item", capabilities=("pack.one.marker",))
        )

    class WrongOwner:
        capabilities = ("pack.two.other",)

        def enrich(self, request):
            return GenerationDelta(components=(MarkerComponent(),))

    owner = Plugin(
        id="pack.one", name="One", ecs=EcsContribution(components=(MarkerComponent,))
    )
    consumer = Plugin(
        id="pack.two",
        name="Two",
        content=ContentContribution(
            generation_capabilities=("pack.two.other",),
            generation_enrichers=(WrongOwner,),
        ),
    )
    with pytest.raises(GenerationError, match="cannot provide component"):
        await GenerationPipeline(PluginRegistry([owner, consumer])).compile(
            GenerationRequest(entity_kind="item", capabilities=("pack.two.other",))
        )


async def test_generation_pipeline_accepts_repeatable_edges_and_child_requests():
    target_actor = WorldActor()
    target = next(target_actor.world.query().execute_entities())

    class EdgeEnricher:
        capabilities = ("pack.edge.link",)

        async def enrich(self, request):
            return GenerationDelta(
                edges=(GenerationEdge(MarkerEdge(), target.id),),
                children=(GenerationRequest(entity_kind="item"),),
                satisfies=self.capabilities,
            )

    plugin = Plugin(
        id="pack.edge",
        name="Edge",
        ecs=EcsContribution(edges=(MarkerEdge,)),
        content=ContentContribution(
            generation_capabilities=("pack.edge.link",),
            generation_enrichers=(EdgeEnricher,),
        ),
    )
    plan = await GenerationPipeline(PluginRegistry([plugin])).compile(
        GenerationRequest(entity_kind="room", capabilities=("pack.edge.link",))
    )

    assert plan.edges[0].target_id == target.id
    assert plan.children[0].parent_request_id == plan.request.request_id


async def test_generation_plan_edge_application_validates_string_and_entity_references():
    from bunnyland.core import spawn_entity
    from bunnyland.worldgen.instantiate import _apply_plan_edges, _validate_plan_edges

    actor = WorldActor()
    target = spawn_entity(actor.world, [])
    source = spawn_entity(actor.world, [])
    plan = type("Plan", (), {"edges": (GenerationEdge(MarkerEdge(), str(target.id)),)})()

    _validate_plan_edges(actor, plan)
    _apply_plan_edges(actor, source, plan)
    assert source.has_relationship(MarkerEdge, target.id)

    entity_plan = type(
        "Plan", (), {"edges": (GenerationEdge(MarkerEdge("second"), target.id),)}
    )()
    _validate_plan_edges(actor, entity_plan)
    _apply_plan_edges(actor, source, entity_plan)

    invalid = type("Plan", (), {"edges": (GenerationEdge(MarkerEdge(), "invalid"),)})()
    with pytest.raises(GenerationError, match="missing entity"):
        _validate_plan_edges(actor, invalid)


async def test_legacy_generation_adapter_awaits_callable_hooks_and_ignores_nonhandlers():
    from bunnyland.core.events import GeneratedEntityEvent
    from bunnyland.worldgen.instantiate import _finalize_legacy_hooks

    actor = WorldActor()
    seen: list[str] = []

    async def hook(event):
        seen.append(event.entity_id)

    actor._worldgen_hooks.extend((object(), hook))
    event = GeneratedEntityEvent(
        **event_base(
            0,
            seed="seed",
            entity_id="entity_1",
            entity_key="one",
            entity_kind="item",
        )
    )
    await _finalize_legacy_hooks(actor, event)
    assert seen == ["entity_1"]
    assert event.needs == ()


def test_legacy_type_discovery_rejects_loaded_schema_v1_name_collisions():
    from bunnyland.persistence import type_registries

    duplicate_component = type(
        "IdentityComponent", (Component,), {"__module__": "bunnyland.fake"}
    )
    with pytest.raises(PluginError, match="duplicate persisted component"):
        type_registries()
    duplicate_component.__name__ = "LegacyIdentityComponent"

    duplicate_edge = type("Contains", (Edge,), {"__module__": "bunnyland.fake"})
    with pytest.raises(PluginError, match="duplicate persisted edge"):
        type_registries()
    duplicate_edge.__name__ = "LegacyContains"
