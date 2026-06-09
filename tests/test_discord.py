"""The Discord front-end shares the LLM name resolver and 'did you mean' feedback.

The bot itself needs the ``discord`` extra, but its name-resolution helper is the same one
the LLM dispatch uses and is importable (and testable) without it.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from types import ModuleType

import pytest

import bunnyland.discord.bot as discord_bot
import bunnyland.discord.view as discord_view
from bunnyland.core import (
    ActionArgument,
    ActionDefinition,
    ActionExample,
    ActionPattern,
    CharacterComponent,
    ContainerComponent,
    ContainmentMode,
    Contains,
    ControlledBy,
    DiscordControllerComponent,
    IdentityComponent,
    LLMControllerComponent,
    SayHandler,
    SuspendedComponent,
    SuspendedControllerComponent,
    spawn_entity,
)
from bunnyland.core.controllers import ClaimTimeoutComponent
from bunnyland.core.events import (
    CommandExecutedEvent,
    CommandRejectedEvent,
    EventVisibility,
    NotesSearchedEvent,
    WorldPauseStatusChangedEvent,
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
    set_discord_claim_fallback,
    split_discord_text,
    suspend_discord_character,
)
from bunnyland.discord.bot import (
    PAUSED_REACTION,
    QUEUED_REACTION,
    DiscordBot,
    _minutes_to_timeout_seconds,
    _parse_discord_claim_args,
    _parse_structured_payload,
    _payload_from_text,
    _require_discord,
    _split,
)
from bunnyland.discord.claim import _match_character, discord_controlled_character
from bunnyland.memory import InMemoryStore, install_memory


class _DiscordObject:
    def __init__(self, **attrs):
        self.__dict__.update(attrs)


class _DiscordThread:
    def __init__(self, *, parent=None, fail_after: int | None = None):
        self.id = 987
        self.parent = parent
        self.owner_id = 654
        self.sent = []
        self.fail_after = fail_after

    async def send(self, body):
        if self.fail_after is not None and len(self.sent) >= self.fail_after:
            raise RuntimeError("thread send failed")
        self.sent.append(body)


class _DiscordThreadMessage:
    def __init__(self, thread=None, *, fail_create=False, type_error_once=False):
        self.thread = thread or _DiscordThread()
        self.thread_requests = []
        self.fail_create = fail_create
        self.type_error_once = type_error_once

    async def create_thread(self, **kwargs):
        self.thread_requests.append(kwargs)
        if self.type_error_once and "auto_archive_duration" in kwargs:
            raise TypeError("auto archive unsupported")
        if self.fail_create:
            raise RuntimeError("missing thread permissions")
        return self.thread


class _DiscordCommandMessage:
    def __init__(self):
        self.reactions = []

    async def add_reaction(self, reaction):
        self.reactions.append(reaction)


class _DiscordThreadCtx:
    def __init__(
        self,
        *,
        channel=None,
        message=None,
        permissions=None,
        guild=True,
    ):
        self.author = _DiscordObject(id=123, mention="<@123>")
        self.me = _DiscordObject(id=456)
        self.guild = None if guild is None else _DiscordObject(id=789, me=self.me)
        self.channel = channel or _DiscordObject(id=456)
        self.message = message or _DiscordThreadMessage()
        self.sent = []
        self.replies = []
        self._permissions = permissions

        if permissions is not None:
            self.channel.permissions_for = lambda _member: permissions

    async def send(self, body):
        self.sent.append(body)

    async def reply(self, body, mention_author=False):
        self.replies.append((body, mention_author))


def _bot_for_scenario(scenario, **attrs):
    bot = object.__new__(DiscordBot)
    bot.actor = scenario.actor
    bot.allow_child_claims = attrs.pop("allow_child_claims", False)
    bot.llm_provider = attrs.pop("llm_provider", "ollama")
    bot.character_model = attrs.pop("character_model", "deepseek-v4-flash")
    bot.message_filters = attrs.pop("message_filters", DiscordMessageFilters())
    bot._pause_status = attrs.pop("pause_status", None)
    bot._world_paused = attrs.pop("world_paused", False)
    bot._pending = attrs.pop("pending", {})
    bot._paused_reactions = attrs.pop("paused_reactions", {})
    bot.client = attrs.pop("client", _DiscordObject(user="bot-user"))
    for key, value in attrs.items():
        setattr(bot, key, value)
    return bot


class _FakeDiscordIntents:
    def __init__(self):
        self.message_content = False

    @classmethod
    def default(cls):
        return cls()


class _FakeCommandNotFound(Exception):
    pass


class _FakeCommandInvokeError(Exception):
    def __init__(self, original):
        super().__init__(str(original))
        self.original = original


class _FakeDiscordBotClient:
    def __init__(self, *, command_prefix, intents, help_command):
        self.command_prefix = command_prefix
        self.intents = intents
        self.help_command = help_command
        self.commands = {}
        self.events = {}
        self.user = "fake-bot"
        self.run_tokens = []
        self.start_tokens = []
        self.closed = False
        self.context = None

    def command(self, *, name):
        def decorate(func):
            self.commands[name] = func
            return func

        return decorate

    def event(self, func):
        self.events[func.__name__] = func
        return func

    async def get_context(self, message):
        del message
        return self.context

    def run(self, token):
        self.run_tokens.append(token)

    async def start(self, token):
        self.start_tokens.append(token)

    async def close(self):
        self.closed = True


def _install_fake_discord(monkeypatch):
    clients = []

    def bot_factory(**kwargs):
        client = _FakeDiscordBotClient(**kwargs)
        clients.append(client)
        return client

    discord_module = ModuleType("discord")
    discord_module.Intents = _FakeDiscordIntents
    ext_module = ModuleType("discord.ext")
    commands_module = ModuleType("discord.ext.commands")
    commands_module.Bot = bot_factory
    commands_module.CommandNotFound = _FakeCommandNotFound
    commands_module.CommandInvokeError = _FakeCommandInvokeError
    ext_module.commands = commands_module
    discord_module.ext = ext_module

    monkeypatch.setitem(sys.modules, "discord", discord_module)
    monkeypatch.setitem(sys.modules, "discord.ext", ext_module)
    monkeypatch.setitem(sys.modules, "discord.ext.commands", commands_module)
    return discord_module, commands_module, clients


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


def test_assign_discord_controller_stores_claim_timeout_preferences(scenario):
    assign_discord_controller(
        scenario.actor,
        discord_user_id=123,
        default_channel_id=456,
        character_name="Juniper",
        fallback_controller="llm",
        timeout_seconds=900,
        llm_model="claim-model",
        llm_provider="openrouter",
    )
    character = scenario.actor.world.get_entity(scenario.character)
    _edge, controller_id = character.get_relationships(ControlledBy)[0]
    controller = scenario.actor.world.get_entity(controller_id)
    claim = controller.get_component(ClaimTimeoutComponent)

    assert claim.fallback_controller == "llm"
    assert claim.timeout_seconds == 900
    assert claim.llm_model == "claim-model"
    assert claim.llm_provider == "openrouter"


def test_set_discord_claim_fallback_updates_existing_claim(scenario):
    assign_discord_controller(
        scenario.actor,
        discord_user_id=123,
        default_channel_id=456,
        character_name="Juniper",
    )

    name, fallback = set_discord_claim_fallback(
        scenario.actor,
        discord_user_id=123,
        fallback_controller="llm",
        timeout_seconds=1200,
        model="claim-model",
        provider="openrouter",
    )

    character = scenario.actor.world.get_entity(scenario.character)
    _edge, controller_id = character.get_relationships(ControlledBy)[0]
    claim = scenario.actor.world.get_entity(controller_id).get_component(ClaimTimeoutComponent)
    assert name == "Juniper"
    assert fallback == "llm"
    assert claim.timeout_seconds == 1200
    assert claim.llm_model == "claim-model"


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


def test_minutes_to_timeout_seconds_normalizes_and_rejects_bad_values():
    assert _minutes_to_timeout_seconds(None) is None
    assert _minutes_to_timeout_seconds("15") == 900

    for value in ("not-a-number", 0):
        with pytest.raises(ValueError):
            _minutes_to_timeout_seconds(value)


def test_parse_discord_claim_args_covers_flag_forms_and_errors():
    empty_args = _parse_discord_claim_args(None)
    assert empty_args.character_name is None
    assert empty_args.fallback_controller is None
    assert empty_args.timeout_seconds is None

    args = _parse_discord_claim_args(
        '"Juniper Moss" --fallback-controller llm --timeout-minutes=15'
    )
    assert args.character_name == "Juniper Moss"
    assert args.fallback_controller == "llm"
    assert args.timeout_seconds == 900

    equals_args = _parse_discord_claim_args("Hazel --fallback=suspend --timeout 20")
    assert equals_args.character_name == "Hazel"
    assert equals_args.fallback_controller == "suspend"
    assert equals_args.timeout_seconds == 1200

    timeout_alias = _parse_discord_claim_args("Clover --claim-timeout 30 --timeout=45")
    assert timeout_alias.character_name == "Clover"
    assert timeout_alias.timeout_seconds == 2700

    separated_alias = _parse_discord_claim_args("Clover --timeout-minutes 30")
    assert separated_alias.character_name == "Clover"
    assert separated_alias.timeout_seconds == 1800

    for text, message in (
        ("Juniper --fallback", "--fallback requires suspend or llm"),
        ("Juniper --timeout", "--timeout requires minutes"),
    ):
        with pytest.raises(ValueError, match=message):
            _parse_discord_claim_args(text)


def test_split_falls_back_when_shell_quoting_is_invalid():
    assert _split('say "hello there"') == ["say", "hello there"]
    assert _split('say "unterminated') == ["say", '"unterminated']


def test_discord_payload_parsing_covers_empty_json_and_plain_text(monkeypatch):
    assert _parse_structured_payload("") == {}
    assert _parse_structured_payload('{"query": "trust", "limit": 2}') == {
        "query": "trust",
        "limit": 2,
    }
    assert _payload_from_text("hello there", ("text",)) == {"text": "hello there"}

    monkeypatch.setattr(discord_bot.json, "loads", lambda _value: ["not", "an", "object"])
    with pytest.raises(ValueError, match="JSON command payload must be an object"):
        _parse_structured_payload('{"not": "an object"}')


def test_match_character_handles_exact_prefix_ambiguous_and_missing(scenario):
    characters = list(
        scenario.actor.world.query()
        .with_all([CharacterComponent, IdentityComponent])
        .execute_entities()
    )
    juniper = characters[0]
    spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="Junia", kind="character"),
            CharacterComponent(species="bunny"),
        ],
    )
    spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="June", kind="character"),
            CharacterComponent(species="bunny"),
        ],
    )
    characters = list(
        scenario.actor.world.query()
        .with_all([CharacterComponent, IdentityComponent])
        .execute_entities()
    )

    assert _match_character(characters, "juniper") == juniper
    assert _match_character(characters, "junip") == juniper
    assert _match_character(characters, "missing") is None
    with pytest.raises(RuntimeError, match="multiple characters match"):
        _match_character(characters, "jun")


def test_discord_message_filters_require_allowed_guild_and_channel():
    filters = DiscordMessageFilters(guild_ids=(111, 222), channel_ids=(333, 444))

    assert filters.allows(_message(guild_id=111, channel_id=333))
    assert filters.allows(_message(guild_id=222, channel_id=444))
    assert not filters.allows(_message(guild_id=999, channel_id=333))
    assert not filters.allows(_message(guild_id=111, channel_id=999))
    assert not filters.allows(_message(guild_id=None, author_id=123, channel_id=333))


def test_discord_message_filters_allow_threads_in_allowed_parent_channel():
    filters = DiscordMessageFilters(guild_ids=(111,), channel_ids=(333,))
    channel = _DiscordObject(id=999, parent=_DiscordObject(id=333))
    message = _message(guild_id=111, channel_id=999)
    message.channel = channel

    assert filters.allows(message)


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


def test_help_without_actor_reports_no_world_verbs():
    assert render_help("verbs") == "No world verbs are available."


def test_help_wraps_long_inline_verb_lists():
    items = tuple(f"verb-{index}-{'x' * 120}" for index in range(12))

    lines = discord_view._wrapped_inline_lines("Header:", items)

    assert lines[0] == ""
    assert lines[1] == "Header:"
    assert len(lines) > 3
    assert all(len(line) <= 900 for line in lines[2:])
    assert discord_view._wrapped_inline_lines("Header:", ()) == ["", "Header:"]


def test_discord_action_parser_uses_live_world_verbs(scenario):
    install_memory(scenario.actor, InMemoryStore())
    verbs = scenario.actor.available_command_types()

    with pytest.raises(ValueError, match="No command provided"):
        parse_discord_action("   ", verbs)

    note = parse_discord_action("note Porcupines cannot be trusted", verbs)
    assert note.command_type == "take-note"
    assert note.tool == "take_note"
    assert note.payload == {"text": "Porcupines cannot be trusted"}

    explicit_note = parse_discord_action("take-note Porcupines cannot be trusted", verbs)
    assert explicit_note.command_type == "take-note"
    assert explicit_note.tool == "take_note"
    assert explicit_note.payload == {"text": "Porcupines cannot be trusted"}

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


def test_render_notes_search_result_handles_empty_recent_and_missing_note_ids():
    empty = NotesSearchedEvent(
        event_id="event-1",
        world_epoch=1,
        created_at=datetime.now(UTC),
        query="basin",
        mode="keyword",
        results=(),
    )
    recent = NotesSearchedEvent(
        event_id="event-2",
        world_epoch=1,
        created_at=datetime.now(UTC),
        query=None,
        mode="recent",
        results=("The basin water is unsafe.", "The well is safe."),
        note_ids=("note-123",),
    )

    assert render_notes_search_result(empty) == "No matching notes."
    assert render_notes_search_result(recent).splitlines() == [
        "Recent notes:",
        "- `note-123` The basin water is unsafe.",
        "- The well is safe.",
    ]


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


def test_split_discord_text_handles_invalid_limits_and_candidate_overflow():
    with pytest.raises(ValueError, match="limit must be between 1"):
        split_discord_text("hello", limit=0)
    with pytest.raises(ValueError, match="limit must be between 1"):
        split_discord_text("hello", limit=2001)

    chunks = split_discord_text("abc\ndefgh", limit=5)
    long_chunks = split_discord_text("ab\ncdefgh", limit=5)

    assert chunks == ("abc", "defgh")
    assert long_chunks == ("ab", "cdefg", "h")
    assert split_discord_text("") == ("",)


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


async def test_discord_threaded_reply_creates_thread_when_permitted():
    thread = _DiscordThread()
    message = _DiscordThreadMessage(thread)
    permissions = _DiscordObject(create_public_threads=True, send_messages_in_threads=True)
    ctx = _DiscordThreadCtx(message=message, permissions=permissions)

    await DiscordBot._send_threaded_or_reply(
        ctx, "Help body", title="Bunnyland help", topic="verbs 2"
    )

    assert message.thread_requests == [
        {"name": "Bunnyland help: verbs 2", "auto_archive_duration": 60}
    ]
    assert thread.sent == ["Help body"]
    assert ctx.replies == []
    assert ctx.sent == []


async def test_discord_threaded_reply_continues_in_existing_thread():
    parent = _DiscordObject(id=456)
    thread = _DiscordThread(parent=parent)
    ctx = _DiscordThreadCtx(channel=thread, message=_DiscordThreadMessage())

    await DiscordBot._send_threaded_or_reply(ctx, "More help", title="Bunnyland help")

    assert thread.sent == ["More help"]
    assert ctx.message.thread_requests == []
    assert ctx.replies == []


async def test_discord_threaded_reply_falls_back_to_reply_without_thread_permissions():
    permissions = _DiscordObject(create_public_threads=False, send_messages_in_threads=True)
    ctx = _DiscordThreadCtx(permissions=permissions)

    await DiscordBot._send_threaded_or_reply(ctx, "Help body", title="Bunnyland help")

    assert ctx.message.thread_requests == []
    assert ctx.replies == [("Help body", True)]
    assert ctx.sent == []


async def test_discord_threaded_reply_logs_thread_creation_failure(caplog):
    permissions = _DiscordObject(create_public_threads=True, send_messages_in_threads=True)
    ctx = _DiscordThreadCtx(
        message=_DiscordThreadMessage(fail_create=True),
        permissions=permissions,
    )

    caplog.set_level("WARNING", logger="bunnyland.discord")
    await DiscordBot._send_threaded_or_reply(ctx, "Help body", title="Bunnyland help")

    assert ctx.replies == [("Help body", True)]
    assert "Discord thread creation failed; falling back." in caplog.text


def test_discord_thread_detection_and_permission_edges():
    assert not DiscordBot._is_thread_channel(None)
    assert DiscordBot._is_thread_channel(_DiscordObject(type="public_thread"))

    Thread = type("Thread", (), {})
    assert DiscordBot._is_thread_channel(Thread())

    assert not DiscordBot._can_start_thread(_DiscordThreadCtx(guild=None))
    assert DiscordBot._can_start_thread(
        _DiscordThreadCtx(channel=_DiscordObject(), permissions=None)
    )


async def test_discord_reply_thread_covers_missing_and_type_error_fallbacks(caplog):
    permissions = _DiscordObject(create_public_threads=True, send_messages_in_threads=True)
    no_create = _DiscordThreadCtx(
        message=_DiscordObject(),
        permissions=permissions,
    )
    assert await DiscordBot._reply_thread(no_create, title="Help") is None

    message = _DiscordThreadMessage(type_error_once=True)
    ctx = _DiscordThreadCtx(message=message, permissions=permissions)
    thread = await DiscordBot._reply_thread(ctx, title="Bunnyland help")
    assert thread is message.thread
    assert message.thread_requests == [
        {"name": "Bunnyland help", "auto_archive_duration": 60},
        {"name": "Bunnyland help"},
    ]

    caplog.set_level("WARNING", logger="bunnyland.discord")
    failing_message = _DiscordThreadMessage(type_error_once=True, fail_create=True)
    failing = _DiscordThreadCtx(message=failing_message, permissions=permissions)

    assert await DiscordBot._reply_thread(failing, title="Bunnyland help") is None
    assert "Discord thread creation failed; falling back." in caplog.text


async def test_discord_thread_send_failure_falls_back_to_remaining_replies(monkeypatch, caplog):
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(discord_bot.asyncio, "sleep", fake_sleep)
    caplog.set_level("WARNING", logger="bunnyland.discord")
    thread = _DiscordThread(fail_after=0)
    ctx = _DiscordThreadCtx(channel=thread)

    await DiscordBot._send_threaded_or_reply(ctx, "x" * 4100, title="Bunnyland help")

    assert thread.sent == []
    assert len(ctx.replies) == 3
    assert sleeps == [0.25, 0.25]
    assert "Discord thread send failed; falling back." in caplog.text


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


def test_render_look_reports_unclaimed_and_nowhere_characters(scenario):
    assert render_look(scenario.actor, 123) == "You are not controlling a character yet."

    assign_discord_controller(
        scenario.actor,
        discord_user_id=123,
        character_name="Juniper",
    )
    scenario.actor.world.get_entity(scenario.room_a).remove_relationship(
        Contains, scenario.character
    )

    assert render_look(scenario.actor, 123) == "You are nowhere."


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


def test_render_action_result_routes_move_results(scenario):
    assign_discord_controller(
        scenario.actor,
        discord_user_id=123,
        character_name="Juniper",
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

    text = render_action_result(scenario.actor, 123, "move", event)

    assert text.startswith("You are now in Mosslit Burrow")


def test_render_action_result_summarizes_payload_values_and_rooms(scenario):
    room = scenario.actor.world.get_entity(scenario.room_b)
    room.add_component(IdentityComponent(name="Named Tunnel", kind="room"))
    nameless = spawn_entity(scenario.actor.world, [])
    event = CommandExecutedEvent(
        event_id="event-1",
        world_epoch=0,
        created_at=datetime.now(UTC),
        visibility=EventVisibility.PRIVATE,
        actor_id="entity_999999",
        command_id="cmd-1",
        command_type="inspect",
        payload={
            "target_ids": (str(scenario.character), str(scenario.room_b)),
            "note": "shiny",
            "empty": "",
            "missing": None,
            "raw_id": "entity_999999",
            "nameless_id": str(nameless.id),
        },
    )

    text = render_action_result(scenario.actor, 123, "inspect", event)

    assert "Inspect complete:" in text
    assert "target Juniper, Named Tunnel" in text
    assert "note shiny" in text
    assert f"nameless {nameless.id}" in text
    assert "raw entity_999999" in text
    assert "empty" not in text


def test_render_action_result_summarizes_single_entity_payload(scenario):
    event = CommandExecutedEvent(
        event_id="event-1",
        world_epoch=0,
        created_at=datetime.now(UTC),
        visibility=EventVisibility.PRIVATE,
        actor_id=str(scenario.character),
        command_id="cmd-1",
        command_type="inspect",
        payload={"target_id": str(scenario.character)},
    )

    assert render_action_result(scenario.actor, 123, "inspect", event) == (
        "Inspect complete: Juniper."
    )

    named_by_value = CommandExecutedEvent(
        event_id="event-2",
        world_epoch=0,
        created_at=datetime.now(UTC),
        visibility=EventVisibility.PRIVATE,
        actor_id=str(scenario.character),
        command_id="cmd-2",
        command_type="inspect",
        payload={"target": str(scenario.character)},
    )
    assert render_action_result(scenario.actor, 123, "inspect", named_by_value) == (
        "Inspect complete: Juniper."
    )

    plain_payload = CommandExecutedEvent(
        event_id="event-3",
        world_epoch=0,
        created_at=datetime.now(UTC),
        visibility=EventVisibility.PRIVATE,
        actor_id=str(scenario.character),
        command_id="cmd-3",
        command_type="inspect",
        payload={"note": "shiny"},
    )
    assert render_action_result(scenario.actor, 123, "inspect", plain_payload) == (
        "Inspect complete: note shiny."
    )


def test_render_action_result_uses_actor_fallback_contexts(scenario):
    unknown_actor = CommandExecutedEvent(
        event_id="event-1",
        world_epoch=0,
        created_at=datetime.now(UTC),
        visibility=EventVisibility.PRIVATE,
        actor_id="entity_999999",
        command_id="cmd-1",
        command_type="wait",
    )
    assert render_action_result(scenario.actor, 123, "wait", unknown_actor) == (
        "Wait complete for character."
    )

    loose = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Loose Bunny", kind="character"), CharacterComponent()],
    )
    loose_actor = CommandExecutedEvent(
        event_id="event-2",
        world_epoch=0,
        created_at=datetime.now(UTC),
        visibility=EventVisibility.PRIVATE,
        actor_id=str(loose.id),
        command_id="cmd-2",
        command_type="wait",
    )

    assert render_action_result(scenario.actor, 123, "wait", loose_actor) == (
        "Wait complete for Loose Bunny."
    )


def test_render_action_result_uses_room_titles_for_entities_without_identity(scenario):
    event = CommandExecutedEvent(
        event_id="event-1",
        world_epoch=0,
        created_at=datetime.now(UTC),
        visibility=EventVisibility.PRIVATE,
        actor_id=str(scenario.character),
        command_id="cmd-1",
        command_type="inspect",
        payload={"target_id": str(scenario.room_b)},
    )

    assert render_action_result(scenario.actor, 123, "inspect", event) == (
        "Inspect complete: North Tunnel."
    )


def test_render_action_result_summarizes_result_events(scenario):
    token = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="silver token", kind="item")],
    )
    event = CommandExecutedEvent(
        event_id="event-1",
        world_epoch=0,
        created_at=datetime.now(UTC),
        visibility=EventVisibility.PRIVATE,
        actor_id=str(scenario.character),
        command_id="cmd-1",
        command_type="take",
        result_events=(
            {
                "event_type": "ItemTakenEvent",
                "actor_id": str(scenario.character),
                "item_id": str(token.id),
                "target_ids": (str(token.id),),
                "count": 2,
                "missing_id": "entity_999999",
                "missing_ids": ("entity_999998",),
            },
            {
                "event_type": "CustomEvent",
                "event_id": "event-2",
                "world_epoch": 0,
                "created_at": "now",
            },
        ),
    )

    text = render_action_result(scenario.actor, 123, "take", event)

    assert text.splitlines() == [
        "Item taken: item silver token; count 2.",
        "Custom.",
    ]
    assert discord_view._humanize_event_type("") == ""


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


async def test_discord_queued_ack_ignores_reaction_failures():
    class Message:
        async def add_reaction(self, reaction):
            del reaction
            raise RuntimeError("missing reaction permission")

    class Ctx:
        def __init__(self):
            self.message = Message()

    await DiscordBot._acknowledge_queued(Ctx(), PAUSED_REACTION)


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


async def test_discord_resume_ignores_paused_reaction_failures():
    class Message:
        def __init__(self):
            self.add_attempts = 0
            self.remove_attempts = 0

        async def add_reaction(self, reaction):
            del reaction
            self.add_attempts += 1
            raise RuntimeError("missing add permission")

        async def remove_reaction(self, reaction, user):
            del reaction, user
            self.remove_attempts += 1
            raise RuntimeError("missing remove permission")

    bot = object.__new__(DiscordBot)
    bot.client = type("Client", (), {"user": "bot-user"})()
    message = Message()
    bot._paused_reactions = {"command-1": message}

    await bot._replace_paused_reactions()

    assert message.remove_attempts == 1
    assert message.add_attempts == 1
    assert bot._paused_reactions == {}


def test_discord_pause_status_probe_overrides_cached_state():
    paused = True
    bot = object.__new__(DiscordBot)
    bot._world_paused = False
    bot._pause_status = lambda: paused

    assert bot._is_world_paused() is True


async def test_discord_bot_complete_pending_resolves_future_and_clears_reaction():
    bot = object.__new__(DiscordBot)
    future = asyncio.get_running_loop().create_future()
    message = _DiscordCommandMessage()
    bot._pending = {"cmd-1": future}
    bot._paused_reactions = {"cmd-1": message}
    event = CommandExecutedEvent(
        event_id="event-1",
        world_epoch=1,
        created_at=datetime.now(UTC),
        visibility=EventVisibility.PRIVATE,
        actor_id="char-1",
        command_id="cmd-1",
        command_type="wait",
    )

    bot._complete_pending(event)

    assert future.result() is event
    assert bot._pending == {}
    assert bot._paused_reactions == {}

    done_future = asyncio.get_running_loop().create_future()
    done_future.set_result("already done")
    bot._pending = {"cmd-1": done_future}
    bot._paused_reactions = {}

    bot._complete_pending(event)

    assert done_future.result() == "already done"


async def test_discord_bot_posts_pause_status_to_broadcast_channels(scenario):
    assign_discord_controller(
        scenario.actor,
        discord_user_id=123,
        default_channel_id=456,
        character_name="Juniper",
    )

    class Channel:
        def __init__(self):
            self.messages = []

        async def send(self, message):
            self.messages.append(message)

    class Client:
        def __init__(self, channel):
            self.channel = channel
            self.fetched = []

        def get_channel(self, channel_id):
            assert channel_id == 456
            return self.channel

        async def fetch_channel(self, channel_id):
            self.fetched.append(channel_id)
            return self.channel

    channel = Channel()
    bot = _bot_for_scenario(scenario, client=Client(channel))

    await bot._post_pause_status(
        WorldPauseStatusChangedEvent(
            event_id="event-1",
            world_epoch=1,
            created_at=datetime.now(UTC),
            paused=True,
            state="paused",
            message="World paused.",
        )
    )

    assert bot._world_paused is True
    assert channel.messages == ["World paused."]
    assert bot.client.fetched == []


async def test_discord_bot_pause_status_fetch_and_send_failures_are_nonfatal(
    capsys,
    scenario,
):
    assign_discord_controller(
        scenario.actor,
        discord_user_id=123,
        default_channel_id=456,
        character_name="Juniper",
    )

    class FetchFailingClient:
        def get_channel(self, channel_id):
            del channel_id
            return None

        async def fetch_channel(self, channel_id):
            del channel_id
            raise RuntimeError("fetch failed")

    bot = _bot_for_scenario(scenario, client=FetchFailingClient())
    await bot._post_pause_status(
        WorldPauseStatusChangedEvent(
            event_id="event-1",
            world_epoch=1,
            created_at=datetime.now(UTC),
            paused=True,
            state="paused",
            message="World paused.",
        )
    )
    assert "fetch failed" in capsys.readouterr().out

    class SendFailingChannel:
        async def send(self, message):
            del message
            raise RuntimeError("send failed")

    class SendFailingClient:
        def get_channel(self, channel_id):
            del channel_id
            return SendFailingChannel()

    bot = _bot_for_scenario(scenario, client=SendFailingClient())
    await bot._post_pause_status(
        WorldPauseStatusChangedEvent(
            event_id="event-2",
            world_epoch=1,
            created_at=datetime.now(UTC),
            paused=True,
            state="paused",
            message="World paused.",
        )
    )
    assert "send failed" in capsys.readouterr().out


async def test_discord_bot_pause_resume_replaces_cached_reactions(scenario):
    assign_discord_controller(
        scenario.actor,
        discord_user_id=123,
        default_channel_id=456,
        character_name="Juniper",
    )

    class Channel:
        def __init__(self):
            self.messages = []

        async def send(self, message):
            self.messages.append(message)

    class Client:
        user = "bot-user"

        def __init__(self):
            self.channel = Channel()

        def get_channel(self, channel_id):
            del channel_id
            return self.channel

    class Message:
        def __init__(self):
            self.removed = []
            self.added = []

        async def remove_reaction(self, reaction, user):
            self.removed.append((reaction, user))

        async def add_reaction(self, reaction):
            self.added.append(reaction)

    client = Client()
    paused_message = Message()
    bot = _bot_for_scenario(
        scenario,
        client=client,
        paused_reactions={"cmd-1": paused_message},
        world_paused=True,
    )

    await bot._post_pause_status(
        WorldPauseStatusChangedEvent(
            event_id="event-1",
            world_epoch=1,
            created_at=datetime.now(UTC),
            paused=False,
            state="running",
            message="World resumed.",
        )
    )

    assert bot._world_paused is False
    assert paused_message.removed == [(PAUSED_REACTION, "bot-user")]
    assert paused_message.added == [QUEUED_REACTION]
    assert client.channel.messages == ["World resumed."]


async def test_discord_bot_build_command_resolves_names_and_reports_suggestions(scenario):
    bot = _bot_for_scenario(scenario)

    missing_command, missing_error = await bot._build_command(
        123,
        parse_discord_action("move north", scenario.actor.available_command_types()),
    )
    assert missing_command is None
    assert missing_error == "You are not controlling a character yet."

    assign_discord_controller(scenario.actor, discord_user_id=123, character_name="Juniper")
    basket = spawn_entity(
        scenario.actor.world,
        [
            IdentityComponent(name="woven basket", kind="item"),
            ContainerComponent(open=True),
        ],
    )
    scenario.actor.world.get_entity(scenario.room_a).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT),
        basket.id,
    )

    command, error = await bot._build_command(
        123,
        parse_discord_action("move north", scenario.actor.available_command_types()),
    )
    assert error is None
    assert command.command_type == "move"
    assert command.payload == {"direction": "north"}

    unresolved_command, unresolved_error = await bot._build_command(
        123,
        discord_bot.DiscordAction(
            command_type="take",
            payload={"item_id": "baskt"},
            tool="take",
        ),
    )
    assert unresolved_command is None
    assert "did you mean" in unresolved_error.lower()
    assert "woven basket" in unresolved_error


async def test_discord_bot_build_command_supports_plugin_verbs_without_tool(scenario):
    assign_discord_controller(scenario.actor, discord_user_id=123, character_name="Juniper")
    bot = _bot_for_scenario(scenario)

    command, error = await bot._build_command(
        123,
        discord_bot.DiscordAction(
            command_type="smile",
            payload={"wide": True},
            tool=None,
        ),
    )

    assert error is None
    assert command.command_type == "smile"
    assert command.payload == {"wide": True}
    assert command.cost.action == 1
    assert command.lane.value == "world"


async def test_discord_bot_submit_action_returns_build_errors(scenario):
    bot = _bot_for_scenario(scenario)
    ctx = _DiscordThreadCtx(message=_DiscordCommandMessage())

    result = await bot._submit_action(
        ctx,
        discord_bot.DiscordAction(command_type="say", payload={"text": "hello"}, tool="say"),
    )

    assert result == "You are not controlling a character yet."
    assert ctx.message.reactions == []


async def test_discord_bot_submit_action_acknowledges_and_renders_result(scenario):
    assign_discord_controller(scenario.actor, discord_user_id=123, character_name="Juniper")
    scenario.actor.register_handler(SayHandler())
    bot = _bot_for_scenario(scenario)
    submitted = []

    async def submit(command):
        submitted.append(command)
        bot._complete_pending(
            CommandExecutedEvent(
                event_id="event-1",
                world_epoch=1,
                created_at=datetime.now(UTC),
                visibility=EventVisibility.PRIVATE,
                actor_id=command.character_id,
                command_id=command.command_id,
                command_type=command.command_type,
            )
        )

    bot.actor.submit = submit
    ctx = _DiscordThreadCtx(message=_DiscordCommandMessage())

    result = await bot._submit_action(
        ctx,
        parse_discord_action("say hello", scenario.actor.available_command_types()),
    )

    assert submitted[0].on_insufficient_points.value == "deny"
    assert ctx.message.reactions == [QUEUED_REACTION]
    assert result == "Say complete for Juniper in Mosslit Burrow."


async def test_discord_bot_submit_action_tracks_paused_reactions(scenario):
    assign_discord_controller(scenario.actor, discord_user_id=123, character_name="Juniper")
    scenario.actor.register_handler(SayHandler())
    bot = _bot_for_scenario(scenario, world_paused=True)
    submitted = []

    async def submit(command):
        submitted.append(command)

    bot.actor.submit = submit
    ctx = _DiscordThreadCtx(message=_DiscordCommandMessage())
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(discord_bot, "MOVE_RESULT_TIMEOUT_SECONDS", 0.001)
    try:
        result = await bot._submit_action(
            ctx,
            parse_discord_action("say hello", scenario.actor.available_command_types()),
        )
    finally:
        monkeypatch.undo()

    assert submitted
    assert ctx.message.reactions == [PAUSED_REACTION]
    assert result == "Say queued, but it has not run yet."
    assert bot._pending == {}
    assert list(bot._paused_reactions.values()) == [ctx.message]


async def test_discord_bot_submit_action_renders_remember_notes(scenario):
    install_memory(scenario.actor, InMemoryStore())
    assign_discord_controller(scenario.actor, discord_user_id=123, character_name="Juniper")
    bot = _bot_for_scenario(scenario)

    async def submit(command):
        await scenario.actor.bus.publish(
            NotesSearchedEvent(
                event_id="event-notes",
                world_epoch=1,
                created_at=datetime.now(UTC),
                visibility=EventVisibility.PRIVATE,
                actor_id=command.character_id,
                query="trust",
                mode="vector",
                results=("Trust the moss keeper.",),
                note_ids=("note-1",),
            )
        )
        bot._complete_pending(
            CommandExecutedEvent(
                event_id="event-1",
                world_epoch=1,
                created_at=datetime.now(UTC),
                visibility=EventVisibility.PRIVATE,
                actor_id=command.character_id,
                command_id=command.command_id,
                command_type=command.command_type,
            )
        )

    bot.actor.submit = submit
    ctx = _DiscordThreadCtx(message=_DiscordCommandMessage())

    result = await bot._submit_action(
        ctx,
        parse_discord_action("remember trust", scenario.actor.available_command_types()),
    )

    assert "`note-1`" in result
    assert "Trust the moss keeper." in result
    assert ctx.message.reactions == [QUEUED_REACTION]


async def test_discord_bot_reply_falls_back_across_context_shapes(caplog):
    class TypeErrorReplyCtx:
        def __init__(self):
            self.calls = []

        async def reply(self, body, mention_author=False):
            if mention_author:
                raise TypeError("mention unsupported")
            self.calls.append(body)

    ctx = TypeErrorReplyCtx()
    await DiscordBot._reply(ctx, "hello")
    assert ctx.calls == ["hello"]

    class MessageReplyCtx:
        def __init__(self):
            self.author = _DiscordObject(mention="<@123>")
            self.message = _DiscordObject()
            self.sent = []
            self.message.replies = []

            async def reply(body, mention_author=False):
                raise RuntimeError("reply failed")

            self.message.reply = reply

        async def send(self, body):
            self.sent.append(body)

    caplog.set_level("WARNING", logger="bunnyland.discord")
    fallback = MessageReplyCtx()
    await DiscordBot._reply(fallback, "hello")

    assert fallback.sent == ["<@123> hello"]
    assert "Discord message reply failed; falling back." in caplog.text


async def test_discord_bot_reply_logs_context_failure_and_handles_message_type_error(caplog):
    class Ctx:
        def __init__(self):
            self.author = _DiscordObject(mention="<@123>")
            self.message = _DiscordObject()
            self.message_calls = []

            async def message_reply(body, mention_author=False):
                if mention_author:
                    raise TypeError("mention unsupported")
                self.message_calls.append(body)

            self.message.reply = message_reply

        async def reply(self, body, mention_author=False):
            del body, mention_author
            raise RuntimeError("context reply failed")

        async def send(self, body):
            raise AssertionError(f"unexpected send: {body}")

    caplog.set_level("WARNING", logger="bunnyland.discord")
    ctx = Ctx()

    await DiscordBot._reply(ctx, "hello")

    assert ctx.message_calls == ["hello"]
    assert "Discord context reply failed; falling back." in caplog.text


async def test_discord_bot_send_help_splits_and_sleeps(monkeypatch):
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(discord_bot.asyncio, "sleep", fake_sleep)
    ctx = _DiscordThreadCtx()

    await DiscordBot._send_help(ctx, "x" * 2100)

    assert len(ctx.sent) == 2
    assert sleeps == [0.25]


async def test_discord_bot_meta_commands_cover_success_and_errors(scenario):
    bot = _bot_for_scenario(scenario)
    ctx = _DiscordThreadCtx()

    assert await bot._handle_meta_command(ctx, "claim", "Juniper") is True
    assert ctx.replies[-1][0] == "You are now controlling Juniper."

    assert await bot._handle_meta_command(ctx, "claim", "Hazel") is True
    assert ctx.replies[-1][0] == "You are already controlling a character."

    assert await bot._handle_meta_command(ctx, "fallback", "") is True
    assert ctx.replies[-1][0].startswith("Usage: !fallback")

    assert await bot._handle_meta_command(ctx, "fallback", "llm 15") is True
    assert ctx.replies[-1][0] == "Juniper will fall back to llm after 15 minutes."

    assert await bot._handle_meta_command(ctx, "characters", "") is True
    assert "Characters:" in ctx.sent[-1]

    assert await bot._handle_meta_command(ctx, "look", "") is True
    assert ctx.sent[-1].startswith("Mosslit Burrow")

    assert await bot._handle_meta_command(ctx, "help", "verbs") is True
    assert "World verbs available now" in ctx.message.thread.sent[-1]

    assert await bot._handle_meta_command(ctx, "release", "") is True
    assert ctx.replies[-1][0] == "Juniper is now controlled by the LLM."

    assert await bot._handle_meta_command(ctx, "release", "") is True
    assert "not controlling" in ctx.replies[-1][0]

    assign_discord_controller(scenario.actor, discord_user_id=123, character_name="Juniper")
    assert await bot._handle_meta_command(ctx, "suspend", "") is True
    assert ctx.replies[-1][0] == "Juniper is suspended until someone claims them."

    assert await bot._handle_meta_command(ctx, "dance", "") is False


async def test_discord_bot_meta_commands_report_parse_and_fallback_errors(scenario):
    bot = _bot_for_scenario(scenario)
    ctx = _DiscordThreadCtx()

    assert await bot._handle_meta_command(ctx, "claim", "Juniper --timeout nope") is True
    assert "timeout minutes must be a whole number" in ctx.replies[-1][0]

    assert await bot._handle_meta_command(ctx, "fallback", "llm nope") is True
    assert "timeout minutes must be a whole number" in ctx.replies[-1][0]

    assert await bot._handle_meta_command(ctx, "suspend", "") is True
    assert "not controlling" in ctx.replies[-1][0]


async def test_discord_bot_handle_text_command_routes_meta_parse_errors_and_actions(
    monkeypatch,
    scenario,
):
    bot = _bot_for_scenario(scenario)
    ctx = _DiscordThreadCtx()

    await bot.handle_text_command(ctx, "")
    assert ctx.replies == []

    await bot.handle_text_command(ctx, "unknown")
    assert "Unknown world verb" in ctx.replies[-1][0]

    submitted = []

    async def fake_submit_action(ctx_arg, action):
        submitted.append((ctx_arg, action))
        return "submitted"

    monkeypatch.setattr(bot, "_submit_action", fake_submit_action)
    scenario.actor.register_handler(SayHandler())

    await bot.handle_text_command(ctx, "say hello")

    assert submitted[0][1].command_type == "say"
    assert ctx.replies[-1][0] == "submitted"


def test_discord_require_discord_uses_installed_sdk(monkeypatch):
    discord_module, commands_module, _clients = _install_fake_discord(monkeypatch)

    assert _require_discord() == (discord_module, commands_module)


def test_discord_require_discord_reports_missing_extra(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "discord" or name.startswith("discord."):
            raise ImportError("missing discord")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="requires the 'discord' extra"):
        _require_discord()


async def test_discord_bot_init_registers_commands_and_lifecycle_delegates(
    monkeypatch,
    scenario,
):
    _discord_module, _commands_module, clients = _install_fake_discord(monkeypatch)
    pause_status = False

    bot = DiscordBot(
        scenario.actor,
        token="discord-token",
        allow_child_claims=True,
        llm_provider="openrouter",
        character_model="controller-model",
        pause_status=lambda: pause_status,
    )

    client = clients[0]
    assert bot.client is client
    assert client.command_prefix == "!"
    assert client.intents.message_content is True
    assert set(client.commands) == {
        "claim",
        "fallback",
        "characters",
        "release",
        "suspend",
        "look",
        "help",
    }
    assert {"on_ready", "on_message", "on_command_error"} <= set(client.events)

    bot.run()
    await bot.start()
    await bot.close()

    assert client.run_tokens == ["discord-token"]
    assert client.start_tokens == ["discord-token"]
    assert client.closed is True


async def test_discord_registered_command_callbacks_cover_success_and_error_paths(
    monkeypatch,
    scenario,
):
    _install_fake_discord(monkeypatch)
    bot = DiscordBot(scenario.actor, token="discord-token")
    commands = bot.client.commands
    ctx = _DiscordThreadCtx()

    await commands["claim"](ctx, character="Juniper")
    assert ctx.replies[-1][0] == "You are now controlling Juniper."

    await commands["claim"](ctx, character="Hazel")
    assert ctx.replies[-1][0] == "You are already controlling a character."

    await commands["fallback"](ctx, fallback_controller=None)
    assert ctx.replies[-1][0].startswith("Usage: !fallback")

    await commands["fallback"](ctx, fallback_controller="llm", minutes=15)
    assert ctx.replies[-1][0] == "Juniper will fall back to llm after 15 minutes."

    await commands["characters"](ctx)
    assert "Characters:" in ctx.sent[-1]

    await commands["look"](ctx)
    assert ctx.sent[-1].startswith("Mosslit Burrow")

    await commands["help"](ctx, topic="verbs")
    assert "World verbs available now" in ctx.message.thread.sent[-1]

    await commands["release"](ctx)
    assert ctx.replies[-1][0] == "Juniper is now controlled by the LLM."

    await commands["release"](ctx)
    assert "not controlling" in ctx.replies[-1][0]

    assign_discord_controller(scenario.actor, discord_user_id=123, character_name="Juniper")
    await commands["suspend"](ctx)
    assert ctx.replies[-1][0] == "Juniper is suspended until someone claims them."

    await commands["suspend"](ctx)
    assert "not controlling" in ctx.replies[-1][0]


async def test_discord_registered_command_callbacks_report_validation_errors(
    monkeypatch,
    scenario,
):
    _install_fake_discord(monkeypatch)
    bot = DiscordBot(scenario.actor, token="discord-token")
    commands = bot.client.commands
    ctx = _DiscordThreadCtx()

    await commands["claim"](ctx, character="Juniper --timeout nope")
    assert "timeout minutes must be a whole number" in ctx.replies[-1][0]

    await commands["fallback"](ctx, fallback_controller="llm", minutes=0)
    assert "timeout_seconds must be between 300 and 3600" in ctx.replies[-1][0]


async def test_discord_registered_events_route_messages_and_errors(
    monkeypatch,
    capsys,
    scenario,
):
    _discord_module, commands_module, _clients = _install_fake_discord(monkeypatch)
    bot = DiscordBot(scenario.actor, token="discord-token")
    ctx = _DiscordThreadCtx()
    bot.client.context = ctx
    handled = []

    async def handle_text_command(ctx_arg, text):
        handled.append((ctx_arg, text))

    bot.handle_text_command = handle_text_command

    await bot.client.events["on_ready"]()
    assert "Discord bot connected as fake-bot." in capsys.readouterr().out

    await bot.client.events["on_message"](_message(content="!look"))
    assert handled == [(ctx, "look")]

    await bot.client.events["on_message"](_message(content="look"))
    assert handled == [(ctx, "look")]

    await bot.client.events["on_command_error"](ctx, commands_module.CommandNotFound("missing"))
    assert ctx.sent == []

    await bot.client.events["on_command_error"](
        ctx,
        commands_module.CommandInvokeError(RuntimeError("boom")),
    )

    assert "Discord command failed: RuntimeError('boom')" in capsys.readouterr().out
    assert ctx.sent[-1] == "Command failed: boom"

    await bot.client.events["on_command_error"](ctx, RuntimeError("plain boom"))

    assert "Discord command failed: RuntimeError('plain boom')" in capsys.readouterr().out
    assert ctx.sent[-1] == "Command failed: plain boom"
