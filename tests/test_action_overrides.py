"""Persistent per-entity command routing."""

from __future__ import annotations

import logging

import pytest
from conftest import build_scenario
from pydantic import TypeAdapter, ValidationError

from bunnyland import telemetry
from bunnyland.core import (
    ActionArgument,
    ActionDefinition,
    ActionOverrideComponent,
    ActionOverrideEntry,
    ActionPointsComponent,
    CommandCost,
    DescriptionComponent,
    EntityActionCallbackDefinition,
    FocusPointsComponent,
    HandlerContext,
    Lane,
    MutationPlan,
    SetComponent,
    build_submitted_command,
    spawn_entity,
)
from bunnyland.core.events import (
    CommandExecutedEvent,
    CommandQueuedEvent,
    CommandRejectedEvent,
    CommandSubmittedEvent,
    DomainEvent,
)
from bunnyland.core.handlers import planned
from bunnyland.persistence import WorldMeta, load_world, save_world
from bunnyland.plugins import (
    CommandContribution,
    Plugin,
    PluginError,
    PluginRegistry,
    apply_plugins,
)


class SourceEvent(DomainEvent):
    value: str


class DestinationEvent(DomainEvent):
    target_id: str
    preserved: str


class CallbackEvent(DomainEvent):
    target_id: str
    command_type: str


class SourceHandler:
    command_type = "source"

    def execute(self, ctx: HandlerContext, command):
        return planned(
            MutationPlan(),
            SourceEvent(**ctx.event_base(actor_id=command.character_id), value="source"),
        )


class DestinationHandler:
    command_type = "destination"

    def __init__(self):
        self.commands = []

    def execute(self, ctx: HandlerContext, command):
        self.commands.append(command)
        target_id = str(command.payload["target_id"])
        return planned(
            MutationPlan(
                (
                    SetComponent(
                        target_id,
                        DescriptionComponent(short="handled by destination"),
                    ),
                )
            ),
            DestinationEvent(
                **ctx.event_base(actor_id=command.character_id),
                target_id=target_id,
                preserved=str(command.payload["preserved"]),
            ),
        )


SOURCE_DEFINITION = ActionDefinition(
    command_type="source",
    lane=Lane.WORLD,
    cost=CommandCost(action=1),
    arguments={
        "item_id": ActionArgument(kind="entity", required=True),
        "other_id": ActionArgument(kind="entity"),
        "preserved": ActionArgument(required=True),
    },
)
DESTINATION_DEFINITION = ActionDefinition(
    command_type="destination",
    lane=Lane.FOCUS,
    cost=CommandCost(focus=2),
    arguments={
        "target_id": ActionArgument(kind="entity", required=True),
        "preserved": ActionArgument(required=True),
    },
)


def _setup():
    scenario = build_scenario()
    source = SourceHandler()
    destination = DestinationHandler()
    scenario.actor.register_action_definition(SOURCE_DEFINITION)
    scenario.actor.register_action_definition(DESTINATION_DEFINITION)
    scenario.actor.register_handler(source)
    scenario.actor.register_handler(destination)
    return scenario, source, destination


def _command(scenario, owner_id: str, **payload):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="source",
        payload={"item_id": owner_id, "preserved": "keep", **payload},
        # Deliberately untrusted values: an override must replace both from metadata.
        cost=CommandCost(action=5),
        lane=Lane.WORLD,
    )


def _collect(actor, event_type):
    events = []
    actor.bus.subscribe(event_type, events.append)
    return events


def _callback(ctx: HandlerContext, command, owning_entity_id):
    return planned(
        MutationPlan(
            (
                SetComponent(
                    owning_entity_id,
                    DescriptionComponent(short="handled by callback"),
                ),
            )
        ),
        CallbackEvent(
            **ctx.event_base(actor_id=command.character_id),
            target_id=str(owning_entity_id),
            command_type=command.command_type,
        ),
    )


@pytest.fixture
def override_otel_capture(monkeypatch):
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    monkeypatch.setenv("BUNNYLAND_OTEL_ENABLED", "1")
    resource = Resource.create({"service.name": "action-override-test"})
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[InMemoryMetricReader()],
    )
    telemetry.reset_for_tests()
    assert telemetry.init_telemetry(providers=(tracer_provider, meter_provider)) is True
    yield exporter
    telemetry.reset_for_tests()


