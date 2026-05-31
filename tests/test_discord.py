"""The Discord front-end shares the LLM name resolver and 'did you mean' feedback.

The bot itself needs the ``discord`` extra, but its name-resolution helper is the same one
the LLM dispatch uses and is importable (and testable) without it.
"""

from __future__ import annotations

from bunnyland.discord import HELP_TEXT, assign_discord_controller, did_you_mean, render_look


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
