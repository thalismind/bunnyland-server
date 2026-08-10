"""Sandbox-owned After Dark access mechanics."""

from __future__ import annotations

from dataclasses import replace

from pydantic.dataclasses import dataclass
from relics import Component, Edge

from ..core.commands import SubmittedCommand
from ..core.components import NoiseComponent, RoomComponent
from ..core.ecs import container_of
from ..core.edges import ContainmentMode, Contains
from ..core.events import ActorMovedEvent, DomainEvent, EventVisibility
from ..core.handlers import (
    HandlerContext,
    HandlerResult,
    planned,
    rejected,
    require_character,
    require_reachable_entity,
)
from ..core.mutations import AddEdge, AddEntity, MutationPlan, RemoveEdge, SetComponent
from ..foundation.policy.mechanics import (
    BoundaryTag,
    CharacterBoundaryComponent,
    evaluate,
)
from ..projections.room_summary import build_room_facts, render_summary

AFTER_DARK_SCOPE = "adult:after_dark"


@dataclass(frozen=True)
class AfterDarkEntranceComponent(Component):
    """Marks a reachable object as an After Dark entrance."""


@dataclass(frozen=True)
class AfterDarkExitComponent(Component):
    """Marks a reachable object as an unconditional After Dark exit."""


@dataclass(frozen=True)
class AfterDarkPassage(Edge):
    """A marker's directed passage to its destination room."""


class AfterDarkWarningAcceptedEvent(DomainEvent):
    scope: str = AFTER_DARK_SCOPE


class AfterDarkConsentWithdrawnEvent(DomainEvent):
    scope: str = AFTER_DARK_SCOPE


def _boundary(character) -> CharacterBoundaryComponent:
    if character.has_component(CharacterBoundaryComponent):
        return character.get_component(CharacterBoundaryComponent)
    return CharacterBoundaryComponent()


class AcceptAfterDarkWarningHandler:
    command_type = "accept-after-dark-warning"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id, character, error = require_character(ctx, command.character_id)
        if error is not None:
            return error
        if command.payload.get("acknowledged") is not True:
            return rejected("you must acknowledge the After Dark content warning")

        boundary = _boundary(character)
        if BoundaryTag.ADULT in boundary.denied:
            return rejected("adult access is denied for this character")
        if AFTER_DARK_SCOPE in boundary.allowed and AFTER_DARK_SCOPE not in boundary.denied:
            return rejected("the After Dark warning is already accepted")

        updated = replace(
            boundary,
            allowed=boundary.allowed | {AFTER_DARK_SCOPE},
            denied=boundary.denied - {AFTER_DARK_SCOPE},
        )
        return planned(
            MutationPlan((SetComponent(character_id, updated),)),
            lambda: AfterDarkWarningAcceptedEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                )
            ),
        )


class WithdrawAfterDarkConsentHandler:
    command_type = "withdraw-after-dark-consent"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id, character, error = require_character(ctx, command.character_id)
        if error is not None:
            return error

        boundary = _boundary(character)
        if AFTER_DARK_SCOPE not in boundary.allowed:
            return rejected("After Dark consent is not active")
        updated = replace(
            boundary,
            allowed=boundary.allowed - {AFTER_DARK_SCOPE},
            denied=boundary.denied | {AFTER_DARK_SCOPE},
        )
        return planned(
            MutationPlan((SetComponent(character_id, updated),)),
            lambda: AfterDarkConsentWithdrawnEvent(
                **ctx.event_base(
                    visibility=EventVisibility.PRIVATE,
                    actor_id=str(character_id),
                )
            ),
        )


def _passage_move(
    ctx: HandlerContext,
    command: SubmittedCommand,
    *,
    argument: str,
    marker_type: type[Component],
    direction: str,
) -> HandlerResult:
    character_id, character, error = require_character(ctx, command.character_id)
    if error is not None:
        return error
    _marker_id, marker, error = require_reachable_entity(
        ctx,
        character,
        command.payload.get(argument),
        invalid_reason=f"invalid {argument.replace('_', ' ')}",
        missing_reason=f"{argument.replace('_', ' ')} does not exist",
        unreachable_reason=f"{argument.replace('_', ' ')} is not reachable",
    )
    if error is not None:
        return error
    if not marker.has_component(marker_type):
        return rejected(f"{argument.replace('_', ' ')} is the wrong kind")

    passages = marker.get_relationships(AfterDarkPassage)
    if not passages:
        return rejected("After Dark passage is not connected")
    if len(passages) != 1:
        return rejected("After Dark passage is ambiguous")
    _passage, destination_id = passages[0]
    destination = ctx.entity(destination_id)
    if not destination.has_component(RoomComponent):
        return rejected("After Dark destination is not a room")

    current_room_id = container_of(character)
    if current_room_id is None:
        return rejected("character is not in a room")

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
                        loudness=1.0,
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
                visibility=EventVisibility.ROOM,
                actor_id=str(character_id),
                room_id=str(destination_id),
                from_room_id=str(current_room_id),
                to_room_id=str(destination_id),
                direction=direction,
                arrival_summary=render_summary(build_room_facts(ctx.world, destination_id)),
            )
        ),
    )


class EnterAfterDarkHandler:
    command_type = "enter-after-dark"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        character_id, character, error = require_character(ctx, command.character_id)
        if error is not None:
            return error
        boundary = _boundary(character)
        if AFTER_DARK_SCOPE not in boundary.allowed:
            return rejected("accept the After Dark warning before entering")
        allowed, reason = evaluate(ctx.world, AFTER_DARK_SCOPE, [str(character_id)])
        if not allowed:
            return rejected(reason or "After Dark entry is not allowed")
        return _passage_move(
            ctx,
            command,
            argument="entrance_id",
            marker_type=AfterDarkEntranceComponent,
            direction="after-dark",
        )


class LeaveAfterDarkHandler:
    command_type = "leave-after-dark"

    def execute(self, ctx: HandlerContext, command: SubmittedCommand) -> HandlerResult:
        return _passage_move(
            ctx,
            command,
            argument="exit_id",
            marker_type=AfterDarkExitComponent,
            direction="commons",
        )


__all__ = [
    "AFTER_DARK_SCOPE",
    "AcceptAfterDarkWarningHandler",
    "AfterDarkConsentWithdrawnEvent",
    "AfterDarkEntranceComponent",
    "AfterDarkExitComponent",
    "AfterDarkPassage",
    "AfterDarkWarningAcceptedEvent",
    "EnterAfterDarkHandler",
    "LeaveAfterDarkHandler",
    "WithdrawAfterDarkConsentHandler",
]