def test_component_validates_routes_and_duplicate_sources():
    component = ActionOverrideComponent(
        (
            ActionOverrideEntry("use", destination_action="eat", destination_argument="food_id"),
            ActionOverrideEntry("inspect", callback_id="example.items.inspect"),
        )
    )
    assert TypeAdapter(ActionOverrideComponent).validate_python(
        {
            "overrides": [
                {
                    "source_action": "use",
                    "destination_action": "eat",
                    "destination_argument": "food_id",
                },
                {"source_action": "inspect", "callback_id": "example.items.inspect"},
            ]
        }
    ) == component

    invalid = (
        (
            ActionOverrideEntry("use", callback_id="one"),
            ActionOverrideEntry("use", callback_id="two"),
        ),
    )
    with pytest.raises(ValidationError, match="source actions must be unique"):
        ActionOverrideComponent(invalid[0])
    with pytest.raises(ValidationError, match="source action must not be empty"):
        ActionOverrideEntry(" ", callback_id="example.items.use")
    with pytest.raises(ValidationError, match="require a destination action and argument"):
        ActionOverrideEntry("use", destination_action="eat")
    with pytest.raises(ValidationError, match="either an alias or a callback"):
        ActionOverrideEntry(
            "use",
            destination_action="eat",
            destination_argument="food_id",
            callback_id="example.items.use",
        )
    with pytest.raises(ValidationError, match="either an alias or a callback"):
        ActionOverrideEntry("use")


@pytest.mark.parametrize("suffix", ["json", "yaml"])
def test_override_component_persists_in_json_and_yaml(tmp_path, suffix):
    scenario, _source, _destination = _setup()
    owner = spawn_entity(
        scenario.actor.world,
        [
            ActionOverrideComponent(
                (
                    ActionOverrideEntry(
                        "source",
                        destination_action="destination",
                        destination_argument="target_id",
                    ),
                    ActionOverrideEntry("inspect", callback_id="example.items.inspect"),
                )
            )
        ],
    )
    path = tmp_path / f"world.{suffix}"
    save_world(scenario.actor, path, meta=WorldMeta())

    loaded, _meta = load_world(path, registry=PluginRegistry())
    assert loaded.world.get_entity(owner.id).get_component(ActionOverrideComponent) == (
        owner.get_component(ActionOverrideComponent)
    )


async def test_no_matching_override_preserves_ordinary_command_behavior():
    scenario, source, destination = _setup()
    owner = spawn_entity(
        scenario.actor.world,
        [
            ActionOverrideComponent(
                (ActionOverrideEntry("inspect", callback_id="example.items.inspect"),)
            )
        ],
    )
    source_events = _collect(scenario.actor, SourceEvent)

    outcome = await scenario.actor.submit(_command(scenario, str(owner.id), cost="ignored"))
    await scenario.actor.tick(0.0)

    assert outcome.accepted is True
    assert len(source_events) == 1
    assert destination.commands == []
    assert source is not None


async def test_alias_rewrites_full_lifecycle_and_runs_only_destination(caplog):
    scenario, _source, destination = _setup()
    owner = spawn_entity(
        scenario.actor.world,
        [
            ActionOverrideComponent(
                (
                    ActionOverrideEntry(
                        "source",
                        destination_action="destination",
                        destination_argument="target_id",
                    ),
                )
            )
        ],
    )
    submitted = _collect(scenario.actor, CommandSubmittedEvent)
    queued = _collect(scenario.actor, CommandQueuedEvent)
    executed = _collect(scenario.actor, CommandExecutedEvent)
    source_events = _collect(scenario.actor, SourceEvent)
    destination_events = _collect(scenario.actor, DestinationEvent)
    policy_types = []
    scenario.actor.register_gate(
        lambda _world, command: (policy_types.append(command.command_type) or True, None)
    )
    before_action = scenario.actor.world.get_entity(scenario.character).get_component(
        ActionPointsComponent
    ).current
    before_focus = scenario.actor.world.get_entity(scenario.character).get_component(
        FocusPointsComponent
    ).current

    caplog.set_level(logging.INFO, logger="bunnyland.core.world_actor")
    command = _command(scenario, str(owner.id), unrelated="still here")
    outcome = await scenario.actor.submit(command)
    pending = scenario.actor.pending_submissions()[0]
    await scenario.actor.tick(0.0)
    duplicate = await scenario.actor.submit(command)

    assert outcome.accepted is True
    assert pending.command_id == command.command_id
    assert duplicate.accepted is True
    assert duplicate.receipt == scenario.actor.receipt_for(command.command_id)
    assert pending.command_type == "destination"
    assert pending.lane is Lane.FOCUS
    assert pending.cost == CommandCost(focus=2)
    assert pending.payload == {
        "item_id": str(owner.id),
        "preserved": "keep",
        "unrelated": "still here",
        "target_id": str(owner.id),
    }
    assert policy_types == ["destination", "destination"]
    assert [event.command_type for event in submitted + queued + executed] == [
        "destination",
        "destination",
        "destination",
    ]
    assert source_events == []
    assert len(destination_events) == 1
    assert executed[0].result_events[0]["event_type"] == "DestinationEvent"
    assert destination.commands == [pending]
    assert scenario.actor.receipt_for(command.command_id).command_type == "destination"
    character = scenario.actor.world.get_entity(scenario.character)
    assert character.get_component(ActionPointsComponent).current == before_action
    assert character.get_component(FocusPointsComponent).current == before_focus - 2
    record = next(
        record for record in caplog.records if record.message == "entity action override resolved"
    )
    assert record.__dict__["command.requested_action"] == "source"
    assert record.__dict__["command.resolved_action"] == "destination"
    assert record.__dict__["command.override.kind"] == "alias"
    assert record.__dict__["command.override.entity_id"] == str(owner.id)


