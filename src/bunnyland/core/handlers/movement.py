"""Movement verb (spec 13.3)."""

from __future__ import annotations

from collections.abc import Mapping

from relics import Entity, EntityId

from ...projections.room_summary import build_room_facts, render_summary
from ..commands import SubmittedCommand
from ..components import AdminComponent, NoiseComponent, RoomGateComponent
from ..ecs import container_of, parse_entity_id
from ..edges import AllowsMembersOf, ContainmentMode, Contains, ExitTo
from ..events import ActorMovedEvent
from ..mutations import AddEdge, AddEntity, MutationPlan, RemoveEdge
from .base import HandlerContext, HandlerResult, planned, rejected, require_character

_ADULT_LIFE_STAGES = frozenset({"adult", "elder"})


def _is_adult(ctx: HandlerContext, character: Entity) -> bool:
    stage_type = ctx.world._component_types.get("LifeStageComponent")
    if stage_type is None or not character.has_component(stage_type):
        return False
    stage = getattr(character.get_component(stage_type), "stage", "")
    return stage.lower() in _ADULT_LIFE_STAGES


def _is_allowed_member(ctx: HandlerContext, character: Entity, room: Entity) -> bool:
    allowed_groups = {
        target_id for _edge, target_id in room.get_relationships(AllowsMembersOf)
    }
    if not allowed_groups:
        return False
    for edge_name, edge_type in ctx.world._edge_types.items():
        if not edge_name.startswith("MemberOf"):
            continue
        if any(
            target_id in allowed_groups
            for _edge, target_id in character.get_relationships(edge_type)
        ):
            return True
    return False


def _owns_room(ctx: HandlerContext, character_id: EntityId, room: Entity) -> bool:
    owns_home_type = ctx.world._edge_types.get("OwnsHome")
    return owns_home_type is not None and any(
        source_id == character_id
        for source_id, _edge in room.get_incoming_relationships(owns_home_type)
    )


def _is_admin(ctx: HandlerContext, command: SubmittedCommand, character: Entity) -> bool:
    if character.has_component(AdminComponent):
        return True
    controller_id = parse_entity_id(command.controller_id)
    return (
        controller_id is not None
        and ctx.world.has_entity(controller_id)
        and ctx.entity(controller_id).has_component(AdminComponent)
    )


def _entry_rejection_reason(
    ctx: HandlerContext,
    command: SubmittedCommand,
    character_id: EntityId,
    character: Entity,
    room: Entity,
) -> str | None:
    if not room.has_component(RoomGateComponent):
        return None
    gate = room.get_component(RoomGateComponent)
    if gate.adults_only and not _is_adult(ctx, character):
        return gate.rejection_reason
    if gate.members_only and not _is_allowed_member(ctx, character, room):
        return gate.rejection_reason
    if gate.owner_only and not _owns_room(ctx, character_id, room):
        return gate.rejection_reason
    if gate.admin_only and not _is_admin(ctx, command, character):
        return gate.rejection_reason
    return None


class MoveHandler:
    """Move a character along an ``ExitTo`` edge.

    Transfers the character's ``Contains`` parent from the current room to the
    destination room.
    """

    command_type = "move"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        payload: Mapping[str, object] = command.payload
        character_id, character, error = require_character(ctx, command.character_id)
        if error is not None:
            return error
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
        if not ctx.world.has_entity(destination_id):
            return rejected("destination does not exist")
        destination = ctx.entity(destination_id)
        entry_rejection = _entry_rejection_reason(
            ctx,
            command,
            character_id,
            character,
            destination,
        )
        if entry_rejection is not None:
            return rejected(entry_rejection)

        plan = MutationPlan(
            (
                RemoveEdge(current_room_id, character_id, Contains),
                AddEdge(
                    destination_id,
                    character_id,
                    Contains(mode=ContainmentMode.ROOM_CONTENT),
                ),
                AddEntity(
                    (
                        NoiseComponent(
                            loudness=float(payload.get("noise", 1.0)),
                            text="movement",
                            source_entity_id=str(character_id),
                            room_id=str(destination_id),
                            created_at_epoch=ctx.epoch,
                            expires_at_epoch=ctx.epoch + 60,
                        ),
                    )
                ),
            )
        )

        return planned(
            plan,
            lambda: ActorMovedEvent(
                **ctx.event_base(
                    actor_id=str(character_id),
                    room_id=str(destination_id),
                    from_room_id=str(current_room_id),
                    to_room_id=str(destination_id),
                    direction=chosen_direction,
                    arrival_summary=render_summary(build_room_facts(ctx.world, destination_id)),
                )
            ),
        )


__all__ = ["MoveHandler"]
