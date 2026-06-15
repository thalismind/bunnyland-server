"""Handler base types (spec sections 13, 23.6).

A handler validates and executes one command type against the world. Handlers run
inside the world actor's command phase. World-state validation (reachability, target
existence) lives in handlers; generation/affordability checks are done by the actor
before dispatch. Handlers return the domain events that resulted, which the actor
publishes; points are spent only when a handler succeeds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from relics import EntityId, World

from ..commands import SubmittedCommand
from ..ecs import parse_entity_id, reachable_ids
from ..events import DomainEvent, event_base


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
        return event_base(self.epoch, **kwargs)


def require_entity(
    ctx: HandlerContext,
    raw_id: object,
    *,
    invalid_reason: str,
    missing_reason: str,
) -> tuple[EntityId | None, Any | None, HandlerResult | None]:
    entity_id = parse_entity_id(raw_id)
    if entity_id is None:
        return None, None, rejected(invalid_reason)
    if not ctx.world.has_entity(entity_id):
        return None, None, rejected(missing_reason)
    return entity_id, ctx.entity(entity_id), None


def require_character(
    ctx: HandlerContext,
    raw_id: object,
    *,
    invalid_reason: str = "invalid character id",
    missing_reason: str = "character does not exist",
) -> tuple[EntityId | None, Any | None, HandlerResult | None]:
    return require_entity(
        ctx,
        raw_id,
        invalid_reason=invalid_reason,
        missing_reason=missing_reason,
    )


def require_reachable_entity(
    ctx: HandlerContext,
    character,
    raw_id: object,
    *,
    invalid_reason: str,
    missing_reason: str,
    unreachable_reason: str,
) -> tuple[EntityId | None, Any | None, HandlerResult | None]:
    entity_id = parse_entity_id(raw_id)
    if entity_id is None:
        return None, None, rejected(invalid_reason)
    if not ctx.world.has_entity(entity_id):
        return None, None, rejected(missing_reason)
    if entity_id not in reachable_ids(ctx.world, character):
        return None, None, rejected(unreachable_reason)
    return entity_id, ctx.entity(entity_id), None


class CommandHandler(Protocol):
    command_type: str

    def can_handle(self, ctx: HandlerContext, command: SubmittedCommand) -> bool: ...

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult: ...


__all__ = [
    "CommandHandler",
    "HandlerContext",
    "HandlerResult",
    "ok",
    "rejected",
    "require_character",
    "require_entity",
    "require_reachable_entity",
]
