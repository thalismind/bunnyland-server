"""Movement verb (spec 13.3)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from relics import EntityId

from ..commands import SubmittedCommand
from ..ecs import container_of, parse_entity_id
from ..edges import ContainmentMode, Contains, ExitTo
from ..events import ActorMovedEvent
from .base import HandlerContext, HandlerResult, ok, rejected


class MoveHandler:
    """Move a character along an ``ExitTo`` edge.

    Transfers the character's ``Contains`` parent from the current room to the
    destination room.
    """

    command_type = "move"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, Any] = command.payload
        character_id = parse_entity_id(command.character_id)
        if character_id is None:
            return rejected("invalid character id")

        character = ctx.entity(character_id)
        current_room_id = container_of(character)
        if current_room_id is None:
            return rejected("character is not in a room")

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
            return rejected("no matching exit")

        # Transfer containment: remove from old room, add to new room.
        current_room.remove_relationship(Contains, character_id)
        destination = ctx.entity(destination_id)
        destination.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), character_id)

        return ok(
            ActorMovedEvent(
                **ctx.event_base(
                    actor_id=str(character_id),
                    room_id=str(destination_id),
                    from_room_id=str(current_room_id),
                    to_room_id=str(destination_id),
                    direction=chosen_direction,
                )
            )
        )


__all__ = ["MoveHandler"]
