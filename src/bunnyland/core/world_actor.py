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
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from relics import EntityId, World

from .. import telemetry
from .actions import (
    ActionDefinition,
)
from .availability import (
    affordable,
    lifecycle_block_reason,
    meets_requirement,
)
from .claim_timeout import record_claim_activity
from .commands import (
    CommitReceipt,
    CommitStatus,
    Lane,
    OnInsufficientPoints,
    SubmittedCommand,
)
from .components import (
    ActionPointsComponent,
    CharacterComponent,
    DeadComponent,
    DownedComponent,
    FocusPointsComponent,
    InitiativeComponent,
    RoomComponent,
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
    BehaviorControllerComponent,
    ClaimTimeoutComponent,
    DiscordControllerComponent,
    LLMControllerComponent,
    MCPControllerComponent,
    ScriptedControllerComponent,
    SuspendedControllerComponent,
    WebControllerComponent,
)
from .ecs import container_of, ensure_blank_prefab, parse_entity_id, spawn_entity
from .edges import ControlledBy, KnowsRoom
from .events import (
    ActionPointsChangedEvent,
    CharacterClaimedEvent,
    CommandCancelledEvent,
    CommandExecutedEvent,
    CommandExpiredEvent,
    CommandQueuedEvent,
    CommandRejectedEvent,
    CommandSubmittedEvent,
    ControllerChangedEvent,
    DomainEvent,
    EventBus,
    FocusPointsChangedEvent,
    event_base,
)
from .handlers import CommandHandler, HandlerContext
from .handlers.lifecycle import WakeHandler
from .mutations import (
    AddComponent,
    AddEdge,
    MutationPlan,
    RemoveComponent,
    RemoveEdge,
    SetComponent,
    execute_mutation_plan,
    world_transaction,
)
from .perspective import PerspectiveQueryRegistry
from .queue import CommandQueues
from .systems import ActionFocusRegenSystem, WorldClockSystem

#: Control verbs change the controller itself (spec 7.4); they carry no point cost and
#: bypass generation/participation gates so handoff and resume always work.
CONTROL_COMMANDS = frozenset({"take-control", "release-to-llm", "suspend", "resume"})

#: A policy gate inspects a command against the world and returns ``(allowed, reason)``.
CommandGate = Callable[[World, SubmittedCommand], tuple[bool, "str | None"]]
AfterTickHook = Callable[["WorldActor"], None | Awaitable[None]]


@dataclass(frozen=True)
class SubmissionOutcome:
    """Result of submitting a command: accepted for ingestion or rejected outright."""

    accepted: bool
    command_id: str
    reason: str = ""
    receipt: CommitReceipt | None = None


@dataclass(frozen=True)
class _LaneOutcome:
    """Result of attempting the command at the front of a lane."""

    executed: bool
    stop_lane: bool  # leave remaining commands queued (insufficient points, waiting)


@dataclass
class WorldPersistenceContext:
    """Runtime persistence wiring used by actor-bound plugin handlers."""

    save_path: str | Path | None = None
    meta: Any | None = None
    plugins: tuple[Any, ...] = ()
    plugin_context: Any | None = None


