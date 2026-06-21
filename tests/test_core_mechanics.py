"""End-to-end checks for core simulation mechanics."""

from __future__ import annotations

import pytest
from conftest import build_scenario

import bunnyland.core.world_actor as world_actor_module
from bunnyland.claims import controlled_character
from bunnyland.core import (
    ActionPointsComponent,
    AttentionComponent,
    BleedingComponent,
    BodyPlanComponent,
    CharacterComponent,
    ClaimTimeoutComponent,
    CommandCost,
    CommandQueues,
    ContainmentMode,
    Contains,
    DeadComponent,
    DiscordControllerComponent,
    DownedComponent,
    EncumbranceComponent,
    ExitTo,
    GenerationIntentComponent,
    HandlerResult,
    HasInjury,
    HealthComponent,
    HearingComponent,
    IdentityComponent,
    Lane,
    MCPControllerComponent,
    MoveHandler,
    NoiseComponent,
    OnInsufficientPoints,
    PainComponent,
    PerceptionComponent,
    SleepingComponent,
    StealthComponent,
    StimulusComponent,
    SuspendedComponent,
    SuspendedControllerComponent,
    WebControllerComponent,
    WeightComponent,
    WorldActor,
    build_submitted_command,
    parse_entity_id,
    remove_from_container,
    spawn_entity,
)
from bunnyland.core.claim_timeout import normalize_claim_timeout
from bunnyland.core.consequences import (
    AttentionConsequence,
    HearingConsequence,
    InjuryConsequence,
)
from bunnyland.core.edges import ControlledBy
from bunnyland.core.events import (
    ActionPointsChangedEvent,
    AttentionShiftedEvent,
    CommandCancelledEvent,
    CommandExecutedEvent,
    CommandExpiredEvent,
    CommandRejectedEvent,
    EncumbranceChangedEvent,
    EntitySeenEvent,
    FocusPointsChangedEvent,
    GeneratedEntityEvent,
    InjuryAddedEvent,
    NoiseHeardEvent,
)
from bunnyland.core.handlers.base import HandlerContext, require_reachable_entity
from bunnyland.mechanics.barbariansim import AttackHandler

HOUR = 3600.0


def collect(actor, event_type):
    seen = []
    actor.bus.subscribe(event_type, seen.append)
    return seen


def test_require_reachable_entity_reports_validation_failures():
    scenario = build_scenario()
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    character = scenario.actor.world.get_entity(scenario.character)
    reachable = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="reachable lever", kind="button")],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), reachable.id
    )
    far = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="far lever", kind="button")],
    )

    assert require_reachable_entity(
        ctx,
        character,
        "not-an-id",
        invalid_reason="invalid target",
        missing_reason="missing target",
        unreachable_reason="unreachable target",
    )[2].reason == "invalid target"
    assert require_reachable_entity(
        ctx,
        character,
        "entity_999999",
        invalid_reason="invalid target",
        missing_reason="missing target",
        unreachable_reason="unreachable target",
    )[2].reason == "missing target"
    assert require_reachable_entity(
        ctx,
        character,
        str(far.id),
        invalid_reason="invalid target",
        missing_reason="missing target",
        unreachable_reason="unreachable target",
    )[2].reason == "unreachable target"

    entity_id, entity, error = require_reachable_entity(
        ctx,
        character,
        str(reachable.id),
        invalid_reason="invalid target",
        missing_reason="missing target",
        unreachable_reason="unreachable target",
    )
    assert entity_id == reachable.id
    assert entity is not None
    assert error is None


def test_controlled_character_returns_none_for_unassigned_matching_controller():
    actor = WorldActor()
    controller = spawn_entity(
        actor.world,
        [WebControllerComponent(client_id="web-1")],
    )
    other_controller = spawn_entity(
        actor.world,
        [WebControllerComponent(client_id="web-2")],
    )
    character = spawn_entity(
        actor.world,
        [IdentityComponent(name="Juniper", kind="character"), CharacterComponent()],
    )
    character.add_relationship(ControlledBy(generation=1), other_controller.id)

    result = controlled_character(
        actor,
        WebControllerComponent,
        lambda component: component.client_id == controller.get_component(
            WebControllerComponent
        ).client_id,
    )

    assert result is None


