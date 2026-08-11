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
    EventVisibility,
    IdentityComponent,
    event_base,
    parse_entity_id,
    spawn_entity,
)
from bunnyland.core.events import SpeechSaidEvent
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
from bunnyland.llm_agents.agent import ChatAgentReply
from bunnyland.llm_agents.tools import ToolCall
from bunnyland.persistence import WorldMeta
from bunnyland.prompts.builder import PromptBuilder
from bunnyland.server import app as server_app
from bunnyland.server.app import create_app
from bunnyland.server.character_chat import MEDIA_ACTION_WARNING, CharacterChatService
from bunnyland.server.chat_media import (
    CHAT_MEDIA_CONTEXT_CHARS,
    capture_chat_media_scene,
    chat_media_prompt_context,
    chat_media_tool,
)
from bunnyland.server.client_ids import CLIENT_ID_HEADER
from bunnyland.server.models import CharacterChatHistoryMessage, ChatMediaCreativeDirection

MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"short-video"


class _VideoClient:
    async def generate(self, graph, *, output_node_id=""):
        return MP4_BYTES


class _InvalidVideoClient:
    async def generate(self, graph, *, output_node_id=""):
        return b"not-a-video"


def _video_template(*, default_negative: str = "") -> WorkflowTemplate:
    return WorkflowTemplate(
        name="event-video",
        purpose=ImagePurpose.EVENT,
        media=MediaKind.VIDEO,
        width=768,
        height=512,
        graph={"1": {"inputs": {"text": "%PROMPT%"}}},
        output_node_id="9",
        default_negative=default_negative,
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
    service = _service(scenario.actor, tmp_path, video=True)
    for event_id, text, epoch in (
        ("evt-1", "Juniper waved", 1),
        ("evt-2", "A bell rang", 2),
    ):
        await scenario.actor.bus.publish(
            SpeechSaidEvent(
                **event_base(
                    epoch,
                    event_id=event_id,
                    visibility=EventVisibility.ROOM,
                    actor_id=str(scenario.character),
                    room_id=str(scenario.room_a),
                ),
                text=text,
            )
        )
    events = []
    scenario.actor.bus.subscribe(VideoGenerationCompletedEvent, events.append)

    job = await request_scene_video(
        scenario.actor, service, character_id=scenario.character, requested_by="player"
    )
    assert job is not None
    await service.wait_idle()

    record_id = parse_entity_id(job.entity_id)
    assert record_id is not None
    record = scenario.actor.world.get_entity(record_id)
    video = record.get_component(EventVideoComponent)
    assert "A bell rang" in video.prompt
    assert "Juniper waved" in video.prompt
    assert "Mosslit Burrow" in video.prompt
    assert video.source_event_id == "evt-2"
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


async def test_ephemeral_chat_media_uses_one_pipeline_without_mutating_world(tmp_path):
    scenario = build_scenario()
    image = _image_service(scenario.actor, tmp_path)
    video = _service(scenario.actor, tmp_path, video=True)
    entity_count = len(list(scenario.actor.world.query().execute_entities()))
    image_subject, image_scene = await capture_chat_media_scene(
        scenario.actor, image, scenario.character
    )
    video_subject, video_scene = await capture_chat_media_scene(
        scenario.actor, video, scenario.character
    )

    image_job = await image.start_ephemeral(
        str(scenario.character),
        subject=image_subject,
        scene=image_scene,
        extra="Visual focus: Juniper. Fictional scene action: Juniper dances.",
    )
    video_job = await video.start_ephemeral(
        str(scenario.character),
        subject=video_subject,
        scene=video_scene,
        extra="Visual focus: Juniper. Fictional scene action: Juniper dances.",
    )
    await image.wait_idle()
    await video.wait_idle()

    character = scenario.actor.world.get_entity(scenario.character)
    assert image_job.status == "succeeded"
    assert video_job.status == "succeeded"
    assert not character.has_component(EventImageComponent)
    assert not character.has_component(EventVideoComponent)
    assert len(list(scenario.actor.world.query().execute_entities())) == entity_count
    assert image_job.source_event_id == ""
    assert video_job.source_event_id == ""
    await image.aclose()
    await video.aclose()


async def test_video_profile_default_negative_is_used_when_enhancer_omits_it(tmp_path):
    scenario = build_scenario()
    requests = []

    class CapturingGenerator:
        name = "capturing-video"

        def resolve_video_profile(self, profile_name=""):
            return VideoGeneratorProfile(
                name=profile_name or "event-video",
                default_negative="watermark, text",
            )

        async def generate_video(self, request):
            requests.append(request)
            return MP4_BYTES

    service = VideoGenService(
        scenario.actor,
        _config(tmp_path),
        generator=CapturingGenerator(),
        profile_name="event-video",
        enhancer=StubPromptEnhancer(),
        examples=CatalogExampleSource(),
        media=MediaStore(tmp_path),
    )
    record = record_world_history(
        scenario.actor.world,
        source_event_id="default-negative",
        summary="A gate opens",
        event_type="test",
        created_at_epoch=1,
        location_id=str(scenario.room_a),
    )
    job = await service.start(str(record.id))
    await service.wait_idle()
    assert job.status == "succeeded"
    assert requests[0].negative == "watermark, text"
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

    event = SpeechSaidEvent(
        **event_base(
            2,
            event_id="evt-single",
            visibility=EventVisibility.ROOM,
            actor_id=str(scenario.character),
            room_id=str(scenario.room_a),
        ),
        text="Juniper hopped",
    )
    await scenario.actor.bus.publish(event)
    job = await request_scene_video(
        scenario.actor, service, character_id=scenario.character
    )
    assert job is not None
    await service.wait_idle()
    assert job.source_event_id == event.event_id
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
        unknown_event = await client.post(
            f"/v1/play/claims/{claim_id}/jobs",
            headers=headers,
            json={"kind": "scene_video", "event_id": "event:unknown"},
        )
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
    assert unknown_event.status_code == 400
    assert "unknown or expired" in unknown_event.json()["detail"]
    assert no_room.status_code == 400
    assert no_room.json()["detail"] == "character has no room to illustrate"
    await enabled.aclose()
    await enabled_image.aclose()


async def test_player_chat_image_and_video_share_private_media_job_pipeline(
    tmp_path, monkeypatch
):
    scenario = build_scenario()
    monkeypatch.setenv(server_app.SCENE_IMAGE_RATE_LIMIT_REQUESTS_ENV, "2")
    image = _image_service(scenario.actor, tmp_path)
    video = _service(scenario.actor, tmp_path, video=True)

    class ChatService:
        allow_sleeping_character_chat = False

    app = create_app(
        scenario.actor,
        meta=WorldMeta(seed="moss"),
        imagegen=image,
        videogen=video,
        character_chat=ChatService(),
        character_chat_media_tools=True,
        allow_unauthenticated_embedding=True,
    )
    payload = {
        "focus": "Juniper's delighted expression",
        "history": [
            {"role": "user", "text": "Shall we dance?"},
            {"role": "character", "text": "Under these lanterns, absolutely."},
        ],
    }
    async with _client(app) as client:
        features = await client.get("/v1/public/features")
        image_response = await client.post(
            f"/v1/chat/characters/{scenario.character}/media-jobs",
            json={"kind": "chat_image", **payload},
        )
        video_response = await client.post(
            f"/v1/chat/characters/{scenario.character}/media-jobs",
            json={
                "kind": "chat_video",
                "scene_action": "Juniper twirls; this is only an illustration.",
                **payload,
            },
        )
        limited = await client.post(
            f"/v1/chat/characters/{scenario.character}/media-jobs",
            json={"kind": "chat_image", **payload},
        )
        invalid = await client.post(
            "/v1/chat/characters/not-a-character/media-jobs",
            headers={CLIENT_ID_HEADER: "other-video-client"},
            json={"kind": "chat_image", **payload},
        )
        await image.wait_idle()
        await video.wait_idle()
        image_job = await client.get(
            f"/v1/chat/characters/{scenario.character}/media-jobs/"
            f"{image_response.json()['id']}"
        )
        video_job = await client.get(
            f"/v1/chat/characters/{scenario.character}/media-jobs/"
            f"{video_response.json()['id']}"
        )
        wrong_owner = await client.get(
            f"/v1/chat/characters/{scenario.character}/media-jobs/"
            f"{image_response.json()['id']}",
            headers={CLIENT_ID_HEADER: "other-video-client"},
        )
        missing = await client.get(
            f"/v1/chat/characters/{scenario.character}/media-jobs/missing"
        )

    assert features.json()["chat_image_generation"] is True
    assert features.json()["chat_video_generation"] is True
    assert features.json()["character_chat_media_tools"] is True
    assert image_response.status_code == 202
    assert video_response.status_code == 202
    assert image_response.headers["location"].endswith(image_response.json()["id"])
    assert limited.status_code == 429
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "character does not exist"
    assert wrong_owner.status_code == 404
    assert missing.status_code == 404
    assert image_job.json()["status"] == "succeeded"
    assert image_job.json()["result"]["url"].endswith(".png")
    assert image_job.json()["result"]["enhanced_prompt"]
    assert video_job.json()["status"] == "succeeded"
    assert video_job.json()["result"]["url"].endswith(".mp4")
    assert video_job.json()["result"]["enhanced_prompt"]
    assert not scenario.actor.world.get_entity(scenario.character).has_component(
        EventImageComponent
    )
    assert not scenario.actor.world.get_entity(scenario.character).has_component(
        EventVideoComponent
    )
    await image.aclose()
    await video.aclose()

    disabled = create_app(
        scenario.actor,
        imagegen=image,
        allow_unauthenticated_embedding=True,
    )
    async with _client(disabled) as client:
        unavailable = await client.post(
            f"/v1/chat/characters/{scenario.character}/media-jobs",
            json={"kind": "chat_image"},
        )
    assert unavailable.status_code == 404
    assert unavailable.json()["detail"] == "character chat is not enabled"


async def test_chat_media_context_validation_bounding_and_ephemeral_job_guards(
    tmp_path, monkeypatch
):
    scenario = build_scenario()
    image = _image_service(scenario.actor, tmp_path / "images")
    video = _service(scenario.actor, tmp_path / "videos", video=True)
    subject, scene = await capture_chat_media_scene(
        scenario.actor, image, scenario.character
    )
    assert "Juniper" in subject

    with pytest.raises(ValueError, match="character does not exist"):
        await capture_chat_media_scene(scenario.actor, image, "not-an-id")
    with pytest.raises(TypeError, match="not a character"):
        await capture_chat_media_scene(scenario.actor, image, scenario.room_a)
    stray = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Stray", kind="character"), CharacterComponent()],
    )
    with pytest.raises(ValueError, match="has no room"):
        await capture_chat_media_scene(scenario.actor, image, stray.id)
    box = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Box", kind="container")],
    )
    boxed = spawn_entity(
        scenario.actor.world,
        [IdentityComponent(name="Boxed", kind="character"), CharacterComponent()],
    )
    box.add_relationship(Contains(mode=ContainmentMode.ROOM_CONTENT), boxed.id)
    with pytest.raises(ValueError, match="has no room"):
        await capture_chat_media_scene(scenario.actor, image, boxed.id)

    direction = ChatMediaCreativeDirection(
        focus="Juniper",
        scene_action="Juniper imagines dancing",
        mood="joyful",
        composition="wide shot",
        style_notes="storybook",
    )
    context = chat_media_prompt_context(
        history_summary="They discussed lanterns.",
        history=[
            CharacterChatHistoryMessage(role="user", text="Shall we dance?"),
            CharacterChatHistoryMessage(role="character", text=" "),
        ],
        direction=direction,
        current_message="Show me.",
    )
    assert MEDIA_ACTION_WARNING not in context
    assert "Fictional scene action: Juniper imagines dancing" in context
    assert "Conversation summary:" in context
    assert "Human now: Show me." in context
    no_transcript = chat_media_prompt_context(
        history_summary="",
        history=[],
        direction=ChatMediaCreativeDirection(),
    )
    assert no_transcript == (
        "Illustrate the private conversation below while preserving the trusted world scene."
    )
    bounded = chat_media_prompt_context(
        history_summary="",
        history=[
            CharacterChatHistoryMessage(role="character", text=str(index) + "x" * 3_999)
            for index in range(4)
        ],
        direction=ChatMediaCreativeDirection(),
    )
    assert len(bounded) <= CHAT_MEDIA_CONTEXT_CHARS
    assert MEDIA_ACTION_WARNING not in bounded
    with pytest.raises(ValueError, match="chat media kind"):
        chat_media_tool("audio", lambda *_args: None)

    for service in (image, video):
        invalid = await service.start_ephemeral(
            "missing:character",
            subject="Nobody",
            scene=scene,
        )
        assert invalid.status == "failed"
        assert invalid.error == "unknown entity"

    parent = object()
    monkeypatch.setattr("bunnyland.telemetry.capture_context", lambda: parent)
    monkeypatch.setattr(image, "_ensure_worker", lambda: None)
    monkeypatch.setattr(video, "_ensure_worker", lambda: None)
    queued_image = await image.start_ephemeral(
        str(scenario.character), subject=subject, scene=scene
    )
    queued_video = await video.start_ephemeral(
        str(scenario.character), subject=subject, scene=scene
    )
    assert image._parent_contexts[queued_image.job_id] is parent
    assert video._parent_contexts[queued_video.job_id] is parent
    await image.aclose()
    await video.aclose()


