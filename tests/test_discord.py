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
    explain_rejection,
    render_action_result,
    render_help,
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


def test_help_lists_available_discord_verbs(scenario):
    assert "!look" in HELP_TEXT
    assert "!move <direction>" in HELP_TEXT
    assert "!claim [character]" in HELP_TEXT
    assert render_help() == HELP_TEXT
    assert render_help("humans") == HELP_TEXT
    text = render_help("humans", scenario.actor)
    assert "World verbs available now:" in text
    assert "move" in text
    assert "take-control" in text


def test_help_agents_describes_llm_agent_rules(scenario):
    text = render_help("agents", scenario.actor)

    assert "Agent rules:" in text
    assert "persistent ECS world" in text
    assert "verb/tool" in text
    assert "Action points" in text
    assert "Focus points" in text
    assert "cannot mutate ECS directly" in text
    assert "World verbs available now:" in text
    assert "move" in text


def test_help_command_stubs_action_help(scenario):
    text = render_help("take", scenario.actor)

    assert "Help for `take`" in text
    assert "item_id" in text
    assert "Detailed command help is not written yet" in text


def test_help_command_handles_unknown_topic():
    text = render_help("dance")

    assert "No detailed help is available for `dance` yet" in text
    assert "!help agents" in text


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

    assert text.startswith("You are now in North Tunnel")
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


def test_explain_rejection_passes_through_plain_world_reasons():
    assert explain_rejection("no matching exit") == "no matching exit"


def test_explain_rejection_guides_on_insufficient_points():
    message = explain_rejection("insufficient points")
    assert "action points" in message
    assert "regenerate" in message


def test_explain_rejection_guides_on_consent_gate():
    message = explain_rejection("Juniper has not consented to flirting")
    assert "Juniper has not consented to flirting" in message
    assert "opt in" in message


def test_explain_rejection_guides_on_world_policy_gate():
    disabled = explain_rejection("adult is disabled in this world")
    not_enabled = explain_rejection("pvp is not enabled here")
    assert "admin has turned that off" in disabled
    assert "everyone involved has opted in" in not_enabled


def test_render_action_result_explains_a_gated_rejection(scenario):
    event = CommandRejectedEvent(
        event_id="event-1",
        world_epoch=0,
        created_at=datetime.now(UTC),
        visibility=EventVisibility.PRIVATE,
        actor_id=str(scenario.character),
        command_id="cmd-1",
        command_type="say",
        reason="insufficient points",
    )

    text = render_action_result(scenario.actor, 123, "say", event)

    assert text.startswith("Say failed: you don't have enough action points")
    assert text.endswith(".")
    assert ".." not in text
