"""Privacy-safe first-session milestone tracking for Apple Crossing."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from relics import EntityId

from .. import telemetry
from ..core.components import IdentityComponent, ReadableComponent, RoomComponent
from ..core.ecs import container_of, parse_entity_id
from ..core.events import CommandExecutedEvent, CommandRejectedEvent, DomainEvent
from ..core.world_actor import WorldActor
from ..foundation.tutorial.mechanics import DELIVERY_MARK


@dataclass(frozen=True)
class OnboardingMilestone:
    name: str
    elapsed_seconds: float
    command_type: str = ""


@dataclass
class _Session:
    started_at: float
    ledger_id: EntityId
    connected: bool = False
    first_useful_action: bool = False
    completed: bool = False


def _record_telemetry(milestone: OnboardingMilestone) -> None:
    attributes: dict[str, str | float] = {
        "tutorial.name": "apple-crossing",
        "tutorial.milestone": milestone.name,
        "tutorial.elapsed_seconds": milestone.elapsed_seconds,
    }
    if milestone.command_type:
        attributes["command.type"] = milestone.command_type
    with telemetry.span("tutorial.onboarding", attributes):
        pass


class OnboardingTracker:
    """Track milestones without retaining player text, credentials, or identifiers."""

    def __init__(
        self,
        actor: WorldActor,
        *,
        clock: Callable[[], float] = time.monotonic,
        record: Callable[[OnboardingMilestone], None] = _record_telemetry,
    ) -> None:
        self._actor = actor
        self._clock = clock
        self._record = record
        self._sessions: dict[str, _Session] = {}
        self._commands: dict[str, str] = {}

    def claimed(self, claim_id: str, character_id: str) -> None:
        ledger_id = self._apple_crossing_ledger(character_id)
        if ledger_id is None or claim_id in self._sessions:
            return
        session = _Session(started_at=self._clock(), ledger_id=ledger_id)
        self._sessions[claim_id] = session
        self.connected(claim_id)
        self._emit(session, "claim")

    def connected(self, claim_id: str) -> None:
        session = self._sessions.get(claim_id)
        if session is not None and not session.connected:
            session.connected = True
            self._emit(session, "connection")

    def command_submitted(self, claim_id: str, command_id: str, command_type: str) -> None:
        session = self._sessions.get(claim_id)
        if session is None:
            return
        self._commands[command_id] = claim_id
        if not session.first_useful_action and command_type not in {"look", "wait"}:
            session.first_useful_action = True
            self._emit(session, "first_useful_action", command_type)

    def record_event(self, event: DomainEvent) -> None:
        if isinstance(event, CommandRejectedEvent):
            claim_id = self._commands.get(event.command_id)
            session = self._sessions.get(claim_id) if claim_id is not None else None
            if session is not None:
                self._emit(session, "rejection", event.command_type)
        if not isinstance(event, CommandExecutedEvent):
            return
        for session in self._sessions.values():
            if session.completed or not self._actor.world.has_entity(session.ledger_id):
                continue
            ledger = self._actor.world.get_entity(session.ledger_id)
            if not ledger.has_component(ReadableComponent):
                continue
            if DELIVERY_MARK in ledger.get_component(ReadableComponent).text:
                session.completed = True
                self._emit(session, "completion")

    def _emit(self, session: _Session, name: str, command_type: str = "") -> None:
        self._record(
            OnboardingMilestone(
                name=name,
                elapsed_seconds=max(0.0, self._clock() - session.started_at),
                command_type=command_type,
            )
        )

    def _apple_crossing_ledger(self, character_id: str) -> EntityId | None:
        parsed = parse_entity_id(character_id)
        if parsed is None or not self._actor.world.has_entity(parsed):
            return None
        character = self._actor.world.get_entity(parsed)
        room_id = container_of(character)
        if room_id is None or not self._actor.world.has_entity(room_id):
            return None
        room = self._actor.world.get_entity(room_id)
        if (
            not room.has_component(RoomComponent)
            or room.get_component(RoomComponent).title != "Apple Crossing"
        ):
            return None
        query = self._actor.world.query().with_all([IdentityComponent, ReadableComponent])
        for entity in query.execute_entities():
            if entity.get_component(IdentityComponent).name == "delivery ledger":
                return entity.id
        return None


__all__ = ["OnboardingMilestone", "OnboardingTracker"]
