"""Tests for the Discord camera (image-request) reaction flow."""

from __future__ import annotations

from conftest import build_scenario
from test_discord import _bot_for_scenario, _DiscordObject, _install_fake_discord

from bunnyland.core import (
    CharacterComponent,
    ContainmentMode,
    Contains,
    IdentityComponent,
    spawn_entity,
)
from bunnyland.discord import assign_discord_controller
from bunnyland.discord.bot import DiscordBot
from bunnyland.foundation.history.mechanics import history_record_for_event
from bunnyland.imagegen.affordance import ACK_EMOJI, DELIVER_EMOJI, FAIL_EMOJI, REQUEST_EMOJI
from bunnyland.imagegen.components import EventImageComponent
from bunnyland.imagegen.config import ImageGenConfig
from bunnyland.imagegen.events import (
    ImageGenerationCompletedEvent,
    ImageGenerationFailedEvent,
)
from bunnyland.imagegen.media import MediaStore
from bunnyland.imagegen.prompt import CatalogExampleSource, StubPromptEnhancer
from bunnyland.imagegen.service import ImageGenService
from bunnyland.imagegen.store import WorkflowTemplateStore, default_templates


class _FakeClient:
    async def generate(self, graph, *, output_node_id=""):
        return b"PNG"


class _ReactMessage:
    def __init__(self, *, fail_reaction=False):
        self.reactions = []
        self.replied_files = []
        self._fail_reaction = fail_reaction

    async def add_reaction(self, reaction):
        if self._fail_reaction:
            raise RuntimeError("no permission")
        self.reactions.append(reaction)

    async def reply(self, *, file=None):
        self.replied_files.append(file)


def _reaction(message, emoji=REQUEST_EMOJI):
    return _DiscordObject(emoji=emoji, message=message)


def _service(actor, tmp_path):
    return ImageGenService(
        actor,
        ImageGenConfig(server_url="http://comfy.local"),
        client=_FakeClient(),
        templates=WorkflowTemplateStore(defaults=default_templates()),
        enhancer=StubPromptEnhancer(),
        examples=CatalogExampleSource(),
        media=MediaStore(tmp_path),
    )


def _bot(scenario, service):
    bot = _bot_for_scenario(scenario, imagegen=service, _image_messages={})
    scenario.actor.bus.subscribe(ImageGenerationCompletedEvent, bot._deliver_image)
    scenario.actor.bus.subscribe(ImageGenerationFailedEvent, bot._image_failed)
    return bot


async def test_camera_reaction_full_flow(tmp_path):
    scenario = build_scenario()
    assign_discord_controller(scenario.actor, discord_user_id=123, character_name="Juniper")
    service = _service(scenario.actor, tmp_path)
    bot = _bot(scenario, service)
    message = _ReactMessage()

    await bot._on_image_reaction(_reaction(message), _DiscordObject(id=123, bot=False))
    assert ACK_EMOJI in message.reactions  # acknowledged
    await service.wait_idle()  # worker runs, completion handler delivers
    assert message.replied_files and message.replied_files[0] is not None
    assert DELIVER_EMOJI in message.reactions
    await service.aclose()