async def test_direct_callback_uses_source_lifecycle_and_mutation_plan():
    scenario, _source, destination = _setup()
    definition = EntityActionCallbackDefinition("example.items.activate", _callback)
    scenario.actor.register_action_callback(definition)
    owner = spawn_entity(
        scenario.actor.world,
        [ActionOverrideComponent((ActionOverrideEntry("source", callback_id=definition.id),))],
    )
    callback_events = _collect(scenario.actor, CallbackEvent)
    source_events = _collect(scenario.actor, SourceEvent)
    executed = _collect(scenario.actor, CommandExecutedEvent)

    outcome = await scenario.actor.submit(_command(scenario, str(owner.id)))
    pending = scenario.actor.pending_submissions()[0]
    await scenario.actor.tick(0.0)

    assert outcome.accepted is True
    assert pending.command_type == "source"
    assert pending.cost == SOURCE_DEFINITION.cost
    assert pending.lane == SOURCE_DEFINITION.lane
    assert pending.action_override.kind == "callback"
    assert source_events == []
    assert destination.commands == []
    assert callback_events[0].command_type == "source"
    assert executed[0].command_type == "source"
    assert owner.get_component(DescriptionComponent).short == "handled by callback"


async def test_alias_then_callback_uses_destination_identity():
    scenario, _source, destination = _setup()
    definition = EntityActionCallbackDefinition("example.items.destination", _callback)
    scenario.actor.register_action_callback(definition)
    owner = spawn_entity(
        scenario.actor.world,
        [
            ActionOverrideComponent(
                (
                    ActionOverrideEntry(
                        "source",
                        destination_action="destination",
                        destination_argument="target_id",
                    ),
                    ActionOverrideEntry("destination", callback_id=definition.id),
                )
            )
        ],
    )
    callback_events = _collect(scenario.actor, CallbackEvent)
    executed = _collect(scenario.actor, CommandExecutedEvent)

    await scenario.actor.submit(_command(scenario, str(owner.id)))
    pending = scenario.actor.pending_submissions()[0]
    await scenario.actor.tick(0.0)

    assert pending.command_type == "destination"
    assert pending.action_override.kind == "alias_callback"
    assert destination.commands == []
    assert callback_events[0].command_type == "destination"
    assert executed[0].command_type == "destination"


@pytest.mark.otel
async def test_override_annotates_existing_command_spans(override_otel_capture):
    scenario, _source, _destination = _setup()
    definition = EntityActionCallbackDefinition("example.items.destination", _callback)
    scenario.actor.register_action_callback(definition)
    owner = spawn_entity(
        scenario.actor.world,
        [
            ActionOverrideComponent(
                (
                    ActionOverrideEntry(
                        "source",
                        destination_action="destination",
                        destination_argument="target_id",
                    ),
                    ActionOverrideEntry("destination", callback_id=definition.id),
                )
            )
        ],
    )

    await scenario.actor.submit(_command(scenario, str(owner.id)))
    await scenario.actor.tick(0.0)

    spans = {
        span.name: span
        for span in override_otel_capture.get_finished_spans()
        if span.name in {"command.submit", "command.attempt", "handler.execute"}
    }
    assert set(spans) == {"command.submit", "command.attempt", "handler.execute"}
    for span in spans.values():
        assert span.attributes["command.type"] == "destination"
        assert span.attributes["command.requested_action"] == "source"
        assert span.attributes["command.resolved_action"] == "destination"
        assert span.attributes["command.override.kind"] == "alias_callback"
        assert span.attributes["command.override.entity_id"] == str(owner.id)
        assert span.attributes["command.override.callback_id"] == definition.id
    assert spans["command.submit"].attributes["command.lane"] == "focus"