def test_normalize_claim_timeout_allows_unspecified_timeout():
    assert normalize_claim_timeout(None) is None


def test_remove_from_container_ignores_missing_entity():
    scenario = build_scenario()
    remove_from_container(scenario.actor.world, parse_entity_id("entity_999999"))


def test_generated_entity_event_exposes_generation_intent_fields():
    event = GeneratedEntityEvent(
        event_id="evt-generated",
        created_at="2026-01-01T00:00:00Z",
        world_epoch=0,
        seed="seed",
        entity_id="entity_1",
        entity_key="room-1",
        entity_kind="room",
        generation=GenerationIntentComponent(
            description="moss room",
            tags=("moss",),
            wants=("light",),
            needs=("water",),
        ),
    )

    assert event.intent == "moss room"
    assert event.tags == ("moss",)
    assert event.wants == ("light",)
    assert event.needs == ("water",)


def _command(scenario, command_type="move", **kwargs):
    payload = kwargs.pop("payload", None)
    if payload is None and command_type == "move":
        payload = {"direction": "north"}
    return build_submitted_command(
        character_id=kwargs.pop("character_id", str(scenario.character)),
        controller_id=kwargs.pop("controller_id", str(scenario.controller)),
        controller_generation=kwargs.pop("controller_generation", scenario.generation),
        command_type=command_type,
        cost=kwargs.pop("cost", CommandCost(action=0)),
        lane=kwargs.pop("lane", Lane.WORLD),
        payload=payload,
        on_insufficient_points=kwargs.pop(
            "on_insufficient_points", OnInsufficientPoints.QUEUE
        ),
        submitted_at_epoch=kwargs.pop("submitted_at_epoch", 0),
        expires_at_epoch=kwargs.pop("expires_at_epoch", None),
        command_id=kwargs.pop("command_id", None),
    )


def test_command_queues_report_pending_commands_by_character_and_lane():
    scenario = build_scenario()
    queues = CommandQueues()
    world_command = _command(scenario, command_id="world-command")
    focus_command = _command(
        scenario,
        command_id="focus-command",
        command_type="remember",
        lane=Lane.FOCUS,
        payload={"query": "moss"},
    )

    assert queues.pop(str(scenario.character), Lane.WORLD) is None
    assert queues.pending(str(scenario.character)) == []

    queues.enqueue(world_command)
    queues.enqueue(focus_command)

    assert queues.has_pending(str(scenario.character))
    assert queues.pending(str(scenario.character), Lane.WORLD) == [world_command]
    assert queues.pending(str(scenario.character), Lane.FOCUS) == [focus_command]
    assert queues.pending(str(scenario.character)) == [focus_command, world_command]
    assert queues.remove(str(scenario.character), "world-command") == world_command
    assert queues.pending(str(scenario.character), Lane.WORLD) == []
    assert queues.remove(str(scenario.character), "missing") is None


async def test_world_actor_hooks_available_commands_and_submit_nowait():
    scenario = build_scenario()
    calls = []

    def sync_hook(actor):
        calls.append(("sync", actor.epoch))

    async def async_hook(actor):
        calls.append(("async", actor.epoch))

    scenario.actor.register_after_tick(sync_hook)
    scenario.actor.register_after_tick(async_hook)
    executed = collect(scenario.actor, CommandExecutedEvent)

    assert "move" in scenario.actor.available_command_types()
    assert "take-control" in scenario.actor.available_command_types()

    scenario.actor.submit_nowait(_command(scenario))
    await scenario.actor.tick(0.0)

    assert [event.command_type for event in executed] == ["move"]
    assert calls == [("sync", 0), ("async", 0)]


