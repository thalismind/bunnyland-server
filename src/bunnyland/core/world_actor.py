"""The single async world actor (spec sections 3.2, 5).

All world mutation flows through this actor:

    submitted command -> volatile queue -> tick -> validation -> handler -> ECS mutation
    -> typed events -> projections / side effects

The actor owns the synchronous Relics ``World``. External callers (Discord, LLM workers,
timers) never touch the ECS directly; they ``submit`` commands into an async inbox. Each
``tick`` drains the inbox, advances simulation, then processes queued commands in
initiative order with random tie-breaks.
"""

from __future__ import annotations

import asyncio
import inspect
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from relics import EntityId, World

from .actions import ActionDefinition
from .commands import Lane, OnInsufficientPoints, SubmittedCommand
from .components import (
    ActionPointsComponent,
    DeadComponent,
    DownedComponent,
    FocusPointsComponent,
    InitiativeComponent,
    SleepingComponent,
    SuspendedComponent,
    WorldClockComponent,
)
from .consequences import (
    AttentionConsequence,
    Consequence,
    EncumbranceConsequence,
    HealthConsequence,
    HearingConsequence,
    InjuryConsequence,
    PerceptionConsequence,
)
from .controllers import (
    DiscordControllerComponent,
    LLMControllerComponent,
    MCPControllerComponent,
    SuspendedControllerComponent,
)
from .ecs import ensure_blank_prefab, parse_entity_id, replace_component, spawn_entity
from .edges import ControlledBy
from .events import (
    ActionPointsChangedEvent,
    CommandExecutedEvent,
    CommandExpiredEvent,
    CommandQueuedEvent,
    CommandRejectedEvent,
    CommandSubmittedEvent,
    ControllerChangedEvent,
    DomainEvent,
    EventBus,
    FocusPointsChangedEvent,
)
from .handlers import CommandHandler, HandlerContext
from .handlers.lifecycle import WakeHandler
from .queue import CommandQueues
from .systems import ActionFocusRegenSystem, WorldClockSystem

#: Control verbs change the controller itself (spec 7.4); they carry no point cost and
#: bypass generation/participation gates so handoff and resume always work.
CONTROL_COMMANDS = frozenset({"take-control", "release-to-llm", "suspend", "resume"})

#: A policy gate inspects a command against the world and returns ``(allowed, reason)``.
CommandGate = Callable[[World, SubmittedCommand], tuple[bool, "str | None"]]
AfterTickHook = Callable[["WorldActor"], None | Awaitable[None]]


@dataclass(frozen=True)
class _LaneOutcome:
    """Result of attempting the command at the front of a lane."""

    executed: bool
    stop_lane: bool  # leave remaining commands queued (insufficient points, waiting)