class WorldActor:
    """Owns the Relics world and serializes all mutations through ticks."""

    def __init__(
        self,
        world: World | None = None,
        *,
        rng: random.Random | None = None,
        receipt_cache_size: int = 1000,
    ) -> None:
        self.world = world or World()
        ensure_blank_prefab(self.world)
        self.bus = EventBus(reaction_transaction=lambda: world_transaction(self.world))
        self.queues = CommandQueues()
        self._handlers: dict[str, list[CommandHandler]] = {}
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
        #: Lazily-built ``command_type -> merged definition`` map for submit validation.
        self._definition_cache: dict[str, ActionDefinition] | None = None
        self._inbox: asyncio.Queue[SubmittedCommand] = asyncio.Queue()
        self._rng = rng or random.Random()
        self._submission_sequence = 0
        self._receipt_cache_size = receipt_cache_size
        self._receipts: OrderedDict[str, CommitReceipt] = OrderedDict()
        self._lock = asyncio.Lock()
        self.persistence = WorldPersistenceContext()
        self.world_id = ""
        #: Populated by the plugin loader without making core import plugin modules.
        self.plugins: Any | None = None
        #: Prompt providers are registered by the plugin loader. Core handlers access them
        #: through ``project_prompt_facts`` without importing plugin-owned mechanics.
        self.prompt_fragment_providers: tuple[Any, ...] = ()
        self.perspective_queries = PerspectiveQueryRegistry()

        self.world.register_system(WorldClockSystem())
        self.world.register_system(ActionFocusRegenSystem())

        # World singleton holds the authoritative clock.
        self._clock_entity = spawn_entity(self.world, [WorldClockComponent()])

    # -- registration -------------------------------------------------------------------

    def register_handler(self, handler: CommandHandler) -> None:
        self._handlers.setdefault(handler.command_type, []).append(handler)

    def register_action_definition(self, definition: ActionDefinition) -> None:
        self._action_definitions[definition.command_type] = definition
        self._definition_cache = None

    def action_definitions(self) -> tuple[ActionDefinition, ...]:
        return tuple(self._action_definitions.values())

    def project_prompt_facts(self, entity, *, viewer, cutoff: int):
        """Project registered component facts with the requested disclosure cutoff."""
        from ..prompts.facts import collect_prompt_facts

        return collect_prompt_facts(
            self.world,
            entity,
            self.prompt_fragment_providers,
            cutoff=cutoff,
            viewer=viewer,
        )

    def register_consequence(self, consequence: Consequence) -> None:
        """Add a post-command consequence pass (spec 5.6 phase 6)."""
        self._consequences.append(consequence)

    def register_gate(self, gate: CommandGate) -> None:
        """Add a policy gate that can veto a command before it executes (spec 20)."""
        self._gates.append(gate)

    def register_after_tick(self, hook: AfterTickHook) -> None:
        """Run ``hook`` at the end of every tick while the actor owns the world lock."""
        self._after_tick.append(hook)

    def configure_persistence(
        self,
        *,
        save_path: str | Path | None,
        meta: Any | None,
        plugins: tuple[Any, ...] = (),
        plugin_context: Any | None = None,
    ) -> None:
        self.persistence = WorldPersistenceContext(
            save_path=save_path,
            meta=meta,
            plugins=tuple(plugins),
            plugin_context=plugin_context,
        )

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

    async def submit(self, command: SubmittedCommand) -> SubmissionOutcome:
        """Queue a command for ingestion on the next tick. Never mutates the world.

        This is the single submission chokepoint for every source (API, MCP, Discord, and
        the autonomous dispatch), so the ``command.submit`` span here ties a queued command
        back to whatever trace originated it (an HTTP request span, ``controller.run_once``,
        etc.).

        Obviously-invalid commands (no handler, can't act, missing required arguments,
        invalid/unreachable target, unmet capability, or unaffordable under DENY) are
        rejected synchronously here instead of being queued to fail at the next tick. The
        handler at ``_attempt`` remains the final arbiter for everything else.
        """
        with telemetry.span(
            "command.submit",
            {
                "command.type": command.command_type,
                "command.id": command.command_id,
                "character.id": command.character_id,
                "command.lane": command.lane.value,
            },
        ) as span:
            try:
                receipt = self._receipts.get(command.command_id)
                if receipt is not None:
                    self._receipts.move_to_end(command.command_id)
                    return SubmissionOutcome(
                        accepted=receipt.status is CommitStatus.COMMITTED,
                        command_id=command.command_id,
                        reason=receipt.reason,
                        receipt=receipt,
                    )
                if self._command_pending(command.command_id):
                    return SubmissionOutcome(accepted=True, command_id=command.command_id)
                self._submission_sequence += 1
                object.__setattr__(command, "submission_sequence", self._submission_sequence)
                reason = self._validate_submission(command)
                if reason is not None:
                    span.set_attribute("command.accepted", False)
                    span.set_attribute("command.reject_reason_text", reason)
                    telemetry.mark_span_error(reason, span)
                    await self._reject(command, reason)
                    return SubmissionOutcome(
                        accepted=False, command_id=command.command_id, reason=reason
                    )
                await self._inbox.put(command)
                span.set_attribute("command.accepted", True)
                telemetry.mark_span_ok(span)
                return SubmissionOutcome(accepted=True, command_id=command.command_id)
            except Exception as exc:
                span.record_exception(exc)
                telemetry.mark_span_error(str(exc), span)
                raise

    def _command_pending(self, command_id: str) -> bool:
        if any(command.command_id == command_id for command in self.pending_submissions()):
            return True
        return any(
            command.command_id == command_id
            for character_id in self.queues.characters_with_pending()
            for command in self.queues.pending(character_id)
        )

    def receipt_for(self, command_id: str) -> CommitReceipt | None:
        """Return a terminal receipt while it remains in the bounded retry cache."""

        return self._receipts.get(command_id)

    def _record_receipt(
        self,
        command: SubmittedCommand,
        status: CommitStatus,
        *,
        reason: str = "",
        event_ids: tuple[str, ...] = (),
    ) -> CommitReceipt:
        receipt = CommitReceipt(
            command_id=command.command_id,
            character_id=command.character_id,
            command_type=command.command_type,
            status=status,
            submitted_at_epoch=command.submitted_at_epoch,
            committed_at_epoch=self.epoch,
            submission_sequence=command.submission_sequence,
            reason=reason,
            event_ids=event_ids,
        )
        with telemetry.span(
            "command.receipt",
            {
                "command.id": receipt.command_id,
                "command.type": receipt.command_type,
                "character.id": receipt.character_id,
                "command.status": receipt.status.value,
                "command.result_text": receipt.reason,
                "command.result_event_ids": receipt.event_ids,
                "command.committed_epoch": receipt.committed_at_epoch,
            },
        ) as receipt_span:
            telemetry.mark_span_ok(receipt_span)
        self._receipts[command.command_id] = receipt
        self._receipts.move_to_end(command.command_id)
        while len(self._receipts) > self._receipt_cache_size:
            self._receipts.popitem(last=False)
        if self.persistence.save_path is not None:
            from ..persistence import OperationalJournal

            OperationalJournal(self.persistence.save_path).append(
                "command_receipt",
                receipt=receipt,
                mutation_summary={"event_count": len(event_ids)},
                event_range={
                    "first": event_ids[0] if event_ids else None,
                    "last": event_ids[-1] if event_ids else None,
                },
                rng_stream_state={"command_order": self._rng.getstate()},
                world_epoch=self.epoch,
            )
        return receipt

    def _definition_for(self, command_type: str) -> ActionDefinition | None:
        if self._definition_cache is None:
            self._definition_cache = {
                definition.command_type: definition for definition in self.action_definitions()
            }
        return self._definition_cache.get(command_type)

    def _validate_submission(self, command: SubmittedCommand) -> str | None:
        """Return a rejection reason for an obviously-invalid command, else ``None``.

        Conservative on purpose: it never rejects for transient reasons that the tick
        pipeline legitimately defers (affordability under QUEUE waits for regen; stale
        generation and fine-grained handler gates resolve at tick).
        """

        entity_id = parse_entity_id(command.character_id)
        if entity_id is None or not self.world.has_entity(entity_id):
            return "character does not exist"
        # Control verbs change the controller itself and bypass the action gates.
        if command.command_type in CONTROL_COMMANDS:
            return None
        if command.command_type not in self._handlers:
            return f"no handler for {command.command_type}"

        character = self.world.get_entity(entity_id)
        block = lifecycle_block_reason(character, command.command_type)
        if block is not None:
            return block
        for gate in self._gates:
            allowed, reason = gate(self.world, command)
            if not allowed:
                return reason or "not allowed by policy"

        definition = self._definition_for(command.command_type)
        if definition is None:
            return f"no action definition for {command.command_type}"
        if not meets_requirement(self.world, character, definition.requirement):
            return "missing a required skill or item"
        argument_reason = self._validate_arguments(definition, command.payload)
        if argument_reason is not None:
            return argument_reason

        enough_action, enough_focus = affordable(character, command.cost)
        if not (enough_action and enough_focus):
            if command.on_insufficient_points is OnInsufficientPoints.DENY:
                return "insufficient points"
        return None

    def _validate_arguments(
        self, definition: ActionDefinition, payload: Mapping[str, Any]
    ) -> str | None:
        """Reject only *structural* argument problems (a missing required argument).

        Target existence and reachability are intentionally left to the handler at tick:
        they are state-dependent (a queued command's target can become reachable before
        the tick that runs it) and some handlers define a broader reachability than the
        generic room+inventory set (e.g. buying an item out of a shop's stock).
        """

        for key, argument in (definition.arguments or {}).items():
            value = payload.get(key)
            if argument.required and (
                value is None or (isinstance(value, str) and not value.strip())
            ):
                return f"missing required argument: {key}"
        return None

    def submit_nowait(self, command: SubmittedCommand) -> None:
        self._inbox.put_nowait(command)

    def pending_submissions(self) -> list[SubmittedCommand]:
        """Return commands accepted for ingestion on the next tick."""

        return list(self._inbox._queue)

    async def cancel_command(self, character_id: str, command_id: str) -> SubmittedCommand | None:
        """Remove one queued command for a character by id, from inbox or lane queues."""

        async with self._lock:
            for index, command in enumerate(list(self._inbox._queue)):
                if command.character_id == character_id and command.command_id == command_id:
                    del self._inbox._queue[index]
                    await self._publish_cancelled(command)
                    return command
            command = self.queues.remove(character_id, command_id)
            if command is not None:
                await self._publish_cancelled(command)
            return command

    async def _publish_cancelled(self, command: SubmittedCommand) -> None:
        event = CommandCancelledEvent(
            **self._event_base(
                actor_id=command.character_id,
                command_id=command.command_id,
                command_type=command.command_type,
                lane=command.lane.value,
            )
        )
        await self._publish(event)
        self._record_receipt(
            command, CommitStatus.CANCELLED, reason="cancelled", event_ids=(event.event_id,)
        )

    # -- tick pipeline ------------------------------------------------------------------

    async def tick(self, game_delta_seconds: float) -> None:
        """Run one deterministic world tick (spec 5.6)."""
        with (
            telemetry.record_duration(telemetry.record_tick),
            telemetry.span(
                "game.tick", {"tick.game_delta_seconds": game_delta_seconds}
            ) as tick_span,
        ):
            self.bus.begin_transaction()
            try:
                async with self._lock:
                    # Deliver work deferred by the prior tick before producing new events.
                    await self.bus.drain()
                    # Phase 1: drain the inbox into the per-character lanes.
                    with telemetry.span("tick.ingest"):
                        await self._ingest()
                    # Phases 2-4: advance clock, regen Action/Focus, run passive systems.
                    with telemetry.span("tick.systems"):
                        with world_transaction(self.world):
                            self.world.tick(game_delta_seconds)
                            self._reconcile_room_knowledge()
                    tick_span.set_attribute("tick.epoch", self.epoch)
                    # Phase 5: process queued commands in initiative order.
                    with telemetry.span("tick.commands"):
                        await self._process_commands()
                    # Phase 6: consequence systems (downed/death transitions, etc.).
                    with telemetry.span("tick.consequences"):
                        await self._run_consequences()
                    with telemetry.span("tick.after_tick"):
                        await self._run_after_tick()
            finally:
                await self.bus.end_transaction()

    async def _run_consequences(self) -> None:
        events: list[DomainEvent] = []
        with world_transaction(self.world):
            for consequence in self._consequences:
                events.extend(consequence.process(self.world, self.epoch))
        for event in events:
            await self._publish(event)

    async def _run_after_tick(self) -> None:
        for hook in self._after_tick:
            with world_transaction(self.world):
                result = hook(self)
                if inspect.isawaitable(result):
                    await result

    async def _ingest(self) -> None:
        while not self._inbox.empty():
            command = self._inbox.get_nowait()
            self._record_controller_activity(command)
            self.queues.enqueue(command)
            telemetry.record_command_submitted(command.command_type)
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

    def _record_controller_activity(self, command: SubmittedCommand) -> None:
        controller_id = parse_entity_id(command.controller_id)
        character_id = parse_entity_id(command.character_id)
        if (
            controller_id is None
            or character_id is None
            or not self.world.has_entity(controller_id)
            or not self.world.has_entity(character_id)
        ):
            return
        controller = self.world.get_entity(controller_id)
        if not controller.has_component(ClaimTimeoutComponent):
            return
        if self.current_generation(character_id, controller_id) != command.controller_generation:
            return
        record_claim_activity(controller, now_unix=int(time.time()))

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

        # Submission chronology is the recorded tie-break. Character id is a stable final
        # key for empty queues and legacy commands with sequence zero.
        def oldest(cid: str) -> tuple[int, int]:
            pending = self.queues.pending(cid)
            if not pending:
                return (0, 0)
            command = min(
                pending,
                key=lambda item: (item.submitted_at_epoch, item.submission_sequence),
            )
            return (command.submitted_at_epoch, command.submission_sequence)

        return sorted(character_ids, key=lambda cid: (-key(cid), *oldest(cid), cid))

    async def _drain_lane(
        self, character_id: str, lane: Lane, *, max_executions: int | None
    ) -> None:
        executions = 0
        while max_executions is None or executions < max_executions:
            command = self.queues.peek(character_id, lane)
            if command is None:
                return
            with telemetry.span(
                "command.attempt",
                {
                    "command.type": command.command_type,
                    "command.lane": lane.value,
                    "command.id": command.command_id,
                    "character.id": character_id,
                },
            ) as attempt_span:
                outcome = await self._attempt(character_id, lane, command)
                attempt_span.set_attribute("command.executed", outcome.executed)
                attempt_span.set_attribute("command.queued", outcome.stop_lane)
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
            telemetry.set_span_attributes({"command.outcome": "expired"})
            event = CommandExpiredEvent(
                **self._event_base(
                    actor_id=character_id,
                    command_id=command.command_id,
                    command_type=command.command_type,
                    payload=dict(command.payload),
                )
            )
            await self._publish(event)
            self._record_receipt(
                command, CommitStatus.EXPIRED, reason="expired", event_ids=(event.event_id,)
            )
            return _LaneOutcome(executed=False, stop_lane=False)

        if command.expected_epoch is not None and command.expected_epoch != self.epoch:
            self.queues.pop(character_id, lane)
            await self._reject(command, "world epoch changed")
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
            executed_event = CommandExecutedEvent(
                **self._event_base(
                    actor_id=character_id,
                    command_id=command.command_id,
                    command_type=command.command_type,
                )
            )
            await self._publish(executed_event)
            self._record_receipt(
                command, CommitStatus.COMMITTED, event_ids=(executed_event.event_id,)
            )
            telemetry.record_command_accepted(command.command_type)
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

        handlers = self._handlers.get(command.command_type, [])
        if not handlers:
            self.queues.pop(character_id, lane)
            await self._reject(command, f"no handler for {command.command_type}")
            return _LaneOutcome(executed=False, stop_lane=False)

        # Execute. Points are spent only if the handler succeeds.
        ctx = HandlerContext(
            world=self.world,
            epoch=self.epoch,
            actor=self,
        )
        handler = self._handler_for(ctx, command, handlers)
        if handler is None:
            self.queues.pop(character_id, lane)
            await self._reject(command, f"no handler accepted {command.command_type}")
            return _LaneOutcome(executed=False, stop_lane=False)
        transaction_point_events: tuple[DomainEvent, ...] = ()
        with (
            telemetry.record_duration(
                telemetry.record_handler, {"command_type": command.command_type}
            ),
            telemetry.span(
                "handler.execute",
                {
                    "command.type": command.command_type,
                    "command.id": command.command_id,
                    "character.id": character_id,
                    "handler.kind": type(handler).__name__,
                },
            ) as hspan,
        ):
            result = handler.execute(ctx, command)
            if result.ok and result.plan is None:
                result = replace(
                    result,
                    ok=False,
                    reason="handler returned success without a mutation plan",
                )
            if result.ok:
                assert result.plan is not None
                combined = MutationPlan(
                    operations=(
                        *result.plan.operations,
                        *self._cost_operations(character, command),
                    ),
                    invariants=result.plan.invariants,
                )
                try:
                    _summary, built = execute_mutation_plan(
                        self.world,
                        combined,
                        after_apply=lambda: (
                            tuple(factory() for factory in result.event_factories),
                            self._point_events(character, command),
                        ),
                    )
                except Exception as exc:  # noqa: BLE001 - transaction rejects atomically.
                    self.queues.pop(character_id, lane)
                    await self._reject(command, f"mutation failed: {exc}")
                    return _LaneOutcome(executed=False, stop_lane=False)
                deferred_events, transaction_point_events = built
                result = replace(
                    result,
                    events=(*result.events, *deferred_events),
                    plan=combined,
                    event_factories=(),
                )
            hspan.set_attribute("handler.ok", result.ok)
            if not result.ok and result.reason:
                hspan.set_attribute("handler.reason", telemetry.attr_text(result.reason))
            hspan.set_attribute("handler.event_count", len(result.events))
        self.queues.pop(character_id, lane)
        if not result.ok:
            await self._reject(command, result.reason or "rejected by handler")
            return _LaneOutcome(executed=False, stop_lane=False)

        result_events = tuple(
            {
                "event_type": event.__class__.__name__,
                **event.model_dump(mode="json"),
            }
            for event in result.events
        )
        for event in transaction_point_events:
            await self._publish(event)
        executed_event = CommandExecutedEvent(
            **self._event_base(
                actor_id=character_id,
                command_id=command.command_id,
                command_type=command.command_type,
                payload=dict(command.payload),
                result_events=result_events,
            )
        )
        await self._publish(executed_event)
        telemetry.record_command_accepted(command.command_type)
        for event in result.events:
            await self._publish(event)
        with world_transaction(self.world):
            self._reconcile_room_knowledge(character)
        self._record_receipt(
            command,
            CommitStatus.COMMITTED,
            event_ids=(
                *(event.event_id for event in transaction_point_events),
                executed_event.event_id,
                *(event.event_id for event in result.events),
            ),
        )
        return _LaneOutcome(executed=True, stop_lane=False)

    def _reconcile_room_knowledge(self, character=None) -> None:
        """Persist rooms directly perceived now; current perception wins stale labels."""

        characters = (
            (character,)
            if character is not None
            else self.world.query().with_all([CharacterComponent]).execute_entities()
        )
        for candidate in characters:
            room_id = container_of(candidate)
            if room_id is None or not self.world.has_entity(room_id):
                continue
            room = self.world.get_entity(room_id)
            if not room.has_component(RoomComponent):
                continue
            label = room.get_component(RoomComponent).title
            previous = next(
                (
                    edge
                    for edge, target in candidate.get_relationships(KnowsRoom)
                    if target == room_id
                ),
                None,
            )
            first_seen = previous.first_seen_epoch if previous is not None else self.epoch
            candidate.add_relationship(
                KnowsRoom(
                    first_seen_epoch=first_seen,
                    last_seen_epoch=self.epoch,
                    remembered_label=label,
                ),
                room_id,
            )

    def _handler_for(
        self,
        ctx: HandlerContext,
        command: SubmittedCommand,
        handlers: list[CommandHandler],
    ) -> CommandHandler | None:
        """Pick the most recently registered handler whose predicate accepts the command."""

        for handler in reversed(handlers):
            can_handle = getattr(handler, "can_handle", None)
            if can_handle is None or can_handle(ctx, command):
                return handler
        return None

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
        enough_action, enough_focus = affordable(character, command.cost)
        return enough_action and enough_focus

    def _cost_operations(self, character, command: SubmittedCommand) -> tuple[SetComponent, ...]:
        operations = []
        if command.cost.action and character.has_component(ActionPointsComponent):
            points = character.get_component(ActionPointsComponent)
            operations.append(
                SetComponent(
                    character.id,
                    replace(points, current=points.current - command.cost.action),
                )
            )
        if command.cost.focus and character.has_component(FocusPointsComponent):
            points = character.get_component(FocusPointsComponent)
            operations.append(
                SetComponent(
                    character.id,
                    replace(points, current=points.current - command.cost.focus),
                )
            )
        return tuple(operations)

    def _point_events(self, character, command: SubmittedCommand) -> tuple[DomainEvent, ...]:
        events: list[DomainEvent] = []
        if command.cost.action and character.has_component(ActionPointsComponent):
            points = character.get_component(ActionPointsComponent)
            events.append(
                ActionPointsChangedEvent(
                    **self._event_base(
                        actor_id=command.character_id,
                        current=points.current,
                        maximum=points.maximum,
                    )
                )
            )
        if command.cost.focus and character.has_component(FocusPointsComponent):
            points = character.get_component(FocusPointsComponent)
            events.append(
                FocusPointsChangedEvent(
                    **self._event_base(
                        actor_id=command.character_id,
                        current=points.current,
                        maximum=points.maximum,
                    )
                )
            )
        return tuple(events)

    # -- controller management ----------------------------------------------------------

    def assign_controller(self, character_id: EntityId, controller_id: EntityId) -> int:
        """Point a character's ``ControlledBy`` edge at a controller, bumping generation.

        Returns the new generation. Any commands queued under the old controller are
        flushed (spec 7.4).
        """
        character = self.world.get_entity(character_id)
        next_generation = 0
        operations = []
        for edge, target_id in character.get_relationships(ControlledBy):
            next_generation = max(next_generation, edge.generation + 1)
            operations.append(RemoveEdge(character_id, target_id, ControlledBy))
        operations.append(
            AddEdge(
                character_id,
                controller_id,
                ControlledBy(generation=next_generation, since_epoch=self.epoch),
            )
        )
        execute_mutation_plan(self.world, MutationPlan(tuple(operations)))
        self.queues.flush_character(str(character_id))
        return next_generation

    def suspend(
        self, character_id: EntityId, controller_id: EntityId, reason: str = "offline"
    ) -> int:
        """Suspend a character: add the marker and assign the no-op controller (spec 7.7)."""
        character = self.world.get_entity(character_id)
        controller = self.world.get_entity(controller_id)
        generation = max(
            (edge.generation + 1 for edge, _ in character.get_relationships(ControlledBy)),
            default=0,
        )
        operations = [
            *(
                RemoveEdge(character_id, target_id, ControlledBy)
                for _, target_id in character.get_relationships(ControlledBy)
            ),
            AddEdge(
                character_id,
                controller_id,
                ControlledBy(generation=generation, since_epoch=self.epoch),
            ),
            SetComponent(
                character_id,
                SuspendedComponent(reason=reason, suspended_at_epoch=self.epoch),
            ),
        ]
        if not controller.has_component(SuspendedControllerComponent):
            operations.append(
                AddComponent(controller_id, SuspendedControllerComponent(reason=reason))
            )
        execute_mutation_plan(self.world, MutationPlan(tuple(operations)))
        self.queues.flush_character(str(character_id))
        return generation

    def _controller_kind(self, controller_id: EntityId) -> str:
        controller = self.world.get_entity(controller_id)
        if controller.has_component(DiscordControllerComponent):
            return "discord"
        if controller.has_component(LLMControllerComponent):
            return "llm"
        if controller.has_component(MCPControllerComponent):
            return "mcp"
        if controller.has_component(BehaviorControllerComponent):
            return "behavioral"
        if controller.has_component(ScriptedControllerComponent):
            return "scripted"
        if controller.has_component(WebControllerComponent):
            return "web"
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
            character = self.world.get_entity(character_id)
            generation = max(
                (edge.generation + 1 for edge, _ in character.get_relationships(ControlledBy)),
                default=0,
            )
            operations = [
                *(
                    RemoveEdge(character_id, target_id, ControlledBy)
                    for _, target_id in character.get_relationships(ControlledBy)
                ),
                AddEdge(
                    character_id,
                    controller_id,
                    ControlledBy(generation=generation, since_epoch=self.epoch),
                ),
            ]
            if character.has_component(SuspendedComponent):
                operations.append(RemoveComponent(character_id, SuspendedComponent))
            execute_mutation_plan(self.world, MutationPlan(tuple(operations)))
            self.queues.flush_character(str(character_id))
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
        if command.command_type in {"take-control", "resume"}:
            await self._publish(
                CharacterClaimedEvent(
                    **self._event_base(
                        actor_id=str(character_id),
                        character_id=str(character_id),
                        controller_id=str(controller_id),
                        generation=generation,
                    )
                )
            )
        return True, ""

    # -- events -------------------------------------------------------------------------

    def _event_base(self, **kwargs) -> dict:
        return event_base(self.epoch, **kwargs)

    async def _publish(self, event: DomainEvent) -> None:
        await self.bus.publish(event)

    async def _reject(self, command: SubmittedCommand, reason: str) -> None:
        telemetry.record_command_rejected(command.command_type, reason)
        # Annotate the enclosing command.attempt span with why the command failed.
        telemetry.set_span_attributes(
            {
                "command.outcome": "rejected",
                "command.reject_reason": telemetry._reject_category(reason),
                "command.reject_reason_text": telemetry.attr_text(reason),
            }
        )
        event = CommandRejectedEvent(
            **self._event_base(
                actor_id=command.character_id,
                command_id=command.command_id,
                command_type=command.command_type,
                reason=reason,
            )
        )
        await self._publish(event)
        self._record_receipt(
            command, CommitStatus.REJECTED, reason=reason, event_ids=(event.event_id,)
        )


__all__ = ["WorldActor"]