def test_move_handler_rejects_invalid_detached_and_unmatched_exits():
    scenario = build_scenario()
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    handler = MoveHandler()

    invalid = _command(scenario, character_id="not-an-id")
    assert handler.execute(ctx, invalid).reason == "invalid character id"

    missing = _command(scenario, character_id="entity_999")
    assert handler.execute(ctx, missing).reason == "character does not exist"

    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(
        Contains,
        scenario.character,
    )
    assert handler.execute(ctx, _command(scenario)).reason == "character is not in a room"

    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        scenario.character,
    )
    assert (
        handler.execute(ctx, _command(scenario, payload={"direction": "west"})).reason
        == "no matching exit"
    )


def test_move_handler_rejects_dangling_exit_target():
    scenario = build_scenario()
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    scenario.actor.world._relationships.setdefault(scenario.room_a, {}).setdefault(ExitTo, {})[
        parse_entity_id("entity_999")
    ] = ExitTo(direction="down")

    result = MoveHandler().execute(ctx, _command(scenario, payload={"direction": "down"}))

    assert result.reason == "destination does not exist"


def test_move_handler_can_select_exit_by_target_id_and_custom_noise():
    scenario = build_scenario()
    ctx = HandlerContext(scenario.actor.world, scenario.actor.epoch)
    command = _command(
        scenario,
        payload={"exit_id": str(scenario.room_b), "noise": 2.5},
    )

    result = MoveHandler().execute(ctx, command)

    assert result.ok is True
    event = result.events[0]
    assert event.to_room_id == str(scenario.room_b)
    assert event.direction == "north"
    assert event.arrival_summary.startswith("North Tunnel")
    assert "Here: Juniper." in event.arrival_summary
    assert "Exits: south." in event.arrival_summary

    noises = scenario.actor.world.query().with_all([NoiseComponent]).execute_entities()
    noise = next(iter(noises)).get_component(NoiseComponent)
    assert noise.loudness == 2.5
    assert noise.room_id == str(scenario.room_b)


def test_world_actor_registration_helpers_and_bind_clock_paths():
    actor = WorldActor()
    definition = type("Definition", (), {"command_type": "custom"})()
    consequence = type("Consequence", (), {"process": lambda self, world, epoch: ()})()

    actor.register_action_definition(definition)
    actor.register_consequence(consequence)

    assert actor.action_definitions() == (definition,)
    assert actor._consequences[-1] is consequence

    actor.bind_clock()
    assert actor.epoch == 0

    actor.world.remove(actor._clock_entity.id)

    with pytest.raises(RuntimeError, match="expected exactly one world clock"):
        actor.bind_clock()


async def test_world_actor_records_claim_activity_for_current_controller(monkeypatch):
    scenario = build_scenario()
    controller = scenario.actor.world.get_entity(scenario.controller)
    controller.add_component(ClaimTimeoutComponent(claimed_at_unix=1, last_command_unix=1))
    monkeypatch.setattr(world_actor_module.time, "time", lambda: 1234)

    scenario.actor.submit_nowait(_command(scenario))
    await scenario.actor.tick(0.0)

    assert controller.get_component(ClaimTimeoutComponent).last_command_unix == 1234

    stale = _command(scenario, controller_generation=scenario.generation + 1)
    scenario.actor._record_controller_activity(stale)
    assert controller.get_component(ClaimTimeoutComponent).last_command_unix == 1234

    missing = _command(
        scenario,
        character_id="not-an-entity",
        controller_id="entity_999",
    )
    scenario.actor._record_controller_activity(missing)
    assert controller.get_component(ClaimTimeoutComponent).last_command_unix == 1234