async def test_opted_in_character_chat_uses_the_same_media_job_pipeline(
    tmp_path, monkeypatch
):
    scenario = build_scenario()
    monkeypatch.setenv(server_app.SCENE_IMAGE_RATE_LIMIT_REQUESTS_ENV, "1")
    image = _image_service(scenario.actor, tmp_path)

    class MediaRequestingAgent:
        def __init__(self):
            self.calls = []

        async def chat(
            self,
            messages,
            *,
            character_id,
            model=None,
            provider=None,
            tools=None,
        ):
            del character_id, model, provider
            self.calls.append((messages, tools or []))
            if len(self.calls) % 2 == 1:
                return ChatAgentReply(
                    tool_call=ToolCall(
                        "request_chat_image",
                        {
                            "focus": "Juniper's scarf",
                            "scene_action": "Juniper imagines leaping over a lantern",
                        },
                    )
                )
            return ChatAgentReply(content="I pictured the leap for you.")

    agent = MediaRequestingAgent()
    chat = CharacterChatService(
        scenario.actor,
        PromptBuilder(scenario.actor.world),
        agent,
    )
    app = create_app(
        scenario.actor,
        meta=WorldMeta(seed="moss"),
        imagegen=image,
        character_chat=chat,
        character_chat_media_tools=True,
        allow_unauthenticated_embedding=True,
    )
    async with _client(app) as client:
        submitted = await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            json={
                "kind": "chat",
                "message": "Show me how you imagine it.",
                "allow_character_media": True,
            },
        )
        outer = submitted.json()
        for _attempt in range(40):
            outer_response = await client.get(
                f"/v1/chat/characters/{scenario.character}/jobs/{outer['id']}"
            )
            outer = outer_response.json()
            if outer["status"] not in {"queued", "running"}:
                break
            await asyncio.sleep(0.01)
        await image.wait_idle()
        media = outer["result"]["action"]["media_job"]
        media_response = await client.get(
            f"/v1/chat/characters/{scenario.character}/media-jobs/{media['id']}"
        )
        limited_response = await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            json={
                "kind": "chat",
                "message": "Show me another.",
                "allow_character_media": True,
            },
        )
        limited = limited_response.json()
        for _attempt in range(40):
            limited = (
                await client.get(
                    f"/v1/chat/characters/{scenario.character}/jobs/{limited['id']}"
                )
            ).json()
            if limited["status"] not in {"queued", "running"}:
                break
            await asyncio.sleep(0.01)

        async def invalid_scene(*_args, **_kwargs):
            raise ValueError("scene is unavailable")

        monkeypatch.setattr(server_app, "capture_chat_media_scene", invalid_scene)
        alternate_headers = {CLIENT_ID_HEADER: "alternate-video-client"}
        invalid_response = await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            headers=alternate_headers,
            json={
                "kind": "chat",
                "message": "Show me one more.",
                "allow_character_media": True,
            },
        )
        invalid = invalid_response.json()
        for _attempt in range(40):
            invalid = (
                await client.get(
                    f"/v1/chat/characters/{scenario.character}/jobs/{invalid['id']}",
                    headers=alternate_headers,
                )
            ).json()
            if invalid["status"] not in {"queued", "running"}:
                break
            await asyncio.sleep(0.01)

    tool = next(
        item["function"]
        for item in agent.calls[0][1]
        if item["function"]["name"] == "request_chat_image"
    )
    assert MEDIA_ACTION_WARNING in tool["description"]
    assert outer["status"] == "succeeded"
    assert outer["result"]["reply"] == "I pictured the leap for you."
    assert media_response.json()["status"] == "succeeded"
    assert media_response.json()["result"]["url"].endswith(".png")
    assert media_response.json()["result"]["enhanced_prompt"]
    assert limited["result"]["action"]["status"] == "rejected"
    assert limited["result"]["action"]["reason"] == "chat media rate limit exceeded"
    assert invalid["result"]["action"]["status"] == "rejected"
    assert invalid["result"]["action"]["reason"] == "scene is unavailable"
    assert not scenario.actor.world.get_entity(scenario.character).has_component(
        EventImageComponent
    )
    await image.aclose()