@pytest.mark.parametrize(
    ("owner_overrides", "expected"),
    [
        (
            (
                ActionOverrideEntry(
                    "source",
                    destination_action="missing",
                    destination_argument="target_id",
                ),
            ),
            "action override destination 'missing' is not registered",
        ),
        (
            (
                ActionOverrideEntry(
                    "source",
                    destination_action="destination",
                    destination_argument="preserved",
                ),
            ),
            "action override destination argument 'preserved' is not an entity argument",
        ),
        (
            (
                ActionOverrideEntry(
                    "source",
                    destination_action="destination",
                    destination_argument="missing_id",
                ),
            ),
            "action override destination argument 'missing_id' is not an entity argument",
        ),
        (
            (ActionOverrideEntry("source", callback_id="missing.plugin.callback"),),
            "action override callback 'missing.plugin.callback' is unavailable",
        ),
        (
            (
                ActionOverrideEntry(
                    "source",
                    destination_action="destination",
                    destination_argument="target_id",
                ),
                ActionOverrideEntry(
                    "destination",
                    destination_action="source",
                    destination_argument="item_id",
                ),
            ),
            "action override alias chains are not supported",
        ),
        (
            (
                ActionOverrideEntry(
                    "source",
                    destination_action="destination",
                    destination_argument="target_id",
                ),
                ActionOverrideEntry(
                    "destination",
                    callback_id="missing.plugin.destination",
                ),
            ),
            "action override callback 'missing.plugin.destination' is unavailable",
        ),
    ],
)
async def test_invalid_override_routes_are_rejected(owner_overrides, expected):
    scenario, _source, _destination = _setup()
    owner = spawn_entity(
        scenario.actor.world,
        [ActionOverrideComponent(owner_overrides)],
    )
    rejected = _collect(scenario.actor, CommandRejectedEvent)

    outcome = await scenario.actor.submit(_command(scenario, str(owner.id)))

    assert outcome.accepted is False
    assert expected in outcome.reason
    assert rejected[0].reason == outcome.reason
    assert scenario.actor.pending_submissions() == []


async def test_distinct_owners_claiming_same_action_are_ambiguous_but_duplicate_id_is_not():
    scenario, _source, _destination = _setup()
    override = ActionOverrideComponent(
        (ActionOverrideEntry("source", callback_id="missing.callback"),)
    )
    owner_a = spawn_entity(scenario.actor.world, [override])
    owner_b = spawn_entity(scenario.actor.world, [override])

    ambiguous = await scenario.actor.submit(
        _command(scenario, str(owner_a.id), other_id=str(owner_b.id))
    )
    duplicate = await scenario.actor.submit(
        _command(scenario, str(owner_a.id), other_id=str(owner_a.id))
    )

    assert ambiguous.reason == "multiple entities override action 'source'"
    assert duplicate.reason == "action override callback 'missing.callback' is unavailable"


async def test_callback_unavailable_after_queueing_rejects_at_attempt():
    scenario, _source, _destination = _setup()
    definition = EntityActionCallbackDefinition("example.items.activate", _callback)
    scenario.actor.register_action_callback(definition)
    owner = spawn_entity(
        scenario.actor.world,
        [ActionOverrideComponent((ActionOverrideEntry("source", callback_id=definition.id),))],
    )
    rejected = _collect(scenario.actor, CommandRejectedEvent)

    await scenario.actor.submit(_command(scenario, str(owner.id)))
    scenario.actor._action_callbacks.clear()
    await scenario.actor.tick(0.0)

    assert rejected[0].reason == f"action override callback {definition.id!r} is unavailable"


def test_plugin_callback_registration_validates_namespace_and_duplicates():
    definition = EntityActionCallbackDefinition("example.items.activate", _callback)
    plugin = Plugin(
        id="example.items",
        name="Items",
        commands=CommandContribution(action_callbacks=(definition,)),
    )
    registry = PluginRegistry((plugin,))
    assert registry.action_callbacks[definition.id] == ("example.items", definition)

    with pytest.raises(PluginError, match="must be namespaced"):
        PluginRegistry(
            (
                Plugin(
                    id="example.items",
                    name="Items",
                    commands=CommandContribution(
                        action_callbacks=(
                            EntityActionCallbackDefinition("wrong.activate", _callback),
                        )
                    ),
                ),
            )
        )
    with pytest.raises(PluginError, match="duplicate action callback name"):
        PluginRegistry(
            (
                Plugin(
                    id="example.items",
                    name="Items",
                    commands=CommandContribution(action_callbacks=(definition, definition)),
                ),
            )
        )


def test_apply_plugins_registers_callbacks_on_actor():
    definition = EntityActionCallbackDefinition("example.items.activate", _callback)
    actor = build_scenario().actor
    apply_plugins(
        (
            Plugin(
                id="example.items",
                name="Items",
                commands=CommandContribution(action_callbacks=(definition,)),
            ),
        ),
        actor,
    )
    with pytest.raises(ValueError, match="duplicate action callback id"):
        actor.register_action_callback(definition)