async def test_world_actor_rejects_expired_missing_and_state_blocked_commands():
    scenario = build_scenario()
    rejected = collect(scenario.actor, CommandRejectedEvent)
    expired = collect(scenario.actor, CommandExpiredEvent)
    character = scenario.actor.world.get_entity(scenario.character)

    scenario.actor.submit_nowait(_command(scenario, character_id="entity_999"))
    await scenario.actor.tick(0.0)
    assert rejected[-1].reason == "character does not exist"

    scenario.actor.submit_nowait(_command(scenario, expires_at_epoch=0))
    await scenario.actor.tick(1.0)
    assert expired[-1].command_type == "move"

    scenario.actor.submit_nowait(_command(scenario, controller_generation=scenario.generation + 1))
    await scenario.actor.tick(0.0)
    assert rejected[-1].reason == "stale controller generation"

    character.add_component(SuspendedComponent(reason="test"))
    scenario.actor.submit_nowait(_command(scenario))
    await scenario.actor.tick(0.0)
    assert rejected[-1].reason == "character is suspended"
    character.remove_component(SuspendedComponent)

    character.add_component(DownedComponent(downed_at_epoch=scenario.actor.epoch, cause="test"))
    scenario.actor.submit_nowait(_command(scenario))
    await scenario.actor.tick(0.0)
    assert rejected[-1].reason == "character is downed"
    character.remove_component(DownedComponent)

    character.add_component(SleepingComponent(started_at_epoch=scenario.actor.epoch))
    scenario.actor.submit_nowait(_command(scenario))
    await scenario.actor.tick(0.0)
    assert rejected[-1].reason == "character is asleep"
    character.remove_component(SleepingComponent)

    character.add_component(DeadComponent(died_at_epoch=scenario.actor.epoch, cause="test"))
    scenario.actor.submit_nowait(_command(scenario))
    await scenario.actor.tick(0.0)
    assert rejected[-1].reason == "character is dead"


async def test_world_actor_rejects_gate_affordability_missing_handler_and_handler_failure():
    scenario = build_scenario(action_current=0.0)
    rejected = collect(scenario.actor, CommandRejectedEvent)

    scenario.actor.register_gate(lambda _world, _command: (True, None))
    scenario.actor.register_gate(lambda _world, _command: (False, "gate closed"))
    scenario.actor.submit_nowait(_command(scenario))
    await scenario.actor.tick(0.0)
    assert rejected[-1].reason == "gate closed"

    scenario = build_scenario(action_current=0.0)
    rejected = collect(scenario.actor, CommandRejectedEvent)
    queued = _command(scenario, cost=CommandCost(action=1))
    scenario.actor.submit_nowait(queued)
    await scenario.actor.tick(0.0)
    assert scenario.actor.queues.peek(str(scenario.character), Lane.WORLD) == queued
    assert rejected == []

    deny = _command(
        scenario,
        cost=CommandCost(action=10),
        on_insufficient_points=OnInsufficientPoints.DENY,
    )
    scenario.actor.queues.flush_character(str(scenario.character))
    scenario.actor.submit_nowait(deny)
    await scenario.actor.tick(0.0)
    assert rejected[-1].reason == "insufficient points"

    scenario = build_scenario()
    rejected = collect(scenario.actor, CommandRejectedEvent)
    scenario.actor.submit_nowait(_command(scenario, "missing-command", payload={}))
    await scenario.actor.tick(0.0)
    assert rejected[-1].reason == "no handler for missing-command"

    class FailingHandler:
        command_type = "fail"

        def execute(self, _ctx, _command):
            return HandlerResult(ok=False)

    scenario.actor.register_handler(FailingHandler())
    scenario.actor.submit_nowait(_command(scenario, "fail", payload={}))
    await scenario.actor.tick(0.0)
    assert rejected[-1].reason == "rejected by handler"


async def test_world_actor_tries_latest_matching_handler_for_shared_verbs():
    scenario = build_scenario()
    events: list[str] = []

    class FallbackHandler:
        command_type = "shared"

        def execute(self, _ctx, _command):
            events.append("fallback")
            return HandlerResult(ok=True)

    class SpecificHandler:
        command_type = "shared"

        def can_handle(self, _ctx, command):
            return command.payload.get("kind") == "specific"

        def execute(self, _ctx, _command):
            events.append("specific")
            return HandlerResult(ok=True)

    scenario.actor.register_handler(FallbackHandler())
    scenario.actor.register_handler(SpecificHandler())

    scenario.actor.submit_nowait(_command(scenario, "shared", payload={"kind": "specific"}))
    await scenario.actor.tick(0.0)
    scenario.actor.submit_nowait(_command(scenario, "shared", payload={"kind": "other"}))
    await scenario.actor.tick(0.0)

    assert events == ["specific", "fallback"]