async def test_camera_reaction_ignores_non_camera(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    bot = _bot(scenario, service)
    message = _ReactMessage()
    await bot._on_image_reaction(_reaction(message, emoji="👍"), _DiscordObject(id=123, bot=False))
    assert message.reactions == []
    await service.aclose()


async def test_camera_reaction_ignores_bot_user(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    bot = _bot(scenario, service)
    message = _ReactMessage()
    await bot._on_image_reaction(_reaction(message), _DiscordObject(id=999, bot=True))
    assert message.reactions == []
    await service.aclose()


async def test_camera_reaction_noop_without_imagegen():
    scenario = build_scenario()
    bot = _bot_for_scenario(scenario, imagegen=None, _image_messages={})
    message = _ReactMessage()
    await bot._on_image_reaction(_reaction(message), _DiscordObject(id=123, bot=False))
    assert message.reactions == []


async def test_camera_reaction_no_controlled_character(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    bot = _bot(scenario, service)
    message = _ReactMessage()
    # User 777 controls nothing.
    await bot._on_image_reaction(_reaction(message), _DiscordObject(id=777, bot=False))
    assert message.reactions == []
    await service.aclose()


async def test_camera_reaction_character_not_in_room(tmp_path):
    scenario = build_scenario()
    spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Stray", kind="character"), CharacterComponent(species="bunny")],
    )
    assign_discord_controller(scenario.actor, discord_user_id=222, character_name="Stray")
    service = _service(scenario.actor, tmp_path)
    bot = _bot(scenario, service)
    message = _ReactMessage()
    await bot._on_image_reaction(_reaction(message), _DiscordObject(id=222, bot=False))
    assert message.reactions == []  # no room -> nothing requested
    await service.aclose()


async def test_camera_reaction_reuses_existing_scene_image(tmp_path):
    scenario = build_scenario()
    assign_discord_controller(scenario.actor, discord_user_id=123, character_name="Juniper")
    service = _service(scenario.actor, tmp_path)
    bot = _bot(scenario, service)

    first = _ReactMessage()
    await bot._on_image_reaction(_reaction(first), _DiscordObject(id=123, bot=False))
    await service.wait_idle()
    # Same epoch -> same scene record, which now already has an image.
    second = _ReactMessage()
    await bot._on_image_reaction(_reaction(second), _DiscordObject(id=123, bot=False))
    # Delivered inline from the existing image, no queue round-trip.
    assert second.replied_files and second.replied_files[0] is not None
    assert DELIVER_EMOJI in second.reactions
    assert ACK_EMOJI not in second.reactions
    await service.aclose()


async def test_camera_reaction_via_registered_event_and_init(monkeypatch, tmp_path):
    scenario = build_scenario()
    assign_discord_controller(scenario.actor, discord_user_id=123, character_name="Juniper")
    discord_module, _commands, clients = _install_fake_discord(monkeypatch)
    discord_module.File = lambda fp, filename=None: {"filename": filename}
    service = _service(scenario.actor, tmp_path)
    # Real __init__ wires the bus subscriptions and registers the reaction event.
    bot = DiscordBot(scenario.actor, token="t", imagegen=service)
    assert bot.imagegen is service
    client = clients[0]
    assert client.intents.reactions is True
    assert "on_reaction_add" in client.events

    message = _ReactMessage()
    await client.events["on_reaction_add"](_reaction(message), _DiscordObject(id=123, bot=False))
    assert ACK_EMOJI in message.reactions
    await service.wait_idle()
    assert message.replied_files and message.replied_files[0] is not None
    assert DELIVER_EMOJI in message.reactions
    await service.aclose()


async def test_camera_reaction_container_not_a_room(tmp_path):
    scenario = build_scenario()
    world = scenario.actor.world
    box = spawn_entity(world, [IdentityComponent(name="Box", kind="container")])
    boxed = spawn_entity(
        world,
        [IdentityComponent(name="Boxed", kind="character"), CharacterComponent(species="bunny")],
    )
    box.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), boxed.id)
    assign_discord_controller(scenario.actor, discord_user_id=321, character_name="Boxed")
    service = _service(scenario.actor, tmp_path)
    bot = _bot(scenario, service)
    message = _ReactMessage()
    await bot._on_image_reaction(_reaction(message), _DiscordObject(id=321, bot=False))
    assert message.reactions == []  # the container is not a room
    await service.aclose()


async def test_camera_reaction_swallows_errors(tmp_path):
    scenario = build_scenario()
    assign_discord_controller(scenario.actor, discord_user_id=123, character_name="Juniper")
    service = _service(scenario.actor, tmp_path)
    bot = _bot(scenario, service)
    message = _ReactMessage(fail_reaction=True)
    # add_reaction raises; _on_image_reaction must log and not propagate.
    await bot._on_image_reaction(_reaction(message), _DiscordObject(id=123, bot=False))
    await service.wait_idle()
    await service.aclose()


async def test_deliver_image_unknown_record_is_noop(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    bot = _bot_for_scenario(scenario, imagegen=service, _image_messages={})
    base = {"event_id": "e", "world_epoch": 0}
    from datetime import UTC, datetime

    event = ImageGenerationCompletedEvent(
        entity_id="ghost_1",
        purpose="event",
        url="/media/events/x.png",
        created_at=datetime.now(UTC),
        **base,
    )
    await bot._deliver_image(event)  # no mapped message -> no error


async def test_image_failed_reacts_and_unknown_noop(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    bot = _bot_for_scenario(scenario, imagegen=service, _image_messages={})
    message = _ReactMessage()
    bot._image_messages["rec_1"] = message
    from datetime import UTC, datetime

    failed = ImageGenerationFailedEvent(
        entity_id="rec_1",
        purpose="event",
        reason="boom",
        created_at=datetime.now(UTC),
        event_id="e",
        world_epoch=0,
    )
    await bot._image_failed(failed)
    assert FAIL_EMOJI in message.reactions
    # Unknown record id is a no-op.
    failed_unknown = ImageGenerationFailedEvent(
        entity_id="nope",
        purpose="event",
        reason="boom",
        created_at=datetime.now(UTC),
        event_id="e2",
        world_epoch=0,
    )
    await bot._image_failed(failed_unknown)


def test_scene_record_is_created(tmp_path):
    # Sanity: the reuse path resolves a real history record by its source event id.
    scenario = build_scenario()
    assert history_record_for_event(scenario.actor.world, "discord-scene:none:0") is None


def test_event_image_component_round_trips():
    component = EventImageComponent(url="/media/events/x.png", source_event_id="evt")
    assert component.url == "/media/events/x.png"
