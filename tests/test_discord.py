"""The Discord front-end shares the LLM name resolver and 'did you mean' feedback.

The bot itself needs the ``discord`` extra, but its name-resolution helper is the same one
the LLM dispatch uses and is importable (and testable) without it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bunnyland.core import ContainmentMode, Contains
from bunnyland.core.events import CommandExecutedEvent, CommandRejectedEvent, EventVisibility
from bunnyland.discord import (
    HELP_TEXT,
    assign_discord_controller,
    did_you_mean,
    render_action_result,
    render_look,
    render_move_result,
)


def test_did_you_mean_importable_without_the_discord_extra():
    # Importing this from the discord package must not require discord.py.
    message = did_you_mean({"item_id": "baskt"}, {"item_id": ["woven basket"]})
    assert "did you mean" in message.lower()
    assert "woven basket" in message


def test_did_you_mean_is_the_shared_resolver_helper():
    from bunnyland.llm_agents import did_you_mean as shared

    assert did_you_mean is shared


def test_help_lists_available_discord_verbs():
    assert "!look" in HELP_TEXT
    assert "!move <direction>" in HELP_TEXT
    assert "!claim [character]" in HELP_TEXT


def test_render_look_uses_room_summary_projection(scenario):
    assign_discord_controller(
        scenario.actor,
        discord_user_id=123,
        character_name="Juniper",
    )

    text = render_look(scenario.actor, 123)

    assert text.startswith("Mosslit Burrow")
    assert "Here: Juniper." in text
    assert "Exits: north." in text


def test_render_move_result_reports_rejection_reason(scenario):
    assign_discord_controller(
        scenario.actor,
        discord_user_id=123,
        character_name="Juniper",
    )
    event = CommandRejectedEvent(
        event_id="event-1",
        world_epoch=0,
        created_at=datetime.now(UTC),
        visibility=EventVisibility.PRIVATE,
        actor_id=str(scenario.character),
        command_id="cmd-1",
        command_type="move",
        reason="no matching exit",
    )

    text = render_move_result(scenario.actor, 123, event)

    assert text == "Move failed: no matching exit."


def test_render_move_result_shows_room_after_successful_move(scenario):
    assign_discord_controller(
        scenario.actor,
        discord_user_id=123,
        character_name="Juniper",
    )
    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(
        Contains, scenario.character
    )
    scenario.actor.world.get_entity(scenario.room_b).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), scenario.character
    )
    event = CommandExecutedEvent(
        event_id="event-1",
        world_epoch=0,
        created_at=datetime.now(UTC),
        visibility=EventVisibility.PRIVATE,
        actor_id=str(scenario.character),
        command_id="cmd-1",
        command_type="move",
    )

    text = render_move_result(scenario.actor, 123, event)

    assert text.startswith("North Tunnel")
    assert "Exits: south." in text


def test_render_action_result_confirms_non_move_success(scenario):
    event = CommandExecutedEvent(
        event_id="event-1",
        world_epoch=0,
        created_at=datetime.now(UTC),
        visibility=EventVisibility.PRIVATE,
        actor_id=str(scenario.character),
        command_id="cmd-1",
        command_type="say",
    )

    text = render_action_result(scenario.actor, 123, "say", event)

    assert text == "Done: say."


def test_render_action_result_reports_non_move_rejection(scenario):
    event = CommandRejectedEvent(
        event_id="event-1",
        world_epoch=0,
        created_at=datetime.now(UTC),
        visibility=EventVisibility.PRIVATE,
        actor_id=str(scenario.character),
        command_id="cmd-1",
        command_type="take",
        reason="item is not reachable",
    )

    text = render_action_result(scenario.actor, 123, "take", event)

    assert text == "Take failed: item is not reachable."