def test_world_actor_initiative_order_handles_missing_and_unscored_entities():
    actor = WorldActor()
    character = spawn_entity(
        actor.world,
        [IdentityComponent(name="No Initiative", kind="character"), CharacterComponent()],
    )

    ordered = actor._initiative_order(["not-an-entity", str(character.id)])

    assert set(ordered) == {"not-an-entity", str(character.id)}


async def test_world_actor_spends_action_and_focus_on_success():
    scenario = build_scenario(action_current=5.0, focus_current=3.0)
    action_changes = collect(scenario.actor, ActionPointsChangedEvent)
    focus_changes = collect(scenario.actor, FocusPointsChangedEvent)

    class FocusHandler:
        command_type = "focus-test"

        def execute(self, _ctx, _command):
            return HandlerResult(ok=True)

    scenario.actor.register_handler(FocusHandler())
    scenario.actor.submit_nowait(
        _command(scenario, "focus-test", cost=CommandCost(action=2, focus=1), payload={})
    )
    await scenario.actor.tick(0.0)

    assert action_changes[-1].current == pytest.approx(3.0)
    assert focus_changes[-1].current == pytest.approx(2.0)


async def test_world_actor_control_commands_and_controller_kinds():
    scenario = build_scenario()
    controller_events = collect(scenario.actor, CommandExecutedEvent)
    changes = collect(scenario.actor, world_actor_module.ControllerChangedEvent)
    rejected = collect(scenario.actor, CommandRejectedEvent)
    character = scenario.actor.world.get_entity(scenario.character)

    assert (
        scenario.actor.current_generation(scenario.character, parse_entity_id("entity_999"))
        is None
    )
    assert (
        scenario.actor._generation_current(character, _command(scenario, controller_id="bad"))
        is False
    )

    discord = spawn_entity(
        scenario.actor.world, [DiscordControllerComponent(discord_user_id=1, default_channel_id=2)]
    )
    mcp = spawn_entity(scenario.actor.world, [MCPControllerComponent(agent_id="agent")])
    web = spawn_entity(scenario.actor.world, [WebControllerComponent(client_id="client")])
    suspended = spawn_entity(
        scenario.actor.world, [SuspendedControllerComponent(reason="already suspended")]
    )
    unknown = spawn_entity(scenario.actor.world, [IdentityComponent(name="Unknown", kind="test")])

    assert scenario.actor._controller_kind(discord.id) == "discord"
    assert scenario.actor._controller_kind(scenario.controller) == "llm"
    assert scenario.actor._controller_kind(mcp.id) == "mcp"
    assert scenario.actor._controller_kind(web.id) == "web"
    assert scenario.actor._controller_kind(suspended.id) == "suspended"
    assert scenario.actor._controller_kind(unknown.id) == "unknown"
    assert (
        scenario.actor._generation_current(
            character, _command(scenario, controller_id=str(mcp.id))
        )
        is False
    )
    character.add_relationship(ControlledBy(generation=7), mcp.id)
    assert (
        scenario.actor._generation_current(
            character,
            _command(scenario, controller_id=str(mcp.id), controller_generation=7),
        )
        is True
    )

    scenario.actor.submit_nowait(
        _command(
            scenario,
            "take-control",
            payload={"controller_id": str(web.id)},
            cost=CommandCost(action=99, focus=99),
        )
    )
    await scenario.actor.tick(0.0)
    assert controller_events[-1].command_type == "take-control"
    assert changes[-1].controller_kind == "web"

    scenario.actor.submit_nowait(
        _command(
            scenario,
            "suspend",
            payload={"controller_id": str(suspended.id), "reason": "away"},
        )
    )
    await scenario.actor.tick(0.0)
    assert character.has_component(SuspendedComponent)
    assert changes[-1].controller_kind == "suspended"

    scenario.actor.submit_nowait(
        _command(scenario, "resume", payload={"controller_id": str(web.id)})
    )
    await scenario.actor.tick(0.0)
    assert not character.has_component(SuspendedComponent)
    assert changes[-1].controller_kind == "web"

    scenario.actor.submit_nowait(
        _command(scenario, "take-control", payload={"controller_id": "entity_999"})
    )
    await scenario.actor.tick(0.0)
    assert rejected[-1].reason == "controller does not exist"

    character.add_component(DeadComponent(died_at_epoch=scenario.actor.epoch, cause="test"))
    scenario.actor.submit_nowait(
        _command(scenario, "take-control", payload={"controller_id": str(web.id)})
    )
    await scenario.actor.tick(0.0)
    assert rejected[-1].reason == "character is dead"

    other_suspended = spawn_entity(
        scenario.actor.world, [IdentityComponent(name="Suspended", kind="controller")]
    )
    generation = scenario.actor.suspend(scenario.character, other_suspended.id)
    assert generation >= 0
    assert other_suspended.has_component(SuspendedControllerComponent)


