"""Short event-video generation behavior and HTTP capability tests."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from conftest import build_scenario

from bunnyland.core import (
    CharacterComponent,
    ContainmentMode,
    Contains,
    IdentityComponent,
    parse_entity_id,
    spawn_entity,
)
from bunnyland.foundation.history.mechanics import record_world_history
from bunnyland.foundation.media.service import sniff_video_extension
from bunnyland.imagegen.comfyui import ComfyUIGenerator
from bunnyland.imagegen.components import EventImageComponent, EventVideoComponent
from bunnyland.imagegen.config import (
    ComfyUIConfig,
    ImageGenConfig,
    MediaGenConfig,
    VideoGenConfig,
)
from bunnyland.imagegen.events import VideoGenerationCompletedEvent, VideoGenerationFailedEvent
from bunnyland.imagegen.generators import ImageGeneratorProfile, VideoGeneratorProfile
from bunnyland.imagegen.in_memory import InMemoryImageGenerator
from bunnyland.imagegen.media import MediaStore
from bunnyland.imagegen.prompt import CatalogExampleSource, StubPromptEnhancer
from bunnyland.imagegen.scene import request_scene_video
from bunnyland.imagegen.service import ImageGenService
from bunnyland.imagegen.spec import ImagePurpose, MediaKind, WorkflowTemplate
from bunnyland.imagegen.store import WorkflowTemplateStore, default_templates
from bunnyland.imagegen.video_service import VideoGenJob, VideoGenService
from bunnyland.imagegen.wiring import build_media_services
from bunnyland.persistence import WorldMeta
from bunnyland.server import app as server_app
from bunnyland.server.app import create_app
from bunnyland.server.client_ids import CLIENT_ID_HEADER

MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"short-video"


class _VideoClient:
    async def generate(self, graph, *, output_node_id=""):
        return MP4_BYTES


class _InvalidVideoClient:
    async def generate(self, graph, *, output_node_id=""):
        return b"not-a-video"


def _video_template() -> WorkflowTemplate:
    return WorkflowTemplate(
        name="event-video",
        purpose=ImagePurpose.EVENT,
        media=MediaKind.VIDEO,
        width=768,
        height=512,
        graph={"1": {"inputs": {"text": "%PROMPT%"}}},
        output_node_id="9",
    )


def _config(tmp_path, *, video: bool = True, templates_path: str = "") -> MediaGenConfig:
    return MediaGenConfig(
        comfyui=ComfyUIConfig(
            server_url="http://comfy.local",
            templates_path=templates_path,
        ),
        image=ImageGenConfig(generator="in-memory"),
        video=VideoGenConfig(
            generator="comfyui" if video else "",
            profile="event-video" if video else "",
        ),
        media_root=str(tmp_path),
    )


def _service(actor, tmp_path, *, video: bool, client=None) -> VideoGenService:
    assert video
    templates = [*default_templates()]
    templates.append(_video_template())
    config = _config(tmp_path)
    return VideoGenService(
        actor,
        config,
        generator=ComfyUIGenerator(
            client or _VideoClient(), WorkflowTemplateStore(defaults=templates)
        ),
        profile_name="event-video",
        enhancer=StubPromptEnhancer(),
        examples=CatalogExampleSource(),
        media=MediaStore(tmp_path),
    )


def _image_service(actor, tmp_path) -> ImageGenService:
    config = _config(tmp_path, video=False)
    generator = InMemoryImageGenerator()
    return ImageGenService(
        actor,
        config,
        generators={purpose: generator for purpose in ImagePurpose},
        enhancer=StubPromptEnhancer(),
        examples=CatalogExampleSource(),
        media=MediaStore(tmp_path),
    )


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={CLIENT_ID_HEADER: "video-client"},
    )


async def _claim(client: httpx.AsyncClient, character_id: str) -> tuple[str, dict[str, str]]:
    response = await client.post("/v1/play/claims", json={"character_id": character_id})
    return response.json()["id"], {
        CLIENT_ID_HEADER: "video-client",
        "X-Bunnyland-Claim-Secret": response.headers["X-Bunnyland-Claim-Secret"],
    }


async def test_scene_video_combines_recent_room_events_and_persists_mp4(tmp_path):
    scenario = build_scenario()
    for event_id, summary, epoch in (("evt-1", "Juniper waved", 1), ("evt-2", "A bell rang", 2)):
        record_world_history(
            scenario.actor.world,
            source_event_id=event_id,
            summary=summary,
            event_type="test",
            created_at_epoch=epoch,
            location_id=str(scenario.room_a),
        )
    events = []
    scenario.actor.bus.subscribe(VideoGenerationCompletedEvent, events.append)
    service = _service(scenario.actor, tmp_path, video=True)

    job = await request_scene_video(
        scenario.actor, service, character_id=scenario.character, requested_by="player"
    )
    assert job is not None
    await service.wait_idle()

    record_id = parse_entity_id(job.entity_id)
    assert record_id is not None
    record = scenario.actor.world.get_entity(record_id)
    video = record.get_component(EventVideoComponent)
    assert "Juniper waved Then, A bell rang" in video.prompt
    assert video.url.startswith("/v1/public/media/videos/")
    assert video.url.endswith(".mp4")
    assert service.media.read("videos", video.url.rsplit("/", 1)[-1]) == MP4_BYTES
    assert events[0].target_ids == (str(scenario.character),)

    reused = await request_scene_video(
        scenario.actor, service, character_id=scenario.character, requested_by="player"
    )
    assert reused is not None
    assert reused.status == "skipped"
    assert reused.url == video.url
    await service.aclose()


def test_video_container_detection_accepts_mp4_and_webm_only():
    assert sniff_video_extension(MP4_BYTES) == "mp4"
    assert sniff_video_extension(b"\x1aE\xdf\xa3webm") == "webm"
    assert sniff_video_extension(b"not-media") is None


async def test_video_jobs_reject_invalid_requests_and_report_invalid_output(tmp_path):
    scenario = build_scenario()
    failed_events = []
    scenario.actor.bus.subscribe(VideoGenerationFailedEvent, failed_events.append)
    enabled = _service(
        scenario.actor,
        tmp_path / "enabled",
        video=True,
        client=_InvalidVideoClient(),
    )
    job = await request_scene_video(scenario.actor, enabled, character_id=scenario.character)
    assert job is not None
    await enabled.wait_idle()
    assert job.status == "failed"
    assert job.error == "video generator returned an unsupported container"
    assert failed_events[0].reason == job.error
    await enabled.aclose()


async def test_video_service_guards_duplicate_force_lookup_and_restart(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path, video=True)
    assert service.idle is True
    assert service.job("missing") is None
    await VideoGenService.aclose(service)

    record = record_world_history(
        scenario.actor.world,
        source_event_id="video-state",
        summary="Juniper hopped",
        event_type="test",
        created_at_epoch=1,
        location_id=str(scenario.room_a),
    )
    first = await service.start(str(record.id))
    duplicate = await service.start(str(record.id))
    forced = await service.start(str(record.id), force=True)
    assert duplicate.status == "duplicate"
    assert first.status == forced.status == "queued"
    assert service.job(first.job_id) is first
    await service.wait_idle()
    assert forced.status == "succeeded"
    assert scenario.actor.world.get_entity(record.id).has_component(EventVideoComponent)

    completed = asyncio.create_task(asyncio.sleep(0))
    await completed
    service._worker = completed
    service._ensure_worker()
    await service.aclose()


async def test_video_service_handles_unknown_and_vanishing_entities(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path, video=True)
    unknown = await service.start("not-an-id")
    assert unknown.status == "failed"
    assert unknown.error == "unknown entity"

    record = record_world_history(
        scenario.actor.world,
        source_event_id="video-vanish",
        summary="A fleeting scene",
        event_type="test",
        created_at_epoch=1,
        location_id=str(scenario.room_a),
    )
    job = await service.start(str(record.id))
    scenario.actor.world.remove(record.id)
    await service.wait_idle()
    assert job.status == "failed"
    assert job.error == "entity no longer exists"
    direct = VideoGenJob(job_id="direct-invalid", entity_id="not-an-id")
    await service._process(direct)
    assert direct.status == "failed"
    await service.aclose()


async def test_video_service_handles_entity_removed_by_provider_and_prompt_override(tmp_path):
    scenario = build_scenario()
    record = record_world_history(
        scenario.actor.world,
        source_event_id="video-provider-vanish",
        summary="A fleeting scene",
        event_type="test",
        created_at_epoch=1,
        location_id=str(scenario.room_a),
    )

    class RemovingClient:
        async def generate(self, graph, *, output_node_id=""):
            del graph, output_node_id
            scenario.actor.world.remove(record.id)
            return MP4_BYTES

    config = _config(tmp_path)
    config = config.__class__(**{**config.__dict__, "prompt_style": "tag"})
    service = VideoGenService(
        scenario.actor,
        config,
        generator=ComfyUIGenerator(
            RemovingClient(), WorkflowTemplateStore(defaults=[_video_template()])
        ),
        profile_name="event-video",
        enhancer=StubPromptEnhancer(),
        examples=CatalogExampleSource(),
        media=MediaStore(tmp_path),
    )
    job = await service.start(str(record.id), extra="dramatic")
    await service.wait_idle()
    assert job.status == "failed"
    assert job.error == "entity no longer exists"
    VideoGenService._clear_request(scenario.actor.world.get_entity(scenario.character))
    await service.aclose()


async def test_video_service_captures_parent_context(tmp_path, monkeypatch):
    scenario = build_scenario()
    gate = asyncio.Event()

    class BlockingClient:
        async def generate(self, graph, *, output_node_id=""):
            del graph, output_node_id
            await gate.wait()
            return MP4_BYTES

    service = _service(scenario.actor, tmp_path, video=True, client=BlockingClient())
    parent = object()
    monkeypatch.setattr(
        "bunnyland.imagegen.video_service.telemetry.capture_context", lambda: parent
    )
    record = record_world_history(
        scenario.actor.world,
        source_event_id="video-parent",
        summary="A traced scene",
        event_type="test",
        created_at_epoch=1,
        location_id=str(scenario.room_a),
    )
    job = await service.start(str(record.id))
    assert service._parent_contexts[job.job_id] is parent
    gate.set()
    await service.wait_idle()
    await service.aclose()


async def test_image_and_video_provider_queues_run_independently(tmp_path):
    scenario = build_scenario()
    image_started = asyncio.Event()
    video_started = asyncio.Event()
    release = asyncio.Event()

    class ImageGenerator:
        name = "image-provider"

        def resolve_profile(self, purpose, profile_name=""):
            del profile_name
            return ImageGeneratorProfile(name=purpose.value, purpose=purpose)

        async def generate(self, request):
            del request
            image_started.set()
            await release.wait()
            return b"PNG"

    class VideoGenerator:
        name = "video-provider"

        def resolve_video_profile(self, profile_name=""):
            return VideoGeneratorProfile(name=profile_name or "event-video")

        async def generate_video(self, request):
            del request
            video_started.set()
            await release.wait()
            return MP4_BYTES

    config = MediaGenConfig()
    media = MediaStore(tmp_path)
    image = ImageGenService(
        scenario.actor,
        config,
        generators={purpose: ImageGenerator() for purpose in ImagePurpose},
        enhancer=StubPromptEnhancer(),
        examples=CatalogExampleSource(),
        media=media,
    )
    video = VideoGenService(
        scenario.actor,
        config,
        generator=VideoGenerator(),
        profile_name="event-video",
        enhancer=StubPromptEnhancer(),
        examples=CatalogExampleSource(),
        media=media,
    )
    record = record_world_history(
        scenario.actor.world,
        source_event_id="concurrent-video",
        summary="A concurrent scene",
        event_type="test",
        created_at_epoch=1,
        location_id=str(scenario.room_a),
    )
    image_job = await image.start(str(scenario.character), ImagePurpose.PORTRAIT)
    video_job = await video.start(str(record.id))
    await asyncio.wait_for(
        asyncio.gather(image_started.wait(), video_started.wait()), timeout=1
    )
    assert image_job.status == video_job.status == "running"
    release.set()
    await asyncio.gather(image.wait_idle(), video.wait_idle())
    await asyncio.gather(image.aclose(), video.aclose())


async def test_image_and_video_requests_can_share_one_history_record(tmp_path):
    scenario = build_scenario()
    image = _image_service(scenario.actor, tmp_path)
    video = _service(scenario.actor, tmp_path, video=True)
    record = record_world_history(
        scenario.actor.world,
        source_event_id="dual-media",
        summary="A scene worth keeping",
        event_type="test",
        created_at_epoch=1,
        location_id=str(scenario.room_a),
    )
    image_job = await image.start(str(record.id), ImagePurpose.EVENT)
    video_job = await video.start(str(record.id))
    assert image_job.status == video_job.status == "queued"
    await asyncio.gather(image.wait_idle(), video.wait_idle())
    entity = scenario.actor.world.get_entity(record.id)
    assert entity.has_component(EventImageComponent)
    assert entity.has_component(EventVideoComponent)
    await asyncio.gather(image.aclose(), video.aclose())


async def test_scene_video_rejects_invalid_locations_and_reuses_one_room_event(tmp_path):
    scenario = build_scenario()
    service = _service(scenario.actor, tmp_path, video=True)
    assert await request_scene_video(scenario.actor, service, character_id="invalid") is None
    assert await request_scene_video(
        scenario.actor, service, character_id="character:999999"
    ) is None

    stray = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Stray", kind="character"), CharacterComponent(species="bunny")],
    )
    assert await request_scene_video(scenario.actor, service, character_id=stray.id) is None

    box = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Box", kind="container")],
    )
    boxed = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Boxed", kind="character"), CharacterComponent(species="bunny")],
    )
    box.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), boxed.id)
    assert await request_scene_video(scenario.actor, service, character_id=boxed.id) is None

    record_world_history(
        scenario.actor.world,
        source_event_id="event-video:ignored",
        summary="an old generated clip",
        event_type="event-video",
        created_at_epoch=3,
        location_id=str(scenario.room_a),
    )
    single = record_world_history(
        scenario.actor.world,
        source_event_id="evt-single",
        summary="Juniper hopped",
        event_type="test",
        created_at_epoch=2,
        location_id=str(scenario.room_a),
    )
    record_world_history(
        scenario.actor.world,
        source_event_id="evt-other-room",
        summary="something elsewhere",
        event_type="test",
        created_at_epoch=4,
        location_id=str(scenario.room_b),
    )
    job = await request_scene_video(
        scenario.actor, service, character_id=scenario.character
    )
    assert job is not None
    assert job.entity_id == str(single.id)
    await service.wait_idle()
    await service.aclose()


async def test_video_job_fails_when_the_selected_profile_produces_an_image(tmp_path):
    scenario = build_scenario()
    image_profile = _video_template().model_copy(update={"media": MediaKind.IMAGE})
    service = VideoGenService(
        scenario.actor,
        _config(tmp_path),
        generator=ComfyUIGenerator(
            _VideoClient(), WorkflowTemplateStore(defaults=[*default_templates(), image_profile])
        ),
        profile_name=image_profile.name,
        enhancer=StubPromptEnhancer(),
        examples=CatalogExampleSource(),
        media=MediaStore(tmp_path),
    )

    job = await request_scene_video(
        scenario.actor, service, character_id=scenario.character
    )
    assert job is not None
    await service.wait_idle()
    assert job.status == "failed"
    assert job.error == "workflow 'event-video' produces image, not video"
    await service.aclose()


def test_build_service_requires_a_named_event_video_workflow(tmp_path):
    scenario = build_scenario()
    path = tmp_path / "workflows.json"
    path.write_text(json.dumps({"templates": [_video_template().model_dump(mode="json")]}))
    config = _config(tmp_path / "media", templates_path=str(path))

    services = build_media_services(scenario.actor, config)

    assert services.image is not None
    assert services.video is not None


@pytest.mark.parametrize(
    ("template", "message"),
    [
        (None, "unknown workflow template"),
        (
            _video_template().model_copy(update={"purpose": ImagePurpose.PORTRAIT}),
            "video profile .* does not support purpose 'event'",
        ),
        (
            _video_template().model_copy(update={"media": MediaKind.IMAGE}),
            "produces image, not video",
        ),
    ],
)
def test_build_service_rejects_invalid_video_workflow_metadata(tmp_path, template, message):
    path = tmp_path / "workflows.json"
    templates = [] if template is None else [template.model_dump(mode="json")]
    path.write_text(json.dumps({"templates": templates}))
    config = _config(tmp_path, templates_path=str(path))
    config = config.__class__(
        **{
            **config.__dict__,
            "video": VideoGenConfig(
                generator="comfyui",
                profile=template.name if template is not None else "missing-video",
            ),
        }
    )

    with pytest.raises(ValueError, match=message):
        build_media_services(build_scenario().actor, config)


async def test_video_feature_and_player_job_are_independently_optional(tmp_path, monkeypatch):
    disabled_scenario = build_scenario()
    disabled = _image_service(disabled_scenario.actor, tmp_path / "disabled")
    disabled_app = create_app(
        disabled_scenario.actor,
        meta=WorldMeta(seed="moss"),
        imagegen=disabled,
        allow_unauthenticated_embedding=True,
    )
    async with _client(disabled_app) as client:
        features = await client.get("/v1/public/features")
        claim_id, headers = await _claim(client, str(disabled_scenario.character))
        response = await client.post(
            f"/v1/play/claims/{claim_id}/jobs",
            headers=headers,
            json={"kind": "scene_video"},
        )
    assert features.json()["image_generation"] is True
    assert features.json()["video_generation"] is False
    assert response.status_code == 409
    await disabled.aclose()

    enabled_scenario = build_scenario()
    enabled_image = _image_service(enabled_scenario.actor, tmp_path / "enabled")
    enabled = _service(enabled_scenario.actor, tmp_path / "enabled", video=True)
    enabled_app = create_app(
        enabled_scenario.actor,
        meta=WorldMeta(seed="moss"),
        imagegen=enabled_image,
        videogen=enabled,
        allow_unauthenticated_embedding=True,
    )
    async with _client(enabled_app) as client:
        features = await client.get("/v1/public/features")
        claim_id, headers = await _claim(client, str(enabled_scenario.character))
        response = await client.post(
            f"/v1/play/claims/{claim_id}/jobs",
            headers=headers,
            json={"kind": "scene_video"},
        )
        await enabled.wait_idle()
        async def no_scene_video(*_args, **_kwargs):
            return None

        monkeypatch.setattr(server_app, "request_scene_video", no_scene_video)
        no_room = await client.post(
            f"/v1/play/claims/{claim_id}/jobs",
            headers=headers,
            json={"kind": "scene_video"},
        )
    assert features.json()["video_generation"] is True
    assert response.status_code == 202
    assert response.json()["kind"] == "scene_video"
    assert no_room.status_code == 400
    assert no_room.json()["detail"] == "character has no room to illustrate"
    await enabled.aclose()
    await enabled_image.aclose()
