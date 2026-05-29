"""Command handlers (spec sections 13, 23.6).

A handler validates and executes one command type against the world. Handlers run
inside the world actor's command phase, after points have been checked and spent.
Validation that depends on world state (reachability, target existence) lives here;
generation/affordability checks are done by the actor before dispatch.

Handlers return the domain events that resulted, which the actor publishes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from relics import EntityId, World

from .commands import SubmittedCommand
from .ecs import container_of, parse_entity_id
from .edges import ContainmentMode, Contains, ExitTo
from .events import ActorMovedEvent, DomainEvent


@dataclass(frozen=True)
class HandlerResult:
    ok: bool
    events: tuple[DomainEvent, ...] = ()
    reason: str = ""


def _rejected(reason: str) -> HandlerResult:
    return HandlerResult(ok=False, reason=reason)


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


class MoveHandler:
    """Move a character along an ``ExitTo`` edge (spec 13.3).

    Transfers the character's ``Contains`` parent from the current room to the
    destination room.
    """

    command_type = "move"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return _rejected("invalid character id")

        character = ctx.entity(character_id)
        current_room_id = container_of(character)
        if current_room_id is None:
            return _rejected("character is not in a room")

        current_room = ctx.entity(current_room_id)
        exits = current_room.get_relationships(ExitTo)

        direction = payload.get("direction")
        target_exit_id = parse_entity_id(payload.get("exit_id"))

        destination_id: EntityId | None = None
        chosen_direction: str | None = None
        for edge, target_id in exits:
            if target_exit_id is not None and target_id == target_exit_id:
                destination_id, chosen_direction = target_id, edge.direction
                break
            if direction is not None and edge.direction == direction:
                destination_id, chosen_direction = target_id, edge.direction
                break

        if destination_id is None:
            return _rejected("no matching exit")

        # Transfer containment: remove from old room, add to new room.
        current_room.remove_relationship(Contains, character_id)
        destination = ctx.entity(destination_id)
        destination.add_relationship(
            Contains(mode=ContainmentMode.ROOM_CONTENT), character_id
        )

        event = ActorMovedEvent(
            **ctx.event_base(
                actor_id=str(character_id),
                room_id=str(destination_id),
                from_room_id=str(current_room_id),
                to_room_id=str(destination_id),
                direction=chosen_direction,
            )
        )
        return HandlerResult(ok=True, events=(event,))


__all__ = [
    "CommandHandler",
    "HandlerContext",
    "HandlerResult",
    "MoveHandler",
]