async def test_carried_weight_updates_load_and_reduces_speed_when_over_capacity():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(EncumbranceComponent(capacity=5.0))
    boulder = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="basalt boulder", kind="item"),
            WeightComponent(weight=10.0),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), boulder.id)
    changes = collect(scenario.actor, EncumbranceChangedEvent)

    await scenario.actor.tick(HOUR)

    encumbrance = character.get_component(EncumbranceComponent)
    assert encumbrance.current_load == pytest.approx(10.0)
    assert encumbrance.overburdened is True
    assert encumbrance.speed_multiplier == pytest.approx(0.5)
    assert changes[-1].actor_id == str(scenario.character)
    assert changes[-1].speed_multiplier == pytest.approx(0.5)


async def test_dropping_heavy_item_restores_encumbrance_speed():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(EncumbranceComponent(capacity=5.0))
    boulder = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="basalt boulder", kind="item"),
            WeightComponent(weight=10.0),
        ],
    )
    character.add_relationship(Contains(mode=ContainmentMode.INVENTORY), boulder.id)

    await scenario.actor.tick(HOUR)
    character.remove_relationship(Contains, boulder.id)
    await scenario.actor.tick(HOUR)

    encumbrance = character.get_component(EncumbranceComponent)
    assert encumbrance.current_load == pytest.approx(0.0)
    assert encumbrance.overburdened is False
    assert encumbrance.speed_multiplier == pytest.approx(1.0)


async def test_fight_creates_injury_and_bleeding_reduces_health():
    scenario = build_scenario()
    scenario.actor.register_handler(AttackHandler())
    attacker = scenario.actor.world.get_entity(scenario.character)
    attacker.add_component(HealthComponent(current=20.0, maximum=20.0))
    target = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Hazel", kind="character"),
            CharacterComponent(),
            ActionPointsComponent(current=5.0, maximum=5.0),
            HealthComponent(current=20.0, maximum=20.0),
            BodyPlanComponent(parts=("torso",), vital_parts=("torso",)),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), target.id
    )
    injuries = collect(scenario.actor, InjuryAddedEvent)

    await scenario.actor.submit(
        build_submitted_command(
            character_id=str(scenario.character),
            controller_id=str(scenario.controller),
            controller_generation=scenario.generation,
            command_type="attack",
            cost=CommandCost(action=1),
            lane=Lane.WORLD,
            payload={"target_id": str(target.id)},
        )
    )
    await scenario.actor.tick(HOUR)

    target_health = target.get_component(HealthComponent)
    assert target_health.current == pytest.approx(15.0)
    assert target.has_component(PainComponent)
    assert target.get_component(PainComponent).current == pytest.approx(5.0)
    assert target.has_component(BleedingComponent)
    assert target.get_component(BleedingComponent).rate == pytest.approx(0.5)
    assert len(target.get_relationships(HasInjury)) == 1
    assert injuries[-1].body_part == "torso"

    await scenario.actor.tick(HOUR)

    assert target.get_component(HealthComponent).current == pytest.approx(14.5)
    assert target.get_component(BleedingComponent).accumulated_loss == pytest.approx(0.5)


