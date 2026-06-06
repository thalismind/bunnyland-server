"""The Discord front-end shares the LLM name resolver and 'did you mean' feedback.

The bot itself needs the ``discord`` extra, but its name-resolution helper is the same one
the LLM dispatch uses and is importable (and testable) without it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bunnyland.core import (
    ActionArgument,
    ActionDefinition,
    ActionExample,
    ActionPattern,
    CharacterComponent,
    ContainmentMode,
    Contains,
    ControlledBy,
    DiscordControllerComponent,
    IdentityComponent,
    LLMControllerComponent,
    SuspendedComponent,
    SuspendedControllerComponent,
    spawn_entity,
)
from bunnyland.core.events import (
    CommandExecutedEvent,
    CommandRejectedEvent,
    EventVisibility,
    NotesSearchedEvent,
)
from bunnyland.discord import (
    HELP_TEXT,
    DiscordMessageFilters,
    assign_discord_controller,
    did_you_mean,
    discord_broadcast_channel_ids,
    explain_rejection,
    parse_discord_action,
    parse_discord_id_list,
    release_discord_character_to_llm,
    render_action_result,
    render_character_list,
    render_help,
    render_look,
    render_move_result,
    render_notes_search_result,
    split_discord_text,
    suspend_discord_character,
)
from bunnyland.discord.bot import PAUSED_REACTION, QUEUED_REACTION, DiscordBot
from bunnyland.discord.claim import discord_controlled_character
from bunnyland.memory import InMemoryStore, install_memory


class _DiscordObject:
    def __init__(self, **attrs):
        self.__dict__.update(attrs)


def _message(
    *,
    author_id: int = 123,
    channel_id: int = 456,
    content: str = "!look",
    guild_id: int | None = 789,
    bot: bool = False,
):
    return _DiscordObject(
        author=_DiscordObject(id=author_id, bot=bot),
        channel=_DiscordObject(id=channel_id),
        content=content,
        guild=None if guild_id is None else _DiscordObject(id=guild_id),
    )


def test_did_you_mean_importable_without_the_discord_extra():
    # Importing this from the discord package must not require discord.py.
    message = did_you_mean({"item_id": "baskt"}, {"item_id": ["woven basket"]})
    assert "did you mean" in message.lower()
    assert "woven basket" in message


def test_did_you_mean_is_the_shared_resolver_helper():
    from bunnyland.llm_agents import did_you_mean as shared

    assert did_you_mean is shared


def test_render_character_list_includes_controller_statuses(scenario):
    assign_discord_controller(
        scenario.actor,
        discord_user_id=123,
        character_name="Juniper",
    )
    llm_character = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Hazel", kind="character"),
            CharacterComponent(species="bunny"),
        ],
    )
    llm_controller = spawn_entity(
        scenario.actor.world,
        [LLMControllerComponent(profile_name="default", model="deepseek-v4-flash")],
    )
    scenario.actor.assign_controller(llm_character.id, llm_controller.id)
    spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Clover", kind="character"),
            CharacterComponent(species="bunny"),
        ],
    )

    text = render_character_list(scenario.actor)

    assert "Characters:" in text
    assert "- Juniper - Discord controller" in text
    assert "- Hazel - LLM controller" in text
    assert "- Clover - free" in text


def test_assign_discord_controller_reuses_existing_user_channel_controller(scenario):
    assigned = assign_discord_controller(
        scenario.actor,
        discord_user_id=123,
        default_channel_id=456,
        character_name="Juniper",
    )
    character = scenario.actor.world.get_entity(scenario.character)
    first_edge, first_controller_id = character.get_relationships(ControlledBy)[0]

    reassigned = assign_discord_controller(
        scenario.actor,
        discord_user_id=123,
        default_channel_id=456,
        character_name="Juniper",
    )

    second_edge, second_controller_id = character.get_relationships(ControlledBy)[0]
    controllers = scenario.actor.world.query().with_all([DiscordControllerComponent])
    matching_controllers = [
        entity.id
        for entity in controllers.execute_entities()
        if entity.get_component(DiscordControllerComponent).discord_user_id == 123
        and entity.get_component(DiscordControllerComponent).default_channel_id == 456
    ]
    assert assigned == "Juniper"
    assert reassigned == "Juniper"
    assert second_controller_id == first_controller_id
    assert second_edge.generation == first_edge.generation
    assert matching_controllers == [first_controller_id]


def test_discord_broadcast_channel_ids_returns_unique_attached_channels(scenario):
    assign_discord_controller(
        scenario.actor,
        discord_user_id=123,
        default_channel_id=456,
        character_name="Juniper",
    )
    spawn_entity(
        scenario.actor.world,
        [DiscordControllerComponent(discord_user_id=456, default_channel_id=456)],
    )
    spawn_entity(
        scenario.actor.world,
        [DiscordControllerComponent(discord_user_id=789, default_channel_id=0)],
    )

    assert discord_broadcast_channel_ids(scenario.actor) == (456,)


def test_discord_message_filters_allow_all_when_unconfigured():
    filters = DiscordMessageFilters()

    assert filters.allows(_message(guild_id=789))
    assert filters.allows(_message(guild_id=None))


def test_discord_message_filters_require_allowed_guild_and_channel():
    filters = DiscordMessageFilters(guild_ids=(111, 222), channel_ids=(333, 444))

    assert filters.allows(_message(guild_id=111, channel_id=333))
    assert filters.allows(_message(guild_id=222, channel_id=444))
    assert not filters.allows(_message(guild_id=999, channel_id=333))
    assert not filters.allows(_message(guild_id=111, channel_id=999))
    assert not filters.allows(_message(guild_id=None, author_id=123, channel_id=333))


def test_discord_message_filters_allow_only_configured_user_dms():
    filters = DiscordMessageFilters(dm_user_ids=(123, 456))

    assert filters.allows(_message(guild_id=None, author_id=123))
    assert filters.allows(_message(guild_id=None, author_id=456))
    assert not filters.allows(_message(guild_id=None, author_id=789))
    assert not filters.allows(_message(guild_id=111, author_id=123))


def test_discord_message_filters_allow_guild_channels_or_user_dms():
    filters = DiscordMessageFilters(
        guild_ids=(111,),
        channel_ids=(333,),
        dm_user_ids=(123,),
    )

    assert filters.allows(_message(guild_id=111, channel_id=333, author_id=999))
    assert filters.allows(_message(guild_id=None, author_id=123))
    assert not filters.allows(_message(guild_id=111, channel_id=999, author_id=123))
    assert not filters.allows(_message(guild_id=None, author_id=999))


def test_parse_discord_id_list_accepts_comma_separated_ids():
    assert parse_discord_id_list(None) == ()
    assert parse_discord_id_list("") == ()
    assert parse_discord_id_list("111, 222,333") == (111, 222, 333)


def test_discord_bot_ignores_messages_rejected_by_filters():
    bot = object.__new__(DiscordBot)
    bot.message_filters = DiscordMessageFilters(guild_ids=(111,), channel_ids=(333,))

    assert bot._should_handle_message(_message(guild_id=111, channel_id=333))
    assert not bot._should_handle_message(_message(guild_id=111, channel_id=999))
    assert not bot._should_handle_message(_message(guild_id=111, channel_id=333, bot=True))
    assert not bot._should_handle_message(_message(guild_id=111, channel_id=333, content="look"))


def test_release_discord_character_reassigns_to_llm_controller(scenario):
    assign_discord_controller(
        scenario.actor,
        discord_user_id=123,
        character_name="Juniper",
    )

    released = release_discord_character_to_llm(
        scenario.actor,
        discord_user_id=123,
        model="deepseek-v4-flash",
        provider="openrouter",
    )

    character = scenario.actor.world.get_entity(scenario.character)
    edge, controller_id = character.get_relationships(ControlledBy)[0]
    controller = scenario.actor.world.get_entity(controller_id)
    llm = controller.get_component(LLMControllerComponent)
    assert released == "Juniper"
    assert edge.generation == 2
    assert llm.model == "deepseek-v4-flash"
    assert llm.provider == "openrouter"
    assert not controller.has_component(DiscordControllerComponent)
    assert not character.has_component(SuspendedComponent)
    assert render_character_list(scenario.actor).splitlines()[1] == "- Juniper - LLM controller"
    controllers = scenario.actor.world.query().with_all([DiscordControllerComponent])
    assert [
        entity
        for entity in controllers.execute_entities()
        if entity.get_component(DiscordControllerComponent).discord_user_id == 123
    ] == []


def test_suspend_discord_character_reassigns_to_suspended_controller(scenario):
    assign_discord_controller(
        scenario.actor,
        discord_user_id=123,
        character_name="Juniper",
    )

    suspended = suspend_discord_character(
        scenario.actor,
        discord_user_id=123,
        reason="player suspended",
    )

    character = scenario.actor.world.get_entity(scenario.character)
    edge, controller_id = character.get_relationships(ControlledBy)[0]
    controller = scenario.actor.world.get_entity(controller_id)
    marker = character.get_component(SuspendedComponent)
    no_op = controller.get_component(SuspendedControllerComponent)
    assert suspended == "Juniper"
    assert edge.generation == 2
    assert marker.reason == "player suspended"
    assert no_op.reason == "player suspended"
    assert not controller.has_component(DiscordControllerComponent)
    assert render_character_list(scenario.actor).splitlines()[1] == "- Juniper - suspended"
    assert discord_controlled_character(scenario.actor, 123) is None
    controllers = scenario.actor.world.query().with_all([DiscordControllerComponent])
    assert [
        entity
        for entity in controllers.execute_entities()
        if entity.get_component(DiscordControllerComponent).discord_user_id == 123
    ] == []

    claimed = assign_discord_controller(
        scenario.actor,
        discord_user_id=123,
        character_name="Juniper",
    )

    assert claimed == "Juniper"
    assert discord_controlled_character(scenario.actor, 123) is not None


def test_help_lists_available_discord_verbs(scenario):
    assert "!look" in HELP_TEXT
    assert "!<verb> ..." in HELP_TEXT
    assert "!claim [character]" in HELP_TEXT
    assert "!release" in HELP_TEXT
    assert "!suspend" in HELP_TEXT
    assert render_help() == HELP_TEXT
    assert render_help("humans") == HELP_TEXT
    text = render_help("humans", scenario.actor)
    assert "World verbs available now:" in text
    assert "move" in text
    assert "take-control" in text
    assert "move:" not in text


def test_discord_action_parser_uses_live_world_verbs(scenario):
    install_memory(scenario.actor, InMemoryStore())
    verbs = scenario.actor.available_command_types()

    note = parse_discord_action("note Porcupines cannot be trusted", verbs)
    assert note.command_type == "take-note"
    assert note.tool == "take_note"
    assert note.payload == {"text": "Porcupines cannot be trusted"}

    remember = parse_discord_action("remember trust", verbs)
    assert remember.command_type == "remember"
    assert remember.tool == "remember"
    assert remember.payload == {"query": "trust", "mode": "vector"}

    forget = parse_discord_action("forget note-123", verbs)
    assert forget.command_type == "forget"
    assert forget.tool == "forget"
    assert forget.payload == {"note_id": "note-123"}

    structured = parse_discord_action("remember query=trust mode=keyword limit=2", verbs)
    assert structured.payload == {"query": "trust", "mode": "keyword", "limit": 2}


def test_discord_action_parser_accepts_plugin_only_world_verbs(scenario):
    class DummyHandler:
        command_type = "smile"

        def execute(self, ctx, command):
            raise AssertionError("not called")

    scenario.actor.register_handler(DummyHandler())

    action = parse_discord_action(
        "smile target_id=Hazel wide=true", scenario.actor.available_command_types()
    )

    assert action.command_type == "smile"
    assert action.tool is None
    assert action.payload == {"target_id": "Hazel", "wide": True}


def test_discord_action_parser_uses_plugin_action_definition_patterns():
    definition = ActionDefinition(
        command_type="wave",
        tool_name="wave",
        arguments={"target_id": ActionArgument(kind="entity")},
        natural_patterns=(ActionPattern("wave to {target_id}"),),
    )

    action = parse_discord_action("wave to Hazel", ("wave",), (definition,))

    assert action.command_type == "wave"
    assert action.tool == "wave"
    assert action.payload == {"target_id": "Hazel"}


def test_discord_action_parser_accepts_natural_enchant_commands():
    action = parse_discord_action(
        "enchant moss charm with Mend Moss",
        ("enchant-item", "cast-spell"),
    )
    cast = parse_discord_action("cast moss charm on Juniper", ("cast-spell",))

    assert action.command_type == "enchant-item"
    assert action.tool == "enchant_item"
    assert action.payload == {"item_id": "moss charm", "spell_id": "Mend Moss"}
    assert cast.command_type == "cast-spell"
    assert cast.tool == "cast_spell"
    assert cast.payload == {"spell_id": "moss charm", "target_id": "Juniper"}


def test_discord_action_parser_rejects_unstructured_plugin_only_args(scenario):
    class DummyHandler:
        command_type = "smile"

        def execute(self, ctx, command):
            raise AssertionError("not called")

    scenario.actor.register_handler(DummyHandler())

    try:
        parse_discord_action("smile Hazel", scenario.actor.available_command_types())
    except ValueError as exc:
        assert "key=value" in str(exc)
    else:
        raise AssertionError("expected unstructured plugin-only command to fail")


def test_help_agents_describes_llm_agent_rules(scenario):
    text = render_help("agents", scenario.actor)

    assert "Agent help:" in text
    assert "persistent ECS world" in text
    assert "verb/tool" in text
    assert "Action points" in text
    assert "Focus points" in text
    assert "cannot mutate ECS directly" in text
    assert "!help verbs" in text
    assert "World verbs available now:" not in text


def test_help_verbs_lists_available_discord_verbs_with_arguments(scenario):
    text = render_help("verbs", scenario.actor)

    assert "World verbs available now (page 1/1):" in text
    assert "move: direction, exit_id" in text
    assert "take-control: no documented arguments" in text


def test_render_notes_search_result_includes_note_ids():
    event = NotesSearchedEvent(
        event_id="event-1",
        world_epoch=1,
        created_at=datetime.now(UTC),
        query="basin",
        mode="keyword",
        results=("The basin water is unsafe.",),
        note_ids=("note-123",),
    )

    text = render_notes_search_result(event)

    assert "`note-123`" in text
    assert "The basin water is unsafe." in text


def test_help_verbs_is_paginated(scenario):
    class DummyHandler:
        def __init__(self, command_type: str) -> None:
            self.command_type = command_type

        def execute(self, ctx, command):
            raise AssertionError("not called")

    for index in range(30):
        scenario.actor.register_handler(DummyHandler(f"zz-{index:02d}"))

    first_page = render_help("verbs", scenario.actor)
    second_page = render_help("verbs 2", scenario.actor)

    assert "World verbs available now (page 1/3):" in first_page
    assert "Use !help verbs 2 for the next page." in first_page
    assert "World verbs available now (page 2/3):" in second_page
    assert len(first_page) < 1900
    assert len(second_page) < 1900


def test_split_discord_text_keeps_chunks_below_the_api_limit():
    text = "x" * 2100
    chunks = split_discord_text(text, limit=1000)

    assert all(len(chunk) <= 1000 for chunk in chunks)
    assert "".join(chunks) == text


def test_help_command_stubs_action_help(scenario):
    text = render_help("take", scenario.actor)

    assert "Help for `take`" in text
    assert "item_id" in text
    assert "Character action: take" in text


def test_help_command_uses_plugin_action_definition_metadata(scenario):
    scenario.actor.register_action_definition(
        ActionDefinition(
            command_type="wave",
            tool_name="wave",
            title="Wave",
            description="Wave to a reachable character.",
            arguments={
                "target_id": ActionArgument(
                    description="The character to wave at.",
                    kind="entity",
                    required=True,
                )
            },
            examples=(ActionExample("wave to Hazel", natural=True),),
        )
    )

    text = render_help("wave", scenario.actor)

    assert "Help for `wave`" in text
    assert "Wave to a reachable character." in text
    assert "- target_id (entity, required): The character to wave at." in text
    assert "- wave to Hazel" in text


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

    assert text == "Say complete for Juniper in Mosslit Burrow."


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


async def test_discord_queued_ack_uses_requested_reaction():
    class Message:
        def __init__(self):
            self.reactions = []

        async def add_reaction(self, reaction):
            self.reactions.append(reaction)

    class Ctx:
        def __init__(self):
            self.message = Message()

    ctx = Ctx()

    await DiscordBot._acknowledge_queued(ctx, PAUSED_REACTION)

    assert ctx.message.reactions == [PAUSED_REACTION]


async def test_discord_resume_replaces_paused_reactions_with_hourglass():
    class Message:
        def __init__(self):
            self.added = []
            self.removed = []

        async def add_reaction(self, reaction):
            self.added.append(reaction)

        async def remove_reaction(self, reaction, user):
            self.removed.append((reaction, user))

    bot = object.__new__(DiscordBot)
    bot.client = type("Client", (), {"user": "bot-user"})()
    message = Message()
    bot._paused_reactions = {"command-1": message}

    await bot._replace_paused_reactions()

    assert message.removed == [(PAUSED_REACTION, "bot-user")]
    assert message.added == [QUEUED_REACTION]
    assert bot._paused_reactions == {}


def test_discord_pause_status_probe_overrides_cached_state():
    paused = True
    bot = object.__new__(DiscordBot)
    bot._world_paused = False
    bot._pause_status = lambda: paused

    assert bot._is_world_paused() is True
