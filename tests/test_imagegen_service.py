"""Tests for the background image generation service and subject assembly."""

from __future__ import annotations

from conftest import build_scenario

from bunnyland.core import spawn_entity
from bunnyland.core.components import DescriptionComponent, IdentityComponent
from bunnyland.core.ecs import container_of
from bunnyland.core.events import DomainEvent
from bunnyland.imagegen.components import (
    EventImageComponent,
    ImageRequestComponent,
    PortraitImageComponent,
)
from bunnyland.imagegen.config import ImageGenConfig
from bunnyland.imagegen.events import (
    ImageGenerationCompletedEvent,
    ImageGenerationFailedEvent,
)
from bunnyland.imagegen.media import SEGMENT_PORTRAITS, MediaStore
from bunnyland.imagegen.prompt import CatalogExampleSource, StubPromptEnhancer
from bunnyland.imagegen.service import (
    ImageGenService,
    _clear_request,
    _existing_image_url,
    _first_missing_portrait,
    _first_missing_sprite,
    _seed_for,
)
from bunnyland.imagegen.spec import ImagePurpose
from bunnyland.imagegen.store import WorkflowTemplateStore, default_templates
from bunnyland.imagegen.subject import subject_for_entity, subject_for_event
from bunnyland.mechanics.history import record_world_history
from bunnyland.mechanics.toonsim import SpriteImage


class _FakeClient:
    def __init__(self, *, data=b"PNG", error=None):
        self.data = data
        self.error = error
        self.graphs: list[dict] = []

    async def generate(self, graph, *, output_node_id=""):
        self.graphs.append(graph)
        if self.error is not None:
            raise self.error
        return self.data


def _service(actor, tmp_path, *, client=None) -> ImageGenService:
    return ImageGenService(
        actor,
        ImageGenConfig(server_url="http://comfy.local"),
        client=client or _FakeClient(),
        templates=WorkflowTemplateStore(defaults=default_templates()),
        enhancer=StubPromptEnhancer(),
        examples=CatalogExampleSource(),
        media=MediaStore(tmp_path),
    )


def _capture(actor) -> list[DomainEvent]:
    events: list[DomainEvent] = []
    actor.bus.subscribe(DomainEvent, events.append)
    return events


# --- subject assembly ----------------------------------------------------------------


def test_subject_for_entity_uses_appearance():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(DescriptionComponent(short="a bunny", appearance="grey fur, red scarf"))
    text = subject_for_entity(character)
    assert "Juniper" in text
    assert "grey fur, red scarf" in text


def test_subject_for_entity_falls_back_to_short():
    scenario = build_scenario()
    character = scenario.actor.world.get_entity(scenario.character)
    character.add_component(DescriptionComponent(short="a small bunny"))
    assert "a small bunny" in subject_for_entity(character)


def test_subject_for_entity_minimal():
    scenario = build_scenario()
    # A bare entity: no identity, no kind, no description.
    bare = spawn_entity(scenario.actor.world, [])
    assert subject_for_entity(bare) == str(bare.id)


def test_subject_for_entity_blank_kind_no_description():
    scenario = build_scenario()
    entity = spawn_entity(scenario.actor.world, [IdentityComponent(name="Thing", kind="")])
    assert subject_for_entity(entity) == "Thing"


def test_subject_for_entity_blank_description_text():
    scenario = build_scenario()
    entity = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Blank", kind="thing"), DescriptionComponent(short="")],
    )
    # Description present but every text field empty: nothing extra appended.
    assert subject_for_entity(entity) == "Blank, thing"


def test_subject_for_event_empty_room_and_no_tags():
    scenario = build_scenario()
    world = scenario.actor.world
    record = record_world_history(
        world,
        source_event_id="evt-empty",
        summary="A quiet moment",
        event_type="quiet",
        created_at_epoch=0,
        location_id=str(scenario.room_b),  # north tunnel: empty, no members
    )
    text = subject_for_event(world, record)
    assert "North Tunnel" in text
    assert "present:" not in text
    assert "themes:" not in text


def test_subject_for_event_non_room_location():
    scenario = build_scenario()
    world = scenario.actor.world
    # Point the record's location at a non-room entity.
    record = record_world_history(
        world,
        source_event_id="evt-odd",
        summary="An odd event",
        event_type="odd",
        created_at_epoch=0,
        location_id=str(scenario.character),
    )
    text = subject_for_event(world, record)
    assert "An odd event" in text
    assert "in " not in text  # the location is not a room, so no room title