async def test_room_perception_tracks_visible_entities_and_skips_hidden():
    scenario = build_scenario()
    visible_item = spawn_entity(
        scenario.actor.world, [IdentityComponent(name="brass bell", kind="item")]
    )
    hidden_item = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="hidden cache", kind="item"),
            StealthComponent(visibility_level=0.05, hidden_threshold=0.1, hiding=True),
        ],
    )
    room = scenario.actor.world.get_entity(scenario.room_a)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), visible_item.id)
    room.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), hidden_item.id)
    seen = collect(scenario.actor, EntitySeenEvent)

    await scenario.actor.tick(HOUR)

    perception = scenario.actor.world.get_entity(scenario.character).get_component(
        PerceptionComponent
    )
    assert str(visible_item.id) in perception.visible_entities
    assert str(hidden_item.id) not in perception.visible_entities
    assert any(event.entity_id == str(visible_item.id) for event in seen)


async def test_listener_hears_character_move_when_noise_meets_sensitivity():
    scenario = build_scenario()
    listener = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Hazel", kind="character"),
            CharacterComponent(),
            HearingComponent(sensitivity=0.5),
        ],
    )
    hard_of_hearing = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Clover", kind="character"),
            CharacterComponent(),
            HearingComponent(sensitivity=2.0),
        ],
    )
    room_b = scenario.actor.world.get_entity(scenario.room_b)
    room_b.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), listener.id)
    room_b.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), hard_of_hearing.id)
    heard = collect(scenario.actor, NoiseHeardEvent)

    await scenario.actor.submit(
        build_submitted_command(
            character_id=str(scenario.character),
            controller_id=str(scenario.controller),
            controller_generation=scenario.generation,
            command_type="move",
            cost=CommandCost(action=1),
            lane=Lane.WORLD,
            payload={"direction": "north", "noise": 1.0},
        )
    )
    await scenario.actor.tick(HOUR)

    listener_perception = listener.get_component(PerceptionComponent)
    quiet_perception = hard_of_hearing.get_component(PerceptionComponent)
    assert len(listener_perception.audible_entities) == 1
    assert quiet_perception.audible_entities == frozenset()
    noise_id = next(iter(listener_perception.audible_entities))
    parsed_noise_id = parse_entity_id(noise_id)
    assert parsed_noise_id is not None
    noise = scenario.actor.world.get_entity(parsed_noise_id)
    assert noise.get_component(NoiseComponent).source_entity_id == str(scenario.character)
    assert any(event.noise_id == noise_id and event.actor_id == str(listener.id) for event in heard)

    await scenario.actor.tick(61)

    assert not scenario.actor.world.has_entity(parsed_noise_id)
    assert listener.get_component(PerceptionComponent).audible_entities == frozenset()


async def test_stimulus_shifts_attention_then_decays_after_expiration():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(AttentionComponent(decay_rate=0.5))
    source = spawn_entity(
        scenario.actor.world, [IdentityComponent(name="silver chime", kind="item")]
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), source.id
    )
    spawn_entity(
        scenario.actor.world,
        [
            StimulusComponent(
                stimulus_type="sound",
                source_entity_id=str(source.id),
                room_id=str(scenario.room_a),
                intensity=1.0,
                created_at_epoch=0,
                expires_at_epoch=int(HOUR),
                text="a clear chime",
            )
        ],
    )
    shifts = collect(scenario.actor, AttentionShiftedEvent)

    await scenario.actor.tick(HOUR)

    attention = character.get_component(AttentionComponent)
    assert attention.focus_entity_id == str(source.id)
    assert attention.score == pytest.approx(1.0)
    assert any(event.focus_entity_id == str(source.id) for event in shifts)

    await scenario.actor.tick(HOUR)

    attention = character.get_component(AttentionComponent)
    assert attention.focus_entity_id == str(source.id)
    assert attention.score == pytest.approx(0.5)