class WorldActor:
    """Owns the Relics world and serializes all mutations through ticks."""

    def __init__(self, world: World | None = None, *, rng: random.Random | None = None) -> None:
        self.world = world or World()
        ensure_blank_prefab(self.world)
        self.bus = EventBus()
        self.queues = CommandQueues()
        self._handlers: dict[str, CommandHandler] = {}
        self._action_definitions: dict[str, ActionDefinition] = {}
        self._consequences: list[Consequence] = [
            EncumbranceConsequence(),
            InjuryConsequence(),
            HealthConsequence(),
            PerceptionConsequence(),
            HearingConsequence(),
            AttentionConsequence(),
        ]
        #: Policy gates: (world, command) -> (allowed, reason). Any deny rejects the
        #: command before it costs anything (spec 20). Plugins register these.
        self._gates: list[CommandGate] = []
        self._after_tick: list[AfterTickHook] = []
        self._inbox: asyncio.Queue[SubmittedCommand] = asyncio.Queue()
        self._rng = rng or random.Random()
        self._lock = asyncio.Lock()

        self.world.register_system(WorldClockSystem())
        self.world.register_system(ActionFocusRegenSystem())

        # World singleton holds the authoritative clock.
        self._clock_entity = spawn_entity(self.world, [WorldClockComponent()])

    # -- registration -------------------------------------------------------------------

    def register_handler(self, handler: CommandHandler) -> None:
        self._handlers[handler.command_type] = handler

    def register_action_definition(self, definition: ActionDefinition) -> None:
        self._action_definitions[definition.command_type] = definition

    def action_definitions(self) -> tuple[ActionDefinition, ...]:
        return tuple(self._action_definitions.values())

    def register_consequence(self, consequence: Consequence) -> None:
        """Add a post-command consequence pass (spec 5.6 phase 6)."""
        self._consequences.append(consequence)

    def register_gate(self, gate: CommandGate) -> None:
        """Add a policy gate that can veto a command before it executes (spec 20)."""
        self._gates.append(gate)

    def register_after_tick(self, hook: AfterTickHook) -> None:
        """Run ``hook`` at the end of every tick while the actor owns the world lock."""
        self._after_tick.append(hook)

    def available_command_types(self) -> tuple[str, ...]:
        """Return command types currently accepted by this actor."""

        return tuple(sorted({*self._handlers.keys(), *CONTROL_COMMANDS}))

    # -- clock --------------------------------------------------------------------------

    @property
    def epoch(self) -> int:
        return self._clock_entity.get_component(WorldClockComponent).game_time_seconds

    def bind_clock(self) -> None:
        """Re-point ``_clock_entity`` at the world's clock entity.

        Loading a saved world replaces every entity (including the clock spawned in
        ``__init__``), so persistence calls this afterwards to rebind the singleton clock.
        """
        clocks = list(self.world.query().with_all([WorldClockComponent]).execute_entities())
        if len(clocks) != 1:
            raise RuntimeError(f"expected exactly one world clock, found {len(clocks)}")
        self._clock_entity = clocks[0]

    # -- submission ---------------------------------------------------------------------

    async def submit(self, command: SubmittedCommand) -> None:
        """Queue a command for ingestion on the next tick. Never mutates the world."""
        await self._inbox.put(command)

    def submit_nowait(self, command: SubmittedCommand) -> None:
        self._inbox.put_nowait(command)

    # -- tick pipeline ------------------------------------------------------------------

    async def tick(self, game_delta_seconds: float) -> None:
        """Run one deterministic world tick (spec 5.6)."""
        async with self._lock:
            await self._ingest()
            # Phases 2-4: advance clock, regen Action/Focus, run passive systems.
            self.world.tick(game_delta_seconds)
            # Phase 5: process queued commands in initiative order.
            await self._process_commands()
            # Phase 6: consequence systems (downed/death transitions, etc.).
            await self._run_consequences()
            await self._run_after_tick()

    async def _run_consequences(self) -> None:
        for consequence in self._consequences:
            for event in consequence.process(self.world, self.epoch):
                await self._publish(event)

    async def _run_after_tick(self) -> None:
        for hook in self._after_tick:
            result = hook(self)
            if inspect.isawaitable(result):
                await result

    async def _ingest(self) -> None:
        while not self._inbox.empty():
            command = self._inbox.get_nowait()
            self.queues.enqueue(command)
            await self._publish(
                CommandSubmittedEvent(
                    **self._event_base(
                        actor_id=command.character_id,
                        command_id=command.command_id,
                        command_type=command.command_type,
                    )
                )
            )
            await self._publish(
                CommandQueuedEvent(
                    **self._event_base(
                        actor_id=command.character_id,
                        command_id=command.command_id,
                        command_type=command.command_type,
                        lane=command.lane.value,
                    )
                )
            )

    async def _process_commands(self) -> None:
        for character_id in self._initiative_order(self.queues.characters_with_pending()):
            # Focus lane drains (subject to affordability); world lane runs at most once.
            await self._drain_lane(character_id, Lane.FOCUS, max_executions=None)
            await self._drain_lane(character_id, Lane.WORLD, max_executions=1)

    def _initiative_order(self, character_ids: list[str]) -> list[str]:
        def key(cid: str) -> float:
            entity_id = parse_entity_id(cid)
            if entity_id is None or not self.world.has_entity(entity_id):
                return 0.0
            entity = self.world.get_entity(entity_id)
            if entity.has_component(InitiativeComponent):
                return entity.get_component(InitiativeComponent).score
            return 0.0

        # Random jitter breaks ties freshly each tick (spec 5.5).
        return sorted(character_ids, key=lambda cid: (key(cid), self._rng.random()), reverse=True)

    async def _drain_lane(
        self, character_id: str, lane: Lane, *, max_executions: int | None
    ) -> None:
        executions = 0
        while max_executions is None or executions < max_executions:
            command = self.queues.peek(character_id, lane)
            if command is None:
                return
            outcome = await self._attempt(character_id, lane, command)
            if outcome.stop_lane:
                return
            if outcome.executed:
                executions += 1

    async def _attempt(
        self, character_id: str, lane: Lane, command: SubmittedCommand
    ) -> _LaneOutcome:
        entity_id = parse_entity_id(character_id)
        if entity_id is None or not self.world.has_entity(entity_id):
            self.queues.pop(character_id, lane)
            await self._reject(command, "character does not exist")
            return _LaneOutcome(executed=False, stop_lane=False)
        character = self.world.get_entity(entity_id)

        # Expiry.
        if command.expires_at_epoch is not None and self.epoch > command.expires_at_epoch:
            self.queues.pop(character_id, lane)
            await self._publish(
                CommandExpiredEvent(
                    **self._event_base(
                        actor_id=character_id,
                        command_id=command.command_id,
                        command_type=command.command_type,
                        payload=dict(command.payload),
                    )
                )
            )
            return _LaneOutcome(executed=False, stop_lane=False)

        # Control verbs change the controller itself, so they bypass generation,
        # cost, and participation gates (but never apply to the dead).
        if command.command_type in CONTROL_COMMANDS:
            self.queues.pop(character_id, lane)
            if character.has_component(DeadComponent):
                await self._reject(command, "character is dead")
                return _LaneOutcome(executed=False, stop_lane=False)
            applied, reason = await self._apply_control(entity_id, command)
            if not applied:
                await self._reject(command, reason)
                return _LaneOutcome(executed=False, stop_lane=False)
            await self._publish(
                CommandExecutedEvent(
                    **self._event_base(
                        actor_id=character_id,
                        command_id=command.command_id,
                        command_type=command.command_type,
                    )
                )
            )
            return _LaneOutcome(executed=True, stop_lane=False)

        # Stale controller generation (spec 7.3).
        if not self._generation_current(character, command):
            self.queues.pop(character_id, lane)
            await self._reject(command, "stale controller generation")
            return _LaneOutcome(executed=False, stop_lane=False)

        # Dead / suspended characters cannot act.
        if character.has_component(DeadComponent):
            self.queues.pop(character_id, lane)
            await self._reject(command, "character is dead")
            return _LaneOutcome(executed=False, stop_lane=False)
        if character.has_component(SuspendedComponent):
            self.queues.pop(character_id, lane)
            await self._reject(command, "character is suspended")
            return _LaneOutcome(executed=False, stop_lane=False)
        if character.has_component(DownedComponent):
            self.queues.pop(character_id, lane)
            await self._reject(command, "character is downed")
            return _LaneOutcome(executed=False, stop_lane=False)
        # Asleep characters may only wake (spec 11.11, 19).
        if (
            character.has_component(SleepingComponent)
            and command.command_type != WakeHandler.command_type
        ):
            self.queues.pop(character_id, lane)
            await self._reject(command, "character is asleep")
            return _LaneOutcome(executed=False, stop_lane=False)

        # Policy gates (spec 20): a forbidden action is rejected outright, before any cost.
        for gate in self._gates:
            allowed, reason = gate(self.world, command)
            if not allowed:
                self.queues.pop(character_id, lane)
                await self._reject(command, reason or "not allowed by policy")
                return _LaneOutcome(executed=False, stop_lane=False)

        # Affordability (points are checked, but spent only on handler success).
        if not self._affordable(character, command):
            if command.on_insufficient_points is OnInsufficientPoints.DENY:
                self.queues.pop(character_id, lane)
                await self._reject(command, "insufficient points")
                return _LaneOutcome(executed=False, stop_lane=False)
            # QUEUE: wait for regen. FIFO means we cannot skip ahead.
            return _LaneOutcome(executed=False, stop_lane=True)

        handler = self._handlers.get(command.command_type)
        if handler is None:
            self.queues.pop(character_id, lane)
            await self._reject(command, f"no handler for {command.command_type}")
            return _LaneOutcome(executed=False, stop_lane=False)

        # Execute. Points are spent only if the handler succeeds.
        ctx = HandlerContext(world=self.world, epoch=self.epoch)
        result = handler.execute(ctx, command)
        self.queues.pop(character_id, lane)
        if not result.ok:
            await self._reject(command, result.reason or "rejected by handler")
            return _LaneOutcome(executed=False, stop_lane=False)

        result_events = tuple(
            {"event_type": event.__class__.__name__, **event.model_dump(mode="json")}
            for event in result.events
        )
        await self._spend(character, command)
        await self._publish(
            CommandExecutedEvent(
                **self._event_base(
                    actor_id=character_id,
                    command_id=command.command_id,
                    command_type=command.command_type,
                    payload=dict(command.payload),
                    result_events=result_events,
                )
            )
        )
        for event in result.events:
            await self._publish(event)
        return _LaneOutcome(executed=True, stop_lane=False)

    # -- validation helpers -------------------------------------------------------------

    def current_generation(self, character_id: EntityId, controller_id: EntityId) -> int | None:
        """Return the live ``ControlledBy`` generation for a character/controller pair."""
        character = self.world.get_entity(character_id)
        for edge, target_id in character.get_relationships(ControlledBy):
            if target_id == controller_id:
                return edge.generation
        return None

    def _generation_current(self, character, command: SubmittedCommand) -> bool:
        controller_id = parse_entity_id(command.controller_id)
        if controller_id is None:
            return False
        for edge, target_id in character.get_relationships(ControlledBy):
            if target_id == controller_id:
                return edge.generation == command.controller_generation
        return False

    def _affordable(self, character, command: SubmittedCommand) -> bool:
        action_have = (
            character.get_component(ActionPointsComponent).current
            if character.has_component(ActionPointsComponent)
            else 0.0
        )
        focus_have = (
            character.get_component(FocusPointsComponent).current
            if character.has_component(FocusPointsComponent)
            else 0.0
        )
        return action_have >= command.cost.action and focus_have >= command.cost.focus

    async def _spend(self, character, command: SubmittedCommand) -> None:
        if command.cost.action and character.has_component(ActionPointsComponent):
            ap = character.get_component(ActionPointsComponent)
            replace_component(character, replace(ap, current=ap.current - command.cost.action))
            updated = character.get_component(ActionPointsComponent)
            await self._publish(
                ActionPointsChangedEvent(
                    **self._event_base(
                        actor_id=command.character_id,
                        current=updated.current,
                        maximum=updated.maximum,
                    )
                )
            )
        if command.cost.focus and character.has_component(FocusPointsComponent):
            fp = character.get_component(FocusPointsComponent)
            replace_component(character, replace(fp, current=fp.current - command.cost.focus))
            updated = character.get_component(FocusPointsComponent)
            await self._publish(
                FocusPointsChangedEvent(
                    **self._event_base(
                        actor_id=command.character_id,
                        current=updated.current,
                        maximum=updated.maximum,
                    )
                )
            )

    # -- controller management ----------------------------------------------------------

    def assign_controller(self, character_id: EntityId, controller_id: EntityId) -> int:
        """Point a character's ``ControlledBy`` edge at a controller, bumping generation.

        Returns the new generation. Any commands queued under the old controller are
        flushed (spec 7.4).
        """
        character = self.world.get_entity(character_id)
        next_generation = 0
        for edge, target_id in character.get_relationships(ControlledBy):
            next_generation = max(next_generation, edge.generation + 1)
            character.remove_relationship(ControlledBy, target_id)
        character.add_relationship(
            ControlledBy(generation=next_generation, since_epoch=self.epoch), controller_id
        )
        self.queues.flush_character(str(character_id))
        return next_generation

    def suspend(
        self, character_id: EntityId, controller_id: EntityId, reason: str = "offline"
    ) -> int:
        """Suspend a character: add the marker and assign the no-op controller (spec 7.7)."""
        generation = self.assign_controller(character_id, controller_id)
        character = self.world.get_entity(character_id)
        replace_component(
            character, SuspendedComponent(reason=reason, suspended_at_epoch=self.epoch)
        )
        controller = self.world.get_entity(controller_id)
        if not controller.has_component(SuspendedControllerComponent):
            controller.add_component(SuspendedControllerComponent(reason=reason))
        return generation

    def _controller_kind(self, controller_id: EntityId) -> str:
        controller = self.world.get_entity(controller_id)
        if controller.has_component(DiscordControllerComponent):
            return "discord"
        if controller.has_component(LLMControllerComponent):
            return "llm"
        if controller.has_component(MCPControllerComponent):
            return "mcp"
        if controller.has_component(SuspendedControllerComponent):
            return "suspended"
        return "unknown"

    async def _apply_control(
        self, character_id: EntityId, command: SubmittedCommand
    ) -> tuple[bool, str]:
        """Apply a control verb. Returns (applied, reject_reason)."""
        controller_id = parse_entity_id(command.payload.get("controller_id"))
        if controller_id is None or not self.world.has_entity(controller_id):
            return False, "controller does not exist"

        if command.command_type == "suspend":
            reason = str(command.payload.get("reason", "offline"))
            generation = self.suspend(character_id, controller_id, reason=reason)
            kind = "suspended"
        else:
            # take-control / release-to-llm / resume -> an active controller.
            generation = self.assign_controller(character_id, controller_id)
            character = self.world.get_entity(character_id)
            if character.has_component(SuspendedComponent):
                character.remove_component(SuspendedComponent)
            kind = self._controller_kind(controller_id)

        await self._publish(
            ControllerChangedEvent(
                **self._event_base(
                    actor_id=str(character_id),
                    generation=generation,
                    controller_kind=kind,
                )
            )
        )
        return True, ""

    # -- events -------------------------------------------------------------------------

    def _event_base(self, **kwargs) -> dict:
        from datetime import UTC, datetime
        from uuid import uuid4

        base = {
            "event_id": uuid4().hex,
            "world_epoch": self.epoch,
            "created_at": datetime.now(UTC),
        }
        base.update(kwargs)
        return base

    async def _publish(self, event: DomainEvent) -> None:
        await self.bus.publish(event)

    async def _reject(self, command: SubmittedCommand, reason: str) -> None:
        await self._publish(
            CommandRejectedEvent(
                **self._event_base(
                    actor_id=command.character_id,
                    command_id=command.command_id,
                    command_type=command.command_type,
                    reason=reason,
                )
            )
        )


__all__ = ["WorldActor"]
