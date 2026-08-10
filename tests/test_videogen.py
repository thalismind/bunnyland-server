"""Short event-video generation behavior and HTTP capability tests."""

from __future__ import annotations

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
from bunnyland.imagegen.components import EventVideoComponent
from bunnyland.imagegen.config import ImageGenConfig
from bunnyland.imagegen.events import VideoGenerationCompletedEvent, VideoGenerationFailedEvent
from bunnyland.imagegen.media import MediaStore
from bunnyland.imagegen.prompt import CatalogExampleSource, StubPromptEnhancer
from bunnyland.imagegen.scene import request_scene_video
from bunnyland.imagegen.service import ImageGenError, ImageGenService
from bunnyland.imagegen.spec import ImagePurpose, MediaKind, WorkflowTemplate
from bunnyland.imagegen.store import WorkflowTemplateStore, default_templates
from bunnyland.imagegen.wiring import build_image_service
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


def _service(actor, tmp_path, *, video: bool, client=None) -> ImageGenService:
    templates = [*default_templates()]
    if video:
        templates.append(_video_template())
    return ImageGenService(
        actor,
        ImageGenConfig(
            server_url="http://comfy.local",
            video_template="event-video" if video else "",
        ),
        client=client or _VideoClient(),
        templates=WorkflowTemplateStore(defaults=templates),
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
    disabled = _service(scenario.actor, tmp_path / "disabled", video=False)
    with pytest.raises(ImageGenError, match="video generation is not configured"):
        await disabled.start("missing:one", ImagePurpose.EVENT, media=MediaKind.VIDEO)
    with pytest.raises(ImageGenError, match="video generation is not configured"):
        await disabled.start("missing:one", ImagePurpose.PORTRAIT, media=MediaKind.VIDEO)
    await disabled.aclose()

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
    assert job.error == "ComfyUI returned an unsupported video container"
    assert failed_events[0].reason == job.error
    await enabled.aclose()


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
    service = ImageGenService(
        scenario.actor,
        ImageGenConfig(server_url="http://comfy.local", video_template=image_profile.name),
        client=_VideoClient(),
        templates=WorkflowTemplateStore(defaults=[*default_templates(), image_profile]),
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
    config = ImageGenConfig(
        server_url="http://comfy.local",
        generator="in-memory",
        media_root=str(tmp_path / "media"),
        templates_path=str(path),
        video_template="event-video",
    )

    service = build_image_service(scenario.actor, config)

    assert service.video_enabled is True


@pytest.mark.parametrize(
    ("template", "message"),
    [
        (None, "unknown video workflow template"),
        (
            _video_template().model_copy(update={"purpose": ImagePurpose.PORTRAIT}),
            "video workflow template must have purpose 'event'",
        ),
        (
            _video_template().model_copy(update={"media": MediaKind.IMAGE}),
            "video workflow template must declare media 'video'",
        ),
    ],
)
def test_build_service_rejects_invalid_video_workflow_metadata(tmp_path, template, message):
    path = tmp_path / "workflows.json"
    templates = [] if template is None else [template.model_dump(mode="json")]
    path.write_text(json.dumps({"templates": templates}))
    config = ImageGenConfig(
        server_url="http://comfy.local",
        generator="in-memory",
        templates_path=str(path),
        video_template=template.name if template is not None else "missing-video",
    )

    with pytest.raises(ValueError, match=message):
        build_image_service(build_scenario().actor, config)


async def test_video_feature_and_player_job_are_independently_optional(tmp_path, monkeypatch):
    disabled_scenario = build_scenario()
    disabled = _service(disabled_scenario.actor, tmp_path / "disabled", video=False)
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
    enabled = _service(enabled_scenario.actor, tmp_path / "enabled", video=True)
    enabled_app = create_app(
        enabled_scenario.actor,
        meta=WorldMeta(seed="moss"),
        imagegen=enabled,
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