def test_injury_consequence_skips_non_injury_edges():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)

    # An injury edge pointing at an entity that carries no InjuryComponent.
    non_injury = spawn_entity(world, [IdentityComponent(name="splinter", kind="item")])
    character.add_relationship(HasInjury(), non_injury.id)

    # The edge contributes no pain, so the character ends up with zero pain.
    InjuryConsequence().process(world, epoch=0)

    assert not character.has_component(PainComponent) or character.get_component(
        PainComponent
    ).current == pytest.approx(0.0)


def test_hearing_consequence_clears_audible_when_perception_inactive():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    character.add_component(
        PerceptionComponent(active=False, audible_entities=frozenset({"stale"}))
    )
    # A noise in the room would normally be audible, but perception is inactive.
    spawn_entity(
        world,
        [
            NoiseComponent(
                loudness=5.0,
                text="a loud crash",
                source_entity_id=None,
                room_id=str(scenario.room_a),
                expires_at_epoch=int(HOUR),
            )
        ],
    )

    HearingConsequence().process(world, epoch=0)

    assert (
        world.get_entity(scenario.character)
        .get_component(PerceptionComponent)
        .audible_entities
        == frozenset()
    )


def test_attention_consequence_skips_other_room_and_self_stimuli():
    scenario = build_scenario()
    world = scenario.actor.world
    character = world.get_entity(scenario.character)
    character.add_component(AttentionComponent())

    # Stimulus in a different room -> skipped on the room mismatch branch.
    spawn_entity(
        world,
        [
            StimulusComponent(
                stimulus_type="sound",
                source_entity_id="someone",
                room_id=str(scenario.room_b),
                intensity=1.0,
                created_at_epoch=0,
                expires_at_epoch=int(HOUR),
                text="elsewhere",
            )
        ],
    )
    # Stimulus sourced by the character itself -> skipped on the self branch.
    spawn_entity(
        world,
        [
            StimulusComponent(
                stimulus_type="sound",
                source_entity_id=str(character.id),
                room_id=str(scenario.room_a),
                intensity=1.0,
                created_at_epoch=0,
                expires_at_epoch=int(HOUR),
                text="own footsteps",
            )
        ],
    )

    AttentionConsequence().process(world, epoch=0)

    # No valid candidate, so attention keeps no focus.
    assert character.get_component(AttentionComponent).focus_entity_id is None


def test_entity_id_from_string_rejects_unknown_id():
    from bunnyland.core.consequences import _entity_id_from_string

    scenario = build_scenario()
    with pytest.raises(KeyError):
        _entity_id_from_string(scenario.actor.world, "not-a-real-entity")


async def test_submit_rejects_command_for_missing_character_synchronously():
    scenario = build_scenario()
    rejected = collect(scenario.actor, CommandRejectedEvent)

    outcome = await scenario.actor.submit(_command(scenario, character_id="entity_999999"))

    # _validate_submission rejects before queueing: never enters the inbox, emits a
    # synchronous rejection with the missing-character reason.
    assert outcome.accepted is False
    assert outcome.reason == "character does not exist"
    assert scenario.actor._inbox.empty()
    assert rejected[-1].reason == "character does not exist"


async def test_cancel_command_removes_a_queued_command_from_the_inbox():
    scenario = build_scenario()
    cancelled = collect(scenario.actor, CommandCancelledEvent)
    command = _command(scenario, command_id="inbox-cancel-me")

    outcome = await scenario.actor.submit(command)
    assert outcome.accepted is True
    assert not scenario.actor._inbox.empty()

    removed = await scenario.actor.cancel_command(
        str(scenario.character), "inbox-cancel-me"
    )

    # The command is pulled out of the inbox (before any tick ingests it) and a
    # cancellation event is published for the removed command.
    assert removed is command
    assert scenario.actor._inbox.empty()
    assert [event.command_id for event in cancelled] == ["inbox-cancel-me"]
