"""Handler base types (spec sections 13, 23.6).

A handler validates and executes one command type against the world. Handlers run
inside the world actor's command phase. World-state validation (reachability, target
existence) lives in handlers; generation/affordability checks are done by the actor
before dispatch. Handlers return the domain events that resulted, which the actor
publishes; points are spent only when a handler succeeds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from relics import EntityId, World

from ..commands import SubmittedCommand
from ..events import DomainEvent


@dataclass(frozen=True)
class HandlerResult:
    ok: bool
    events: tuple[DomainEvent, ...] = ()
    reason: str = ""


def rejected(reason: str) -> HandlerResult:
    return HandlerResult(ok=False, reason=reason)


def ok(*events: DomainEvent) -> HandlerResult:
    return HandlerResult(ok=True, events=tuple(events))


@dataclass
class HandlerContext:
    """What a handler needs to read and mutate the world during execution."""

    world: World
    epoch: int

    def entity(self, entity_id: EntityId):
        return self.world.get_entity(entity_id)

    def event_base(self, **kwargs: Any) -> dict[str, Any]:
        base = {
            "event_id": uuid4().hex,
            "world_epoch": self.epoch,
            "created_at": datetime.now(UTC),
        }
        base.update(kwargs)
        return base


class CommandHandler(Protocol):
    command_type: str

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult: ...


__all__ = [
    "CommandHandler",
    "HandlerContext",
    "HandlerResult",
    "ok",
    "rejected",
]