async def test_opted_in_character_can_request_video_when_only_video_is_enabled(tmp_path):
    scenario = build_scenario()
    video = _service(scenario.actor, tmp_path, video=True)

    class VideoRequestingAgent:
        def __init__(self):
            self.calls = 0

        async def chat(
            self,
            messages,
            *,
            character_id,
            model=None,
            provider=None,
            tools=None,
        ):
            del messages, character_id, model, provider
            self.calls += 1
            if self.calls == 1:
                names = {
                    item["function"]["name"]
                    for item in tools or []
                    if item["function"]["name"].startswith("request_chat_")
                }
                assert names == {"request_chat_video"}
                return ChatAgentReply(
                    tool_call=ToolCall(
                        "request_chat_video",
                        {"focus": "Juniper", "scene_action": "Juniper waves"},
                    )
                )
            return ChatAgentReply(content="Here is how I imagine the wave.")

    chat = CharacterChatService(
        scenario.actor,
        PromptBuilder(scenario.actor.world),
        VideoRequestingAgent(),
    )
    app = create_app(
        scenario.actor,
        meta=WorldMeta(seed="moss"),
        videogen=video,
        character_chat=chat,
        character_chat_media_tools=True,
        allow_unauthenticated_embedding=True,
    )
    async with _client(app) as client:
        response = await client.post(
            f"/v1/chat/characters/{scenario.character}/jobs",
            json={"kind": "chat", "message": "Wave.", "allow_character_media": True},
        )
        outer = response.json()
        for _attempt in range(40):
            outer = (
                await client.get(
                    f"/v1/chat/characters/{scenario.character}/jobs/{outer['id']}"
                )
            ).json()
            if outer["status"] not in {"queued", "running"}:
                break
            await asyncio.sleep(0.01)
        media = outer["result"]["action"]["media_job"]
        await video.wait_idle()
        result = await client.get(
            f"/v1/chat/characters/{scenario.character}/media-jobs/{media['id']}"
        )

    assert media["kind"] == "chat_video"
    assert result.json()["result"]["url"].endswith(".mp4")
    await video.aclose()