def test_subject_for_event_includes_room_and_members():
    scenario = build_scenario()
    world = scenario.actor.world
    room_id = container_of(world.get_entity(scenario.character))
    record = record_world_history(
        world,
        source_event_id="evt-1",
        summary="A grand feast",
        event_type="feast",
        created_at_epoch=0,
        location_id=str(room_id),
        tags=("celebration",),
    )
    text = subject_for_event(world, record)
    assert "A grand feast" in text
    assert "Mosslit Burrow" in text
    assert "Juniper" in text
    assert "celebration" in text


def test_subject_for_event_without_location():
    scenario = build_scenario()
    world = scenario.actor.world
    record = record_world_history(
        world,
        source_event_id="evt-2",
        summary="Something happened somewhere",
        event_type="misc",
        created_at_epoch=0,
    )
    assert subject_for_event(world, record) == "Something happened somewhere"


# --- service: portrait ---------------------------------------------------------------


async def test_start_generates_and_attaches_portrait(tmp_path):
    scenario = build_scenario()
    events = _capture(scenario.actor)
    client = _FakeClient(data=b"PORTRAIT")
    service = _service(scenario.actor, tmp_path, client=client)

    job = await service.start(str(scenario.character), ImagePurpose.PORTRAIT)
    assert job.status == "queued"
    await service.wait_idle()

    entity = scenario.actor.world.get_entity(scenario.character)
    portrait = entity.get_component(PortraitImageComponent)
    assert portrait.url.startswith("/media/portraits/")
    assert portrait.seed == _seed_for(str(scenario.character))
    assert not entity.has_component(ImageRequestComponent)  # cleared
    # File written and a completion event emitted.
    segment, name = portrait.url.split("/")[2:4]
    assert MediaStore(tmp_path).read(SEGMENT_PORTRAITS, name) == b"PORTRAIT"
    assert any(isinstance(e, ImageGenerationCompletedEvent) for e in events)
    await service.aclose()


async def test_start_reuses_existing_image(tmp_path):
    scenario = build_scenario()
    entity = scenario.actor.world.get_entity(scenario.character)
    entity.add_component(PortraitImageComponent(url="/media/portraits/old.png"))
    service = _service(scenario.actor, tmp_path)

    job = await service.start(str(scenario.character), ImagePurpose.PORTRAIT)
    assert job.status == "skipped"
    assert job.url == "/media/portraits/old.png"


async def test_start_force_regenerates(tmp_path):
    scenario = build_scenario()
    entity = scenario.actor.world.get_entity(scenario.character)
    entity.add_component(PortraitImageComponent(url="/media/portraits/old.png"))
    service = _service(scenario.actor, tmp_path)

    job = await service.start(str(scenario.character), ImagePurpose.PORTRAIT, force=True)
    await service.wait_idle()
    new_url = scenario.actor.world.get_entity(scenario.character).get_component(
        PortraitImageComponent
    ).url
    assert new_url != "/media/portraits/old.png"
    assert job.status in {"queued", "running", "succeeded"}
    await service.aclose()


