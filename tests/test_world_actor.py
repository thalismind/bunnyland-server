"""Focused checks for WorldActor branches not covered by end-to-end tests."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import (
    CommandCost,
    Lane,
    OnInsufficientPoints,
    build_submitted_command,
)
from bunnyland.core.events import CommandCancelledEvent


def _command(scenario, *, command_id: str):
    return build_submitted_command(
        character_id=str(scenario.character),
        controller_id=str(scenario.controller),
        controller_generation=scenario.generation,
        command_type="move",
        cost=CommandCost(action=0),
        lane=Lane.WORLD,
        payload={"direction": "north"},
        on_insufficient_points=OnInsufficientPoints.QUEUE,
        submitted_at_epoch=0,
        expires_at_epoch=None,
        command_id=command_id,
    )


async def test_cancel_command_skips_non_matching_inbox_entries():
    """The cancel loop must iterate past a leading non-matching command.

    Exercises the `for` continue arc (world_actor.py 310->309): when the first
    queued command does not match the requested id, the loop advances to the
    next entry rather than stopping.
    """

    scenario = build_scenario()
    cancelled: list[CommandCancelledEvent] = []
    scenario.actor.bus.subscribe(CommandCancelledEvent, cancelled.append)

    keep = _command(scenario, command_id="keep-me")
    target = _command(scenario, command_id="cancel-me")
    scenario.actor.submit_nowait(keep)
    scenario.actor.submit_nowait(target)

    removed = await scenario.actor.cancel_command(str(scenario.character), "cancel-me")

    assert removed is target
    # The leading non-matching command survives; only the target was removed.
    assert scenario.actor.pending_submissions() == [keep]
    assert [event.command_id for event in cancelled] == ["cancel-me"]