async def test_start_unknown_entity(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    job = await service.start("nonsense_99", ImagePurpose.PORTRAIT)
    assert job.status == "failed"
    assert job.error == "unknown entity"


async def test_start_duplicate_when_in_flight(tmp_path):
    scenario = build_scenario()
    entity = scenario.actor.world.get_entity(scenario.character)
    entity.add_component(ImageRequestComponent(purpose="portrait"))
    service = _service(scenario.actor, tmp_path)
    job = await service.start(str(scenario.character), ImagePurpose.PORTRAIT)
    assert job.status == "duplicate"


# --- service: sprite + event ---------------------------------------------------------


async def test_start_sprite_sets_sprite_image(tmp_path):
    scenario = build_scenario()
    entity = scenario.actor.world.get_entity(scenario.character)
    entity.add_component(SpriteImage())  # toonsim backfilled, empty url
    service = _service(scenario.actor, tmp_path)

    await service.start(str(scenario.character), ImagePurpose.SPRITE)
    await service.wait_idle()
    sprite = scenario.actor.world.get_entity(scenario.character).get_component(SpriteImage)
    assert sprite.url.startswith("/media/sprites/")
    await service.aclose()


async def test_start_event_attaches_event_image(tmp_path):
    scenario = build_scenario()
    world = scenario.actor.world
    room_id = container_of(world.get_entity(scenario.character))
    record = record_world_history(
        world,
        source_event_id="evt-7",
        summary="A duel at dawn",
        event_type="duel",
        created_at_epoch=0,
        location_id=str(room_id),
    )
    service = _service(scenario.actor, tmp_path)

    await service.start(str(record.id), ImagePurpose.EVENT)
    await service.wait_idle()
    image = world.get_entity(record.id).get_component(EventImageComponent)
    assert image.url.startswith("/media/events/")
    assert image.source_event_id == "evt-7"
    await service.aclose()


# --- service: failures ---------------------------------------------------------------


async def test_failed_generation_emits_event_and_clears_request(tmp_path):
    scenario = build_scenario()
    events = _capture(scenario.actor)
    service = _service(scenario.actor, tmp_path, client=_FakeClient(error=RuntimeError("boom")))

    await service.start(str(scenario.character), ImagePurpose.PORTRAIT)
    await service.wait_idle()
    entity = scenario.actor.world.get_entity(scenario.character)
    assert not entity.has_component(PortraitImageComponent)
    assert not entity.has_component(ImageRequestComponent)
    failed = [e for e in events if isinstance(e, ImageGenerationFailedEvent)]
    assert failed and failed[0].reason == "boom"
    # The failed character is parked so the backfill won't retry it forever.
    assert str(scenario.character) in service._failed
    assert await service.enqueue_one_missing() is None
    await service.aclose()


async def test_backfill_recovers_after_failure_clears(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    service._failed.add(str(scenario.character))  # previously failed -> parked
    assert await service.enqueue_one_missing() is None
    # A successful generation discards the entity from the failed set.
    service._failed.discard(str(scenario.character))
    job = await service.enqueue_one_missing()
    assert job is not None
    await service.wait_idle()
    assert str(scenario.character) not in service._failed
    await service.aclose()


async def test_unknown_template_fails(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    job = await service.start(
        str(scenario.character), ImagePurpose.PORTRAIT, template_name="ghost"
    )
    await service.wait_idle()
    assert job.status == "failed"
    assert "unknown workflow template" in job.error
    await service.aclose()


async def test_no_template_for_purpose_fails(tmp_path):
    scenario = build_scenario()
    service = ImageGenService(
        scenario.actor,
        ImageGenConfig(server_url="http://comfy.local"),
        client=_FakeClient(),
        templates=WorkflowTemplateStore(),  # no defaults registered
        enhancer=StubPromptEnhancer(),
        examples=CatalogExampleSource(),
        media=MediaStore(tmp_path),
    )
    job = await service.start(str(scenario.character), ImagePurpose.PORTRAIT)
    await service.wait_idle()
    assert job.status == "failed"
    assert "no workflow template" in job.error
    await service.aclose()


async def test_entity_vanishes_before_processing(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    # Mark in-flight manually, then enqueue against a now-removed entity id.
    character_id = scenario.character
    job = await service.start(str(character_id), ImagePurpose.PORTRAIT)
    # Remove the entity before the worker runs its locked read.
    scenario.actor.world.remove(character_id)
    await service.wait_idle()
    assert job.status == "failed"
    assert "no longer exists" in job.error
    await service.aclose()


# --- service: backfill picker --------------------------------------------------------


async def test_enqueue_one_missing_picks_portrait(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    job = await service.enqueue_one_missing()
    assert job is not None
    assert job.purpose is ImagePurpose.PORTRAIT
    await service.wait_idle()
    assert scenario.actor.world.get_entity(scenario.character).has_component(
        PortraitImageComponent
    )
    await service.aclose()


async def test_enqueue_one_missing_returns_none_when_busy(tmp_path):
    import asyncio

    scenario = build_scenario()
    gate = asyncio.Event()

    class _BlockingClient:
        async def generate(self, graph, *, output_node_id=""):
            await gate.wait()
            return b"PNG"

    service = _service(scenario.actor, tmp_path, client=_BlockingClient())
    await service.start(str(scenario.character), ImagePurpose.PORTRAIT)
    await asyncio.sleep(0)  # let the worker pick the job up (now busy)
    assert service.idle is False
    assert await service.enqueue_one_missing() is None
    gate.set()
    await service.wait_idle()
    await service.aclose()


async def test_enqueue_one_missing_picks_sprite_when_portrait_done(tmp_path):
    scenario = build_scenario()
    entity = scenario.actor.world.get_entity(scenario.character)
    entity.add_component(PortraitImageComponent(url="/media/portraits/x.png"))
    entity.add_component(SpriteImage())  # empty url -> needs a sprite
    service = _service(scenario.actor, tmp_path)
    job = await service.enqueue_one_missing()
    assert job is not None
    assert job.purpose is ImagePurpose.SPRITE
    await service.wait_idle()
    await service.aclose()


async def test_enqueue_one_missing_none_when_all_done(tmp_path):
    scenario = build_scenario()
    entity = scenario.actor.world.get_entity(scenario.character)
    entity.add_component(PortraitImageComponent(url="/media/portraits/x.png"))
    service = _service(scenario.actor, tmp_path)
    assert await service.enqueue_one_missing() is None


def test_job_lookup(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    assert service.job("missing") is None


async def test_aclose_without_worker_is_noop(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    await service.aclose()  # never started a worker


async def test_named_template_resolves(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path)
    job = await service.start(
        str(scenario.character), ImagePurpose.PORTRAIT, template_name="portrait"
    )
    await service.wait_idle()
    assert job.status == "succeeded"
    await service.aclose()


async def test_two_jobs_reuse_one_worker(tmp_path):
    scenario = build_scenario()
    other = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Bramble", kind="character")],
    )
    from bunnyland.core import CharacterComponent

    other.add_component(CharacterComponent(species="bunny"))
    service = _service(scenario.actor, tmp_path)
    await service.start(str(scenario.character), ImagePurpose.PORTRAIT)
    await service.start(str(other.id), ImagePurpose.PORTRAIT)
    await service.wait_idle()
    assert scenario.actor.world.get_entity(other.id).has_component(PortraitImageComponent)
    await service.aclose()


def test_existing_image_url_all_purposes():
    scenario = build_scenario()
    entity = scenario.actor.world.get_entity(scenario.character)
    # No images yet.
    assert _existing_image_url(entity, ImagePurpose.SPRITE) == ""
    assert _existing_image_url(entity, ImagePurpose.EVENT) == ""
    assert _existing_image_url(entity, ImagePurpose.PORTRAIT) == ""
    entity.add_component(SpriteImage(url="/media/sprites/s.png"))
    entity.add_component(EventImageComponent(url="/media/events/e.png"))
    entity.add_component(PortraitImageComponent(url="/media/portraits/p.png"))
    assert _existing_image_url(entity, ImagePurpose.SPRITE) == "/media/sprites/s.png"
    assert _existing_image_url(entity, ImagePurpose.EVENT) == "/media/events/e.png"
    assert _existing_image_url(entity, ImagePurpose.ENTITY) == "/media/portraits/p.png"


def test_clear_request_both_branches():
    scenario = build_scenario()
    entity = scenario.actor.world.get_entity(scenario.character)
    _clear_request(entity)  # no request component: no-op
    entity.add_component(ImageRequestComponent(purpose="portrait"))
    _clear_request(entity)
    assert not entity.has_component(ImageRequestComponent)


def test_first_missing_sprite_skips_filled_sprites():
    scenario = build_scenario()
    entity = scenario.actor.world.get_entity(scenario.character)
    entity.add_component(SpriteImage(url="/media/sprites/done.png"))
    # Only character already has a sprite url, so nothing is missing.
    assert _first_missing_sprite(scenario.actor, set()) is None


def test_first_missing_portrait_skips_failed_set():
    scenario = build_scenario()
    # The only character is in the skip set, so the picker finds nothing.
    assert _first_missing_portrait(scenario.actor, {str(scenario.character)}) is None
    assert _first_missing_portrait(scenario.actor, set()) is not None


def test_first_missing_sprite_skips_failed_set():
    scenario = build_scenario()
    entity = scenario.actor.world.get_entity(scenario.character)
    entity.add_component(SpriteImage())  # empty url -> needs a sprite
    assert _first_missing_sprite(scenario.actor, {str(scenario.character)}) is None
